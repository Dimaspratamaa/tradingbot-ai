# ============================================
# MULTI STRATEGY ENGINE v1.0
# Mode: SCALPING | SWING | GRID
# Bot otomatis pilih mode terbaik per kondisi
# ============================================

from binance.client import Client
import pandas as pd
import numpy as np

# ── PARAMETER PER MODE ────────────────────────
PARAMS = {
    "SCALPING": {
        "interval"        : Client.KLINE_INTERVAL_15MINUTE,
        "interval_konfirm": Client.KLINE_INTERVAL_1HOUR,
        "min_skor"        : 5,      # Lebih agresif
        "sl_multiplier"   : 1.0,    # SL lebih ketat
        "tp_multiplier"   : 1.5,    # TP lebih dekat
        "trailing_aktivasi": 0.8,   # Trail lebih cepat
        "trailing_jarak"  : 0.5,
        "max_posisi"      : 2,
        "modal"           : 50.0,   # Modal lebih kecil
        "hold_max_jam"    : 4,      # Maksimal 4 jam hold
        "deskripsi"       : "Entry cepat 15m, TP kecil tapi sering"
    },
    "SWING": {
        "interval"        : Client.KLINE_INTERVAL_1HOUR,
        "interval_konfirm": Client.KLINE_INTERVAL_4HOUR,
        "min_skor"        : 6,
        "sl_multiplier"   : 1.5,
        "tp_multiplier"   : 3.0,
        "trailing_aktivasi": 1.5,
        "trailing_jarak"  : 1.0,
        "max_posisi"      : 3,
        "modal"           : 100.0,
        "hold_max_jam"    : 72,     # Maksimal 3 hari
        "deskripsi"       : "Default - balance antara profit & risiko"
    },
    "GRID": {
        "interval"        : Client.KLINE_INTERVAL_1HOUR,
        "interval_konfirm": Client.KLINE_INTERVAL_4HOUR,
        "min_skor"        : 4,      # Entry lebih sering
        "sl_multiplier"   : 2.0,    # SL lebih lebar
        "tp_multiplier"   : 2.0,
        "trailing_aktivasi": 1.0,
        "trailing_jarak"  : 0.8,
        "max_posisi"      : 5,      # Lebih banyak posisi
        "modal"           : 40.0,   # Modal kecil per grid
        "hold_max_jam"    : 168,    # Maksimal 1 minggu
        "deskripsi"       : "Buy/sell di range, cocok untuk sideways"
    }
}

# ── STATE ─────────────────────────────────────
_mode_aktif = "SWING"  # Default mode
_grid_levels = {}       # Untuk mode GRID

# ══════════════════════════════════════════════
# MODE SELECTOR
# ══════════════════════════════════════════════

def get_mode():
    """Ambil mode strategi aktif"""
    return _mode_aktif

def set_mode(mode):
    """Set mode strategi"""
    global _mode_aktif
    mode = mode.upper()
    if mode in PARAMS:
        _mode_aktif = mode
        print(f"  📈 Mode strategi: {mode}")
        return True
    return False

def get_params():
    """Ambil parameter untuk mode aktif"""
    return PARAMS[_mode_aktif]

def auto_detect_mode(btc_kondisi, market_overview, geo_sentiment):
    """
    Deteksi mode terbaik berdasarkan kondisi market.
    - Trending + bullish → SCALPING (tangkap momentum)
    - Sideways + netral  → GRID (profit dari ranging)
    - Strong trend       → SWING (ikuti trend)
    """
    btc_change = btc_kondisi.get("btc_change_1h", 0)
    btc_change_4h = btc_kondisi.get("btc_change_4h", 0)
    mcap_change = market_overview.get("change_24h", 0)
    geo_sell = geo_sentiment.get("skor_sell", 0)

    # Kondisi untuk setiap mode
    trending_kuat    = abs(btc_change_4h) > 3    # Bergerak > 3% per 4H
    trending_sedang  = abs(btc_change_4h) > 1.5
    market_bullish   = mcap_change > 2
    market_bearish   = mcap_change < -2
    geo_negatif      = geo_sell >= 2

    if geo_negatif:
        return "SWING"   # Saat geo negatif, tetap pakai swing yang konservatif

    if trending_kuat and market_bullish:
        return "SCALPING"   # Tangkap momentum kuat
    elif not trending_sedang:
        return "GRID"       # Market sideways → grid
    else:
        return "SWING"      # Default

# ══════════════════════════════════════════════
# SCALPING ENGINE
# ══════════════════════════════════════════════

def analisis_scalping(df_15m, df_1h):
    """
    Analisis khusus untuk mode scalping (15 menit).
    Fokus pada momentum jangka pendek.
    """
    if df_15m is None or len(df_15m) < 30:
        return {"sinyal": "HOLD", "skor": 0, "detail": []}

    close  = df_15m['close']
    high   = df_15m['high']
    low    = df_15m['low']
    volume = df_15m['volume']

    skor   = 0
    detail = []

    # RSI 9 period (lebih responsif untuk scalping)
    delta = close.diff()
    gain  = delta.where(delta > 0, 0).rolling(9).mean()
    loss  = (-delta.where(delta < 0, 0)).rolling(9).mean()
    rsi9  = (100 - (100 / (1 + gain / loss))).iloc[-1]

    # EMA cepat
    ema5  = close.ewm(span=5,  adjust=False).mean()
    ema13 = close.ewm(span=13, adjust=False).mean()
    ema21 = close.ewm(span=21, adjust=False).mean()

    harga = close.iloc[-1]

    # Sinyal scalping
    if rsi9 < 30:
        skor += 2; detail.append(f"RSI9 oversold({rsi9:.0f})")
    elif rsi9 < 45:
        skor += 1; detail.append(f"RSI9 murah({rsi9:.0f})")
    elif rsi9 > 70:
        skor -= 1; detail.append(f"RSI9 OB({rsi9:.0f})")

    # EMA alignment
    if ema5.iloc[-1] > ema13.iloc[-1] > ema21.iloc[-1]:
        skor += 2; detail.append("EMA bullish stack")
    elif ema5.iloc[-1] < ema13.iloc[-1] < ema21.iloc[-1]:
        skor -= 1; detail.append("EMA bearish stack")

    # EMA5 cross EMA13
    if (ema5.iloc[-1] > ema13.iloc[-1] and
            ema5.iloc[-2] <= ema13.iloc[-2]):
        skor += 2; detail.append("EMA5 cross UP")

    # Volume spike
    vol_avg = volume.rolling(20).mean().iloc[-1]
    if volume.iloc[-1] > vol_avg * 2:
        skor += 1; detail.append(f"Vol spike {volume.iloc[-1]/vol_avg:.1f}x")

    # Konfirmasi dari 1H
    if df_1h is not None:
        close_1h  = df_1h['close']
        ema20_1h  = close_1h.ewm(span=20, adjust=False).mean().iloc[-1]
        if close_1h.iloc[-1] > ema20_1h:
            skor += 1; detail.append("1H above EMA20")

    sinyal = "BUY" if skor >= 5 else "HOLD"
    return {"sinyal": sinyal, "skor": skor, "detail": detail, "rsi9": rsi9}

# ══════════════════════════════════════════════
# GRID ENGINE
# ══════════════════════════════════════════════

def setup_grid(symbol, harga_tengah, atr, n_grid=5):
    """
    Setup grid trading untuk symbol.
    Buat level buy/sell di sekitar harga tengah.

    Args:
        symbol      : trading pair
        harga_tengah: harga saat ini
        atr         : ATR untuk menentukan jarak grid
        n_grid      : jumlah level grid (default 5)
    """
    jarak_grid = atr * 0.8   # Jarak antar level = 0.8x ATR
    grid_levels = []

    for i in range(-(n_grid//2), n_grid//2 + 1):
        level = harga_tengah + (i * jarak_grid)
        tipe  = "BUY"  if i < 0 else ("CENTER" if i == 0 else "SELL")
        grid_levels.append({
            "level"   : round(level, 6),
            "tipe"    : tipe,
            "terisi"  : False,
            "qty"     : None
        })

    _grid_levels[symbol] = {
        "levels"        : grid_levels,
        "harga_tengah"  : harga_tengah,
        "atr"           : atr,
        "waktu_setup"   : __import__('time').strftime("%Y-%m-%d %H:%M:%S")
    }

    print(f"  📊 Grid {symbol}: {n_grid} level, jarak ${jarak_grid:,.4f}")
    return grid_levels

def cek_grid_trigger(symbol, harga_skrng):
    """
    Cek apakah harga menyentuh level grid.
    Return: level yang terpicu, atau None.
    """
    if symbol not in _grid_levels:
        return None

    grid = _grid_levels[symbol]
    for level in grid["levels"]:
        if level["terisi"]:
            continue

        # Toleransi 0.1% dari level
        toleransi = level["level"] * 0.001
        if abs(harga_skrng - level["level"]) <= toleransi:
            return level

    return None

def tandai_grid_terisi(symbol, level_harga):
    """Tandai level grid sebagai terisi"""
    if symbol not in _grid_levels:
        return
    for level in _grid_levels[symbol]["levels"]:
        if abs(level["level"] - level_harga) < level_harga * 0.001:
            level["terisi"] = True

def get_grid_status(symbol):
    """Ambil status grid untuk display"""
    if symbol not in _grid_levels:
        return None
    grid = _grid_levels[symbol]
    terisi = sum(1 for l in grid["levels"] if l["terisi"])
    total  = len(grid["levels"])
    return f"Grid {symbol}: {terisi}/{total} terisi"

# ══════════════════════════════════════════════
# CEK HOLD TIME (untuk scalping)
# ══════════════════════════════════════════════

def cek_hold_time_exceeded(pos, mode):
    """
    Cek apakah posisi sudah melewati batas waktu hold.
    Khusus untuk mode SCALPING yang punya batas waktu ketat.
    """
    params = PARAMS.get(mode, PARAMS["SWING"])
    max_jam = params["hold_max_jam"]

    try:
        waktu_beli = __import__('datetime').datetime.strptime(
            pos["waktu_beli"][:19], "%Y-%m-%d %H:%M:%S"
        )
        selisih_jam = (
            __import__('datetime').datetime.now() - waktu_beli
        ).total_seconds() / 3600

        if selisih_jam > max_jam:
            return True, round(selisih_jam, 1)
    except:
        pass

    return False, 0

# ══════════════════════════════════════════════
# STATUS STRATEGI
# ══════════════════════════════════════════════

def print_strategi_status():
    """Print status mode strategi aktif"""
    mode   = _mode_aktif
    params = PARAMS[mode]
    print(f"  📈 Strategi: {mode} | "
          f"Min skor:{params['min_skor']} | "
          f"Modal:${params['modal']} | "
          f"Max pos:{params['max_posisi']}")