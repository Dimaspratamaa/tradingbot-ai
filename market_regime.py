# ============================================
# MARKET REGIME DETECTOR v1.0
# Deteksi kondisi market: BULL / BEAR / SIDEWAYS
# dan sesuaikan parameter trading otomatis
#
# Metode:
#   - BTC trend (EMA 20/50/200)
#   - Volatilitas (ATR ratio)
#   - Market breadth (berapa koin yang uptrend)
#   - Volume trend
# ============================================

import time
import pandas as pd
import numpy as np

# ── CACHE ─────────────────────────────────────
_regime_cache = {"data": None, "waktu": 0, "ttl": 900}  # 15 menit

# ── PARAMETER PER REGIME ─────────────────────
REGIME_PARAMS = {
    "BULL_KUAT": {
        "min_skor"        : 6,    # Lebih mudah entry saat bull
        "sl_multiplier"   : 1.2,  # SL lebih ketat (less noise)
        "tp_multiplier"   : 4.0,  # TP lebih jauh (ride the trend)
        "max_posisi"      : 3,
        "deskripsi"       : "Trend naik kuat — ride the trend"
    },
    "BULL_LEMAH": {
        "min_skor"        : 7,
        "sl_multiplier"   : 1.5,
        "tp_multiplier"   : 3.0,
        "max_posisi"      : 2,
        "deskripsi"       : "Trend naik tapi lemah — selektif"
    },
    "SIDEWAYS": {
        "min_skor"        : 8,    # Lebih ketat saat sideways
        "sl_multiplier"   : 1.0,  # SL ketat
        "tp_multiplier"   : 1.5,  # TP dekat (scalp)
        "max_posisi"      : 2,
        "deskripsi"       : "Market ranging — scalp atau skip"
    },
    "BEAR_LEMAH": {
        "min_skor"        : 9,    # Sangat selektif
        "sl_multiplier"   : 2.0,  # SL lebar (volatile)
        "tp_multiplier"   : 2.0,
        "max_posisi"      : 1,
        "deskripsi"       : "Downtrend — hati-hati, posisi minimal"
    },
    "BEAR_KUAT": {
        "min_skor"        : 12,   # Hampir tidak entry
        "sl_multiplier"   : 2.5,
        "tp_multiplier"   : 2.0,
        "max_posisi"      : 0,    # Stop entry saat bear kuat
        "deskripsi"       : "Downtrend kuat — stop entry spot"
    }
}

# ══════════════════════════════════════════════
# DETEKSI REGIME
# ══════════════════════════════════════════════

def deteksi_regime(client):
    """
    Deteksi kondisi market berdasarkan BTC price action.
    """
    global _regime_cache
    sekarang = time.time()

    if (_regime_cache["data"] is not None and
            sekarang - _regime_cache["waktu"] < _regime_cache["ttl"]):
        return _regime_cache["data"]

    try:
        # Ambil data BTC beberapa timeframe
        from binance.client import Client as BClient
        klines_1d = client.get_klines(
            symbol="BTCUSDT",
            interval=BClient.KLINE_INTERVAL_1DAY,
            limit=60
        )
        klines_4h = client.get_klines(
            symbol="BTCUSDT",
            interval=BClient.KLINE_INTERVAL_4HOUR,
            limit=50
        )

        df_1d = pd.DataFrame(klines_1d, columns=[
            'time','open','high','low','close','volume',
            'close_time','quote_vol','trades',
            'taker_base','taker_quote','ignore'
        ])
        df_4h = pd.DataFrame(klines_4h, columns=[
            'time','open','high','low','close','volume',
            'close_time','quote_vol','trades',
            'taker_base','taker_quote','ignore'
        ])
        for col in ['open','high','low','close','volume']:
            df_1d[col] = df_1d[col].astype(float)
            df_4h[col] = df_4h[col].astype(float)

        regime = _analisis_regime(df_1d, df_4h)

        _regime_cache["data"]  = regime
        _regime_cache["waktu"] = sekarang
        return regime

    except Exception as e:
        print(f"  ⚠️  Regime detection error: {e}")
        return _default_regime()

def _analisis_regime(df_1d, df_4h):
    """Analisis regime dari dataframe"""
    close_1d = df_1d['close']
    close_4h = df_4h['close']

    harga_skrng = close_1d.iloc[-1]

    # ── EMA Trend (1D) ──
    ema20_1d  = close_1d.ewm(span=20,  adjust=False).mean().iloc[-1]
    ema50_1d  = close_1d.ewm(span=50,  adjust=False).mean().iloc[-1]
    ema200_1d = close_1d.ewm(span=200, adjust=False).mean().iloc[-1] if len(close_1d) >= 200 else ema50_1d

    # ── EMA Trend (4H) ──
    ema20_4h = close_4h.ewm(span=20, adjust=False).mean().iloc[-1]
    ema50_4h = close_4h.ewm(span=50, adjust=False).mean().iloc[-1]

    # ── Volatilitas (ATR ratio) ──
    high = df_1d['high']; low = df_1d['low']
    tr   = pd.concat([
        high - low,
        (high - close_1d.shift()).abs(),
        (low  - close_1d.shift()).abs()
    ], axis=1).max(axis=1)
    atr_14  = tr.rolling(14).mean().iloc[-1]
    atr_50  = tr.rolling(50).mean().iloc[-1]
    vol_ratio = atr_14 / atr_50 if atr_50 > 0 else 1.0

    # ── Momentum 30 hari ──
    mom_30 = ((harga_skrng - close_1d.iloc[-30]) / close_1d.iloc[-30]) * 100

    # ── Scoring ──
    bull_score = 0
    bear_score = 0

    # EMA alignment
    if harga_skrng > ema20_1d > ema50_1d:
        bull_score += 3
    elif harga_skrng < ema20_1d < ema50_1d:
        bear_score += 3

    if harga_skrng > ema200_1d:
        bull_score += 2
    else:
        bear_score += 2

    # 4H trend
    if close_4h.iloc[-1] > ema20_4h > ema50_4h:
        bull_score += 2
    elif close_4h.iloc[-1] < ema20_4h < ema50_4h:
        bear_score += 2

    # Momentum
    if mom_30 > 15:
        bull_score += 2
    elif mom_30 > 5:
        bull_score += 1
    elif mom_30 < -15:
        bear_score += 2
    elif mom_30 < -5:
        bear_score += 1

    # Volatilitas tinggi = kurang pasti
    volatile = vol_ratio > 1.5

    # ── Tentukan regime ──
    net = bull_score - bear_score

    if net >= 6 and not volatile:
        regime = "BULL_KUAT"
    elif net >= 3:
        regime = "BULL_LEMAH"
    elif net <= -6:
        regime = "BEAR_KUAT"
    elif net <= -3:
        regime = "BEAR_LEMAH"
    else:
        regime = "SIDEWAYS"

    params = REGIME_PARAMS[regime]

    return {
        "regime"      : regime,
        "bull_score"  : bull_score,
        "bear_score"  : bear_score,
        "net_score"   : net,
        "mom_30d"     : round(mom_30, 2),
        "volatile"    : volatile,
        "vol_ratio"   : round(vol_ratio, 2),
        "harga_btc"   : harga_skrng,
        "ema20_1d"    : round(ema20_1d, 2),
        "ema50_1d"    : round(ema50_1d, 2),
        "params"      : params,
        "deskripsi"   : params["deskripsi"],
        "min_skor"    : params["min_skor"],
        "max_posisi"  : params["max_posisi"]
    }

def _default_regime():
    return {
        "regime"    : "SIDEWAYS",
        "bull_score": 0, "bear_score": 0, "net_score": 0,
        "mom_30d"   : 0, "volatile": False, "vol_ratio": 1.0,
        "harga_btc" : 0, "ema20_1d": 0, "ema50_1d": 0,
        "params"    : REGIME_PARAMS["SIDEWAYS"],
        "deskripsi" : "Default (data tidak tersedia)",
        "min_skor"  : 7, "max_posisi": 2
    }

def get_regime_params(client):
    """Ambil parameter trading yang disesuaikan dengan regime"""
    regime = deteksi_regime(client)
    return regime

def print_regime_status(client):
    """Print status regime untuk monitoring"""
    r = deteksi_regime(client)
    em = "🚀" if "BULL" in r["regime"] else (
         "🐻" if "BEAR" in r["regime"] else "↔️")
    print(f"  {em} Regime: {r['regime']} | "
          f"Mom30d:{r['mom_30d']:+.1f}% | "
          f"MinSkor:{r['min_skor']} | "
          f"MaxPos:{r['max_posisi']}")