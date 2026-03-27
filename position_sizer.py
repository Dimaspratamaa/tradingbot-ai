# ============================================
# POSITION SIZER v1.0
# Kelly Criterion + Dynamic Position Sizing
#
# Kelly Formula:
#   f = (bp - q) / b
#   f = fraction of capital to bet
#   b = odds (avg_win / avg_loss)
#   p = win probability
#   q = 1 - p (loss probability)
#
# Implementasi: Half-Kelly untuk safety
# ============================================

import json
import os
from datetime import datetime, timedelta

# ── KONFIGURASI ───────────────────────────────
KELLY_FRACTION    = 0.5    # Half-Kelly (lebih konservatif)
MIN_MODAL         = 20.0   # Minimum $20 per trade
MAX_MODAL         = 200.0  # Maximum $200 per trade
DEFAULT_MODAL     = 100.0  # Default jika belum ada data
MIN_TRADE_SAMPLE  = 10     # Minimal 10 trade untuk hitung Kelly

# ══════════════════════════════════════════════
# HITUNG STATISTIK DARI RIWAYAT
# ══════════════════════════════════════════════

def hitung_statistik_trading(hari=30):
    """
    Hitung statistik win rate dari riwayat trade.
    Default: 30 hari terakhir.
    """
    if not os.path.exists("riwayat_trade.json"):
        return None

    try:
        with open("riwayat_trade.json", "r") as f:
            semua = json.load(f)
    except:
        return None

    # Filter 30 hari terakhir
    batas = datetime.now() - timedelta(days=hari)
    trades = []
    for t in semua:
        try:
            wt = datetime.strptime(t["waktu_jual"][:19], "%Y-%m-%d %H:%M:%S")
            if wt >= batas:
                trades.append(t)
        except:
            pass

    if len(trades) < MIN_TRADE_SAMPLE:
        return None

    menang = [t for t in trades if t["profit_pct"] > 0]
    kalah  = [t for t in trades if t["profit_pct"] <= 0]

    if not menang or not kalah:
        return None

    win_rate  = len(menang) / len(trades)
    avg_win   = sum(t["profit_pct"] for t in menang) / len(menang)
    avg_loss  = abs(sum(t["profit_pct"] for t in kalah) / len(kalah))

    return {
        "n_trade"  : len(trades),
        "win_rate" : win_rate,
        "avg_win"  : avg_win,
        "avg_loss" : avg_loss,
        "rr_ratio" : avg_win / avg_loss if avg_loss > 0 else 1.0
    }

# ══════════════════════════════════════════════
# KELLY CRITERION
# ══════════════════════════════════════════════

def hitung_kelly(win_rate, avg_win, avg_loss):
    """
    Hitung Kelly fraction.
    Return: persentase modal yang optimal (0.0 - 1.0)
    """
    if avg_loss <= 0 or win_rate <= 0:
        return 0.0

    b = avg_win / avg_loss  # Odds ratio
    p = win_rate
    q = 1 - p

    kelly = (b * p - q) / b

    # Kelly negatif = jangan bet
    if kelly <= 0:
        return 0.0

    # Half-Kelly untuk safety
    return kelly * KELLY_FRACTION

def hitung_posisi_size(saldo_usdt, skor_sinyal=7,
                        modal_default=DEFAULT_MODAL):
    """
    Hitung ukuran posisi optimal berdasarkan:
    1. Kelly Criterion dari riwayat trade
    2. Kekuatan sinyal (skor lebih tinggi = posisi lebih besar)
    3. Batas min/max

    Return: float (nominal USD untuk trade)
    """
    stats = hitung_statistik_trading()

    if stats is None:
        # Belum ada data cukup — pakai default
        return modal_default

    # Hitung Kelly fraction
    kelly_f = hitung_kelly(
        stats["win_rate"],
        stats["avg_win"],
        stats["avg_loss"]
    )

    # Base position dari Kelly
    base_modal = saldo_usdt * kelly_f

    # Boost berdasarkan kekuatan sinyal (skor 7-15)
    # Skor 7 = 1.0x, Skor 10 = 1.3x, Skor 15 = 1.8x
    skor_boost = 1.0 + min((skor_sinyal - 7) * 0.06, 0.8)
    modal      = base_modal * skor_boost

    # Clamp ke min/max
    modal = max(MIN_MODAL, min(MAX_MODAL, modal))

    return round(modal, 2)

def get_position_info(saldo_usdt, skor_sinyal=7):
    """Ambil info lengkap position sizing untuk display"""
    stats  = hitung_statistik_trading()
    modal  = hitung_posisi_size(saldo_usdt, skor_sinyal)

    if stats:
        kelly_f = hitung_kelly(
            stats["win_rate"], stats["avg_win"], stats["avg_loss"]
        )
        return {
            "modal"    : modal,
            "kelly_f"  : round(kelly_f * 100, 1),
            "win_rate" : round(stats["win_rate"] * 100, 1),
            "rr_ratio" : round(stats["rr_ratio"], 2),
            "n_trade"  : stats["n_trade"],
            "metode"   : "KELLY"
        }
    else:
        return {
            "modal"    : modal,
            "kelly_f"  : 0,
            "win_rate" : 0,
            "rr_ratio" : 0,
            "n_trade"  : 0,
            "metode"   : "DEFAULT"
        }