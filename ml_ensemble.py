# ============================================
# ADVANCED ML ENSEMBLE v1.0 — Phase 3
# Terinspirasi Two Sigma & Renaissance Technologies
#
# Model yang digunakan:
#   1. XGBoost      — gradient boosting (akurasi tertinggi tabular)
#   2. LightGBM     — lebih cepat, bagus untuk data besar
#   3. Random Forest — robust, baseline kuat
#   4. LSTM (simple) — sequence modeling via numpy murni
#   5. Ensemble Voting — gabungkan semua model dengan bobot dinamis
#
# Upgrade dari Phase 1:
#   - Walk-forward validation WAJIB (no lookahead bias)
#   - SHAP-proxy feature importance
#   - Model performance tracking
#   - Auto-reweight berdasarkan performa terkini
# ============================================

import os
import sys
import json
import time
import pathlib
import warnings
import numpy as np
import pandas as pd
import joblib
warnings.filterwarnings('ignore')

from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.preprocessing import RobustScaler
from sklearn.metrics import accuracy_score, roc_auc_score, f1_score
from sklearn.model_selection import TimeSeriesSplit
from sklearn.utils.class_weight import compute_class_weight

# Import opsional — fallback ke sklearn jika tidak ada
try:
    import xgboost as xgb
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False
    print("  ⚠️  XGBoost tidak tersedia — pakai GradientBoosting")

try:
    import lightgbm as lgb
    LGB_AVAILABLE = True
except ImportError:
    LGB_AVAILABLE = False
    print("  ⚠️  LightGBM tidak tersedia — skip")

BASE_DIR = pathlib.Path(__file__).parent

# ── FILE PATHS ────────────────────────────────
MODEL_ENSEMBLE_FILE = BASE_DIR / "model_ensemble.pkl"
SCALER_FILE         = BASE_DIR / "scaler_ml.pkl"
FEATURES_FILE       = BASE_DIR / "features_ml.pkl"
META_FILE           = BASE_DIR / "model_meta.json"
PERF_FILE           = BASE_DIR / "model_performance.json"

# ══════════════════════════════════════════════
# 1. LSTM SEDERHANA (tanpa tensorflow/pytorch)
# Pakai numpy murni — ringan, bisa jalan di Railway
# ══════════════════════════════════════════════

class SimpleLSTM:
    """
    LSTM sederhana menggunakan numpy.
    Bukan true LSTM tapi approximasi yang cukup baik
    untuk menangkap sequential patterns.

    Cara kerja: sliding window features + linear regression
    dengan exponential decay weighting (bobot candle terbaru lebih besar)
    """
    def __init__(self, window=10, hidden=32):
        self.window = window
        self.hidden = hidden
        self.W      = None
        self.b      = None
        self.scaler = RobustScaler()
        self.fitted = False

    def _make_sequences(self, X):
        """Buat sequence features dari window."""
        n, d = X.shape
        if n <= self.window:
            return np.zeros((0, self.window * d))
        seqs = []
        for i in range(self.window, n):
            window = X[i-self.window:i].flatten()
            seqs.append(window)
        return np.array(seqs)

    def fit(self, X, y):
        """Train dengan least squares + decay weighting."""
        X_s   = self.scaler.fit_transform(X)
        X_seq = self._make_sequences(X_s)
        y_seq = y[self.window:]

        if len(X_seq) < 20:
            self.fitted = False
            return self

        # Decay weights: candle terbaru lebih penting
        n = len(X_seq)
        weights = np.exp(np.linspace(-1, 0, n))
        weights /= weights.sum()

        # Weighted least squares
        W_diag   = np.diag(weights)
        XtW      = X_seq.T @ W_diag
        XtWX     = XtW @ X_seq + np.eye(X_seq.shape[1]) * 0.01
        XtWy     = XtW @ y_seq.astype(float)
        try:
            self.W = np.linalg.solve(XtWX, XtWy)
            self.b = np.mean(y_seq) - X_seq.mean(axis=0) @ self.W
        except np.linalg.LinAlgError:
            self.W = np.zeros(X_seq.shape[1])
            self.b = 0.5
        self.fitted = True
        return self

    def predict_proba(self, X):
        """Return probabilitas [P(0), P(1)]."""
        if not self.fitted or self.W is None:
            n = len(X)
            return np.column_stack([np.full(n, 0.5), np.full(n, 0.5)])
        X_s   = self.scaler.transform(X)
        X_seq = self._make_sequences(X_s)
        if len(X_seq) == 0:
            return np.array([[0.5, 0.5]])
        raw = X_seq @ self.W + self.b
        # Sigmoid
        prob1 = 1 / (1 + np.exp(-np.clip(raw, -10, 10)))
        prob0 = 1 - prob1
        return np.column_stack([prob0, prob1])

    def predict(self, X):
        proba = self.predict_proba(X)
        return (proba[:, 1] > 0.5).astype(int)


# ══════════════════════════════════════════════
# 2. MODEL REGISTRY — konfigurasi semua model
# ══════════════════════════════════════════════

def buat_semua_model(class_weights):
    """Buat semua model dengan konfigurasi optimal."""
    models = {}

    # Random Forest — robust baseline
    models["rf"] = RandomForestClassifier(
        n_estimators=300,
        max_depth=12,
        min_samples_split=10,
        min_samples_leaf=5,
        max_features="sqrt",
        class_weight=class_weights,
        random_state=42,
        n_jobs=-1
    )

    # XGBoost — biasanya akurasi tertinggi
    if XGB_AVAILABLE:
        scale_pos = (class_weights.get(0, 1) / class_weights.get(1, 1)
                     if class_weights else 1.0)
        models["xgb"] = xgb.XGBClassifier(
            n_estimators=300,
            max_depth=6,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            scale_pos_weight=scale_pos,
            use_label_encoder=False,
            eval_metric="logloss",
            random_state=42,
            n_jobs=-1,
            verbosity=0
        )
    else:
        # Fallback ke GradientBoosting
        models["xgb"] = GradientBoostingClassifier(
            n_estimators=200,
            max_depth=5,
            learning_rate=0.05,
            subsample=0.8,
            random_state=42
        )

    # LightGBM — cepat dan akurat
    if LGB_AVAILABLE:
        models["lgb"] = lgb.LGBMClassifier(
            n_estimators=300,
            max_depth=7,
            learning_rate=0.05,
            num_leaves=31,
            subsample=0.8,
            colsample_bytree=0.8,
            class_weight=class_weights,
            random_state=42,
            n_jobs=-1,
            verbose=-1
        )

    # Simple LSTM
    models["lstm"] = SimpleLSTM(window=10, hidden=32)

    return models


# ══════════════════════════════════════════════
# 3. WALK-FORWARD TRAINING
# ══════════════════════════════════════════════

def walk_forward_train(X, y, feature_names, n_splits=5):
    """
    Walk-forward cross-validation.
    Kritis untuk trading ML — tidak ada lookahead bias.

    Cara kerja:
    Fold 1: train [0:200]     test [200:240]
    Fold 2: train [0:240]     test [240:280]
    Fold 3: train [0:280]     test [280:320]
    ... dan seterusnya

    Return:
        model_weights: bobot setiap model berdasarkan AUC
        fold_results : detail performa per fold
    """
    tscv       = TimeSeriesSplit(n_splits=n_splits)
    fold_results = []
    model_aucs   = {}

    # Hitung class weights
    cw_arr = compute_class_weight("balanced",
                                   classes=np.array([0, 1]),
                                   y=y)
    class_weights = {0: cw_arr[0], 1: cw_arr[1]}

    print(f"\n  📊 Walk-Forward Validation ({n_splits} folds)...")

    for fold, (train_idx, test_idx) in enumerate(tscv.split(X), 1):
        X_tr, X_te = X[train_idx], X[test_idx]
        y_tr, y_te = y[train_idx], y[test_idx]

        if len(np.unique(y_te)) < 2:
            continue

        # Scale
        sc     = RobustScaler()
        X_tr_s = sc.fit_transform(X_tr)
        X_te_s = sc.transform(X_te)

        # Train semua model di fold ini
        models_fold = buat_semua_model(class_weights)
        fold_aucs   = {}

        for name, model in models_fold.items():
            try:
                model.fit(X_tr_s, y_tr)
                proba = model.predict_proba(X_te_s)[:, 1]
                auc   = roc_auc_score(y_te, proba)
                fold_aucs[name] = auc
                if name not in model_aucs:
                    model_aucs[name] = []
                model_aucs[name].append(auc)
            except Exception as e:
                print(f"    ⚠️  {name} fold {fold}: {e}")

        print(f"  Fold {fold}: " +
              " | ".join(f"{n}={a:.3f}" for n, a in fold_aucs.items()))
        fold_results.append(fold_aucs)

    # Hitung bobot berdasarkan mean AUC
    mean_aucs = {name: np.mean(aucs)
                 for name, aucs in model_aucs.items()
                 if aucs}

    # Bobot proporsional ke AUC (model lebih baik = bobot lebih besar)
    total_auc = sum(max(0, a - 0.5) for a in mean_aucs.values())
    if total_auc > 0:
        weights = {name: max(0, a - 0.5) / total_auc
                   for name, a in mean_aucs.items()}
    else:
        weights = {name: 1/len(mean_aucs) for name in mean_aucs}

    print(f"\n  Mean AUC per model:")
    for name, auc in sorted(mean_aucs.items(), key=lambda x: -x[1]):
        print(f"    {name:6}: {auc:.4f} (weight: {weights.get(name,0):.3f})")

    return weights, mean_aucs, fold_results


# ══════════════════════════════════════════════
# 4. TRAIN FINAL ENSEMBLE
# ══════════════════════════════════════════════

def train_ensemble(X, y, feature_names, model_weights):
    """
    Train model final dengan semua data.
    Gunakan bobot dari walk-forward untuk ensemble.
    """
    print(f"\n  🤖 Training ensemble final ({len(X)} sampel)...")

    cw_arr = compute_class_weight("balanced",
                                   classes=np.array([0, 1]), y=y)
    class_weights = {0: cw_arr[0], 1: cw_arr[1]}

    scaler_final = RobustScaler()
    X_scaled     = scaler_final.fit_transform(X)

    models_final = buat_semua_model(class_weights)
    trained      = {}

    for name, model in models_final.items():
        if model_weights.get(name, 0) > 0.01:  # skip model yang sangat buruk
            try:
                model.fit(X_scaled, y)
                trained[name] = model
                print(f"    ✅ {name} trained")
            except Exception as e:
                print(f"    ⚠️  {name} gagal: {e}")

    # Feature importance (SHAP-proxy via RF)
    feat_imp = {}
    if "rf" in trained:
        imp = trained["rf"].feature_importances_
        feat_imp = dict(zip(feature_names, imp.tolist()))

    return trained, scaler_final, feat_imp


# ══════════════════════════════════════════════
# 5. ENSEMBLE PREDICT — gabungkan semua model
# ══════════════════════════════════════════════

class EnsemblePredictor:
    """
    Ensemble predictor yang menggabungkan semua model
    dengan bobot dinamis berdasarkan performa walk-forward.
    """
    def __init__(self, models, weights, scaler):
        self.models  = models
        self.weights = weights
        self.scaler  = scaler

    def predict_proba_ensemble(self, X):
        """Return probabilitas weighted ensemble."""
        if not self.models:
            return np.array([[0.5, 0.5]])

        X_scaled   = self.scaler.transform(X)
        weighted_p = np.zeros(len(X))
        total_w    = 0

        for name, model in self.models.items():
            w = self.weights.get(name, 0)
            if w <= 0:
                continue
            try:
                p = model.predict_proba(X_scaled)[:, 1]
                weighted_p += w * p
                total_w    += w
            except Exception:
                pass

        if total_w > 0:
            weighted_p /= total_w
        else:
            weighted_p = np.full(len(X), 0.5)

        prob1 = np.clip(weighted_p, 0, 1)
        prob0 = 1 - prob1
        return np.column_stack([prob0, prob1])

    def predict(self, X):
        proba = self.predict_proba_ensemble(X)
        return (proba[:, 1] > 0.5).astype(int)

    def predict_proba(self, X):
        return self.predict_proba_ensemble(X)

    def get_model_votes(self, X):
        """Lihat vote setiap model secara individual."""
        X_scaled = self.scaler.transform(X)
        votes    = {}
        for name, model in self.models.items():
            try:
                p = model.predict_proba(X_scaled)[0, 1]
                votes[name] = round(float(p), 4)
            except Exception:
                votes[name] = 0.5
        return votes


# ══════════════════════════════════════════════
# 6. LOAD / SAVE ENSEMBLE
# ══════════════════════════════════════════════

def save_ensemble(ensemble, feature_names, model_weights,
                  mean_aucs, feat_importance):
    """Simpan ensemble ke disk."""
    joblib.dump(ensemble.models,  MODEL_ENSEMBLE_FILE)
    joblib.dump(ensemble.scaler,  SCALER_FILE)
    joblib.dump(feature_names,    FEATURES_FILE)

    meta = {
        "versi"        : "3.0-ensemble",
        "n_fitur"      : len(feature_names),
        "model_weights": model_weights,
        "mean_aucs"    : mean_aucs,
        "n_models"     : len(ensemble.models),
        "model_names"  : list(ensemble.models.keys()),
        "feature_names": feature_names,
        "waktu_train"  : time.strftime("%Y-%m-%d %H:%M:%S"),
        "top_features" : sorted(feat_importance.items(),
                                key=lambda x: -x[1])[:20]
                         if feat_importance else []
    }
    with open(META_FILE, "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\n  💾 Ensemble tersimpan:")
    print(f"     model_ensemble.pkl ({len(ensemble.models)} models)")
    print(f"     features_ml.pkl ({len(feature_names)} fitur)")
    print(f"     model_meta.json")


def load_ensemble():
    """
    Load ensemble dari disk.
    Return EnsemblePredictor atau None jika belum ada.
    """
    if not MODEL_ENSEMBLE_FILE.exists():
        return None, None, None

    try:
        models        = joblib.load(MODEL_ENSEMBLE_FILE)
        scaler        = joblib.load(SCALER_FILE)
        feature_names = joblib.load(FEATURES_FILE)

        with open(META_FILE) as f:
            meta = json.load(f)

        weights    = meta.get("model_weights", {})
        # Normalisasi weights
        total_w = sum(weights.values())
        if total_w > 0:
            weights = {k: v/total_w for k, v in weights.items()}

        ensemble = EnsemblePredictor(models, weights, scaler)
        return ensemble, feature_names, meta

    except Exception as e:
        print(f"  ⚠️  Gagal load ensemble: {e}")
        return None, None, None


# ══════════════════════════════════════════════
# 7. MODEL PERFORMANCE TRACKER
# ══════════════════════════════════════════════

def catat_prediksi(symbol, prediksi, confidence, harga_entry):
    """Catat prediksi untuk evaluasi akurasi real-time."""
    log = []
    if PERF_FILE.exists():
        try:
            log = json.loads(PERF_FILE.read_text())
        except Exception:
            pass

    log.append({
        "waktu"      : time.strftime("%Y-%m-%d %H:%M:%S"),
        "symbol"     : symbol,
        "prediksi"   : prediksi,
        "confidence" : round(confidence, 4),
        "harga_entry": harga_entry,
        "harga_exit" : None,   # diisi saat posisi ditutup
        "benar"      : None,
    })
    PERF_FILE.write_text(json.dumps(log[-1000:], indent=2))


def get_model_accuracy_live():
    """Hitung akurasi model dari prediksi historis yang sudah selesai."""
    if not PERF_FILE.exists():
        return None

    try:
        log  = json.loads(PERF_FILE.read_text())
        done = [e for e in log if e.get("benar") is not None]
        if len(done) < 5:
            return None

        acc    = sum(1 for e in done if e["benar"]) / len(done)
        recent = done[-20:]
        acc_20 = sum(1 for e in recent if e["benar"]) / len(recent)

        return {
            "total_prediksi": len(done),
            "akurasi_all"   : round(acc, 4),
            "akurasi_20"    : round(acc_20, 4),
            "perlu_retrain" : acc_20 < 0.52   # retrain jika akurasi turun
        }
    except Exception:
        return None


# ══════════════════════════════════════════════
# 8. PREDIKSI DENGAN ENSEMBLE
# ══════════════════════════════════════════════

_ensemble_cache = {"model": None, "features": None, "meta": None}

def prediksi_ensemble(df_1h, df_4h=None, df_1d=None):
    """
    Fungsi utama prediksi menggunakan ensemble model.
    Drop-in replacement untuk prediksi_ml() lama.

    Return:
        sinyal     : "BUY" atau "HOLD"
        confidence : float 0-100
        detail     : dict berisi vote setiap model
    """
    global _ensemble_cache

    # Load model jika belum
    if _ensemble_cache["model"] is None:
        ens, feats, meta = load_ensemble()
        if ens is None:
            return "HOLD", 50.0, {}
        _ensemble_cache = {"model": ens, "features": feats, "meta": meta}

    ensemble = _ensemble_cache["model"]
    features = _ensemble_cache["features"]

    if ensemble is None or features is None:
        return "HOLD", 50.0, {}

    try:
        # Compute features
        from feature_engineering import compute_all_features
        feat_dict, _ = compute_all_features(df_1h, df_4h, df_1d)

        if not feat_dict:
            return "HOLD", 50.0, {}

        # Build feature vector
        X_vec = [feat_dict.get(f, 0.0) for f in features]
        X     = np.array(X_vec).reshape(1, -1)

        # Ensemble predict
        proba  = ensemble.predict_proba(X)[0]
        prob1  = proba[1]
        pred   = "BUY" if prob1 > 0.5 else "HOLD"
        conf   = prob1 * 100 if pred == "BUY" else (1 - prob1) * 100

        # Individual model votes
        votes  = ensemble.get_model_votes(X)

        return pred, round(conf, 2), votes

    except Exception as e:
        return "HOLD", 50.0, {}