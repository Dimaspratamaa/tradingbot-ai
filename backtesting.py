# ============================================
# BACKTESTING ENGINE v2.0 — Quant Edition
# Menggunakan 98 fitur dari feature_engineering
# + Walk-forward validation
# + Multiple strategi comparison
# ============================================

import pandas as pd
import numpy as np
import warnings
warnings.filterwarnings("ignore")
from datetime import datetime, timedelta

MODAL_AWAL = 1000.0
FEE_RATE   = 0.001
SLIPPAGE   = 0.0005


def get_data_historis(client, symbol, interval, hari=90):
    try:
        limit  = min(1000, hari * 24)
        klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
        df     = pd.DataFrame(klines, columns=[
            "time","open","high","low","close","volume",
            "ct","qv","n","tb","tq","i"])
        for c in ["open","high","low","close","volume"]:
            df[c] = df[c].astype(float)
        df["time"] = pd.to_datetime(df["time"], unit="ms")
        df = df.set_index("time")
        print(f"  Data: {len(df)} candle")
        return df
    except Exception as e:
        print(f"  Data error: {e}")
        return None


def hitung_indikator_bt(df):
    """Hitung indikator dasar untuk sinyal sederhana."""
    d = df.copy()
    delta = d["close"].diff()
    gain  = delta.where(delta>0,0).rolling(14).mean()
    loss  = (-delta.where(delta<0,0)).rolling(14).mean()
    d["rsi"]    = 100 - 100/(1+gain/loss)
    d["ema20"]  = d["close"].ewm(span=20,adjust=False).mean()
    d["ema50"]  = d["close"].ewm(span=50,adjust=False).mean()
    ema12       = d["close"].ewm(span=12,adjust=False).mean()
    ema26       = d["close"].ewm(span=26,adjust=False).mean()
    d["macd"]   = ema12 - ema26
    d["signal"] = d["macd"].ewm(span=9,adjust=False).mean()
    sma20       = d["close"].rolling(20).mean()
    std20       = d["close"].rolling(20).std()
    d["bb_pos"] = (d["close"] - (sma20-2*std20)) / (4*std20+1e-10)
    d["vol_ratio"] = d["volume"] / d["volume"].rolling(20).mean()
    d["momentum"]  = d["close"].pct_change(3)*100
    return d.dropna()


def generate_sinyal_quant(df, min_skor=7, window=80):
    """Generate sinyal menggunakan 98 fitur quant."""
    try:
        from feature_engineering import compute_all_features
        signals = pd.Series(0, index=df.index)
        scores  = pd.Series(0.0, index=df.index)

        for i in range(window, len(df)):
            slice_df = df.iloc[max(0,i-200):i+1]
            try:
                feat, _ = compute_all_features(slice_df)
                if not feat:
                    continue
                skor = 0
                if feat.get("rsi_14",50) < 35:         skor += 2
                elif feat.get("rsi_14",50) < 45:        skor += 1
                if feat.get("rsi_14",50) > 70:          skor -= 2
                if feat.get("macd_12_26_hist",0) > 0:   skor += 1
                if feat.get("macd_12_26_cross",0) == 1: skor += 2
                if feat.get("ema_stack_bull",0):         skor += 2
                if feat.get("adx_bull",0):               skor += 1
                if feat.get("ichi_above_cloud",0):       skor += 1
                if feat.get("vol_ratio_20",1) > 1.5:    skor += 1
                if feat.get("mfi_14",50) < 25:           skor += 1
                if feat.get("obv_slope",0) > 0:          skor += 1
                if feat.get("bb_pos",0.5) < 0.2:        skor += 1
                if feat.get("bb_squeeze",0):              skor += 1
                H = feat.get("hurst_20",0.5)
                if H > 0.6: skor += 1
                if feat.get("hammer",0):        skor += 1
                if feat.get("bull_engulf",0):   skor += 2
                if feat.get("shooting_star",0): skor -= 1
                if feat.get("bear_engulf",0):   skor -= 2
                mtf = feat.get("mtf_alignment",0.5)
                if mtf >= 0.67: skor += 2
                elif mtf <= 0.33: skor -= 1
                scores.iloc[i] = skor
                if skor >= min_skor:   signals.iloc[i] = 1
                elif skor <= -3:       signals.iloc[i] = -1
            except Exception:
                continue

        n_buy = (signals==1).sum()
        print(f"  Sinyal quant: {n_buy} BUY dari {len(df)-window} candle")
        return signals, scores

    except ImportError:
        print("  ⚠️  feature_engineering tidak tersedia, pakai sinyal sederhana")
        return generate_sinyal_sederhana(df, min_skor=4)


def generate_sinyal_sederhana(df, min_skor=4):
    df2     = hitung_indikator_bt(df)
    signals = pd.Series(0, index=df.index)
    scores  = pd.Series(0.0, index=df.index)
    for i in range(1, len(df2)):
        row  = df2.iloc[i]
        prev = df2.iloc[i-1]
        skor = 0
        if row["rsi"] < 35:    skor += 2
        elif row["rsi"] < 45:  skor += 1
        if row["rsi"] > 70:    skor -= 2
        if row["bb_pos"] < 0.2: skor += 1
        if row["macd"] > row["signal"] and prev["macd"] <= prev["signal"]: skor += 2
        if row["ema20"] > row["ema50"]: skor += 1
        if row["vol_ratio"] > 1.5: skor += 1
        if row["momentum"] > 3: skor += 1
        if row["momentum"] < -3: skor -= 1
        scores.iloc[i] = skor
        if skor >= min_skor:  signals.iloc[i] = 1
        elif skor <= -2:      signals.iloc[i] = -1
    n_buy = (signals==1).sum()
    print(f"  Sinyal sederhana: {n_buy} BUY")
    return signals, scores


def simulasi_trading(df, signals, scores=None,
                     modal=MODAL_AWAL, fee=FEE_RATE):
    trades  = []
    saldo   = modal
    equity  = [modal]
    posisi  = None
    max_hold= 72

    for i in range(1, len(df)):
        candle   = df.iloc[i]
        harga    = float(candle["close"])
        high_c   = float(candle["high"])
        low_c    = float(candle["low"])
        sig      = int(signals.iloc[i])
        skor_now = float(scores.iloc[i]) if scores is not None else 0

        if posisi:
            hold   = i - posisi["entry_idx"]
            pl_pct = (harga - posisi["entry"]) / posisi["entry"] * 100

            # Update trailing
            if pl_pct > 1.5 and harga > posisi.get("peak",0):
                posisi["peak"]     = harga
                posisi["trail_sl"] = harga * 0.99

            exit_h = None; exit_r = None
            if low_c  <= posisi["sl"]:                       exit_h=posisi["sl"];       exit_r="SL"
            elif posisi.get("trail_sl") and low_c<=posisi["trail_sl"]: exit_h=posisi["trail_sl"]; exit_r="TRAIL"
            elif high_c >= posisi["tp"]:                     exit_h=posisi["tp"];       exit_r="TP"
            elif hold   >= max_hold:                         exit_h=harga;              exit_r="TIME"
            elif sig == -1:                                  exit_h=harga*(1-SLIPPAGE); exit_r="SIGNAL"

            if exit_h:
                pl    = (exit_h-posisi["entry"])/posisi["entry"]*100
                pl_usd= posisi["modal"]*(pl/100)
                fees  = posisi["modal"]*fee*2
                saldo+= posisi["modal"]+pl_usd-fees
                trades.append({
                    "entry_time" : posisi["entry_time"],
                    "exit_time"  : str(df.index[i])[:16],
                    "symbol"     : "BT",
                    "entry"      : posisi["entry"],
                    "exit"       : exit_h,
                    "profit_pct" : round(pl, 4),
                    "profit_usd" : round(pl_usd-fees, 4),
                    "alasan"     : exit_r,
                    "hold_candle": hold,
                    "skor"       : posisi["skor"],
                })
                posisi = None

        if posisi is None and sig==1 and saldo>20:
            entry_h = harga*(1+SLIPPAGE)
            # Dynamic ATR-based SL/TP
            atr_h   = df["high"].iloc[max(0,i-14):i].max()
            atr_l   = df["low"].iloc[max(0,i-14):i].min()
            atr_pct = (atr_h-atr_l)/entry_h*100
            sl_pct  = max(1.0, min(atr_pct*1.5, 5.0))
            tp_pct  = sl_pct*2.5
            modal_t = min(saldo*0.95, modal*0.33)
            saldo  -= modal_t + modal_t*fee
            posisi  = {
                "entry"      : entry_h,
                "entry_time" : str(df.index[i])[:16],
                "entry_idx"  : i,
                "sl"         : entry_h*(1-sl_pct/100),
                "tp"         : entry_h*(1+tp_pct/100),
                "trail_sl"   : None,
                "peak"       : entry_h,
                "modal"      : modal_t,
                "skor"       : skor_now,
            }

        equity.append(saldo+(posisi["modal"]*(harga/posisi["entry"]) if posisi else 0))

    if posisi:
        h_last = float(df["close"].iloc[-1])
        pl     = (h_last-posisi["entry"])/posisi["entry"]*100
        pl_usd = posisi["modal"]*(pl/100)
        saldo += posisi["modal"]+pl_usd
        trades.append({"entry_time":posisi["entry_time"],"exit_time":str(df.index[-1])[:16],
                       "symbol":"BT","entry":posisi["entry"],"exit":h_last,
                       "profit_pct":round(pl,4),"profit_usd":round(pl_usd,4),
                       "alasan":"END","hold_candle":len(df)-posisi["entry_idx"],
                       "skor":posisi["skor"]})

    return trades, equity, saldo


def hitung_stats_backtest(trades, equity, modal_awal=MODAL_AWAL):
    if not trades: return None
    profits   = [t["profit_pct"] for t in trades]
    profits_u = [t["profit_usd"]  for t in trades]
    menang    = [t for t in trades if t["profit_pct"]>0]
    kalah     = [t for t in trades if t["profit_pct"]<=0]
    arr       = np.array(profits)

    wr    = len(menang)/len(trades)*100
    aw    = np.mean([t["profit_pct"] for t in menang]) if menang else 0
    al    = np.mean([t["profit_pct"] for t in kalah])  if kalah  else 0
    gp    = sum(t["profit_pct"] for t in menang)
    gl    = abs(sum(t["profit_pct"] for t in kalah))
    pf    = gp/gl if gl>0 else 99.0
    exp   = (len(menang)/len(trades)*aw)+(len(kalah)/len(trades)*al)

    eq_arr = np.array(equity)
    peak   = np.maximum.accumulate(eq_arr)
    dd     = (eq_arr-peak)/peak*100
    max_dd = float(np.min(dd))
    sharpe = float(np.mean(arr)/(np.std(arr)+1e-10)*np.sqrt(252))
    calmar = (sum(profits)/abs(max_dd)) if max_dd<0 else 99.0

    exit_r = {}
    for t in trades:
        r = t.get("alasan","?")
        exit_r[r] = exit_r.get(r,0)+1

    modal_akhir = equity[-1] if equity else modal_awal
    return_pct  = (modal_akhir-modal_awal)/modal_awal*100

    return {
        "n_trade"       : len(trades),
        "n_menang"      : len(menang),
        "n_kalah"       : len(kalah),
        "win_rate"      : round(wr,1),
        "return_pct"    : round(return_pct,2),
        "modal_awal"    : modal_awal,
        "modal_akhir"   : round(modal_akhir,2),
        "profit_total"  : round(sum(profits_u),2),
        "avg_win"       : round(aw,2),
        "avg_loss"      : round(al,2),
        "profit_factor" : round(pf,2),
        "expectancy"    : round(exp,3),
        "max_drawdown"  : round(max_dd,2),
        "sharpe_ratio"  : round(sharpe,3),
        "calmar_ratio"  : round(calmar,2),
        "avg_hold_h"    : round(np.mean([t.get("hold_candle",0) for t in trades]),1),
        "best_trade"    : round(max(profits),2),
        "worst_trade"   : round(min(profits),2),
        "exit_reasons"  : exit_r,
        "trades"        : trades[-10:],
    }


def walk_forward_backtest(client, symbol, interval="1h", n_splits=4):
    print(f"\n  📊 Walk-Forward: {symbol}")
    df = get_data_historis(client, symbol, interval, hari=180)
    if df is None or len(df)<200: return None

    n         = len(df)
    fold_size = n//n_splits
    test_size = int(fold_size*0.25)
    train_size= fold_size-test_size
    all_stats = []

    for fold in range(n_splits):
        start = fold*fold_size
        mid   = start+train_size
        end   = min(start+fold_size, n)
        df_te = df.iloc[mid:end]
        if len(df_te)<20: continue
        try:
            sig, sc = generate_sinyal_quant(df_te, min_skor=7)
        except Exception:
            sig, sc = generate_sinyal_sederhana(df_te)
        trades, equity, _ = simulasi_trading(df_te, sig, sc)
        if not trades:
            print(f"  Fold {fold+1}: Tidak ada trade"); continue
        stats = hitung_stats_backtest(trades, equity)
        if stats:
            stats["fold"]    = fold+1
            stats["periode"] = f"{str(df_te.index[0])[:10]} → {str(df_te.index[-1])[:10]}"
            all_stats.append(stats)
            print(f"  Fold {fold+1} [{stats['periode']}]: "
                  f"{stats['n_trade']}T WR={stats['win_rate']:.0f}% "
                  f"Ret={stats['return_pct']:+.1f}%")

    if not all_stats: return None

    summary = {
        "symbol"        : symbol,
        "n_folds"       : len(all_stats),
        "avg_wr"        : round(np.mean([s["win_rate"]     for s in all_stats]),1),
        "avg_return"    : round(np.mean([s["return_pct"]   for s in all_stats]),2),
        "avg_dd"        : round(np.mean([s["max_drawdown"] for s in all_stats]),2),
        "avg_sharpe"    : round(np.mean([s["sharpe_ratio"] for s in all_stats]),3),
        "avg_pf"        : round(np.mean([s["profit_factor"]for s in all_stats]),2),
        "konsisten"     : all(s["return_pct"]>0 for s in all_stats),
        "folds"         : all_stats,
    }
    print(f"  Summary: WR={summary['avg_wr']}% Ret={summary['avg_return']:+.1f}% "
          f"Konsisten={'Ya' if summary['konsisten'] else 'Tidak'}")
    return summary


def jalankan_backtest(client, symbol, interval="1h",
                      hari=90, kirim_telegram=None, metode="quant"):
    print(f"\n📊 Backtest {symbol} ({interval}, {hari}H, {metode})...")

    if kirim_telegram:
        kirim_telegram(
            f"📊 <b>Backtest dimulai</b>\n"
            f"💎 {symbol} | {interval} | {hari} hari\n"
            f"🔬 Metode: {metode.upper()}\n🔄 Memproses..."
        )

    df = get_data_historis(client, symbol, interval, hari)
    if df is None or len(df)<100:
        if kirim_telegram: kirim_telegram(f"⚠️ Data tidak cukup untuk {symbol}")
        return None

    try:
        if metode=="quant":
            sig, sc = generate_sinyal_quant(df, min_skor=7)
        else:
            sig, sc = generate_sinyal_sederhana(df)
    except Exception as e:
        print(f"  ⚠️ Error sinyal: {e}")
        sig, sc = generate_sinyal_sederhana(df)

    trades, equity, _ = simulasi_trading(df, sig, sc)
    if not trades:
        if kirim_telegram: kirim_telegram(f"⚠️ Tidak ada trade di {symbol}")
        return None

    stats = hitung_stats_backtest(trades, equity)
    if not stats: return None

    print(f"  ✅ {stats['n_trade']}T | Ret:{stats['return_pct']:+.1f}% | "
          f"WR:{stats['win_rate']:.0f}% | DD:{stats['max_drawdown']:.1f}%")

    if kirim_telegram:
        em     = "📈" if stats["return_pct"]>=0 else "📉"
        layak  = (stats["win_rate"]>=50 and stats["profit_factor"]>=1.3
                  and stats["max_drawdown"]>=-15)
        eval_s = "✅ LAYAK" if layak else "⚠️ PERLU REVIEW"
        exit_s = " | ".join(f"{k}:{v}" for k,v in stats["exit_reasons"].items())
        sep = "─"*28
        pesan_bt = (
            f"📊 <b>Backtest — {symbol}</b>\n{sep}\n"
            f"📅 {hari} hari ({interval}) | {metode.upper()}\n\n"
            f"💰 ${MODAL_AWAL:,.0f} → <b>${stats['modal_akhir']:,.0f}</b>\n"
            f"{em} Return: <b>{stats['return_pct']:+.2f}%</b>\n\n"
            f"  Trade    : {stats['n_trade']} ({stats['n_menang']}W/{stats['n_kalah']}L)\n"
            f"  Win rate : <b>{stats['win_rate']:.1f}%</b>\n"
            f"  PF       : {stats['profit_factor']:.2f}\n"
            f"  Expect   : {stats['expectancy']:.3f}%\n"
            f"  Max DD   : {stats['max_drawdown']:.2f}%\n"
            f"  Sharpe   : {stats['sharpe_ratio']:.3f}\n"
            f"  Avg hold : {stats['avg_hold_h']:.0f}H\n"
            f"  Exit: {exit_s}\n\n"
            f"🏁 <b>{eval_s}</b>"
        )
        kirim_telegram(pesan_bt)
    return stats


def backtest_semua_koin(client, koin_list,
                         kirim_telegram=None, metode="quant"):
    hasil = []
    koin_list = koin_list[:5]
    if kirim_telegram:
        kirim_telegram(
            f"📊 <b>Multi-Coin Backtest</b>\n"
            f"Koin: {', '.join(koin_list)}\n🔄 Proses..."
        )
    for sym in koin_list:
        try:
            s = jalankan_backtest(client, sym, "1h", 60, None, metode)
            if s:
                s["symbol"] = sym
                hasil.append(s)
        except Exception as e:
            print(f"  ⚠️ {sym}: {e}")

    if not hasil: return []
    hasil_sorted = sorted(hasil, key=lambda x: x["sharpe_ratio"], reverse=True)

    if kirim_telegram:
        sep   = "─"*26
        pesan = f"🏆 <b>Ranking Backtest (Sharpe)</b>\n{sep}\n\n"
        for i, s in enumerate(hasil_sorted, 1):
            em_r  = "🥇" if i==1 else "🥈" if i==2 else "🥉" if i==3 else f"{i}."
            pesan += (f"{em_r} <b>{s['symbol']}</b>: "
                      f"{s['return_pct']:+.1f}% WR={s['win_rate']:.0f}% "
                      f"Sharpe={s['sharpe_ratio']:.2f}\n")
        kirim_telegram(pesan)
    return hasil_sorted