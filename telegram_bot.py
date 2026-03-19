# ============================================
# TELEGRAM COMMAND HANDLER v1.0
# Kontrol bot trading via pesan Telegram
#
# Daftar Command:
#   /status   → Status posisi & kondisi market
#   /pause    → Hentikan entry baru sementara
#   /resume   → Aktifkan kembali entry
#   /laporan  → Kirim laporan portfolio sekarang
#   /posisi   → Detail semua posisi aktif
#   /scan     → Scan manual semua koin
#   /close X  → Close posisi symbol X
#   /saldo    → Cek saldo semua exchange
#   /help     → Daftar semua command
# ============================================

import requests
import time
import threading
import json
import os
from datetime import datetime

# ── STATE GLOBAL ─────────────────────────────
_bot_paused    = False   # True = stop entry baru
_last_update   = 0       # ID update Telegram terakhir
_polling_aktif = False

# ══════════════════════════════════════════════
# POLLING TELEGRAM UPDATES
# ══════════════════════════════════════════════

def mulai_polling(tg_token, tg_chat_id, handler_dict):
    """
    Mulai polling Telegram di background thread.
    handler_dict = referensi ke state bot (posisi, client, dll)
    """
    global _polling_aktif
    _polling_aktif = True
    t = threading.Thread(
        target=_polling_loop,
        args=(tg_token, tg_chat_id, handler_dict),
        daemon=True
    )
    t.start()
    print("  📱 Telegram Command Handler aktif!")
    return t

def hentikan_polling():
    global _polling_aktif
    _polling_aktif = False

def _polling_loop(tg_token, tg_chat_id, ctx):
    """Loop polling command dari Telegram"""
    global _last_update
    url = f"https://api.telegram.org/bot{tg_token}/getUpdates"

    while _polling_aktif:
        try:
            params = {
                "offset"  : _last_update + 1,
                "timeout" : 30,
                "limit"   : 10
            }
            resp = requests.get(url, params=params, timeout=35)
            data = resp.json()

            if not data.get("ok"):
                time.sleep(5)
                continue

            for update in data.get("result", []):
                _last_update = update["update_id"]
                msg = update.get("message", {})

                # Security: hanya terima dari chat ID yang diotorisasi
                chat_id = str(msg.get("chat", {}).get("id", ""))
                if chat_id != str(tg_chat_id):
                    continue

                teks = msg.get("text", "").strip()
                if teks.startswith("/"):
                    _proses_command(teks, tg_token, tg_chat_id, ctx)

        except Exception as e:
            print(f"  ⚠️  Polling error: {e}")
            time.sleep(10)

# ══════════════════════════════════════════════
# PROSES COMMAND
# ══════════════════════════════════════════════

def _proses_command(teks, tg_token, tg_chat_id, ctx):
    """Proses command dari Telegram dan kirim respons"""
    global _bot_paused

    parts   = teks.split()
    command = parts[0].lower().split("@")[0]  # Handle /cmd@botname

    def balas(pesan):
        _kirim(tg_token, tg_chat_id, pesan)

    print(f"  📱 Command: {command}")

    # ── /help ──
    if command == "/help":
        balas(
            "🤖 <b>Daftar Command Bot Trading</b>\n\n"
            "📊 <b>Info:</b>\n"
            "  /status   → Status bot & market\n"
            "  /posisi   → Detail posisi aktif\n"
            "  /saldo    → Cek saldo exchange\n"
            "  /laporan  → Laporan P/L hari ini\n\n"
            "⚙️ <b>Kontrol:</b>\n"
            "  /pause    → Stop entry baru\n"
            "  /resume   → Aktifkan entry\n"
            "  /scan     → Scan koin manual\n"
            "  /close X  → Close posisi (contoh: /close BTCUSDT)\n\n"
            "📈 <b>Strategi:</b>\n"
            "  /strategi → Status mode strategi aktif\n"
            "  /mode X   → Ganti mode (scalping/swing/grid)\n"
        )

    # ── /status ──
    elif command == "/status":
        posisi_spot    = ctx.get("posisi_spot", {})
        posisi_futures = ctx.get("posisi_futures", {})
        client         = ctx.get("client")

        n_spot    = sum(1 for p in posisi_spot.values() if p.get("aktif"))
        n_futures = sum(1 for p in posisi_futures.values() if p.get("aktif"))

        # BTC kondisi
        btc_info = "N/A"
        try:
            from risk_manager import get_btc_kondisi
            btc = get_btc_kondisi(client)
            btc_info = f"{btc['kondisi']} ({btc['btc_change_1h']:+.2f}%/1H)"
        except: pass

        # Session
        ses_info = "N/A"
        try:
            from risk_manager import cek_session_aktif
            ses = cek_session_aktif(client)
            ses_info = f"{ses['sesi']} ({ses['jam_wib']})"
        except: pass

        mode_str = "✅ AKTIF" if not _bot_paused else "⏸️ PAUSED"

        balas(
            f"📊 <b>Status Bot Trading</b>\n"
            f"{'─'*28}\n"
            f"🤖 Mode      : <b>{mode_str}</b>\n"
            f"💰 Spot      : {n_spot}/3 posisi\n"
            f"⚡ Futures   : {n_futures}/2 posisi\n"
            f"₿  BTC       : {btc_info}\n"
            f"🕐 Sesi      : {ses_info}\n"
            f"🕐 Waktu     : {datetime.now().strftime('%d/%m/%Y %H:%M WIB')}\n"
        )

    # ── /pause ──
    elif command == "/pause":
        _bot_paused = True
        balas(
            "⏸️ <b>Bot PAUSED</b>\n\n"
            "Entry baru dihentikan sementara.\n"
            "Posisi aktif tetap dimonitor (SL/TP tetap jalan).\n\n"
            "Ketik /resume untuk mengaktifkan kembali."
        )

    # ── /resume ──
    elif command == "/resume":
        _bot_paused = False
        balas(
            "▶️ <b>Bot RESUMED</b>\n\n"
            "Bot aktif kembali dan akan mencari entry baru.\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S WIB')}"
        )

    # ── /posisi ──
    elif command == "/posisi":
        posisi_spot    = ctx.get("posisi_spot", {})
        posisi_futures = ctx.get("posisi_futures", {})
        client         = ctx.get("client")

        aktif_spot = [(s, p) for s, p in posisi_spot.items()
                      if p.get("aktif")]
        aktif_fut  = [(s, p) for s, p in posisi_futures.items()
                      if p.get("aktif")]

        if not aktif_spot and not aktif_fut:
            balas("📭 Tidak ada posisi aktif saat ini.")
            return

        pesan = "📊 <b>Posisi Aktif</b>\n" + "─"*28 + "\n\n"

        # Spot positions
        if aktif_spot:
            pesan += "💰 <b>SPOT:</b>\n"
            for symbol, pos in aktif_spot:
                try:
                    harga  = float(client.get_symbol_ticker(
                        symbol=symbol)["price"])
                    pl_pct = ((harga - pos["harga_beli"]) /
                              pos["harga_beli"]) * 100
                    em     = "📈" if pl_pct >= 0 else "📉"
                    trail  = " 🔄" if pos.get("trailing_aktif") else ""
                    pesan += (
                        f"  {em} <b>{symbol}</b>{trail}\n"
                        f"     Entry: ${pos['harga_beli']:,.4f}\n"
                        f"     Skrg : ${harga:,.4f}\n"
                        f"     P/L  : <b>{pl_pct:+.2f}%</b>\n"
                        f"     SL   : ${pos['stop_loss']:,.4f}\n"
                        f"     TP   : ${pos['take_profit']:,.4f}\n\n"
                    )
                except:
                    pesan += f"  • {symbol}: error ambil harga\n"

        # Futures positions
        if aktif_fut:
            pesan += "⚡ <b>FUTURES:</b>\n"
            for symbol, pos in aktif_fut:
                try:
                    harga  = float(client.futures_symbol_ticker(
                        symbol=symbol)["price"])
                    side   = pos.get("side","?")
                    entry  = pos.get("entry", pos.get("harga_beli",0))
                    if side == "LONG":
                        pl_pct = ((harga - entry) / entry) * 100
                    else:
                        pl_pct = ((entry - harga) / entry) * 100
                    em = "📈" if pl_pct >= 0 else "📉"
                    pesan += (
                        f"  {em} <b>{symbol}</b> {side}\n"
                        f"     Entry: ${entry:,.4f}\n"
                        f"     Skrg : ${harga:,.4f}\n"
                        f"     P/L  : <b>{pl_pct:+.2f}%</b>"
                        f" ({pl_pct*pos.get('leverage',1):+.1f}% lev)\n\n"
                    )
                except:
                    pesan += f"  • {symbol}: error\n"

        balas(pesan)

    # ── /saldo ──
    elif command == "/saldo":
        client = ctx.get("client")
        try:
            akun  = client.get_account()
            saldo = {a["asset"]: float(a["free"])
                     for a in akun["balances"] if float(a["free"]) > 0}
            usdt  = saldo.get("USDT", 0)
            pesan = f"💰 <b>Saldo Exchange</b>\n{'─'*28}\n"
            pesan += f"  Binance USDT: <b>${usdt:,.2f}</b>\n"
            # Tambah exchange lain jika tersedia
            balas(pesan)
        except Exception as e:
            balas(f"⚠️ Gagal cek saldo: {e}")

    # ── /laporan ──
    elif command == "/laporan":
        try:
            from portfolio_tracker import kirim_laporan_manual
            posisi_spot    = ctx.get("posisi_spot", {})
            posisi_futures = ctx.get("posisi_futures", {})
            kirim_laporan_manual(
                posisi_spot, posisi_futures,
                lambda p: _kirim(tg_token, tg_chat_id, p)
            )
        except Exception as e:
            balas(f"⚠️ Gagal buat laporan: {e}")

    # ── /scan ──
    elif command == "/scan":
        balas("🔍 Memulai scan manual... Tunggu sebentar.")
        ctx["force_scan"] = True  # Flag untuk trigger scan di main loop

    # ── /close SYMBOL ──
    elif command == "/close":
        if len(parts) < 2:
            balas("⚠️ Format: /close BTCUSDT")
            return

        symbol         = parts[1].upper()
        posisi_spot    = ctx.get("posisi_spot", {})
        posisi_futures = ctx.get("posisi_futures", {})
        client         = ctx.get("client")

        closed = False

        # Coba close spot
        if symbol in posisi_spot and posisi_spot[symbol].get("aktif"):
            try:
                pos   = posisi_spot[symbol]
                harga = float(client.get_symbol_ticker(
                    symbol=symbol)["price"])
                client.order_market_sell(
                    symbol=symbol, quantity=pos["qty"])
                pl_pct = ((harga - pos["harga_beli"]) /
                          pos["harga_beli"]) * 100
                posisi_spot[symbol]["aktif"] = False
                balas(
                    f"✅ <b>SPOT {symbol} Closed!</b>\n"
                    f"💰 Entry: ${pos['harga_beli']:,.4f}\n"
                    f"💰 Exit : ${harga:,.4f}\n"
                    f"📊 P/L  : <b>{pl_pct:+.2f}%</b>\n"
                    f"📋 Alasan: MANUAL_CLOSE\n"
                    f"🕐 {datetime.now().strftime('%H:%M:%S')}"
                )
                closed = True
            except Exception as e:
                balas(f"⚠️ Gagal close spot {symbol}: {e}")

        # Coba close futures
        elif symbol in posisi_futures and posisi_futures[symbol].get("aktif"):
            try:
                pos    = posisi_futures[symbol]
                side   = pos.get("side", "LONG")
                harga  = float(client.futures_symbol_ticker(
                    symbol=symbol)["price"])
                close_side = "SELL" if side == "LONG" else "BUY"
                client.futures_cancel_all_open_orders(symbol=symbol)
                client.futures_create_order(
                    symbol=symbol, side=close_side,
                    type="MARKET", quantity=pos["qty"],
                    reduceOnly=True
                )
                posisi_futures[symbol]["aktif"] = False
                balas(
                    f"✅ <b>FUTURES {symbol} {side} Closed!</b>\n"
                    f"🕐 {datetime.now().strftime('%H:%M:%S')}"
                )
                closed = True
            except Exception as e:
                balas(f"⚠️ Gagal close futures {symbol}: {e}")

        if not closed:
            balas(f"⚠️ Tidak ada posisi aktif untuk {symbol}")

    # ── /strategi ──
    elif command == "/strategi":
        mode = ctx.get("mode_strategi", "SWING")
        balas(
            f"📈 <b>Mode Strategi Aktif</b>\n\n"
            f"Mode saat ini: <b>{mode}</b>\n\n"
            f"Mode tersedia:\n"
            f"  • SCALPING → Entry cepat 15m-1H\n"
            f"  • SWING    → Entry 4H-1D (default)\n"
            f"  • GRID     → Buy/sell di range harga\n\n"
            f"Ganti dengan: /mode scalping"
        )

    # ── /mode X ──
    elif command == "/mode":
        if len(parts) < 2:
            balas("⚠️ Format: /mode scalping | /mode swing | /mode grid")
            return
        mode_baru = parts[1].upper()
        if mode_baru in ["SCALPING", "SWING", "GRID"]:
            ctx["mode_strategi"] = mode_baru
            balas(
                f"✅ Mode strategi diubah ke <b>{mode_baru}</b>\n"
                f"Bot akan menggunakan parameter {mode_baru} "
                f"di siklus berikutnya."
            )
        else:
            balas("⚠️ Mode tidak valid. Pilih: scalping / swing / grid")

    else:
        balas(f"❓ Command tidak dikenali: {command}\nKetik /help untuk daftar command.")

# ── HELPER ────────────────────────────────────

def _kirim(tg_token, tg_chat_id, pesan):
    """Kirim pesan ke Telegram"""
    try:
        url  = f"https://api.telegram.org/bot{tg_token}/sendMessage"
        data = {
            "chat_id"   : tg_chat_id,
            "text"      : pesan,
            "parse_mode": "HTML"
        }
        requests.post(url, data=data, timeout=15)
    except Exception as e:
        print(f"  ⚠️  Kirim balasan error: {e}")

def is_paused():
    """Cek apakah bot sedang di-pause"""
    return _bot_paused