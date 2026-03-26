# ============================================
# MARKET DEPTH ANALYZER v1.0
# Sumber data market microstructure
#
# 1. CoinGlass (GRATIS)
#    - Liquidation heatmap
#    - Open Interest perubahan
#    - Long/Short ratio
#    - Funding rate agregat
#
# 2. Polygon.io (GRATIS tier)
#    - Tick-level data
#    - Options flow (paid)
#    - Market microstructure
#
# Cara daftar:
#   CoinGlass: https://coinglass.com/api (gratis, daftar email)
#   Polygon  : https://polygon.io (gratis tier)
# ============================================

import requests
import time
import os
from datetime import datetime, timedelta

# ── API KEYS ──────────────────────────────────
COINGLASS_KEY = os.environ.get("COINGLASS_API_KEY", "")
POLYGON_KEY   = os.environ.get("POLYGON_API_KEY", "")

# ── CACHE ─────────────────────────────────────
_depth_cache = {"data": {}, "waktu": {}, "ttl": 300}

# ══════════════════════════════════════════════
# 1. COINGLASS — LIQUIDASI & OPEN INTEREST
# ══════════════════════════════════════════════

def get_liquidasi(symbol="BTC", interval="1h"):
    """
    Ambil data liquidasi futures dari CoinGlass.
    Liquidasi besar = volatilitas tinggi = hati-hati entry.
    """
    try:
        # CoinGlass public API (beberapa endpoint gratis tanpa key)
        coin = symbol.replace("USDT", "")
        url  = f"https://open-api.coinglass.com/public/v2/liquidation_chart"
        params = {
            "symbol"  : coin,
            "interval": interval
        }
        headers = {}
        if COINGLASS_KEY:
            headers["coinglassSecret"] = COINGLASS_KEY

        resp = requests.get(url, params=params,
                           headers=headers, timeout=10)
        data = resp.json()

        if data.get("code") == "0" and data.get("data"):
            items        = data["data"]
            # Ambil liquidasi 1 jam terakhir
            liq_long  = sum(float(i.get("longLiquidationUsd", 0))
                           for i in items[-4:])
            liq_short = sum(float(i.get("shortLiquidationUsd", 0))
                           for i in items[-4:])
            liq_total = liq_long + liq_short

            return {
                "symbol"   : symbol,
                "liq_long" : liq_long,
                "liq_short": liq_short,
                "liq_total": liq_total,
                "dominasi" : "LONG" if liq_long > liq_short else "SHORT"
            }
    except Exception as e:
        print(f"  ⚠️  CoinGlass liquidation error: {e}")
    return None

def get_open_interest(symbol="BTC"):
    """
    Ambil Open Interest dari CoinGlass.
    OI naik + harga naik = bullish kuat
    OI naik + harga turun = bearish (short squeeze potential)
    """
    try:
        coin = symbol.replace("USDT", "")
        url  = "https://open-api.coinglass.com/public/v2/open_interest"
        params = {"symbol": coin}
        headers = {}
        if COINGLASS_KEY:
            headers["coinglassSecret"] = COINGLASS_KEY

        resp = requests.get(url, params=params,
                           headers=headers, timeout=10)
        data = resp.json()

        if data.get("code") == "0" and data.get("data"):
            total_oi    = sum(float(d.get("openInterestUsd", 0))
                             for d in data["data"])
            return {
                "symbol"  : symbol,
                "total_oi": total_oi,
                "oi_b"    : total_oi / 1e9
            }
    except Exception as e:
        print(f"  ⚠️  CoinGlass OI error: {e}")
    return None

def get_long_short_ratio(symbol="BTC"):
    """
    Ambil rasio Long/Short dari CoinGlass.
    Ratio > 1 = lebih banyak long (contrarian: bisa bearish)
    Ratio < 1 = lebih banyak short (contrarian: bisa bullish)
    """
    try:
        coin = symbol.replace("USDT", "")
        url  = "https://open-api.coinglass.com/public/v2/long_short_account"
        params = {
            "symbol"  : coin,
            "interval": "1h",
            "limit"   : 5
        }
        headers = {}
        if COINGLASS_KEY:
            headers["coinglassSecret"] = COINGLASS_KEY

        resp = requests.get(url, params=params,
                           headers=headers, timeout=10)
        data = resp.json()

        if data.get("code") == "0" and data.get("data"):
            latest = data["data"][-1]
            ratio  = float(latest.get("longRatio", 0.5))
            return {
                "symbol"    : symbol,
                "long_ratio": ratio,
                "short_ratio": 1 - ratio,
                "dominasi"  : "LONG" if ratio > 0.5 else "SHORT"
            }
    except Exception as e:
        print(f"  ⚠️  CoinGlass L/S ratio error: {e}")
    return None

def get_funding_rate_global(symbol="BTC"):
    """
    Funding rate dari semua exchange via CoinGlass.
    Funding positif tinggi = too many longs = reversal risk
    Funding negatif = banyak short = potential short squeeze
    """
    try:
        coin = symbol.replace("USDT", "")
        url  = "https://open-api.coinglass.com/public/v2/funding"
        params = {"symbol": coin}
        headers = {}
        if COINGLASS_KEY:
            headers["coinglassSecret"] = COINGLASS_KEY

        resp = requests.get(url, params=params,
                           headers=headers, timeout=10)
        data = resp.json()

        if data.get("code") == "0" and data.get("data"):
            rates = [float(d.get("fundingRate", 0))
                    for d in data["data"] if d.get("fundingRate")]
            if rates:
                avg_rate = sum(rates) / len(rates)
                return {
                    "symbol"  : symbol,
                    "avg_rate": avg_rate,
                    "avg_pct" : avg_rate * 100,
                    "n_ex"    : len(rates)
                }
    except Exception as e:
        print(f"  ⚠️  CoinGlass funding error: {e}")
    return None

# ══════════════════════════════════════════════
# 2. POLYGON.IO — MARKET MICROSTRUCTURE
# ══════════════════════════════════════════════

def get_crypto_snapshot(symbol="X:BTCUSD"):
    """
    Ambil snapshot market dari Polygon.io.
    Termasuk: spread bid-ask, volume, VWAP
    """
    if not POLYGON_KEY:
        return None
    try:
        url  = f"https://api.polygon.io/v2/snapshot/locale/global/markets/crypto/tickers/{symbol}"
        params = {"apiKey": POLYGON_KEY}
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()

        if data.get("status") == "OK" and data.get("ticker"):
            t   = data["ticker"]
            day = t.get("day", {})
            return {
                "symbol"  : symbol,
                "harga"   : t.get("lastTrade", {}).get("p", 0),
                "vwap"    : day.get("vw", 0),
                "volume"  : day.get("v", 0),
                "open"    : day.get("o", 0),
                "high"    : day.get("h", 0),
                "low"     : day.get("l", 0),
                "spread"  : t.get("lastQuote", {}).get("S", 0) -
                            t.get("lastQuote", {}).get("P", 0)
            }
    except Exception as e:
        print(f"  ⚠️  Polygon snapshot error: {e}")
    return None

def get_market_conditions():
    """
    Ambil kondisi market broad dari Polygon
    (indices, market breadth)
    """
    if not POLYGON_KEY:
        return None
    try:
        # S&P 500 sebagai proxy risk sentiment
        url  = "https://api.polygon.io/v2/snapshot/locale/us/markets/indices/tickers"
        params = {
            "tickers": "I:SPX,I:VIX",
            "apiKey" : POLYGON_KEY
        }
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()

        if data.get("status") == "OK":
            hasil = {}
            for ticker in data.get("tickers", []):
                sym = ticker.get("ticker", "")
                day = ticker.get("day", {})
                hasil[sym] = {
                    "harga"    : day.get("c", 0),
                    "change_pct": ticker.get("todaysChangePerc", 0)
                }
            return hasil
    except Exception as e:
        print(f"  ⚠️  Polygon market conditions error: {e}")
    return None

# ══════════════════════════════════════════════
# ANALISIS SINYAL DARI MARKET DEPTH
# ══════════════════════════════════════════════

def analisis_market_depth(symbol_usdt):
    """
    Gabungkan semua data market depth jadi sinyal trading.
    """
    coin = symbol_usdt.replace("USDT", "")

    skor_buy  = 0
    skor_sell = 0
    detail    = []

    # ── Liquidasi ──
    liq = get_liquidasi(coin)
    if liq:
        total_usd = liq["liq_total"]
        if total_usd > 50_000_000:  # > $50M liquidasi = sangat volatile
            skor_sell += 2
            detail.append(
                f"⚠️ Liquidasi besar: ${total_usd/1e6:.1f}M "
                f"(dominasi: {liq['dominasi']})"
            )
        elif total_usd > 10_000_000:  # > $10M
            skor_sell += 1
            detail.append(f"⚡ Liquidasi ${total_usd/1e6:.1f}M")

        # Short squeeze potential
        if liq["liq_short"] > liq["liq_long"] * 2:
            skor_buy += 1
            detail.append("🚀 Short squeeze potential!")

    # ── Long/Short Ratio (contrarian) ──
    ls = get_long_short_ratio(coin)
    if ls:
        ratio = ls["long_ratio"]
        if ratio > 0.72:  # Terlalu banyak long = reversal risk
            skor_sell += 2
            detail.append(
                f"🔴 Long/Short: {ratio:.0%} long (crowded, reversal risk)"
            )
        elif ratio < 0.45:  # Terlalu banyak short = squeeze potential
            skor_buy += 2
            detail.append(
                f"🟢 Short crowded: {ratio:.0%} long (squeeze potential)"
            )
        else:
            detail.append(f"⚪ L/S ratio: {ratio:.0%} long")

    # ── Funding Rate ──
    funding = get_funding_rate_global(coin)
    if funding:
        rate = funding["avg_pct"]
        if rate > 0.08:  # Funding sangat positif = terlalu banyak long
            skor_sell += 2
            detail.append(
                f"🔴 Funding tinggi: {rate:.4f}% "
                f"({funding['n_ex']} exchange)"
            )
        elif rate > 0.04:
            skor_sell += 1
            detail.append(f"🟡 Funding elevated: {rate:.4f}%")
        elif rate < -0.04:  # Funding negatif = short squeeze setup
            skor_buy += 2
            detail.append(f"🟢 Funding negatif: {rate:.4f}% (bullish)")
        elif rate < 0:
            skor_buy += 1
            detail.append(f"🟢 Funding sedikit negatif: {rate:.4f}%")

    if not detail:
        detail.append("⚪ Market depth data tidak tersedia (isi API key)")

    net = skor_buy - skor_sell
    if net >= 2:
        sentimen = "DEPTH_BULLISH"
    elif net >= 1:
        sentimen = "DEPTH_SEDIKIT_BULLISH"
    elif net <= -2:
        sentimen = "DEPTH_BEARISH"
    elif net <= -1:
        sentimen = "DEPTH_SEDIKIT_BEARISH"
    else:
        sentimen = "DEPTH_NETRAL"

    return {
        "skor_buy" : min(skor_buy, 3),
        "skor_sell": min(skor_sell, 3),
        "sentimen" : sentimen,
        "detail"   : detail,
        "liquidasi": liq,
        "ls_ratio" : ls,
        "funding"  : funding,
        "summary"  : f"Depth:{sentimen}"
    }

# ── FUNGSI UTAMA ─────────────────────────────
def get_depth_score(symbol_usdt):
    """Entry point — dipanggil dari hitung_skor_koin()"""
    global _depth_cache
    sekarang = time.time()
    ttl      = _depth_cache["ttl"]

    if (symbol_usdt in _depth_cache["data"] and
            sekarang - _depth_cache["waktu"].get(symbol_usdt, 0) < ttl):
        return _depth_cache["data"][symbol_usdt]

    hasil = analisis_market_depth(symbol_usdt)
    _depth_cache["data"][symbol_usdt]  = hasil
    _depth_cache["waktu"][symbol_usdt] = sekarang
    return hasil