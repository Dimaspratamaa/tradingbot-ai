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
