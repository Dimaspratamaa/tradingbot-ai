# ============================================
# FUNDING RATE ARBITRAGE v1.0
# Strategi market-neutral: profit dari funding rate
#
# Cara kerja:
#   Saat funding rate NEGATIF (short bayar long):
#     → Buka LONG futures + HEDGING tidak diperlukan
#     → Pocket funding fee setiap 8 jam
#
#   Saat funding rate POSITIF SANGAT TINGGI (> 0.1%):
#     → Buka SHORT futures
#     → Pocket funding fee dari long traders
#
# Funding rate dibayar setiap: 00:00, 08:00, 16:00 UTC
# Jika rate -0.05%/8jam = -0.15%/hari = -4.5%/bulan
# Artinya: long traders MENERIMA 4.5%/bulan hanya dari hold!
#
# Risk: liquidasi jika harga bergerak terlalu jauh
# Mitigasi: leverage rendah (3x-5x) + SL ketat
# ============================================

import os
import json
import time
import pathlib
import requests

from datetime import datetime, timedelta
from collections import defaultdict

BASE_DIR       = pathlib.Path(__file__).parent
STATE_FILE     = BASE_DIR / "funding_state.json"
LOG_FILE       = BASE_DIR / "funding_trades.json"

# ── KONFIGURASI ───────────────────────────────
FUTURES_API    = "https://fapi.binance.com"
MIN_RATE_NEG   = -0.0005   # min -0.05% untuk buka long
MIN_RATE_POS   = 0.0010    # min +0.10% untuk buka short
MAX_POSISI     = 2          # max 2 posisi funding arb sekaligus
LEVERAGE       = 3          # leverage rendah = aman
TRADE_SIZE_USD = 50.0       # $50 per posisi
MIN_HOLD_JAM   = 7          # hold minimal 7 jam (dapat 1 funding)
MAX_HOLD_JAM   = 48         # max hold 2 hari

# Waktu funding: jam UTC (WIB = UTC+7)
FUNDING_HOURS_UTC = [0, 8, 16]


# ══════════════════════════════════════════════
# 1. AMBIL DATA FUNDING RATE
# ══════════════════════════════════════════════

def get_funding_rate(symbol, client=None):
    """
    Ambil funding rate terkini untuk satu simbol.
    Coba lewat Binance client dulu, fallback ke REST langsung.
    """
    # Via Binance client (lebih reliable di cloud)
    if client:
        try:
            data = client.futures_mark_price(symbol=symbol)
            return {
                "symbol"       : symbol,
                "funding_rate" : float(data["lastFundingRate"]),
                "mark_price"   : float(data["markPrice"]),
                "index_price"  : float(data["indexPrice"]),
                "next_funding" : int(data.get("nextFundingTime", 0)),
            }
        except Exception:
            pass

    # Fallback: REST langsung
    try:
        r = requests.get(
            f"{FUTURES_API}/fapi/v1/premiumIndex",
            params={"symbol": symbol},
            timeout=8
        )
        if r.status_code == 200:
            data = r.json()
            return {
                "symbol"       : symbol,
                "funding_rate" : float(data["lastFundingRate"]),
                "mark_price"   : float(data["markPrice"]),
                "index_price"  : float(data["indexPrice"]),
                "next_funding" : int(data.get("nextFundingTime", 0)),
            }
    except Exception as e:
        pass

    return None


def get_all_funding_rates(client=None, min_abs_rate=0.0001):
    """
    Ambil funding rate semua pasang USDT.
    Return list diurutkan dari rate paling ekstrem.
    """
    all_rates = []

    # Via client
    if client:
        try:
            data_list = client.futures_mark_price()
            for d in data_list:
                sym  = d.get("symbol", "")
                rate = float(d.get("lastFundingRate", 0))
                if not sym.endswith("USDT"):
                    continue
                if abs(rate) < min_abs_rate:
                    continue
                all_rates.append({
                    "symbol"      : sym,
                    "funding_rate": rate,
                    "rate_pct"    : round(rate * 100, 4),
                    "mark_price"  : float(d.get("markPrice", 0)),
                    "annual_pct"  : round(rate * 3 * 365 * 100, 2),
                })
            # Sort by absolute rate tertinggi
            all_rates.sort(key=lambda x: abs(x["funding_rate"]), reverse=True)
            return all_rates
        except Exception:
            pass

    # Fallback REST
    try:
        r = requests.get(
            f"{FUTURES_API}/fapi/v1/premiumIndex",
            timeout=10
        )
        if r.status_code == 200:
            for d in r.json():
                sym  = d.get("symbol", "")
                rate = float(d.get("lastFundingRate", 0))
                if not sym.endswith("USDT"):
                    continue
                if abs(rate) < min_abs_rate:
                    continue
                all_rates.append({
                    "symbol"      : sym,
                    "funding_rate": rate,
                    "rate_pct"    : round(rate * 100, 4),
                    "mark_price"  : float(d.get("markPrice", 0)),
                    "annual_pct"  : round(rate * 3 * 365 * 100, 2),
                })
            all_rates.sort(key=lambda x: abs(x["funding_rate"]), reverse=True)
    except Exception:
        pass

    return all_rates


def get_funding_history(symbol, client=None, limit=10):
    """Ambil histori funding rate 10 periode terakhir."""
    if client:
        try:
            hist = client.futures_funding_rate(symbol=symbol, limit=limit)
            return [
                {
                    "time": datetime.fromtimestamp(
                        int(h["fundingTime"])/1000
                    ).strftime("%Y-%m-%d %H:%M"),
                    "rate": round(float(h["fundingRate"]) * 100, 4),
                }
                for h in hist
            ]
        except Exception:
            pass
    return []


# ══════════════════════════════════════════════
# 2. ANALISIS & SINYAL
# ══════════════════════════════════════════════

def analisis_funding_opportunity(symbol, client=None):
    """
    Analisis lengkap peluang funding rate arbitrage.

    Return:
        signal  : "LONG" / "SHORT" / None
        rate    : funding rate saat ini
        detail  : penjelasan lengkap
    """
    data = get_funding_rate(symbol, client)
    if not data:
        return None, 0, "Gagal ambil data"

    rate        = data["funding_rate"]
    rate_pct    = rate * 100
    mark        = data["mark_price"]
    idx         = data["index_price"]
    basis       = (mark - idx) / idx * 100  # premium/discount futures

    # Hitung profit per hari jika hold
    profit_8h   = abs(rate_pct)
    profit_hari = profit_8h * 3
    profit_bulan= profit_hari * 30

    # Waktu funding berikutnya
    next_ts   = data.get("next_funding", 0)
    if next_ts > 0:
        next_dt    = datetime.fromtimestamp(next_ts / 1000)
        menit_lagi = max(0, int((next_dt - datetime.now()).total_seconds() / 60))
    else:
        menit_lagi = 0

    # Tentukan sinyal
    signal = None
    alasan = ""

    if rate <= MIN_RATE_NEG:
        # Funding negatif → long futures gratis (menerima pembayaran)
        signal = "LONG"
        alasan = (f"Funding {rate_pct:.4f}% — long menerima "
                  f"{profit_hari:.3f}%/hari = {profit_bulan:.1f}%/bulan")

    elif rate >= MIN_RATE_POS:
        # Funding positif sangat tinggi → short dapat pembayaran
        signal = "SHORT"
        alasan = (f"Funding {rate_pct:.4f}% — short menerima "
                  f"{profit_hari:.3f}%/hari = {profit_bulan:.1f}%/bulan")

    else:
        alasan = f"Funding {rate_pct:.4f}% — tidak cukup signifikan"

    return signal, rate, {
        "symbol"        : symbol,
        "funding_rate"  : rate,
        "rate_pct"      : round(rate_pct, 4),
        "mark_price"    : mark,
        "index_price"   : idx,
        "basis_pct"     : round(basis, 4),
        "profit_8h_pct" : round(profit_8h, 4),
        "profit_hari_pct": round(profit_hari, 4),
        "profit_bulan_pct": round(profit_bulan, 2),
        "menit_ke_funding": menit_lagi,
        "signal"        : signal,
        "alasan"        : alasan,
    }


def scan_semua_peluang(client=None, top_n=5):
    """
    Scan semua pasang dan temukan peluang terbaik.
    Return top N peluang diurutkan by profit potensial.
    """
    rates = get_all_funding_rates(client, min_abs_rate=0.0003)
    if not rates:
        return []

    peluang = []
    for r in rates[:20]:  # cek top 20 rate tertinggi
        sym    = r["symbol"]
        rate   = r["funding_rate"]
        signal = None

        if rate <= MIN_RATE_NEG:
            signal = "LONG"
        elif rate >= MIN_RATE_POS:
            signal = "SHORT"
        else:
            continue

        peluang.append({
            "symbol"      : sym,
            "signal"      : signal,
            "rate_pct"    : r["rate_pct"],
            "profit_hari" : round(abs(r["rate_pct"]) * 3, 3),
            "profit_bulan": r["annual_pct"] / 12,
            "mark_price"  : r["mark_price"],
        })

    return sorted(peluang, key=lambda x: abs(x["rate_pct"]), reverse=True)[:top_n]


# ══════════════════════════════════════════════
# 3. STATE MANAGEMENT
# ══════════════════════════════════════════════

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"posisi": [], "total_funding_received": 0.0}


def save_state(state):
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception as e:
        print(f"  ⚠️  [FUNDING] Save state error: {e}")


def get_posisi_aktif():
    state = load_state()
    return [p for p in state.get("posisi", []) if p.get("aktif")]


def catat_posisi(symbol, signal, rate, harga_beli, size_usd, leverage):
    """Catat posisi funding arbitrage baru."""
    state = load_state()
    posisi = state.setdefault("posisi", [])

    posisi.append({
        "symbol"      : symbol,
        "signal"      : signal,
        "funding_rate": rate,
        "harga_beli"  : harga_beli,
        "size_usd"    : size_usd,
        "leverage"    : leverage,
        "waktu_buka"  : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "aktif"       : True,
        "funding_collected": 0.0,
        "n_funding"   : 0,
    })

    save_state(state)
    print(f"  ✅ [FUNDING] Posisi dicatat: {symbol} {signal}")


def update_funding_collected(symbol, amount):
    """Update jumlah funding yang sudah diterima."""
    state = load_state()
    for p in state.get("posisi", []):
        if p["symbol"] == symbol and p.get("aktif"):
            p["funding_collected"] = round(
                p.get("funding_collected", 0) + amount, 6)
            p["n_funding"] = p.get("n_funding", 0) + 1
            break
    state["total_funding_received"] = round(
        state.get("total_funding_received", 0) + amount, 6)
    save_state(state)


def tutup_posisi(symbol):
    """Tandai posisi sebagai ditutup."""
    state = load_state()
    for p in state.get("posisi", []):
        if p["symbol"] == symbol and p.get("aktif"):
            p["aktif"]     = False
            p["waktu_tutup"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            break
    save_state(state)


# ══════════════════════════════════════════════
# 4. EKSEKUSI (PAPER & LIVE)
# ══════════════════════════════════════════════

def buka_posisi_funding(symbol, signal, detail,
                         client=None, paper_mode=True,
                         size_usd=TRADE_SIZE_USD,
                         leverage=LEVERAGE):
    """
    Buka posisi funding rate arbitrage.
    Signal: "LONG" → beli futures long saat funding negatif
    Signal: "SHORT" → jual futures short saat funding tinggi
    """
    rate     = detail.get("funding_rate", 0)
    mark     = detail.get("mark_price", 0)

    print(f"\n  📊 [FUNDING] Buka {signal} {symbol}")
    print(f"     Rate  : {rate*100:.4f}%/8jam")
    print(f"     Profit: {detail.get('profit_hari_pct',0):.3f}%/hari")
    print(f"     Harga : ${mark:,.4f}")
    print(f"     Size  : ${size_usd} (leverage {leverage}x)")

    if paper_mode:
        print("     [PAPER] Posisi disimulasikan")
        catat_posisi(symbol, signal, rate, mark, size_usd, leverage)
        return {"status": "PAPER", "symbol": symbol, "signal": signal}

    # LIVE: eksekusi real
    if not client:
        print("  ❌ [FUNDING] Client tidak tersedia")
        return None

    try:
        # Set leverage
        client.futures_change_leverage(
            symbol=symbol, leverage=leverage)

        # Tentukan side
        side = "BUY" if signal == "LONG" else "SELL"

        # Hitung qty
        qty_notional = size_usd * leverage
        qty = round(qty_notional / mark, 3)

        # Market order
        order = client.futures_create_order(
            symbol   = symbol,
            side     = side,
            type     = "MARKET",
            quantity = qty,
        )

        print(f"  ✅ [FUNDING] Order masuk! ID: {order.get('orderId')}")
        catat_posisi(symbol, signal, rate, mark, size_usd, leverage)
        return {"status": "OK", "order": order}

    except Exception as e:
        print(f"  ❌ [FUNDING] Order error: {e}")
        return None


def tutup_posisi_funding_live(symbol, signal, client=None,
                               paper_mode=True):
    """Tutup posisi funding rate arbitrage."""
    print(f"\n  📤 [FUNDING] Tutup posisi {symbol}")

    if paper_mode:
        tutup_posisi(symbol)
        print("     [PAPER] Posisi ditutup")
        return True

    if not client:
        return False

    try:
        # Tutup dengan reduce-only order
        side = "SELL" if signal == "LONG" else "BUY"
        # Ambil qty dari posisi
        pos_info = client.futures_position_information(symbol=symbol)
        qty = abs(float(pos_info[0].get("positionAmt", 0)))

        if qty > 0:
            client.futures_create_order(
                symbol      = symbol,
                side        = side,
                type        = "MARKET",
                quantity    = qty,
                reduceOnly  = True,
            )

        tutup_posisi(symbol)
        print(f"  ✅ [FUNDING] Posisi {symbol} ditutup")
        return True

    except Exception as e:
        print(f"  ❌ [FUNDING] Tutup error: {e}")
        return False


# ══════════════════════════════════════════════
# 5. MONITORING — Cek setiap jam
# ══════════════════════════════════════════════

def cek_posisi_aktif(client=None, paper_mode=True, kirim_telegram=None):
    """
    Cek semua posisi funding aktif:
    - Apakah sudah dapat funding?
    - Apakah perlu ditutup?
    Dipanggil setiap jam dari main loop.
    """
    posisi = get_posisi_aktif()
    if not posisi:
        return

    now = datetime.now()

    for pos in posisi:
        symbol    = pos["symbol"]
        signal    = pos["signal"]
        waktu_str = pos.get("waktu_buka", "")

        try:
            waktu_buka = datetime.strptime(waktu_str[:19], "%Y-%m-%d %H:%M:%S")
            jam_hold   = (now - waktu_buka).total_seconds() / 3600
        except Exception:
            jam_hold   = 0

        # Ambil data terbaru
        data = get_funding_rate(symbol, client)
        if not data:
            continue

        rate_skrng = data["funding_rate"]
        mark       = data["mark_price"]
        harga_beli = pos.get("harga_beli", mark)
        pnl_pct    = (mark - harga_beli) / harga_beli * 100
        if signal == "SHORT":
            pnl_pct = -pnl_pct

        print(f"  📊 [FUNDING] {symbol} {signal} "
              f"hold={jam_hold:.1f}H "
              f"PnL={pnl_pct:+.2f}% "
              f"rate={rate_skrng*100:.4f}%")

        # Cek apakah perlu tutup
        perlu_tutup = False
        alasan_tutup = ""

        # 1. Funding rate sudah berbalik
        if signal == "LONG" and rate_skrng > 0.0002:
            perlu_tutup  = True
            alasan_tutup = f"Funding rate berbalik positif ({rate_skrng*100:.4f}%)"

        elif signal == "SHORT" and rate_skrng < -0.0002:
            perlu_tutup  = True
            alasan_tutup = f"Funding rate berbalik negatif ({rate_skrng*100:.4f}%)"

        # 2. Max hold time
        elif jam_hold >= MAX_HOLD_JAM:
            perlu_tutup  = True
            alasan_tutup = f"Max hold {MAX_HOLD_JAM}H tercapai"

        # 3. Minimal 1 funding sudah diterima dan profit bagus
        elif jam_hold >= MIN_HOLD_JAM and pos.get("n_funding", 0) >= 1:
            if pnl_pct > 0.5:
                perlu_tutup  = True
                alasan_tutup = f"Profit {pnl_pct:.2f}% + funding collected"

        if perlu_tutup:
            funding_total = pos.get("funding_collected", 0)
            print(f"  🔔 [FUNDING] Tutup {symbol}: {alasan_tutup}")

            tutup_posisi_funding_live(symbol, signal, client, paper_mode)

            if kirim_telegram:
                em = "✅" if pnl_pct > 0 else "📉"
                kirim_telegram(
                    f"{em} <b>Funding Arb Ditutup — {symbol}</b>\n"
                    f"Signal   : {signal}\n"
                    f"Hold     : {jam_hold:.1f} jam\n"
                    f"PnL      : {pnl_pct:+.2f}%\n"
                    f"Funding  : +{funding_total:.4f}%\n"
                    f"Alasan   : {alasan_tutup}"
                )


# ══════════════════════════════════════════════
# 6. LAPORAN — Format Telegram
# ══════════════════════════════════════════════

def format_laporan(client=None, top_n=5):
    """
    Format laporan funding rate untuk Telegram /funding command.
    """
    state    = load_state()
    posisi   = get_posisi_aktif()
    total_fr = state.get("total_funding_received", 0)

    # Header
    teks = (
        f"💰 <b>Funding Rate Arbitrage</b>\n"
        f"{'─'*28}\n\n"
    )

    # Posisi aktif
    if posisi:
        teks += f"<b>📌 Posisi Aktif ({len(posisi)}):</b>\n"
        for p in posisi:
            sym  = p["symbol"]
            sig  = p["signal"]
            rate = p.get("funding_rate", 0) * 100
            fr   = p.get("funding_collected", 0)
            teks += (f"  • {sym} {sig} "
                     f"rate:{rate:.4f}% "
                     f"collected:{fr:.4f}%\n")
        teks += "\n"
    else:
        teks += "📌 Tidak ada posisi aktif\n\n"

    # Total funding diterima
    teks += f"💵 Total funding diterima: {total_fr:.4f}%\n\n"

    # Peluang terbaik saat ini
    peluang = scan_semua_peluang(client, top_n=top_n)
    if peluang:
        teks += f"<b>🎯 Top {len(peluang)} Peluang Sekarang:</b>\n"
        for p in peluang:
            em  = "🔴" if p["signal"] == "SHORT" else "🟢"
            teks += (
                f"  {em} <b>{p['symbol']}</b> "
                f"{p['signal']} "
                f"rate:{p['rate_pct']:+.4f}% "
                f"→ {p['profit_hari']:.3f}%/hari\n"
            )
    else:
        teks += "🎯 Tidak ada peluang signifikan saat ini\n"

    return teks


# ══════════════════════════════════════════════
# 7. MAIN SCAN — Dipanggil dari trading_bot
# ══════════════════════════════════════════════

_last_scan = 0
SCAN_INTERVAL_MENIT = 60  # scan setiap 1 jam


def jalankan_funding_scan(client=None, paper_mode=True,
                           kirim_telegram=None):
    """
    Fungsi utama yang dipanggil dari trading_bot.py.
    Scan peluang + cek posisi aktif.
    Dipanggil setiap 1 jam dari main loop.
    """
    global _last_scan
    now = time.time()

    # Throttle: jangan scan terlalu sering
    if now - _last_scan < SCAN_INTERVAL_MENIT * 60:
        return
    _last_scan = now

    print(f"\n  💰 [FUNDING] Scan dimulai...")

    # 1. Cek posisi aktif
    cek_posisi_aktif(client, paper_mode, kirim_telegram)

    # 2. Scan peluang baru
    posisi_aktif = get_posisi_aktif()
    if len(posisi_aktif) >= MAX_POSISI:
        print(f"  ℹ️  [FUNDING] Max posisi ({MAX_POSISI}) — skip scan baru")
        return

    peluang = scan_semua_peluang(client, top_n=3)

    if not peluang:
        print("  ℹ️  [FUNDING] Tidak ada peluang signifikan")
        return

    # Ambil peluang terbaik yang belum ada posisinya
    aktif_syms = {p["symbol"] for p in posisi_aktif}

    for p in peluang:
        if p["symbol"] in aktif_syms:
            continue

        sym    = p["symbol"]
        signal = p["signal"]
        detail = analisis_funding_opportunity(sym, client)[2]

        if not detail:
            continue

        print(f"\n  🎯 [FUNDING] Peluang: {sym} {signal} "
              f"rate:{p['rate_pct']:+.4f}% "
              f"profit:{p['profit_hari']:.3f}%/hari")

        # Buka posisi
        result = buka_posisi_funding(
            sym, signal, detail,
            client     = client,
            paper_mode = paper_mode,
            size_usd   = TRADE_SIZE_USD,
            leverage   = LEVERAGE,
        )

        if result and kirim_telegram:
            mode_em = "📝" if paper_mode else "💰"
            kirim_telegram(
                f"{mode_em} <b>Funding Arb Dibuka!</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"Symbol  : <b>{sym}</b>\n"
                f"Signal  : {signal}\n"
                f"Rate    : {p['rate_pct']:+.4f}%/8jam\n"
                f"Profit  : ~{p['profit_hari']:.3f}%/hari\n"
                f"        = ~{detail.get('profit_bulan_pct',0):.1f}%/bulan\n"
                f"Size    : ${TRADE_SIZE_USD} ({LEVERAGE}x leverage)\n"
                f"{'📝 PAPER MODE' if paper_mode else '✅ LIVE ORDER'}"
            )

        aktif_syms.add(sym)
        if len(aktif_syms) >= MAX_POSISI:
            break