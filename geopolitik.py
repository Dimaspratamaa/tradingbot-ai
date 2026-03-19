# ============================================
# GEOPOLITICAL & NEWS SENTIMENT ANALYZER v3.0
# Sumber:
#   1. NewsAPI        → berita geopolitik global
#   2. Finnhub        → berita crypto & market
#   3. NewsData.io    → 92k+ sumber berita dunia
#   4. Free Crypto RSS → CoinDesk + CoinTelegraph
# ============================================

import requests
import time
import re
from datetime import datetime

# ── KONFIGURASI API ───────────────────────────
NEWS_API_KEY  = "bd6cd1c660d142a69b57fd2ca87436b5"
FINNHUB_KEY   = "d6ts24pr01qhkb45d920d6ts24pr01qhkb45d92g" 
NEWSDATA_KEY  = "pub_1047f4b52e224d68a50874bb740bdcf6"   

# ── CACHE ─────────────────────────────────────
_cache = {"data": None, "waktu": 0, "ttl": 600}

# ── KEYWORD BERBOBOT ──────────────────────────
KEYWORDS_NEGATIF = [
    ("nuclear war",5),("world war",5),("nuclear attack",5),
    ("missile strike",4),("invasion",4),("military attack",4),
    ("war declared",4),("armed conflict",3),("war",2),
    ("attack",1),("conflict",1),("sanctions",2),("embargo",3),
    ("iran nuclear",4),("north korea missile",4),
    ("russia ukraine war",4),("middle east war",4),
    ("taiwan china war",5),("market crash",4),
    ("financial crisis",4),("bank collapse",4),
    ("recession",3),("debt default",4),("hyperinflation",4),
    ("banking crisis",3),("crash",2),("collapse",2),
    ("crisis",2),("default",2),("inflation",1),
    ("tariff",1),("trade war",3),("crypto ban",4),
    ("ban bitcoin",4),("sec crackdown",3),("sec lawsuit",3),
    ("illegal crypto",3),("restrict crypto",2),("crackdown",2),
    ("ban",1),("trump tariff",3),("china tariff",3),
    ("fed rate hike",2),("interest rate hike",2),
    ("oil crisis",3),("energy crisis",3),
]

KEYWORDS_POSITIF = [
    ("rate cut",3),("fed cuts",3),("interest rate cut",3),
    ("stimulus",3),("economic recovery",2),("gdp growth",2),
    ("recovery",1),("bullish",2),("rally",2),("surge",1),
    ("bitcoin etf approved",4),("bitcoin etf",3),
    ("crypto etf",3),("institutional adoption",3),
    ("bitcoin reserve",4),("national bitcoin",4),
    ("crypto legal",3),("crypto approved",3),
    ("bitcoin legal tender",4),("crypto adoption",2),
    ("adoption",1),("institutional",2),("spot etf",3),
    ("bitcoin ath",3),("ceasefire",3),("peace deal",3),
    ("trade deal",2),("trade agreement",2),
    ("cooperation",1),("partnership",1),
    ("fed pivot",3),("dovish fed",3),
    ("soft landing",2),("inflation cooling",2),
]

KEYWORDS_CRYPTO = [
    "bitcoin","crypto","blockchain","ethereum","btc","eth",
    "defi","digital asset","cryptocurrency","altcoin",
    "token","stablecoin","web3","binance","coinbase","solana"
]

# ══════════════════════════════════════════════
# SUMBER 1: NEWSAPI
# ══════════════════════════════════════════════

def get_berita_newsapi():
    try:
        queries = [
            "cryptocurrency bitcoin market regulation",
            "federal reserve interest rate decision",
            "geopolitical risk global economy",
            "bitcoin institutional adoption",
            "trump tariff economy trade",
        ]
        semua = []; seen = set()
        for q in queries:
            url  = (f"https://newsapi.org/v2/everything?"
                    f"q={requests.utils.quote(q)}&language=en&"
                    f"sortBy=publishedAt&pageSize=5&apiKey={NEWS_API_KEY}")
            resp = requests.get(url, timeout=10)
            data = resp.json()
            if data.get("status") == "ok":
                for art in data.get("articles", []):
                    judul = art.get("title","") or ""
                    key   = judul[:50].lower()
                    if key in seen or not judul: continue
                    seen.add(key)
                    semua.append({
                        "judul"  : judul,
                        "desc"   : art.get("description","") or "",
                        "sumber" : art.get("source",{}).get("name","NewsAPI"),
                        "waktu"  : art.get("publishedAt",""),
                        "jam_lalu": _jam_lalu_iso(art.get("publishedAt","")),
                        "asal"   : "newsapi"
                    })
        return semua
    except Exception as e:
        print(f"  ⚠️  NewsAPI error: {e}"); return []

# ══════════════════════════════════════════════
# SUMBER 2: FINNHUB (ganti CryptoPanic)
# ══════════════════════════════════════════════

def get_berita_finnhub():
    if not FINNHUB_KEY:
        return []
    try:
        berita = []; seen = set()
        for cat in ["crypto", "general"]:
            url  = (f"https://finnhub.io/api/v1/news?"
                    f"category={cat}&token={FINNHUB_KEY}")
            resp = requests.get(url, timeout=10)
            data = resp.json()
            if not isinstance(data, list): continue
            for item in data[:15]:
                judul = item.get("headline","") or ""
                key   = judul[:50].lower()
                if key in seen or not judul: continue
                seen.add(key)
                ts       = item.get("datetime", 0)
                jam_lalu = (time.time() - ts) / 3600 if ts else 99
                waktu_str = datetime.fromtimestamp(ts).strftime(
                    "%Y-%m-%dT%H:%M:%SZ") if ts else ""
                berita.append({
                    "judul"  : judul,
                    "desc"   : item.get("summary","") or "",
                    "sumber" : item.get("source","Finnhub"),
                    "waktu"  : waktu_str,
                    "jam_lalu": jam_lalu,
                    "asal"   : "finnhub"
                })
        print(f"  📰 Finnhub: {len(berita)} berita")
        return berita
    except Exception as e:
        print(f"  ⚠️  Finnhub error: {e}"); return []

# ══════════════════════════════════════════════
# SUMBER 3: NEWSDATA.IO
# ══════════════════════════════════════════════

def get_berita_newsdata():
    if not NEWSDATA_KEY:
        return []
    try:
        berita = []; seen = set()
        queries = [
            "bitcoin cryptocurrency",
            "geopolitical risk economy",
            "federal reserve interest rate",
        ]
        for q in queries:
            url  = (f"https://newsdata.io/api/1/latest?"
                    f"apikey={NEWSDATA_KEY}&"
                    f"q={requests.utils.quote(q)}&"
                    f"language=en&category=business,politics,world")
            resp = requests.get(url, timeout=10)
            data = resp.json()
            if data.get("status") != "success": continue
            for art in data.get("results", [])[:8]:
                judul = art.get("title","") or ""
                key   = judul[:50].lower()
                if key in seen or not judul: continue
                seen.add(key)
                waktu_str = art.get("pubDate","")
                berita.append({
                    "judul"  : judul,
                    "desc"   : art.get("description","") or "",
                    "sumber" : art.get("source_name","NewsData"),
                    "waktu"  : waktu_str,
                    "jam_lalu": _jam_lalu_iso(waktu_str),
                    "asal"   : "newsdata"
                })
        print(f"  📰 NewsData.io: {len(berita)} berita")
        return berita
    except Exception as e:
        print(f"  ⚠️  NewsData error: {e}"); return []

# ══════════════════════════════════════════════
# SUMBER 4: FREE CRYPTO RSS (backup tanpa key)
# ══════════════════════════════════════════════

def get_berita_rss():
    try:
        berita = []; seen = set()
        feeds  = [
            ("https://www.coindesk.com/arc/outboundfeeds/rss/", "CoinDesk"),
            ("https://cointelegraph.com/rss",                   "CoinTelegraph"),
        ]
        for url, nama in feeds:
            try:
                resp    = requests.get(url, timeout=8,
                    headers={"User-Agent": "TradingBot/3.0"})
                content = resp.text
                items   = re.findall(r'<item>(.*?)</item>',
                    content, re.DOTALL)[:10]
                for item in items:
                    m = re.search(
                        r'<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>',
                        item)
                    if not m: continue
                    judul = m.group(1).strip()
                    if not judul or judul in seen: continue
                    seen.add(judul)
                    dm = re.search(r'<pubDate>(.*?)</pubDate>', item)
                    waktu_str = dm.group(1).strip() if dm else ""
                    berita.append({
                        "judul"  : judul[:200],
                        "desc"   : "",
                        "sumber" : nama,
                        "waktu"  : waktu_str,
                        "jam_lalu": _jam_lalu_rss(waktu_str),
                        "asal"   : f"rss_{nama.lower().replace(' ','_')}"
                    })
            except Exception as e:
                print(f"  ⚠️  RSS {nama}: {e}")
        print(f"  📰 Free RSS: {len(berita)} berita")
        return berita
    except Exception as e:
        print(f"  ⚠️  RSS error: {e}"); return []

# ── HELPER ────────────────────────────────────

def _jam_lalu_iso(s):
    try:
        dt = datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S")
        return (datetime.utcnow() - dt).total_seconds() / 3600
    except: return 99

def _jam_lalu_rss(s):
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(s)
        return (datetime.now(dt.tzinfo) - dt).total_seconds() / 3600
    except: return 99

def _sumber_bobot(asal):
    return {"finnhub":1.4,"newsdata":1.3,"newsapi":1.2,
            "rss_coindesk":1.3,"rss_cointelegraph":1.2}.get(asal,1.0)

# ══════════════════════════════════════════════
# ANALISIS SENTIMENT
# ══════════════════════════════════════════════

def analisis_sentiment(teks, jam_lalu=99):
    if not teks: return 0.0
    teks_lower = teks.lower()
    skor = 0.0
    if jam_lalu < 2:    fw = 2.0
    elif jam_lalu < 6:  fw = 1.5
    elif jam_lalu < 24: fw = 1.2
    else:               fw = 1.0
    for kata, bobot in KEYWORDS_NEGATIF:
        if kata in teks_lower: skor -= bobot * fw
    for kata, bobot in KEYWORDS_POSITIF:
        if kata in teks_lower: skor += bobot * fw
    return skor

def _deduplikasi(scored):
    hasil = []; seen = set()
    for b in scored:
        key = frozenset(b["judul"].lower().split()[:5])
        if key not in seen:
            seen.add(key); hasil.append(b)
    return hasil

# ══════════════════════════════════════════════
# FUNGSI UTAMA
# ══════════════════════════════════════════════

def get_geo_score():
    global _cache
    sekarang = time.time()
    if _cache["data"] is not None and sekarang-_cache["waktu"] < _cache["ttl"]:
        return _cache["data"]

    print("  🌍 Menganalisis geopolitik v3.0 "
          "(NewsAPI+Finnhub+NewsData+RSS)...")

    # Kumpulkan dari semua sumber
    sumber_aktif = []
    semua        = []

    b = get_berita_newsapi()
    if b: semua.extend(b); sumber_aktif.append(f"NewsAPI({len(b)})")

    b = get_berita_finnhub()
    if b: semua.extend(b); sumber_aktif.append(f"Finnhub({len(b)})")

    b = get_berita_newsdata()
    if b: semua.extend(b); sumber_aktif.append(f"NewsData({len(b)})")

    b = get_berita_rss()
    if b: semua.extend(b); sumber_aktif.append(f"RSS({len(b)})")

    if not semua:
        print("  ⚠️  Tidak ada berita, pakai default NETRAL")
        hasil = _default_result()
        _cache["data"] = hasil; _cache["waktu"] = sekarang
        return hasil

    # Scoring
    scored = []
    for b in semua:
        teks     = f"{b['judul']} {b.get('desc','')}"
        skor     = analisis_sentiment(teks, b.get("jam_lalu",99))
        skor    *= _sumber_bobot(b.get("asal",""))
        if any(k in teks.lower() for k in KEYWORDS_CRYPTO):
            skor *= 1.2
        scored.append({**b, "skor_final": round(skor, 2)})

    scored     = _deduplikasi(scored)
    total_skor = sum(b["skor_final"] for b in scored)
    n_berita   = len(scored)
    rata       = total_skor / max(n_berita, 1)

    sp = [b for b in scored if b["skor_final"] >  4]
    pp = [b for b in scored if 0 < b["skor_final"] <= 4]
    np_ = [b for b in scored if b["skor_final"] == 0]
    nn = [b for b in scored if -4 <= b["skor_final"] < 0]
    sn = [b for b in scored if b["skor_final"] < -4]

    if rata >= 1.5:    sentiment = "SANGAT_POSITIF"
    elif rata >= 0.5:  sentiment = "POSITIF"
    elif rata >= 0.2:  sentiment = "SEDIKIT_POSITIF"
    elif rata <= -1.5: sentiment = "SANGAT_NEGATIF"
    elif rata <= -0.5: sentiment = "NEGATIF"
    elif rata <= -0.2: sentiment = "SEDIKIT_NEGATIF"
    else:              sentiment = "NETRAL"

    skor_buy = skor_sell = 0
    if rata >= 1.5:    skor_buy  = 3
    elif rata >= 0.8:  skor_buy  = 2
    elif rata >= 0.3:  skor_buy  = 1
    if rata <= -1.5:   skor_sell = 3
    elif rata <= -0.8: skor_sell = 2
    elif rata <= -0.3: skor_sell = 1

    # Alert
    alert = False; alert_pesan = ""
    for b in sorted(scored, key=lambda x: abs(x["skor_final"]), reverse=True):
        if abs(b["skor_final"]) >= 10:
            alert = True
            emoji = "🔴" if b["skor_final"] < 0 else "🟢"
            alert_pesan = (
                f"{emoji} <b>BERITA BESAR TERDETEKSI!</b>\n"
                f"📰 {b['judul'][:100]}\n"
                f"📊 Impact: {b['skor_final']:+.1f}\n"
                f"🗞️ {b.get('sumber','?')} | "
                f"{b.get('jam_lalu',99):.0f} jam lalu"
            )
            break

    top_berita = sorted(scored, key=lambda x: abs(x["skor_final"]),
                        reverse=True)[:5]

    hasil = {
        "skor_buy"   : skor_buy,
        "skor_sell"  : skor_sell,
        "detail_buy" : [f"🌍 {sentiment}: rata {rata:+.2f}"] if skor_buy  else [],
        "detail_sell": [f"⚠️ {sentiment}: rata {rata:+.2f}"] if skor_sell else [],
        "sentiment"  : sentiment,
        "total_skor" : round(total_skor, 2),
        "rata_skor"  : round(rata, 3),
        "n_berita"   : n_berita,
        "top_berita" : top_berita,
        "alert"      : alert,
        "alert_pesan": alert_pesan,
        "sumber_aktif": sumber_aktif,
        "breakdown"  : {
            "sangat_positif": len(sp), "positif": len(pp),
            "netral": len(np_), "negatif": len(nn),
            "sangat_negatif": len(sn)
        }
    }

    _cache["data"] = hasil; _cache["waktu"] = sekarang
    return hasil

def _default_result():
    return {
        "skor_buy":0,"skor_sell":0,"detail_buy":[],"detail_sell":[],
        "sentiment":"NETRAL","total_skor":0,"rata_skor":0.0,
        "n_berita":0,"top_berita":[],"alert":False,"alert_pesan":"",
        "sumber_aktif":[],"breakdown":{
            "sangat_positif":0,"positif":0,"netral":0,
            "negatif":0,"sangat_negatif":0}
    }

# ── TEST ──────────────────────────────────────
if __name__ == "__main__":
    print("="*60)
    print("   GEOPOLITICAL NEWS SENTIMENT ANALYZER v3.0")
    print("   NewsAPI + Finnhub + NewsData.io + Free RSS")
    print("="*60)
    hasil = get_geo_score()
    print(f"\n📰 Total berita  : {hasil['n_berita']}")
    print(f"🗞️  Sumber aktif : {', '.join(hasil['sumber_aktif'])}")
    print(f"📊 Sentiment     : {hasil['sentiment']}")
    print(f"📈 Rata skor     : {hasil['rata_skor']:+.3f}")
    print(f"  ✅ Skor BUY  : +{hasil['skor_buy']}")
    print(f"  🛑 Skor SELL : -{hasil['skor_sell']}")
    print(f"\n🏆 Top Berita:")
    for i, b in enumerate(hasil["top_berita"], 1):
        em = "🟢" if b["skor_final"]>0 else ("🔴" if b["skor_final"]<0 else "⚪")
        print(f"  {i}. {em} [{b['sumber']}] {b['skor_final']:+.1f}")
        print(f"     {b['judul'][:65]}")
    if hasil["alert"]:
        print(f"\n🚨 ALERT: {hasil['alert_pesan']}")