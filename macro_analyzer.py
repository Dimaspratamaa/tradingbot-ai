# ============================================
# MACRO ANALYZER v1.0
# Sumber data makro ekonomi institusional-grade
#
# 1. FRED API (Federal Reserve Economic Data)
#    - Suku bunga Fed Funds
#    - Inflasi CPI
#    - GDP growth
#    - DXY (Dollar Index proxy)
#    - Treasury yields (2Y, 10Y)
#
# 2. Alpha Vantage
#    - Forex correlation (DXY proxy)
#    - Commodity prices (Gold, Oil)
#    - Market sentiment indicators
#
# Daftar API key GRATIS:
#   FRED     : https://fred.stlouisfed.org/docs/api/api_key.html
#   Alpha V  : https://www.alphavantage.co/support/#api-key
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
import os
from datetime import datetime, timedelta

# ── API KEYS ──────────────────────────────────
FRED_API_KEY    = os.environ.get("FRED_API_KEY", "be2d7af1d1c13770737a294411d14baa")
ALPHAV_API_KEY  = os.environ.get("ALPHAV_API_KEY", "DVMC0VXQKJEBYKYL")

# ── CACHE ─────────────────────────────────────
_macro_cache = {"data": None, "waktu": 0, "ttl": 3600}  # Cache 1 jam

# ── FRED SERIES IDs ───────────────────────────
FRED_SERIES = {
    "fed_rate"    : "FEDFUNDS",      # Fed Funds Rate
    "cpi"         : "CPIAUCSL",      # Consumer Price Index
    "gdp"         : "GDP",           # US GDP
    "unemployment": "UNRATE",        # Unemployment Rate
    "yield_2y"    : "DGS2",          # 2-Year Treasury
    "yield_10y"   : "DGS10",         # 10-Year Treasury
    "yield_spread": "T10Y2Y",        # 10Y-2Y Spread (recession indicator)
    "vix"         : "VIXCLS",        # VIX Volatility Index
}

# ══════════════════════════════════════════════
# 1. FRED API
# ══════════════════════════════════════════════

def get_fred_series(series_id, limit=2):
    """Ambil data series dari FRED API"""
    if not FRED_API_KEY:
        return None
    try:
        url    = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            "series_id"      : series_id,
            "api_key"        : FRED_API_KEY,
            "file_type"      : "json",
            "sort_order"     : "desc",
            "limit"          : limit,
            "observation_end": datetime.now().strftime("%Y-%m-%d")
        }
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        obs  = [o for o in data.get("observations", [])
                if o.get("value") != "."]
        if obs:
            return {
                "nilai"    : float(obs[0]["value"]),
                "nilai_prev": float(obs[1]["value"]) if len(obs) > 1 else None,
                "tanggal"  : obs[0]["date"],
                "series"   : series_id
            }
    except Exception as e:
        print(f"  ⚠️  FRED {series_id} error: {e}")
    return None

def get_fred_macro():
    """Ambil semua indikator makro dari FRED"""
    hasil = {}
    for nama, series_id in FRED_SERIES.items():
        data = get_fred_series(series_id)
        if data:
            hasil[nama] = data
        time.sleep(0.3)  # Rate limit FRED
    return hasil

# ══════════════════════════════════════════════
# 2. ALPHA VANTAGE
# ══════════════════════════════════════════════

def get_forex_rate(from_ccy="USD", to_ccy="EUR"):
    """Ambil kurs forex dari Alpha Vantage"""
    if not ALPHAV_API_KEY:
        return None
    try:
        url    = "https://www.alphavantage.co/query"
        params = {
            "function"    : "CURRENCY_EXCHANGE_RATE",
            "from_currency": from_ccy,
            "to_currency"  : to_ccy,
            "apikey"      : ALPHAV_API_KEY
        }
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        info = data.get("Realtime Currency Exchange Rate", {})
        if info:
            return {
                "rate"    : float(info.get("5. Exchange Rate", 0)),
                "dari"    : from_ccy,
                "ke"      : to_ccy,
                "waktu"   : info.get("6. Last Refreshed", "")
            }
    except Exception as e:
        print(f"  ⚠️  AlphaV forex error: {e}")
    return None

def get_commodity_price(symbol="WTI"):
    """
    Ambil harga komoditas dari Alpha Vantage.
    WTI = Minyak Brent, NATURAL_GAS, COPPER, dll
    """
    if not ALPHAV_API_KEY:
        return None
    try:
        url    = "https://www.alphavantage.co/query"
        params = {
            "function": "WTI" if symbol == "WTI" else symbol,
            "interval": "monthly",
            "apikey"  : ALPHAV_API_KEY
        }
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        items = data.get("data", [])
        if items:
            return {
                "nilai"    : float(items[0].get("value", 0)),
                "nilai_prev": float(items[1].get("value", 0)) if len(items) > 1 else None,
                "tanggal"  : items[0].get("date", ""),
                "symbol"   : symbol
            }
    except Exception as e:
        print(f"  ⚠️  AlphaV commodity error: {e}")
    return None

# ══════════════════════════════════════════════
# 3. FALLBACK TANPA API KEY (sumber publik gratis)
# ══════════════════════════════════════════════

def get_vix_free():
    """
    Ambil VIX dari Yahoo Finance (tanpa API key).
    ^VIX adalah ticker VIX di Yahoo.
    """
    try:
        url  = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?interval=1d&range=5d"
        hdrs = {"User-Agent": "Mozilla/5.0 TradingBot/2.0"}
        resp = requests.get(url, headers=hdrs, timeout=10)
        data = resp.json()
        closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
        closes = [c for c in closes if c is not None]
        if len(closes) >= 2:
            return {
                "nilai"     : closes[-1],
                "nilai_prev": closes[-2],
                "tanggal"   : "Yahoo",
                "series"    : "VIX_FREE"
            }
    except Exception as e:
        print(f"  ⚠️  VIX free error: {e}")
    return None

def get_yield_free():
    """
    Ambil US 10Y-2Y yield spread dari Yahoo Finance.
    ^TNX = 10Y Treasury, ^IRX = 13-week (proxy 2Y).
    """
    try:
        hasil = {}
        tickers = {"yield_10y": "%5ETNX", "yield_2y": "%5EIRX"}
        hdrs = {"User-Agent": "Mozilla/5.0 TradingBot/2.0"}
        for nama, ticker in tickers.items():
            url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d"
            resp = requests.get(url, headers=hdrs, timeout=10)
            data = resp.json()
            closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
            closes = [c for c in closes if c is not None]
            if closes:
                hasil[nama] = {"nilai": closes[-1],
                               "nilai_prev": closes[-2] if len(closes)>1 else closes[-1],
                               "tanggal": "Yahoo", "series": nama}
            time.sleep(0.3)

        if "yield_10y" in hasil and "yield_2y" in hasil:
            spread = hasil["yield_10y"]["nilai"] - hasil["yield_2y"]["nilai"]
            hasil["yield_spread"] = {
                "nilai": spread, "nilai_prev": None,
                "tanggal": "Yahoo", "series": "T10Y2Y_FREE"
            }
        return hasil
    except Exception as e:
        print(f"  ⚠️  Yield free error: {e}")
    return {}

def get_eurusd_free():
    """
    Ambil EUR/USD dari exchangerate-api (tanpa key, gratis).
    """
    try:
        url  = "https://open.er-api.com/v6/latest/USD"
        resp = requests.get(url, timeout=8)
        data = resp.json()
        eur  = data.get("rates", {}).get("EUR", 0)
        if eur > 0:
            # EUR/USD = 1 / (USD/EUR)
            eur_usd = 1 / eur
            return {"rate": eur_usd, "dari": "USD", "ke": "EUR", "waktu": "free"}
    except Exception as e:
        print(f"  ⚠️  EUR/USD free error: {e}")
    return None

def get_free_macro_data():
    """
    Kumpulkan data makro dari sumber gratis tanpa API key.
    Digunakan sebagai fallback jika FRED/AlphaV key tidak ada.
    """
    print("  📊 Mengambil data makro gratis (Yahoo Finance + ER-API)...")
    fred_data  = {}
    forex_data = None

    # VIX
    vix = get_vix_free()
    if vix:
        fred_data["vix"] = vix
        print(f"  ✅ VIX: {vix['nilai']:.1f}")

    # Yield curve
    yields = get_yield_free()
    if yields:
        fred_data.update(yields)
        if "yield_10y" in yields:
            print(f"  ✅ 10Y Yield: {yields['yield_10y']['nilai']:.2f}%")
        if "yield_spread" in yields:
            print(f"  ✅ Yield Spread (10Y-2Y): {yields['yield_spread']['nilai']:.2f}%")

    # EUR/USD (proxy DXY)
    forex_data = get_eurusd_free()
    if forex_data:
        print(f"  ✅ EUR/USD: {forex_data['rate']:.4f}")

    return fred_data, forex_data



def analisis_makro(fred_data, forex_data=None, commodity_data=None):
    """
    Terjemahkan data makro menjadi sinyal trading crypto.

    Logika:
    - Fed rate tinggi & naik  → bearish crypto (likuiditas ketat)
    - Fed rate turun          → bullish crypto (risk-on)
    - Yield curve inverted    → resesi → bearish
    - VIX tinggi (>30)        → panik → bearish jangka pendek
    - DXY kuat (USD naik)     → bearish crypto (inverse correlation)
    - Oil naik tajam          → inflasi → Fed hawkish → bearish
    """
    skor_buy  = 0
    skor_sell = 0
    detail    = []
    kondisi   = []

    # ── Fed Rate ──
    fed = fred_data.get("fed_rate")
    if fed:
        rate     = fed["nilai"]
        rate_prev = fed["nilai_prev"] or rate
        rate_chg  = rate - rate_prev

        if rate_chg < -0.1:  # Fed turunkan rate
            skor_buy += 2
            detail.append(f"🟢 Fed cut: {rate:.2f}% (dari {rate_prev:.2f}%)")
            kondisi.append("FED_DOVISH")
        elif rate_chg > 0.1:  # Fed naikkan rate
            skor_sell += 2
            detail.append(f"🔴 Fed hike: {rate:.2f}% (dari {rate_prev:.2f}%)")
            kondisi.append("FED_HAWKISH")
        elif rate > 5.0:  # Rate tinggi tapi stabil
            skor_sell += 1
            detail.append(f"🟡 Fed rate tinggi: {rate:.2f}%")
            kondisi.append("HIGH_RATE")
        else:
            detail.append(f"⚪ Fed rate: {rate:.2f}%")

    # ── Yield Curve ──
    spread = fred_data.get("yield_spread")
    if spread:
        spd = spread["nilai"]
        if spd < -0.5:  # Inverted yield curve = resesi
            skor_sell += 2
            detail.append(f"🔴 Yield curve inverted: {spd:.2f}% (resesi signal)")
            kondisi.append("YIELD_INVERTED")
        elif spd > 1.0:  # Normal curve = expansion
            skor_buy += 1
            detail.append(f"🟢 Yield curve normal: {spd:.2f}%")
            kondisi.append("EXPANSION")

    # ── VIX (Fear Index) ──
    vix = fred_data.get("vix")
    if vix:
        v = vix["nilai"]
        if v > 30:
            skor_sell += 2
            detail.append(f"🔴 VIX tinggi: {v:.1f} (panik pasar)")
            kondisi.append("HIGH_FEAR")
        elif v > 20:
            skor_sell += 1
            detail.append(f"🟡 VIX elevated: {v:.1f}")
        elif v < 15:
            skor_buy += 1
            detail.append(f"🟢 VIX rendah: {v:.1f} (risk-on)")
            kondisi.append("LOW_FEAR")

    # ── CPI/Inflasi ──
    cpi = fred_data.get("cpi")
    if cpi and cpi["nilai_prev"]:
        cpi_chg = ((cpi["nilai"] - cpi["nilai_prev"]) / cpi["nilai_prev"]) * 100
        if cpi_chg > 0.3:
            skor_sell += 1
            detail.append(f"🔴 Inflasi naik: {cpi_chg:+.2f}% MoM")
            kondisi.append("HIGH_INFLATION")
        elif cpi_chg < -0.1:
            skor_buy += 1
            detail.append(f"🟢 Inflasi turun: {cpi_chg:+.2f}% MoM")

    # ── Forex (DXY proxy via EUR/USD inverse) ──
    if forex_data:
        eur_usd = forex_data.get("rate", 0)
        if eur_usd > 0:
            # EUR/USD naik = USD lemah = bullish crypto
            if eur_usd > 1.10:
                skor_buy += 1
                detail.append(f"🟢 USD lemah (EUR/USD: {eur_usd:.4f})")
                kondisi.append("USD_WEAK")
            elif eur_usd < 1.05:
                skor_sell += 1
                detail.append(f"🔴 USD kuat (EUR/USD: {eur_usd:.4f})")
                kondisi.append("USD_STRONG")

    # ── Oil (korelasi inflasi) ──
    if commodity_data:
        oil = commodity_data.get("nilai", 0)
        oil_prev = commodity_data.get("nilai_prev", oil)
        if oil > 0 and oil_prev > 0:
            oil_chg = ((oil - oil_prev) / oil_prev) * 100
            if oil_chg > 5:
                skor_sell += 1
                detail.append(f"🔴 Oil naik tajam: ${oil:.1f} ({oil_chg:+.1f}%)")
            elif oil_chg < -5:
                skor_buy += 1
                detail.append(f"🟢 Oil turun: ${oil:.1f} ({oil_chg:+.1f}%)")

    # ── Tentukan kondisi makro keseluruhan ──
    net = skor_buy - skor_sell
    if net >= 3:
        sentimen = "MACRO_BULLISH"
    elif net >= 1:
        sentimen = "MACRO_SEDIKIT_BULLISH"
    elif net <= -3:
        sentimen = "MACRO_BEARISH"
    elif net <= -1:
        sentimen = "MACRO_SEDIKIT_BEARISH"
    else:
        sentimen = "MACRO_NETRAL"

    return {
        "skor_buy" : min(skor_buy, 4),
        "skor_sell": min(skor_sell, 4),
        "sentimen" : sentimen,
        "kondisi"  : kondisi,
        "detail"   : detail,
        "fred_raw" : fred_data,
        "summary"  : f"Macro:{sentimen} | " + " | ".join(detail[:3])
    }

# ══════════════════════════════════════════════
# FUNGSI UTAMA
# ══════════════════════════════════════════════

def get_macro_score():
    """
    Ambil semua data makro dan kembalikan sinyal.
    Cache 1 jam — data makro tidak berubah cepat.

    Prioritas sumber data:
    1. FRED API + AlphaVantage  → jika key tersedia (paling lengkap)
    2. Yahoo Finance + ER-API   → fallback gratis otomatis (tanpa key)
    """
    global _macro_cache
    sekarang = time.time()

    if (_macro_cache["data"] is not None and
            sekarang - _macro_cache["waktu"] < _macro_cache["ttl"]):
        return _macro_cache["data"]

    fred_data      = {}
    forex_data     = None
    commodity_data = None

    if FRED_API_KEY and ALPHAV_API_KEY:
        # Gunakan API key resmi jika tersedia
        print("  📊 Menganalisis kondisi makro (FRED + AlphaVantage)...")
        fred_data      = get_fred_macro()
        forex_data     = get_forex_rate("USD", "EUR")
        commodity_data = get_commodity_price("WTI")
    else:
        # Fallback gratis — Yahoo Finance + ER-API
        if not FRED_API_KEY:
            print("  ⚠️  FRED key kosong → pakai data gratis Yahoo Finance")
        fred_data, forex_data = get_free_macro_data()

    if not fred_data and not forex_data:
        print("  ⚠️  Semua sumber makro gagal — pakai default netral")
        hasil = _default_macro()
        _macro_cache["data"]  = hasil
        _macro_cache["waktu"] = sekarang
        return hasil

    hasil = analisis_makro(fred_data, forex_data, commodity_data)

    if hasil["detail"]:
        print(f"  📊 Macro: {hasil['sentimen']} | "
              f"Buy:{hasil['skor_buy']} Sell:{hasil['skor_sell']}")

    _macro_cache["data"]  = hasil
    _macro_cache["waktu"] = sekarang
    return hasil

def _default_macro():
    return {
        "skor_buy": 0, "skor_sell": 0,
        "sentimen": "MACRO_NETRAL", "kondisi": [],
        "detail": ["⚪ FRED/AlphaV API key belum diisi"],
        "fred_raw": {}, "summary": "Macro:NETRAL (no API key)"
    }