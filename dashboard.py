# ============================================
# WEB DASHBOARD TRADING BOT
# Akses via browser: http://localhost:5000
# ============================================

from flask import Flask, render_template_string
from flask_socketio import SocketIO
import threading
import json
import os
import time

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# ── HTML DASHBOARD ────────────────────────────
HTML = '''
<!DOCTYPE html>
<html lang="id">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Trading Bot Dashboard</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js"></script>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: #0d1117;
            color: #e6edf3;
            font-family: 'Segoe UI', sans-serif;
            padding: 20px;
        }
        h1 {
            text-align: center;
            color: #58a6ff;
            font-size: 24px;
            margin-bottom: 20px;
            padding: 15px;
            border-bottom: 1px solid #30363d;
        }
        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        .card {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 10px;
            padding: 20px;
            text-align: center;
        }
        .card .label {
            color: #8b949e;
            font-size: 12px;
            margin-bottom: 8px;
        }
        .card .value {
            font-size: 22px;
            font-weight: bold;
        }
        .green  { color: #2ecc71; }
        .red    { color: #e74c3c; }
        .blue   { color: #58a6ff; }
        .gold   { color: #f39c12; }
        .white  { color: #e6edf3; }

        .chart-container {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 20px;
        }
        .chart-container h3 {
            color: #8b949e;
            font-size: 14px;
            margin-bottom: 15px;
        }

        .skor-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
            margin-bottom: 20px;
        }
        .skor-card {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 10px;
            padding: 20px;
        }
        .skor-card h3 {
            font-size: 14px;
            margin-bottom: 15px;
            color: #8b949e;
        }
        .skor-bar {
            display: flex;
            align-items: center;
            margin-bottom: 10px;
            gap: 10px;
        }
        .skor-label {
            width: 120px;
            font-size: 12px;
            color: #8b949e;
        }
        .skor-fill {
            height: 8px;
            border-radius: 4px;
            transition: width 0.5s;
        }
        .skor-num {
            font-size: 12px;
            color: #e6edf3;
            width: 30px;
        }

        .tabel-container {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 10px;
            padding: 20px;
            margin-bottom: 20px;
            overflow-x: auto;
        }
        .tabel-container h3 {
            color: #8b949e;
            font-size: 14px;
            margin-bottom: 15px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            font-size: 13px;
        }
        th {
            background: #0d1117;
            padding: 10px;
            text-align: left;
            color: #8b949e;
            border-bottom: 1px solid #30363d;
        }
        td {
            padding: 10px;
            border-bottom: 1px solid #21262d;
        }
        tr:hover { background: #1c2128; }

        .badge {
            padding: 3px 10px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: bold;
        }
        .badge-buy    { background: #1a4731; color: #2ecc71; }
        .badge-sell   { background: #4a1a1a; color: #e74c3c; }
        .badge-hold   { background: #1a2a4a; color: #58a6ff; }
        .badge-profit { background: #1a4731; color: #2ecc71; }
        .badge-loss   { background: #4a1a1a; color: #e74c3c; }
        .badge-tp     { background: #1a3a4a; color: #58a6ff; }
        .badge-sl     { background: #4a2a1a; color: #f39c12; }

        .status-dot {
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 50%;
            background: #2ecc71;
            animation: pulse 1.5s infinite;
            margin-right: 6px;
        }
        @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.3; }
        }

        .log-container {
            background: #0d1117;
            border: 1px solid #30363d;
            border-radius: 10px;
            padding: 15px;
            height: 200px;
            overflow-y: auto;
            font-family: monospace;
            font-size: 12px;
        }
        .log-item {
            padding: 3px 0;
            border-bottom: 1px solid #21262d;
            color: #8b949e;
        }
        .log-item.buy  { color: #2ecc71; }
        .log-item.sell { color: #e74c3c; }
        .log-item.err  { color: #f39c12; }

        footer {
            text-align: center;
            color: #8b949e;
            font-size: 11px;
            margin-top: 20px;
            padding-top: 15px;
            border-top: 1px solid #30363d;
        }
    </style>
</head>
<body>
    <h1>🤖 Trading Bot Dashboard - BTC/USDT</h1>

    <!-- Status Cards -->
    <div class="grid">
        <div class="card">
            <div class="label">STATUS BOT</div>
            <div class="value">
                <span class="status-dot"></span>
                <span class="green" id="status-bot">AKTIF</span>
            </div>
        </div>
        <div class="card">
            <div class="label">HARGA BTC</div>
            <div class="value blue" id="harga">$0.00</div>
        </div>
        <div class="card">
            <div class="label">SINYAL</div>
            <div class="value" id="sinyal">-</div>
        </div>
        <div class="card">
            <div class="label">SKOR BUY</div>
            <div class="value green" id="skor-buy">0/8</div>
        </div>
        <div class="card">
            <div class="label">SKOR SELL</div>
            <div class="value red" id="skor-sell">0/8</div>
        </div>
        <div class="card">
            <div class="label">ML PREDIKSI</div>
            <div class="value gold" id="ml-pred">-</div>
        </div>
        <div class="card">
            <div class="label">SALDO USDT</div>
            <div class="value white" id="saldo-usdt">0.00</div>
        </div>
        <div class="card">
            <div class="label">SALDO BTC</div>
            <div class="value white" id="saldo-btc">0.00</div>
        </div>
    </div>

    <!-- Grafik Harga -->
    <div class="chart-container">
        <h3>📈 Grafik Harga BTC (Real-time)</h3>
        <canvas id="hargaChart" height="80"></canvas>
    </div>

    <!-- Posisi Aktif -->
    <div id="posisi-container" style="display:none; margin-bottom:20px;">
        <div class="card" style="text-align:left;">
            <div class="label" style="margin-bottom:10px;">📊 POSISI AKTIF</div>
            <div style="display:grid; grid-template-columns:repeat(4,1fr); gap:10px;">
                <div><div class="label">Harga Beli</div><div class="value blue" id="pos-beli">-</div></div>
                <div><div class="label">Stop Loss</div><div class="value red" id="pos-sl">-</div></div>
                <div><div class="label">Take Profit</div><div class="value green" id="pos-tp">-</div></div>
                <div><div class="label">P/L Saat Ini</div><div class="value" id="pos-pl">-</div></div>
            </div>
        </div>
    </div>

    <!-- Skor Indikator -->
    <div class="skor-grid">
        <div class="skor-card">
            <h3>🟢 Konfirmasi BUY</h3>
            <div id="detail-buy"></div>
        </div>
        <div class="skor-card">
            <h3>🔴 Konfirmasi SELL</h3>
            <div id="detail-sell"></div>
        </div>
    </div>

    <!-- Riwayat Transaksi -->
    <div class="tabel-container">
        <h3>📋 Riwayat Transaksi</h3>
        <table>
            <thead>
                <tr>
                    <th>No</th>
                    <th>Waktu Beli</th>
                    <th>Harga Beli</th>
                    <th>Harga Jual</th>
                    <th>P/L</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody id="tabel-transaksi">
                <tr><td colspan="6" style="text-align:center; color:#8b949e;">
                    Belum ada transaksi
                </td></tr>
            </tbody>
        </table>
    </div>

    <!-- Log Activity -->
    <div class="tabel-container">
        <h3>📝 Log Aktivitas</h3>
        <div class="log-container" id="log-container"></div>
    </div>

    <footer>
        Trading Bot v6.0 — Update setiap 5 detik
        | <span id="last-update">-</span>
    </footer>

    <script>
        const socket = io();

        // ── Grafik Harga ──
        const ctx = document.getElementById('hargaChart').getContext('2d');
        const hargaChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: [{
                    label: 'BTC/USDT',
                    data: [],
                    borderColor: '#58a6ff',
                    backgroundColor: 'rgba(88,166,255,0.1)',
                    borderWidth: 2,
                    pointRadius: 3,
                    tension: 0.3,
                    fill: true
                }]
            },
            options: {
                responsive: true,
                plugins: { legend: { display: false } },
                scales: {
                    x: {
                        ticks: { color: '#8b949e', maxTicksLimit: 8 },
                        grid:  { color: '#21262d' }
                    },
                    y: {
                        ticks: {
                            color: '#8b949e',
                            callback: v => '$' + v.toLocaleString()
                        },
                        grid: { color: '#21262d' }
                    }
                }
            }
        });

        // ── Update Data dari Server ──
        socket.on('update_data', function(data) {
            // Cards
            const h = parseFloat(data.harga);
            document.getElementById('harga').textContent =
                '$' + h.toLocaleString('en-US', {minimumFractionDigits:2});

            // Sinyal
            const sEl = document.getElementById('sinyal');
            sEl.textContent = data.sinyal;
            sEl.className = 'value ' +
                (data.sinyal === 'BUY' ? 'green' :
                 data.sinyal === 'SELL' ? 'red' : 'blue');

            document.getElementById('skor-buy').textContent  = data.skor_buy + '/8';
            document.getElementById('skor-sell').textContent = data.skor_sell + '/8';
            document.getElementById('ml-pred').textContent   =
                data.ml_pred + ' (' + data.ml_conf + '%)';
            document.getElementById('saldo-usdt').textContent =
                parseFloat(data.saldo_usdt).toFixed(2);
            document.getElementById('saldo-btc').textContent =
                parseFloat(data.saldo_btc).toFixed(8);

            // Grafik
            const now = new Date().toLocaleTimeString('id-ID');
            hargaChart.data.labels.push(now);
            hargaChart.data.datasets[0].data.push(h);
            if (hargaChart.data.labels.length > 30) {
                hargaChart.data.labels.shift();
                hargaChart.data.datasets[0].data.shift();
            }
            hargaChart.update();

            // Posisi aktif
            if (data.posisi_aktif) {
                document.getElementById('posisi-container').style.display = 'block';
                document.getElementById('pos-beli').textContent =
                    '$' + parseFloat(data.harga_beli).toLocaleString();
                document.getElementById('pos-sl').textContent =
                    '$' + parseFloat(data.stop_loss).toLocaleString();
                document.getElementById('pos-tp').textContent =
                    '$' + parseFloat(data.take_profit).toLocaleString();
                const pl = parseFloat(data.pl_pct);
                const plEl = document.getElementById('pos-pl');
                plEl.textContent   = (pl >= 0 ? '+' : '') + pl.toFixed(2) + '%';
                plEl.className = 'value ' + (pl >= 0 ? 'green' : 'red');
            } else {
                document.getElementById('posisi-container').style.display = 'none';
            }

            // Detail indikator
            const buyDiv  = document.getElementById('detail-buy');
            const sellDiv = document.getElementById('detail-sell');
            buyDiv.innerHTML  = data.detail_buy.map(d =>
                `<div style="font-size:12px;padding:4px 0;color:#2ecc71">${d}</div>`
            ).join('') || '<div style="color:#8b949e;font-size:12px">Tidak ada sinyal</div>';
            sellDiv.innerHTML = data.detail_sell.map(d =>
                `<div style="font-size:12px;padding:4px 0;color:#e74c3c">${d}</div>`
            ).join('') || '<div style="color:#8b949e;font-size:12px">Tidak ada sinyal</div>';

            // Last update
            document.getElementById('last-update').textContent =
                'Update: ' + new Date().toLocaleTimeString('id-ID');
        });

        // ── Update Transaksi ──
        socket.on('update_transaksi', function(trades) {
            const tbody = document.getElementById('tabel-transaksi');
            if (trades.length === 0) {
                tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;color:#8b949e">Belum ada transaksi</td></tr>';
                return;
            }
            tbody.innerHTML = trades.slice().reverse().map((t, i) => {
                const pl = parseFloat(t.profit_pct);
                const badge = pl > 0
                    ? '<span class="badge badge-profit">✅ PROFIT</span>'
                    : '<span class="badge badge-loss">❌ LOSS</span>';
                const alasan = t.alasan === 'TAKE_PROFIT'
                    ? '<span class="badge badge-tp">🎯 TP</span>'
                    : '<span class="badge badge-sl">🛑 SL</span>';
                return `<tr>
                    <td>${trades.length - i}</td>
                    <td>${t.waktu_beli}</td>
                    <td>$${parseFloat(t.harga_beli).toLocaleString()}</td>
                    <td>$${parseFloat(t.harga_jual).toLocaleString()}</td>
                    <td class="${pl >= 0 ? 'green' : 'red'}">${pl >= 0 ? '+' : ''}${pl.toFixed(2)}%</td>
                    <td>${badge} ${alasan}</td>
                </tr>`;
            }).join('');
        });

        // ── Log Aktivitas ──
        socket.on('log', function(data) {
            const container = document.getElementById('log-container');
            const div = document.createElement('div');
            div.className = 'log-item ' + (data.type || '');
            div.textContent = data.waktu + ' | ' + data.pesan;
            container.insertBefore(div, container.firstChild);
            if (container.children.length > 50) {
                container.removeChild(container.lastChild);
            }
        });
    </script>
</body>
</html>
'''

# ── BACA DATA BOT ─────────────────────────────
def baca_status():
    try:
        if os.path.exists("bot_status.json"):
            with open("bot_status.json", "r") as f:
                return json.load(f)
    except:
        pass
    return {}

def baca_transaksi():
    try:
        if os.path.exists("riwayat_trade.json"):
            with open("riwayat_trade.json", "r") as f:
                return json.load(f)
    except:
        pass
    return []

# ── BROADCAST DATA KE BROWSER ─────────────────
def broadcast_loop():
    while True:
        try:
            status    = baca_status()
            transaksi = baca_transaksi()

            if status:
                socketio.emit('update_data', status)
                socketio.emit('update_transaksi', transaksi)

        except Exception as e:
            print(f"Broadcast error: {e}")

        time.sleep(5)

# ── ROUTE ─────────────────────────────────────
@app.route('/')
def index():
    return render_template_string(HTML)

# ── MAIN ──────────────────────────────────────
if __name__ == '__main__':
    t = threading.Thread(target=broadcast_loop, daemon=True)
    t.start()
    print("=" * 45)
    print("   WEB DASHBOARD TRADING BOT")
    print("   Buka browser: http://localhost:5000")
    print("=" * 45)
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)