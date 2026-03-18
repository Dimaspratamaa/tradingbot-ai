# ============================================
# ON-CHAIN ANALYTICS MODULE v2.0
# Sumber: Fear & Greed + CoinGlass + CoinGecko
# ============================================

import requests
import time
import json

# ── FUNGSI: FEAR & GREED INDEX ────────────────
def get_fear_greed():
    try:
        url      = "https://api.alternative.me/fng/?limit=1"
        response = requests.get(url, timeout=10)
        data     = response.json()
        score    = int(data["data"][0]["value"])
        label    = data["data"][0]["value_classification"]

        if score <= 25:
            sinyal = "BUY_KUAT"
        elif score <= 45:
            sinyal = "BUY_LEMAH"
        elif score <= 55:
            sinyal = "NEUTRAL"
        elif score <= 75:
            sinyal = "SELL_LEMAH"
        else:
            sinyal = "SELL_KUAT"

        return {"score": score, "label": label,
                "sinyal": sinyal, "ok": True}
    except Exception as e:
        print(f"  ⚠️  Fear & Greed error: {e}")
        return {"score": 50, "label": "Neutral",
                "sinyal": "NEUTRAL", "ok": False}

# ── FUNGSI: FUNDING RATE (via CoinGlass) ──────
def get_funding_rate(symbol="BTC"):
    try:
        url      = "https://open-api.coinglass.com/public/v2/funding"
        response = requests.get(url, timeout=10)
        data     = response.json()

        for item in data.get("data", []):
            if item.get("symbol") == symbol:
                rate = float(item.get("fundingRate", 0)) * 100
                if rate < -0.01:
                    sinyal = "BUY"
                elif rate > 0.01:
                    sinyal = "SELL"
                else:
                    sinyal = "NEUTRAL"
                return {"rate": round(rate, 4),
                        "sinyal": sinyal, "ok": True}

        return {"rate": 0, "sinyal": "NEUTRAL", "ok": False}
    except Exception as e:
        print(f"  ⚠️  Funding Rate error: {e}")
        return {"rate": 0, "sinyal": "NEUTRAL", "ok": False}

# ── FUNGSI: LONG/SHORT RATIO (via CoinGlass) ──
def get_long_short_ratio(symbol="BTC"):
    try:
        url = (
            "https://open-api.coinglass.com/public/v2/"
            f"longShortCoin?symbol={symbol}&interval=1h&limit=1"
        )
        response = requests.get(url, timeout=10)
        data     = response.json()

        if data.get("data"):
            item      = data["data"][0]
            long_pct  = float(item.get("longRatio", 0.5)) * 100
            short_pct = float(item.get("shortRatio", 0.5)) * 100
            ratio     = long_pct / short_pct if short_pct > 0 else 1

            if ratio < 0.7:
                sinyal = "BUY"
            elif ratio > 1.5:
                sinyal = "SELL"
            else:
                sinyal = "NEUTRAL"

            return {"ratio": round(ratio, 4),
                    "long_pct": round(long_pct, 2),
                    "short_pct": round(short_pct, 2),
                    "sinyal": sinyal, "ok": True}

        return {"ratio": 1, "long_pct": 50,
                "short_pct": 50, "sinyal": "NEUTRAL", "ok": False}
    except Exception as e:
        print(f"  ⚠️  Long/Short error: {e}")
        return {"ratio": 1, "long_pct": 50,
                "short_pct": 50, "sinyal": "NEUTRAL", "ok": False}

# ── FUNGSI: OPEN INTEREST (via CoinGlass) ─────
def get_open_interest(symbol="BTC"):
    try:
        url      = f"https://open-api.coinglass.com/public/v2/openInterest?symbol={symbol}"
        response = requests.get(url, timeout=10)
        data     = response.json()

        if data.get("data"):
            oi = float(data["data"][0].get("openInterest", 0))
            return {"open_interest": round(oi, 2), "ok": True}

        return {"open_interest": 0, "ok": False}
    except Exception as e:
        print(f"  ⚠️  Open Interest error: {e}")
        return {"open_interest": 0, "ok": False}

# ── FUNGSI: BTC DOMINANCE (via CoinGecko) ─────
def get_btc_dominance():
    try:
        url      = "https://api.coingecko.com/api/v3/global"
        response = requests.get(url, timeout=10)
        data     = response.json()
        dom      = data["data"]["market_cap_percentage"]["btc"]

        if dom > 55:
            sinyal = "BTC_DOMINAN"
        elif dom < 45:
            sinyal = "ALTSEASON"
        else:
            sinyal = "NEUTRAL"

        return {"dominance": round(dom, 2),
                "sinyal": sinyal, "ok": True}
    except Exception as e:
        print(f"  ⚠️  BTC Dominance error: {e}")
        return {"dominance": 50, "sinyal": "NEUTRAL", "ok": False}

# ── FUNGSI UTAMA: GABUNGKAN SEMUA DATA ────────
def get_onchain_score():
    fg  = get_fear_greed()
    fr  = get_funding_rate()
    ls  = get_long_short_ratio()
    oi  = get_open_interest()
    dom = get_btc_dominance()

    skor_buy    = 0
    skor_sell   = 0
    detail_buy  = []
    detail_sell = []

    # ── Fear & Greed ──
    if fg["sinyal"] == "BUY_KUAT":
        skor_buy += 2
        detail_buy.append(
            f"🟢 Fear&Greed: {fg['score']} ({fg['label']}) - EXTREME FEAR")
    elif fg["sinyal"] == "BUY_LEMAH":
        skor_buy += 1
        detail_buy.append(
            f"🟡 Fear&Greed: {fg['score']} ({fg['label']}) - FEAR")
    elif fg["sinyal"] == "SELL_KUAT":
        skor_sell += 2
        detail_sell.append(
            f"🔴 Fear&Greed: {fg['score']} ({fg['label']}) - EXTREME GREED")
    elif fg["sinyal"] == "SELL_LEMAH":
        skor_sell += 1
        detail_sell.append(
            f"🟡 Fear&Greed: {fg['score']} ({fg['label']}) - GREED")

    # ── Funding Rate ──
    if fr["sinyal"] == "BUY":
        skor_buy += 1
        detail_buy.append(
            f"🟢 Funding Rate: {fr['rate']}% (Short squeeze)")
    elif fr["sinyal"] == "SELL":
        skor_sell += 1
        detail_sell.append(
            f"🔴 Funding Rate: {fr['rate']}% (Long squeeze)")

    # ── Long/Short Ratio ──
    if ls["sinyal"] == "BUY":
        skor_buy += 1
        detail_buy.append(
            f"🟢 L/S Ratio: {ls['ratio']} "
            f"(L:{ls['long_pct']}% S:{ls['short_pct']}%)")
    elif ls["sinyal"] == "SELL":
        skor_sell += 1
        detail_sell.append(
            f"🔴 L/S Ratio: {ls['ratio']} "
            f"(L:{ls['long_pct']}% S:{ls['short_pct']}%)")

    # ── BTC Dominance ──
    if dom["sinyal"] == "BTC_DOMINAN":
        skor_buy += 1
        detail_buy.append(
            f"🟢 BTC Dominance: {dom['dominance']}% (BTC kuat)")
    elif dom["sinyal"] == "ALTSEASON":
        skor_sell += 1
        detail_sell.append(
            f"🔴 BTC Dominance: {dom['dominance']}% (Altseason)")

    return {
        "skor_buy"     : skor_buy,
        "skor_sell"    : skor_sell,
        "detail_buy"   : detail_buy,
        "detail_sell"  : detail_sell,
        "fear_greed"   : fg,
        "funding_rate" : fr,
        "long_short"   : ls,
        "open_interest": oi,
        "btc_dominance": dom
    }

# ── TEST ──────────────────────────────────────
if __name__ == "__main__":
    print("=" * 55)
    print("   ON-CHAIN ANALYTICS TEST")
    print("=" * 55)

    hasil = get_onchain_score()

    print(f"\n📊 FEAR & GREED : {hasil['fear_greed']['score']}/100 "
          f"({hasil['fear_greed']['label']})")
    print(f"📈 FUNDING RATE : {hasil['funding_rate']['rate']}% "
          f"| Sinyal: {hasil['funding_rate']['sinyal']}")
    print(f"⚖️  L/S RATIO   : {hasil['long_short']['ratio']} "
          f"| Long: {hasil['long_short']['long_pct']}%")
    print(f"🌐 BTC DOMINANCE: {hasil['btc_dominance']['dominance']}% "
          f"| {hasil['btc_dominance']['sinyal']}")
    print(f"\n  Skor BUY  : {hasil['skor_buy']}")
    print(f"  Skor SELL : {hasil['skor_sell']}")

    if hasil['detail_buy']:
        print(f"\n  Detail BUY:")
        for d in hasil['detail_buy']:
            print(f"    {d}")
    if hasil['detail_sell']:
        print(f"\n  Detail SELL:")
        for d in hasil['detail_sell']:
            print(f"    {d}")