# ============================================
# PORTFOLIO TRACKER v2.0
# Laporan harian profit/loss ke Telegram
# Kirim otomatis setiap hari jam 08:00 WIB
#
# Metrik lengkap:
#   Win Rate, Profit Factor, Max Drawdown,
#   Sharpe Ratio, Expectancy, Calmar Ratio,
#   Recovery Factor, Consecutive Win/Loss,
#   Best/Worst Trade, Monthly Breakdown
# ============================================

import json
import os
import time
import numpy as np
from datetime import datetime, timedelta
from collections import defaultdict

LAPORAN_JAM_WIB = 8
_last_laporan   = {"tanggal": None}

# ══════════════════════════════════════════════
# BACA RIWAYAT TRADE
# ══════════════════════════════════════════════

def baca_riwayat(hari=1):
    if not os.path.exists("riwayat_trade.json"):
        return []
    try:
        with open("riwayat_trade.json") as f:
            semua = json.load(f)
        batas  = datetime.now() - timedelta(days=hari)
        return [
            t for t in semua
            if _parse_dt(t.get("waktu_jual","")) >= batas
        ]
    except Exception as e:
        print(f"  ⚠️  Baca riwayat error: {e}")
        return []

def baca_semua_riwayat():
    if not os.path.exists("riwayat_trade.json"):
        return []
    try:
        with open("riwayat_trade.json") as f:
            return json.load(f)
    except Exception:
        return []

def _parse_dt(s):
    try:
        return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.min

# ══════════════════════════════════════════════
# HITUNG STATISTIK LENGKAP
# ══════════════════════════════════════════════

def hitung_statistik(trades, modal_per_trade=100.0):
    """
    Hitung statistik profesional dari daftar trade.
    Metrik ala hedge fund: Sharpe, Calmar, Expectancy, dll.
    """
    if not trades:
        return None

    total  = len(trades)
    menang = [t for t in trades if t["profit_pct"] > 0]
    kalah  = [t for t in trades if t["profit_pct"] <= 0]
    profits= [t["profit_pct"] for t in trades]
    arr    = np.array(profits)

    win_rate     = len(menang) / total * 100
    avg_profit   = np.mean([t["profit_pct"] for t in menang]) if menang else 0
    avg_loss     = np.mean([t["profit_pct"] for t in kalah]) if kalah else 0
    total_pl_pct = sum(profits)
    total_pl_usd = sum(modal_per_trade * p/100 for p in profits)

    # Profit Factor
    gross_profit  = sum(t["profit_pct"] for t in menang)
    gross_loss    = abs(sum(t["profit_pct"] for t in kalah))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 99.0

    # Expectancy = (WR × avg_win) + ((1-WR) × avg_loss)
    wr_dec     = len(menang) / total
    expectancy = (wr_dec * avg_profit) + ((1 - wr_dec) * avg_loss)

    # Max Drawdown (equity curve)
    equity      = np.cumsum(arr)
    running_max = np.maximum.accumulate(equity)
    drawdowns   = equity - running_max
    max_drawdown= float(np.min(drawdowns)) if len(drawdowns) > 0 else 0

    # Sharpe Ratio (simplified, 0% risk-free)
    if np.std(arr) > 0:
        sharpe = float(np.mean(arr) / np.std(arr) * np.sqrt(252))
    else:
        sharpe = 0.0

    # Calmar Ratio = total return / |max drawdown|
    calmar = (total_pl_pct / abs(max_drawdown)) if max_drawdown < 0 else 99.0

    # Recovery Factor = total profit / |max drawdown|
    recovery = (total_pl_usd / abs(max_drawdown * modal_per_trade / 100)
                if max_drawdown < 0 else 99.0)

    # Consecutive wins/losses
    max_consec_win  = 0
    max_consec_loss = 0
    cur_win = cur_loss = 0
    for p in profits:
        if p > 0:
            cur_win  += 1
            cur_loss  = 0
            max_consec_win = max(max_consec_win, cur_win)
        else:
            cur_loss += 1
            cur_win   = 0
            max_consec_loss = max(max_consec_loss, cur_loss)

    # Best & worst trade
    best  = max(trades, key=lambda x: x["profit_pct"])
    worst = min(trades, key=lambda x: x["profit_pct"])

    # Per koin
    per_koin = defaultdict(lambda: {"n": 0, "profit": 0.0, "wins": 0})
    for t in trades:
        sym = t["symbol"]
        per_koin[sym]["n"]      += 1
        per_koin[sym]["profit"] += t["profit_pct"]
        if t["profit_pct"] > 0:
            per_koin[sym]["wins"] += 1
    koin_sorted = sorted(
        per_koin.items(),
        key=lambda x: x[1]["profit"], reverse=True
    )

    # Per alasan exit
    per_alasan = defaultdict(int)
    for t in trades:
        per_alasan[t.get("alasan", "UNKNOWN")] += 1

    # Monthly breakdown
    per_bulan = defaultdict(lambda: {"n": 0, "profit": 0.0})
    for t in trades:
        try:
            bln = _parse_dt(t["waktu_jual"]).strftime("%Y-%m")
            per_bulan[bln]["n"]      += 1
            per_bulan[bln]["profit"] += t["profit_pct"]
        except Exception:
            pass

    return {
        # Dasar
        "total"           : total,
        "menang"          : len(menang),
        "kalah"           : len(kalah),
        "win_rate"        : round(win_rate, 1),
        "profit_total_pct": round(total_pl_pct, 2),
        "profit_total_usd": round(total_pl_usd, 2),
        "avg_profit"      : round(avg_profit, 2),
        "avg_loss"        : round(avg_loss, 2),
        # Profesional
        "profit_factor"   : round(profit_factor, 2),
        "expectancy"      : round(expectancy, 3),
        "max_drawdown"    : round(max_drawdown, 2),
        "sharpe"          : round(sharpe, 3),
        "calmar"          : round(calmar, 3),
        "recovery_factor" : round(recovery, 2),
        "max_consec_win"  : max_consec_win,
        "max_consec_loss" : max_consec_loss,
        # Detail
        "best"            : best,
        "worst"           : worst,
        "per_koin"        : koin_sorted[:5],
        "per_alasan"      : dict(per_alasan),
        "per_bulan"       : dict(per_bulan),
    }

# ══════════════════════════════════════════════
# EVALUASI KESIAPAN LIVE TRADING
# ══════════════════════════════════════════════

def evaluasi_live_readiness(n_min=20):
    """
    Evaluasi apakah bot siap untuk live trading
    berdasarkan statistik paper trading.

    Return:
        skor       : 0-100
        siap       : bool
        detail     : dict penjelasan per metrik
    """
    semua  = baca_semua_riwayat()
    if len(semua) < n_min:
        return {
            "skor" : 0, "siap": False,
            "pesan": f"Belum cukup data ({len(semua)}/{n_min} trade)"
        }

    stats  = hitung_statistik(semua)
    skor   = 0
    detail = []

    # Win Rate > 50%
    if stats["win_rate"] >= 55:
        skor += 20
        detail.append(f"✅ Win rate {stats['win_rate']}% (≥55%)")
    elif stats["win_rate"] >= 50:
        skor += 10
        detail.append(f"⚠️ Win rate {stats['win_rate']}% (target 55%)")
    else:
        detail.append(f"❌ Win rate {stats['win_rate']}% (<50%)")

    # Profit Factor > 1.5
    pf = min(stats["profit_factor"], 99.0)
    if pf >= 1.8:
        skor += 20
        detail.append(f"✅ Profit factor {pf:.2f} (≥1.8)")
    elif pf >= 1.5:
        skor += 12
        detail.append(f"⚠️ Profit factor {pf:.2f} (target 1.8)")
    else:
        detail.append(f"❌ Profit factor {pf:.2f} (<1.5)")

    # Sharpe > 0.5
    if stats["sharpe"] >= 1.0:
        skor += 20
        detail.append(f"✅ Sharpe {stats['sharpe']:.3f} (≥1.0)")
    elif stats["sharpe"] >= 0.5:
        skor += 10
        detail.append(f"⚠️ Sharpe {stats['sharpe']:.3f} (target 1.0)")
    else:
        detail.append(f"❌ Sharpe {stats['sharpe']:.3f} (<0.5)")

    # Max Drawdown < 10%
    dd = abs(stats["max_drawdown"])
    if dd <= 5:
        skor += 20
        detail.append(f"✅ Max drawdown {dd:.1f}% (≤5%)")
    elif dd <= 10:
        skor += 10
        detail.append(f"⚠️ Max drawdown {dd:.1f}% (target ≤5%)")
    else:
        detail.append(f"❌ Max drawdown {dd:.1f}% (>10%)")

    # Expectancy > 0
    if stats["expectancy"] >= 0.3:
        skor += 20
        detail.append(f"✅ Expectancy {stats['expectancy']:.3f}% (≥0.3%)")
    elif stats["expectancy"] > 0:
        skor += 10
        detail.append(f"⚠️ Expectancy {stats['expectancy']:.3f}% (target ≥0.3%)")
    else:
        detail.append(f"❌ Expectancy {stats['expectancy']:.3f}% (≤0)")

    siap  = skor >= 70
    pesan = (
        "🟢 Bot SIAP untuk live trading!"
        if siap else
        "🔴 Bot belum siap — teruskan paper trading"
    )

    return {
        "skor"    : skor,
        "siap"    : siap,
        "pesan"   : pesan,
        "detail"  : detail,
        "n_trade" : len(semua),
        "stats"   : stats
    }

# ══════════════════════════════════════════════
# FORMAT LAPORAN TELEGRAM
# ══════════════════════════════════════════════

def buat_laporan_harian(posisi_spot, posisi_futures,
                        modal_per_trade=100.0):
    tanggal = datetime.now().strftime("%d %B %Y")
    waktu   = datetime.now().strftime("%H:%M WIB")

    trades_hari   = baca_riwayat(hari=1)
    trades_minggu = baca_riwayat(hari=7)
    trades_semua  = baca_semua_riwayat()
    stats_hari    = hitung_statistik(trades_hari, modal_per_trade)
    stats_minggu  = hitung_statistik(trades_minggu, modal_per_trade)
    stats_semua   = hitung_statistik(trades_semua, modal_per_trade)

    n_spot    = sum(1 for p in posisi_spot.values() if p.get("aktif"))
    n_futures = sum(1 for p in posisi_futures.values() if p.get("aktif"))

    pesan = (
        f"📊 <b>LAPORAN HARIAN — {tanggal}</b>\n"
        f"🕐 {waktu}\n"
        f"{'─'*30}\n\n"
        f"📌 <b>Posisi Aktif:</b> "
        f"Spot {n_spot}/3 | Futures {n_futures}/2\n\n"
    )

    # ── Hari ini ──
    if stats_hari:
        em = "📈" if stats_hari["profit_total_usd"] >= 0 else "📉"
        pesan += (
            f"📅 <b>Hari Ini ({stats_hari['total']} trade):</b>\n"
            f"  {em} P/L    : <b>{stats_hari['profit_total_usd']:+.2f} USD</b>"
            f" ({stats_hari['profit_total_pct']:+.2f}%)\n"
            f"  🎯 Win Rate: <b>{stats_hari['win_rate']}%</b>"
            f" ({stats_hari['menang']}W/{stats_hari['kalah']}L)\n"
            f"  ✅ Avg Win : +{stats_hari['avg_profit']:.2f}%\n"
            f"  ❌ Avg Loss: {stats_hari['avg_loss']:.2f}%\n"
        )
        if stats_hari["best"]:
            pesan += (f"  🏆 Best    : {stats_hari['best']['symbol']}"
                      f" +{stats_hari['best']['profit_pct']:.2f}%\n")
        pesan += "\n"
    else:
        pesan += "📅 <b>Hari Ini:</b> Belum ada trade\n\n"

    # ── 7 hari ──
    if stats_minggu:
        em = "📈" if stats_minggu["profit_total_usd"] >= 0 else "📉"
        pesan += (
            f"📆 <b>7 Hari ({stats_minggu['total']} trade):</b>\n"
            f"  {em} P/L     : <b>{stats_minggu['profit_total_usd']:+.2f} USD</b>\n"
            f"  🎯 Win Rate : {stats_minggu['win_rate']}%\n"
            f"  📊 P.Factor : {stats_minggu['profit_factor']:.2f}\n"
            f"  📉 Max DD   : {stats_minggu['max_drawdown']:.2f}%\n"
            f"  📈 Sharpe   : {stats_minggu['sharpe']:.3f}\n"
            f"  💡 Expectancy: {stats_minggu['expectancy']:.3f}%\n"
        )
        if stats_minggu["per_koin"]:
            pesan += "  🏅 Top koin:\n"
            for sym, data in stats_minggu["per_koin"][:3]:
                em2 = "✅" if data["profit"] > 0 else "❌"
                wr  = data["wins"] / data["n"] * 100
                pesan += (f"     {em2} {sym}: {data['profit']:+.2f}%"
                          f" ({data['n']}T {wr:.0f}%WR)\n")
        pesan += "\n"
    else:
        pesan += "📆 <b>7 Hari:</b> Belum ada data\n\n"

    # ── Semua waktu ──
    if stats_semua and len(trades_semua) >= 10:
        pesan += (
            f"🏦 <b>Total All-Time ({len(trades_semua)} trade):</b>\n"
            f"  📈 Total P/L    : {stats_semua['profit_total_usd']:+.2f} USD\n"
            f"  🎯 Win Rate     : {stats_semua['win_rate']}%\n"
            f"  📊 Profit Factor: {stats_semua['profit_factor']:.2f}\n"
            f"  📐 Sharpe Ratio : {stats_semua['sharpe']:.3f}\n"
            f"  📉 Max Drawdown : {stats_semua['max_drawdown']:.2f}%\n"
            f"  📏 Calmar Ratio : {stats_semua['calmar']:.2f}\n"
            f"  💰 Expectancy   : {stats_semua['expectancy']:.3f}%\n"
            f"  🔥 Max Win Str  : {stats_semua['max_consec_win']}x\n"
            f"  ❄️  Max Loss Str : {stats_semua['max_consec_loss']}x\n\n"
        )

    # ── Evaluasi kesiapan live ──
    if len(trades_semua) >= 20:
        eval_r = evaluasi_live_readiness()
        bar    = "█" * (eval_r["skor"] // 10) + "░" * (10 - eval_r["skor"] // 10)
        pesan += (
            f"🎯 <b>Kesiapan Live Trading:</b>\n"
            f"  Skor: <b>{eval_r['skor']}/100</b> [{bar}]\n"
            f"  {eval_r['pesan']}\n\n"
        )

    pesan += "─" * 30 + "\n🤖 <i>Bot berjalan 24/7</i>"
    return pesan

def buat_laporan_mingguan(posisi_spot, posisi_futures,
                           modal_per_trade=100.0):
    """Laporan lebih detail untuk akhir minggu."""
    trades_semua = baca_semua_riwayat()
    stats        = hitung_statistik(trades_semua, modal_per_trade)

    if not stats:
        return "📊 Belum ada data trade untuk laporan mingguan."

    pesan = (
        f"📊 <b>LAPORAN MINGGUAN</b>\n"
        f"{'═'*30}\n\n"
        f"<b>Statistik Profesional:</b>\n"
        f"  📊 Total Trade    : {stats['total']}\n"
        f"  🎯 Win Rate       : {stats['win_rate']}%\n"
        f"  💰 Profit Factor  : {stats['profit_factor']:.2f}\n"
        f"  📐 Sharpe Ratio   : {stats['sharpe']:.3f}\n"
        f"  📉 Max Drawdown   : {stats['max_drawdown']:.2f}%\n"
        f"  📏 Calmar Ratio   : {stats['calmar']:.2f}\n"
        f"  🔄 Recovery Factor: {stats['recovery_factor']:.2f}\n"
        f"  💡 Expectancy     : {stats['expectancy']:.3f}%\n"
        f"  ✅ Avg Win        : +{stats['avg_profit']:.2f}%\n"
        f"  ❌ Avg Loss       : {stats['avg_loss']:.2f}%\n"
        f"  🔥 Max Win Streak : {stats['max_consec_win']}x\n"
        f"  ❄️  Max Loss Streak: {stats['max_consec_loss']}x\n\n"
    )

    # Monthly breakdown
    if stats["per_bulan"]:
        pesan += "<b>Breakdown Bulanan:</b>\n"
        for bln, data in sorted(stats["per_bulan"].items(), reverse=True)[:3]:
            em = "📈" if data["profit"] > 0 else "📉"
            pesan += (f"  {em} {bln}: "
                      f"{data['profit']:+.2f}% ({data['n']} trade)\n")
        pesan += "\n"

    # Best/Worst
    pesan += (
        f"<b>Hall of Fame:</b>\n"
        f"  🏆 Best  : {stats['best']['symbol']}"
        f" +{stats['best']['profit_pct']:.2f}%\n"
        f"  💸 Worst : {stats['worst']['symbol']}"
        f" {stats['worst']['profit_pct']:.2f}%\n\n"
    )

    # Evaluasi live readiness
    eval_r = evaluasi_live_readiness()
    bar    = "█" * (eval_r["skor"] // 10) + "░" * (10 - eval_r["skor"] // 10)
    pesan += (
        f"<b>Kesiapan Live Trading:</b>\n"
        f"  Skor  : <b>{eval_r['skor']}/100</b> [{bar}]\n"
        f"  Status: {eval_r['pesan']}\n"
    )
    for d in eval_r.get("detail", []):
        pesan += f"  {d}\n"

    return pesan

# ══════════════════════════════════════════════
# JADWAL & MANUAL
# ══════════════════════════════════════════════

def cek_jadwal_laporan(posisi_spot, posisi_futures,
                       kirim_telegram, modal=100.0):
    global _last_laporan
    sekarang     = datetime.now()
    tanggal_hari = sekarang.strftime("%Y-%m-%d")
    jam_wib      = (sekarang.hour + 7) % 24

    if (jam_wib == LAPORAN_JAM_WIB and
            _last_laporan["tanggal"] != tanggal_hari):
        laporan = buat_laporan_harian(posisi_spot, posisi_futures, modal)
        if kirim_telegram(laporan):
            _last_laporan["tanggal"] = tanggal_hari
            print("  ✅ Laporan harian terkirim!")

        # Laporan mingguan setiap Senin
        if sekarang.weekday() == 0:
            lap_ming = buat_laporan_mingguan(posisi_spot, posisi_futures, modal)
            kirim_telegram(lap_ming)

        return True
    return False

def kirim_laporan_manual(posisi_spot, posisi_futures,
                         kirim_telegram, modal=100.0):
    laporan = buat_laporan_harian(posisi_spot, posisi_futures, modal)
    return kirim_telegram(laporan)