# ============================================
# WHALE TRACKER v1.0
# Monitor transaksi besar on-chain
# Sumber: Etherscan + BSCScan + public APIs
# ============================================

import requests
import time
from datetime import datetime

# ── KONFIGURASI ───────────────────────────────
WHALE_MIN_USD      = 500_000   # Transaksi > $500k = whale
WHALE_ALERT_USD    = 5_000_000 # Transaksi > $5jt = alert
CACHE_TTL          = 300       # Cache 5 menit

_whale_cache = {"data": None, "waktu": 0}

# Contract addresses token utama
TOKEN_CONTRACTS = {
    "BTCUSDT" : "bitcoin",
    "ETHUSDT" : "ethereum",
    "BNBUSDT" : "binancecoin",
    "SOLUSDT" : "solana",
    "XRPUSDT" : "ripple",
    "ADAUSDT" : "cardano",
    "AVAXUSDT": "avalanche-2",
    "DOTUSDT" : "polkadot",
    "LINKUSDT": "chainlink",
}

# ══════════════════════════════════════════════
# 1. LARGE TRANSACTIONS (via public APIs)
# ══════════════════════════════════════════════

def get_whale_transactions():
    """
    Ambil transaksi besar dari berbagai sumber publik.
    Menggunakan whale-alert.io public feed dan
    CoinGecko large transactions.
    """
    try:
        transaksi = []

        # WhaleAlert public RSS/JSON
        url  = "https://api.whale-alert.io/v1/transactions"
        params = {
            "api_key": "free",  # Public endpoint terbatas
            "min_value": WHALE_MIN_USD,
            "limit": 20
        }
        try:
            resp = requests.get(url, params=params, timeout=8)
            if resp.status_code == 200:
                data = resp.json()
                for t in data.get("transactions", []):
                    nilai = t.get("amount_usd", 0)
                    if nilai >= WHALE_MIN_USD:
                        transaksi.append({
                            "aset"     : t.get("symbol","?").upper(),
                            "nilai_usd": nilai,
                            "dari"     : t.get("from",{}).get("owner_type","unknown"),
                            "ke"       : t.get("to",{}).get("owner_type","unknown"),
                            "waktu"    : t.get("timestamp", 0),
                            "sumber"   : "whale-alert",
                            "tipe"     : _klasifikasi_whale(t)
                        })
        except:
            pass

        return transaksi

    except Exception as e:
        print(f"  ⚠️  Whale API error: {e}")
        return []

def get_exchange_netflow(symbol="bitcoin"):
    """
    Ambil net flow ke/dari exchange.
    Inflow tinggi = kemungkinan sell pressure
    Outflow tinggi = akumulasi (bullish)
    """
    try:
        # CryptoQuant-style data via public endpoint
        url    = f"https://api.coingecko.com/api/v3/coins/{symbol}"
        params = {
            "localization"    : "false",
            "tickers"         : "false",
            "market_data"     : "true",
            "community_data"  : "false",
            "developer_data"  : "false"
        }
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()

        market = data.get("market_data", {})
        return {
            "symbol"       : symbol,
            "harga"        : market.get("current_price",{}).get("usd", 0),
            "volume_24h"   : market.get("total_volume",{}).get("usd", 0),
            "change_24h"   : market.get("price_change_percentage_24h", 0),
            "market_cap"   : market.get("market_cap",{}).get("usd", 0),
            "ath_distance" : market.get("ath_change_percentage",{}).get("usd", 0)
        }
    except Exception as e:
        print(f"  ⚠️  Exchange flow error: {e}")
        return {}

# ══════════════════════════════════════════════
# 2. KLASIFIKASI TRANSAKSI
# ══════════════════════════════════════════════

def _klasifikasi_whale(t):
    """Klasifikasi tipe transaksi whale"""
    dari = t.get("from",{}).get("owner_type","")
    ke   = t.get("to",{}).get("owner_type","")

    if dari == "exchange" and ke == "unknown":
        return "WITHDRAWAL"   # Tarik dari exchange = bullish
    elif dari == "unknown" and ke == "exchange":
        return "DEPOSIT"      # Deposit ke exchange = sell pressure
    elif dari == "exchange" and ke == "exchange":
        return "TRANSFER_EX"  # Antar exchange
    else:
        return "TRANSFER_OTC" # OTC / wallet besar

# ══════════════════════════════════════════════
# 3. ANALISIS SINYAL DARI WHALE ACTIVITY
# ══════════════════════════════════════════════

def analisis_whale_signal(symbol_usdt):
    """
    Analisis sinyal trading dari aktivitas whale.

    Return dict:
        skor_buy  : int (0-3)
        skor_sell : int (0-3)
        sinyal    : str
        detail    : list[str]
        alert     : bool
    """
    global _whale_cache
    sekarang = time.time()

    # Cek cache
    if (_whale_cache["data"] is not None and
            sekarang - _whale_cache["waktu"] < CACHE_TTL):
        data_cache = _whale_cache["data"]
    else:
        transaksi = get_whale_transactions()
        _whale_cache["data"]  = transaksi
        _whale_cache["waktu"] = sekarang
        data_cache = transaksi

    symbol = symbol_usdt.replace("USDT","").lower()

    # Filter transaksi untuk symbol ini
    transaksi_symbol = [
        t for t in data_cache
        if t.get("aset","").lower() == symbol or
           t.get("aset","").lower() in ["btc","bitcoin"]  # BTC selalu relevan
    ]

    skor_buy  = 0
    skor_sell = 0
    detail    = []
    alert     = False

    withdrawal_total = 0
    deposit_total    = 0

    for t in transaksi_symbol:
        nilai = t.get("nilai_usd", 0)
        tipe  = t.get("tipe", "")

        if tipe == "WITHDRAWAL":
            withdrawal_total += nilai
        elif tipe == "DEPOSIT":
            deposit_total    += nilai

        # Alert untuk transaksi sangat besar
        if nilai >= WHALE_ALERT_USD:
            alert = True
            em    = "🟢" if tipe == "WITHDRAWAL" else "🔴"
            detail.append(
                f"{em} Whale {tipe}: ${nilai/1e6:.1f}M "
                f"{t.get('aset','?')}"
            )

    # Net flow analysis
    net_flow = withdrawal_total - deposit_total

    if net_flow > WHALE_ALERT_USD:
        skor_buy += 2
        detail.append(
            f"🐳 Net withdrawal: ${net_flow/1e6:.1f}M "
            f"(whale akumulasi)"
        )
    elif net_flow > WHALE_MIN_USD:
        skor_buy += 1
        detail.append(f"🐳 Withdrawal > deposit")
    elif net_flow < -WHALE_ALERT_USD:
        skor_sell += 2
        detail.append(
            f"⚠️ Net deposit: ${abs(net_flow)/1e6:.1f}M "
            f"(sell pressure)"
        )
    elif net_flow < -WHALE_MIN_USD:
        skor_sell += 1
        detail.append(f"⚠️ Deposit > withdrawal")

    if not detail:
        detail.append("✅ Tidak ada aktivitas whale signifikan")
        sinyal = "NETRAL"
    elif skor_buy > skor_sell:
        sinyal = "BULLISH"
    elif skor_sell > skor_buy:
        sinyal = "BEARISH"
    else:
        sinyal = "MIXED"

    return {
        "skor_buy"          : min(skor_buy, 3),
        "skor_sell"         : min(skor_sell, 3),
        "sinyal"            : sinyal,
        "detail"            : detail,
        "alert"             : alert,
        "withdrawal_total"  : withdrawal_total,
        "deposit_total"     : deposit_total,
        "n_transaksi"       : len(transaksi_symbol)
    }

# ══════════════════════════════════════════════
# 4. MONITOR MARKET CAP & DOMINANCE
# ══════════════════════════════════════════════

def get_market_overview():
    """
    Ambil overview market global untuk konteks.
    BTC dominance, total market cap, fear index.
    """
    try:
        url  = "https://api.coingecko.com/api/v3/global"
        resp = requests.get(url, timeout=10)
        data = resp.json().get("data", {})

        btc_dom     = data.get("market_cap_percentage",{}).get("btc", 0)
        total_mcap  = data.get("total_market_cap",{}).get("usd", 0)
        change_24h  = data.get("market_cap_change_percentage_24h_usd", 0)

        sinyal_dom = "NETRAL"
        if btc_dom > 55:
            sinyal_dom = "BTC_DOMINAN"  # Altcoin lemah
        elif btc_dom < 40:
            sinyal_dom = "ALTSEASON"    # Altcoin kuat

        return {
            "btc_dominance" : round(btc_dom, 2),
            "total_mcap_b"  : round(total_mcap / 1e9, 1),
            "change_24h"    : round(change_24h, 2),
            "sinyal_dom"    : sinyal_dom
        }
    except Exception as e:
        print(f"  ⚠️  Market overview error: {e}")
        return {
            "btc_dominance": 50, "total_mcap_b": 0,
            "change_24h": 0, "sinyal_dom": "NETRAL"
        }

# ══════════════════════════════════════════════
# FUNGSI UTAMA
# ══════════════════════════════════════════════

def get_whale_score(symbol):
    """
    Fungsi utama — analisis whale activity untuk symbol.
    Dipanggil dari hitung_skor_koin().
    """
    try:
        whale = analisis_whale_signal(symbol)
        return whale
    except Exception as e:
        print(f"  ⚠️  Whale score error {symbol}: {e}")
        return {
            "skor_buy": 0, "skor_sell": 0,
            "sinyal": "NETRAL", "detail": [],
            "alert": False, "n_transaksi": 0
        }

def print_whale_status(symbol):
    """Print status whale untuk monitoring"""
    w = get_whale_score(symbol)
    em = "🐳" if w["skor_buy"] > 0 else ("⚠️" if w["skor_sell"] > 0 else "⚪")
    print(f"  {em} Whale {symbol}: {w['sinyal']} | "
          f"+{w['skor_buy']}/-{w['skor_sell']} | "
          f"{w['n_transaksi']} tx")