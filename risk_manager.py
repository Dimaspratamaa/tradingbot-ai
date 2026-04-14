# ============================================
# RISK MANAGER v1.0
# Modul manajemen risiko cerdas untuk bot v9.7
# Fitur:
#   1. Dynamic Stop Loss (sesuai volatilitas)
#   2. BTC Market Filter (block saat BTC dump)
#   3. Early Exit Signal (exit sebelum kena SL)
#   4. Session Filter (entry saat volume tinggi)
# ============================================

import time
import pandas as pd
import numpy as np
from datetime import datetime, timezone

# ── KONFIGURASI DYNAMIC SL ────────────────────
ATR_MULT_NORMAL   = 1.5   # SL normal
ATR_MULT_VOLATILE = 2.5   # SL saat market volatile
ATR_MULT_CALM     = 1.2   # SL saat market tenang
VOLATILITY_HIGH   = 3.0   # ATR% > 3% = volatile
VOLATILITY_LOW    = 1.0   # ATR% < 1% = calm

# ── KONFIGURASI BTC FILTER ────────────────────
BTC_DROP_1H       = -1.5  # BTC turun >1.5% per jam = block
BTC_DROP_4H       = -3.0  # BTC turun >3% per 4 jam = block kuat
BTC_VOLUME_RATIO  = 2.0   # Volume BTC 2x rata2 = ada pergerakan besar

# ── KONFIGURASI EARLY EXIT ────────────────────
EXIT_RSI_OVERBOUGHT = 72   # RSI > 72 = mulai pertimbangkan exit
EXIT_PROFIT_MIN     = 0.8  # Minimal profit 0.8% sebelum early exit
EXIT_MACD_KONFIRM   = True # Butuh MACD cross down untuk konfirmasi

# ── KONFIGURASI SESSION FILTER ────────────────
# Jam dalam UTC (server Railway)
SESSION_AKTIF = [
    # Asia session (Tokyo + Shanghai open)
    (0, 3),    # 00:00 - 03:00 UTC = 07:00-10:00 WIB
    # London session
    (7, 10),   # 07:00 - 10:00 UTC = 14:00-17:00 WIB
    # US session (paling volatile)
    (13, 17),  # 13:00 - 17:00 UTC = 20:00-00:00 WIB
    # US overlap dengan London
    (12, 16),
]
VOLUME_MIN_RATIO  = 1.2   # Volume minimal 1.2x rata-rata untuk entry

# ── CACHE BTC ─────────────────────────────────
_btc_cache = {"data": None, "waktu": 0, "ttl": 120}  # Cache 2 menit

# ══════════════════════════════════════════════
# 1. DYNAMIC STOP LOSS
# ══════════════════════════════════════════════

def hitung_dynamic_sl(harga, atr, df_1h=None):
    """
    Hitung Stop Loss dinamis berdasarkan volatilitas pasar.

    Args:
        harga  : harga entry
        atr    : ATR dari timeframe 1H
        df_1h  : dataframe 1H untuk analisis volatilitas lebih lanjut

    Return dict:
        sl          : float (harga stop loss)
        tp          : float (harga take profit)
        sl_pct      : float (persentase SL dari entry)
        tp_pct      : float (persentase TP dari entry)
        multiplier  : float (ATR multiplier yang dipakai)
        kondisi     : str (VOLATILE/NORMAL/CALM)
        alasan      : str
    """
    atr_pct    = (atr / harga) * 100
    multiplier = ATR_MULT_NORMAL
    kondisi    = "NORMAL"
    alasan     = "Volatilitas normal"

    # Analisis volatilitas tambahan dari df jika tersedia
    if df_1h is not None:
        try:
            # Hitung ATR 7 periode terakhir vs 20 periode
            high  = df_1h['high']
            low   = df_1h['low']
            close = df_1h['close']
            tr    = pd.concat([
                high - low,
                (high - close.shift()).abs(),
                (low  - close.shift()).abs()
            ], axis=1).max(axis=1)

            atr_7  = tr.rolling(7).mean().iloc[-1]
            atr_20 = tr.rolling(20).mean().iloc[-1]

            # Jika ATR terkini jauh lebih tinggi dari rata2 = sangat volatile
            volatility_ratio = atr_7 / atr_20 if atr_20 > 0 else 1.0

            if volatility_ratio > 1.5 or atr_pct > VOLATILITY_HIGH:
                multiplier = ATR_MULT_VOLATILE
                kondisi    = "VOLATILE"
                alasan     = f"Market volatile (ATR {atr_pct:.1f}%, ratio {volatility_ratio:.1f}x)"
            elif volatility_ratio < 0.7 and atr_pct < VOLATILITY_LOW:
                multiplier = ATR_MULT_CALM
                kondisi    = "CALM"
                alasan     = f"Market tenang (ATR {atr_pct:.1f}%)"
            else:
                multiplier = ATR_MULT_NORMAL
                kondisi    = "NORMAL"
                alasan     = f"Volatilitas normal (ATR {atr_pct:.1f}%)"

        except Exception as e:
            print(f"  ⚠️  Dynamic SL calc error: {e}")

    else:
        # Fallback hanya dari atr_pct
        if atr_pct > VOLATILITY_HIGH:
            multiplier = ATR_MULT_VOLATILE
            kondisi    = "VOLATILE"
            alasan     = f"ATR tinggi ({atr_pct:.1f}%)"
        elif atr_pct < VOLATILITY_LOW:
            multiplier = ATR_MULT_CALM
            kondisi    = "CALM"
            alasan     = f"ATR rendah ({atr_pct:.1f}%)"

    sl     = harga - (atr * multiplier)
    tp     = harga + (atr * multiplier * 2.0)  # RR 1:2
    sl_pct = ((harga - sl) / harga) * 100
    tp_pct = ((tp - harga) / harga) * 100

    return {
        "sl"        : sl,
        "tp"        : tp,
        "sl_pct"    : round(sl_pct, 2),
        "tp_pct"    : round(tp_pct, 2),
        "multiplier": multiplier,
        "kondisi"   : kondisi,
        "alasan"    : alasan,
        "atr_pct"   : round(atr_pct, 2)
    }

# ══════════════════════════════════════════════
# 2. BTC MARKET FILTER
# ══════════════════════════════════════════════

def get_btc_kondisi(client):
    """
    Analisis kondisi BTC untuk filter market.
    Cache 2 menit agar tidak spam API.

    Return dict:
        boleh_entry  : bool
        kondisi      : str
        btc_change_1h: float
        btc_change_4h: float
        alasan       : str
        skor_market  : int (-3 to +3)
    """
    global _btc_cache
    sekarang = time.time()

    if (_btc_cache["data"] is not None and
            sekarang - _btc_cache["waktu"] < _btc_cache["ttl"]):
        return _btc_cache["data"]

    try:
        # Ambil data BTC 1H dan 4H
        klines_1h = client.get_klines(
            symbol="BTCUSDT",
            interval="1h",
            limit=10
        )
        klines_4h = client.get_klines(
            symbol="BTCUSDT",
            interval="4h",
            limit=5
        )

        # Hitung perubahan harga
        close_1h      = [float(k[4]) for k in klines_1h]
        close_4h      = [float(k[4]) for k in klines_4h]
        volume_1h     = [float(k[5]) for k in klines_1h]

        btc_now       = close_1h[-1]
        btc_1h_ago    = close_1h[-2]
        btc_4h_ago    = close_4h[-2] if len(close_4h) >= 2 else close_4h[-1]

        change_1h     = ((btc_now - btc_1h_ago) / btc_1h_ago) * 100
        change_4h     = ((btc_now - btc_4h_ago) / btc_4h_ago) * 100

        # Cek volume BTC
        vol_avg       = np.mean(volume_1h[:-1])
        vol_sekarang  = volume_1h[-1]
        vol_ratio     = vol_sekarang / vol_avg if vol_avg > 0 else 1.0

        # ── Tentukan kondisi ──
        skor_market  = 0
        alasan_list  = []

        # BTC 1H
        if change_1h < BTC_DROP_1H:
            skor_market -= 2
            alasan_list.append(f"BTC -1H: {change_1h:.2f}%")
        elif change_1h > 1.5:
            skor_market += 1
            alasan_list.append(f"BTC +1H: {change_1h:.2f}%")

        # BTC 4H
        if change_4h < BTC_DROP_4H:
            skor_market -= 2
            alasan_list.append(f"BTC -4H: {change_4h:.2f}%")
        elif change_4h > 3.0:
            skor_market += 1
            alasan_list.append(f"BTC +4H: {change_4h:.2f}%")

        # Volume tinggi saat turun = selling pressure kuat
        if vol_ratio > BTC_VOLUME_RATIO and change_1h < 0:
            skor_market -= 1
            alasan_list.append(f"Vol tinggi saat turun ({vol_ratio:.1f}x)")

        # ── Tentukan boleh entry atau tidak ──
        if skor_market <= -3:
            kondisi    = "BEARISH_KUAT"
            boleh_entry = False
        elif skor_market <= -2:
            kondisi    = "BEARISH"
            boleh_entry = False
        elif skor_market <= -1:
            kondisi    = "SEDIKIT_BEARISH"
            boleh_entry = True   # Boleh tapi waspada
        elif skor_market >= 2:
            kondisi    = "BULLISH"
            boleh_entry = True
        else:
            kondisi    = "NETRAL"
            boleh_entry = True

        alasan = " | ".join(alasan_list) if alasan_list else "BTC stabil"

        hasil = {
            "boleh_entry"  : boleh_entry,
            "kondisi"      : kondisi,
            "btc_change_1h": round(change_1h, 3),
            "btc_change_4h": round(change_4h, 3),
            "vol_ratio"    : round(vol_ratio, 2),
            "btc_harga"    : btc_now,
            "skor_market"  : skor_market,
            "alasan"       : alasan
        }

        _btc_cache["data"]  = hasil
        _btc_cache["waktu"] = sekarang
        return hasil

    except Exception as e:
        print(f"  ⚠️  BTC filter error: {e}")
        return {
            "boleh_entry"  : True,   # Default: boleh entry jika error
            "kondisi"      : "UNKNOWN",
            "btc_change_1h": 0,
            "btc_change_4h": 0,
            "vol_ratio"    : 1.0,
            "btc_harga"    : 0,
            "skor_market"  : 0,
            "alasan"       : "Data BTC tidak tersedia"
        }

# ══════════════════════════════════════════════
# 3. EARLY EXIT SIGNAL
# ══════════════════════════════════════════════

def cek_early_exit(symbol, pos, client):
    """
    Cek apakah sebaiknya exit lebih awal sebelum kena SL.
    Dipanggil di setiap siklus untuk posisi aktif.

    Args:
        symbol: trading pair
        pos   : dict posisi aktif
        client: binance client

    Return dict:
        exit_sekarang: bool
        alasan       : str
        profit_pct   : float
    """
    try:
        # Ambil harga terkini
        ticker = client.get_symbol_ticker(symbol=symbol)
        harga  = float(ticker["price"])

        harga_beli = pos.get("harga_beli") or pos.get("entry", harga)
        profit_pct = ((harga - harga_beli) / harga_beli) * 100

        # Jangan exit jika masih profit tipis atau rugi (biarkan SL yang handle)
        if profit_pct < EXIT_PROFIT_MIN:
            return {
                "exit_sekarang": False,
                "alasan"       : f"Profit belum cukup ({profit_pct:.2f}%)",
                "profit_pct"   : profit_pct
            }

        # Ambil data terbaru untuk analisis
        klines = client.get_klines(
            symbol=symbol, interval="1h", limit=30)
        df = pd.DataFrame(klines, columns=[
            'time','open','high','low','close','volume',
            'close_time','quote_vol','trades',
            'taker_base','taker_quote','ignore'
        ])
        for col in ['open','high','low','close','volume']:
            df[col] = df[col].astype(float)

        close = df['close']

        # ── Sinyal reversal untuk early exit ──
        sinyal_exit = []

        # 1. RSI Overbought
        delta = close.diff()
        gain  = delta.where(delta > 0, 0).rolling(14).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi   = (100 - (100 / (1 + gain / loss))).iloc[-1]

        if rsi > EXIT_RSI_OVERBOUGHT:
            sinyal_exit.append(f"RSI overbought ({rsi:.0f})")

        # 2. MACD cross down
        ema12       = close.ewm(span=12, adjust=False).mean()
        ema26       = close.ewm(span=26, adjust=False).mean()
        macd_line   = ema12 - ema26
        signal_line = macd_line.ewm(span=9, adjust=False).mean()
        macd_cross_down = (
            macd_line.iloc[-1] < signal_line.iloc[-1] and
            macd_line.iloc[-2] >= signal_line.iloc[-2]
        )
        if macd_cross_down:
            sinyal_exit.append("MACD cross DOWN")

        # 3. Bearish divergence
        harga_r  = close.iloc[-5:].values
        rsi_ser  = 100 - (100 / (1 + gain / loss))
        rsi_r    = rsi_ser.iloc[-5:].values
        bear_div = harga_r[-1] > harga_r[0] and rsi_r[-1] < rsi_r[0]
        if bear_div:
            sinyal_exit.append("Bearish divergence")

        # 4. Momentum negatif
        momentum = ((harga - close.iloc[-7]) / close.iloc[-7]) * 100
        if momentum < -2:
            sinyal_exit.append(f"Momentum negatif ({momentum:.1f}%)")

        # 5. Volume turun saat harga naik (weak rally)
        vol_avg   = df['volume'].rolling(10).mean().iloc[-1]
        vol_skrng = df['volume'].iloc[-1]
        if vol_skrng < vol_avg * 0.6 and profit_pct > 1.5:
            sinyal_exit.append("Volume lemah di puncak")

        # ── Keputusan exit ──
        n_sinyal = len(sinyal_exit)

        # Exit jika ada 2+ sinyal reversal DAN sudah profit
        if n_sinyal >= 2 and profit_pct >= EXIT_PROFIT_MIN:
            return {
                "exit_sekarang": True,
                "alasan"       : f"Early exit: {' | '.join(sinyal_exit)}",
                "profit_pct"   : profit_pct,
                "sinyal"       : sinyal_exit
            }

        # Exit jika RSI sangat overbought + MACD turun
        if rsi > 80 and macd_cross_down and profit_pct > 0:
            return {
                "exit_sekarang": True,
                "alasan"       : f"RSI ekstrem ({rsi:.0f}) + MACD turun",
                "profit_pct"   : profit_pct,
                "sinyal"       : sinyal_exit
            }

        return {
            "exit_sekarang": False,
            "alasan"       : f"Posisi aman ({n_sinyal} sinyal, profit {profit_pct:.2f}%)",
            "profit_pct"   : profit_pct,
            "sinyal"       : sinyal_exit
        }

    except Exception as e:
        print(f"  ⚠️  Early exit check error {symbol}: {e}")
        return {
            "exit_sekarang": False,
            "alasan"       : f"Error: {e}",
            "profit_pct"   : 0
        }

# ══════════════════════════════════════════════
# 4. SESSION FILTER
# ══════════════════════════════════════════════

def cek_session_aktif(client=None, symbol="BTCUSDT"):
    """
    Cek apakah saat ini adalah waktu trading yang baik.
    Berdasarkan jam sesi + volume pasar.

    Return dict:
        aktif      : bool
        sesi       : str (ASIA/LONDON/US/OFF)
        jam_utc    : int
        alasan     : str
        vol_ratio  : float
    """
    sekarang_utc = datetime.now(timezone.utc)
    jam_utc      = sekarang_utc.hour
    menit_utc    = sekarang_utc.minute

    # ── Tentukan sesi ──
    sesi = "OFF"
    if 0 <= jam_utc < 4:
        sesi = "ASIA"
    elif 7 <= jam_utc < 12:
        sesi = "LONDON"
    elif 12 <= jam_utc < 17:
        sesi = "US_OPEN"
    elif 17 <= jam_utc < 21:
        sesi = "US_AFTERNOON"
    else:
        sesi = "QUIET"   # 21:00 - 00:00 UTC = sepi

    # ── Cek apakah dalam jam aktif ──
    dalam_session = False
    for start, end in SESSION_AKTIF:
        if start <= jam_utc < end:
            dalam_session = True
            break

    # ── Cek volume aktual jika client tersedia ──
    vol_ratio = 1.0
    vol_info  = ""

    if client and symbol:
        try:
            klines = client.get_klines(
                symbol=symbol, interval="1h", limit=25)
            volumes    = [float(k[5]) for k in klines]
            vol_avg    = np.mean(volumes[:-1])
            vol_skrng  = volumes[-1]
            vol_ratio  = vol_skrng / vol_avg if vol_avg > 0 else 1.0
            vol_info   = f", Vol:{vol_ratio:.1f}x"
        except:
            pass

    # ── Volume rendah = pasar sepi, tidak entry ──
    volume_ok = vol_ratio >= VOLUME_MIN_RATIO

    # Gabungkan: harus dalam session DAN volume cukup
    aktif  = dalam_session and volume_ok

    # Edge case: jika volume sangat tinggi, masuk session manapun
    if vol_ratio > 2.5:
        aktif = True
        sesi  = f"{sesi}+BREAKOUT"

    alasan_list = []
    if tidak := not dalam_session:
        alasan_list.append(f"Di luar jam trading ({sesi}, {jam_utc:02d}:{menit_utc:02d} UTC)")
    if not volume_ok:
        alasan_list.append(f"Volume rendah ({vol_ratio:.1f}x < {VOLUME_MIN_RATIO}x)")
    if aktif:
        alasan_list = [f"Sesi {sesi} aktif{vol_info}"]

    return {
        "aktif"    : aktif,
        "sesi"     : sesi,
        "jam_utc"  : jam_utc,
        "vol_ratio": round(vol_ratio, 2),
        "alasan"   : " | ".join(alasan_list) if alasan_list else "OK",
        "jam_wib"  : f"{(jam_utc + 7) % 24:02d}:{menit_utc:02d} WIB"
    }

# ══════════════════════════════════════════════
# FUNGSI UTAMA: VALIDASI ENTRY
# ══════════════════════════════════════════════

def validasi_entry(symbol, skor, client, df_1h=None):
    """
    Validasi komprehensif sebelum buka posisi baru.
    Gabungkan semua filter: BTC, Session, Skor minimum.

    Return dict:
        boleh      : bool
        alasan     : list[str]
        btc        : dict
        session    : dict
        warning    : list[str]
    """
    alasan  = []
    warning = []
    boleh   = True

    # 1. Cek BTC market condition
    btc = get_btc_kondisi(client)

    if not btc["boleh_entry"]:
        boleh = False
        alasan.append(f"❌ BTC {btc['kondisi']}: {btc['alasan']}")
    elif btc["skor_market"] < 0:
        warning.append(f"⚠️ BTC sedikit bearish ({btc['alasan']})")

    # 2. Cek session
    session = cek_session_aktif(client, symbol)

    if not session["aktif"]:
        boleh = False
        alasan.append(f"❌ Session: {session['alasan']}")
    else:
        if session["vol_ratio"] < 1.5:
            warning.append(f"⚠️ Volume sedang ({session['vol_ratio']:.1f}x)")

    # 3. Skor minimum (sudah dicek di bot utama, tapi double-check)
    if skor < 6:
        boleh = False
        alasan.append(f"❌ Skor {skor} < minimum 6")

    if boleh and not alasan:
        alasan.append(
            f"✅ Entry OK | BTC:{btc['kondisi']} | "
            f"Sesi:{session['sesi']} | Vol:{session['vol_ratio']:.1f}x"
        )

    return {
        "boleh"  : boleh,
        "alasan" : alasan,
        "warning": warning,
        "btc"    : btc,
        "session": session
    }

def print_kondisi_market(client):
    """Print kondisi market saat ini untuk monitoring"""
    btc     = get_btc_kondisi(client)
    session = cek_session_aktif(client)

    btc_em  = "🟢" if btc["boleh_entry"] else "🔴"
    ses_em  = "🟢" if session["aktif"] else "🔴"

    print(f"  {btc_em} BTC  : {btc['kondisi']} | "
          f"1H:{btc['btc_change_1h']:+.2f}% | "
          f"4H:{btc['btc_change_4h']:+.2f}%")
    print(f"  {ses_em} Sesi : {session['sesi']} | "
          f"{session['jam_wib']} | "
          f"Vol:{session['vol_ratio']:.1f}x")

    if not btc["boleh_entry"]:
        print(f"  🚫 Entry DIBLOKIR: {btc['alasan']}")
    if not session["aktif"]:
        print(f"  🚫 Sesi tidak aktif: {session['alasan']}")


# ============================================
# RISK MANAGER v2.0 UPGRADE
# Tambahan fitur manajemen risiko profesional
#
# Fitur baru:
#   5.  Volatility Regime Detection
#   6.  Risk/Reward Enforcer
#   7.  Position Heat Calculator
#   8.  Consecutive Loss Detector
#   9.  Correlation Risk Guard
#   10. Spread/Slippage Guard
#   11. Liquidation Distance Check (Futures)
#   12. Drawdown Per-Posisi Tracker
#   13. Risk-Adjusted Position Sizing
# ============================================

import json
import pathlib

RISK_STATE_FILE = pathlib.Path(__file__).parent / "risk_state.json"

# ── KONFIGURASI v2.0 ──────────────────────────
MIN_RR_RATIO          = 1.5    # Minimal Risk:Reward ratio sebelum entry
MAX_HEAT_PCT          = 0.15   # Max 15% saldo dalam risiko sekaligus
MAX_CORRELATION       = 0.80   # Blokir jika korelasi posisi baru > 0.8
MAX_SPREAD_PCT        = 0.15   # Spread > 0.15% = terlalu lebar
CONSEC_LOSS_THRESHOLD = 3      # Setelah 3 loss berturut → kurangi sizing
CONSEC_LOSS_REDUCTION = 0.50   # Kurangi 50% sizing setelah consecutive loss
VOLATILITY_STORM_ATR  = 5.0    # ATR% > 5% = kondisi storm, stop entry
LIQIDATION_BUFFER_PCT = 20.0   # Futures: min 20% jarak dari liquidasi


# ══════════════════════════════════════════════
# 5. VOLATILITY REGIME DETECTION
# ══════════════════════════════════════════════

def deteksi_volatility_regime(df_1h):
    """
    Deteksi regime volatilitas pasar: CALM, NORMAL, ELEVATED, STORM.

    Setiap regime punya implikasi berbeda:
    - CALM    : ATR% < 1%    → SL ketat, sizing normal
    - NORMAL  : ATR% 1-3%    → Parameter standar
    - ELEVATED: ATR% 3-5%    → SL lebih lebar, sizing dikurangi 25%
    - STORM   : ATR% > 5%    → STOP ENTRY semua posisi baru

    Return dict:
        regime      : str
        atr_pct     : float
        sl_multiplier: float (faktor kali untuk SL)
        size_factor  : float (faktor kali untuk sizing)
        boleh_entry  : bool
        alasan       : str
    """
    try:
        close  = df_1h["close"].astype(float)
        high   = df_1h["high"].astype(float)
        low    = df_1h["low"].astype(float)

        # Hitung ATR 14
        tr = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs()
        ], axis=1).max(axis=1)
        atr     = tr.rolling(14).mean().iloc[-1]
        atr_pct = (atr / close.iloc[-1]) * 100

        # Hitung volatilitas 24H terakhir vs 7 hari
        ret_24h = close.pct_change().tail(24).std() * 100
        ret_7d  = close.pct_change().tail(168).std() * 100
        vol_ratio = ret_24h / (ret_7d + 1e-10)

        # Tentukan regime
        if atr_pct > VOLATILITY_STORM_ATR:
            return {
                "regime"       : "STORM",
                "atr_pct"      : round(atr_pct, 3),
                "vol_ratio"    : round(vol_ratio, 2),
                "sl_multiplier": 3.0,
                "size_factor"  : 0.0,
                "boleh_entry"  : False,
                "alasan"       : f"ATR {atr_pct:.1f}% terlalu tinggi (STORM mode)"
            }
        elif atr_pct > 3.0:
            return {
                "regime"       : "ELEVATED",
                "atr_pct"      : round(atr_pct, 3),
                "vol_ratio"    : round(vol_ratio, 2),
                "sl_multiplier": 2.0,
                "size_factor"  : 0.75,
                "boleh_entry"  : True,
                "alasan"       : f"Volatilitas tinggi — sizing dikurangi 25%"
            }
        elif atr_pct < 1.0:
            return {
                "regime"       : "CALM",
                "atr_pct"      : round(atr_pct, 3),
                "vol_ratio"    : round(vol_ratio, 2),
                "sl_multiplier": 1.2,
                "size_factor"  : 1.0,
                "boleh_entry"  : True,
                "alasan"       : "Pasar tenang — SL ketat"
            }
        else:
            return {
                "regime"       : "NORMAL",
                "atr_pct"      : round(atr_pct, 3),
                "vol_ratio"    : round(vol_ratio, 2),
                "sl_multiplier": 1.5,
                "size_factor"  : 1.0,
                "boleh_entry"  : True,
                "alasan"       : "Volatilitas normal"
            }
    except Exception as e:
        return {
            "regime": "NORMAL", "atr_pct": 2.0, "vol_ratio": 1.0,
            "sl_multiplier": 1.5, "size_factor": 1.0,
            "boleh_entry": True, "alasan": f"Error: {e}"
        }


# ══════════════════════════════════════════════
# 6. RISK/REWARD ENFORCER
# ══════════════════════════════════════════════

def cek_risk_reward(harga_entry, sl, tp, min_rr=MIN_RR_RATIO):
    """
    Pastikan setiap trade punya R:R minimal sebelum entry.

    Contoh: Entry $100, SL $98 (risiko $2), TP $104 (reward $4)
    R:R = 4/2 = 2.0 → bagus (> 1.5)

    Return dict:
        rr_ratio  : float
        bagus     : bool
        risk_pct  : float (% yang dirisikokan)
        reward_pct: float (% yang diharapkan)
        alasan    : str
    """
    if harga_entry <= 0 or sl <= 0 or tp <= 0:
        return {"rr_ratio": 0, "bagus": False,
                "risk_pct": 0, "reward_pct": 0,
                "alasan": "Harga tidak valid"}

    risk_pct   = abs(harga_entry - sl) / harga_entry * 100
    reward_pct = abs(tp - harga_entry) / harga_entry * 100

    if risk_pct < 0.01:
        return {"rr_ratio": 0, "bagus": False,
                "risk_pct": risk_pct, "reward_pct": reward_pct,
                "alasan": "SL terlalu dekat"}

    rr_ratio = reward_pct / risk_pct
    bagus    = rr_ratio >= min_rr

    return {
        "rr_ratio"  : round(rr_ratio, 2),
        "bagus"     : bagus,
        "risk_pct"  : round(risk_pct, 3),
        "reward_pct": round(reward_pct, 3),
        "alasan"    : (f"R:R {rr_ratio:.2f} ✅" if bagus
                       else f"R:R {rr_ratio:.2f} terlalu rendah (min {min_rr})")
    }


# ══════════════════════════════════════════════
# 7. POSITION HEAT CALCULATOR
# ══════════════════════════════════════════════

def hitung_position_heat(posisi_spot, posisi_futures,
                          saldo_total, harga_dict=None):
    """
    Ukur total 'heat' (risiko) portfolio saat ini.

    Heat = total modal yang berisiko jika semua SL kena.
    Max heat 15% — jika lebih, blokir entry baru.

    Return dict:
        total_heat_usd : float
        heat_pct       : float (% dari saldo)
        terlalu_panas  : bool
        detail_posisi  : list
        rekomendasi    : str
    """
    detail   = []
    total_heat = 0.0
    total_exposure = 0.0

    # Spot positions
    for sym, pos in posisi_spot.items():
        if not pos.get("aktif"):
            continue
        modal   = pos.get("modal", 0)
        sl_pct  = abs(pos.get("harga_beli", 1) - pos.get("stop_loss", 0)) / pos.get("harga_beli", 1) * 100
        heat    = modal * (sl_pct / 100)
        total_heat     += heat
        total_exposure += modal
        detail.append({
            "symbol" : sym,
            "modal"  : round(modal, 2),
            "sl_pct" : round(sl_pct, 2),
            "heat"   : round(heat, 2),
            "tipe"   : "SPOT"
        })

    # Futures positions
    try:
        from futures_engine import posisi_futures, LEVERAGE
        for sym, pos in posisi_futures.items():
            if not pos.get("aktif"):
                continue
            modal  = pos.get("modal", 0)
            # Futures: risiko lebih besar karena leverage
            sl_pct = abs(pos.get("harga_beli", 1) - pos.get("stop_loss", 0)) / pos.get("harga_beli", 1) * 100
            heat   = modal * (sl_pct / 100) * LEVERAGE
            total_heat     += heat
            total_exposure += modal
            detail.append({
                "symbol" : sym,
                "modal"  : round(modal, 2),
                "sl_pct" : round(sl_pct, 2),
                "heat"   : round(heat, 2),
                "tipe"   : "FUTURES"
            })
    except Exception:
        pass

    if saldo_total <= 0:
        heat_pct = 0.0
    else:
        heat_pct = (total_heat / saldo_total) * 100

    terlalu_panas = heat_pct > MAX_HEAT_PCT * 100

    if terlalu_panas:
        rekomendasi = f"BLOKIR entry baru — heat {heat_pct:.1f}% > max {MAX_HEAT_PCT*100:.0f}%"
    elif heat_pct > MAX_HEAT_PCT * 75:
        rekomendasi = f"Hati-hati — heat {heat_pct:.1f}% mendekati batas"
    else:
        rekomendasi = f"Aman — heat {heat_pct:.1f}% dari max {MAX_HEAT_PCT*100:.0f}%"

    return {
        "total_heat_usd" : round(total_heat, 2),
        "total_exposure" : round(total_exposure, 2),
        "heat_pct"       : round(heat_pct, 2),
        "terlalu_panas"  : terlalu_panas,
        "detail_posisi"  : detail,
        "rekomendasi"    : rekomendasi
    }


# ══════════════════════════════════════════════
# 8. CONSECUTIVE LOSS DETECTOR
# ══════════════════════════════════════════════

def _load_risk_state():
    if RISK_STATE_FILE.exists():
        try:
            return json.loads(RISK_STATE_FILE.read_text())
        except Exception:
            pass
    return {
        "konsekutif_loss" : 0,
        "total_loss_hari" : 0,
        "total_profit_hari": 0,
        "last_result"     : None,
        "last_update"     : "",
        "loss_streak_start": "",
    }

def _save_risk_state(state):
    state["last_update"] = time.strftime("%Y-%m-%d %H:%M:%S")
    RISK_STATE_FILE.write_text(json.dumps(state, indent=2))

def update_loss_tracker(profit_pct, symbol=""):
    """
    Update tracker setelah setiap trade selesai.
    Dipanggil dari simpan_transaksi().
    """
    state = _load_risk_state()

    # Reset harian jika hari berganti
    hari_ini = time.strftime("%Y-%m-%d")
    if state.get("last_update", "")[:10] != hari_ini:
        state["total_loss_hari"]   = 0
        state["total_profit_hari"] = 0

    if profit_pct > 0:
        state["konsekutif_loss"]   = 0
        state["total_profit_hari"] += profit_pct
        state["last_result"]       = "WIN"
    else:
        state["konsekutif_loss"]   += 1
        state["total_loss_hari"]   += abs(profit_pct)
        state["last_result"]       = "LOSS"
        if state["konsekutif_loss"] == CONSEC_LOSS_THRESHOLD:
            state["loss_streak_start"] = time.strftime("%Y-%m-%d %H:%M:%S")
            print(f"  ⚠️  {CONSEC_LOSS_THRESHOLD} loss berturut! Sizing dikurangi {int(CONSEC_LOSS_REDUCTION*100)}%")

    _save_risk_state(state)
    return state

def get_sizing_factor():
    """
    Return faktor pengali sizing berdasarkan performa terkini.

    - Normal   : 1.0 (sizing penuh)
    - Setelah 3 loss berturut: 0.5 (sizing 50%)
    - Recovery setelah menang: balik ke 1.0
    """
    state = _load_risk_state()
    konsekutif = state.get("konsekutif_loss", 0)

    if konsekutif >= CONSEC_LOSS_THRESHOLD:
        factor = CONSEC_LOSS_REDUCTION
        return {
            "factor"    : factor,
            "alasan"    : f"{konsekutif} loss berturut — sizing {int(factor*100)}%",
            "normal"    : False,
            "konsekutif": konsekutif
        }

    return {
        "factor"    : 1.0,
        "alasan"    : f"Normal (loss berturut: {konsekutif})",
        "normal"    : True,
        "konsekutif": konsekutif
    }


# ══════════════════════════════════════════════
# 9. CORRELATION RISK GUARD
# ══════════════════════════════════════════════

def cek_korelasi_posisi(symbol_baru, posisi_aktif, client):
    """
    Cek apakah menambah posisi baru akan membuat
    portfolio terlalu berkorelasi.

    Misal: sudah hold ETH dan SOL → keduanya sangat korelasi
    dengan BTC. Kalau BTC dump, semua kena sekaligus.

    Return dict:
        aman        : bool
        korelasi_max: float
        pasangan    : str (simbol paling berkorelasi)
        alasan      : str
    """
    syms_aktif = [s for s, p in posisi_aktif.items() if p.get("aktif")]

    if not syms_aktif:
        return {"aman": True, "korelasi_max": 0,
                "pasangan": "", "alasan": "Tidak ada posisi aktif"}

    # Ambil returns 24H
    returns = {}
    for sym in syms_aktif + [symbol_baru]:
        try:
            klines = client.get_klines(
                symbol=sym,
                interval="1h",
                limit=48
            )
            closes = [float(k[4]) for k in klines]
            rets   = [closes[i]/closes[i-1]-1 for i in range(1, len(closes))]
            returns[sym] = rets
        except Exception:
            pass

    if symbol_baru not in returns or len(returns) < 2:
        return {"aman": True, "korelasi_max": 0,
                "pasangan": "", "alasan": "Data tidak cukup"}

    # Hitung korelasi simbol baru vs semua posisi aktif
    ret_baru = np.array(returns[symbol_baru])
    max_corr = 0.0
    pasangan = ""

    for sym in syms_aktif:
        if sym not in returns:
            continue
        ret_ada = np.array(returns[sym])
        n       = min(len(ret_baru), len(ret_ada))
        if n < 10:
            continue
        try:
            corr = float(np.corrcoef(ret_baru[:n], ret_ada[:n])[0, 1])
            if not np.isnan(corr) and abs(corr) > max_corr:
                max_corr = abs(corr)
                pasangan = sym
        except Exception:
            pass

    aman = max_corr < MAX_CORRELATION

    return {
        "aman"        : aman,
        "korelasi_max": round(max_corr, 3),
        "pasangan"    : pasangan,
        "alasan"      : (
            f"OK — korelasi max {max_corr:.2f} dengan {pasangan}"
            if aman else
            f"BLOKIR — {symbol_baru} berkorelasi {max_corr:.2f} dengan {pasangan}"
        )
    }


# ══════════════════════════════════════════════
# 10. SPREAD / SLIPPAGE GUARD
# ══════════════════════════════════════════════

def cek_spread(client, symbol):
    """
    Cek spread bid-ask sebelum entry.
    Spread terlalu lebar = likuiditas buruk = slippage tinggi.

    Return dict:
        spread_pct : float
        aman       : bool
        alasan     : str
    """
    try:
        ob = client.get_order_book(symbol=symbol, limit=5)
        if not ob.get("bids") or not ob.get("asks"):
            return {"spread_pct": 0, "aman": True, "alasan": "No data"}

        best_bid = float(ob["bids"][0][0])
        best_ask = float(ob["asks"][0][0])
        mid      = (best_bid + best_ask) / 2
        spread   = (best_ask - best_bid) / mid * 100

        aman = spread < MAX_SPREAD_PCT

        return {
            "spread_pct": round(spread, 4),
            "best_bid"  : best_bid,
            "best_ask"  : best_ask,
            "aman"      : aman,
            "alasan"    : (
                f"Spread {spread:.3f}% OK"
                if aman else
                f"Spread {spread:.3f}% terlalu lebar (max {MAX_SPREAD_PCT}%)"
            )
        }
    except Exception as e:
        return {"spread_pct": 0, "aman": True,
                "alasan": f"Error: {e}"}


# ══════════════════════════════════════════════
# 11. LIQUIDATION DISTANCE CHECK (FUTURES)
# ══════════════════════════════════════════════

def cek_liquidation_distance(harga_entry, sl, leverage,
                              buffer_pct=LIQIDATION_BUFFER_PCT):
    """
    Untuk posisi futures — pastikan SL kena SEBELUM liquidasi.

    Jarak liquidasi long = harga / leverage
    Jika SL lebih jauh dari liquidasi → BAHAYA.

    Return dict:
        aman            : bool
        liq_price       : float
        jarak_liq_pct   : float
        jarak_sl_pct    : float
        alasan          : str
    """
    if leverage <= 0 or harga_entry <= 0:
        return {"aman": False, "alasan": "Parameter tidak valid"}

    # Harga liquidasi (long): entry * (1 - 1/leverage)
    liq_price     = harga_entry * (1 - 1/leverage)
    jarak_liq_pct = abs(harga_entry - liq_price) / harga_entry * 100
    jarak_sl_pct  = abs(harga_entry - sl) / harga_entry * 100

    # SL harus lebih dekat dari liquidasi dengan buffer
    sl_before_liq = sl > liq_price
    buffer_ok     = (jarak_liq_pct - jarak_sl_pct) >= buffer_pct / leverage

    aman = sl_before_liq and jarak_sl_pct < jarak_liq_pct

    return {
        "aman"          : aman,
        "liq_price"     : round(liq_price, 4),
        "jarak_liq_pct" : round(jarak_liq_pct, 2),
        "jarak_sl_pct"  : round(jarak_sl_pct, 2),
        "alasan"        : (
            f"SL ${sl:.4f} aman ({jarak_sl_pct:.1f}%) sebelum liq ${liq_price:.4f}"
            if aman else
            f"BAHAYA: SL ${sl:.4f} lebih jauh dari liquidasi ${liq_price:.4f}!"
        )
    }


# ══════════════════════════════════════════════
# 12. DRAWDOWN PER-POSISI TRACKER
# ══════════════════════════════════════════════

def hitung_drawdown_posisi(pos, harga_sekarang):
    """
    Hitung drawdown dari peak untuk posisi aktif.

    Jika posisi sudah naik 3% lalu turun ke +1%,
    drawdown dari peak = 2% — ini trigger trailing stop review.

    Return dict:
        profit_pct    : float (profit/loss dari entry)
        peak_pct      : float (profit tertinggi yang pernah dicapai)
        drawdown_pct  : float (turun dari peak)
        perlu_review  : bool (drawdown > 1.5% dari peak)
    """
    harga_beli  = pos.get("harga_beli", harga_sekarang)
    harga_peak  = pos.get("harga_tertinggi", harga_beli)

    profit_pct  = (harga_sekarang - harga_beli) / harga_beli * 100
    peak_pct    = (harga_peak     - harga_beli) / harga_beli * 100
    drawdown_pct= peak_pct - profit_pct  # selisih dari peak

    perlu_review = drawdown_pct > 1.5 and peak_pct > 0.5

    return {
        "profit_pct"  : round(profit_pct, 3),
        "peak_pct"    : round(peak_pct, 3),
        "drawdown_pct": round(drawdown_pct, 3),
        "perlu_review": perlu_review,
        "status"      : (
            f"Drawdown {drawdown_pct:.1f}% dari peak ⚠️"
            if perlu_review else
            f"P/L {profit_pct:+.2f}%"
        )
    }


# ══════════════════════════════════════════════
# 13. RISK-ADJUSTED POSITION SIZING
# ══════════════════════════════════════════════

def hitung_ukuran_posisi_risiko(saldo_usdt, harga_entry, sl_price,
                                 max_risk_pct=0.01, vol_regime=None,
                                 sizing_factor=None):
    """
    Hitung ukuran posisi berdasarkan risiko yang diterima.

    Formula: Size = (Saldo × Max_Risk%) / (Entry - SL)

    Contoh:
    Saldo $1000, Max risk 1%, Entry $50000, SL $49000
    Size = ($1000 × 0.01) / ($50000 - $49000) = $10 / $1000 = 0.01 BTC
    Nilai = 0.01 × $50000 = $500

    Ini memastikan: jika SL kena, maksimal rugi 1% dari saldo.

    Return dict:
        modal_usd   : float (nominal USDT untuk trade)
        qty_approx  : float (perkiraan qty koin)
        risiko_usd  : float (max loss dalam USD)
        risiko_pct  : float (% saldo yang dirisikokan)
        alasan      : str
    """
    if harga_entry <= 0 or sl_price <= 0 or saldo_usdt <= 0:
        return {"modal_usd": 0, "alasan": "Parameter tidak valid"}

    jarak_sl_pct = abs(harga_entry - sl_price) / harga_entry
    if jarak_sl_pct < 0.001:
        return {"modal_usd": 20, "alasan": "SL terlalu dekat — pakai modal minimum"}

    # Modal berdasarkan risiko
    modal_risiko = (saldo_usdt * max_risk_pct) / jarak_sl_pct

    # Sesuaikan dengan volatility regime
    if vol_regime:
        modal_risiko *= vol_regime.get("size_factor", 1.0)

    # Sesuaikan dengan consecutive loss factor
    if sizing_factor is None:
        sf_data = get_sizing_factor()
        sizing_factor = sf_data.get("factor", 1.0)
    modal_risiko *= sizing_factor

    # Clamp ke batas aman
    from trading_bot import (MAX_MODAL_PER_TRADE, MIN_MODAL_PER_TRADE,
                              MAX_PORTFOLIO_RISK_PCT)
    modal_final = max(
        MIN_MODAL_PER_TRADE,
        min(MAX_MODAL_PER_TRADE,
            min(modal_risiko, saldo_usdt * MAX_PORTFOLIO_RISK_PCT))
    )

    risiko_usd = modal_final * jarak_sl_pct
    risiko_pct = risiko_usd / saldo_usdt * 100

    return {
        "modal_usd"  : round(modal_final, 2),
        "qty_approx" : round(modal_final / harga_entry, 6),
        "risiko_usd" : round(risiko_usd, 2),
        "risiko_pct" : round(risiko_pct, 3),
        "sl_jarak_pct": round(jarak_sl_pct * 100, 3),
        "sizing_factor": sizing_factor,
        "alasan"     : (
            f"Modal ${modal_final:.2f} | "
            f"Max loss: ${risiko_usd:.2f} ({risiko_pct:.2f}% saldo)"
        )
    }


# ══════════════════════════════════════════════
# FUNGSI MASTER: VALIDASI RISIKO KOMPREHENSIF
# ══════════════════════════════════════════════

def validasi_risiko_lengkap(symbol, harga_entry, sl, tp,
                              saldo_usdt, posisi_spot,
                              posisi_futures, client,
                              df_1h=None, leverage=1):
    """
    Validasi SEMUA aspek risiko sebelum buka posisi.
    Gabungkan semua modul v2.0 dalam satu panggilan.

    Return dict:
        boleh       : bool — apakah boleh entry
        modal_usd   : float — ukuran posisi yang direkomendasikan
        skor_risiko : int   — 0-100 (100=sempurna)
        blokir      : list  — alasan blokir (jika ada)
        warning     : list  — peringatan (tidak blokir)
        detail      : dict  — detail semua cek
    """
    blokir  = []
    warning = []
    detail  = {}
    skor    = 100

    # ── 1. Risk/Reward ─────────────────────────
    rr = cek_risk_reward(harga_entry, sl, tp)
    detail["rr"] = rr
    if not rr["bagus"]:
        blokir.append(f"R:R {rr['rr_ratio']:.2f} < {MIN_RR_RATIO}")
        skor -= 25
    else:
        pass  # bonus tidak perlu

    # ── 2. Volatility Regime ───────────────────
    if df_1h is not None:
        vol = deteksi_volatility_regime(df_1h)
        detail["volatility"] = vol
        if not vol["boleh_entry"]:
            blokir.append(vol["alasan"])
            skor -= 30
        elif vol["regime"] == "ELEVATED":
            warning.append(f"Volatilitas ELEVATED — sizing dikurangi 25%")
            skor -= 10
    else:
        vol = {"size_factor": 1.0, "sl_multiplier": 1.5}
        detail["volatility"] = vol

    # ── 3. Position Heat ───────────────────────
    heat = hitung_position_heat(posisi_spot, posisi_futures, saldo_usdt)
    detail["heat"] = heat
    if heat["terlalu_panas"]:
        blokir.append(f"Portfolio heat {heat['heat_pct']:.1f}% > max {MAX_HEAT_PCT*100:.0f}%")
        skor -= 20
    elif heat["heat_pct"] > MAX_HEAT_PCT * 75:
        warning.append(f"Heat mendekati batas: {heat['heat_pct']:.1f}%")
        skor -= 5

    # ── 4. Consecutive Loss ────────────────────
    sf = get_sizing_factor()
    detail["sizing_factor"] = sf
    if not sf["normal"]:
        warning.append(sf["alasan"])
        skor -= 10

    # ── 5. Spread ──────────────────────────────
    spread = cek_spread(client, symbol)
    detail["spread"] = spread
    if not spread["aman"]:
        blokir.append(spread["alasan"])
        skor -= 15
    elif spread["spread_pct"] > MAX_SPREAD_PCT * 0.7:
        warning.append(f"Spread mendekati batas: {spread['spread_pct']:.3f}%")

    # ── 6. Korelasi ────────────────────────────
    if posisi_spot:
        try:
            korr = cek_korelasi_posisi(symbol, posisi_spot, client)
            detail["korelasi"] = korr
            if not korr["aman"]:
                warning.append(korr["alasan"])
                skor -= 10
        except Exception:
            pass

    # ── 7. Liquidasi (Futures) ──────────────────
    if leverage > 1:
        liq = cek_liquidation_distance(harga_entry, sl, leverage)
        detail["liquidasi"] = liq
        if not liq["aman"]:
            blokir.append(liq["alasan"])
            skor -= 20

    # ── Hitung ukuran posisi optimal ───────────
    ukuran = hitung_ukuran_posisi_risiko(
        saldo_usdt, harga_entry, sl,
        max_risk_pct=0.01,
        vol_regime=vol,
        sizing_factor=sf["factor"]
    )
    detail["sizing"] = ukuran

    boleh = len(blokir) == 0
    skor  = max(0, skor)

    return {
        "boleh"      : boleh,
        "modal_usd"  : ukuran.get("modal_usd", 20) if boleh else 0,
        "skor_risiko": skor,
        "blokir"     : blokir,
        "warning"    : warning,
        "detail"     : detail,
        "ringkasan"  : (
            f"✅ Risk OK (skor:{skor}) | Modal:${ukuran.get('modal_usd',0):.2f}"
            if boleh else
            f"🚫 Entry DIBLOKIR ({len(blokir)} alasan)"
        )
    }