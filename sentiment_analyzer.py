# ============================================
# SENTIMENT ANALYZER v1.0
# Sumber: Reddit (public API) + CryptoPanic
# + Fear & Greed Index + Google Trends proxy
# ============================================

import requests
import time
import json
from datetime import datetime, timedelta
from collections import defaultdict

# ── KONFIGURASI ───────────────────────────────
REDDIT_BASE    = "https://www.reddit.com"
SUBREDDITS     = ["cryptocurrency", "bitcoin", "ethfinance",
                  "solana", "cryptomarkets", "altcoin"]
POSTS_LIMIT    = 25    # Post per subreddit

# Keyword sentiment
BULLISH_WORDS  = [
    "bullish", "moon", "pump", "buy", "long", "breakout",
    "ath", "accumulate", "undervalued", "support", "bounce",
    "adoption", "bullrun", "surge", "rally", "gain", "profit",
    "hold", "hodl", "green", "up", "positive", "strong"
]
BEARISH_WORDS  = [
    "bearish", "dump", "sell", "short", "crash", "bear",
    "rekt", "loss", "scam", "fud", "overvalued", "resistance",
    "breakdown", "correction", "drop", "fall", "red", "down",
    "negative", "weak", "panic", "fear", "bubble", "warning"
]

# Cache
_sentiment_cache = {"data": None, "waktu": 0, "ttl": 1800}  # 30 menit

# ══════════════════════════════════════════════
# 1. REDDIT SENTIMENT
# ══════════════════════════════════════════════

def get_reddit_sentiment(subreddit="cryptocurrency", limit=25):
    """
    Ambil post terbaru dari subreddit dan analisis sentimen.
    Menggunakan public Reddit JSON API (tanpa API key).
    """
    try:
        url     = f"{REDDIT_BASE}/r/{subreddit}/hot.json?limit={limit}"
        headers = {"User-Agent": "TradingBot/1.0"}
        resp    = requests.get(url, headers=headers, timeout=10)

        if resp.status_code != 200:
            return None

        data  = resp.json()
        posts = data.get("data", {}).get("children", [])

        skor_total = 0
        n_post     = 0
        detail     = []

        for post in posts:
            p     = post.get("data", {})
            title = (p.get("title", "") + " " +
                     p.get("selftext", "")[:200]).lower()
            score = p.get("score", 0)
            upvote_ratio = p.get("upvote_ratio", 0.5)

            # Hitung sentimen teks
            bull = sum(1 for w in BULLISH_WORDS if w in title)
            bear = sum(1 for w in BEARISH_WORDS if w in title)
            net  = bull - bear

            # Weight by upvotes
            bobot  = min(score / 1000, 3.0)  # Max bobot 3x
            skor_w = net * (1 + bobot) * upvote_ratio

            skor_total += skor_w
            n_post     += 1

            if abs(net) >= 2 and score > 100:
                detail.append({
                    "judul" : p.get("title", "")[:60],
                    "skor"  : round(skor_w, 2),
                    "upvote": score
                })

        rata = skor_total / max(n_post, 1)

        return {
            "subreddit": subreddit,
            "n_post"   : n_post,
            "rata_skor": round(rata, 3),
            "skor_total": round(skor_total, 2),
            "top_posts": sorted(detail,
                key=lambda x: abs(x["skor"]), reverse=True)[:3]
        }

    except Exception as e:
        print(f"  ⚠️  Reddit {subreddit} error: {e}")
        return None

def get_all_reddit_sentiment():
    """Ambil sentimen dari semua subreddit yang dikonfigurasi"""
    hasil_semua = []
    skor_gabung = 0

    for sub in SUBREDDITS:
        hasil = get_reddit_sentiment(sub, POSTS_LIMIT)
        if hasil:
            hasil_semua.append(hasil)
            skor_gabung += hasil["rata_skor"]
        time.sleep(1)  # Rate limit Reddit

    if not hasil_semua:
        return None

    rata_gabung = skor_gabung / len(hasil_semua)

    return {
        "subreddits" : hasil_semua,
        "rata_gabung": round(rata_gabung, 3),
        "n_subreddit": len(hasil_semua)
    }

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

        # Tentukan sinyal
        if nilai >= 75:
            sinyal    = "EXTREME_GREED"
            skor_sell = 2  # Overbought → bearish
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
            skor_buy  = 1  # Oversold → bullish
            skor_sell = 0
        else:
            sinyal    = "EXTREME_FEAR"
            skor_buy  = 2  # Sangat oversold → beli
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
    Fungsi utama — gabungkan semua sumber sentimen.

    Return dict:
        skor_buy     : int (0-4)
        skor_sell    : int (0-4)
        sentiment    : str
        fear_greed   : dict
        reddit       : dict
        detail       : list[str]
        summary      : str
    """
    global _sentiment_cache
    sekarang = time.time()

    # Cek cache
    if (_sentiment_cache["data"] is not None and
            sekarang - _sentiment_cache["waktu"] < _sentiment_cache["ttl"]):
        return _sentiment_cache["data"]

    print("  🧠 Menganalisis sentimen market (Reddit + F&G)...")

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

    # 2. Reddit Sentiment
    reddit = get_all_reddit_sentiment()
    if reddit:
        rata   = reddit["rata_gabung"]
        n_sub  = reddit["n_subreddit"]

        if rata >= 1.5:
            skor_buy += 2
            detail.append(f"Reddit BULLISH ({rata:+.2f}, {n_sub} sub)")
        elif rata >= 0.5:
            skor_buy += 1
            detail.append(f"Reddit sedikit bullish ({rata:+.2f})")
        elif rata <= -1.5:
            skor_sell += 2
            detail.append(f"Reddit BEARISH ({rata:+.2f})")
        elif rata <= -0.5:
            skor_sell += 1
            detail.append(f"Reddit sedikit bearish ({rata:+.2f})")
        else:
            detail.append(f"Reddit netral ({rata:+.2f})")

        print(f"  📱 Reddit: {rata:+.3f} ({n_sub} subreddits)")
    else:
        reddit = {"rata_gabung": 0, "n_subreddit": 0}

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
        f"Reddit:{reddit.get('rata_gabung', 0):+.2f} | "
        f"Sentiment:{sentiment}"
    )

    hasil = {
        "skor_buy" : min(skor_buy, 4),
        "skor_sell": min(skor_sell, 4),
        "sentiment": sentiment,
        "fear_greed": fg,
        "reddit"   : reddit,
        "detail"   : detail,
        "summary"  : summary
    }

    _sentiment_cache["data"]  = hasil
    _sentiment_cache["waktu"] = sekarang
    return hasil