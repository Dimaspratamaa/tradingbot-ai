# ============================================
# ML AUTO RETRAINER v1.1 - FIXED
# Retrain model ML setiap minggu
# FIX: Stop spam, class balance check,
#      persist state ke file
# ============================================

import json
import os
import time
import joblib
import numpy as np
import pandas as pd
from datetime import datetime

# ── KONFIGURASI ───────────────────────────────
RETRAIN_INTERVAL_HARI = 7
MIN_TRADE_RETRAIN     = 30   # Minimal 30 trade
MIN_PROFIT_TRADE      = 5    # Minimal 5 trade profit
MIN_LOSS_TRADE        = 5    # Minimal 5 trade loss
RETRAIN_STATE_FILE    = "retrain_state.json"

# ── STATE (persist ke file) ───────────────────
_state = {"tanggal": None, "waktu": 0}

def _load_state():
    global _state
    try:
        if os.path.exists(RETRAIN_STATE_FILE):
            with open(RETRAIN_STATE_FILE, "r") as f:
                _state = json.load(f)
    except:
        pass

def _save_state():
    try:
        with open(RETRAIN_STATE_FILE, "w") as f:
            json.dump(_state, f)
    except:
        pass

_load_state()

# ══════════════════════════════════════════════
# CEK JADWAL (DIPANGGIL TIAP SIKLUS)
# ══════════════════════════════════════════════

def cek_jadwal_retrain(client, kirim_telegram):
    """
    Entry point utama — dipanggil tiap siklus.
    TIDAK akan spam Telegram jika data belum siap.
    """
    global _state
    sekarang     = time.time()
    tanggal_hari = datetime.now().strftime("%Y-%m-%d")

    # Sudah retrain hari ini → skip
    if _state.get("tanggal") == tanggal_hari:
        return False

    # Belum 7 hari sejak retrain terakhir → skip
    waktu_terakhir = _state.get("waktu", 0)
    if waktu_terakhir > 0:
        selisih_hari = (sekarang - waktu_terakhir) / 86400
        if selisih_hari < RETRAIN_INTERVAL_HARI:
            return False

    # ── Cek data SEBELUM notif apapun ke Telegram ──
    cek = _cek_data_cukup()
    if not cek["cukup"]:
        # Simpan tanggal agar tidak coba lagi hari ini
        _state["tanggal"] = tanggal_hari
        _state["waktu"]   = sekarang
        _save_state()
        print(f"  ⏳ Retrain ditunda: {cek['alasan']}")
        return False  # SILENT — tidak kirim ke Telegram

    # Data cukup → jalankan retrain
    print(f"\n🧠 Data siap untuk retrain! ({cek['n_trade']} trade)")
    sukses = _jalankan_retrain(client, kirim_telegram, cek)

    _state["tanggal"] = tanggal_hari
    _state["waktu"]   = sekarang
    _save_state()
    return sukses

# ══════════════════════════════════════════════
# CEK DATA
# ══════════════════════════════════════════════

def _cek_data_cukup():
    """Cek apakah data riwayat trade cukup untuk retrain"""
    if not os.path.exists("riwayat_trade.json"):
        return {"cukup": False, "alasan": "File riwayat tidak ada", "n_trade": 0}

    try:
        with open("riwayat_trade.json", "r") as f:
            riwayat = json.load(f)
    except:
        return {"cukup": False, "alasan": "Gagal baca riwayat", "n_trade": 0}

    n_total  = len(riwayat)
    n_profit = sum(1 for t in riwayat if t.get("profit_pct", 0) > 0)
    n_loss   = n_total - n_profit

    if n_total < MIN_TRADE_RETRAIN:
        return {
            "cukup": False,
            "alasan": f"Trade {n_total}/{MIN_TRADE_RETRAIN}",
            "n_trade": n_total
        }
    if n_profit < MIN_PROFIT_TRADE:
        return {
            "cukup": False,
            "alasan": f"Trade profit hanya {n_profit}/{MIN_PROFIT_TRADE}",
            "n_trade": n_total
        }
    if n_loss < MIN_LOSS_TRADE:
        return {
            "cukup": False,
            "alasan": f"Trade loss hanya {n_loss}/{MIN_LOSS_TRADE}",
            "n_trade": n_total
        }

    return {
        "cukup"   : True,
        "n_trade" : n_total,
        "n_profit": n_profit,
        "n_loss"  : n_loss,
        "alasan"  : "OK"
    }

# ══════════════════════════════════════════════
# HITUNG FITUR TEKNIKAL
# ══════════════════════════════════════════════

def _hitung_fitur(df):
    """Hitung 14 fitur teknikal dari dataframe"""
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
        sig   = macd.ewm(span=9, adjust=False).mean()
        hist  = macd - sig

        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        bb_w  = (std20 * 4 / sma20).iloc[-1]
        bb_p  = ((close - (sma20 - std20*2)) / (std20*4)).iloc[-1]

        tr   = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs()
        ], axis=1).max(axis=1)
        atr_pct = (tr.rolling(14).mean() / close * 100).iloc[-1]

        vol_r = (volume / volume.rolling(20).mean()).iloc[-1]

        ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
        ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
        ema_d = (ema20 - ema50) / close.iloc[-1] * 100

        m3  = close.pct_change(3).iloc[-1]  * 100
        m7  = close.pct_change(7).iloc[-1]  * 100
        m14 = close.pct_change(14).iloc[-1] * 100

        body = abs(close.iloc[-1] - df['open'].iloc[-1]) / close.iloc[-1] * 100
        cdir = 1 if close.iloc[-1] > df['open'].iloc[-1] else 0

        # Validasi nilai
        fitur = [rsi, macd.iloc[-1], sig.iloc[-1], hist.iloc[-1],
                 bb_w, bb_p, atr_pct, vol_r, ema_d,
                 m3, m7, m14, body, cdir]

        if any(np.isnan(f) or np.isinf(f) for f in fitur):
            return None

        return fitur
    except:
        return None

# ══════════════════════════════════════════════
# BUAT DATASET
# ══════════════════════════════════════════════

def _buat_dataset(client):
    """Buat dataset X, y dari riwayat trade"""
    with open("riwayat_trade.json", "r") as f:
        riwayat = json.load(f)

    X_list = []
    y_list = []

    for trade in riwayat:
        try:
            symbol = trade.get("symbol", "")
            if not symbol:
                continue

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

            fitur = _hitung_fitur(df)
            if fitur is None:
                continue

            label = 1 if trade.get("profit_pct", 0) > 0 else 0
            X_list.append(fitur)
            y_list.append(label)

        except Exception:
            continue

    if not X_list:
        return None, None

    return np.array(X_list), np.array(y_list)

# ══════════════════════════════════════════════
# JALANKAN RETRAIN
# ══════════════════════════════════════════════

def _jalankan_retrain(client, kirim_telegram, info_data):
    """Retrain model dengan data yang sudah tervalidasi"""
    kirim_telegram(
        "🧠 <b>Auto Retrain ML dimulai!</b>\n\n"
        f"📊 Dataset  : {info_data['n_trade']} trade\n"
        f"  ✅ Profit : {info_data['n_profit']}\n"
        f"  ❌ Loss   : {info_data['n_loss']}\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    try:
        X, y = _buat_dataset(client)
        if X is None or len(X) < MIN_TRADE_RETRAIN:
            print("  ⚠️  Dataset kosong setelah proses fitur")
            return False

        # Cek ulang balance setelah proses
        n_p = int(sum(y))
        n_l = len(y) - n_p
        if n_p < MIN_PROFIT_TRADE or n_l < MIN_LOSS_TRADE:
            print(f"  ⚠️  Class tidak balance setelah proses ({n_p}/{n_l})")
            return False

        from sklearn.ensemble import RandomForestClassifier
        from sklearn.preprocessing import StandardScaler
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import accuracy_score

        # Split tanpa stratify jika class terlalu kecil
        min_class = min(n_p, n_l)
        use_stratify = min_class >= 4

        X_train, X_test, y_train, y_test = train_test_split(
            X, y,
            test_size=0.2,
            random_state=42,
            stratify=y if use_stratify else None
        )

        scaler = StandardScaler()
        X_tr   = scaler.fit_transform(X_train)
        X_te   = scaler.transform(X_test)

        model = RandomForestClassifier(
            n_estimators=100,
            max_depth=6,
            min_samples_leaf=3,
            class_weight='balanced',  # ← Handle imbalanced class
            random_state=42
        )
        model.fit(X_tr, y_train)
        akurasi = accuracy_score(y_test, model.predict(X_te))

        # Cek akurasi model lama
        akurasi_lama = 0.0
        try:
            m_lama = joblib.load("model_ml.pkl")
            s_lama = joblib.load("scaler_ml.pkl")
            akurasi_lama = accuracy_score(
                y_test, m_lama.predict(s_lama.transform(X_test))
            )
        except:
            pass

        nama_fitur = [
            'rsi','macd','macd_signal','macd_hist',
            'bb_width','bb_pos','atr_pct','vol_ratio',
            'ema_diff','momentum_3','momentum_7','momentum_14',
            'candle_body','candle_dir'
        ]

        if akurasi >= akurasi_lama or akurasi_lama == 0:
            joblib.dump(model,      "model_ml.pkl")
            joblib.dump(scaler,     "scaler_ml.pkl")
            joblib.dump(nama_fitur, "features_ml.pkl")
            status = "✅ Model diperbarui!"
        else:
            status = "ℹ️ Model lama dipertahankan"

        kirim_telegram(
            f"🧠 <b>Retrain ML Selesai!</b>\n\n"
            f"🎯 Akurasi baru  : {akurasi:.1%}\n"
            f"📉 Akurasi lama  : {akurasi_lama:.1%}\n"
            f"📊 Data dipakai  : {len(X)} sampel\n\n"
            f"{status}\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return True

    except Exception as e:
        print(f"  ❌ Retrain error: {e}")
        # Kirim error tapi HANYA sekali, tidak berulang
        kirim_telegram(
            f"⚠️ <b>Retrain error (akan coba lagi 7 hari)</b>\n"
            f"<code>{str(e)[:150]}</code>"
        )
        return False