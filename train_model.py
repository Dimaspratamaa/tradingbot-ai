# ============================================
# TRAIN MODEL v2.0 — Quant Feature Edition
# Upgrade dari 14 fitur → 85+ fitur
# Algoritma: Random Forest (siap upgrade ke XGBoost di Phase 3)
# ============================================

import os, sys, pathlib
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
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.preprocessing import RobustScaler
from sklearn.utils.class_weight import compute_class_weight
import joblib, json, warnings
warnings.filterwarnings('ignore')

from feature_engineering import compute_all_features, get_feature_groups

API_KEY    = os.environ.get("BINANCE_API_KEY", "U0LiHucqGcPDj3L8bAHp0Qzfa9ocMxbEilQJeOihSwpmioNnl33WV4wyJcytSkkG")
API_SECRET = os.environ.get("BINANCE_API_SECRET", "pg412rXf0oSLFUqSn0914FCyYnJtZ32GCtBEwGPjT9UdawZz1BX2rVpxuwJmn0up")
SYMBOLS    = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT"]
LIMIT      = 1500
FORWARD    = 3
TARGET_PCT = 0.008

print("=" * 60)
print("   TRAINING MODEL v2.0 — 85+ QUANT FEATURES")
print("=" * 60)

try:
    client = Client(API_KEY, API_SECRET, testnet=False,
                    requests_params={"verify": False})
    client.ping()
    print("Binance terkoneksi")
except Exception as e:
    print(f"Binance error: {e}"); sys.exit(1)

def get_df(symbol, interval, limit):
    klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
    df = pd.DataFrame(klines, columns=[
        "time","open","high","low","close","volume",
        "close_time","quote_vol","trades","taker_base","taker_quote","ignore"])
    for col in ["open","high","low","close","volume"]:
        df[col] = df[col].astype(float)
    df["time"] = pd.to_datetime(df["time"], unit="ms")
    return df.set_index("time")

print(f"\nMengambil data {len(SYMBOLS)} simbol...")
dfs_1h, dfs_4h, dfs_1d = {}, {}, {}
for sym in SYMBOLS:
    try:
        dfs_1h[sym] = get_df(sym, Client.KLINE_INTERVAL_1HOUR, LIMIT)
        dfs_4h[sym] = get_df(sym, Client.KLINE_INTERVAL_4HOUR, 400)
        dfs_1d[sym] = get_df(sym, Client.KLINE_INTERVAL_1DAY, 200)
        print(f"  OK {sym}: {len(dfs_1h[sym])} candle")
    except Exception as e:
        print(f"  ERR {sym}: {e}")

print(f"\nMembangun feature matrix...")
all_rows = []
WINDOW = 100

for sym in SYMBOLS:
    if sym not in dfs_1h: continue
    df1h = dfs_1h[sym]
    df4h = dfs_4h.get(sym)
    df1d = dfs_1d.get(sym)
    n_rows = 0
    for i in range(WINDOW, len(df1h) - FORWARD):
        w1h = df1h.iloc[max(0, i-250):i+1]
        w4h = df4h.iloc[:max(1, i//4)] if df4h is not None else None
        w1d = df1d.iloc[:max(1, i//24)] if df1d is not None else None
        try:
            feat_dict, _ = compute_all_features(w1h, w4h, w1d)
        except Exception:
            continue
        if not feat_dict: continue
        future  = df1h["close"].iloc[i + FORWARD]
        current = df1h["close"].iloc[i]
        feat_dict["_target"] = int((future / current - 1) > TARGET_PCT)
        feat_dict["_symbol"] = sym
        all_rows.append(feat_dict)
        n_rows += 1
    print(f"  {sym}: {n_rows} sampel")

df_feat = pd.DataFrame(all_rows)
print(f"\nTotal: {len(df_feat)} sampel | {len(df_feat.columns)-2} fitur")
print(f"Label BUY(1): {df_feat['_target'].sum()} | HOLD(0): {(df_feat['_target']==0).sum()}")

feature_cols = [c for c in df_feat.columns if not c.startswith("_")]
X_raw = df_feat[feature_cols].fillna(0).replace([np.inf, -np.inf], 0)
y     = df_feat["_target"]

# Filter low-variance
low_var = X_raw.columns[X_raw.std() < 0.001].tolist()
X_raw   = X_raw.drop(columns=low_var)

# Filter high-correlation
corr = X_raw.corr().abs()
upper = corr.where(np.triu(np.ones(corr.shape), k=1).astype(bool))
high_corr = [col for col in upper.columns if any(upper[col] > 0.97)]
X_raw = X_raw.drop(columns=high_corr)

feature_names = X_raw.columns.tolist()
print(f"Fitur final setelah filter: {len(feature_names)}")

print(f"\nWalk-forward validation (5 fold)...")
X    = X_raw.values
tscv = TimeSeriesSplit(n_splits=5)
scores_acc, scores_auc = [], []

for fold, (tr_idx, te_idx) in enumerate(tscv.split(X), 1):
    X_tr, X_te = X[tr_idx], X[te_idx]
    y_tr, y_te = y.values[tr_idx], y.values[te_idx]
    sc = RobustScaler()
    X_tr_s = sc.fit_transform(X_tr)
    X_te_s = sc.transform(X_te)
    cw = compute_class_weight("balanced", classes=np.array([0,1]), y=y_tr)
    m  = RandomForestClassifier(n_estimators=300, max_depth=12,
             min_samples_split=10, min_samples_leaf=5,
             max_features="sqrt", class_weight={0:cw[0],1:cw[1]},
             random_state=42, n_jobs=-1)
    m.fit(X_tr_s, y_tr)
    acc = accuracy_score(y_te, m.predict(X_te_s))
    auc = roc_auc_score(y_te, m.predict_proba(X_te_s)[:,1])
    scores_acc.append(acc); scores_auc.append(auc)
    print(f"  Fold {fold}: Acc={acc:.3f} | AUC={auc:.3f}")

print(f"\n  Mean Acc : {np.mean(scores_acc):.3f} +/- {np.std(scores_acc):.3f}")
print(f"  Mean AUC : {np.mean(scores_auc):.3f} +/- {np.std(scores_auc):.3f}")

print(f"\nTraining model final...")
scaler_final = RobustScaler()
X_scaled     = scaler_final.fit_transform(X)
cw_all       = compute_class_weight("balanced", classes=np.array([0,1]), y=y.values)
model_final  = RandomForestClassifier(
    n_estimators=500, max_depth=15, min_samples_split=8,
    min_samples_leaf=4, max_features="sqrt",
    class_weight={0:cw_all[0],1:cw_all[1]},
    random_state=42, n_jobs=-1)
model_final.fit(X_scaled, y)

print("\nTop 15 fitur terpenting:")
importances = pd.Series(model_final.feature_importances_, index=feature_names)
groups = get_feature_groups()
for feat, imp in importances.nlargest(15).items():
    cat = next((c for c, fl in groups.items() if feat in fl), "other")
    print(f"  {feat:25} [{cat:10}] {imp:.4f}")

joblib.dump(model_final,   "model_ml.pkl")
joblib.dump(scaler_final,  "scaler_ml.pkl")
joblib.dump(feature_names, "features_ml.pkl")
meta = {"versi":"2.0-quant","n_fitur":len(feature_names),
        "n_sampel":len(X),"symbols":SYMBOLS,
        "mean_acc":round(float(np.mean(scores_acc)),4),
        "mean_auc":round(float(np.mean(scores_auc)),4),
        "feature_names":feature_names}
with open("model_meta.json","w") as f:
    json.dump(meta, f, indent=2)

print(f"\n{'='*60}")
print(f"  Model disimpan: model_ml.pkl ({len(feature_names)} fitur)")
print(f"  AUC: {np.mean(scores_auc):.4f}")
print(f"  Jalankan: python trading_bot.py")
print(f"{'='*60}")