# ============================================
# TRAIN MODEL v3.1 — Railway Edition
# Jalankan di Railway: railway run python train_model.py
#
# Yang dilakukan:
# 1. Ambil data historis dari Binance (Railway bisa akses)
# 2. Hitung 98 fitur quant (Phase 1)
# 3. Walk-forward validation 5-fold
# 4. Train XGBoost + GradientBoosting + RF + LSTM
# 5. Simpan model_ensemble.pkl
# ============================================

import os, sys, pathlib, time, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, str(pathlib.Path(__file__).parent))

# Load .env jika ada (lokal)
_env = pathlib.Path(__file__).parent / ".env"
if _env.exists():
    for _l in _env.read_text().splitlines():
        _l = _l.strip()
        if _l and not _l.startswith("#") and "=" in _l:
            _k, _v = _l.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

import ssl, urllib3
urllib3.disable_warnings()
ssl._create_default_https_context = ssl._create_unverified_context

print("=" * 60)
print("   TRAINING MODEL v3.1 — RAILWAY EDITION")
print("=" * 60)
print(f"   Waktu: {time.strftime('%Y-%m-%d %H:%M:%S')}")
print()

# ── CONNECT BINANCE ──────────────────────────
from binance.client import Client
API_KEY    = os.environ.get("BINANCE_API_KEY", "U0LiHucqGcPDj3L8bAHp0Qzfa9ocMxbEilQJeOihSwpmioNnl33WV4wyJcytSkkG")
API_SECRET = os.environ.get("BINANCE_API_SECRET", "pg412rXf0oSLFUqSn0914FCyYnJtZ32GCtBEwGPjT9UdawZz1BX2rVpxuwJmn0up")

if not API_KEY or not API_SECRET:
    print("❌ BINANCE_API_KEY / BINANCE_API_SECRET tidak ditemukan!")
    print("   Set di Railway Variables atau .env lokal")
    sys.exit(1)

try:
    client = Client(API_KEY, API_SECRET, testnet=False)
    client.ping()
    print("✅ Binance terkoneksi")
except Exception as e:
    print(f"❌ Binance error: {e}")
    sys.exit(1)

# ── KONFIGURASI ──────────────────────────────
SYMBOLS    = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
LIMIT      = 1000   # 1000 candle per simbol (lebih cepat dari 1500)
FORWARD    = 3      # prediksi 3 candle ke depan
TARGET_PCT = 0.008  # target profit 0.8%

import pandas as pd
import numpy as np
import joblib, json
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import roc_auc_score, accuracy_score
from sklearn.preprocessing import RobustScaler
from sklearn.utils.class_weight import compute_class_weight
from feature_engineering import compute_all_features
from ml_ensemble import (
    SimpleLSTM, EnsemblePredictor,
    save_ensemble, XGB_AVAILABLE, LGB_AVAILABLE
)

print(f"   XGBoost : {'tersedia' if XGB_AVAILABLE else 'tidak ada, pakai GradientBoosting'}")
print(f"   LightGBM: {'tersedia' if LGB_AVAILABLE else 'tidak ada, skip'}")
print()

# ── AMBIL DATA ───────────────────────────────
def get_df(symbol, interval, limit):
    klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(klines, columns=[
        "time","open","high","low","close","volume",
        "close_time","quote_vol","trades",
        "taker_base","taker_quote","ignore"])
    for col in ["open","high","low","close","volume"]:
        df[col] = df[col].astype(float)
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    return df.set_index("time")

print(f"📥 Mengambil data {len(SYMBOLS)} simbol...")
dfs_1h, dfs_4h, dfs_1d = {}, {}, {}
for sym in SYMBOLS:
    try:
        dfs_1h[sym] = get_df(sym, Client.KLINE_INTERVAL_1HOUR,  LIMIT)
        dfs_4h[sym] = get_df(sym, Client.KLINE_INTERVAL_4HOUR,  300)
        dfs_1d[sym] = get_df(sym, Client.KLINE_INTERVAL_1DAY,   150)
        print(f"  ✅ {sym}: {len(dfs_1h[sym])} candle 1H")
    except Exception as e:
        print(f"  ⚠️  {sym}: {e}")

# ── BUILD FEATURE MATRIX ─────────────────────
print(f"\n🔧 Building feature matrix...")
all_rows = []
WINDOW   = 80  # minimum window untuk compute features

for sym in SYMBOLS:
    if sym not in dfs_1h: continue
    df1h = dfs_1h[sym]
    df4h = dfs_4h.get(sym)
    df1d = dfs_1d.get(sym)
    n_rows = 0

    for i in range(WINDOW, len(df1h) - FORWARD):
        w1h = df1h.iloc[max(0, i-200):i+1]
        w4h = df4h.iloc[:max(1, i//4)] if df4h is not None else None
        w1d = df1d.iloc[:max(1, i//24)] if df1d is not None else None

        try:
            feat_dict, _ = compute_all_features(w1h, w4h, w1d)
        except Exception:
            continue
        if not feat_dict: continue

        future  = df1h["close"].iloc[i + FORWARD]
        current = df1h["close"].iloc[i]
        feat_dict["_target"] = int((future/current - 1) > TARGET_PCT)
        feat_dict["_symbol"] = sym
        all_rows.append(feat_dict)
        n_rows += 1

    print(f"  {sym}: {n_rows} sampel training")

df_feat = pd.DataFrame(all_rows)
print(f"\n📊 Total: {len(df_feat)} sampel")
print(f"   BUY(1): {df_feat['_target'].sum()} | HOLD(0): {(df_feat['_target']==0).sum()}")

if len(df_feat) < 100:
    print("❌ Data tidak cukup untuk training!")
    sys.exit(1)

# ── FILTER FITUR ─────────────────────────────
feature_cols = [c for c in df_feat.columns if not c.startswith("_")]
X_raw = df_feat[feature_cols].fillna(0).replace([np.inf,-np.inf], 0)
y     = df_feat["_target"]

# Hapus low-variance & high-correlation
low_var = X_raw.columns[X_raw.std() < 0.001].tolist()
X_raw   = X_raw.drop(columns=low_var)

corr  = X_raw.corr().abs()
upper = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
hc    = [c for c in upper.columns if any(upper[c] > 0.97)]
X_raw = X_raw.drop(columns=hc)

feature_names = X_raw.columns.tolist()
X = X_raw.values
print(f"   Fitur final: {len(feature_names)}")

# ── WALK-FORWARD VALIDATION ──────────────────
print(f"\n📈 Walk-forward validation (5 fold)...")
tscv = TimeSeriesSplit(n_splits=5)
cw_arr = compute_class_weight("balanced", classes=np.array([0,1]), y=y.values)
class_weights = {0: cw_arr[0], 1: cw_arr[1]}

all_aucs = {"rf": [], "xgb": [], "lstm": []}

for fold, (tr_idx, te_idx) in enumerate(tscv.split(X), 1):
    X_tr, X_te = X[tr_idx], X[te_idx]
    y_tr, y_te = y.values[tr_idx], y.values[te_idx]

    if len(np.unique(y_te)) < 2: continue

    sc = RobustScaler()
    X_tr_s = sc.fit_transform(X_tr)
    X_te_s = sc.transform(X_te)

    fold_aucs = {}

    # Random Forest
    try:
        rf = RandomForestClassifier(
            n_estimators=200, max_depth=10,
            min_samples_split=10, min_samples_leaf=5,
            max_features="sqrt", class_weight=class_weights,
            random_state=42, n_jobs=-1)
        rf.fit(X_tr_s, y_tr)
        auc = roc_auc_score(y_te, rf.predict_proba(X_te_s)[:,1])
        all_aucs["rf"].append(auc)
        fold_aucs["RF"] = auc
    except Exception as e:
        fold_aucs["RF"] = 0

    # XGBoost atau GradientBoosting
    try:
        if XGB_AVAILABLE:
            import xgboost as xgb
            xgb_model = xgb.XGBClassifier(
                n_estimators=200, max_depth=5,
                learning_rate=0.05, subsample=0.8,
                colsample_bytree=0.8, random_state=42,
                eval_metric="logloss", verbosity=0)
        else:
            xgb_model = GradientBoostingClassifier(
                n_estimators=150, max_depth=4,
                learning_rate=0.05, subsample=0.8, random_state=42)
        xgb_model.fit(X_tr_s, y_tr)
        auc = roc_auc_score(y_te, xgb_model.predict_proba(X_te_s)[:,1])
        all_aucs["xgb"].append(auc)
        fold_aucs["XGB"] = auc
    except Exception as e:
        fold_aucs["XGB"] = 0

    # LSTM
    try:
        lstm = SimpleLSTM(window=8)
        lstm.fit(X_tr_s, y_tr)
        proba_lstm = lstm.predict_proba(X_te_s)[:,1]
        auc = roc_auc_score(y_te, proba_lstm)
        all_aucs["lstm"].append(auc)
        fold_aucs["LSTM"] = auc
    except Exception:
        fold_aucs["LSTM"] = 0

    print(f"  Fold {fold}: " +
          " | ".join(f"{k}={v:.3f}" for k,v in fold_aucs.items()))

# Hitung mean AUC & bobot
mean_aucs = {k: np.mean(v) if v else 0 for k, v in all_aucs.items()}
print(f"\n  Mean AUC: " +
      " | ".join(f"{k}={v:.4f}" for k,v in mean_aucs.items()))

total_edge = sum(max(0, v-0.5) for v in mean_aucs.values())
if total_edge > 0:
    weights = {k: max(0, v-0.5)/total_edge for k,v in mean_aucs.items()}
else:
    weights = {k: 1/3 for k in mean_aucs}

print(f"  Bobot ensemble: " +
      " | ".join(f"{k}={v:.3f}" for k,v in weights.items()))

# ── TRAIN FINAL MODEL ─────────────────────────
print(f"\n🤖 Training model final...")
scaler_final = RobustScaler()
X_scaled     = scaler_final.fit_transform(X)

trained_models = {}

# RF
rf_final = RandomForestClassifier(
    n_estimators=400, max_depth=12,
    min_samples_split=8, min_samples_leaf=4,
    max_features="sqrt", class_weight=class_weights,
    random_state=42, n_jobs=-1)
rf_final.fit(X_scaled, y)
trained_models["rf"] = rf_final
print("  ✅ Random Forest trained")

# XGB/GBM
if XGB_AVAILABLE:
    import xgboost as xgb
    xgb_final = xgb.XGBClassifier(
        n_estimators=400, max_depth=6,
        learning_rate=0.03, subsample=0.8,
        colsample_bytree=0.8, random_state=42,
        eval_metric="logloss", verbosity=0)
else:
    xgb_final = GradientBoostingClassifier(
        n_estimators=300, max_depth=5,
        learning_rate=0.03, subsample=0.8, random_state=42)
xgb_final.fit(X_scaled, y)
trained_models["xgb"] = xgb_final
print(f"  ✅ {'XGBoost' if XGB_AVAILABLE else 'GradientBoosting'} trained")

# LSTM
try:
    lstm_final = SimpleLSTM(window=8)
    lstm_final.fit(X_scaled, y.values)
    trained_models["lstm"] = lstm_final
    print("  ✅ SimpleLSTM trained")
except Exception as e:
    print(f"  ⚠️  LSTM skip: {e}")

# Feature importance
feat_imp = {}
if "rf" in trained_models:
    imp = trained_models["rf"].feature_importances_
    feat_imp = dict(zip(feature_names, imp.tolist()))

# ── SIMPAN ───────────────────────────────────
ensemble = EnsemblePredictor(trained_models, weights, scaler_final)
save_ensemble(ensemble, feature_names, weights, mean_aucs, feat_imp)

# Juga update model_ml.pkl lama untuk fallback kompatibilitas
joblib.dump(rf_final, "model_ml.pkl")
joblib.dump(scaler_final, "scaler_ml.pkl")
joblib.dump(feature_names, "features_ml.pkl")

print(f"\n{'='*60}")
print(f"  Top 10 fitur terpenting:")
for feat, imp in sorted(feat_imp.items(), key=lambda x:-x[1])[:10]:
    bar = "█" * int(imp*300)
    print(f"  {feat:28} {imp:.4f} {bar}")

overall_auc = np.mean(list(mean_aucs.values()))
print(f"\n  Overall AUC : {overall_auc:.4f}")
print(f"  N fitur     : {len(feature_names)}")
print(f"  N sampel    : {len(X)}")
print(f"  N models    : {len(trained_models)}")
print(f"\n  Training selesai! Bot siap gunakan model baru.")
print(f"{'='*60}")