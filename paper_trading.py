# ============================================
# PAPER TRADING ENGINE v1.0
# Simulasi trading tanpa uang asli
#
# Fitur:
#   1. Simulasi spot & futures dengan harga real Binance
#   2. Modal virtual $5,000 USDT
#   3. Tracking P&L real-time
#   4. Laporan performa lengkap (win rate, Sharpe, dll)
#   5. Switch ke live trading dengan 1 perintah Telegram
#   6. Persistent state (tidak hilang jika bot restart)
# ============================================

import json
import os
import time
import pathlib
from datetime import datetime, timezone

# ── KONFIGURASI ───────────────────────────────
PAPER_FILE        = pathlib.Path(__file__).parent / "paper_state.json"
PAPER_MODAL_AWAL  = 5000.0   # $5,000 USDT simulasi
PAPER_FEE_SPOT    = 0.001    # 0.1% fee per transaksi (realistis Binance)
PAPER_FEE_FUTURES = 0.0004   # 0.04% fee futures taker
PAPER_SLIPPAGE    = 0.0005   # 0.05% slippage simulasi

# ── STATE GLOBAL ──────────────────────────────
_state = None

def _waktu():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

# ══════════════════════════════════════════════
# 1. STATE MANAGEMENT — load/save ke disk
# ══════════════════════════════════════════════

def _state_default():
    return {
        "aktif"          : True,         # True = paper mode, False = live mode
        "modal_awal"     : PAPER_MODAL_AWAL,
        "saldo_usdt"     : PAPER_MODAL_AWAL,
        "posisi_spot"    : {},           # {symbol: {harga_beli, qty, sl, tp, ...}}
        "posisi_futures" : {},           # {symbol: {side, entry, qty, sl, tp, ...}}
        "riwayat"        : [],           # list semua trade selesai
        "statistik"      : {
            "total_trade"  : 0,
            "win"          : 0,
            "loss"         : 0,
            "total_profit" : 0.0,
            "total_loss"   : 0.0,
            "max_drawdown" : 0.0,
            "peak_equity"  : PAPER_MODAL_AWAL,
        },
        "dibuat"         : _waktu(),
        "update_terakhir": _waktu(),
    }

def load_state():
    global _state
    if PAPER_FILE.exists():
        try:
            _state = json.loads(PAPER_FILE.read_text())
            return _state
        except Exception:
            pass
    _state = _state_default()
    save_state()
    return _state

def save_state():
    global _state
    if _state is None:
        return
    _state["update_terakhir"] = _waktu()
    PAPER_FILE.write_text(json.dumps(_state, indent=2, ensure_ascii=False))

def is_paper_mode():
    """Return True jika bot dalam mode paper trading"""
    st = load_state()
    return st.get("aktif", True)

def switch_ke_live():
    """Switch dari paper ke live mode"""
    st = load_state()
    st["aktif"] = False
    save_state()
    print("  🔴 PAPER MODE DIMATIKAN — bot sekarang LIVE TRADING!")

def switch_ke_paper():
    """Switch kembali ke paper mode"""
    st = load_state()
    st["aktif"] = True
    save_state()
    print("  📝 Kembali ke PAPER MODE")

# ══════════════════════════════════════════════
# 2. EKSEKUSI ORDER SIMULASI
# ══════════════════════════════════════════════

def paper_beli_spot(symbol, harga_raw, qty, sl, tp, detail_str=""):
    """
    Simulasi BUY spot order.
    Return True jika berhasil, False jika saldo tidak cukup.
    """
    st = load_state()

    # Harga dengan slippage (beli = sedikit lebih mahal)
    harga  = harga_raw * (1 + PAPER_SLIPPAGE)
    nilai  = harga * qty
    fee    = nilai * PAPER_FEE_SPOT
    total  = nilai + fee

    if st["saldo_usdt"] < total:
        print(f"  ⚠️  [PAPER] Saldo tidak cukup: ${st['saldo_usdt']:.2f} < ${total:.2f}")
        return False

    st["saldo_usdt"] -= total
    st["posisi_spot"][symbol] = {
        "aktif"      : True,
        "harga_beli" : harga,
        "harga_raw"  : harga_raw,
        "qty"        : qty,
        "nilai_masuk": total,
        "fee_masuk"  : fee,
        "stop_loss"  : sl,
        "take_profit": tp,
        "waktu_beli" : _waktu(),
        "trailing_aktif"  : False,
        "harga_tertinggi" : harga,
        "detail"     : detail_str,
    }

    save_state()
    print(f"  📝 [PAPER] BUY {symbol} | Harga: ${harga:,.4f} | "
          f"Qty: {qty} | Fee: ${fee:.4f} | "
          f"Saldo: ${st['saldo_usdt']:,.2f}")
    return True

def paper_jual_spot(symbol, harga_raw, alasan="PAPER_SELL"):
    """Simulasi SELL spot order, hitung P&L."""
    st = load_state()
    pos = st["posisi_spot"].get(symbol)
    if not pos or not pos.get("aktif"):
        return False

    # Harga dengan slippage (jual = sedikit lebih murah)
    harga   = harga_raw * (1 - PAPER_SLIPPAGE)
    qty     = pos["qty"]
    nilai   = harga * qty
    fee     = nilai * PAPER_FEE_SPOT
    hasil   = nilai - fee

    pnl_usd = hasil - pos["nilai_masuk"]
    pnl_pct = (pnl_usd / pos["nilai_masuk"]) * 100

    st["saldo_usdt"] += hasil

    # Update statistik
    s = st["statistik"]
    s["total_trade"] += 1
    if pnl_usd >= 0:
        s["win"]          += 1
        s["total_profit"] += pnl_usd
    else:
        s["loss"]         += 1
        s["total_loss"]   += abs(pnl_usd)

    # Update peak & drawdown
    equity = st["saldo_usdt"] + _nilai_posisi_terbuka(st, {})
    if equity > s["peak_equity"]:
        s["peak_equity"] = equity
    drawdown = (s["peak_equity"] - equity) / s["peak_equity"] * 100
    if drawdown > s["max_drawdown"]:
        s["max_drawdown"] = drawdown

    # Simpan ke riwayat
    st["riwayat"].append({
        "tipe"       : "SPOT",
        "symbol"     : symbol,
        "side"       : "BUY→SELL",
        "harga_beli" : pos["harga_beli"],
        "harga_jual" : harga,
        "qty"        : qty,
        "pnl_usd"    : round(pnl_usd, 4),
        "pnl_pct"    : round(pnl_pct, 4),
        "fee_total"  : round(pos["fee_masuk"] + fee, 4),
        "waktu_beli" : pos["waktu_beli"],
        "waktu_jual" : _waktu(),
        "alasan"     : alasan,
    })

    st["posisi_spot"][symbol]["aktif"] = False
    save_state()

    emoji = "✅" if pnl_usd >= 0 else "❌"
    print(f"  📝 [PAPER] SELL {symbol} | {emoji} P&L: ${pnl_usd:+.2f} "
          f"({pnl_pct:+.2f}%) | Saldo: ${st['saldo_usdt']:,.2f}")
    return pnl_usd

def paper_buka_futures(symbol, side, harga_raw, qty, sl, tp, leverage, detail_str=""):
    """Simulasi buka posisi futures (LONG/SHORT)."""
    st = load_state()

    # Margin yang dibutuhkan (qty * harga / leverage)
    harga  = harga_raw * (1 + PAPER_SLIPPAGE if side == "LONG" else 1 - PAPER_SLIPPAGE)
    nilai  = harga * qty
    margin = nilai / leverage
    fee    = nilai * PAPER_FEE_FUTURES

    if st["saldo_usdt"] < (margin + fee):
        print(f"  ⚠️  [PAPER] Margin tidak cukup: ${st['saldo_usdt']:.2f}")
        return False

    st["saldo_usdt"] -= (margin + fee)
    st["posisi_futures"][symbol] = {
        "aktif"          : True,
        "side"           : side,
        "entry"          : harga,
        "harga_raw"      : harga_raw,
        "qty"            : qty,
        "margin"         : margin,
        "fee_masuk"      : fee,
        "stop_loss"      : sl,
        "take_profit"    : tp,
        "leverage"       : leverage,
        "waktu_beli"     : _waktu(),
        "trailing_aktif" : False,
        "harga_tertinggi": harga,
        "harga_terendah" : harga,
        "detail"         : detail_str,
    }

    save_state()
    print(f"  📝 [PAPER] FUTURES {side} {symbol} | "
          f"Entry: ${harga:,.4f} | Margin: ${margin:.2f} | {leverage}x")
    return True

def paper_tutup_futures(symbol, harga_raw, alasan="PAPER_CLOSE"):
    """Simulasi tutup posisi futures, hitung P&L."""
    st = load_state()
    pos = st["posisi_futures"].get(symbol)
    if not pos or not pos.get("aktif"):
        return False

    harga    = harga_raw
    qty      = pos["qty"]
    entry    = pos["entry"]
    leverage = pos["leverage"]
    margin   = pos["margin"]
    side     = pos["side"]

    if side == "LONG":
        pnl_usd = (harga - entry) * qty
    else:
        pnl_usd = (entry - harga) * qty

    fee    = harga * qty * PAPER_FEE_FUTURES
    pnl_usd -= fee
    pnl_pct = (pnl_usd / margin) * 100  # % dari margin

    # Kembalikan margin + P&L
    st["saldo_usdt"] += margin + pnl_usd

    s = st["statistik"]
    s["total_trade"] += 1
    if pnl_usd >= 0:
        s["win"]          += 1
        s["total_profit"] += pnl_usd
    else:
        s["loss"]         += 1
        s["total_loss"]   += abs(pnl_usd)

    equity = st["saldo_usdt"]
    if equity > s["peak_equity"]:
        s["peak_equity"] = equity
    drawdown = (s["peak_equity"] - equity) / s["peak_equity"] * 100
    if drawdown > s["max_drawdown"]:
        s["max_drawdown"] = drawdown

    st["riwayat"].append({
        "tipe"      : "FUTURES",
        "symbol"    : symbol,
        "side"      : side,
        "entry"     : pos["entry"],
        "exit"      : harga,
        "qty"       : qty,
        "leverage"  : leverage,
        "pnl_usd"   : round(pnl_usd, 4),
        "pnl_pct"   : round(pnl_pct, 4),
        "waktu_beli": pos["waktu_beli"],
        "waktu_jual": _waktu(),
        "alasan"    : alasan,
    })

    st["posisi_futures"][symbol]["aktif"] = False
    save_state()

    emoji = "✅" if pnl_usd >= 0 else "❌"
    print(f"  📝 [PAPER] CLOSE {side} {symbol} | {emoji} P&L: "
          f"${pnl_usd:+.2f} ({pnl_pct:+.2f}% margin) | "
          f"Saldo: ${st['saldo_usdt']:,.2f}")
    return pnl_usd

# ══════════════════════════════════════════════
# 3. CEK SL/TP PAPER SECARA REAL-TIME
# ══════════════════════════════════════════════

def cek_paper_sl_tp(client, kirim_telegram):
    """
    Cek semua posisi paper apakah sudah kena SL atau TP.
    Dipanggil setiap siklus bot berjalan.
    """
    st = load_state()
    waktu = _waktu()

    # ── CEK SPOT ──
    for symbol, pos in list(st["posisi_spot"].items()):
        if not pos.get("aktif"):
            continue
        try:
            harga = float(client.get_symbol_ticker(symbol=symbol)["price"])
        except Exception:
            continue

        profit_pct = ((harga - pos["harga_beli"]) / pos["harga_beli"]) * 100

        # Update trailing
        if harga > pos.get("harga_tertinggi", pos["harga_beli"]):
            st["posisi_spot"][symbol]["harga_tertinggi"] = harga
            save_state()

        # Cek TP
        if harga >= pos["take_profit"]:
            pnl = paper_jual_spot(symbol, harga, "PAPER_TP")
            kirim_telegram(
                f"🎯 <b>[PAPER] TAKE PROFIT - {symbol}</b>\n"
                f"💰 Entry : ${pos['harga_beli']:,.4f}\n"
                f"💰 Exit  : ${harga:,.4f}\n"
                f"📈 P&L   : <b>+${pnl:.2f} ({profit_pct:.2f}%)</b> ✅\n"
                f"💼 Saldo : ${load_state()['saldo_usdt']:,.2f}\n"
                f"🕐 {waktu}"
            )

        # Cek SL
        elif harga <= pos["stop_loss"]:
            pnl = paper_jual_spot(symbol, harga, "PAPER_SL")
            kirim_telegram(
                f"🛑 <b>[PAPER] STOP LOSS - {symbol}</b>\n"
                f"💰 Entry : ${pos['harga_beli']:,.4f}\n"
                f"💰 Exit  : ${harga:,.4f}\n"
                f"📉 P&L   : <b>${pnl:.2f} ({profit_pct:.2f}%)</b> ❌\n"
                f"💼 Saldo : ${load_state()['saldo_usdt']:,.2f}\n"
                f"🕐 {waktu}"
            )

    # ── CEK FUTURES ──
    for symbol, pos in list(st["posisi_futures"].items()):
        if not pos.get("aktif"):
            continue
        try:
            harga = float(client.get_symbol_ticker(symbol=symbol)["price"])
        except Exception:
            continue

        side = pos["side"]
        entry = pos["entry"]
        if side == "LONG":
            pnl_pct = ((harga - entry) / entry) * 100 * pos["leverage"]
        else:
            pnl_pct = ((entry - harga) / entry) * 100 * pos["leverage"]

        # Cek TP & SL
        kena_tp = (side == "LONG" and harga >= pos["take_profit"]) or \
                  (side == "SHORT" and harga <= pos["take_profit"])
        kena_sl = (side == "LONG" and harga <= pos["stop_loss"]) or \
                  (side == "SHORT" and harga >= pos["stop_loss"])

        if kena_tp:
            pnl = paper_tutup_futures(symbol, harga, "PAPER_TP")
            kirim_telegram(
                f"🎯 <b>[PAPER] FUTURES TP - {symbol}</b>\n"
                f"📊 Side  : {side} {pos['leverage']}x\n"
                f"💰 Entry : ${entry:,.4f}\n"
                f"💰 Exit  : ${harga:,.4f}\n"
                f"📈 P&L   : <b>+${pnl:.2f} ({pnl_pct:.1f}%)</b> ✅\n"
                f"💼 Saldo : ${load_state()['saldo_usdt']:,.2f}\n"
                f"🕐 {waktu}"
            )
        elif kena_sl:
            pnl = paper_tutup_futures(symbol, harga, "PAPER_SL")
            kirim_telegram(
                f"🛑 <b>[PAPER] FUTURES SL - {symbol}</b>\n"
                f"📊 Side  : {side} {pos['leverage']}x\n"
                f"💰 Entry : ${entry:,.4f}\n"
                f"💰 Exit  : ${harga:,.4f}\n"
                f"📉 P&L   : <b>${pnl:.2f} ({pnl_pct:.1f}%)</b> ❌\n"
                f"💼 Saldo : ${load_state()['saldo_usdt']:,.2f}\n"
                f"🕐 {waktu}"
            )

# ══════════════════════════════════════════════
# 4. LAPORAN PERFORMA
# ══════════════════════════════════════════════

def _nilai_posisi_terbuka(st, harga_cache):
    """Hitung estimasi nilai posisi yang masih terbuka."""
    total = 0.0
    for sym, pos in st["posisi_spot"].items():
        if pos.get("aktif"):
            # Pakai harga beli sebagai estimasi jika tidak ada harga real
            harga = harga_cache.get(sym, pos["harga_beli"])
            total += harga * pos["qty"]
    for sym, pos in st["posisi_futures"].items():
        if pos.get("aktif"):
            total += pos.get("margin", 0)
    return total

def get_laporan_paper(client=None):
    """
    Generate laporan performa paper trading lengkap.
    Return string siap kirim ke Telegram.
    """
    st = load_state()
    s  = st["statistik"]

    # Hitung equity total (saldo + nilai posisi terbuka)
    equity = st["saldo_usdt"]
    if client:
        for sym, pos in st["posisi_spot"].items():
            if pos.get("aktif"):
                try:
                    h = float(client.get_symbol_ticker(symbol=sym)["price"])
                    equity += h * pos["qty"]
                except Exception:
                    equity += pos["harga_beli"] * pos["qty"]
        for sym, pos in st["posisi_futures"].items():
            if pos.get("aktif"):
                equity += pos.get("margin", 0)

    total_trade = s["total_trade"]
    win_rate    = (s["win"] / total_trade * 100) if total_trade > 0 else 0
    profit_net  = s["total_profit"] - s["total_loss"]
    roi         = ((equity - st["modal_awal"]) / st["modal_awal"]) * 100

    # Rata-rata profit/loss per trade
    avg_win  = s["total_profit"] / s["win"]  if s["win"]  > 0 else 0
    avg_loss = s["total_loss"]   / s["loss"] if s["loss"] > 0 else 0

    # Profit factor
    pf = s["total_profit"] / s["total_loss"] if s["total_loss"] > 0 else float("inf")

    # Posisi terbuka
    n_spot    = sum(1 for p in st["posisi_spot"].values()    if p.get("aktif"))
    n_futures = sum(1 for p in st["posisi_futures"].values() if p.get("aktif"))

    roi_emoji  = "📈" if roi >= 0 else "📉"
    pf_emoji   = "✅" if pf >= 1.5 else ("⚠️" if pf >= 1.0 else "❌")

    laporan = (
        f"📊 <b>LAPORAN PAPER TRADING</b>\n"
        f"{'═'*30}\n\n"
        f"💼 <b>Modal Awal  :</b> ${st['modal_awal']:,.2f}\n"
        f"💰 <b>Equity Now  :</b> ${equity:,.2f}\n"
        f"{roi_emoji} <b>ROI         :</b> <b>{roi:+.2f}%</b>\n"
        f"💵 <b>Net P&L     :</b> ${profit_net:+.2f}\n\n"
        f"📈 <b>STATISTIK TRADE</b>\n"
        f"{'─'*28}\n"
        f"📊 Total Trade  : {total_trade}\n"
        f"✅ Win          : {s['win']} ({win_rate:.1f}%)\n"
        f"❌ Loss         : {s['loss']}\n"
        f"{pf_emoji} Profit Factor: {pf:.2f}\n"
        f"📈 Avg Win      : +${avg_win:.2f}\n"
        f"📉 Avg Loss     : -${avg_loss:.2f}\n"
        f"🔻 Max Drawdown : {s['max_drawdown']:.2f}%\n\n"
        f"📌 <b>POSISI TERBUKA</b>\n"
        f"{'─'*28}\n"
        f"💰 Spot    : {n_spot} posisi\n"
        f"⚡ Futures : {n_futures} posisi\n"
        f"💵 Saldo   : ${st['saldo_usdt']:,.2f}\n\n"
        f"🕐 {_waktu()}"
    )
    return laporan, equity, roi, win_rate

def print_status_paper(client=None):
    """Print status paper trading ke terminal."""
    st = load_state()
    laporan, equity, roi, win_rate = get_laporan_paper(client)

    print("\n  📝 ═══ PAPER TRADING STATUS ═══")
    print(f"  💰 Saldo    : ${st['saldo_usdt']:,.2f}")
    print(f"  📊 Equity   : ${equity:,.2f}")
    print(f"  📈 ROI      : {roi:+.2f}%")
    print(f"  🏆 Win Rate : {win_rate:.1f}%")

    spot_aktif = [(s,p) for s,p in st["posisi_spot"].items() if p.get("aktif")]
    if spot_aktif:
        print(f"\n  💰 Spot ({len(spot_aktif)} posisi):")
        for sym, pos in spot_aktif:
            if client:
                try:
                    h = float(client.get_symbol_ticker(symbol=sym)["price"])
                    pl = ((h - pos["harga_beli"]) / pos["harga_beli"]) * 100
                    print(f"    {sym}: ${pos['harga_beli']:,.4f}→${h:,.4f} "
                          f"P/L:{pl:+.2f}%")
                except Exception:
                    pass

    fut_aktif = [(s,p) for s,p in st["posisi_futures"].items() if p.get("aktif")]
    if fut_aktif:
        print(f"\n  ⚡ Futures ({len(fut_aktif)} posisi):")
        for sym, pos in fut_aktif:
            print(f"    {pos['side']} {sym}: entry=${pos['entry']:,.4f} "
                  f"{pos['leverage']}x")

# ══════════════════════════════════════════════
# 5. HANDLER PERINTAH TELEGRAM
# ══════════════════════════════════════════════

def handle_paper_command(pesan, kirim_telegram, client=None):
    """
    Proses perintah paper trading dari Telegram.
    Panggil ini di telegram_bot.py handler.

    Perintah yang didukung:
    /paper_status   → laporan lengkap
    /paper_reset    → reset simulasi dari awal
    /paper_riwayat  → 10 trade terakhir
    /live_on        → switch ke live trading
    /live_off       → kembali ke paper mode
    """
    cmd = pesan.strip().lower()

    if cmd == "/paper_status":
        laporan, equity, roi, wr = get_laporan_paper(client)
        kirim_telegram(laporan)

    elif cmd == "/paper_reset":
        global _state
        _state = _state_default()
        save_state()
        kirim_telegram(
            "🔄 <b>Paper trading direset!</b>\n"
            f"💰 Modal baru: ${PAPER_MODAL_AWAL:,.2f} USDT\n"
            f"🕐 {_waktu()}"
        )

    elif cmd == "/paper_riwayat":
        st = load_state()
        riwayat = st["riwayat"][-10:]
        if not riwayat:
            kirim_telegram("📋 Belum ada trade paper.")
            return
        teks = "📋 <b>10 Trade Terakhir (Paper)</b>\n\n"
        for r in reversed(riwayat):
            e = "✅" if r["pnl_usd"] >= 0 else "❌"
            teks += (f"{e} {r['symbol']} {r.get('side','?')} | "
                     f"${r['pnl_usd']:+.2f} ({r['pnl_pct']:+.2f}%)\n"
                     f"   {r['waktu_jual']} | {r['alasan']}\n")
        kirim_telegram(teks)

    elif cmd == "/live_on":
        switch_ke_live()
        kirim_telegram(
            "🔴 <b>SWITCHED TO LIVE TRADING!</b>\n\n"
            "⚠️ Bot sekarang menggunakan UANG ASLI\n"
            "Ketik /live_off untuk kembali ke paper mode\n"
            f"🕐 {_waktu()}"
        )

    elif cmd == "/live_off":
        switch_ke_paper()
        kirim_telegram(
            "📝 <b>Kembali ke Paper Trading Mode</b>\n"
            "Bot tidak akan eksekusi order nyata\n"
            f"🕐 {_waktu()}"
        )

    return True