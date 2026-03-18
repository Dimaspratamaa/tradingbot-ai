# ============================================
# ORDER BOOK ANALYZER v1.0
# Fitur:
#   1. Order Book Depth (bid/ask pressure)
#   2. Spoofing Detection (order hilang tiba2)
#   3. Iceberg Order Detection
# ============================================

import time
import numpy as np
from collections import defaultdict

# ── KONFIGURASI ───────────────────────────────

# Order Book Depth
DEPTH_LEVEL        = 20      # Ambil 20 level bid & ask
IMBALANCE_BULL     = 1.5     # Bid 1.5x lebih tebal dari ask = bullish
IMBALANCE_BEAR     = 0.67    # Ask 1.5x lebih tebal dari bid = bearish

# Spoofing Detection
SPOOF_MIN_SIZE     = 50_000  # Order > $50k dianggap "besar"
SPOOF_HILANG_PCT   = 0.7     # 70% order besar hilang = spoof
SPOOF_WINDOW       = 60      # Bandingkan snapshot dalam 60 detik

# Iceberg Detection
ICEBERG_REFRESH    = 3       # Order diisi ulang >= 3x = iceberg
ICEBERG_MIN_SIZE   = 10_000  # Minimum size untuk dianggap iceberg

# ── STORAGE SNAPSHOT ──────────────────────────
# Format: {symbol: [{"waktu": t, "bids": [...], "asks": [...]}, ...]}
_snapshots  = defaultdict(list)
_max_snap   = 10    # Simpan maksimal 10 snapshot per koin

# ── HELPER ────────────────────────────────────

def _total_value(orders, harga_ref):
    """
    Hitung total nilai USD dari list order.
    orders = [[price_str, qty_str], ...]
    """
    total = 0
    for price, qty in orders:
        total += float(price) * float(qty)
    return total

def _orders_ke_dict(orders):
    """Konversi list order ke dict {price: qty}"""
    return {float(p): float(q) for p, q in orders}

# ══════════════════════════════════════════════
# 1. ORDER BOOK DEPTH ANALYSIS
# ══════════════════════════════════════════════

def analisis_depth(order_book, harga):
    """
    Analisis tekanan beli vs jual dari order book.

    Args:
        order_book: hasil client.get_order_book()
        harga: harga current

    Return dict:
        skor_buy  : int (0-3)
        skor_sell : int (0-3)
        imbalance : float (>1 = bid lebih tebal)
        bid_total : float (total USD di sisi beli)
        ask_total : float (total USD di sisi jual)
        detail    : str
        sinyal    : str (BULLISH/BEARISH/NETRAL)
    """
    try:
        bids = order_book["bids"][:DEPTH_LEVEL]   # Top 20 beli
        asks = order_book["asks"][:DEPTH_LEVEL]   # Top 20 jual

        bid_total = _total_value(bids, harga)
        ask_total = _total_value(asks, harga)

        if ask_total == 0:
            return _default_depth()

        imbalance = bid_total / ask_total

        # ── Tentukan sinyal & skor ──
        skor_buy  = 0
        skor_sell = 0
        detail    = []

        if imbalance >= 2.0:
            skor_buy = 3
            sinyal   = "BULLISH_KUAT"
            detail.append(f"📗 Bid {imbalance:.1f}x lebih tebal!")
        elif imbalance >= IMBALANCE_BULL:
            skor_buy = 2
            sinyal   = "BULLISH"
            detail.append(f"📗 Bid lebih tebal ({imbalance:.1f}x)")
        elif imbalance >= 1.1:
            skor_buy = 1
            sinyal   = "SEDIKIT_BULLISH"
            detail.append(f"📗 Bid sedikit lebih tebal ({imbalance:.1f}x)")
        elif imbalance <= 0.5:
            skor_sell = 3
            sinyal    = "BEARISH_KUAT"
            detail.append(f"📕 Ask {1/imbalance:.1f}x lebih tebal!")
        elif imbalance <= IMBALANCE_BEAR:
            skor_sell = 2
            sinyal    = "BEARISH"
            detail.append(f"📕 Ask lebih tebal ({1/imbalance:.1f}x)")
        elif imbalance <= 0.9:
            skor_sell = 1
            sinyal    = "SEDIKIT_BEARISH"
            detail.append(f"📕 Ask sedikit lebih tebal")
        else:
            sinyal = "NETRAL"
            detail.append("⚪ Order book seimbang")

        # ── Cek konsentrasi (whale wall) ──
        # Jika 1 level bid/ask sangat dominan = ada support/resistance kuat
        bid_terbesar = max(float(b[0]) * float(b[1]) for b in bids)
        ask_terbesar = max(float(a[0]) * float(a[1]) for a in asks)

        if bid_terbesar > bid_total * 0.3:
            detail.append(f"🐳 Whale BID wall ${bid_terbesar/1000:.0f}k!")
            skor_buy = min(skor_buy + 1, 3)

        if ask_terbesar > ask_total * 0.3:
            detail.append(f"🐳 Whale ASK wall ${ask_terbesar/1000:.0f}k!")
            skor_sell = min(skor_sell + 1, 3)

        return {
            "skor_buy" : skor_buy,
            "skor_sell": skor_sell,
            "imbalance": round(imbalance, 3),
            "bid_total": round(bid_total, 0),
            "ask_total": round(ask_total, 0),
            "sinyal"   : sinyal,
            "detail"   : detail
        }

    except Exception as e:
        print(f"  ⚠️  Depth error: {e}")
        return _default_depth()


# ══════════════════════════════════════════════
# 2. SPOOFING DETECTION
# ══════════════════════════════════════════════

def simpan_snapshot(symbol, order_book):
    """Simpan snapshot order book untuk perbandingan"""
    snapshot = {
        "waktu": time.time(),
        "bids" : _orders_ke_dict(order_book["bids"][:DEPTH_LEVEL]),
        "asks" : _orders_ke_dict(order_book["asks"][:DEPTH_LEVEL])
    }
    _snapshots[symbol].append(snapshot)

    # Batasi jumlah snapshot
    if len(_snapshots[symbol]) > _max_snap:
        _snapshots[symbol].pop(0)

def deteksi_spoofing(symbol, harga):
    """
    Deteksi spoofing dengan membandingkan snapshot lama vs baru.
    Spoof = order besar muncul lalu hilang tanpa tereksekusi.

    Return dict:
        terdeteksi : bool
        skor_sell  : int (0-3, makin tinggi makin manipulatif)
        detail     : list[str]
        spoof_side : str (BID/ASK/NONE)
    """
    snaps = _snapshots.get(symbol, [])
    if len(snaps) < 2:
        return _default_spoof()

    # Bandingkan snapshot terlama vs terbaru
    snap_lama = snaps[0]
    snap_baru = snaps[-1]

    selisih_waktu = snap_baru["waktu"] - snap_lama["waktu"]
    if selisih_waktu > SPOOF_WINDOW * 3:
        return _default_spoof()

    spoof_bid = _cek_spoof_sisi(
        snap_lama["bids"], snap_baru["bids"], harga, "BID"
    )
    spoof_ask = _cek_spoof_sisi(
        snap_lama["asks"], snap_baru["asks"], harga, "ASK"
    )

    detail      = []
    skor_sell   = 0
    terdeteksi  = False
    spoof_side  = "NONE"

    # Spoof di sisi BID = pura-pura mau beli, padahal mau jual
    # → Bearish, kurangi skor beli
    if spoof_bid["terdeteksi"]:
        terdeteksi = True
        spoof_side = "BID"
        n    = spoof_bid["n_order_hilang"]
        nilai = spoof_bid["nilai_hilang"]
        if nilai >= SPOOF_MIN_SIZE * 3:
            skor_sell += 3
            detail.append(
                f"🎭 SPOOF BID KUAT! {n} order besar hilang "
                f"(${nilai/1000:.0f}k)"
            )
        elif nilai >= SPOOF_MIN_SIZE:
            skor_sell += 2
            detail.append(
                f"🎭 Spoof BID: {n} order hilang (${nilai/1000:.0f}k)"
            )
        else:
            skor_sell += 1
            detail.append(f"⚠️ Potensi spoof BID")

    # Spoof di sisi ASK = pura-pura mau jual, padahal mau beli
    # → Bullish trap, tetap waspada
    if spoof_ask["terdeteksi"]:
        terdeteksi = True
        if spoof_side == "BID":
            spoof_side = "KEDUANYA"
        else:
            spoof_side = "ASK"
        n    = spoof_ask["n_order_hilang"]
        nilai = spoof_ask["nilai_hilang"]
        detail.append(
            f"🎭 Spoof ASK: {n} order hilang (${nilai/1000:.0f}k)"
        )

    if not terdeteksi:
        detail.append("✅ Tidak ada indikasi spoofing")

    return {
        "terdeteksi": terdeteksi,
        "skor_sell" : min(skor_sell, 3),
        "detail"    : detail,
        "spoof_side": spoof_side
    }

def _cek_spoof_sisi(orders_lama, orders_baru, harga, sisi):
    """
    Cek apakah ada order besar yang hilang dari satu sisi.
    Order hilang = ada di snapshot lama, tidak ada di baru,
    dan harga tidak melewatinya (belum tereksekusi).
    """
    n_hilang    = 0
    nilai_hilang = 0.0

    for price, qty in orders_lama.items():
        nilai = price * qty

        # Skip order kecil
        if nilai < SPOOF_MIN_SIZE * 0.3:
            continue

        # Cek apakah order masih ada di snapshot baru
        masih_ada = price in orders_baru

        if not masih_ada:
            # Cek apakah harga sudah melewati level ini
            # Jika sudah terlewati = bukan spoof, memang tereksekusi
            if sisi == "BID" and harga > price * 1.002:
                continue  # Tereksekusi wajar
            if sisi == "ASK" and harga < price * 0.998:
                continue  # Tereksekusi wajar

            # Order besar hilang tanpa tereksekusi = SPOOF!
            n_hilang     += 1
            nilai_hilang += nilai

    return {
        "terdeteksi"    : n_hilang >= 1 and nilai_hilang >= SPOOF_MIN_SIZE,
        "n_order_hilang": n_hilang,
        "nilai_hilang"  : nilai_hilang
    }


# ══════════════════════════════════════════════
# 3. ICEBERG ORDER DETECTION
# ══════════════════════════════════════════════

def deteksi_iceberg(trades_history, order_book, harga):
    """
    Deteksi iceberg order dari trade history.
    Iceberg = order besar dieksekusi berulang di harga yang sama
              → tanda ada hidden order yang terus diisi ulang.

    Args:
        trades_history: hasil client.get_recent_trades()
        order_book    : order book saat ini
        harga         : harga current

    Return dict:
        terdeteksi   : bool
        skor_buy     : int (0-2) jika iceberg di sisi beli
        skor_sell    : int (0-2) jika iceberg di sisi jual
        detail       : list[str]
        iceberg_side : str (BUY/SELL/NONE)
    """
    try:
        if not trades_history:
            return _default_iceberg()

        # ── Kelompokkan trade berdasarkan harga ──
        harga_count  = defaultdict(lambda: {"qty": 0, "count": 0, "buy": 0, "sell": 0})

        for trade in trades_history[-200:]:  # Analisis 200 trade terakhir
            p   = round(float(trade["price"]), 6)
            qty = float(trade["qty"])
            is_buy = not trade["isBuyerMaker"]  # True = buy order

            harga_count[p]["qty"]   += qty
            harga_count[p]["count"] += 1
            if is_buy:
                harga_count[p]["buy"] += qty
            else:
                harga_count[p]["sell"] += qty

        # ── Deteksi level dengan aktivitas berulang ──
        detail       = []
        skor_buy     = 0
        skor_sell    = 0
        iceberg_side = "NONE"
        terdeteksi   = False

        for price, data in harga_count.items():
            nilai_total = price * data["qty"]

            # Skip jika total terlalu kecil
            if nilai_total < ICEBERG_MIN_SIZE:
                continue

            # Tereksekusi banyak kali di harga yang sama = iceberg
            if data["count"] >= ICEBERG_REFRESH:
                buy_ratio  = data["buy"] / (data["qty"] or 1)
                sell_ratio = data["sell"] / (data["qty"] or 1)

                # Iceberg BUY (akumulasi diam-diam)
                if buy_ratio >= 0.7 and price <= harga * 1.005:
                    terdeteksi   = True
                    iceberg_side = "BUY"
                    kekuatan     = "KUAT" if data["count"] >= 8 else "SEDANG"
                    skor_buy     = 2 if data["count"] >= 8 else 1
                    detail.append(
                        f"🧊 Iceberg BUY {kekuatan} @ ${price:,.4f} "
                        f"({data['count']}x, ${nilai_total/1000:.0f}k)"
                    )

                # Iceberg SELL (distribusi diam-diam)
                elif sell_ratio >= 0.7 and price >= harga * 0.995:
                    terdeteksi   = True
                    iceberg_side = "SELL"
                    kekuatan     = "KUAT" if data["count"] >= 8 else "SEDANG"
                    skor_sell    = 2 if data["count"] >= 8 else 1
                    detail.append(
                        f"🧊 Iceberg SELL {kekuatan} @ ${price:,.4f} "
                        f"({data['count']}x, ${nilai_total/1000:.0f}k)"
                    )

        # ── Cek order book untuk konfirmasi ──
        # Jika ada iceberg BUY, cek apakah ada support kuat di bid
        if iceberg_side == "BUY":
            bids = _orders_ke_dict(order_book["bids"][:5])
            ada_support = any(
                p * q >= ICEBERG_MIN_SIZE
                for p, q in bids.items()
            )
            if ada_support:
                detail.append("✅ Dikonfirmasi: Support kuat di bid")
                skor_buy = min(skor_buy + 1, 2)

        if not detail:
            detail.append("✅ Tidak ada iceberg order terdeteksi")

        return {
            "terdeteksi"  : terdeteksi,
            "skor_buy"    : skor_buy,
            "skor_sell"   : skor_sell,
            "detail"      : detail,
            "iceberg_side": iceberg_side
        }

    except Exception as e:
        print(f"  ⚠️  Iceberg error: {e}")
        return _default_iceberg()


# ══════════════════════════════════════════════
# FUNGSI UTAMA: ANALISIS LENGKAP ORDER BOOK
# ══════════════════════════════════════════════

def analisis_orderbook(client, symbol):
    """
    Fungsi utama — jalankan semua analisis order book.
    Dipanggil dari bot utama saat scan koin.

    Return dict:
        skor_buy       : int  → tambahan skor beli
        skor_sell      : int  → pengurang skor / block
        manipulasi     : bool → True jika ada manipulasi kuat
        block_entry    : bool → True jika sebaiknya tidak entry
        depth          : dict
        spoof          : dict
        iceberg        : dict
        detail         : list[str] ringkasan
        summary        : str satu baris untuk log
    """
    try:
        harga = float(client.get_symbol_ticker(symbol=symbol)["price"])

        # Ambil data
        order_book = client.get_order_book(symbol=symbol, limit=DEPTH_LEVEL)
        trades     = client.get_recent_trades(symbol=symbol, limit=200)

        # Simpan snapshot untuk spoofing
        simpan_snapshot(symbol, order_book)

        # Jalankan 3 analisis
        depth   = analisis_depth(order_book, harga)
        spoof   = deteksi_spoofing(symbol, harga)
        iceberg = deteksi_iceberg(trades, order_book, harga)

        # ── Gabungkan skor ──
        skor_buy  = depth["skor_buy"]  + iceberg["skor_buy"]
        skor_sell = depth["skor_sell"] + spoof["skor_sell"] + iceberg["skor_sell"]

        # ── Tentukan manipulasi & block ──
        manipulasi  = spoof["terdeteksi"]
        block_entry = (
            spoof["skor_sell"] >= 3 or      # Spoof sangat kuat
            (spoof["terdeteksi"] and depth["skor_sell"] >= 2)  # Spoof + bearish
        )

        # ── Ringkasan detail ──
        detail = []
        detail.extend(depth["detail"])
        detail.extend(spoof["detail"])
        detail.extend(iceberg["detail"])

        summary = (
            f"Depth:{depth['sinyal']} "
            f"Imbal:{depth['imbalance']:.2f} | "
            f"Spoof:{spoof['spoof_side']} | "
            f"Ice:{iceberg['iceberg_side']}"
        )

        if block_entry:
            detail.insert(0, "🚫 BLOCK ENTRY: Manipulasi terdeteksi!")

        return {
            "skor_buy"  : min(skor_buy, 4),
            "skor_sell" : min(skor_sell, 4),
            "manipulasi": manipulasi,
            "block_entry": block_entry,
            "depth"     : depth,
            "spoof"     : spoof,
            "iceberg"   : iceberg,
            "detail"    : detail,
            "summary"   : summary
        }

    except Exception as e:
        print(f"  ⚠️  OrderBook error {symbol}: {e}")
        return _default_result()


# ── DEFAULT RETURNS ───────────────────────────

def _default_depth():
    return {
        "skor_buy": 0, "skor_sell": 0,
        "imbalance": 1.0, "bid_total": 0, "ask_total": 0,
        "sinyal": "NETRAL", "detail": ["⚠️ Data depth tidak tersedia"]
    }

def _default_spoof():
    return {
        "terdeteksi": False, "skor_sell": 0,
        "detail": ["✅ Tidak ada data spoof"],
        "spoof_side": "NONE"
    }

def _default_iceberg():
    return {
        "terdeteksi": False, "skor_buy": 0, "skor_sell": 0,
        "detail": ["✅ Tidak ada iceberg"],
        "iceberg_side": "NONE"
    }

def _default_result():
    return {
        "skor_buy": 0, "skor_sell": 0,
        "manipulasi": False, "block_entry": False,
        "depth": _default_depth(),
        "spoof": _default_spoof(),
        "iceberg": _default_iceberg(),
        "detail": ["⚠️ Analisis orderbook gagal"],
        "summary": "N/A"
    }


# ── TEST ──────────────────────────────────────
if __name__ == "__main__":
    from binance.client import Client
    import os

    API_KEY    = os.environ.get("BINANCE_API_KEY", "")
    API_SECRET = os.environ.get("BINANCE_API_SECRET", "")

    client = Client(API_KEY, API_SECRET, testnet=True)

    print("=" * 60)
    print("   ORDER BOOK ANALYZER v1.0")
    print("=" * 60)

    symbol = "BTCUSDT"
    print(f"\n🔍 Analisis {symbol}...")

    # Simpan 2 snapshot dulu untuk spoof detection
    ob1 = client.get_order_book(symbol=symbol, limit=20)
    simpan_snapshot(symbol, ob1)
    print("  📸 Snapshot 1 diambil, tunggu 5 detik...")
    time.sleep(5)

    hasil = analisis_orderbook(client, symbol)

    print(f"\n📊 HASIL ANALISIS ORDER BOOK:")
    print(f"  Summary   : {hasil['summary']}")
    print(f"  Skor BUY  : +{hasil['skor_buy']}")
    print(f"  Skor SELL : -{hasil['skor_sell']}")
    print(f"  Manipulasi: {'⚠️ YA' if hasil['manipulasi'] else '✅ TIDAK'}")
    print(f"  Block Entry: {'🚫 YA' if hasil['block_entry'] else '✅ TIDAK'}")

    print(f"\n📗 Depth Analysis:")
    print(f"  Sinyal   : {hasil['depth']['sinyal']}")
    print(f"  Imbalance: {hasil['depth']['imbalance']:.3f}")
    print(f"  Bid Total: ${hasil['depth']['bid_total']:,.0f}")
    print(f"  Ask Total: ${hasil['depth']['ask_total']:,.0f}")

    print(f"\n🎭 Spoofing Detection:")
    for d in hasil['spoof']['detail']:
        print(f"  {d}")

    print(f"\n🧊 Iceberg Detection:")
    for d in hasil['iceberg']['detail']:
        print(f"  {d}")
