# ============================================
# BACKTESTING ENGINE v1.0
# Test strategi di data historis Binance
# Kirim laporan hasil ke Telegram
# ============================================

import pandas as pd
import numpy as np
import json
import time
from datetime import datetime, timedelta
from binance.client import Client

# ── KONFIGURASI ───────────────────────────────
FEE_RATE     = 0.001   # 0.1% fee per transaksi
SLIPPAGE     = 0.0005  # 0.05% slippage estimasi
MODAL_AWAL   = 10_000  # Modal backtest $10,000

# ══════════════════════════════════════════════
# AMBIL DATA HISTORIS
# ══════════════════════════════════════════════

def get_data_historis(client, symbol, interval, hari=90):
    """
    Ambil data OHLCV historis dari Binance.
    Default: 90 hari ke belakang.
    """
    try:
        end_time   = int(time.time() * 1000)
        start_time = int((time.time() - hari * 86400) * 1000)

        klines = client.get_historical_klines(
            symbol     = symbol,
            interval   = interval,
            start_str  = start_time,
            end_str    = end_time,
            limit      = 1000
        )

        df = pd.DataFrame(klines, columns=[
            'time','open','high','low','close','volume',
            'close_time','quote_vol','trades',
            'taker_base','taker_quote','ignore'
        ])
        for col in ['open','high','low','close','volume']:
            df[col] = df[col].astype(float)
        df['time'] = pd.to_datetime(df['time'], unit='ms')
        df = df.set_index('time')

        return df
    except Exception as e:
        print(f"  ⚠️  Historis error {symbol}: {e}")
        return None

# ══════════════════════════════════════════════
# HITUNG INDIKATOR
# ══════════════════════════════════════════════

def hitung_indikator_bt(df):
    """Hitung semua indikator untuk backtesting"""
    close  = df['close']
    high   = df['high']
    low    = df['low']
    volume = df['volume']

    # RSI
    delta = close.diff()
    gain  = delta.where(delta > 0, 0).rolling(14).mean()
    loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi'] = 100 - (100 / (1 + gain / loss))

    # MACD
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    df['macd']   = ema12 - ema26
    df['signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['signal']

    # Bollinger Bands
    sma20 = close.rolling(20).mean()
    std20 = close.rolling(20).std()
    df['bb_upper'] = sma20 + std20 * 2
    df['bb_lower'] = sma20 - std20 * 2
    df['bb_pos']   = (close - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])

    # ATR
    tr  = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()

    # EMA
    df['ema20'] = close.ewm(span=20, adjust=False).mean()
    df['ema50'] = close.ewm(span=50, adjust=False).mean()

    # Volume ratio
    df['vol_ratio'] = volume / volume.rolling(20).mean()

    # Momentum
    df['momentum'] = close.pct_change(24) * 100

    return df.dropna()

# ══════════════════════════════════════════════
# STRATEGI SINYAL
# ══════════════════════════════════════════════

def generate_sinyal(df):
    """
    Generate sinyal BUY/SELL berdasarkan indikator.
    Sama dengan logika bot live.
    """
    sinyal = pd.Series(0, index=df.index)

    for i in range(1, len(df)):
        row      = df.iloc[i]
        row_prev = df.iloc[i-1]

        skor = 0

        # Bullish signals
        if row['rsi'] < 35:   skor += 1
        if row['bb_pos'] < 0: skor += 1
        if (row['macd'] > row['signal'] and
                row_prev['macd'] <= row_prev['signal']): skor += 2
        if row['ema20'] > row['ema50']: skor += 1
        if row['vol_ratio'] > 1.5: skor += 1
        if row['momentum'] > 3: skor += 1

        # Bearish signals
        if row['rsi'] > 70:    skor -= 1
        if row['bb_pos'] > 1:  skor -= 1
        if (row['macd'] < row['signal'] and
                row_prev['macd'] >= row_prev['signal']): skor -= 2
        if row['momentum'] < -3: skor -= 1

        if skor >= 4:
            sinyal.iloc[i] = 1   # BUY
        elif skor <= -2:
            sinyal.iloc[i] = -1  # SELL (short atau exit)

    return sinyal

# ══════════════════════════════════════════════
# SIMULASI TRADING
# ══════════════════════════════════════════════

def simulasi_trading(df, sinyal, sl_mult=1.5, tp_mult=3.0,
                     modal=MODAL_AWAL, fee=FEE_RATE):
    """
    Simulasi trading berdasarkan sinyal.
    Return: list trade results + statistik
    """
    trades   = []
    saldo    = modal
    posisi   = None   # None = tidak ada posisi
    equity   = [modal]

    for i in range(len(df)):
        row   = df.iloc[i]
        sig   = sinyal.iloc[i]
        harga = row['close']
        atr   = row['atr']

        if posisi is None:
            # Cek sinyal BUY
            if sig == 1:
                sl  = harga - (atr * sl_mult)
                tp  = harga + (atr * tp_mult)
                qty = (saldo * 0.95) / harga  # Pakai 95% saldo
                cost = qty * harga * (1 + fee + SLIPPAGE)

                if cost <= saldo:
                    posisi = {
                        "entry"  : harga,
                        "sl"     : sl,
                        "tp"     : tp,
                        "qty"    : qty,
                        "idx"    : i,
                        "waktu"  : df.index[i]
                    }
                    saldo -= cost

        else:
            # Cek SL/TP
            hit_tp = harga >= posisi["tp"]
            hit_sl = harga <= posisi["sl"]
            timeout = (i - posisi["idx"]) > 72  # Max hold 72 candle

            if hit_tp or hit_sl or timeout:
                if hit_tp:
                    exit_harga = posisi["tp"]
                    alasan     = "TP"
                elif hit_sl:
                    exit_harga = posisi["sl"]
                    alasan     = "SL"
                else:
                    exit_harga = harga
                    alasan     = "TIMEOUT"

                revenue    = posisi["qty"] * exit_harga * (1 - fee - SLIPPAGE)
                profit_usd = revenue - (posisi["qty"] * posisi["entry"])
                profit_pct = (exit_harga - posisi["entry"]) / posisi["entry"] * 100
                saldo     += revenue

                trades.append({
                    "waktu_entry": posisi["waktu"],
                    "waktu_exit" : df.index[i],
                    "entry"      : posisi["entry"],
                    "exit"       : exit_harga,
                    "profit_pct" : round(profit_pct, 3),
                    "profit_usd" : round(profit_usd, 2),
                    "alasan"     : alasan
                })
                posisi = None

        equity.append(saldo + (posisi["qty"] * harga
                      if posisi else 0))

    return trades, equity, saldo

# ══════════════════════════════════════════════
# HITUNG STATISTIK BACKTEST
# ══════════════════════════════════════════════

def hitung_stats_backtest(trades, equity, modal_awal=MODAL_AWAL):
    """Hitung statistik komprehensif hasil backtest"""
    if not trades:
        return None

    df_trades = pd.DataFrame(trades)
    menang    = df_trades[df_trades['profit_pct'] > 0]
    kalah     = df_trades[df_trades['profit_pct'] <= 0]

    total_profit = df_trades['profit_usd'].sum()
    win_rate     = len(menang) / len(df_trades) * 100
    avg_win      = menang['profit_pct'].mean() if len(menang) > 0 else 0
    avg_loss     = kalah['profit_pct'].mean() if len(kalah) > 0 else 0
    profit_factor = (
        abs(menang['profit_pct'].sum()) /
        abs(kalah['profit_pct'].sum())
        if len(kalah) > 0 and kalah['profit_pct'].sum() != 0
        else float('inf')
    )

    # Max drawdown
    equity_arr = np.array(equity)
    peak       = np.maximum.accumulate(equity_arr)
    drawdown   = (equity_arr - peak) / peak * 100
    max_dd     = drawdown.min()

    # Return total
    modal_akhir  = equity[-1] if equity else modal_awal
    return_total = (modal_akhir - modal_awal) / modal_awal * 100

    # Sharpe ratio (simplified)
    returns    = pd.Series(equity).pct_change().dropna()
    sharpe     = (returns.mean() / returns.std() * np.sqrt(252)
                  if returns.std() > 0 else 0)

    # Per exit reason
    per_alasan = df_trades.groupby('alasan')['profit_pct'].agg(['count','sum','mean'])

    return {
        "n_trade"       : len(df_trades),
        "n_menang"      : len(menang),
        "n_kalah"       : len(kalah),
        "win_rate"      : round(win_rate, 1),
        "total_profit"  : round(total_profit, 2),
        "return_pct"    : round(return_total, 2),
        "avg_win"       : round(avg_win, 2),
        "avg_loss"      : round(avg_loss, 2),
        "profit_factor" : round(profit_factor, 2),
        "max_drawdown"  : round(max_dd, 2),
        "sharpe_ratio"  : round(sharpe, 2),
        "modal_awal"    : modal_awal,
        "modal_akhir"   : round(modal_akhir, 2),
        "best_trade"    : round(df_trades['profit_pct'].max(), 2),
        "worst_trade"   : round(df_trades['profit_pct'].min(), 2),
        "per_alasan"    : per_alasan.to_dict()
    }

# ══════════════════════════════════════════════
# FUNGSI UTAMA BACKTEST
# ══════════════════════════════════════════════

def jalankan_backtest(client, symbol, interval="1h",
                      hari=90, kirim_telegram=None):
    """
    Jalankan backtest lengkap dan kirim laporan ke Telegram.
    """
    print(f"\n📊 Backtesting {symbol} ({interval}, {hari} hari)...")

    if kirim_telegram:
        kirim_telegram(
            f"📊 <b>Backtesting dimulai</b>\n\n"
            f"💎 Symbol  : {symbol}\n"
            f"⏰ Interval: {interval}\n"
            f"📅 Periode : {hari} hari\n"
            f"💰 Modal   : ${MODAL_AWAL:,}\n"
            f"🔄 Sedang memproses..."
        )

    # 1. Ambil data
    df = get_data_historis(client, symbol, interval, hari)
    if df is None or len(df) < 100:
        msg = f"⚠️ Data tidak cukup untuk backtest {symbol}"
        print(f"  {msg}")
        if kirim_telegram: kirim_telegram(msg)
        return None

    # 2. Hitung indikator
    df = hitung_indikator_bt(df)

    # 3. Generate sinyal
    sinyal = generate_sinyal(df)
    n_buy  = (sinyal == 1).sum()
    print(f"  📈 Sinyal: {n_buy} BUY ditemukan")

    # 4. Simulasi
    trades, equity, modal_akhir = simulasi_trading(df, sinyal)

    if not trades:
        msg = f"⚠️ Tidak ada trade terjadi dalam backtest {symbol}"
        print(f"  {msg}")
        if kirim_telegram: kirim_telegram(msg)
        return None

    # 5. Statistik
    stats = hitung_stats_backtest(trades, equity)
    if not stats:
        return None

    print(f"  ✅ Selesai: {stats['n_trade']} trade, "
          f"Return: {stats['return_pct']:+.1f}%, "
          f"WR: {stats['win_rate']:.0f}%")

    # 6. Kirim laporan
    if kirim_telegram:
        em_return = "📈" if stats['return_pct'] >= 0 else "📉"
        pesan = (
            f"📊 <b>Hasil Backtest - {symbol}</b>\n"
            f"{'─'*30}\n\n"
            f"⏰ Periode   : {hari} hari ({interval})\n"
            f"💰 Modal     : ${stats['modal_awal']:,} → "
            f"<b>${stats['modal_akhir']:,.0f}</b>\n"
            f"{em_return} Return   : <b>{stats['return_pct']:+.2f}%</b>\n\n"
            f"📈 <b>Statistik Trade:</b>\n"
            f"  🔢 Total trade  : {stats['n_trade']}\n"
            f"  ✅ Win rate     : <b>{stats['win_rate']:.1f}%</b> "
            f"({stats['n_menang']}W/{stats['n_kalah']}L)\n"
            f"  📊 Profit factor: {stats['profit_factor']:.2f}\n"
            f"  📉 Max drawdown : {stats['max_drawdown']:.2f}%\n"
            f"  📐 Sharpe ratio : {stats['sharpe_ratio']:.2f}\n\n"
            f"  ✅ Avg win  : +{stats['avg_win']:.2f}%\n"
            f"  ❌ Avg loss : {stats['avg_loss']:.2f}%\n"
            f"  🏆 Best     : +{stats['best_trade']:.2f}%\n"
            f"  💸 Worst    : {stats['worst_trade']:.2f}%\n"
        )
        kirim_telegram(pesan)

    return stats

def backtest_semua_koin(client, koin_list, kirim_telegram=None):
    """Backtest semua koin dan kirim ringkasan"""
    hasil_semua = []
    for symbol in koin_list[:5]:  # Batasi 5 koin
        stats = jalankan_backtest(client, symbol,
                                   kirim_telegram=None)  # Jangan kirim per koin
        if stats:
            hasil_semua.append({"symbol": symbol, **stats})
        time.sleep(2)  # Rate limit

    if not hasil_semua or not kirim_telegram:
        return hasil_semua

    # Kirim ringkasan
    hasil_semua.sort(key=lambda x: x['return_pct'], reverse=True)
    pesan = "🏆 <b>Ringkasan Backtest Semua Koin</b>\n" + "─"*30 + "\n\n"
    for h in hasil_semua:
        em = "📈" if h['return_pct'] >= 0 else "📉"
        pesan += (
            f"{em} <b>{h['symbol']}</b>: {h['return_pct']:+.1f}% | "
            f"WR:{h['win_rate']:.0f}% | DD:{h['max_drawdown']:.1f}%\n"
        )

    kirim_telegram(pesan)
    return hasil_semua