# ============================================
# SMART PYRAMIDING v1.0
# Tambah posisi saat profit (scale-in)
# Strategy: add 50% dari posisi awal
#           setiap kali profit naik X%
# ============================================

import time

# ── KONFIGURASI ───────────────────────────────
PYRAMID_PROFIT_TRIGGER = 2.0   # Tambah posisi saat profit >= 2%
PYRAMID_MAX_LEVEL      = 2     # Maksimal 2x pyramid (total 3 entry)
PYRAMID_SIZE_PCT       = 0.5   # Tambah 50% dari posisi awal
PYRAMID_SL_ADJUST      = True  # Naikkan SL ke breakeven saat pyramid

# ── STATE ─────────────────────────────────────
# Format: {"BTCUSDT": {"level": 1, "entry_avg": ..., "total_qty": ...}}
pyramid_state = {}

# ══════════════════════════════════════════════
# CEK & EKSEKUSI PYRAMIDING
# ══════════════════════════════════════════════

def cek_pyramiding(symbol, pos, harga_skrng, client,
                   trade_usdt, kirim_telegram):
    """
    Cek apakah kondisi untuk pyramid terpenuhi.
    Jika ya, tambah posisi dan update state.

    Args:
        symbol      : trading pair
        pos         : dict posisi aktif dari posisi_spot
        harga_skrng : harga saat ini
        client      : binance client
        trade_usdt  : modal awal per posisi
        kirim_telegram: fungsi kirim Telegram

    Return: bool (True jika pyramid dieksekusi)
    """
    if not pos.get("aktif"):
        return False

    harga_beli = pos["harga_beli"]
    profit_pct = ((harga_skrng - harga_beli) / harga_beli) * 100

    # Inisialisasi state jika belum ada
    if symbol not in pyramid_state:
        pyramid_state[symbol] = {
            "level"    : 0,
            "entry_avg": harga_beli,
            "total_qty": pos["qty"],
            "total_cost": harga_beli * pos["qty"]
        }

    state = pyramid_state[symbol]

    # Cek apakah sudah maksimal level
    if state["level"] >= PYRAMID_MAX_LEVEL:
        return False

    # Threshold profit untuk pyramid berikutnya
    # Level 1: profit 2%, Level 2: profit 4%
    threshold = PYRAMID_PROFIT_TRIGGER * (state["level"] + 1)

    if profit_pct < threshold:
        return False

    # ── Eksekusi Pyramid ──
    waktu     = time.strftime("%Y-%m-%d %H:%M:%S")
    qty_tambah = _hitung_qty_pyramid(
        symbol, harga_skrng, trade_usdt, client
    )

    if qty_tambah <= 0:
        return False

    print(f"\n  📈 [{symbol}] PYRAMID Level {state['level']+1}! "
          f"Profit:{profit_pct:.2f}% Qty:{qty_tambah}")

    try:
        client.order_market_buy(symbol=symbol, quantity=qty_tambah)
    except Exception as e:
        print(f"  ⚠️  Gagal pyramid {symbol}: {e}")
        return False

    # Update state
    cost_baru   = harga_skrng * qty_tambah
    total_cost  = state["total_cost"] + cost_baru
    total_qty   = state["total_qty"] + qty_tambah
    entry_avg   = total_cost / total_qty

    pyramid_state[symbol] = {
        "level"     : state["level"] + 1,
        "entry_avg" : entry_avg,
        "total_qty" : total_qty,
        "total_cost": total_cost
    }

    # Adjust SL ke breakeven jika dikonfigurasi
    sl_baru = None
    if PYRAMID_SL_ADJUST:
        # Naikkan SL ke harga entry rata-rata (breakeven)
        sl_baru = entry_avg * 0.995  # Sedikit di bawah breakeven
        if sl_baru > pos["stop_loss"]:
            pos["stop_loss"] = sl_baru

    # Kirim notifikasi
    kirim_telegram(
        f"📈 <b>PYRAMID Level {state['level']+1} - {symbol}</b>\n\n"
        f"💰 Entry awal : ${harga_beli:,.4f}\n"
        f"💰 Add entry  : ${harga_skrng:,.4f}\n"
        f"📊 Entry avg  : ${entry_avg:,.4f}\n"
        f"📈 Profit saat ini: <b>+{profit_pct:.2f}%</b>\n"
        f"🔢 Qty tambah : {qty_tambah}\n"
        f"🔢 Total qty  : {total_qty:.4f}\n"
        + (f"🛑 SL → ${sl_baru:,.4f} (breakeven)\n"
           if sl_baru else "")
        + f"🕐 {waktu}"
    )

    return True

def _hitung_qty_pyramid(symbol, harga, trade_usdt, client):
    """Hitung quantity untuk pyramid order"""
    modal_tambah = trade_usdt * PYRAMID_SIZE_PCT
    qty = modal_tambah / harga

    if harga > 1000:   qty = round(qty, 3)
    elif harga > 1:    qty = round(qty, 2)
    else:              qty = round(qty, 0)

    return qty

def reset_pyramid(symbol):
    """Reset pyramid state saat posisi ditutup"""
    if symbol in pyramid_state:
        del pyramid_state[symbol]

def cek_semua_pyramid(posisi_spot, client,
                      trade_usdt, kirim_telegram):
    """
    Cek pyramiding untuk semua posisi aktif.
    Dipanggil di setiap siklus setelah cek SL/TP.
    """
    for symbol, pos in posisi_spot.items():
        if not pos.get("aktif"):
            reset_pyramid(symbol)
            continue

        try:
            ticker = client.get_symbol_ticker(symbol=symbol)
            harga  = float(ticker["price"])

            cek_pyramiding(
                symbol, pos, harga, client,
                trade_usdt, kirim_telegram
            )
        except Exception as e:
            print(f"  ⚠️  Pyramid check {symbol}: {e}")

def get_pyramid_info(symbol):
    """Ambil info pyramid untuk display"""
    state = pyramid_state.get(symbol)
    if not state or state["level"] == 0:
        return ""
    return (f" 📈Pyr:L{state['level']} "
            f"avg:${state['entry_avg']:,.4f}")