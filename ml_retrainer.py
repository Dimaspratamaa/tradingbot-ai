# ============================================
# ML AUTO RETRAINER v1.0
# Retrain model ML setiap minggu
# dari data riwayat trade sendiri
# ============================================

import json
import os
import time
import joblib
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

RETRAIN_INTERVAL_HARI = 7     # Retrain setiap 7 hari
MIN_TRADE_RETRAIN     = 20    # Minimal 20 trade untuk retrain
_last_retrain = {"tanggal": None, "waktu": 0}

# ══════════════════════════════════════════════
# BUAT DATASET DARI RIWAYAT TRADE
# ══════════════════════════════════════════════

def buat_dataset_retrain(client, riwayat_file="riwayat_trade.json"):
    """
    Buat dataset training dari riwayat trade.
    Untuk setiap trade yang sudah closed:
    - Ambil data OHLCV pada saat entry
    - Hitung fitur teknikal
    - Label: 1 jika profit, 0 jika loss
    """
    if not os.path.exists(riwayat_file):
        print("  ⚠️  File riwayat tidak ditemukan")
        return None

    with open(riwayat_file, "r") as f:
        riwayat = json.load(f)

    if len(riwayat) < MIN_TRADE_RETRAIN:
        print(f"  ⚠️  Data kurang ({len(riwayat)} < {MIN_TRADE_RETRAIN})")
        return None

    print(f"  📊 Memproses {len(riwayat)} trade untuk retrain...")

    X_list = []
    y_list = []

    for trade in riwayat:
        try:
            symbol     = trade["symbol"]
            waktu_beli = trade["waktu_beli"]
            profit_pct = trade["profit_pct"]

            # Ambil data historis saat entry
            klines = client.get_klines(
                symbol=symbol,
                interval="1h",
                limit=100
            )

            df = pd.DataFrame(klines, columns=[
                'time','open','high','low','close','volume',
                'close_time','quote_vol','trades',
                'taker_base','taker_quote','ignore'
            ])
            for col in ['open','high','low','close','volume']:
                df[col] = df[col].astype(float)

            # Hitung fitur
            fitur = _hitung_fitur(df)
            if fitur is None:
                continue

            # Label: 1 = profit, 0 = loss
            label = 1 if profit_pct > 0 else 0

            X_list.append(fitur)
            y_list.append(label)

        except Exception as e:
            continue

    if len(X_list) < MIN_TRADE_RETRAIN:
        print(f"  ⚠️  Fitur berhasil dihitung: {len(X_list)}")
        return None

    X = np.array(X_list)
    y = np.array(y_list)

    print(f"  ✅ Dataset: {len(X)} sampel "
          f"({sum(y)} profit, {len(y)-sum(y)} loss)")
    return X, y

def _hitung_fitur(df):
    """Hitung fitur teknikal dari dataframe"""
    try:
        close = df['close']; high = df['high']
        low   = df['low'];   volume = df['volume']

        delta = close.diff()
        gain  = delta.where(delta > 0, 0).rolling(14).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi   = (100 - (100 / (1 + gain / loss))).iloc[-1]

        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()
        macd  = ema12 - ema26
        signal = macd.ewm(span=9, adjust=False).mean()
        macd_hist = macd - signal

        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        bb_width = (std20 * 4 / sma20).iloc[-1]
        bb_pos   = ((close - (sma20 - std20*2)) /
                    (std20*4)).iloc[-1]

        tr   = pd.concat([high-low, (high-close.shift()).abs(),
                          (low-close.shift()).abs()],axis=1).max(axis=1)
        atr  = tr.rolling(14).mean().iloc[-1]
        atr_pct = atr / close.iloc[-1] * 100

        vol_ratio = (volume / volume.rolling(20).mean()).iloc[-1]

        ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
        ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
        ema_diff = (ema20 - ema50) / close.iloc[-1] * 100

        mom3  = close.pct_change(3).iloc[-1] * 100
        mom7  = close.pct_change(7).iloc[-1] * 100
        mom14 = close.pct_change(14).iloc[-1] * 100

        candle_body = abs(close.iloc[-1] - df['open'].iloc[-1]) / close.iloc[-1] * 100
        candle_dir  = 1 if close.iloc[-1] > df['open'].iloc[-1] else 0

        return [
            rsi, macd.iloc[-1], signal.iloc[-1], macd_hist.iloc[-1],
            bb_width, bb_pos, atr_pct, vol_ratio, ema_diff,
            mom3, mom7, mom14, candle_body, candle_dir
        ]
    except:
        return None

# ══════════════════════════════════════════════
# RETRAIN MODEL
# ══════════════════════════════════════════════

def retrain_model(client, kirim_telegram):
    """
    Retrain model ML dengan data terbaru.
    Simpan model baru jika performance lebih baik.
    """
    print("\n🧠 Memulai proses retrain ML...")
    kirim_telegram(
        "🧠 <b>Auto Retrain ML dimulai!</b>\n\n"
        "📊 Memproses riwayat trade...\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    # Buat dataset
    dataset = buat_dataset_retrain(client)
    if dataset is None:
        kirim_telegram("⚠️ <b>Retrain gagal</b>: Data tidak cukup")
        return False

    X, y = dataset

    try:
        from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
        from sklearn.preprocessing import StandardScaler
        from sklearn.model_selection import cross_val_score, train_test_split
        from sklearn.metrics import accuracy_score, classification_report

        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y, test_size=0.2, random_state=42, stratify=y
        )

        # Scale fitur
        scaler_baru = StandardScaler()
        X_train_sc  = scaler_baru.fit_transform(X_train)
        X_test_sc   = scaler_baru.transform(X_test)

        # ── Model 1: Random Forest ──
        rf = RandomForestClassifier(
            n_estimators=200, max_depth=8,
            min_samples_leaf=3, random_state=42
        )
        rf.fit(X_train_sc, y_train)
        acc_rf = accuracy_score(y_test, rf.predict(X_test_sc))

        # ── Model 2: Gradient Boosting ──
        gb = GradientBoostingClassifier(
            n_estimators=150, learning_rate=0.1,
            max_depth=4, random_state=42
        )
        gb.fit(X_train_sc, y_train)
        acc_gb = accuracy_score(y_test, gb.predict(X_test_sc))

        # Pilih model terbaik
        if acc_rf >= acc_gb:
            model_baru = rf
            nama_model = "Random Forest"
            akurasi    = acc_rf
        else:
            model_baru = gb
            nama_model = "Gradient Boosting"
            akurasi    = acc_gb

        # Cross validation
        cv_scores = cross_val_score(
            model_baru, X_train_sc, y_train, cv=5
        )
        cv_mean = cv_scores.mean()

        # Cek akurasi model lama
        akurasi_lama = 0.0
        try:
            model_lama  = joblib.load("model_ml.pkl")
            scaler_lama = joblib.load("scaler_ml.pkl")
            X_test_lama = scaler_lama.transform(X_test)
            akurasi_lama = accuracy_score(y_test, model_lama.predict(X_test_lama))
        except:
            pass

        # Simpan jika lebih baik atau tidak ada model lama
        nama_fitur = [
            'rsi', 'macd', 'macd_signal', 'macd_hist',
            'bb_width', 'bb_pos', 'atr_pct', 'vol_ratio',
            'ema_diff', 'momentum_3', 'momentum_7', 'momentum_14',
            'candle_body', 'candle_dir'
        ]

        if akurasi > akurasi_lama or akurasi_lama == 0:
            # Backup model lama
            if os.path.exists("model_ml.pkl"):
                import shutil
                shutil.copy("model_ml.pkl", "model_ml_backup.pkl")
                shutil.copy("scaler_ml.pkl", "scaler_ml_backup.pkl")

            # Simpan model baru
            joblib.dump(model_baru, "model_ml.pkl")
            joblib.dump(scaler_baru, "scaler_ml.pkl")
            joblib.dump(nama_fitur, "features_ml.pkl")

            status = "✅ MODEL DIPERBARUI!"
            print(f"  ✅ Model baru disimpan! Akurasi: {akurasi:.2%}")
        else:
            status = "⚠️ Model lama dipertahankan (lebih akurat)"
            print(f"  ⚠️  Model lama lebih baik ({akurasi_lama:.2%} vs {akurasi:.2%})")

        # Update waktu retrain
        _last_retrain["tanggal"] = datetime.now().strftime("%Y-%m-%d")
        _last_retrain["waktu"]   = time.time()

        # Laporan ke Telegram
        kirim_telegram(
            f"🧠 <b>Retrain ML Selesai!</b>\n\n"
            f"📊 Dataset   : {len(X)} trade\n"
            f"🤖 Model     : {nama_model}\n"
            f"🎯 Akurasi   : {akurasi:.2%}\n"
            f"📈 CV Score  : {cv_mean:.2%} ± {cv_scores.std():.2%}\n"
            f"📉 Akurasi lama: {akurasi_lama:.2%}\n\n"
            f"{status}\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )

        return True

    except Exception as e:
        print(f"  ❌ Retrain error: {e}")
        kirim_telegram(f"❌ <b>Retrain Error!</b>\n\n<code>{str(e)[:200]}</code>")
        return False

# ══════════════════════════════════════════════
# CEK JADWAL RETRAIN
# ══════════════════════════════════════════════

def cek_jadwal_retrain(client, kirim_telegram):
    """
    Cek apakah sudah waktunya retrain.
    Dipanggil di setiap siklus bot.
    """
    sekarang     = time.time()
    tanggal_hari = datetime.now().strftime("%Y-%m-%d")

    # Retrain jika: sudah 7 hari sejak retrain terakhir
    sudah_waktunya = (
        _last_retrain["tanggal"] is None or
        sekarang - _last_retrain["waktu"] > RETRAIN_INTERVAL_HARI * 86400
    )

    if sudah_waktunya and _last_retrain["tanggal"] != tanggal_hari:
        print(f"\n🧠 Waktunya retrain ML (interval {RETRAIN_INTERVAL_HARI} hari)!")
        retrain_model(client, kirim_telegram)
        return True

    return False