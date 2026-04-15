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
            "🤖 <b>Daftar Command — Trading Bot AI</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "📊 <b>Info & Monitor:</b>\n"
            "  /start      → Info bot\n"
            "  /status     → Status bot & market\n"
            "  /posisi     → Detail posisi aktif\n"
            "  /saldo      → Cek saldo exchange\n"
            "  /laporan    → Laporan P/L hari ini\n"
            "  /riwayat    → 10 trade terakhir\n"
            "  /config     → Konfigurasi aktif\n"
            "  /koin       → Scan top koin\n"
            "  /heat       → Portfolio heat\n"
            "  /regime     → Market regime\n"
            "  /risk       → Risk manager report\n"
            "  /alpha      → Alpha engine report\n\n"
            "⚙️ <b>Kontrol Bot:</b>\n"
            "  /pause      → Stop entry baru\n"
            "  /resume     → Aktifkan entry\n"
            "  /scan       → Scan manual\n"
            "  /close X    → Close satu posisi\n"
            "  /closeall   → Close SEMUA posisi 🚨\n\n"
            "💹 <b>Trading Mode:</b>\n"
            "  /live_on    → Aktifkan live trading 🔴\n"
            "  /live_off   → Kembali ke paper mode\n"
            "  /paper_status → Status paper trading\n"
            "  /paper_reset  → Reset paper trading\n\n"
            "🎛️ <b>Pengaturan:</b>\n"
            "  /setsl X    → Set stop loss % (contoh: /setsl 2.5)\n"
            "  /settp X    → Set take profit % (contoh: /settp 5.0)\n"
            "  /mode X     → Ganti mode (scalping/swing/grid)\n"
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


    # ══════════════════════════════════════════
    # COMMAND BARU v2.0
    # ══════════════════════════════════════════

    # ── /start ──
    elif command == "/start":
        balas(
            "🤖 <b>Trading Bot AI — Quant Edition</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Bot trading otomatis dengan teknologi:\n"
            "  🧠 ML Ensemble (XGBoost+LSTM+RF)\n"
            "  📊 98 Quant Features\n"
            "  🔬 Alpha Engine (IC tracking)\n"
            "  📐 Portfolio Optimizer\n"
            "  🛡️ Risk Manager v2.0\n\n"
            "Ketik /help untuk daftar command lengkap.\n"
            "Ketik /status untuk lihat kondisi sekarang."
        )

    # ── /live_on ──
    elif command == "/live_on":
        try:
            from paper_trading import set_live_mode
            set_live_mode(True)
            balas(
                "🔴 <b>LIVE TRADING AKTIF!</b>\n\n"
                "⚠️ Bot sekarang menggunakan UANG NYATA.\n"
                "Pastikan saldo Binance sudah terisi.\n\n"
                "Ketik /live_off untuk kembali ke paper mode.\n"
                f"🕐 {datetime.now().strftime('%d/%m/%Y %H:%M')}"
            )
        except Exception as e:
            balas(f"⚠️ Gagal aktifkan live mode: {e}")

    # ── /live_off ──
    elif command == "/live_off":
        try:
            from paper_trading import set_live_mode
            set_live_mode(False)
            balas(
                "📝 <b>PAPER TRADING AKTIF</b>\n\n"
                "Bot kembali ke mode simulasi.\n"
                "Tidak ada uang nyata yang digunakan.\n"
                f"🕐 {datetime.now().strftime('%d/%m/%Y %H:%M')}"
            )
        except Exception as e:
            balas(f"⚠️ Gagal nonaktifkan live: {e}")

    # ── /paper_status ──
    elif command == "/paper_status":
        try:
            from paper_trading import get_paper_status
            st = get_paper_status()
            balas(
                f"📝 <b>Paper Trading Status</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💰 Modal awal : ${st.get('modal_awal',5000):,.2f}\n"
                f"💰 Saldo kini : ${st.get('saldo_usdt',0):,.2f}\n"
                f"📈 Total P/L  : {st.get('total_pl',0):+.2f}%\n"
                f"📊 Trades     : {st.get('total_trades',0)}\n"
                f"✅ Win rate   : {st.get('win_rate',0):.1f}%\n"
                f"📌 Posisi aktif: {st.get('n_posisi',0)}"
            )
        except Exception as e:
            balas(f"⚠️ Gagal ambil paper status: {e}")

    # ── /paper_reset ──
    elif command == "/paper_reset":
        try:
            from paper_trading import reset_paper
            reset_paper()
            balas(
                "🔄 <b>Paper Trading Direset!</b>\n\n"
                "Modal kembali ke $5,000 USDT.\n"
                "Semua posisi dan riwayat paper dihapus."
            )
        except Exception as e:
            balas(f"⚠️ Gagal reset paper: {e}")

    # ── /risk ──
    elif command == "/risk":
        posisi_spot    = ctx.get("posisi_spot", {})
        posisi_futures = ctx.get("posisi_futures", {})
        client         = ctx.get("client")
        try:
            from risk_manager import (
                hitung_position_heat, get_sizing_factor,
                deteksi_volatility_regime
            )
            saldo = 0
            try:
                akun  = client.get_account()
                saldo = next((float(a["free"]) for a in akun["balances"]
                              if a["asset"] == "USDT"), 0)
            except: pass

            heat  = hitung_position_heat(posisi_spot, posisi_futures, saldo)
            sf    = get_sizing_factor()
            emoji_heat = "🔥" if heat["terlalu_panas"] else ("⚠️" if heat["heat_pct"] > 10 else "✅")

            pesan = (
                f"🛡️ <b>Risk Manager Report</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{emoji_heat} Portfolio Heat : <b>{heat['heat_pct']:.1f}%</b> / 15%\n"
                f"💰 Total Exposure: ${heat['total_exposure']:.2f}\n"
                f"⚡ Risk in USD   : ${heat['total_heat_usd']:.2f}\n"
                f"📉 Sizing Factor : <b>{sf['factor']:.0%}</b>\n"
                f"🔴 Loss Berturut : {sf['konsekutif']} kali\n\n"
                f"📋 {heat['rekomendasi']}"
            )
            # Tambah detail posisi jika ada
            if heat["detail_posisi"]:
                pesan += "\n\n<b>Detail Posisi:</b>\n"
                for p in heat["detail_posisi"][:5]:
                    pesan += (f"  • {p['symbol']}: "
                              f"modal=${p['modal']:.0f} "
                              f"SL={p['sl_pct']:.1f}% "
                              f"heat=${p['heat']:.1f}\n")
            balas(pesan)
        except Exception as e:
            balas(f"⚠️ Gagal ambil risk data: {e}")

    # ── /alpha ──
    elif command == "/alpha":
        try:
            from alpha_engine import get_alpha_engine
            ae  = get_alpha_engine()
            ic_summary = ae.ic_tracker.get_ic_summary()
            aktif = [a for a in ic_summary if a["aktif"] and a["n"] >= 3]
            mati  = [a for a in ic_summary if not a["aktif"]]

            pesan = (
                f"🔬 <b>Alpha Engine Report</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📊 Total alpha  : {len(ic_summary)}\n"
                f"✅ Aktif        : {len(aktif)}\n"
                f"❌ Nonaktif     : {len(mati)}\n\n"
                f"🏆 <b>Top 5 Alpha (IC):</b>\n"
            )
            for a in aktif[:5]:
                bar = "█" * max(0, int(a["ic"] * 30))
                pesan += (f"  {a['alpha'][:18]:18} "
                          f"IC:{a['ic']:+.3f} {bar}\n")
            if mati:
                pesan += f"\n⚠️ Nonaktif: {', '.join(a['alpha'][:12] for a in mati[:3])}"
            balas(pesan)
        except Exception as e:
            balas(f"⚠️ Gagal ambil alpha data: {e}")

    # ── /koin ──
    elif command == "/koin":
        balas("🔍 Scanning top koin... tunggu ~30 detik")
        try:
            client = ctx.get("client")
            from trading_bot import get_top_koin_by_volume, hitung_skor_koin
            koin_list = get_top_koin_by_volume()[:10]
            pesan = "📊 <b>Top Koin Saat Ini</b>\n━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            for sym in koin_list[:6]:
                try:
                    h = hitung_skor_koin(sym, client)
                    skor = h.get("skor", 0)
                    harga = h.get("harga", 0)
                    em = "🔥" if skor >= 7 else ("📈" if skor >= 5 else "⚪")
                    pesan += f"{em} <b>{sym}</b> | ${harga:,.4f} | Skor: {skor}\n"
                except:
                    pesan += f"  • {sym}: error\n"
            balas(pesan)
        except Exception as e:
            balas(f"⚠️ Scan error: {e}")

    # ── /riwayat ──
    elif command == "/riwayat":
        try:
            import json, os
            riwayat_file = "riwayat_trade.json"
            if not os.path.exists(riwayat_file):
                balas("📭 Belum ada riwayat trade.")
                return
            with open(riwayat_file) as f:
                data = json.load(f)
            if not data:
                balas("📭 Riwayat kosong.")
                return

            n    = min(10, len(data))
            terbaru = data[-n:][::-1]  # urutkan terbaru duluan
            wins = sum(1 for t in data if t.get("profit_pct",0) > 0)
            wr   = wins/len(data)*100 if data else 0
            total_pl = sum(t.get("profit_pct",0) for t in data)

            pesan = (
                f"📋 <b>Riwayat {n} Trade Terakhir</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Total: {len(data)} | WR: {wr:.0f}% | P/L: {total_pl:+.1f}%\n\n"
            )
            for t in terbaru:
                pl    = t.get("profit_pct", 0)
                em    = "✅" if pl > 0 else "❌"
                tgl   = t.get("waktu_jual","")[:10]
                pesan += (
                    f"{em} <b>{t.get('symbol','?')}</b> "
                    f"{pl:+.2f}% | {t.get('alasan','?')[:12]} | {tgl}\n"
                )
            balas(pesan)
        except Exception as e:
            balas(f"⚠️ Gagal ambil riwayat: {e}")

    # ── /config ──
    elif command == "/config":
        try:
            from trading_bot import (
                MIN_SCORE_SPOT, MAX_POSISI_SPOT, TRADE_USDT_SPOT,
                MAX_MODAL_PER_TRADE, MIN_MODAL_PER_TRADE,
                MAX_SL_HARIAN, SL_COOLDOWN_JAM,
                TRAILING_AKTIVASI, TRAILING_JARAK, MAX_HOLD_JAM
            )
            paper = ctx.get("paper_mode", True)
            balas(
                f"⚙️ <b>Konfigurasi Bot Aktif</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"📌 Mode         : {'📝 PAPER' if paper else '🔴 LIVE'}\n\n"
                f"<b>Entry:</b>\n"
                f"  Min skor      : {MIN_SCORE_SPOT}\n"
                f"  Max posisi    : {MAX_POSISI_SPOT}\n"
                f"  Modal default : ${TRADE_USDT_SPOT:.0f}\n"
                f"  Max modal     : ${MAX_MODAL_PER_TRADE:.0f}\n"
                f"  Min modal     : ${MIN_MODAL_PER_TRADE:.0f}\n\n"
                f"<b>Exit:</b>\n"
                f"  Trailing aktif: +{TRAILING_AKTIVASI}%\n"
                f"  Trailing jarak: {TRAILING_JARAK}%\n"
                f"  Max hold      : {MAX_HOLD_JAM} jam\n\n"
                f"<b>Proteksi:</b>\n"
                f"  Max SL/hari   : {MAX_SL_HARIAN}x\n"
                f"  SL cooldown   : {SL_COOLDOWN_JAM} jam\n"
            )
        except Exception as e:
            balas(f"⚠️ Gagal ambil config: {e}")

    # ── /heat ──
    elif command == "/heat":
        posisi_spot    = ctx.get("posisi_spot", {})
        posisi_futures = ctx.get("posisi_futures", {})
        client         = ctx.get("client")
        try:
            from risk_manager import hitung_position_heat
            saldo = 0
            try:
                akun  = client.get_account()
                saldo = next((float(a["free"]) for a in akun["balances"]
                              if a["asset"] == "USDT"), 0)
            except: pass

            heat = hitung_position_heat(posisi_spot, posisi_futures, saldo)
            n_pos = len(heat["detail_posisi"])
            emoji = "🔥" if heat["terlalu_panas"] else ("⚠️" if heat["heat_pct"] > 10 else "❄️")
            balas(
                f"{emoji} <b>Portfolio Heat</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Heat saat ini : <b>{heat['heat_pct']:.1f}%</b>\n"
                f"Batas aman    : 15%\n"
                f"Exposure total: ${heat['total_exposure']:.2f}\n"
                f"Risk in $     : ${heat['total_heat_usd']:.2f}\n"
                f"Jumlah posisi : {n_pos}\n\n"
                f"📋 {heat['rekomendasi']}"
            )
        except Exception as e:
            balas(f"⚠️ Error: {e}")

    # ── /regime ──
    elif command == "/regime":
        client = ctx.get("client")
        try:
            import pandas as pd
            klines = client.get_klines(symbol="BTCUSDT",
                                        interval="1h", limit=100)
            df = pd.DataFrame(klines, columns=[
                "time","open","high","low","close","volume",
                "ct","qv","n","tb","tq","i"])
            for c in ["open","high","low","close","volume"]:
                df[c] = df[c].astype(float)

            from risk_manager import deteksi_volatility_regime
            from pattern_detector import deteksi_regime_hmm
            vol = deteksi_volatility_regime(df)
            hmm = deteksi_regime_hmm(df["close"], df["volume"])

            em_vol = {"CALM":"❄️","NORMAL":"✅","ELEVATED":"⚠️","STORM":"🔥"}.get(
                vol["regime"], "❓")
            em_hmm = {"BULL":"📈","BEAR":"📉","CHOP":"↔️","VOLATILE":"⚡"}.get(
                hmm["regime"], "❓")

            balas(
                f"🌡️ <b>Market Regime — BTC</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"{em_vol} Volatility : <b>{vol['regime']}</b>\n"
                f"   ATR      : {vol['atr_pct']:.2f}%\n"
                f"   Entry    : {'✅ Boleh' if vol['boleh_entry'] else '🚫 Diblokir'}\n\n"
                f"{em_hmm} HMM Regime : <b>{hmm['regime']}</b>\n"
                f"   Confidence: {hmm['confidence']:.0%}\n"
                f"   Vol ratio : {hmm.get('vol_ratio',1):.2f}x\n\n"
                f"💡 {vol['alasan']}"
            )
        except Exception as e:
            balas(f"⚠️ Error: {e}")

    # ── /closeall ──
    elif command == "/closeall":
        posisi_spot    = ctx.get("posisi_spot", {})
        posisi_futures = ctx.get("posisi_futures", {})
        client         = ctx.get("client")
        n_closed = 0

        balas("⚠️ <b>MENUTUP SEMUA POSISI...</b>")

        # Close semua spot
        for symbol, pos in list(posisi_spot.items()):
            if not pos.get("aktif"): continue
            try:
                client.order_market_sell(symbol=symbol, quantity=pos["qty"])
                posisi_spot[symbol]["aktif"] = False
                n_closed += 1
            except Exception as e:
                print(f"  Closeall spot {symbol}: {e}")

        # Close semua futures
        for symbol, pos in list(posisi_futures.items()):
            if not pos.get("aktif"): continue
            try:
                side = "SELL" if pos.get("side") == "LONG" else "BUY"
                client.futures_create_order(
                    symbol=symbol, side=side,
                    type="MARKET", quantity=pos["qty"], reduceOnly=True)
                posisi_futures[symbol]["aktif"] = False
                n_closed += 1
            except Exception as e:
                print(f"  Closeall futures {symbol}: {e}")

        balas(
            f"✅ <b>CLOSEALL Selesai</b>\n"
            f"Ditutup: {n_closed} posisi\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S')}"
        )

    # ── /setsl X ──
    elif command == "/setsl":
        if len(parts) < 2:
            balas("⚠️ Format: /setsl 2.5  (untuk set SL 2.5%)")
            return
        try:
            val = float(parts[1])
            if not 0.1 <= val <= 20:
                balas("⚠️ SL harus antara 0.1% - 20%")
                return
            ctx["custom_sl_pct"] = val
            balas(
                f"✅ Stop Loss diset ke <b>{val}%</b>\n"
                f"Berlaku untuk entry baru.\n"
                f"(Bot masih menggunakan ATR-based SL jika lebih baik)"
            )
        except:
            balas("⚠️ Format tidak valid. Contoh: /setsl 2.5")

    # ── /settp X ──
    elif command == "/settp":
        if len(parts) < 2:
            balas("⚠️ Format: /settp 5.0  (untuk set TP 5.0%)")
            return
        try:
            val = float(parts[1])
            if not 0.5 <= val <= 50:
                balas("⚠️ TP harus antara 0.5% - 50%")
                return
            ctx["custom_tp_pct"] = val
            balas(
                f"✅ Take Profit diset ke <b>{val}%</b>\n"
                f"Berlaku untuk entry baru."
            )
        except:
            balas("⚠️ Format tidak valid. Contoh: /settp 5.0")

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