# ============================================
# ML AUTO RETRAINER v1.2 - PERMANENT FIX
# - Tidak pernah spam Telegram
# - Validasi data sebelum training
# - Semua error ditangkap silent
# ============================================

import json, os, time, joblib
import numpy as np
import pandas as pd
from datetime import datetime

RETRAIN_INTERVAL_HARI = 7
MIN_TRADE_RETRAIN     = 30
MIN_PROFIT_TRADE      = 5
MIN_LOSS_TRADE        = 5
STATE_FILE            = "retrain_state.json"
_state                = {"tanggal": None, "waktu": 0}

def _load():
    global _state
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE) as f:
                _state = json.load(f)
    except: pass

def _save():
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(_state, f)
    except: pass

_load()

# ── CEK DATA ──────────────────────────────────
def _cek_data():
    if not os.path.exists("riwayat_trade.json"):
        return False, "File tidak ada", 0, 0, 0
    try:
        with open("riwayat_trade.json") as f:
            data = json.load(f)
    except:
        return False, "Gagal baca file", 0, 0, 0

    n      = len(data)
    n_win  = sum(1 for t in data if t.get("profit_pct", 0) > 0)
    n_loss = n - n_win

    if n < MIN_TRADE_RETRAIN:
        return False, f"Trade {n}/{MIN_TRADE_RETRAIN}", n, n_win, n_loss
    if n_win < MIN_PROFIT_TRADE:
        return False, f"Win {n_win}/{MIN_PROFIT_TRADE}", n, n_win, n_loss
    if n_loss < MIN_LOSS_TRADE:
        return False, f"Loss {n_loss}/{MIN_LOSS_TRADE}", n, n_win, n_loss

    return True, "OK", n, n_win, n_loss

# ── HITUNG FITUR ──────────────────────────────
def _fitur(df):
    try:
        c = df['close']; h = df['high']; l = df['low']; v = df['volume']
        d = c.diff()
        g = d.where(d>0,0).rolling(14).mean()
        ls = (-d.where(d<0,0)).rolling(14).mean()
        rsi = (100-(100/(1+g/ls))).iloc[-1]
        e12 = c.ewm(span=12,adjust=False).mean()
        e26 = c.ewm(span=26,adjust=False).mean()
        mac = e12-e26; sig = mac.ewm(span=9,adjust=False).mean()
        s20 = c.rolling(20).mean(); std = c.rolling(20).std()
        bbw = (std*4/s20).iloc[-1]
        bbp = ((c-(s20-std*2))/(std*4)).iloc[-1]
        tr  = pd.concat([h-l,(h-c.shift()).abs(),(l-c.shift()).abs()],axis=1).max(axis=1)
        atp = (tr.rolling(14).mean()/c*100).iloc[-1]
        vr  = (v/v.rolling(20).mean()).iloc[-1]
        e20 = c.ewm(span=20,adjust=False).mean().iloc[-1]
        e50 = c.ewm(span=50,adjust=False).mean().iloc[-1]
        ed  = (e20-e50)/c.iloc[-1]*100
        m3  = c.pct_change(3).iloc[-1]*100
        m7  = c.pct_change(7).iloc[-1]*100
        m14 = c.pct_change(14).iloc[-1]*100
        bd  = abs(c.iloc[-1]-df['open'].iloc[-1])/c.iloc[-1]*100
        cd  = 1 if c.iloc[-1]>df['open'].iloc[-1] else 0
        f = [rsi, mac.iloc[-1], sig.iloc[-1], (mac-sig).iloc[-1],
             bbw, bbp, atp, vr, ed, m3, m7, m14, bd, cd]
        return None if any(np.isnan(x) or np.isinf(x) for x in f) else f
    except:
        return None

# ── BUAT DATASET ─────────────────────────────
def _dataset(client):
    with open("riwayat_trade.json") as f:
        data = json.load(f)
    X, y = [], []
    for t in data:
        try:
            sym = t.get("symbol","")
            if not sym: continue
            klines = client.get_klines(symbol=sym,interval="1h",limit=100)
            df = pd.DataFrame(klines,columns=[
                'time','open','high','low','close','volume',
                'ct','qv','tr','tb','tq','ig'])
            for c in ['open','high','low','close','volume']:
                df[c] = df[c].astype(float)
            f = _fitur(df)
            if f is None: continue
            X.append(f); y.append(1 if t.get("profit_pct",0)>0 else 0)
        except: continue
    return (np.array(X), np.array(y)) if X else (None, None)

# ── RETRAIN ───────────────────────────────────
def _retrain(client, kirim_telegram, n, n_win, n_loss):
    kirim_telegram(
        "🧠 <b>Auto Retrain ML dimulai!</b>\n\n"
        f"📊 Dataset: {n} trade ({n_win} win / {n_loss} loss)\n"
        f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    try:
        X, y = _dataset(client)
        if X is None or len(X) < MIN_TRADE_RETRAIN:
            print("  ⚠️  Dataset kosong setelah proses fitur"); return False

        nw = int(sum(y)); nl = len(y)-nw
        if nw < MIN_PROFIT_TRADE or nl < MIN_LOSS_TRADE:
            print(f"  ⚠️  Class tidak balance ({nw}/{nl})"); return False

        from sklearn.ensemble import RandomForestClassifier
        from sklearn.preprocessing import StandardScaler
        from sklearn.model_selection import train_test_split
        from sklearn.metrics import accuracy_score

        use_strat = min(nw, nl) >= 4
        Xtr,Xte,ytr,yte = train_test_split(
            X, y, test_size=0.2, random_state=42,
            stratify=y if use_strat else None
        )
        sc = StandardScaler()
        Xtr_s = sc.fit_transform(Xtr)
        Xte_s = sc.transform(Xte)

        mdl = RandomForestClassifier(
            n_estimators=100, max_depth=6,
            min_samples_leaf=3, class_weight='balanced',
            random_state=42
        )
        mdl.fit(Xtr_s, ytr)
        acc = accuracy_score(yte, mdl.predict(Xte_s))

        acc_lama = 0.0
        try:
            m_lama = joblib.load("model_ml.pkl")
            s_lama = joblib.load("scaler_ml.pkl")
            acc_lama = accuracy_score(yte, m_lama.predict(s_lama.transform(Xte)))
        except: pass

        nama_fitur = [
            'rsi','macd','macd_signal','macd_hist',
            'bb_width','bb_pos','atr_pct','vol_ratio',
            'ema_diff','momentum_3','momentum_7','momentum_14',
            'candle_body','candle_dir'
        ]

        if acc >= acc_lama or acc_lama == 0:
            joblib.dump(mdl,       "model_ml.pkl")
            joblib.dump(sc,        "scaler_ml.pkl")
            joblib.dump(nama_fitur,"features_ml.pkl")
            status = "✅ Model diperbarui!"
        else:
            status = "ℹ️ Model lama dipertahankan"

        kirim_telegram(
            f"🧠 <b>Retrain Selesai!</b>\n\n"
            f"🎯 Akurasi baru  : {acc:.1%}\n"
            f"📉 Akurasi lama  : {acc_lama:.1%}\n"
            f"📊 Sampel        : {len(X)}\n\n"
            f"{status}\n"
            f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        return True

    except Exception as e:
        # Error ditangkap SILENT — tidak spam Telegram
        print(f"  ❌ Retrain error (silent): {e}")
        return False

# ── FUNGSI UTAMA ─────────────────────────────
def cek_jadwal_retrain(client, kirim_telegram):
    """Dipanggil tiap siklus — TIDAK PERNAH spam Telegram"""
    global _state
    sekarang     = time.time()
    tanggal_hari = datetime.now().strftime("%Y-%m-%d")

    # Sudah retrain hari ini
    if _state.get("tanggal") == tanggal_hari:
        return False

    # Belum 7 hari
    if _state.get("waktu",0) > 0:
        if (sekarang - _state["waktu"]) / 86400 < RETRAIN_INTERVAL_HARI:
            return False

    # Cek data DIAM-DIAM
    cukup, alasan, n, n_win, n_loss = _cek_data()
    _state["tanggal"] = tanggal_hari
    _state["waktu"]   = sekarang
    _save()

    if not cukup:
        print(f"  ⏳ Retrain ditunda (silent): {alasan}")
        return False  # TIDAK kirim ke Telegram

    return _retrain(client, kirim_telegram, n, n_win, n_loss)