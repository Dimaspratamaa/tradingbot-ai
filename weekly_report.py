# ============================================
# WEEKLY REPORT SCHEDULER v1.0
# Auto Weekly Backtest Report setiap Senin 08:00 WIB
#
# Yang dikirim setiap Senin:
#   1. Laporan performa trading seminggu
#   2. Backtest top 5 koin (validasi strategi)
#   3. Ranking koin by Sharpe ratio
#   4. Skor kesiapan live trading
#   5. Rekomendasi untuk minggu depan
#
# Juga tersedia manual via /backtest di Telegram
# ============================================

import os
import time
import json
import pathlib

from datetime import datetime, timedelta

BASE_DIR   = pathlib.Path(__file__).parent
STATE_FILE = BASE_DIR / "weekly_report_state.json"

# Jam kirim laporan mingguan (WIB = UTC+7)
LAPORAN_HARI  = 0      # Senin (0=Senin, 6=Minggu)
LAPORAN_JAM   = 8      # jam 08:00
KOIN_BACKTEST = [
    "BTCUSDT", "ETHUSDT", "SOLUSDT",
    "BNBUSDT", "XRPUSDT"
]


# ══════════════════════════════════════════════
# STATE — Catat kapan terakhir laporan dikirim
# ══════════════════════════════════════════════

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {"last_weekly": None, "last_backtest": None}


def save_state(state):
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception:
        pass


# ══════════════════════════════════════════════
# FORMAT LAPORAN MINGGUAN LENGKAP
# ══════════════════════════════════════════════

def buat_laporan_mingguan_lengkap(posisi_spot, client,
                                   kirim_telegram):
    """
    Kirim laporan mingguan lengkap:
    1. Performa trading
    2. Backtest top koin
    3. Rekomendasi
    """
    waktu = datetime.now().strftime("%d %b %Y")
    print(f"\n  📊 [WEEKLY] Membuat laporan mingguan {waktu}...")

    # ── BAGIAN 1: Performa trading ──
    try:
        from portfolio_tracker import (
            buat_laporan_mingguan, evaluasi_live_readiness
        )
        lap_perf = buat_laporan_mingguan(posisi_spot, {})
        kirim_telegram(lap_perf)
        print("  ✅ Laporan performa terkirim")
        time.sleep(2)
    except Exception as e:
        print(f"  ⚠️  Laporan performa error: {e}")

    # ── BAGIAN 2: Evaluasi kesiapan live ──
    try:
        from portfolio_tracker import evaluasi_live_readiness
        eval_r = evaluasi_live_readiness()
        skor   = eval_r.get("skor", 0)
        siap   = eval_r.get("siap", False)

        bar    = "█" * (skor // 10) + "░" * (10 - skor // 10)
        pesan  = (
            f"🎯 <b>Evaluasi Kesiapan Live Trading</b>\n"
            f"{'─'*28}\n"
            f"Skor: <b>{skor}/100</b> [{bar}]\n"
            f"Status: {'🟢 SIAP' if siap else '🔴 Belum siap'}\n\n"
        )
        for d in eval_r.get("detail", []):
            pesan += f"{d}\n"
        pesan += f"\n📊 Berdasarkan {eval_r.get('n_trade',0)} trade"
        kirim_telegram(pesan)
        time.sleep(2)
    except Exception as e:
        print(f"  ⚠️  Evaluasi live error: {e}")

    # ── BAGIAN 3: Backtest top koin ──
    if client:
        kirim_telegram(
            f"🔄 <b>Memulai backtest mingguan...</b>\n"
            f"Koin: {', '.join(KOIN_BACKTEST)}\n"
            f"⏱ Estimasi: ~3-5 menit"
        )

        try:
            from backtesting import backtest_semua_koin
            hasil = backtest_semua_koin(
                client      = client,
                koin_list   = KOIN_BACKTEST,
                kirim_telegram = kirim_telegram,
                metode      = "simple",  # lebih cepat
            )

            if hasil:
                # Kirim ringkasan ranking
                pesan_rank = (
                    f"🏆 <b>Ranking Backtest Minggu Ini</b>\n"
                    f"{'─'*28}\n\n"
                )
                medals = ["🥇","🥈","🥉","4️⃣","5️⃣"]
                for i, s in enumerate(hasil[:5]):
                    m      = medals[i] if i < len(medals) else f"{i+1}."
                    layak  = (s["win_rate"] >= 50 and
                              s["profit_factor"] >= 1.3)
                    em     = "✅" if layak else "⚠️"
                    pesan_rank += (
                        f"{m} <b>{s['symbol']}</b> {em}\n"
                        f"   Return:{s['return_pct']:+.1f}% "
                        f"WR:{s['win_rate']:.0f}% "
                        f"Sharpe:{s['sharpe_ratio']:.2f}\n\n"
                    )
                kirim_telegram(pesan_rank)
                print("  ✅ Backtest ranking terkirim")

        except Exception as e:
            print(f"  ⚠️  Backtest error: {e}")
            kirim_telegram(f"⚠️ Backtest error: {str(e)[:100]}")

    # ── BAGIAN 4: Rekomendasi minggu depan ──
    try:
        _kirim_rekomendasi(client, kirim_telegram)
    except Exception as e:
        print(f"  ⚠️  Rekomendasi error: {e}")

    print("  ✅ [WEEKLY] Laporan mingguan selesai!")


def _kirim_rekomendasi(client, kirim_telegram):
    """Kirim rekomendasi singkat untuk minggu depan."""
    from portfolio_tracker import baca_semua_riwayat, hitung_statistik

    semua  = baca_semua_riwayat()
    stats  = hitung_statistik(semua[-50:]) if len(semua) >= 5 else None

    rekom  = []
    pesan  = f"💡 <b>Rekomendasi Minggu Depan</b>\n{'─'*28}\n\n"

    if stats:
        wr = stats.get("win_rate", 0)
        pf = stats.get("profit_factor", 1)
        dd = abs(stats.get("max_drawdown", 0))

        # Win rate terlalu rendah
        if wr < 45:
            rekom.append("⚠️ Win rate rendah (<45%) — pertimbangkan naikkan MIN_SCORE")
        elif wr >= 60:
            rekom.append("✅ Win rate bagus — strategi berjalan baik")

        # Profit factor
        if pf < 1.2:
            rekom.append("⚠️ Profit factor rendah — kurangi ukuran trade")
        elif pf >= 1.8:
            rekom.append("✅ Profit factor excellent — bisa pertimbangkan naikkan size")

        # Max drawdown
        if dd > 10:
            rekom.append(f"🚨 Max drawdown {dd:.1f}% — pertimbangkan pause & review")
        elif dd < 5:
            rekom.append(f"✅ Drawdown {dd:.1f}% — risiko terkontrol dengan baik")

        pesan += f"📊 Berdasarkan {len(semua[-50:])} trade terakhir:\n\n"
    else:
        rekom.append("ℹ️ Data trade belum cukup untuk rekomendasi")

    if not rekom:
        rekom.append("✅ Semua parameter dalam batas normal")

    for r in rekom:
        pesan += f"{r}\n"

    pesan += f"\n🕐 {datetime.now().strftime('%d %b %Y %H:%M WIB')}"
    kirim_telegram(pesan)


# ══════════════════════════════════════════════
# MANUAL BACKTEST — via /backtest Telegram
# ══════════════════════════════════════════════

def jalankan_backtest_manual(symbol, client, kirim_telegram,
                              hari=90, metode="simple"):
    """
    Jalankan backtest satu koin secara manual.
    Dipanggil dari command /backtest di Telegram.
    """
    print(f"\n  📊 [BACKTEST] Manual: {symbol} {hari}H {metode}")
    kirim_telegram(
        f"🔄 <b>Backtest dimulai...</b>\n"
        f"📍 {symbol} | {hari} hari | {metode}\n"
        f"⏱ Tunggu ~30-60 detik"
    )

    try:
        from backtesting import jalankan_backtest
        stats = jalankan_backtest(
            client         = client,
            symbol         = symbol,
            interval       = "1h",
            hari           = hari,
            kirim_telegram = kirim_telegram,
            metode         = metode,
        )
        return stats
    except Exception as e:
        pesan_err = f"❌ Backtest error: {str(e)[:100]}"
        kirim_telegram(pesan_err)
        print(f"  ⚠️  {pesan_err}")
        return None


def jalankan_backtest_semua(client, kirim_telegram,
                             metode="simple"):
    """
    Backtest semua koin prioritas.
    Dipanggil dari /backtest all di Telegram.
    """
    from backtesting import backtest_semua_koin

    kirim_telegram(
        f"🔄 <b>Multi-Coin Backtest dimulai</b>\n"
        f"Koin: {', '.join(KOIN_BACKTEST)}\n"
        f"⏱ Estimasi: ~5-10 menit"
    )

    try:
        hasil = backtest_semua_koin(
            client         = client,
            koin_list      = KOIN_BACKTEST,
            kirim_telegram = kirim_telegram,
            metode         = metode,
        )
        return hasil
    except Exception as e:
        kirim_telegram(f"❌ Backtest error: {str(e)[:100]}")
        return []


# ══════════════════════════════════════════════
# SCHEDULER — Cek jadwal setiap iterasi
# ══════════════════════════════════════════════

def cek_jadwal_weekly(posisi_spot, client, kirim_telegram):
    """
    Cek apakah sudah waktunya kirim laporan mingguan.
    Dipanggil dari main loop trading_bot.py.
    Laporan dikirim setiap Senin jam 08:00 WIB.
    """
    state  = load_state()
    now    = datetime.now()

    # Konversi ke WIB (UTC+7)
    jam_wib  = (now.hour + 7) % 24
    hari_ini = now.strftime("%Y-%m-%d")
    hari_minggu = now.weekday()   # 0=Senin, 6=Minggu

    # Cek: hari Senin + jam 08:00 WIB + belum kirim hari ini
    if (hari_minggu == LAPORAN_HARI and
            jam_wib == LAPORAN_JAM and
            state.get("last_weekly") != hari_ini):

        print(f"\n  📅 [WEEKLY] Waktunya laporan mingguan!")
        state["last_weekly"] = hari_ini
        save_state(state)

        # Jalankan laporan di thread agar tidak block main loop
        import threading
        t = threading.Thread(
            target=buat_laporan_mingguan_lengkap,
            args=(posisi_spot, client, kirim_telegram),
            daemon=True
        )
        t.start()
        return True

    return False