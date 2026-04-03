# ============================================
# SENTIMENT ANALYZER v2.0
# Sumber utama: CryptoPanic + Fear & Greed Index
# Reddit DINONAKTIFKAN — SSL block di semua env non-browser
# ============================================

import requests
import ssl as _ssl_patch
import urllib3 as _urllib3_patch
_urllib3_patch.disable_warnings(_urllib3_patch.exceptions.InsecureRequestWarning)
try:
    _ssl_patch._create_default_https_context = _ssl_patch._create_unverified_context
except Exception:
    pass

import time
import json
from datetime import datetime, timedelta
from collections import defaultdict

# ── KONFIGURASI ───────────────────────────────
CRYPTOPANIC_BASE = "https://cryptopanic.com/api/free/v1/posts/"
POSTS_LIMIT      = 30

# Keyword sentimen
BULLISH_WORDS = [
    "bullish", "moon", "pump", "buy", "long", "breakout",
    "ath", "accumulate", "undervalued", "support", "bounce",
    "adoption", "bullrun", "surge", "rally", "gain", "profit",
    "hold", "hodl", "green", "up", "positive", "strong", "soar",
    "rise", "recover", "uptrend", "breakout", "outperform"
]
BEARISH_WORDS = [
    "bearish", "dump", "sell", "short", "crash", "bear",
    "rekt", "loss", "scam", "fud", "overvalued", "resistance",
    "breakdown", "correction", "drop", "fall", "red", "down",
    "negative", "weak", "panic", "fear", "bubble", "warning",
    "hack", "ban", "regulation", "crackdown", "liquidation"
]

# Cache
_sentiment_cache = {"data": None, "waktu": 0, "ttl": 1800}  # 30 menit

# ══════════════════════════════════════════════
# HELPER
# ══════════════════════════════════════════════

def _analisis_teks_sentimen(teks_list):
    """Analisis sentimen dari list teks, return rata skor."""
    skor_total = 0
    n = 0
    for teks in teks_list:
        t    = teks.lower()
        bull = sum(1 for w in BULLISH_WORDS if w in t)
        bear = sum(1 for w in BEARISH_WORDS if w in t)
        skor_total += (bull - bear)
        n += 1
    return skor_total / max(n, 1)

# ══════════════════════════════════════════════
# 1. CRYPTOPANIC SENTIMENT (sumber utama)
# ══════════════════════════════════════════════

def get_cryptopanic_sentiment():
    """
    Ambil sentimen dari CryptoPanic.
    Hanya coba filter 'hot' untuk hemat waktu.
    """
    try:
        url  = f"{CRYPTOPANIC_BASE}?public=true&kind=news&filter=hot"
        hdrs = {"User-Agent": "Mozilla/5.0 TradingBot/2.0"}
        resp = requests.get(url, headers=hdrs, timeout=8, verify=True)
        if resp.status_code != 200:
            return None
        data    = resp.json()
        results = data.get("results", [])
        if not results:
            return None
        all_teks = [r.get("title","") for r in results[:POSTS_LIMIT] if r.get("title")]
        if not all_teks:
            return None
        rata = _analisis_teks_sentimen(all_teks)
        return {
            "sumber"    : "cryptopanic",
            "n_berita"  : len(all_teks),
            "rata_skor" : round(rata, 3),
            "skor_total": round(rata * len(all_teks), 2),
        }
    except Exception as e:
        print(f"  ⚠️  CryptoPanic error: {e}")
        return None

def get_messari_sentiment():
    """
    Fallback: ambil berita dari Messari public API (tanpa key).
    Endpoint ini gratis dan umumnya tidak di-block.
    """
    try:
        url  = "https://data.messari.io/api/v1/news?limit=20"
        hdrs = {"User-Agent": "Mozilla/5.0 TradingBot/2.0"}
        resp = requests.get(url, headers=hdrs, timeout=8, verify=True)
        if resp.status_code != 200:
            return None
        data    = resp.json()
        results = data.get("data", [])
        if not results:
            return None
        all_teks = [r.get("title","") for r in results if r.get("title")]
        if not all_teks:
            return None
        rata = _analisis_teks_sentimen(all_teks)
        return {
            "sumber"    : "messari",
            "n_berita"  : len(all_teks),
            "rata_skor" : round(rata, 3),
            "skor_total": round(rata * len(all_teks), 2),
        }
    except Exception as e:
        print(f"  ⚠️  Messari error: {e}")
        return None

def get_all_news_sentiment():
    """
    Ambil sentimen berita. Urutan prioritas:
    1. CryptoPanic (utama)
    2. Messari (fallback jika CryptoPanic gagal)
    3. Return None jika keduanya gagal (tidak crash)
    """
    # Coba CryptoPanic dulu
    print("  📰 Mengambil berita dari CryptoPanic...")
    hasil = get_cryptopanic_sentiment()
    if hasil:
        print(f"  ✅ CryptoPanic: {hasil['n_berita']} berita | skor: {hasil['rata_skor']:+.3f}")
        return {"subreddits": [hasil], "rata_gabung": hasil["rata_skor"], "n_subreddit": 1}

    # Fallback ke Messari
    print("  📰 CryptoPanic gagal → coba Messari...")
    hasil = get_messari_sentiment()
    if hasil:
        print(f"  ✅ Messari: {hasil['n_berita']} berita | skor: {hasil['rata_skor']:+.3f}")
        return {"subreddits": [hasil], "rata_gabung": hasil["rata_skor"], "n_subreddit": 1}

    # Semua gagal — lanjutkan tanpa sentimen berita (tidak crash bot)
    print("  ⚠️  Semua sumber berita gagal — pakai sentimen netral")
    return {"subreddits": [], "rata_gabung": 0.0, "n_subreddit": 0}

# Alias kompatibilitas — kode lama yang panggil get_all_reddit_sentiment tetap bekerja
get_all_reddit_sentiment = get_all_news_sentiment

# ══════════════════════════════════════════════
# 2. FEAR & GREED INDEX
# ══════════════════════════════════════════════

def get_fear_greed():
    """
    Ambil Fear & Greed Index dari alternative.me API.
    0 = Extreme Fear, 100 = Extreme Greed
    """
    try:
        url  = "https://api.alternative.me/fng/?limit=2"
        resp = requests.get(url, timeout=10)
        data = resp.json()

        if "data" not in data:
            return None

        current  = data["data"][0]
        previous = data["data"][1] if len(data["data"]) > 1 else current

        nilai    = int(current["value"])
        label    = current["value_classification"]
        prev_val = int(previous["value"])
        perubahan = nilai - prev_val

        if nilai >= 75:
            sinyal    = "EXTREME_GREED"
            skor_sell = 2
            skor_buy  = 0
        elif nilai >= 60:
            sinyal    = "GREED"
            skor_sell = 1
            skor_buy  = 0
        elif nilai >= 45:
            sinyal    = "NETRAL"
            skor_sell = 0
            skor_buy  = 0
        elif nilai >= 25:
            sinyal    = "FEAR"
            skor_buy  = 1
            skor_sell = 0
        else:
            sinyal    = "EXTREME_FEAR"
            skor_buy  = 2
            skor_sell = 0

        return {
            "nilai"    : nilai,
            "label"    : label,
            "sinyal"   : sinyal,
            "perubahan": perubahan,
            "skor_buy" : skor_buy,
            "skor_sell": skor_sell,
            "detail"   : f"F&G:{nilai} ({label}) {perubahan:+d} dari kemarin"
        }

    except Exception as e:
        print(f"  ⚠️  Fear & Greed error: {e}")
        return None

# ══════════════════════════════════════════════
# 3. AGREGASI SENTIMENT
# ══════════════════════════════════════════════

def get_market_sentiment():
    """
    Fungsi utama — gabungkan CryptoPanic + Fear & Greed.

    Return dict:
        skor_buy     : int (0-4)
        skor_sell    : int (0-4)
        sentiment    : str
        fear_greed   : dict
        reddit       : dict  (isi dari CryptoPanic, nama dipertahankan untuk kompatibilitas)
        detail       : list[str]
        summary      : str
    """
    global _sentiment_cache
    sekarang = time.time()

    if (_sentiment_cache["data"] is not None and
            sekarang - _sentiment_cache["waktu"] < _sentiment_cache["ttl"]):
        return _sentiment_cache["data"]

    print("  🧠 Menganalisis sentimen market (CryptoPanic + F&G)...")

    detail    = []
    skor_buy  = 0
    skor_sell = 0

    # 1. Fear & Greed Index
    fg = get_fear_greed()
    if fg:
        skor_buy  += fg["skor_buy"]
        skor_sell += fg["skor_sell"]
        detail.append(fg["detail"])
        print(f"  📊 Fear & Greed: {fg['nilai']} ({fg['label']})")
    else:
        fg = {"nilai": 50, "label": "Neutral", "sinyal": "NETRAL",
              "skor_buy": 0, "skor_sell": 0, "detail": "N/A"}

    # 2. CryptoPanic News Sentiment
    news = get_all_news_sentiment()
    if news:
        rata  = news["rata_gabung"]
        n_src = news["n_subreddit"]

        if rata >= 1.5:
            skor_buy += 2
            detail.append(f"News BULLISH ({rata:+.2f}, {n_src} sumber)")
        elif rata >= 0.5:
            skor_buy += 1
            detail.append(f"News sedikit bullish ({rata:+.2f})")
        elif rata <= -1.5:
            skor_sell += 2
            detail.append(f"News BEARISH ({rata:+.2f})")
        elif rata <= -0.5:
            skor_sell += 1
            detail.append(f"News sedikit bearish ({rata:+.2f})")
        else:
            detail.append(f"News netral ({rata:+.2f})")
    else:
        news = {"rata_gabung": 0, "n_subreddit": 0}

    # Tentukan sentiment keseluruhan
    net_skor = skor_buy - skor_sell
    if net_skor >= 3:
        sentiment = "VERY_BULLISH"
    elif net_skor >= 1:
        sentiment = "BULLISH"
    elif net_skor <= -3:
        sentiment = "VERY_BEARISH"
    elif net_skor <= -1:
        sentiment = "BEARISH"
    else:
        sentiment = "NEUTRAL"

    summary = (
        f"F&G:{fg['nilai']} | "
        f"News:{news.get('rata_gabung', 0):+.2f} | "
        f"Sentiment:{sentiment}"
    )

    hasil = {
        "skor_buy" : min(skor_buy, 4),
        "skor_sell": min(skor_sell, 4),
        "sentiment": sentiment,
        "fear_greed": fg,
        "reddit"   : news,   # nama dipertahankan agar kompatibel dengan trading_bot.py
        "detail"   : detail,
        "summary"  : summary
    }

    _sentiment_cache["data"]  = hasil
    _sentiment_cache["waktu"] = sekarang
    return hasil