# ============================================
# TRAINING MODEL MACHINE LEARNING
# Algoritma : Random Forest Classifier
# ============================================

from binance.client import Client
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report
from sklearn.preprocessing import StandardScaler
import joblib
import warnings
warnings.filterwarnings('ignore')

# ── KONFIGURASI ───────────────────────────────
API_KEY    = "ISI_API_KEY_TESTNET_KAMU"
API_SECRET = "ISI_API_SECRET_TESTNET_KAMU"

SYMBOL   = "BTCUSDT"
INTERVAL = Client.KLINE_INTERVAL_1HOUR
LIMIT    = 1000  # Ambil 1000 candle untuk training

client = Client(API_KEY, API_SECRET, testnet=True)

print("=" * 55)
print("   TRAINING MODEL MACHINE LEARNING")
print("   Algoritma : Random Forest Classifier")
print("=" * 55)

# ── STEP 1: AMBIL DATA HISTORIS ───────────────
print("\n📥 Mengambil data historis dari Binance...")
klines = client.get_klines(symbol=SYMBOL, interval=INTERVAL, limit=LIMIT)
df = pd.DataFrame(klines, columns=[
    'time','open','high','low','close','volume',
    'close_time','quote_vol','trades',
    'taker_base','taker_quote','ignore'
])
for col in ['open','high','low','close','volume']:
    df[col] = df[col].astype(float)

print(f"✅ Data berhasil diambil: {len(df)} candle")

# ── STEP 2: BUAT FITUR (FEATURES) ────────────
print("\n🔧 Membuat fitur untuk model ML...")

# RSI
delta = df['close'].diff()
gain  = delta.where(delta > 0, 0).rolling(14).mean()
loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
df['rsi'] = 100 - (100 / (1 + gain / loss))

# MACD
ema12 = df['close'].ewm(span=12, adjust=False).mean()
ema26 = df['close'].ewm(span=26, adjust=False).mean()
df['macd']        = ema12 - ema26
df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
df['macd_hist']   = df['macd'] - df['macd_signal']

# Bollinger Bands
sma20       = df['close'].rolling(20).mean()
std20       = df['close'].rolling(20).std()
df['bb_upper'] = sma20 + (std20 * 2)
df['bb_lower'] = sma20 - (std20 * 2)
df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / sma20
df['bb_pos']   = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])

# ATR
tr = pd.concat([
    df['high'] - df['low'],
    (df['high'] - df['close'].shift()).abs(),
    (df['low']  - df['close'].shift()).abs()
], axis=1).max(axis=1)
df['atr'] = tr.rolling(14).mean()
df['atr_pct'] = df['atr'] / df['close'] * 100

# Volume
df['vol_ratio'] = df['volume'] / df['volume'].rolling(20).mean()

# EMA
df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
df['ema_diff'] = (df['ema20'] - df['ema50']) / df['close'] * 100

# Price momentum
df['momentum_3']  = df['close'].pct_change(3) * 100
df['momentum_7']  = df['close'].pct_change(7) * 100
df['momentum_14'] = df['close'].pct_change(14) * 100

# Candle pattern
df['candle_body'] = (df['close'] - df['open']).abs() / df['close'] * 100
df['candle_dir']  = (df['close'] > df['open']).astype(int)

# ── STEP 3: BUAT LABEL (TARGET) ───────────────
# Label: 1 = harga naik > 1% dalam 3 candle ke depan
#         0 = harga tidak naik / turun
future_return    = df['close'].shift(-3) / df['close'] - 1
df['target']     = (future_return > 0.01).astype(int)

# ── STEP 4: SIAPKAN DATA TRAINING ─────────────
features = [
    'rsi', 'macd', 'macd_signal', 'macd_hist',
    'bb_width', 'bb_pos', 'atr_pct', 'vol_ratio',
    'ema_diff', 'momentum_3', 'momentum_7', 'momentum_14',
    'candle_body', 'candle_dir'
]

df = df.dropna()
X  = df[features]
y  = df['target']

print(f"✅ Fitur dibuat: {len(features)} fitur")
print(f"   Data training: {len(X)} sampel")
print(f"   Label BUY (1): {y.sum()} | Label HOLD (0): {(y==0).sum()}")

# ── STEP 5: SPLIT DATA ────────────────────────
X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42, shuffle=False
)

# ── STEP 6: NORMALISASI ───────────────────────
scaler  = StandardScaler()
X_train = scaler.fit_transform(X_train)
X_test  = scaler.transform(X_test)

# ── STEP 7: TRAINING MODEL ────────────────────
print("\n🤖 Training model Random Forest...")
model = RandomForestClassifier(
    n_estimators=200,
    max_depth=10,
    min_samples_split=5,
    min_samples_leaf=2,
    random_state=42,
    n_jobs=-1
)
model.fit(X_train, y_train)
print("✅ Training selesai!")

# ── STEP 8: EVALUASI MODEL ────────────────────
y_pred   = model.predict(X_test)
accuracy = accuracy_score(y_test, y_pred)

print(f"\n📊 HASIL EVALUASI MODEL:")
print(f"   Akurasi : {accuracy*100:.2f}%")
print(f"\n{classification_report(y_test, y_pred, target_names=['HOLD','BUY'])}")

# Feature importance
importances = pd.Series(
    model.feature_importances_, index=features
).sort_values(ascending=False)
print("🔍 Feature Importance (Top 5):")
for feat, imp in importances.head(5).items():
    print(f"   {feat:20} : {imp:.4f}")

# ── STEP 9: SIMPAN MODEL ──────────────────────
joblib.dump(model,  "model_ml.pkl")
joblib.dump(scaler, "scaler_ml.pkl")
joblib.dump(features, "features_ml.pkl")
print("\n✅ Model disimpan: model_ml.pkl")
print("✅ Scaler disimpan: scaler_ml.pkl")
print("✅ Features disimpan: features_ml.pkl")
print("\n🎯 Sekarang jalankan: python trading_bot.py")