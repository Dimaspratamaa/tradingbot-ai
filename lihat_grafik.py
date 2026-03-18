# ============================================
# DASHBOARD GRAFIK PROFIT/LOSS TRADING BOT
# ============================================

import json
import os
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.patches import FancyBboxPatch
from datetime import datetime

# ── BACA DATA ─────────────────────────────────
def baca_riwayat():
    if not os.path.exists("riwayat_trade.json"):
        print("❌ File riwayat_trade.json belum ada!")
        return []
    with open("riwayat_trade.json", "r") as f:
        return json.load(f)

# ── HITUNG STATISTIK ──────────────────────────
def hitung_statistik(trades):
    profits     = [t["profit_pct"] for t in trades]
    profit_kum  = []
    total       = 0
    for p in profits:
        total += p
        profit_kum.append(round(total, 4))

    total_trade  = len(trades)
    win_trade    = sum(1 for p in profits if p > 0)
    lose_trade   = total_trade - win_trade
    win_rate     = (win_trade / total_trade * 100) if total_trade > 0 else 0
    total_profit = sum(profits)
    avg_profit   = sum(p for p in profits if p > 0) / win_trade if win_trade > 0 else 0
    avg_loss     = sum(p for p in profits if p < 0) / lose_trade if lose_trade > 0 else 0
    best_trade   = max(profits)
    worst_trade  = min(profits)
    profit_factor = abs(avg_profit / avg_loss) if avg_loss != 0 else 0

    return {
        "profits"       : profits,
        "profit_kum"    : profit_kum,
        "total_trade"   : total_trade,
        "win_trade"     : win_trade,
        "lose_trade"    : lose_trade,
        "win_rate"      : win_rate,
        "total_profit"  : total_profit,
        "avg_profit"    : avg_profit,
        "avg_loss"      : avg_loss,
        "best_trade"    : best_trade,
        "worst_trade"   : worst_trade,
        "profit_factor" : profit_factor
    }

# ── TAMPILKAN TABEL ───────────────────────────
def tampilkan_tabel(trades):
    print("\n" + "=" * 80)
    print(f"{'No':>3} | {'Waktu Beli':<20} | {'Beli':>12} | {'Jual':>12} | {'P/L':>8} | Status")
    print("=" * 80)
    for i, t in enumerate(trades, 1):
        status = "✅ PROFIT" if t["profit_pct"] > 0 else "❌ LOSS"
        print(f"{i:>3} | {t['waktu_beli']:<20} | "
              f"${t['harga_beli']:>11,.2f} | "
              f"${t['harga_jual']:>11,.2f} | "
              f"{t['profit_pct']:>+7.2f}% | {status}")
    print("=" * 80)

# ── BUAT DASHBOARD ────────────────────────────
def buat_dashboard(trades, stat):
    fig = plt.figure(figsize=(16, 12))
    fig.patch.set_facecolor('#0d1117')
    fig.suptitle('📊 TRADING BOT DASHBOARD - BTC/USDT',
                fontsize=18, fontweight='bold',
                color='white', y=0.98)

    gs = gridspec.GridSpec(3, 3, figure=fig,
                          hspace=0.45, wspace=0.35)

    # ── Warna ──
    CLR_BG    = '#161b22'
    CLR_GREEN = '#2ecc71'
    CLR_RED   = '#e74c3c'
    CLR_BLUE  = '#3498db'
    CLR_GOLD  = '#f39c12'
    CLR_WHITE = '#ffffff'
    CLR_GRAY  = '#8b949e'

    n      = stat["total_trade"]
    trades_x = list(range(1, n + 1))

    # ── GRAFIK 1: Profit per Trade (bar) ──────
    ax1 = fig.add_subplot(gs[0, :2])
    ax1.set_facecolor(CLR_BG)
    colors = [CLR_GREEN if p > 0 else CLR_RED for p in stat["profits"]]
    bars = ax1.bar(trades_x, stat["profits"], color=colors, alpha=0.85, width=0.6)
    ax1.axhline(y=0, color=CLR_GRAY, linestyle='-', linewidth=0.8)
    ax1.set_title("Profit / Loss per Trade (%)", color=CLR_WHITE, fontsize=11, pad=8)
    ax1.set_xlabel("Trade ke-", color=CLR_GRAY, fontsize=9)
    ax1.set_ylabel("Profit (%)", color=CLR_GRAY, fontsize=9)
    ax1.tick_params(colors=CLR_GRAY)
    ax1.spines['bottom'].set_color(CLR_GRAY)
    ax1.spines['left'].set_color(CLR_GRAY)
    ax1.spines['top'].set_visible(False)
    ax1.spines['right'].set_visible(False)
    for bar, p in zip(bars, stat["profits"]):
        ax1.text(bar.get_x() + bar.get_width()/2, p + 0.05,
                f"{p:+.1f}%", ha='center', va='bottom',
                fontsize=8, color=CLR_GREEN if p > 0 else CLR_RED)

    # ── GRAFIK 2: Kumulatif Profit (line) ─────
    ax2 = fig.add_subplot(gs[1, :2])
    ax2.set_facecolor(CLR_BG)
    color_kum = CLR_GREEN if stat["profit_kum"][-1] >= 0 else CLR_RED
    ax2.plot(trades_x, stat["profit_kum"], marker='o',
            color=color_kum, linewidth=2.5, markersize=6)
    ax2.fill_between(trades_x, stat["profit_kum"],
                    alpha=0.15, color=color_kum)
    ax2.axhline(y=0, color=CLR_GRAY, linestyle='--', linewidth=0.8)
    ax2.set_title("Profit Kumulatif (%)", color=CLR_WHITE, fontsize=11, pad=8)
    ax2.set_xlabel("Trade ke-", color=CLR_GRAY, fontsize=9)
    ax2.set_ylabel("Total (%)", color=CLR_GRAY, fontsize=9)
    ax2.tick_params(colors=CLR_GRAY)
    ax2.spines['bottom'].set_color(CLR_GRAY)
    ax2.spines['left'].set_color(CLR_GRAY)
    ax2.spines['top'].set_visible(False)
    ax2.spines['right'].set_visible(False)

    # ── GRAFIK 3: Win Rate (pie) ───────────────
    ax3 = fig.add_subplot(gs[0, 2])
    ax3.set_facecolor(CLR_BG)
    sizes  = [stat["win_trade"], max(stat["lose_trade"], 0.001)]
    colors3 = [CLR_GREEN, CLR_RED]
    wedges, texts, autotexts = ax3.pie(
        sizes, labels=[f'Win\n({stat["win_trade"]})', f'Loss\n({stat["lose_trade"]})'],
        colors=colors3, autopct='%1.1f%%',
        startangle=90, textprops={'color': CLR_WHITE, 'fontsize': 9}
    )
    for at in autotexts:
        at.set_fontsize(9)
        at.set_color(CLR_WHITE)
    ax3.set_title(f"Win Rate", color=CLR_WHITE, fontsize=11, pad=8)

    # ── GRAFIK 4: Distribusi Profit (histogram) ─
    ax4 = fig.add_subplot(gs[1, 2])
    ax4.set_facecolor(CLR_BG)
    profit_vals = [p for p in stat["profits"] if p > 0]
    loss_vals   = [p for p in stat["profits"] if p < 0]
    if profit_vals:
        ax4.hist(profit_vals, bins=5, color=CLR_GREEN, alpha=0.7, label='Profit')
    if loss_vals:
        ax4.hist(loss_vals, bins=5, color=CLR_RED, alpha=0.7, label='Loss')
    ax4.set_title("Distribusi P/L", color=CLR_WHITE, fontsize=11, pad=8)
    ax4.set_xlabel("Profit (%)", color=CLR_GRAY, fontsize=9)
    ax4.tick_params(colors=CLR_GRAY)
    ax4.spines['bottom'].set_color(CLR_GRAY)
    ax4.spines['left'].set_color(CLR_GRAY)
    ax4.spines['top'].set_visible(False)
    ax4.spines['right'].set_visible(False)
    ax4.legend(fontsize=8, labelcolor=CLR_WHITE,
              facecolor=CLR_BG, edgecolor=CLR_GRAY)

    # ── STATISTIK PANEL ───────────────────────
    ax5 = fig.add_subplot(gs[2, :])
    ax5.set_facecolor(CLR_BG)
    ax5.axis('off')

    stats_items = [
        ("📈 Total Trade",    f"{stat['total_trade']}",          CLR_WHITE),
        ("✅ Win",            f"{stat['win_trade']}",             CLR_GREEN),
        ("❌ Loss",           f"{stat['lose_trade']}",            CLR_RED),
        ("🎯 Win Rate",       f"{stat['win_rate']:.1f}%",         CLR_GOLD),
        ("💰 Total P/L",      f"{stat['total_profit']:+.2f}%",
         CLR_GREEN if stat['total_profit'] >= 0 else CLR_RED),
        ("📊 Avg Profit",     f"+{stat['avg_profit']:.2f}%",      CLR_GREEN),
        ("📉 Avg Loss",       f"{stat['avg_loss']:.2f}%",         CLR_RED),
        ("🏆 Best Trade",     f"+{stat['best_trade']:.2f}%",      CLR_GREEN),
        ("💔 Worst Trade",    f"{stat['worst_trade']:.2f}%",      CLR_RED),
        ("⚖️  Profit Factor", f"{stat['profit_factor']:.2f}x",    CLR_BLUE),
    ]

    cols   = len(stats_items)
    col_w  = 1.0 / cols
    for i, (label, value, color) in enumerate(stats_items):
        x = i * col_w + col_w / 2
        ax5.text(x, 0.75, label, ha='center', va='center',
                fontsize=8, color=CLR_GRAY,
                transform=ax5.transAxes)
        ax5.text(x, 0.30, value, ha='center', va='center',
                fontsize=13, fontweight='bold', color=color,
                transform=ax5.transAxes)

    ax5.set_title("📋 Ringkasan Statistik",
                 color=CLR_WHITE, fontsize=11, pad=8)

    # ── Simpan & Tampilkan ────────────────────
    plt.savefig("dashboard_trading.png", dpi=150,
               bbox_inches='tight', facecolor='#0d1117')
    print("\n✅ Dashboard disimpan: dashboard_trading.png")
    plt.show()

# ── MAIN ──────────────────────────────────────
print("=" * 55)
print("   📊 TRADING BOT DASHBOARD")
print("=" * 55)

trades = baca_riwayat()

if len(trades) == 0:
    print("❌ Belum ada data transaksi!")
    print("   Jalankan dulu: python buat_data_test.py")
else:
    print(f"✅ Ditemukan {len(trades)} transaksi")
    stat = hitung_statistik(trades)
    tampilkan_tabel(trades)
    buat_dashboard(trades, stat)