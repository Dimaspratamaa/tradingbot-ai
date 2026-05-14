# ============================================
# POLYMARKET INTEGRATION v1.0
# Terintegrasi dengan Trading Bot AI
#
# Strategi: Arbitrase sinyal Binance → Polymarket
# Edge: 30-90 detik lag antara Binance dan Polymarket
# setelah BTC bergerak > 0.3% dalam 60 detik
#
# Dokumentasi: https://docs.polymarket.com
# Python SDK: pip install py-clob-client
#
# Credentials yang dibutuhkan di .env / Railway:
#   POLY_PRIVATE_KEY   = private key wallet Polygon
#   POLY_API_KEY       = apiKey dari create_or_derive_api_credentials
#   POLY_SECRET        = secret dari credentials
#   POLY_PASSPHRASE    = passphrase dari credentials
#   POLY_FUNDER_ADDR   = alamat wallet Polygon Anda
# ============================================

import os
import time
import json
import requests
import threading
import pathlib
import warnings
warnings.filterwarnings('ignore')

from datetime import datetime, timedelta
from collections import deque

BASE_DIR = pathlib.Path(__file__).parent

# ── KONFIGURASI ───────────────────────────────
POLY_HOST         = "https://clob.polymarket.com"
GAMMA_HOST        = "https://gamma-api.polymarket.com"
CHAIN_ID          = 137       # Polygon mainnet
POLY_LOG_FILE     = BASE_DIR / "polymarket_trades.json"
POLY_STATE_FILE   = BASE_DIR / "polymarket_state.json"

# Credentials dari environment
POLY_PRIVATE_KEY  = os.environ.get("POLY_PRIVATE_KEY",  "")
POLY_API_KEY      = os.environ.get("POLY_API_KEY",      "")
POLY_SECRET       = os.environ.get("POLY_SECRET",       "")
POLY_PASSPHRASE   = os.environ.get("POLY_PASSPHRASE",   "")
POLY_FUNDER_ADDR  = os.environ.get("POLY_FUNDER_ADDR",  "")

# Parameter trading
POLY_TRADE_SIZE_USD   = float(os.environ.get("POLY_TRADE_SIZE_USD", "5.0"))  # $5 per trade
POLY_MIN_EDGE         = float(os.environ.get("POLY_MIN_EDGE", "0.08"))        # min 8% mispricing
POLY_BTC_MOVE_THRESH  = float(os.environ.get("POLY_BTC_MOVE_THRESH", "0.3")) # BTC gerak > 0.3%
POLY_MOVE_WINDOW_SEC  = 60    # dalam 60 detik
POLY_MAX_HOLD_MIN     = 5     # max hold 5 menit
POLY_MAX_POSISI       = 3     # max 3 posisi aktif
POLY_AKTIF            = os.environ.get("POLY_AKTIF", "true").lower() == "true"


# ══════════════════════════════════════════════
# 1. CLIENT INITIALIZATION
# ══════════════════════════════════════════════

_poly_client = None

def init_polymarket_client():
    """
    Inisialisasi Polymarket CLOB client.
    Membutuhkan py-clob-client terinstall.
    """
    global _poly_client

    if not POLY_PRIVATE_KEY:
        print("  ⚠️  [POLY] POLY_PRIVATE_KEY tidak diset")
        return None

    try:
        from py_clob_client.client import ClobClient
        client = ClobClient(
            host     = POLY_HOST,
            chain_id = CHAIN_ID,
            key      = POLY_PRIVATE_KEY,
            creds    = {
                "apiKey"    : POLY_API_KEY,
                "secret"    : POLY_SECRET,
                "passphrase": POLY_PASSPHRASE,
            } if POLY_API_KEY else None,
            signature_type = 1,  # 0=MetaMask, 1=email/magic, 2=browser
            funder         = POLY_FUNDER_ADDR or None,
        )
        _poly_client = client
        print("  ✅ [POLY] Polymarket client terkoneksi!")
        return client

    except ImportError:
        print("  ❌ [POLY] py-clob-client belum terinstall!")
        print("  💡 Jalankan: pip install py-clob-client")
        return None
    except Exception as e:
        print(f"  ❌ [POLY] Init error: {e}")
        return None


def get_client():
    global _poly_client
    if _poly_client is None:
        _poly_client = init_polymarket_client()
    return _poly_client


# ══════════════════════════════════════════════
# 2. MARKET DISCOVERY — Cari pasar BTC aktif
# ══════════════════════════════════════════════

def get_btc_markets(limit=20):
    """
    Ambil daftar pasar BTC aktif dari Gamma API.
    Fokus pada pasar UP/DOWN jangka pendek (5 menit, 1 jam, dll).
    """
    try:
        resp = requests.get(
            f"{GAMMA_HOST}/markets",
            params={
                "tag"    : "bitcoin",
                "active" : "true",
                "limit"  : limit,
                "order"  : "volume",
                "ascending": "false",
            },
            timeout=10
        )
        if resp.status_code != 200:
            return []

        markets = resp.json()
        if not isinstance(markets, list):
            markets = markets.get("markets", [])

        # Filter hanya pasar UP/DOWN jangka pendek
        btc_markets = []
        for m in markets:
            q = m.get("question", "").lower()
            if any(k in q for k in ["btc", "bitcoin"]):
                btc_markets.append({
                    "id"          : m.get("id"),
                    "condition_id": m.get("conditionId"),
                    "question"    : m.get("question", ""),
                    "end_date"    : m.get("endDate", ""),
                    "volume"      : float(m.get("volume", 0)),
                    "tokens"      : m.get("tokens", []),
                })

        return btc_markets

    except Exception as e:
        print(f"  ⚠️  [POLY] Get markets error: {e}")
        return []


def get_5min_btc_market():
    """
    Ambil pasar BTC UP/DOWN 5 menit yang paling aktif.
    Ini adalah pasar utama untuk strategi arbitrase Binance→Polymarket.
    """
    try:
        # Cari market dengan keyword "5 minute" atau "5-minute"
        resp = requests.get(
            f"{GAMMA_HOST}/markets",
            params={
                "tag"   : "bitcoin",
                "active": "true",
                "limit" : 50,
            },
            timeout=10
        )
        if resp.status_code != 200:
            return None

        markets = resp.json()
        if not isinstance(markets, list):
            markets = markets.get("markets", [])

        # Cari pasar 5 menit dengan volume tertinggi
        for m in markets:
            q = m.get("question", "").lower()
            if ("5" in q or "five" in q) and ("minute" in q or "min" in q):
                if "bitcoin" in q or "btc" in q:
                    return m

        # Fallback: pasar UP/DOWN dengan volume tertinggi
        btc_updown = [m for m in markets
                      if any(k in m.get("question","").lower()
                             for k in ["up", "down", "above", "below"])
                      and any(k in m.get("question","").lower()
                              for k in ["btc", "bitcoin"])]

        if btc_updown:
            return max(btc_updown,
                       key=lambda x: float(x.get("volume", 0)))
        return None

    except Exception as e:
        print(f"  ⚠️  [POLY] Get 5min market error: {e}")
        return None


def get_market_price(token_id):
    """
    Ambil harga terbaik (best bid/ask) untuk token di CLOB.
    Return: {yes_price, no_price, spread}
    """
    try:
        resp = requests.get(
            f"{POLY_HOST}/price",
            params={"token_id": token_id, "side": "BUY"},
            timeout=5
        )
        if resp.status_code == 200:
            data = resp.json()
            yes_price = float(data.get("price", 0.5))
            return {
                "yes_price": yes_price,
                "no_price" : round(1 - yes_price, 4),
                "spread"   : 0.02,  # estimasi
            }
    except Exception:
        pass
    return {"yes_price": 0.5, "no_price": 0.5, "spread": 0}


# ══════════════════════════════════════════════
# 3. PRICE MONITOR — Monitor BTC di Binance
# ══════════════════════════════════════════════

class BinancePriceMonitor:
    """
    Monitor harga BTC Binance secara real-time.
    Deteksi pergerakan > POLY_BTC_MOVE_THRESH% dalam 60 detik.
    """

    def __init__(self, binance_client):
        self.client     = binance_client
        self.prices     = deque(maxlen=120)  # 120 data points
        self.timestamps = deque(maxlen=120)
        self._running   = False
        self._thread    = None

    def start(self):
        """Mulai monitoring di background thread."""
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True)
        self._thread.start()
        print("  ✅ [POLY] BTC price monitor started")

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            try:
                ticker = self.client.get_symbol_ticker(
                    symbol="BTCUSDT")
                harga  = float(ticker["price"])
                now    = time.time()
                self.prices.append(harga)
                self.timestamps.append(now)
            except Exception:
                pass
            time.sleep(2)  # update setiap 2 detik

    def get_move_60s(self):
        """
        Hitung pergerakan harga BTC dalam 60 detik terakhir.
        Return: (pct_change, direction) atau None jika data kurang.
        """
        if len(self.prices) < 10:
            return None, None

        now     = time.time()
        cutoff  = now - POLY_MOVE_WINDOW_SEC

        # Ambil harga 60 detik lalu
        harga_sekarang = self.prices[-1]
        harga_60s_lalu = None

        for i, ts in enumerate(self.timestamps):
            if ts >= cutoff:
                harga_60s_lalu = self.prices[i]
                break

        if harga_60s_lalu is None or harga_60s_lalu == 0:
            return None, None

        pct = (harga_sekarang - harga_60s_lalu) / harga_60s_lalu * 100
        direction = "UP" if pct > 0 else "DOWN"
        return round(pct, 4), direction

    def get_current_price(self):
        return self.prices[-1] if self.prices else 0


# ══════════════════════════════════════════════
# 4. EDGE DETECTOR — Cari mispricing
# ══════════════════════════════════════════════

def hitung_fair_value(btc_move_pct, direction, window_min=5):
    """
    Hitung fair value YES untuk pasar BTC UP/DOWN berdasarkan
    pergerakan Binance yang baru terjadi.

    Logika sederhana:
    - BTC naik 0.5% dalam 60 detik → probability UP dalam 5 menit naik
    - Semakin besar move, semakin tinggi probability
    """
    # Base probability (50/50 tanpa info)
    base = 0.50

    abs_move = abs(btc_move_pct)

    # Setiap 0.1% move menambah ~3% probability
    edge = min(abs_move * 0.30, 0.35)  # max 35% edge dari move

    if direction == "UP":
        fair_yes = base + edge
        fair_no  = base - edge
    else:
        fair_yes = base - edge
        fair_no  = base + edge

    return {
        "fair_yes"    : round(fair_yes, 4),
        "fair_no"     : round(fair_no, 4),
        "btc_move"    : btc_move_pct,
        "direction"   : direction,
        "edge_factor" : edge,
    }


def deteksi_mispricing(market_price, fair_value):
    """
    Bandingkan harga pasar vs fair value.
    Return trade signal jika ada edge > POLY_MIN_EDGE.
    """
    yes_market = market_price.get("yes_price", 0.5)
    yes_fair   = fair_value.get("fair_yes", 0.5)

    edge_yes   = yes_fair - yes_market   # positif = YES underpriced
    edge_no    = (1-yes_fair) - (1-yes_market)  # positif = NO underpriced

    if edge_yes > POLY_MIN_EDGE:
        return {
            "action"      : "BUY_YES",
            "edge"        : round(edge_yes, 4),
            "harga_pasar" : yes_market,
            "harga_fair"  : yes_fair,
            "alasan"      : f"YES underpriced: market={yes_market:.2f} fair={yes_fair:.2f}",
        }
    elif edge_no > POLY_MIN_EDGE:
        return {
            "action"      : "BUY_NO",
            "edge"        : round(edge_no, 4),
            "harga_pasar" : 1 - yes_market,
            "harga_fair"  : 1 - yes_fair,
            "alasan"      : f"NO underpriced: market={1-yes_market:.2f} fair={1-yes_fair:.2f}",
        }

    return None  # Tidak ada edge


# ══════════════════════════════════════════════
# 5. ORDER EXECUTION
# ══════════════════════════════════════════════

def eksekusi_order_polymarket(market, signal, size_usd=None,
                               paper_mode=True):
    """
    Eksekusi order di Polymarket.
    Paper mode: simulasi saja tanpa order nyata.
    """
    if size_usd is None:
        size_usd = POLY_TRADE_SIZE_USD

    action     = signal["action"]    # BUY_YES atau BUY_NO
    harga      = signal["harga_pasar"]
    edge       = signal["edge"]
    alasan     = signal["alasan"]

    # Hitung berapa token yang dibeli
    qty_token  = round(size_usd / harga, 2) if harga > 0 else 0

    print(f"\n  📊 [POLY] Order signal: {action}")
    print(f"     Harga  : {harga:.4f} | Fair: {signal['harga_fair']:.4f}")
    print(f"     Edge   : {edge:.2%}")
    print(f"     Size   : ${size_usd} ({qty_token:.2f} tokens)")
    print(f"     Alasan : {alasan}")

    if paper_mode:
        print(f"     [PAPER] Order tidak dieksekusi (paper mode)")
        result = {
            "status"    : "PAPER",
            "action"    : action,
            "size_usd"  : size_usd,
            "harga"     : harga,
            "qty"       : qty_token,
            "edge"      : edge,
        }
        simpan_poly_trade(market, signal, result, paper_mode=True)
        return result

    # LIVE mode — eksekusi nyata
    client = get_client()
    if client is None:
        print("  ❌ [POLY] Client tidak tersedia")
        return None

    try:
        from py_clob_client.clob_types import MarketOrderArgs, OrderType
        from py_clob_client.order_builder.constants import BUY

        # Ambil token ID dari market
        tokens    = market.get("tokens", [])
        token_id  = None

        for t in tokens:
            outcome = t.get("outcome", "").upper()
            if action == "BUY_YES" and outcome == "YES":
                token_id = t.get("token_id")
                break
            elif action == "BUY_NO" and outcome == "NO":
                token_id = t.get("token_id")
                break

        if not token_id:
            print("  ❌ [POLY] Token ID tidak ditemukan")
            return None

        # Buat market order
        order_args = MarketOrderArgs(
            token_id = token_id,
            amount   = size_usd,    # dalam USDC
        )

        signed_order = client.create_market_order(order_args)
        resp         = client.post_order(signed_order, OrderType.FOK)

        print(f"  ✅ [POLY] Order berhasil: {resp}")
        result = {
            "status"    : "OK",
            "action"    : action,
            "size_usd"  : size_usd,
            "harga"     : harga,
            "qty"       : qty_token,
            "edge"      : edge,
            "order_id"  : resp.get("orderID", ""),
        }
        simpan_poly_trade(market, signal, result, paper_mode=False)
        return result

    except Exception as e:
        print(f"  ❌ [POLY] Order error: {e}")
        return None


# ══════════════════════════════════════════════
# 6. POSISI MANAGEMENT
# ══════════════════════════════════════════════

def get_posisi_aktif():
    """Ambil posisi Polymarket aktif dari state file."""
    if not POLY_STATE_FILE.exists():
        return []
    try:
        state = json.loads(POLY_STATE_FILE.read_text())
        return [p for p in state.get("posisi", [])
                if p.get("aktif")]
    except Exception:
        return []


def simpan_poly_trade(market, signal, result, paper_mode=True):
    """Simpan trade Polymarket ke log file."""
    try:
        log = []
        if POLY_LOG_FILE.exists():
            log = json.loads(POLY_LOG_FILE.read_text())

        entry = {
            "waktu"     : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "market"    : market.get("question", "")[:60],
            "action"    : signal["action"],
            "edge"      : signal["edge"],
            "harga"     : signal["harga_pasar"],
            "size_usd"  : result.get("size_usd", 0),
            "status"    : result.get("status", "?"),
            "paper"     : paper_mode,
            "alasan"    : signal.get("alasan", ""),
        }
        log.append(entry)
        POLY_LOG_FILE.write_text(json.dumps(log[-200:], indent=2))

    except Exception as e:
        print(f"  ⚠️  [POLY] Gagal simpan trade: {e}")


def get_saldo_usdc():
    """Ambil saldo USDC di wallet Polygon."""
    client = get_client()
    if client is None:
        return 0.0
    try:
        from py_clob_client.clob_types import BalanceAllowanceParams, AssetType
        resp = client.get_balance_allowance(
            BalanceAllowanceParams(asset_type=AssetType.COLLATERAL)
        )
        return float(resp.get("balance", 0)) / 1e6  # USDC 6 desimal
    except Exception as e:
        print(f"  ⚠️  [POLY] Gagal ambil saldo: {e}")
        return 0.0


# ══════════════════════════════════════════════
# 7. MAIN ENGINE — Loop utama Polymarket
# ══════════════════════════════════════════════

class PolymarketEngine:
    """
    Engine utama yang menjalankan strategi arbitrase
    Binance → Polymarket secara otomatis.
    """

    def __init__(self, binance_client, kirim_telegram=None,
                 paper_mode=True):
        self.binance_client  = binance_client
        self.kirim_telegram  = kirim_telegram
        self.paper_mode      = paper_mode
        self.price_monitor   = BinancePriceMonitor(binance_client)
        self._running        = False
        self._thread         = None
        self.stats = {
            "n_scan"     : 0,
            "n_signal"   : 0,
            "n_order"    : 0,
            "total_edge" : 0.0,
            "last_signal": None,
        }

    def start(self):
        """Mulai engine di background thread."""
        if not POLY_AKTIF:
            print("  ⚠️  [POLY] Dinonaktifkan (POLY_AKTIF=false)")
            return

        if not POLY_PRIVATE_KEY:
            print("  ⚠️  [POLY] POLY_PRIVATE_KEY belum diset")
            return

        # Init client
        init_polymarket_client()

        # Mulai price monitor
        self.price_monitor.start()

        # Mulai engine loop
        self._running = True
        self._thread  = threading.Thread(
            target=self._loop, daemon=True)
        self._thread.start()

        mode_str = "📝 PAPER" if self.paper_mode else "🔴 LIVE"
        print(f"  ✅ [POLY] PolymarketEngine started ({mode_str})")

        if self.kirim_telegram:
            self.kirim_telegram(
                f"🎯 <b>Polymarket Engine Started</b>\n"
                f"Mode: {mode_str}\n"
                f"Strategi: Binance→Polymarket arbitrase\n"
                f"Min edge: {POLY_MIN_EDGE:.0%} | "
                f"Size: ${POLY_TRADE_SIZE_USD}\n"
                f"BTC threshold: {POLY_BTC_MOVE_THRESH}%/60s"
            )

    def stop(self):
        self._running = False
        self.price_monitor.stop()

    def _loop(self):
        """Loop utama: scan setiap 5 detik."""
        market_cache      = {"data": None, "waktu": 0}
        MARKET_CACHE_TTL  = 300  # refresh market setiap 5 menit

        while self._running:
            try:
                self.stats["n_scan"] += 1

                # ── 1. Cek pergerakan BTC ──
                move_pct, direction = self.price_monitor.get_move_60s()

                if move_pct is None:
                    time.sleep(5)
                    continue

                abs_move = abs(move_pct)

                # Hanya lanjut jika BTC bergerak cukup besar
                if abs_move < POLY_BTC_MOVE_THRESH:
                    time.sleep(5)
                    continue

                print(f"\n  🔥 [POLY] BTC move: {move_pct:+.3f}% "
                      f"({direction}) dalam 60s!")

                # ── 2. Ambil market aktif ──
                now = time.time()
                if (not market_cache["data"] or
                        now - market_cache["waktu"] > MARKET_CACHE_TTL):
                    market = get_5min_btc_market()
                    if market:
                        market_cache = {"data": market, "waktu": now}
                    else:
                        # Fallback ke semua pasar BTC
                        markets = get_btc_markets(limit=5)
                        market  = markets[0] if markets else None

                market = market_cache.get("data")
                if not market:
                    print("  ⚠️  [POLY] Tidak ada market aktif")
                    time.sleep(10)
                    continue

                # ── 3. Ambil harga pasar sekarang ──
                tokens   = market.get("tokens", [])
                yes_token= next((t for t in tokens
                                  if t.get("outcome","").upper()=="YES"), None)

                if not yes_token:
                    time.sleep(5)
                    continue

                token_id     = yes_token.get("token_id", "")
                market_price = get_market_price(token_id)

                # ── 4. Hitung fair value & edge ──
                fair_value = hitung_fair_value(move_pct, direction)
                signal     = deteksi_mispricing(market_price, fair_value)

                if not signal:
                    print(f"  ℹ️  [POLY] Tidak ada edge yang cukup "
                          f"(yes={market_price['yes_price']:.2f} "
                          f"fair={fair_value['fair_yes']:.2f})")
                    time.sleep(10)
                    continue

                # ── 5. Cek posisi aktif tidak melebihi batas ──
                posisi_aktif = get_posisi_aktif()
                if len(posisi_aktif) >= POLY_MAX_POSISI:
                    print(f"  ⚠️  [POLY] Max posisi tercapai "
                          f"({POLY_MAX_POSISI})")
                    time.sleep(10)
                    continue

                # ── 6. Eksekusi order ──
                self.stats["n_signal"] += 1
                self.stats["total_edge"] += signal["edge"]
                self.stats["last_signal"] = datetime.now().strftime(
                    "%H:%M:%S")

                print(f"\n  🎯 [POLY] SIGNAL DETECTED!")
                print(f"     Market : {market.get('question','')[:50]}")
                print(f"     BTC    : {move_pct:+.3f}% → {direction}")
                print(f"     Action : {signal['action']} @ "
                      f"{signal['harga_pasar']:.4f}")
                print(f"     Edge   : {signal['edge']:.2%}")

                result = eksekusi_order_polymarket(
                    market, signal,
                    size_usd  = POLY_TRADE_SIZE_USD,
                    paper_mode= self.paper_mode
                )

                if result:
                    self.stats["n_order"] += 1
                    if self.kirim_telegram:
                        mode_em = "📝" if self.paper_mode else "💰"
                        self.kirim_telegram(
                            f"{mode_em} <b>Polymarket Signal!</b>\n"
                            f"━━━━━━━━━━━━━━━━━━\n"
                            f"📊 {market.get('question','')[:50]}\n\n"
                            f"🔥 BTC {direction}: {move_pct:+.3f}%/60s\n"
                            f"🎯 Action: <b>{signal['action']}</b>\n"
                            f"💲 Harga pasar: {signal['harga_pasar']:.4f}\n"
                            f"🧮 Fair value : {signal['harga_fair']:.4f}\n"
                            f"📈 Edge       : {signal['edge']:.2%}\n"
                            f"💰 Size       : ${POLY_TRADE_SIZE_USD}\n"
                            f"{'📝 PAPER MODE' if self.paper_mode else '✅ ORDER MASUK'}"
                        )

                # Tunggu setelah order — hindari double entry
                time.sleep(60)

            except Exception as e:
                print(f"  ⚠️  [POLY] Loop error: {e}")
                time.sleep(10)

    def get_stats(self):
        """Return statistik engine."""
        avg_edge = (self.stats["total_edge"] / self.stats["n_signal"]
                    if self.stats["n_signal"] > 0 else 0)
        return {
            **self.stats,
            "avg_edge"    : round(avg_edge, 4),
            "paper_mode"  : self.paper_mode,
        }

    def format_telegram(self):
        """Format laporan untuk Telegram /poly command."""
        s = self.get_stats()
        trades = []
        if POLY_LOG_FILE.exists():
            try:
                trades = json.loads(POLY_LOG_FILE.read_text())[-5:]
            except Exception:
                pass

        mode_str = "📝 PAPER" if s["paper_mode"] else "🔴 LIVE"
        teks = (
            f"🎯 <b>Polymarket Engine</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Mode     : {mode_str}\n"
            f"Scans    : {s['n_scan']}\n"
            f"Signals  : {s['n_signal']}\n"
            f"Orders   : {s['n_order']}\n"
            f"Avg edge : {s['avg_edge']:.2%}\n"
            f"Last sig : {s['last_signal'] or 'Belum ada'}\n"
        )

        if trades:
            teks += "\n<b>5 Trade Terakhir:</b>\n"
            for t in reversed(trades):
                em = "📝" if t.get("paper") else "💰"
                teks += (f"  {em} {t['action']:8} "
                         f"edge:{t['edge']:.2%} "
                         f"${t['size_usd']:.0f}\n")
        return teks


# ── SINGLETON ─────────────────────────────────
_poly_engine = None

def get_poly_engine():
    return _poly_engine

def init_poly_engine(binance_client, kirim_telegram=None,
                     paper_mode=True):
    """Inisialisasi dan start PolymarketEngine."""
    global _poly_engine
    if _poly_engine is None:
        _poly_engine = PolymarketEngine(
            binance_client = binance_client,
            kirim_telegram = kirim_telegram,
            paper_mode     = paper_mode,
        )
        _poly_engine.start()
    return _poly_engine