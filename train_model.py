# ============================================
# TRAIN MODEL v3.0 — Ensemble Edition
# XGBoost + LightGBM + RandomForest + LSTM
# ============================================

import os, sys, pathlib, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, str(pathlib.Path(__file__).parent))

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

from binance.client import Client
import pandas as pd
import numpy as np
from feature_engineering import compute_all_features
from ml_ensemble import (
    walk_forward_train, train_ensemble,
    save_ensemble, EnsemblePredictor,
    XGB_AVAILABLE, LGB_AVAILABLE
)

# ── KONFIGURASI ──────────────────────────────
API_KEY    = os.environ.get("BINANCE_API_KEY", "U0LiHucqGcPDj3L8bAHp0Qzfa9ocMxbEilQJeOihSwpmioNnl33WV4wyJcytSkkG")
API_SECRET = os.environ.get("BINANCE_API_SECRET", "pg412rXf0oSLFUqSn0914FCyYnJtZ32GCtBEwGPjT9UdawZz1BX2rVpxuwJmn0up")
SYMBOLS    = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
LIMIT      = 1500
FORWARD    = 3
TARGET_PCT = 0.008

print("=" * 60)
print("   TRAINING MODEL v3.0 — ENSEMBLE EDITION")
print(f"   XGBoost  : {'✅' if XGB_AVAILABLE else '❌'}")
print(f"   LightGBM : {'✅' if LGB_AVAILABLE else '❌'}")
print("=" * 60)

# ── CONNECT ──────────────────────────────────
try:
    client = Client(API_KEY, API_SECRET, testnet=False,
                    requests_params={"verify": False})
    client.ping()
    print("✅ Binance terkoneksi")
except Exception as e:
    print(f"❌ Binance error: {e}"); sys.exit(1)

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

print(f"\n📥 Mengambil data {len(SYMBOLS)} simbol...")
dfs_1h, dfs_4h, dfs_1d = {}, {}, {}
for sym in SYMBOLS:
    try:
        dfs_1h[sym] = get_df(sym, Client.KLINE_INTERVAL_1HOUR, LIMIT)
        dfs_4h[sym] = get_df(sym, Client.KLINE_INTERVAL_4HOUR, 400)
        dfs_1d[sym] = get_df(sym, Client.KLINE_INTERVAL_1DAY, 200)
        print(f"  ✅ {sym}: {len(dfs_1h[sym])} candle")
    except Exception as e:
        print(f"  ⚠️  {sym}: {e}")

# ── BUILD FEATURE MATRIX ─────────────────────
print(f"\n🔧 Building feature matrix (98+ fitur)...")
all_rows = []
WINDOW   = 100

for sym in SYMBOLS:
    if sym not in dfs_1h: continue
    df1h = dfs_1h[sym]
    df4h = dfs_4h.get(sym)
    df1d = dfs_1d.get(sym)
    n_rows = 0

    for i in range(WINDOW, len(df1h) - FORWARD):
        w1h = df1h.iloc[max(0, i-250):i+1]
        w4h = df4h.iloc[:max(1,i//4)] if df4h is not None else None
        w1d = df1d.iloc[:max(1,i//24)] if df1d is not None else None
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

    print(f"  {sym}: {n_rows} sampel")

df_feat = pd.DataFrame(all_rows)
print(f"\n📊 Total: {len(df_feat)} sampel")
print(f"   BUY(1): {df_feat['_target'].sum()} | "
      f"HOLD(0): {(df_feat['_target']==0).sum()}")

# ── FILTER FITUR ─────────────────────────────
feature_cols = [c for c in df_feat.columns if not c.startswith("_")]
X_raw = df_feat[feature_cols].fillna(0).replace([np.inf,-np.inf], 0)
y     = df_feat["_target"]

# Hapus low-variance
low_var = X_raw.columns[X_raw.std() < 0.001].tolist()
X_raw   = X_raw.drop(columns=low_var)

# Hapus high-correlation
corr  = X_raw.corr().abs()
upper = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
hc    = [c for c in upper.columns if any(upper[c] > 0.97)]
X_raw = X_raw.drop(columns=hc)

feature_names = X_raw.columns.tolist()
print(f"   Fitur final: {len(feature_names)}")

X = X_raw.values

# ── WALK-FORWARD VALIDATION ──────────────────
model_weights, mean_aucs, _ = walk_forward_train(
    X, y.values, feature_names, n_splits=5
)

# ── TRAIN FINAL ENSEMBLE ─────────────────────
trained_models, scaler_final, feat_importance = train_ensemble(
    X, y.values, feature_names, model_weights
)

# ── BUAT ENSEMBLE PREDICTOR ──────────────────
ensemble = EnsemblePredictor(trained_models, model_weights, scaler_final)

# ── EVALUASI FINAL ───────────────────────────
print(f"\n📈 Evaluasi ensemble pada data penuh:")
from sklearn.metrics import classification_report
from sklearn.preprocessing import RobustScaler as RS
X_sc   = scaler_final.transform(X)
y_pred = ensemble.predict(X_sc.reshape(len(X), -1)
                          if hasattr(X_sc, 'reshape') else
                          np.array([[v] for v in range(len(X))]))

# Simple eval
proba_all = ensemble.predict_proba(X_sc)[:,1]
try:
    from sklearn.metrics import roc_auc_score
    auc_final = roc_auc_score(y.values, proba_all)
    print(f"   AUC Final: {auc_final:.4f}")
except Exception:
    pass

# ── SIMPAN ───────────────────────────────────
save_ensemble(ensemble, feature_names, model_weights,
              mean_aucs, feat_importance)

print(f"\n{'='*60}")
print(f"  Top 10 fitur terpenting:")
if feat_importance:
    for feat, imp in sorted(feat_importance.items(),
                             key=lambda x:-x[1])[:10]:
        bar = "█" * int(imp * 300)
        print(f"  {feat:25} {imp:.4f} {bar}")

print(f"\n  Model siap digunakan!")
print(f"  Jalankan: python trading_bot.py")
print(f"{'='*60}")