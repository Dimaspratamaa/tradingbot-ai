# ============================================
# EXECUTION ENGINE v1.0 — Phase 6
# Terinspirasi Virtu Financial & Two Sigma
#
# "The last mile" — seberapa bagus sinyal tidak
# berguna jika eksekusinya jelek.
# Slippage 0.5% per trade = kerugian 180% per tahun
# jika trading 365 hari.
#
# Fitur:
#   1. TWAP  — Time-Weighted Average Price
#              Pecah order besar jadi kecil sepanjang waktu
#   2. VWAP  — Volume-Weighted Average Price
#              Eksekusi saat volume tinggi untuk slippage minimal
#   3. Smart Order Routing — pilih exchange terbaik real-time
#   4. Transaction Cost Model — hitung biaya SEBELUM masuk
#   5. Slippage Estimator — prediksi slippage berdasarkan order book
#   6. Execution Quality Monitor — ukur kualitas eksekusi aktual
# ============================================

import time
import json
import threading
import pathlib
import numpy as np
import warnings
warnings.filterwarnings('ignore')

BASE_DIR   = pathlib.Path(__file__).parent
EXEC_FILE  = BASE_DIR / "execution_log.json"

# ── KONFIGURASI ───────────────────────────────
TWAP_SLICES       = 3        # Pecah order jadi 3 bagian
TWAP_INTERVAL_SEC = 30       # Jeda 30 detik antar slice
VWAP_WINDOW       = 20       # VWAP dari 20 candle terakhir
MAX_SLIPPAGE_PCT  = 0.3      # Tolak order jika slippage > 0.3%
MIN_LIQUIDITY_USD = 50_000   # Minimal $50k volume untuk entry aman
FEE_SPOT          = 0.001    # 0.1% fee Binance spot
FEE_FUTURES       = 0.0004   # 0.04% fee Binance futures taker

# ══════════════════════════════════════════════
# 1. TRANSACTION COST MODEL (TCM)
# ══════════════════════════════════════════════

class TransactionCostModel:
    """
    Hitung biaya transaksi SEBELUM masuk posisi.

    Komponen biaya:
    1. Exchange fee      — 0.1% spot, 0.04% futures
    2. Slippage          — harga bisa bergerak saat order dieksekusi
    3. Market impact     — order besar menggerakkan harga
    4. Spread cost       — selisih bid-ask

    Renaissance menolak trade jika expected profit < total cost.
    """

    def __init__(self, fee_spot=FEE_SPOT, fee_futures=FEE_FUTURES):
        self.fee_spot    = fee_spot
        self.fee_futures = fee_futures

    def estimasi_slippage(self, orderbook, qty_usd, side="BUY"):
        """
        Estimasi slippage dari order book depth.

        Cara kerja: hitung berapa banyak level order book
        yang harus "dimakan" untuk memenuhi qty_usd.
        """
        if not orderbook:
            return 0.002  # default 0.2% jika tidak ada data

        try:
            orders = orderbook.get("asks" if side == "BUY" else "bids", [])
            if not orders:
                return 0.002

            # Harga terbaik (top of book)
            best_price = float(orders[0][0]) if orders else 0
            if best_price <= 0:
                return 0.002

            # Hitung berapa level yang dibutuhkan
            qty_terisi  = 0
            total_cost  = 0
            vwap_exec   = 0

            for price, size in orders[:20]:
                p     = float(price)
                s     = float(size)
                nilai = p * s

                if qty_terisi + nilai >= qty_usd:
                    # Ambil sebagian dari level ini
                    sisa   = qty_usd - qty_terisi
                    total_cost += sisa
                    qty_terisi  = qty_usd
                    vwap_exec   = total_cost / (qty_usd / best_price)
                    break
                else:
                    total_cost += nilai
                    qty_terisi  += nilai

            if qty_terisi < qty_usd * 0.5:
                # Tidak cukup likuiditas
                return 0.005  # 0.5% slippage estimasi

            if best_price > 0 and vwap_exec > 0:
                slippage = abs(vwap_exec - best_price) / best_price
            else:
                slippage = 0.001

            return min(slippage, 0.01)  # cap 1%

        except Exception:
            return 0.002

    def estimasi_market_impact(self, qty_usd, volume_24h_usd):
        """
        Estimasi market impact: order besar menggerakkan harga.
        Square-root model (Almgren-Chriss): impact ~ sqrt(qty/volume)
        """
        if volume_24h_usd <= 0:
            return 0.001
        ratio  = qty_usd / volume_24h_usd
        impact = 0.1 * np.sqrt(ratio)  # 10% * sqrt(participation rate)
        return min(impact, 0.005)  # cap 0.5%

    def hitung_total_biaya(self, qty_usd, harga, orderbook=None,
                            volume_24h_usd=1_000_000, tipe="spot"):
        """
        Hitung total biaya transaksi end-to-end.

        Return dict:
            fee_pct      : biaya exchange
            slippage_pct : estimasi slippage
            impact_pct   : market impact
            spread_pct   : bid-ask spread
            total_pct    : total semua biaya (%)
            total_usd    : total biaya dalam USD
            layak        : bool (trade layak dilanjutkan?)
        """
        fee = self.fee_spot if tipe == "spot" else self.fee_futures
        fee_rt = fee * 2  # round-trip (beli + jual)

        slippage = self.estimasi_slippage(orderbook, qty_usd) if orderbook else 0.001
        impact   = self.estimasi_market_impact(qty_usd, volume_24h_usd)

        # Spread estimasi dari order book
        spread = 0.0
        if orderbook:
            try:
                best_ask = float(orderbook.get("asks", [[0]])[0][0])
                best_bid = float(orderbook.get("bids", [[0]])[0][0])
                if best_ask > 0 and best_bid > 0:
                    spread = (best_ask - best_bid) / best_ask
            except Exception:
                spread = 0.0005

        total_pct = fee_rt + slippage + impact + spread
        total_usd = qty_usd * total_pct

        return {
            "fee_pct"     : round(fee_rt, 5),
            "slippage_pct": round(slippage, 5),
            "impact_pct"  : round(impact, 5),
            "spread_pct"  : round(spread, 5),
            "total_pct"   : round(total_pct, 5),
            "total_usd"   : round(total_usd, 4),
            "layak"       : total_pct < MAX_SLIPPAGE_PCT / 100 * 3,
        }

    def breakeven_return(self, qty_usd, orderbook=None, tipe="spot"):
        """
        Return minimum yang dibutuhkan untuk breakeven setelah biaya.
        Trade ini harus menghasilkan setidaknya sebesar ini.
        """
        biaya = self.hitung_total_biaya(qty_usd, 0, orderbook, tipe=tipe)
        return biaya["total_pct"] * 100  # dalam %


# ══════════════════════════════════════════════
# 2. TWAP EXECUTOR
# ══════════════════════════════════════════════

class TWAPExecutor:
    """
    Time-Weighted Average Price execution.

    Daripada beli semua sekaligus (rentan spike harga),
    pecah order jadi N bagian dengan jeda waktu.

    Contoh: Beli $300 BTCUSDT
    → Slice 1: Beli $100 sekarang
    → Tunggu 30 detik
    → Slice 2: Beli $100
    → Tunggu 30 detik
    → Slice 3: Beli $100

    Result: harga rata-rata lebih baik dari market order tunggal.
    """

    def __init__(self, n_slices=TWAP_SLICES, interval_sec=TWAP_INTERVAL_SEC):
        self.n_slices    = n_slices
        self.interval_sec= interval_sec

    def execute_twap_buy(self, client, symbol, total_qty,
                          kirim_telegram=None, paper_mode=False):
        """
        Eksekusi TWAP BUY — pecah qty jadi n_slices.

        Return:
            sukses      : bool
            avg_harga   : float rata-rata harga eksekusi
            total_terisi: float total qty terisi
            detail      : list log per slice
        """
        from trading_bot import _hitung_qty_dari_modal

        slice_qty = round(total_qty / self.n_slices, 8)
        if slice_qty <= 0:
            return False, 0, 0, []

        hasil_slice  = []
        total_terisi = 0
        total_cost   = 0

        print(f"\n  ⏱  TWAP BUY {symbol}: {self.n_slices} slices × {slice_qty:.6f}")

        for i in range(self.n_slices):
            slice_num = i + 1

            # Ambil harga terkini sebelum setiap slice
            try:
                ticker = client.get_symbol_ticker(symbol=symbol)
                harga  = float(ticker["price"])
            except Exception as e:
                print(f"    Slice {slice_num}: gagal ambil harga — {e}")
                break

            if paper_mode:
                terisi = slice_qty
                cost   = slice_qty * harga
                status = "PAPER"
            else:
                try:
                    resp   = client.order_market_buy(
                        symbol=symbol, quantity=slice_qty)
                    terisi = float(resp.get("executedQty", slice_qty))
                    cost   = float(resp.get("cummulativeQuoteQty",
                                            slice_qty * harga))
                    status = "OK"
                except Exception as e:
                    print(f"    Slice {slice_num} GAGAL: {e}")
                    status = "ERROR"
                    terisi = 0
                    cost   = 0

            total_terisi += terisi
            total_cost   += cost

            avg_price = cost / terisi if terisi > 0 else harga
            hasil_slice.append({
                "slice"  : slice_num,
                "qty"    : terisi,
                "harga"  : round(avg_price, 6),
                "status" : status,
            })

            print(f"    Slice {slice_num}/{self.n_slices}: "
                  f"{terisi:.6f} @ ${avg_price:,.4f} [{status}]")

            # Jeda antar slice (tidak untuk slice terakhir)
            if i < self.n_slices - 1:
                time.sleep(self.interval_sec)

        avg_harga = total_cost / total_terisi if total_terisi > 0 else 0
        sukses    = total_terisi > 0

        if sukses:
            print(f"  ✅ TWAP selesai: avg=${avg_harga:,.4f} | "
                  f"total={total_terisi:.6f}")

        return sukses, round(avg_harga, 6), round(total_terisi, 8), hasil_slice


# ══════════════════════════════════════════════
# 3. VWAP EXECUTOR
# ══════════════════════════════════════════════

class VWAPExecutor:
    """
    Volume-Weighted Average Price execution.

    Eksekusi lebih banyak saat volume tinggi (likuiditas baik),
    lebih sedikit saat volume rendah (likuiditas tipis).

    Prinsip: "Berenang dengan arus volume, bukan melawan."
    """

    def __init__(self, window=VWAP_WINDOW):
        self.window = window

    def hitung_vwap(self, client, symbol):
        """Hitung VWAP dari N candle terakhir."""
        try:
            klines = client.get_klines(
                symbol=symbol,
                interval="5m",
                limit=self.window
            )
            typical_prices = [(float(k[2]) + float(k[3]) + float(k[4])) / 3
                               for k in klines]
            volumes        = [float(k[5]) for k in klines]

            if not volumes or sum(volumes) == 0:
                return float(klines[-1][4]) if klines else 0

            vwap = sum(p * v for p, v in zip(typical_prices, volumes)) / sum(volumes)
            return round(vwap, 6)
        except Exception:
            return 0

    def hitung_volume_profile(self, client, symbol):
        """
        Hitung profil volume 24 jam untuk tentukan waktu eksekusi terbaik.
        Return jam-jam dengan volume di atas rata-rata.
        """
        try:
            klines = client.get_klines(
                symbol=symbol,
                interval="1h",
                limit=24
            )
            vols   = [float(k[5]) for k in klines]
            avg_vol = np.mean(vols) if vols else 0
            jam_vol_tinggi = [i for i, v in enumerate(vols) if v > avg_vol * 1.2]
            return {
                "avg_volume"   : round(avg_vol, 2),
                "jam_vol_tinggi": jam_vol_tinggi,
                "volume_sekarang": vols[-1] if vols else 0,
                "vol_ratio"    : round(vols[-1] / avg_vol, 3) if avg_vol > 0 else 1.0
            }
        except Exception:
            return {"avg_volume": 0, "vol_ratio": 1.0}

    def should_execute_now(self, client, symbol, min_vol_ratio=0.8):
        """
        Apakah sekarang waktu yang baik untuk eksekusi?
        Return True jika volume cukup untuk eksekusi dengan slippage minimal.
        """
        profile = self.hitung_volume_profile(client, symbol)
        return profile.get("vol_ratio", 1.0) >= min_vol_ratio


# ══════════════════════════════════════════════
# 4. SMART ORDER ROUTER
# ══════════════════════════════════════════════

class SmartOrderRouter:
    """
    Pilih exchange terbaik untuk eksekusi berdasarkan:
    1. Spread (bid-ask) terkecil
    2. Depth terbesar (likuiditas)
    3. Fee terendah
    4. Latency historis

    Mirip dengan apa yang dilakukan HFT firms tapi versi
    yang lebih sederhana untuk crypto retail.
    """

    def __init__(self):
        self.exchange_fees = {
            "binance"    : 0.001,
            "tokocrypto" : 0.001,
            "indodax"    : 0.003,
            "hyperliquid": 0.0004,
        }
        self.latency_log = {}  # {exchange: [latency_ms, ...]}

    def get_best_exchange(self, symbol, qty_usd, side="BUY"):
        """
        Pilih exchange terbaik. Return ordered list.
        Saat ini simplified — Binance selalu primary untuk spot.
        """
        from multi_exchange import SYMBOL_MAP, HL_WALLET, TOKO_KEY, INDODAX_KEY

        sym_map   = SYMBOL_MAP.get(symbol, {})
        kandidat  = []

        # Binance — selalu tersedia, fee paling kompetitif
        kandidat.append({
            "exchange": "binance",
            "fee"     : self.exchange_fees["binance"],
            "skor"    : 10,  # highest priority
        })

        # Hyperliquid — hanya untuk leverage, fee sangat rendah
        if sym_map.get("hl") and HL_WALLET and qty_usd >= 50:
            kandidat.append({
                "exchange": "hyperliquid",
                "fee"     : self.exchange_fees["hyperliquid"],
                "skor"    : 8,
            })

        # Tokocrypto — untuk pair yang tersedia
        if sym_map.get("toko") and TOKO_KEY:
            kandidat.append({
                "exchange": "tokocrypto",
                "fee"     : self.exchange_fees["tokocrypto"],
                "skor"    : 6,
            })

        # Sort by skor
        kandidat.sort(key=lambda x: -x["skor"])
        return [k["exchange"] for k in kandidat]

    def log_latency(self, exchange, latency_ms):
        """Catat latency eksekusi untuk monitoring."""
        if exchange not in self.latency_log:
            self.latency_log[exchange] = []
        self.latency_log[exchange].append(latency_ms)
        # Simpan max 100 entri
        self.latency_log[exchange] = self.latency_log[exchange][-100:]

    def get_avg_latency(self, exchange):
        """Return rata-rata latency dalam ms."""
        log = self.latency_log.get(exchange, [])
        return round(np.mean(log), 1) if log else 0


# ══════════════════════════════════════════════
# 5. EXECUTION QUALITY MONITOR
# ══════════════════════════════════════════════

class ExecutionQualityMonitor:
    """
    Ukur kualitas eksekusi aktual vs benchmark.

    Metrik utama:
    - Implementation Shortfall: selisih harga saat sinyal vs harga aktual
    - Slippage aktual: selisih harga expected vs executed
    - Fill rate: berapa % order terisi

    Jika kualitas eksekusi buruk → switch ke TWAP otomatis.
    """

    def __init__(self):
        self.history = self._load()

    def _load(self):
        if EXEC_FILE.exists():
            try:
                return json.loads(EXEC_FILE.read_text())
            except Exception:
                pass
        return []

    def _save(self):
        try:
            EXEC_FILE.write_text(json.dumps(self.history[-500:], indent=2))
        except Exception:
            pass

    def catat_eksekusi(self, symbol, harga_sinyal, harga_eksekusi,
                        qty, metode, exchange):
        """Catat satu eksekusi untuk analisis kualitas."""
        slippage = abs(harga_eksekusi - harga_sinyal) / harga_sinyal * 100
        entry    = {
            "waktu"          : time.strftime("%Y-%m-%d %H:%M:%S"),
            "symbol"         : symbol,
            "harga_sinyal"   : round(harga_sinyal, 6),
            "harga_eksekusi" : round(harga_eksekusi, 6),
            "slippage_pct"   : round(slippage, 4),
            "qty"            : qty,
            "metode"         : metode,
            "exchange"       : exchange,
        }
        self.history.append(entry)
        self._save()
        return slippage

    def get_avg_slippage(self, symbol=None, n_last=20):
        """Return rata-rata slippage dari n eksekusi terakhir."""
        data = self.history
        if symbol:
            data = [e for e in data if e.get("symbol") == symbol]
        if not data:
            return 0.0
        recent = data[-n_last:]
        return round(np.mean([e.get("slippage_pct", 0) for e in recent]), 4)

    def perlu_twap(self, symbol, qty_usd, threshold_usd=200):
        """
        Apakah order ini memerlukan TWAP?
        TWAP diperlukan jika:
        - Order besar (> threshold_usd), ATAU
        - Slippage historis tinggi (> 0.2%)
        """
        avg_slip = self.get_avg_slippage(symbol)
        return qty_usd > threshold_usd or avg_slip > 0.2

    def format_report(self, n=10):
        """Format laporan kualitas eksekusi."""
        if not self.history:
            return "Belum ada data eksekusi"

        recent = self.history[-n:]
        avg_slip = np.mean([e.get("slippage_pct", 0) for e in recent])
        teks = (f"📊 Execution Quality (last {len(recent)} orders)\n"
                f"Avg Slippage: {avg_slip:.3f}%\n")

        for e in recent[-5:]:
            teks += (f"  {e['symbol']:10} {e['metode']:5} "
                     f"slip:{e['slippage_pct']:.3f}% "
                     f"@{e['exchange']}\n")
        return teks


# ══════════════════════════════════════════════
# 6. EXECUTION ENGINE — main orchestrator
# ══════════════════════════════════════════════

class ExecutionEngine:
    """
    Mesin eksekusi utama yang mengorkestrasi:
    - TCM (Transaction Cost Model)
    - TWAP / Market order selector
    - VWAP timing
    - Smart Order Routing
    - Quality monitoring
    """

    def __init__(self):
        self.tcm     = TransactionCostModel()
        self.twap    = TWAPExecutor()
        self.vwap    = VWAPExecutor()
        self.router  = SmartOrderRouter()
        self.monitor = ExecutionQualityMonitor()

    def pre_trade_check(self, client, symbol, qty_usd,
                         orderbook=None, tipe="spot"):
        """
        Cek semua kondisi SEBELUM eksekusi order.

        Return:
            lanjut     : bool
            alasan     : str
            biaya      : dict biaya estimasi
        """
        # 1. Cek liquidity
        vol_profile = self.vwap.hitung_volume_profile(client, symbol)
        vol_24h     = vol_profile.get("avg_volume", 0) * 24
        vol_usd_24h = vol_24h * 50000  # rough estimate

        if vol_usd_24h < MIN_LIQUIDITY_USD and vol_usd_24h > 0:
            return False, f"Likuiditas rendah: ${vol_usd_24h:,.0f} < ${MIN_LIQUIDITY_USD:,.0f}", {}

        # 2. Estimasi biaya
        biaya = self.tcm.hitung_total_biaya(
            qty_usd, 0, orderbook, vol_usd_24h, tipe
        )

        # 3. Cek slippage
        if biaya["slippage_pct"] > MAX_SLIPPAGE_PCT / 100:
            return False, f"Slippage terlalu tinggi: {biaya['slippage_pct']*100:.2f}%", biaya

        return True, "OK", biaya

    def eksekusi_beli(self, client, symbol, harga_sinyal, qty,
                       qty_usd=100, orderbook=None, paper_mode=False,
                       kirim_telegram=None):
        """
        Eksekusi BUY dengan metode terbaik secara otomatis.

        Logic:
        - Order kecil (< $200) + likuiditas baik → Market order
        - Order besar (> $200) → TWAP
        - Slippage historis tinggi → TWAP
        """
        t_start  = time.time()
        metode   = "MARKET"
        exchange = self.router.get_best_exchange(symbol, qty_usd)[0]

        # Pre-trade check
        lanjut, alasan, biaya = self.pre_trade_check(
            client, symbol, qty_usd, orderbook)

        if not lanjut:
            print(f"  ⛔ Pre-trade check gagal: {alasan}")
            return {"sukses": False, "alasan": alasan}

        # Pilih metode eksekusi
        if self.monitor.perlu_twap(symbol, qty_usd):
            metode = "TWAP"

        # Cek VWAP timing
        if not paper_mode and not self.vwap.should_execute_now(client, symbol):
            print(f"  ⚠️  Volume rendah saat ini — pakai TWAP untuk minimasi slippage")
            metode = "TWAP"

        print(f"\n  ⚡ Execution: {metode} | Exchange: {exchange} | "
              f"Est.cost: {biaya.get('total_pct',0)*100:.3f}%")

        # Eksekusi
        if metode == "TWAP":
            sukses, avg_harga, qty_terisi, detail = self.twap.execute_twap_buy(
                client, symbol, qty, kirim_telegram, paper_mode)
        else:
            # Market order biasa
            try:
                if paper_mode:
                    avg_harga  = harga_sinyal
                    qty_terisi = qty
                    sukses     = True
                else:
                    resp       = client.order_market_buy(
                        symbol=symbol, quantity=qty)
                    qty_terisi = float(resp.get("executedQty", qty))
                    avg_harga  = (float(resp.get("cummulativeQuoteQty", 0)) /
                                  qty_terisi if qty_terisi > 0 else harga_sinyal)
                    sukses     = qty_terisi > 0
            except Exception as e:
                print(f"  ❌ Market order error: {e}")
                return {"sukses": False, "alasan": str(e)}

        # Catat kualitas eksekusi
        if sukses and avg_harga > 0:
            slippage = self.monitor.catat_eksekusi(
                symbol, harga_sinyal, avg_harga, qty_terisi, metode, exchange)

        latency_ms = round((time.time() - t_start) * 1000, 1)
        self.router.log_latency(exchange, latency_ms)

        return {
            "sukses"   : sukses,
            "metode"   : metode,
            "exchange" : exchange,
            "avg_harga": avg_harga if sukses else 0,
            "qty"      : qty_terisi if sukses else 0,
            "biaya"    : biaya,
            "latency_ms": latency_ms,
        }

    def get_execution_report(self):
        """Return laporan kualitas eksekusi."""
        return self.monitor.format_report()


# ── SINGLETON ─────────────────────────────────
_exec_engine = None

def get_execution_engine():
    """Return singleton ExecutionEngine."""
    global _exec_engine
    if _exec_engine is None:
        _exec_engine = ExecutionEngine()
    return _exec_engine


def hitung_breakeven(qty_usd, orderbook=None, tipe="spot"):
    """
    Hitung minimum return yang dibutuhkan untuk profit
    setelah semua biaya transaksi.
    """
    engine = get_execution_engine()
    return engine.tcm.breakeven_return(qty_usd, orderbook, tipe)