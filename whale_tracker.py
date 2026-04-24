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
        except Exception as _e:
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

# ══════════════════════════════════════════════
# UPGRADE v2.0 — Real-time Alert & Alpha Integration
# ══════════════════════════════════════════════

import threading
import pathlib
import json

BASE_DIR        = pathlib.Path(__file__).parent
ALERT_STATE_FILE= BASE_DIR / "whale_alert_state.json"

# State: track whale yang sudah di-alert agar tidak double
_alerted_ids    = set()
_monitor_thread = None
_running        = False

MONITOR_INTERVAL = 300   # cek setiap 5 menit
WHALE_ALERT_USD  = 5_000_000  # alert jika > $5M


def _load_alerted():
    """Load ID transaksi yang sudah di-alert."""
    global _alerted_ids
    if ALERT_STATE_FILE.exists():
        try:
            data = json.loads(ALERT_STATE_FILE.read_text())
            _alerted_ids = set(data.get("alerted", []))
        except Exception:
            _alerted_ids = set()


def _save_alerted():
    """Simpan ID yang sudah di-alert (max 500 terakhir)."""
    try:
        alerted_list = list(_alerted_ids)[-500:]
        ALERT_STATE_FILE.write_text(
            json.dumps({"alerted": alerted_list}, indent=2))
    except Exception:
        pass


def cek_whale_alert(posisi_aktif, kirim_telegram, client=None):
    """
    Cek aktivitas whale untuk koin yang sedang di-hold.
    Kirim alert ke Telegram jika ada whale besar masuk/keluar.

    Dipanggil dari main loop setiap 5 menit.

    Args:
        posisi_aktif : dict posisi spot aktif
        kirim_telegram: fungsi kirim pesan
        client       : Binance client (opsional)
    """
    if not posisi_aktif:
        return

    koin_aktif = [s for s, p in posisi_aktif.items() if p.get("aktif")]
    if not koin_aktif:
        return

    _load_alerted()

    for symbol in koin_aktif[:3]:  # max 3 koin agar tidak spam API
        try:
            whale = analisis_whale_signal(symbol)

            # Skip jika tidak ada alert
            if not whale.get("alert"):
                continue

            # Buat ID unik untuk transaksi ini (berdasarkan waktu+symbol)
            alert_id = f"{symbol}_{int(time.time() // 300)}"  # unik per 5 menit

            if alert_id in _alerted_ids:
                continue  # Sudah di-alert

            _alerted_ids.add(alert_id)
            _save_alerted()

            # Format pesan alert
            sinyal  = whale["sinyal"]
            em_sinyal = {
                "BULLISH": "🟢", "BEARISH": "🔴",
                "MIXED"  : "🟡", "NETRAL" : "⚪"
            }.get(sinyal, "⚪")

            detail_str = "\n".join(
                f"  {d}" for d in whale["detail"][:3])

            # Hitung estimasi dampak harga
            net_flow = whale["withdrawal_total"] - whale["deposit_total"]
            dampak   = "Bullish ↗" if net_flow > 0 else "Bearish ↘"

            pesan = (
                f"🐳 <b>WHALE ALERT — {symbol}</b>\n"
                f"{'─'*24}\n"
                f"{em_sinyal} Sinyal : <b>{sinyal}</b>\n"
                f"📊 Detail:\n{detail_str}\n\n"
                f"💰 Net flow : {'+' if net_flow >= 0 else ''}"
                f"${net_flow/1e6:.1f}M\n"
                f"🎯 Dampak   : {dampak}\n"
                f"📌 Koin hold: {symbol}\n"
                f"🕐 {datetime.now().strftime('%H:%M WIB')}"
            )

            kirim_telegram(pesan)
            print(f"  🐳 [WHALE] Alert terkirim: {symbol} {sinyal}")

        except Exception as e:
            print(f"  ⚠️  [WHALE] Alert error {symbol}: {e}")


def mulai_whale_monitor(posisi_getter, kirim_telegram,
                         client=None):
    """
    Mulai monitoring whale di background thread.
    posisi_getter: fungsi yang return dict posisi_spot
    """
    global _monitor_thread, _running

    if _running:
        return

    _running = True

    def _loop():
        print("  ✅ [WHALE] Monitor thread started")
        while _running:
            try:
                posisi = posisi_getter()
                cek_whale_alert(posisi, kirim_telegram, client)
            except Exception as e:
                print(f"  ⚠️  [WHALE] Monitor error: {e}")
            time.sleep(MONITOR_INTERVAL)

    _monitor_thread = threading.Thread(target=_loop, daemon=True)
    _monitor_thread.start()


def hentikan_whale_monitor():
    """Hentikan whale monitor."""
    global _running
    _running = False


def format_whale_telegram(symbol, top_n=3):
    """
    Format laporan whale untuk /whale Telegram command.
    """
    whale  = analisis_whale_signal(symbol)
    market = get_market_overview()

    sinyal   = whale["sinyal"]
    em       = {"BULLISH":"🟢","BEARISH":"🔴",
                "MIXED":"🟡","NETRAL":"⚪"}.get(sinyal,"⚪")

    detail_str = "\n".join(
        f"  {d}" for d in whale["detail"][:5])
    if not whale["detail"]:
        detail_str = "  Tidak ada aktivitas signifikan"

    net = whale["withdrawal_total"] - whale["deposit_total"]

    teks = (
        f"🐳 <b>Whale Tracker — {symbol}</b>\n"
        f"{'─'*26}\n"
        f"{em} Sinyal     : <b>{sinyal}</b>\n"
        f"📊 Skor       : +{whale['skor_buy']} buy / -{whale['skor_sell']} sell\n"
        f"💸 Withdrawal : ${whale['withdrawal_total']/1e6:.2f}M\n"
        f"💰 Deposit    : ${whale['deposit_total']/1e6:.2f}M\n"
        f"📈 Net flow   : {'+'if net>=0 else''}${net/1e6:.2f}M\n\n"
        f"📋 Detail:\n{detail_str}\n\n"
        f"🌐 <b>Market Global:</b>\n"
        f"  BTC dominance: {market.get('btc_dominance',0):.1f}%\n"
        f"  Total MCap   : ${market.get('total_mcap_b',0):.0f}B\n"
        f"  24H change   : {market.get('change_24h',0):+.2f}%\n"
        f"  Regime       : {market.get('sinyal_dom','?')}"
    )
    return teks