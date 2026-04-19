# ============================================
# WEB DASHBOARD v2.0 — Railway Ready
# Pure Python HTTP server — tanpa Flask/SocketIO
# Auto-refresh setiap 30 detik
#
# Akses: https://your-railway-url.railway.app
# ============================================

import json, os, time, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from pathlib import Path

PORT       = int(os.environ.get("PORT", 8080))
BASE_DIR   = Path(__file__).parent
AUTO_REFRESH = 30  # detik

# ══════════════════════════════════════════════
# DATA LOADER
# ══════════════════════════════════════════════

def load_data():
    data = {
        "posisi"    : {},
        "riwayat"   : [],
        "paper_state": {},
        "risk_state" : {},
        "bot_status" : {},
        "alpha_ic"   : {},
        "waktu"      : datetime.now().strftime("%d %b %Y %H:%M:%S"),
    }
    # Posisi aktif
    for fname in ["posisi_state.json", "paper_state.json"]:
        fpath = BASE_DIR / fname
        if fpath.exists():
            try:
                d = json.loads(fpath.read_text())
                if fname == "posisi_state.json":
                    data["posisi"] = d.get("posisi_spot", {})
                else:
                    data["paper_state"] = d
            except Exception:
                pass

    # Riwayat trade
    riwayat_file = BASE_DIR / "riwayat_trade.json"
    if riwayat_file.exists():
        try:
            data["riwayat"] = json.loads(riwayat_file.read_text())[-50:]
        except Exception:
            pass

    # Risk state
    risk_file = BASE_DIR / "risk_state.json"
    if risk_file.exists():
        try:
            data["risk_state"] = json.loads(risk_file.read_text())
        except Exception:
            pass

    # Alpha IC
    alpha_file = BASE_DIR / "alpha_ic.json"
    if alpha_file.exists():
        try:
            data["alpha_ic"] = json.loads(alpha_file.read_text())
        except Exception:
            pass

    return data


def hitung_stats(riwayat):
    if not riwayat:
        return {}
    profits   = [t["profit_pct"] for t in riwayat if "profit_pct" in t]
    if not profits:
        return {}
    import math
    menang    = sum(1 for p in profits if p > 0)
    total_pl  = sum(profits)
    win_rate  = menang / len(profits) * 100
    avg_win   = sum(p for p in profits if p>0) / max(1, menang)
    avg_loss  = sum(p for p in profits if p<=0) / max(1, len(profits)-menang)
    # Max drawdown
    import numpy as np
    arr    = np.array(profits)
    cumsum = np.cumsum(arr)
    peak   = np.maximum.accumulate(cumsum)
    max_dd = float(np.min(cumsum - peak))
    return {
        "n"        : len(profits),
        "menang"   : menang,
        "win_rate" : round(win_rate, 1),
        "total_pl" : round(total_pl, 2),
        "avg_win"  : round(avg_win, 2),
        "avg_loss" : round(avg_loss, 2),
        "max_dd"   : round(max_dd, 2),
    }


# ══════════════════════════════════════════════
# HTML TEMPLATE
# ══════════════════════════════════════════════

def render_html(data):
    stats    = hitung_stats(data["riwayat"])
    paper    = data.get("paper_state", {})
    risk     = data.get("risk_state", {})
    posisi   = data.get("posisi", {})
    riwayat  = data.get("riwayat", [])
    alpha_ic = data.get("alpha_ic", {})

    # Paper mode info
    paper_modal  = paper.get("modal_awal", 5000)
    paper_saldo  = paper.get("saldo_usdt", paper_modal)
    paper_pl     = round((paper_saldo - paper_modal) / paper_modal * 100, 2) if paper_modal else 0
    paper_trades = len(paper.get("riwayat", []))
    paper_live   = paper.get("live_mode", False)

    # Risk info
    konsekutif   = risk.get("konsekutif_loss", 0)
    sizing_f     = 1.0 - (0.5 if konsekutif >= 3 else 0)

    # Build posisi rows
    posisi_rows = ""
    posisi_aktif = [(s, p) for s, p in posisi.items() if p.get("aktif")]
    if posisi_aktif:
        for sym, pos in posisi_aktif:
            harga_beli  = pos.get("harga_beli", 0)
            sl          = pos.get("stop_loss", 0)
            tp          = pos.get("take_profit", 0)
            modal       = pos.get("modal", 0)
            waktu_beli  = pos.get("waktu_beli", "")[:16]
            be_aktif    = pos.get("breakeven_aktif", False)
            partial     = pos.get("partial_close_done", False)
            trailing    = pos.get("trailing_aktif", False)

            sl_pct = abs(harga_beli - sl) / harga_beli * 100 if harga_beli else 0
            badges = ""
            if be_aktif: badges += '<span class="badge be">🔒 BE</span>'
            if trailing: badges += '<span class="badge tr">🔄 Trail</span>'
            if partial:  badges += '<span class="badge pc">✂️ Partial</span>'

            posisi_rows += f"""
            <tr>
                <td><b>{sym}</b></td>
                <td>${harga_beli:,.4f}</td>
                <td>${sl:,.4f} <small>(-{sl_pct:.1f}%)</small></td>
                <td>${tp:,.4f}</td>
                <td>${modal:.0f}</td>
                <td>{waktu_beli}</td>
                <td>{badges}</td>
            </tr>"""
    else:
        posisi_rows = '<tr><td colspan="7" style="text-align:center;color:#666">Tidak ada posisi aktif</td></tr>'

    # Build riwayat rows (10 terakhir)
    riwayat_rows = ""
    for t in reversed(riwayat[-10:]):
        pl    = t.get("profit_pct", 0)
        color = "#2ea043" if pl > 0 else "#f85149"
        em    = "▲" if pl > 0 else "▼"
        riwayat_rows += f"""
        <tr>
            <td>{t.get("symbol","?")}</td>
            <td>{t.get("waktu_jual","")[:16]}</td>
            <td style="color:{color}">{em} {pl:+.2f}%</td>
            <td>{t.get("alasan","?")}</td>
        </tr>"""

    # Build alpha rows (top 8)
    alpha_rows = ""
    alpha_sorted = sorted(
        [(k, v) for k, v in alpha_ic.items() if isinstance(v, dict)],
        key=lambda x: x[1].get("ic_mean", 0), reverse=True
    )[:8]
    for name, ic_data in alpha_sorted:
        ic   = ic_data.get("ic_mean", 0)
        aktif= ic_data.get("aktif", True)
        n    = ic_data.get("n_prediksi", 0)
        color= "#2ea043" if ic > 0.05 else ("#f85149" if ic < -0.02 else "#888")
        status_dot = "🟢" if aktif else "🔴"
        bar_w = max(0, min(100, int(ic * 500 + 50)))
        alpha_rows += f"""
        <tr>
            <td>{status_dot} {name[:22]}</td>
            <td style="color:{color}">{ic:+.3f}</td>
            <td>{n}</td>
            <td><div style="background:{color};height:8px;width:{bar_w}px;border-radius:4px"></div></td>
        </tr>"""

    mode_badge = ('<span style="background:#f85149;padding:4px 12px;border-radius:20px;font-size:12px">🔴 LIVE</span>'
                  if paper_live else
                  '<span style="background:#388bfd;padding:4px 12px;border-radius:20px;font-size:12px">📝 PAPER</span>')

    return f"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="{AUTO_REFRESH}">
<title>Trading Bot Dashboard</title>
<style>
  * {{ box-sizing:border-box; margin:0; padding:0 }}
  body {{ background:#0d1117; color:#e6edf3; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; font-size:14px }}
  .header {{ background:#161b22; border-bottom:1px solid #30363d; padding:16px 24px; display:flex; align-items:center; justify-content:space-between }}
  .header h1 {{ font-size:18px; font-weight:600 }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:16px; padding:20px 24px }}
  .card {{ background:#161b22; border:1px solid #30363d; border-radius:8px; padding:16px }}
  .card h3 {{ font-size:12px; color:#8b949e; text-transform:uppercase; margin-bottom:12px; letter-spacing:.5px }}
  .metric {{ font-size:28px; font-weight:700; margin-bottom:4px }}
  .sub {{ font-size:12px; color:#8b949e }}
  .green {{ color:#2ea043 }} .red {{ color:#f85149 }} .blue {{ color:#388bfd }} .yellow {{ color:#d29922 }}
  .section {{ padding:0 24px 20px }}
  .section h2 {{ font-size:15px; font-weight:600; margin-bottom:12px; color:#8b949e }}
  table {{ width:100%; border-collapse:collapse }}
  th {{ background:#0d1117; color:#8b949e; font-size:11px; text-transform:uppercase; padding:8px 12px; text-align:left; letter-spacing:.5px }}
  td {{ padding:8px 12px; border-bottom:1px solid #21262d; font-size:13px }}
  tr:hover td {{ background:#1c2128 }}
  .badge {{ display:inline-block; font-size:11px; padding:2px 8px; border-radius:12px; margin:0 2px }}
  .be {{ background:#1f3a1f; color:#2ea043 }}
  .tr {{ background:#1a2535; color:#388bfd }}
  .pc {{ background:#2d2000; color:#d29922 }}
  .footer {{ text-align:center; padding:20px; color:#484f58; font-size:12px }}
</style>
</head>
<body>

<div class="header">
  <h1>🤖 Trading Bot Dashboard</h1>
  <div style="display:flex;align-items:center;gap:12px">
    {mode_badge}
    <span style="color:#484f58;font-size:12px">Auto-refresh {AUTO_REFRESH}s | {data['waktu']}</span>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h3>Mode Trading</h3>
    <div class="metric">{"LIVE" if paper_live else "PAPER"}</div>
    <div class="sub">{"Uang nyata aktif" if paper_live else "Simulasi - aman"}</div>
  </div>
  <div class="card">
    <h3>Saldo</h3>
    <div class="metric {'green' if paper_pl>=0 else 'red'}">${paper_saldo:,.2f}</div>
    <div class="sub">Modal: ${paper_modal:,.0f} | P/L: {paper_pl:+.2f}%</div>
  </div>
  <div class="card">
    <h3>Posisi Aktif</h3>
    <div class="metric blue">{len(posisi_aktif)}</div>
    <div class="sub">Max 3 posisi spot</div>
  </div>
  <div class="card">
    <h3>Total Trade</h3>
    <div class="metric">{stats.get('n', paper_trades)}</div>
    <div class="sub">Win rate: {stats.get('win_rate', 0):.1f}%</div>
  </div>
  <div class="card">
    <h3>P/L Total</h3>
    <div class="metric {'green' if stats.get('total_pl',0)>=0 else 'red'}">{stats.get('total_pl', 0):+.2f}%</div>
    <div class="sub">Avg win: +{stats.get('avg_win',0):.2f}% | loss: {stats.get('avg_loss',0):.2f}%</div>
  </div>
  <div class="card">
    <h3>Max Drawdown</h3>
    <div class="metric red">{stats.get('max_dd', 0):.2f}%</div>
    <div class="sub">Limit: -15%</div>
  </div>
  <div class="card">
    <h3>Sizing Factor</h3>
    <div class="metric {'yellow' if sizing_f<1 else 'green'}">{sizing_f:.0%}</div>
    <div class="sub">Loss berturut: {konsekutif}x</div>
  </div>
  <div class="card">
    <h3>Alpha Engine</h3>
    <div class="metric blue">{len(alpha_ic)}</div>
    <div class="sub">Alpha factors aktif</div>
  </div>
</div>

<div class="section">
  <h2>📌 Posisi Aktif</h2>
  <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;overflow:hidden">
  <table>
    <thead><tr>
      <th>Symbol</th><th>Entry</th><th>Stop Loss</th>
      <th>Take Profit</th><th>Modal</th><th>Waktu</th><th>Status</th>
    </tr></thead>
    <tbody>{posisi_rows}</tbody>
  </table>
  </div>
</div>

<div class="section">
  <h2 style="margin-top:20px">📋 Riwayat Trade (10 Terakhir)</h2>
  <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;overflow:hidden">
  <table>
    <thead><tr><th>Symbol</th><th>Waktu</th><th>P/L</th><th>Alasan</th></tr></thead>
    <tbody>{riwayat_rows if riwayat_rows else "<tr><td colspan=4 style='text-align:center;color:#666'>Belum ada trade</td></tr>"}</tbody>
  </table>
  </div>
</div>

<div class="section">
  <h2 style="margin-top:20px">🔬 Alpha IC Ranking</h2>
  <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;overflow:hidden">
  <table>
    <thead><tr><th>Alpha Factor</th><th>IC</th><th>N Trade</th><th>Strength</th></tr></thead>
    <tbody>{alpha_rows if alpha_rows else "<tr><td colspan=4 style='text-align:center;color:#666'>Belum ada data IC</td></tr>"}</tbody>
  </table>
  </div>
</div>

<div class="footer">
  🤖 Trading Bot AI — Quant Edition | Railway Cloud | Auto-refresh {AUTO_REFRESH}s
</div>
</body></html>"""


# ══════════════════════════════════════════════
# HTTP SERVER
# ══════════════════════════════════════════════

class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # suppress access logs

    def do_GET(self):
        if self.path in ('/', '/dashboard'):
            data    = load_data()
            html    = render_html(data)
            body    = html.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif self.path == '/api/data':
            data = load_data()
            body = json.dumps({
                "posisi"   : data["posisi"],
                "stats"    : hitung_stats(data["riwayat"]),
                "waktu"    : data["waktu"],
            }, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif self.path == '/health':
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'OK')

        else:
            self.send_response(404)
            self.end_headers()


def mulai_dashboard(port=PORT):
    """Mulai dashboard di background thread."""
    try:
        server = HTTPServer(('0.0.0.0', port), DashboardHandler)
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()
        print(f"  🌐 Dashboard: http://0.0.0.0:{port}")
        return server
    except Exception as e:
        print(f"  ⚠️  Dashboard error: {e}")
        return None


if __name__ == '__main__':
    print(f"Starting dashboard on port {PORT}...")
    server = HTTPServer(('0.0.0.0', PORT), DashboardHandler)
    print(f"✅ Dashboard running: http://0.0.0.0:{PORT}")
    server.serve_forever()