# ============================================
# GEOPOLITICAL & NEWS SENTIMENT ANALYZER v2.0
# Sumber: NewsAPI + CryptoPanic (Free/Pro)
# Upgrade: Weighted scoring, alert threshold,
#          skor_sell integration, smarter cache
# ============================================

import requests
import time
import json
from datetime import datetime, timedelta

# ── KONFIGURASI ───────────────────────────────
NEWS_API_KEY    = "bd6cd1c660d142a69b57fd2ca87436b5"
CRYPTOPANIC_KEY = ""   # Kosong = pakai free public API

# ── CACHE INTERNAL ────────────────────────────
_cache = {
    "data" : None,
    "waktu": 0,
    "ttl"  : 600   # 10 menit (hemat API limit)
}

# ── KEYWORD BERBOBOT ─────────────────────────
# Format: (keyword, bobot)
# Bobot lebih tinggi = dampak lebih kuat
KEYWORDS_NEGATIF = [
    # ── Konflik & Perang (dampak tinggi) ──
    ("nuclear war",          5),
    ("world war",            5),
    ("nuclear attack",       5),
    ("missile strike",       4),
    ("invasion",             4),
    ("military attack",      4),
    ("war declared",         4),
    ("armed conflict",       3),
    ("war",                  2),
    ("attack",               1),
    ("conflict",             1),
    ("sanctions",            2),
    ("embargo",              3),
    ("iran nuclear",         4),
    ("north korea missile",  4),
    ("russia ukraine war",   4),
    ("middle east war",      4),
    ("taiwan china war",     5),

    # ── Ekonomi Negatif ──
    ("market crash",         4),
    ("financial crisis",     4),
    ("bank collapse",        4),
    ("recession",            3),
    ("debt default",         4),
    ("hyperinflation",       4),
    ("banking crisis",       3),
    ("crash",                2),
    ("collapse",             2),
    ("crisis",               2),
    ("default",              2),
    ("inflation",            1),
    ("tariff",               1),
    ("trade war",            3),

    # ── Regulasi Crypto Negatif ──
    ("crypto ban",           4),
    ("ban bitcoin",          4),
    ("ban crypto",           4),
    ("sec crackdown",        3),
    ("sec lawsuit",          3),
    ("illegal crypto",       3),
    ("crypto illegal",       3),
    ("restrict crypto",      2),
    ("regulate crypto",      2),
    ("crackdown",            2),
    ("ban",                  1),
]

KEYWORDS_POSITIF = [
    # ── Ekonomi Positif ──
    ("rate cut",             3),
    ("interest rate cut",    3),
    ("fed cuts",             3),
    ("stimulus package",     3),
    ("economic recovery",    2),
    ("gdp growth",           2),
    ("recovery",             1),
    ("growth",               1),
    ("bullish",              2),
    ("rally",                2),
    ("surge",                1),

    # ── Crypto Positif ──
    ("bitcoin etf approved", 4),
    ("bitcoin etf",          3),
    ("crypto etf",           3),
    ("institutional adoption", 3),
    ("bitcoin reserve",      4),
    ("national bitcoin",     4),
    ("crypto legal",         3),
    ("crypto approved",      3),
    ("bitcoin legal tender", 4),
    ("crypto adoption",      2),
    ("adoption",             1),
    ("institutional",        2),
    ("spot etf",             3),

    # ── Geopolitik Positif ──
    ("ceasefire",            3),
    ("peace deal",           3),
    ("trade deal",           2),
    ("trade agreement",      2),
    ("peace agreement",      3),
    ("cooperation",          1),
    ("partnership",          1),
]

# Kata kunci crypto-specific untuk filter relevansi
KEYWORDS_CRYPTO_RELEVAN = [
    "bitcoin", "crypto", "blockchain", "ethereum",
    "btc", "eth", "defi", "digital asset",
    "cryptocurrency", "altcoin", "token", "stablecoin"
]

# ── FUNGSI: AMBIL BERITA NEWSAPI ──────────────
def get_berita_global():
    """
    Ambil berita geopolitik & ekonomi global dari NewsAPI.
    Menggunakan beberapa query untuk cakupan lebih luas.
    """
    try:
        queries = [
            "cryptocurrency bitcoin market regulation",
            "federal reserve interest rate decision",
            "geopolitical risk global economy",
            "war conflict economic impact",
            "crypto SEC regulation approval",
            "bitcoin institutional adoption",
        ]

        semua_berita = []
        seen_titles  = set()

        for query in queries:
            url = (
                "https://newsapi.org/v2/everything?"
                f"q={requests.utils.quote(query)}&"
                "language=en&"
                "sortBy=publishedAt&"
                "pageSize=5&"
                f"apiKey={NEWS_API_KEY}"
            )
            resp = requests.get(url, timeout=10)
            data = resp.json()

            if data.get("status") == "ok":
                for art in data.get("articles", []):
                    judul = art.get("title", "") or ""
                    # Deduplikasi
                    key = judul[:50].lower()
                    if key in seen_titles or not judul:
                        continue
                    seen_titles.add(key)

                    # Hitung umur berita
                    waktu_str = art.get("publishedAt", "")
                    jam_lalu  = _hitung_jam_lalu(waktu_str)

                    semua_berita.append({
                        "judul"   : judul,
                        "desc"    : art.get("description", "") or "",
                        "sumber"  : art.get("source", {}).get("name", ""),
                        "waktu"   : waktu_str,
                        "jam_lalu": jam_lalu,
                        "asal"    : "newsapi"
                    })

        return semua_berita

    except Exception as e:
        print(f"  ⚠️  NewsAPI error: {e}")
        return []


# ── FUNGSI: AMBIL BERITA CRYPTOPANIC ──────────
def get_berita_crypto():
    """
    Ambil berita crypto dari CryptoPanic.
    - Jika ada API key → pakai endpoint pro
    - Jika tidak ada   → pakai public free endpoint
    """
    try:
        if CRYPTOPANIC_KEY:
            # ── Mode Pro (dengan key) ──
            url = (
                "https://cryptopanic.com/api/v1/posts/?"
                f"auth_token={CRYPTOPANIC_KEY}&"
                "currencies=BTC,ETH,BNB,SOL&"
                "filter=important&"
                "public=true"
            )
        else:
            # ── Mode Free (tanpa key) ──
            url = (
                "https://cryptopanic.com/api/free/v1/posts/?"
                "public=true"
            )

        resp = requests.get(url, timeout=10)
        data = resp.json()

        berita = []
        for item in data.get("results", [])[:15]:
            judul    = item.get("title", "") or ""
            waktu_str = item.get("published_at", "")
            jam_lalu  = _hitung_jam_lalu(waktu_str)

            # Votes dari CryptoPanic (indikator kepentingan)
            votes    = item.get("votes", {})
            bullish  = votes.get("positive", 0)
            bearish  = votes.get("negative", 0)

            if not judul:
                continue

            berita.append({
                "judul"   : judul,
                "desc"    : "",
                "sumber"  : "CryptoPanic",
                "waktu"   : waktu_str,
                "jam_lalu": jam_lalu,
                "votes_bull": bullish,
                "votes_bear": bearish,
                "asal"    : "cryptopanic"
            })

        return berita

    except Exception as e:
        print(f"  ⚠️  CryptoPanic error: {e}")
        return []


# ── HELPER: HITUNG JAM LALU ───────────────────
def _hitung_jam_lalu(waktu_str):
    """Hitung berapa jam yang lalu berita diterbitkan"""
    try:
        # Format ISO: 2024-01-15T10:30:00Z
        dt = datetime.strptime(waktu_str[:19], "%Y-%m-%dT%H:%M:%S")
        selisih = datetime.utcnow() - dt
        return selisih.total_seconds() / 3600
    except:
        return 99  # Default: anggap lama


# ── FUNGSI: ANALISIS SENTIMENT (WEIGHTED) ─────
def analisis_sentiment(teks, jam_lalu=99):
    """
    Analisis sentiment teks dengan bobot keyword.
    Berita lebih baru mendapat bobot waktu lebih tinggi.
    Return: skor float (bisa negatif atau positif)
    """
    if not teks:
        return 0.0

    teks_lower = teks.lower()
    skor       = 0.0

    # Faktor waktu: berita < 6 jam = 1.5x, < 24 jam = 1.2x, lainnya = 1.0x
    if jam_lalu < 6:
        faktor_waktu = 1.5
    elif jam_lalu < 24:
        faktor_waktu = 1.2
    else:
        faktor_waktu = 1.0

    # Hitung skor negatif
    for kata, bobot in KEYWORDS_NEGATIF:
        if kata in teks_lower:
            skor -= bobot * faktor_waktu

    # Hitung skor positif
    for kata, bobot in KEYWORDS_POSITIF:
        if kata in teks_lower:
            skor += bobot * faktor_waktu

    return skor


# ── FUNGSI: CEK RELEVANSI CRYPTO ─────────────
def is_relevan_crypto(teks):
    """Cek apakah berita relevan untuk crypto market"""
    teks_lower = teks.lower()
    return any(k in teks_lower for k in KEYWORDS_CRYPTO_RELEVAN)


# ── FUNGSI: VOTING SCORE CRYPTOPANIC ─────────
def _skor_dari_votes(bullish, bearish):
    """
    Konversi votes CryptoPanic ke skor.
    Net votes yang tinggi = sinyal lebih kuat.
    """
    net   = bullish - bearish
    total = bullish + bearish
    if total == 0:
        return 0
    rasio = net / total
    # Scale ke -3 sampai +3
    return round(rasio * 3, 2)


# ── FUNGSI: GET GEO SCORE (MAIN) ──────────────
def get_geo_score():
    """
    Fungsi utama: ambil semua berita, analisis,
    dan kembalikan skor untuk keputusan trading.

    Return dict:
      skor_buy   : int (0-4)  → tambahan skor beli
      skor_sell  : int (0-4)  → tambahan skor jual / block beli
      sentiment  : str
      rata_skor  : float
      n_berita   : int
      top_berita : list
      breakdown  : dict
      alert      : bool  → True jika ada berita sangat impactful
      alert_pesan: str
    """
    global _cache

    # ── Cek cache ──
    sekarang = time.time()
    if (_cache["data"] is not None and
            sekarang - _cache["waktu"] < _cache["ttl"]):
        return _cache["data"]

    print("  🌍 Menganalisis berita geopolitik & crypto...")

    # ── Ambil semua berita ──
    berita_global = get_berita_global()
    berita_crypto = get_berita_crypto()
    semua_berita  = berita_global + berita_crypto

    # ── Default jika tidak ada berita ──
    if not semua_berita:
        print("  ⚠️  Tidak ada berita, pakai data default (NETRAL)")
        hasil = _default_result()
        _cache["data"]  = hasil
        _cache["waktu"] = sekarang
        return hasil

    # ── Analisis setiap berita ──
    scored = []
    for b in semua_berita:
        teks     = f"{b['judul']} {b.get('desc', '')}"
        jam_lalu = b.get("jam_lalu", 99)
        skor     = analisis_sentiment(teks, jam_lalu)

        # Bonus dari votes CryptoPanic
        if b.get("asal") == "cryptopanic":
            vote_skor = _skor_dari_votes(
                b.get("votes_bull", 0),
                b.get("votes_bear", 0)
            )
            skor += vote_skor

        # Bonus relevansi crypto
        if is_relevan_crypto(teks):
            skor *= 1.2

        scored.append({**b, "skor_final": round(skor, 2)})

    # ── Statistik ──
    total_skor = sum(b["skor_final"] for b in scored)
    n_berita   = len(scored)
    rata       = total_skor / max(n_berita, 1)

    positif      = [b for b in scored if b["skor_final"] >  2]
    sedikit_pos  = [b for b in scored if 0 < b["skor_final"] <= 2]
    netral       = [b for b in scored if b["skor_final"] == 0]
    sedikit_neg  = [b for b in scored if -2 <= b["skor_final"] < 0]
    negatif      = [b for b in scored if b["skor_final"] < -2]

    # ── Tentukan sentiment ──
    if rata >= 1.0:
        sentiment = "SANGAT_POSITIF"
    elif rata >= 0.3:
        sentiment = "POSITIF"
    elif rata >= 0.1:
        sentiment = "SEDIKIT_POSITIF"
    elif rata <= -1.0:
        sentiment = "SANGAT_NEGATIF"
    elif rata <= -0.3:
        sentiment = "NEGATIF"
    elif rata <= -0.1:
        sentiment = "SEDIKIT_NEGATIF"
    else:
        sentiment = "NETRAL"

    # ── Hitung skor buy/sell ──
    skor_buy  = 0
    skor_sell = 0

    if rata >= 1.0:
        skor_buy = 3
    elif rata >= 0.5:
        skor_buy = 2
    elif rata >= 0.2:
        skor_buy = 1

    if rata <= -1.0:
        skor_sell = 3
    elif rata <= -0.5:
        skor_sell = 2
    elif rata <= -0.2:
        skor_sell = 1

    # ── Deteksi berita SANGAT impactful (alert) ──
    alert       = False
    alert_pesan = ""
    for b in scored:
        if abs(b["skor_final"]) >= 8:
            alert       = True
            emoji       = "🔴" if b["skor_final"] < 0 else "🟢"
            alert_pesan = (
                f"{emoji} <b>BERITA BESAR TERDETEKSI!</b>\n"
                f"📰 {b['judul'][:100]}\n"
                f"📊 Impact Score: {b['skor_final']:+.1f}\n"
                f"🕐 {b.get('jam_lalu', '?'):.0f} jam lalu"
            )
            break  # Hanya ambil yang paling impactful

    # ── Top 5 berita paling berpengaruh ──
    top_berita = sorted(
        scored,
        key=lambda x: abs(x["skor_final"]),
        reverse=True
    )[:5]

    # ── Detail untuk log ──
    detail_buy  = []
    detail_sell = []

    if skor_buy > 0:
        detail_buy.append(
            f"🌍 Geo {sentiment}: "
            f"{len(positif)+len(sedikit_pos)} berita positif "
            f"(rata: {rata:+.2f})"
        )
    if skor_sell > 0:
        detail_sell.append(
            f"⚠️ Geo {sentiment}: "
            f"{len(negatif)+len(sedikit_neg)} berita negatif "
            f"(rata: {rata:+.2f})"
        )

    hasil = {
        "skor_buy"   : skor_buy,
        "skor_sell"  : skor_sell,
        "detail_buy" : detail_buy,
        "detail_sell": detail_sell,
        "sentiment"  : sentiment,
        "total_skor" : round(total_skor, 2),
        "rata_skor"  : round(rata, 3),
        "n_berita"   : n_berita,
        "top_berita" : top_berita,
        "alert"      : alert,
        "alert_pesan": alert_pesan,
        "breakdown"  : {
            "sangat_positif": len(positif),
            "positif"       : len(sedikit_pos),
            "netral"        : len(netral),
            "negatif"       : len(sedikit_neg),
            "sangat_negatif": len(negatif)
        }
    }

    # ── Simpan ke cache ──
    _cache["data"]  = hasil
    _cache["waktu"] = sekarang

    return hasil


def _default_result():
    return {
        "skor_buy"   : 0,
        "skor_sell"  : 0,
        "detail_buy" : [],
        "detail_sell": [],
        "sentiment"  : "NETRAL",
        "total_skor" : 0,
        "rata_skor"  : 0.0,
        "n_berita"   : 0,
        "top_berita" : [],
        "alert"      : False,
        "alert_pesan": "",
        "breakdown"  : {
            "sangat_positif": 0,
            "positif"       : 0,
            "netral"        : 0,
            "negatif"       : 0,
            "sangat_negatif": 0
        }
    }


# ── TEST ──────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("   GEOPOLITICAL NEWS SENTIMENT ANALYZER v2.0")
    print("=" * 60)

    hasil = get_geo_score()

    print(f"\n📰 Total berita   : {hasil['n_berita']}")
    print(f"📊 Sentiment      : {hasil['sentiment']}")
    print(f"📈 Rata skor      : {hasil['rata_skor']:+.3f}")
    print(f"\n📊 Breakdown:")
    bd = hasil["breakdown"]
    print(f"  🟢 Sangat positif : {bd['sangat_positif']}")
    print(f"  🟡 Positif        : {bd['positif']}")
    print(f"  ⚪ Netral          : {bd['netral']}")
    print(f"  🟠 Negatif        : {bd['negatif']}")
    print(f"  🔴 Sangat negatif : {bd['sangat_negatif']}")

    print(f"\n🏆 Top Berita Berpengaruh:")
    for i, b in enumerate(hasil["top_berita"], 1):
        emoji = "🟢" if b["skor_final"] > 0 else ("🔴" if b["skor_final"] < 0 else "⚪")
        print(f"  {i}. {emoji} [{b['sumber']}] score:{b['skor_final']:+.1f}")
        print(f"     {b['judul'][:70]}")

    print(f"\n  ✅ Skor BUY  : +{hasil['skor_buy']}")
    print(f"  🛑 Skor SELL : -{hasil['skor_sell']}")

    if hasil["alert"]:
        print(f"\n  🚨 ALERT AKTIF!")
        print(f"  {hasil['alert_pesan']}")