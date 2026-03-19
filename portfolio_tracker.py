# ============================================
# PORTFOLIO TRACKER v1.0
# Laporan harian profit/loss ke Telegram
# Kirim otomatis setiap hari jam 08:00 WIB
# ============================================

import json
import os
import time
from datetime import datetime, timedelta, timezone
from collections import defaultdict

LAPORAN_JAM_WIB = 8   # Kirim laporan jam 08:00 WIB (01:00 UTC)
_last_laporan   = {"tanggal": None}

# ══════════════════════════════════════════════
# BACA RIWAYAT TRADE
# ══════════════════════════════════════════════

def baca_riwayat(hari=1):
    """
    Baca riwayat trade dari riwayat_trade.json.
    hari=1 → trade hari ini
    hari=7 → trade 7 hari terakhir
    """
    if not os.path.exists("riwayat_trade.json"):
        return []

    try:
        with open("riwayat_trade.json", "r") as f:
            semua = json.load(f)

        # Filter berdasarkan waktu
        batas = datetime.now() - timedelta(days=hari)
        hasil = []

        for t in semua:
            try:
                waktu_jual = datetime.strptime(
                    t["waktu_jual"][:19], "%Y-%m-%d %H:%M:%S"
                )
                if waktu_jual >= batas:
                    hasil.append(t)
            except:
                pass

        return hasil

    except Exception as e:
        print(f"  ⚠️  Baca riwayat error: {e}")
        return []

# ══════════════════════════════════════════════
# HITUNG STATISTIK
# ══════════════════════════════════════════════

def hitung_statistik(trades, modal_per_trade=100.0):
    """
    Hitung statistik dari daftar trade.
    """
    if not trades:
        return None

    total       = len(trades)
    menang      = [t for t in trades if t["profit_pct"] > 0]
    kalah       = [t for t in trades if t["profit_pct"] <= 0]
    win_rate    = (len(menang) / total * 100) if total > 0 else 0

    profit_total_pct = sum(t["profit_pct"] for t in trades)
    profit_total_usd = sum(
        modal_per_trade * (t["profit_pct"] / 100) for t in trades
    )

    avg_profit  = (sum(t["profit_pct"] for t in menang) /
                   len(menang)) if menang else 0
    avg_loss    = (sum(t["profit_pct"] for t in kalah) /
                   len(kalah)) if kalah else 0

    # Profit factor
    gross_profit = sum(t["profit_pct"] for t in menang)
    gross_loss   = abs(sum(t["profit_pct"] for t in kalah))
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else float('inf')

    # Best & worst trade
    best  = max(trades, key=lambda x: x["profit_pct"])
    worst = min(trades, key=lambda x: x["profit_pct"])

    # Per koin
    per_koin = defaultdict(lambda: {"n": 0, "profit": 0})
    for t in trades:
        sym = t["symbol"]
        per_koin[sym]["n"]      += 1
        per_koin[sym]["profit"] += t["profit_pct"]

    # Sort koin by profit
    koin_sorted = sorted(
        per_koin.items(),
        key=lambda x: x[1]["profit"],
        reverse=True
    )

    # Per alasan exit
    per_alasan = defaultdict(int)
    for t in trades:
        per_alasan[t.get("alasan", "UNKNOWN")] += 1

    return {
        "total"         : total,
        "menang"        : len(menang),
        "kalah"         : len(kalah),
        "win_rate"      : round(win_rate, 1),
        "profit_total_pct": round(profit_total_pct, 2),
        "profit_total_usd": round(profit_total_usd, 2),
        "avg_profit"    : round(avg_profit, 2),
        "avg_loss"      : round(avg_loss, 2),
        "profit_factor" : round(profit_factor, 2),
        "best"          : best,
        "worst"         : worst,
        "per_koin"      : koin_sorted[:5],
        "per_alasan"    : dict(per_alasan)
    }

# ══════════════════════════════════════════════
# BUAT LAPORAN HARIAN
# ══════════════════════════════════════════════

def buat_laporan_harian(posisi_spot, posisi_futures,
                        modal_per_trade=100.0):
    """
    Buat teks laporan harian yang dikirim ke Telegram.
    """
    tanggal = datetime.now().strftime("%d %B %Y")
    waktu   = datetime.now().strftime("%H:%M WIB")

    # Trade hari ini
    trades_hari  = baca_riwayat(hari=1)
    stats_hari   = hitung_statistik(trades_hari, modal_per_trade)

    # Trade 7 hari
    trades_minggu = baca_riwayat(hari=7)
    stats_minggu  = hitung_statistik(trades_minggu, modal_per_trade)

    # Posisi aktif saat ini
    n_spot    = sum(1 for p in posisi_spot.values() if p.get("aktif"))
    n_futures = sum(1 for p in posisi_futures.values() if p.get("aktif"))

    # ── Header ──
    pesan = (
        f"📊 <b>LAPORAN HARIAN - {tanggal}</b>\n"
        f"🕐 {waktu}\n"
        f"{'─'*30}\n\n"
    )

    # ── Posisi aktif ──
    pesan += f"📌 <b>Posisi Aktif:</b>\n"
    pesan += f"   💰 Spot   : {n_spot} posisi\n"
    pesan += f"   ⚡ Futures: {n_futures} posisi\n\n"

    # ── Statistik hari ini ──
    if stats_hari:
        emoji_profit = "📈" if stats_hari["profit_total_usd"] >= 0 else "📉"
        pesan += f"📅 <b>Hari Ini ({stats_hari['total']} trade):</b>\n"
        pesan += (f"   {emoji_profit} P/L    : "
                  f"<b>{stats_hari['profit_total_usd']:+.2f} USD</b> "
                  f"({stats_hari['profit_total_pct']:+.2f}%)\n")
        pesan += f"   🎯 Win Rate: <b>{stats_hari['win_rate']}%</b> "
        pesan += f"({stats_hari['menang']}W/{stats_hari['kalah']}L)\n"
        pesan += f"   ✅ Avg Win : +{stats_hari['avg_profit']:.2f}%\n"
        pesan += f"   ❌ Avg Loss: {stats_hari['avg_loss']:.2f}%\n"

        if stats_hari["best"]:
            pesan += (f"   🏆 Best   : {stats_hari['best']['symbol']} "
                      f"+{stats_hari['best']['profit_pct']:.2f}%\n")
        if stats_hari["worst"]:
            pesan += (f"   💸 Worst  : {stats_hari['worst']['symbol']} "
                      f"{stats_hari['worst']['profit_pct']:.2f}%\n")
        pesan += "\n"
    else:
        pesan += "📅 <b>Hari Ini:</b> Belum ada trade\n\n"

    # ── Statistik 7 hari ──
    if stats_minggu:
        emoji_w = "📈" if stats_minggu["profit_total_usd"] >= 0 else "📉"
        pesan += f"📆 <b>7 Hari Terakhir ({stats_minggu['total']} trade):</b>\n"
        pesan += (f"   {emoji_w} P/L Total: "
                  f"<b>{stats_minggu['profit_total_usd']:+.2f} USD</b>\n")
        pesan += f"   🎯 Win Rate  : <b>{stats_minggu['win_rate']}%</b>\n"
        pesan += f"   📊 P. Factor : {stats_minggu['profit_factor']:.2f}\n"

        # Top koin
        if stats_minggu["per_koin"]:
            pesan += "   🏅 Top Koin  :\n"
            for sym, data in stats_minggu["per_koin"][:3]:
                em = "✅" if data["profit"] > 0 else "❌"
                pesan += (f"      {em} {sym}: "
                          f"{data['profit']:+.2f}% ({data['n']}x)\n")

        # Exit reasons
        if stats_minggu["per_alasan"]:
            pesan += "   🚪 Exit      :\n"
            for alasan, n in stats_minggu["per_alasan"].items():
                pesan += f"      • {alasan}: {n}x\n"
        pesan += "\n"
    else:
        pesan += "📆 <b>7 Hari:</b> Belum ada data\n\n"

    pesan += "─" * 30 + "\n"
    pesan += "🤖 <i>Bot terus berjalan 24/7</i>"

    return pesan

# ══════════════════════════════════════════════
# CEK JADWAL LAPORAN
# ══════════════════════════════════════════════

def cek_jadwal_laporan(posisi_spot, posisi_futures,
                       kirim_telegram, modal=100.0):
    """
    Cek apakah sudah waktunya kirim laporan harian.
    Dipanggil di setiap siklus bot.
    """
    global _last_laporan

    sekarang     = datetime.now()
    tanggal_hari = sekarang.strftime("%Y-%m-%d")
    jam_wib      = (sekarang.hour + 7) % 24  # Convert ke WIB

    # Kirim jika: jam sudah 08:00 WIB DAN belum kirim hari ini
    if (jam_wib == LAPORAN_JAM_WIB and
            _last_laporan["tanggal"] != tanggal_hari):

        print(f"\n📊 Mengirim laporan harian...")
        laporan = buat_laporan_harian(
            posisi_spot, posisi_futures, modal
        )
        sukses = kirim_telegram(laporan)
        if sukses:
            _last_laporan["tanggal"] = tanggal_hari
            print(f"  ✅ Laporan harian terkirim!")
        return True

    return False

def kirim_laporan_manual(posisi_spot, posisi_futures,
                         kirim_telegram, modal=100.0):
    """Kirim laporan sekarang (manual)"""
    laporan = buat_laporan_harian(posisi_spot, posisi_futures, modal)
    return kirim_telegram(laporan)