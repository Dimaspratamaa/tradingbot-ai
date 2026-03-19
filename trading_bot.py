# ============================================
# BINANCE TRADING BOT v9.6 - MULTI EXCHANGE
# Spot + Futures + Bybit + OKX + Coinbase
# Arbitrase Detection + Cross OB Analysis
# ============================================

from binance.client import Client
from binance.exceptions import BinanceAPIException
from onchain import get_onchain_score
from bayesian_model import BayesianTradingModel
from geopolitik import get_geo_score
from orderbook import analisis_orderbook
from futures_engine import (
    buka_long, buka_short, cek_posisi_futures,
    print_status_futures, tentukan_mode_futures,
    posisi_futures, LEVERAGE, MAX_POSISI_FUTURES
)
from multi_exchange import (
    analisis_multi_exchange,
    cek_saldo_semua_exchange,
    scan_arbitrase
)
import pandas as pd
import numpy as np
import requests
import time
import json
import os
import joblib
import warnings
import signal
import sys
import traceback
warnings.filterwarnings('ignore')

# ── KONFIGURASI ───────────────────────────────
API_KEY    = os.environ.get("BINANCE_API_KEY",    "U0LiHucqGcPDj3L8bAHp0Qzfa9ocMxbEilQJeOihSwpmioNnl33WV4wyJcytSkkG")
API_SECRET = os.environ.get("BINANCE_API_SECRET", "pg412rXf0oSLFUqSn0914FCyYnJtZ32GCtBEwGPjT9UdawZz1BX2rVpxuwJmn0up")
TG_TOKEN   = os.environ.get("TG_TOKEN",           "8735682075:AAE6N7YtKgGkxK-1dZl-RVKCvQplGgaUN8M")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID",         "8604266478")

# ── MULTI EXCHANGE API (dari env variables) ───
BYBIT_KEY    = os.environ.get("BYBIT_API_KEY", "")
BYBIT_SECRET = os.environ.get("BYBIT_API_SECRET", "")
OKX_KEY      = os.environ.get("OKX_API_KEY", "")
OKX_SECRET   = os.environ.get("OKX_API_SECRET", "")
OKX_PASS     = os.environ.get("OKX_PASSPHRASE", "")
CB_KEY       = os.environ.get("COINBASE_API_KEY", "")
CB_SECRET    = os.environ.get("COINBASE_API_SECRET", "")

# ── DAFTAR KOIN ───────────────────────────────
KOIN_LIST = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT",
    "SOLUSDT", "ADAUSDT", "XRPUSDT",
    "DOGEUSDT", "AVAXUSDT", "DOTUSDT",
    "LINKUSDT"
]

# ── KONFIGURASI SPOT ──────────────────────────
MAX_POSISI_SPOT    = 3
MIN_SCORE_SPOT     = 6
TRADE_USDT_SPOT    = 100.0

# ── TRAILING & TIMEFRAME ──────────────────────
TRAILING_AKTIVASI  = 1.5
TRAILING_JARAK     = 1.0
TF_REQUIRED        = 2
SCAN_INTERVAL      = 300

# ── STATE ─────────────────────────────────────
posisi_spot     = {}
onchain_cache   = {"data": None, "waktu": 0}
geo_cache       = {"data": None, "waktu": 0}
bot_running     = True
reconnect_count = 0
MAX_RECONNECT   = 10
RECONNECT_DELAY = 30

# ── INIT CLIENT ───────────────────────────────
def buat_client():
    return Client(API_KEY, API_SECRET, testnet=True)

client = buat_client()
bayes  = BayesianTradingModel()
bayes.load_model()

# ── GRACEFUL SHUTDOWN ─────────────────────────
def handle_shutdown(signum, frame):
    global bot_running
    bot_running = False
    kirim_telegram(
        "⛔ <b>Bot dihentikan</b>\n"
        "📌 Posisi spot & futures tetap terbuka"
    )
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT,  handle_shutdown)

# ── FUNGSI: KIRIM TELEGRAM ────────────────────
def kirim_telegram(pesan, retry=3):
    for attempt in range(retry):
        try:
            url  = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
            data = {"chat_id": TG_CHAT_ID, "text": pesan, "parse_mode": "HTML"}
            if requests.post(url, data=data, timeout=15).status_code == 200:
                return True
        except:
            if attempt < retry - 1: time.sleep(5)
    return False

# ── FUNGSI: RECONNECT ─────────────────────────
def reconnect_client():
    global client, reconnect_count
    reconnect_count += 1
    if reconnect_count > MAX_RECONNECT:
        kirim_telegram("🚨 <b>Bot OFFLINE!</b> Perlu restart manual!")
        sys.exit(1)
    delay = min(RECONNECT_DELAY * reconnect_count, 300)
    if reconnect_count == 1:
        kirim_telegram(f"⚠️ <b>Koneksi terputus</b>, reconnect #{reconnect_count}...")
    time.sleep(delay)
    try:
        client = buat_client()
        client.ping()
        kirim_telegram(f"✅ <b>Koneksi pulih!</b> (#{reconnect_count})")
        reconnect_count = 0
        return True
    except:
        return False

# ── FUNGSI: SIMPAN TRANSAKSI ──────────────────
def simpan_transaksi(symbol, harga_beli, harga_jual,
                     waktu_beli, waktu_jual, alasan):
    profit_pct = ((harga_jual - harga_beli) / harga_beli) * 100
    riwayat = []
    if os.path.exists("riwayat_trade.json"):
        with open("riwayat_trade.json", "r") as f:
            riwayat = json.load(f)
    riwayat.append({
        "symbol": symbol, "harga_beli": harga_beli,
        "harga_jual": harga_jual, "profit_pct": round(profit_pct, 4),
        "waktu_beli": waktu_beli, "waktu_jual": waktu_jual,
        "alasan": alasan
    })
    with open("riwayat_trade.json", "w") as f:
        json.dump(riwayat, f, indent=2)
    print(f"  💾 [{symbol}] P/L: {profit_pct:+.2f}% | {alasan}")

# ── FUNGSI: CEK SALDO ─────────────────────────
def cek_saldo():
    # Tampilkan saldo semua exchange sekaligus
    cek_saldo_semua_exchange(client)

# ── FUNGSI: LOAD MODEL ML ─────────────────────
model_ml = scaler_ml = features_ml = None

def load_model():
    global model_ml, scaler_ml, features_ml
    try:
        model_ml    = joblib.load("model_ml.pkl")
        scaler_ml   = joblib.load("scaler_ml.pkl")
        features_ml = joblib.load("features_ml.pkl")
        print("  🤖 Model ML dimuat!")
        return True
    except:
        print("  ⚠️  Model ML belum ada!")
        return False

# ── FUNGSI: AMBIL DATA ────────────────────────
def get_data(symbol, interval=Client.KLINE_INTERVAL_1HOUR, limit=150):
    try:
        klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(klines, columns=[
            'time','open','high','low','close','volume',
            'close_time','quote_vol','trades',
            'taker_base','taker_quote','ignore'
        ])
        for col in ['open','high','low','close','volume']:
            df[col] = df[col].astype(float)
        return df
    except Exception as e:
        print(f"  ⚠️  Gagal ambil {symbol}: {e}")
        return None

# ── FUNGSI: HITUNG INDIKATOR ──────────────────
def hitung_indikator(df):
    close  = df['close']; high = df['high']
    low    = df['low'];   volume = df['volume']

    delta = close.diff()
    gain  = delta.where(delta > 0, 0).rolling(14).mean()
    loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rsi   = (100 - (100 / (1 + gain / loss))).iloc[-1]

    ema12       = close.ewm(span=12, adjust=False).mean()
    ema26       = close.ewm(span=26, adjust=False).mean()
    macd_line   = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_up     = (macd_line.iloc[-1] > signal_line.iloc[-1] and
                   macd_line.iloc[-2] <= signal_line.iloc[-2])
    macd_down   = (macd_line.iloc[-1] < signal_line.iloc[-1] and
                   macd_line.iloc[-2] >= signal_line.iloc[-2])

    sma20    = close.rolling(20).mean()
    std20    = close.rolling(20).std()
    harga    = close.iloc[-1]
    bb_bawah = harga <= (sma20 - std20 * 2).iloc[-1]
    bb_atas  = harga >= (sma20 + std20 * 2).iloc[-1]

    tr  = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(14).mean().iloc[-1]

    tenkan  = (high.rolling(9).max()  + low.rolling(9).min())  / 2
    kijun   = (high.rolling(26).max() + low.rolling(26).min()) / 2
    span_a  = ((tenkan + kijun) / 2).shift(26)
    span_b  = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)
    ichi_atas = harga > max(span_a.iloc[-1], span_b.iloc[-1])
    tk_up     = (tenkan.iloc[-1] > kijun.iloc[-1] and
                 tenkan.iloc[-2] <= kijun.iloc[-2])

    vol_avg    = volume.rolling(20).mean().iloc[-1]
    vol_skrng  = volume.iloc[-1]
    vol_tinggi = vol_skrng > (vol_avg * 1.5)
    vol_ratio  = vol_skrng / vol_avg

    rsi_ser  = 100 - (100 / (1 + gain / loss))
    harga_r  = close.iloc[-5:].values
    rsi_r    = rsi_ser.iloc[-5:].values
    bull_div = harga_r[-1] < harga_r[0] and rsi_r[-1] > rsi_r[0]
    bear_div = harga_r[-1] > harga_r[0] and rsi_r[-1] < rsi_r[0]

    momentum_24h = ((harga - close.iloc[-25]) / close.iloc[-25]) * 100
    ema20        = close.ewm(span=20, adjust=False).mean().iloc[-1]
    ema50        = close.ewm(span=50, adjust=False).mean().iloc[-1]
    ema_bull     = ema20 > ema50

    return {
        "harga": harga, "rsi": rsi,
        "macd_up": macd_up, "macd_down": macd_down,
        "bb_bawah": bb_bawah, "bb_atas": bb_atas,
        "atr": atr, "ichi_atas": ichi_atas, "tk_up": tk_up,
        "vol_tinggi": vol_tinggi, "vol_ratio": vol_ratio,
        "bull_div": bull_div, "bear_div": bear_div,
        "momentum": momentum_24h, "ema_bull": ema_bull,
        "ema20": ema20, "ema50": ema50
    }

# ── MULTI TIMEFRAME ───────────────────────────
def analisis_timeframe(symbol, interval, nama_tf):
    df = get_data(symbol, interval=interval)
    if df is None:
        return {"tf": nama_tf, "konfirmasi": False, "skor": 0}
    ind  = hitung_indikator(df)
    skor = sum([ind["rsi"] < 50, ind["macd_up"], ind["ema_bull"],
                ind["ichi_atas"] or ind["tk_up"], ind["momentum"] > 0])
    return {"tf": nama_tf, "konfirmasi": skor >= 3, "skor": skor, "ind": ind}

def multi_timeframe_analysis(symbol):
    tf_list   = [
        (Client.KLINE_INTERVAL_1HOUR, "1H"),
        (Client.KLINE_INTERVAL_4HOUR, "4H"),
        (Client.KLINE_INTERVAL_1DAY,  "1D"),
    ]
    hasil_tf  = [analisis_timeframe(symbol, iv, nm) for iv, nm in tf_list]
    n_konfirm = sum(1 for h in hasil_tf if h["konfirmasi"])
    return {
        "timeframes": hasil_tf, "n_konfirmasi": n_konfirm,
        "semua_bullish": n_konfirm == 3,
        "cukup_bullish": n_konfirm >= TF_REQUIRED,
        "summary": " | ".join([
            f"{h['tf']}:{'✅' if h['konfirmasi'] else '❌'}({h['skor']}/5)"
            for h in hasil_tf
        ])
    }

# ── TRAILING STOP SPOT ────────────────────────
def update_trailing_spot(symbol, harga_skrng):
    if symbol not in posisi_spot: return False
    pos = posisi_spot[symbol]
    if not pos["aktif"]: return False
    profit_pct   = ((harga_skrng - pos["harga_beli"]) / pos["harga_beli"]) * 100
    harga_tinggi = pos.get("harga_tertinggi", pos["harga_beli"])
    if harga_skrng > harga_tinggi:
        posisi_spot[symbol]["harga_tertinggi"] = harga_skrng
        harga_tinggi = harga_skrng
    if not pos.get("trailing_aktif") and profit_pct >= TRAILING_AKTIVASI:
        posisi_spot[symbol]["trailing_aktif"] = True
        kirim_telegram(
            f"🔄 <b>Trailing Aktif (Spot) - {symbol}</b>\n"
            f"📈 Profit: <b>+{profit_pct:.2f}%</b>"
        )
    if pos.get("trailing_aktif"):
        sl_baru = harga_tinggi * (1 - TRAILING_JARAK / 100)
        if sl_baru > pos["stop_loss"]:
            posisi_spot[symbol]["stop_loss"] = sl_baru
            return True
    return False

# ── PREDIKSI ML ───────────────────────────────
def prediksi_ml(df):
    if model_ml is None: return "HOLD", 50.0
    try:
        d     = df.copy()
        delta = d['close'].diff()
        gain  = delta.where(delta > 0, 0).rolling(14).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
        d['rsi'] = 100 - (100 / (1 + gain / loss))
        ema12 = d['close'].ewm(span=12,adjust=False).mean()
        ema26 = d['close'].ewm(span=26,adjust=False).mean()
        d['macd']        = ema12-ema26
        d['macd_signal'] = d['macd'].ewm(span=9,adjust=False).mean()
        d['macd_hist']   = d['macd']-d['macd_signal']
        sma20 = d['close'].rolling(20).mean()
        std20 = d['close'].rolling(20).std()
        bb_upper = sma20+(std20*2); bb_lower = sma20-(std20*2)
        d['bb_width'] = (bb_upper-bb_lower)/sma20
        d['bb_pos']   = (d['close']-bb_lower)/(bb_upper-bb_lower)
        tr = pd.concat([d['high']-d['low'],
                        (d['high']-d['close'].shift()).abs(),
                        (d['low']-d['close'].shift()).abs()],axis=1).max(axis=1)
        d['atr']         = tr.rolling(14).mean()
        d['atr_pct']     = d['atr']/d['close']*100
        d['vol_ratio']   = d['volume']/d['volume'].rolling(20).mean()
        d['ema20']       = d['close'].ewm(span=20,adjust=False).mean()
        d['ema50']       = d['close'].ewm(span=50,adjust=False).mean()
        d['ema_diff']    = (d['ema20']-d['ema50'])/d['close']*100
        d['momentum_3']  = d['close'].pct_change(3)*100
        d['momentum_7']  = d['close'].pct_change(7)*100
        d['momentum_14'] = d['close'].pct_change(14)*100
        d['candle_body'] = (d['close']-d['open']).abs()/d['close']*100
        d['candle_dir']  = (d['close']>d['open']).astype(int)
        d = d.dropna()
        X = d[features_ml].iloc[-1:].values
        X_scaled = scaler_ml.transform(X)
        pred  = model_ml.predict(X_scaled)[0]
        proba = model_ml.predict_proba(X_scaled)[0]
        return ("BUY" if pred == 1 else "HOLD"), proba[pred]*100
    except:
        return "HOLD", 50.0

# ── CACHE ONCHAIN & GEO ───────────────────────
def get_onchain_cached():
    global onchain_cache
    sekarang = time.time()
    if onchain_cache["data"] is None or sekarang-onchain_cache["waktu"] > 300:
        try:
            onchain_cache["data"] = get_onchain_score()
            onchain_cache["waktu"] = sekarang
        except:
            if onchain_cache["data"] is None:
                onchain_cache["data"] = {
                    "skor_buy": 0, "fear_greed": {"score": 50},
                    "funding_rate": {"rate": 0}, "btc_dominance": {"dominance": 50}
                }
    return onchain_cache["data"]

def get_geo_cached():
    global geo_cache
    sekarang = time.time()
    if geo_cache["data"] is None or sekarang-geo_cache["waktu"] > 600:
        try:
            geo_cache["data"] = get_geo_score()
            geo_cache["waktu"] = sekarang
            if geo_cache["data"].get("alert"):
                kirim_telegram("🚨 <b>GEO ALERT!</b>\n\n" + geo_cache["data"]["alert_pesan"])
        except:
            if geo_cache["data"] is None:
                geo_cache["data"] = {
                    "skor_buy": 0, "skor_sell": 0, "sentiment": "NETRAL",
                    "rata_skor": 0.0, "n_berita": 0, "alert": False, "alert_pesan": ""
                }
    return geo_cache["data"]

# ══════════════════════════════════════════════
# HITUNG SKOR KOIN (v9.6 Multi Exchange)
# ══════════════════════════════════════════════

def hitung_skor_koin(symbol):
    df = get_data(symbol, interval=Client.KLINE_INTERVAL_1HOUR)
    if df is None: return None

    ind              = hitung_indikator(df)
    ml_pred, ml_conf = prediksi_ml(df)
    onchain          = get_onchain_cached()
    geo              = get_geo_cached()

    skor   = 0
    detail = []

    # ── Teknikal ──
    if ind["rsi"] < 35:    skor += 1; detail.append(f"RSI({ind['rsi']:.1f})")
    if ind["macd_up"]:     skor += 1; detail.append("MACD↑")
    if ind["bb_bawah"]:    skor += 1; detail.append("BB↓")
    if ind["ichi_atas"] or ind["tk_up"]: skor += 1; detail.append("Ichi✓")
    if ind["vol_tinggi"]:  skor += 1; detail.append(f"Vol{ind['vol_ratio']:.1f}x")
    if ind["bull_div"]:    skor += 1; detail.append("BullDiv✓")
    if ind["momentum"] > 3: skor += 1; detail.append(f"Mom+{ind['momentum']:.1f}%")

    # Sinyal bearish
    if ind["rsi"] > 70:      skor -= 1; detail.append(f"RSI OB({ind['rsi']:.1f})")
    if ind["macd_down"]:     skor -= 1; detail.append("MACD↓")
    if ind["bb_atas"]:       skor -= 1; detail.append("BB↑")
    if ind["bear_div"]:      skor -= 1; detail.append("BearDiv⚠️")
    if ind["momentum"] < -3: skor -= 1; detail.append(f"Mom{ind['momentum']:.1f}%")

    if ml_pred == "BUY" and ml_conf >= 60:
        skor += 2; detail.append(f"ML({ml_conf:.0f}%)")
    if onchain["skor_buy"] >= 1:
        skor += onchain["skor_buy"]

    sinyal_bayes = bayes.buat_sinyal_list(
        rsi=ind["rsi"], macd_up=ind["macd_up"], macd_down=ind["macd_down"],
        bb_bawah=ind["bb_bawah"], bb_atas=ind["bb_atas"],
        ichi_bullish=(ind["ichi_atas"] or ind["tk_up"]),
        vol_tinggi=ind["vol_tinggi"], bull_div=ind["bull_div"],
        ml_pred=ml_pred, ml_conf=ml_conf,
        fear_score=onchain["fear_greed"]["score"],
        funding_rate=onchain["funding_rate"]["rate"],
        btc_dom=onchain["btc_dominance"]["dominance"]
    )
    bayes_hasil = bayes.hitung_probabilitas(sinyal_bayes)
    if bayes_hasil["keputusan"] == "BUY_KUAT":
        skor += 3; detail.append(f"Bayes{bayes_hasil['prob_buy']}%🔥")
    elif bayes_hasil["keputusan"] == "BUY_LEMAH":
        skor += 1; detail.append(f"Bayes{bayes_hasil['prob_buy']}%✅")

    # Geo
    if geo["skor_buy"] >= 2:    skor += geo["skor_buy"]; detail.append(f"🌍+{geo['skor_buy']}")
    elif geo["skor_buy"] == 1:  skor += 1; detail.append("🌍+1")
    if geo["skor_sell"] >= 3:   skor -= 4; detail.append("🔴GeoBlock")
    elif geo["skor_sell"] == 2: skor -= 2; detail.append("🟠Geo-2")
    elif geo["skor_sell"] == 1: skor -= 1; detail.append("🟡Geo-1")

    # MTF
    mtf = multi_timeframe_analysis(symbol)
    if mtf["semua_bullish"]:   skor += 3; detail.append("📊MTF3/3🔥")
    elif mtf["cukup_bullish"]: skor += 1; detail.append(f"📊MTF{mtf['n_konfirmasi']}/3✅")
    else:                       skor -= 1; detail.append(f"📊MTF{mtf['n_konfirmasi']}/3❌")

    # Order Book (Binance)
    ob = analisis_orderbook(client, symbol)
    if ob["block_entry"]:
        skor -= 5; detail.append("🚫OB:MANIP!")
        kirim_telegram(
            f"🚫 <b>MANIPULASI - {symbol}</b>\n\n"
            + "\n".join(ob["spoof"]["detail"])
            + f"\n⚠️ Entry diblokir!\n🕐 {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
    else:
        if ob["skor_buy"] >= 3:    skor += 3; detail.append(f"📗OB+{ob['skor_buy']}🔥")
        elif ob["skor_buy"] >= 1:  skor += ob["skor_buy"]; detail.append(f"📗OB+{ob['skor_buy']}")
        if ob["skor_sell"] >= 2:   skor -= ob["skor_sell"]; detail.append(f"📕OB-{ob['skor_sell']}")
        elif ob["skor_sell"] == 1: skor -= 1; detail.append("📕OB-1")
    if ob["iceberg"]["iceberg_side"] == "BUY":  detail.append("🧊BUY✅")
    if ob["iceberg"]["iceberg_side"] == "SELL": skor -= 1; detail.append("🧊SELL⚠️")

    # ══════════════════════════════════════════
    # ── MULTI EXCHANGE ANALYSIS ───────────────
    # ══════════════════════════════════════════
    mx = analisis_multi_exchange(client, symbol)

    # Cross OB konsensus dari semua exchange
    if mx["skor_buy"] >= 3:
        skor += 3; detail.append(f"🌐MX+{mx['skor_buy']}🔥")
    elif mx["skor_buy"] >= 1:
        skor += mx["skor_buy"]; detail.append(f"🌐MX+{mx['skor_buy']}")

    if mx["skor_sell"] >= 3:
        skor -= 3; detail.append(f"🌐MX-{mx['skor_sell']}🔴")
    elif mx["skor_sell"] >= 1:
        skor -= mx["skor_sell"]; detail.append(f"🌐MX-{mx['skor_sell']}")

    # Info arbitrase
    if mx["arbitrase"]["ada_peluang"]:
        detail.append(
            f"🔄Arbi:{mx['arbitrase']['net_profit_pct']:+.3f}%"
            f"({mx['arbitrase']['exchange_beli']}→"
            f"{mx['arbitrase']['exchange_jual']})"
        )
    # ══════════════════════════════════════════

    return {
        "symbol": symbol, "skor": skor,
        "harga": ind["harga"], "rsi": ind["rsi"],
        "atr": ind["atr"], "momentum": ind["momentum"],
        "ml_pred": ml_pred, "ml_conf": ml_conf,
        "bayes": bayes_hasil["prob_buy"],
        "detail": detail, "ind": ind,
        "geo": geo, "mtf": mtf, "ob": ob,
        "mx": mx,    # ← Data multi exchange
    }

# ── SCAN SEMUA KOIN ───────────────────────────
def scan_semua_koin():
    print(f"\n🔍 Scanning {len(KOIN_LIST)} koin (Multi Exchange)...")
    hasil_scan = []
    for symbol in KOIN_LIST:
        spot_aktif    = symbol in posisi_spot and posisi_spot[symbol]["aktif"]
        futures_aktif = symbol in posisi_futures and posisi_futures[symbol].get("aktif")
        if spot_aktif or futures_aktif:
            mode = "SPOT" if spot_aktif else "FUTURES"
            print(f"  ⏭️  {symbol:12} - {mode} aktif, skip")
            continue
        try:
            hasil = hitung_skor_koin(symbol)
            if hasil:
                mode_fut = tentukan_mode_futures(
                    hasil["skor"], hasil["ind"],
                    hasil["geo"], hasil["mtf"], hasil["ob"]
                )
                mx    = hasil["mx"]
                arbi  = "🔄" if mx["arbitrase"]["ada_peluang"] else ""
                emoji = "🔥" if hasil["skor"] >= MIN_SCORE_SPOT else (
                        "📉" if hasil["skor"] <= -2 else "⚪")
                print(f"  {emoji} {symbol:12} "
                      f"Skor:{hasil['skor']:+3} | "
                      f"MTF:{hasil['mtf']['n_konfirmasi']}/3 | "
                      f"MX:{mx['cross_ob']['sinyal'][:8]} | "
                      f"FUT:{mode_fut}{arbi}")
                hasil["mode_futures"] = mode_fut
                hasil_scan.append(hasil)
        except Exception as e:
            print(f"  ⚠️  {symbol}: {e}")
    hasil_scan.sort(key=lambda x: abs(x["skor"]), reverse=True)
    return hasil_scan

# ── SCAN ARBITRASE ────────────────────────────
def cek_arbitrase_semua_koin():
    """Scan peluang arbitrase di semua koin"""
    print("\n🔄 Cek Arbitrase:")
    ada_peluang = False
    for symbol in KOIN_LIST:
        try:
            arbi = scan_arbitrase(client, symbol)
            if arbi["ada_peluang"]:
                ada_peluang = True
                print(f"  🔄 {symbol}: {arbi['detail']}")
                kirim_telegram(
                    f"🔄 <b>PELUANG ARBITRASE!</b>\n\n"
                    f"💎 Koin    : <b>{symbol}</b>\n"
                    f"📉 Beli di : <b>{arbi['exchange_beli'].upper()}</b> "
                    f"${arbi['harga_beli']:,.4f}\n"
                    f"📈 Jual di : <b>{arbi['exchange_jual'].upper()}</b> "
                    f"${arbi['harga_jual']:,.4f}\n"
                    f"💰 Spread  : {arbi['spread_pct']:.3f}%\n"
                    f"✅ Net Profit: <b>{arbi['net_profit_pct']:+.3f}%</b>\n"
                    f"🕐 {time.strftime('%Y-%m-%d %H:%M:%S')}"
                )
        except Exception as e:
            pass
    if not ada_peluang:
        print("  ⚪ Tidak ada peluang arbitrase saat ini")

# ── CEK SL/TP SPOT ────────────────────────────
def cek_semua_sl_tp_spot():
    waktu = time.strftime("%Y-%m-%d %H:%M:%S")
    for symbol in list(posisi_spot.keys()):
        pos = posisi_spot[symbol]
        if not pos["aktif"]: continue
        try:
            harga = float(client.get_symbol_ticker(symbol=symbol)["price"])
        except Exception as e:
            print(f"  ⚠️  Gagal harga {symbol}: {e}"); continue

        profit_pct = ((harga - pos["harga_beli"]) / pos["harga_beli"]) * 100
        update_trailing_spot(symbol, harga)
        trail = " 🔄" if pos.get("trailing_aktif") else ""
        print(f"  💰 {symbol}: ${harga:,.4f} | P/L:{profit_pct:+.2f}%{trail}")

        if harga >= pos["take_profit"]:
            try: client.order_market_sell(symbol=symbol, quantity=pos["qty"])
            except Exception as e: print(f"  ⚠️  Gagal sell: {e}")
            simpan_transaksi(symbol, pos["harga_beli"], harga,
                             pos["waktu_beli"], waktu, "SPOT_TP")
            kirim_telegram(
                f"🎯 <b>SPOT TP! - {symbol}</b>\n"
                f"💰 Entry: ${pos['harga_beli']:,.4f}\n"
                f"💰 Exit : ${harga:,.4f}\n"
                f"📈 Profit: <b>+{profit_pct:.2f}%</b> ✅\n"
                f"🕐 {waktu}"
            )
            posisi_spot[symbol]["aktif"] = False

        elif harga <= pos["stop_loss"]:
            alasan = "SPOT_TRAILING" if pos.get("trailing_aktif") else "SPOT_SL"
            try: client.order_market_sell(symbol=symbol, quantity=pos["qty"])
            except Exception as e: print(f"  ⚠️  Gagal sell: {e}")
            simpan_transaksi(symbol, pos["harga_beli"], harga,
                             pos["waktu_beli"], waktu, alasan)
            emoji = "🔄" if pos.get("trailing_aktif") else "🛑"
            kirim_telegram(
                f"{emoji} <b>SPOT SL! - {symbol}</b>\n"
                f"💰 Entry: ${pos['harga_beli']:,.4f}\n"
                f"💰 Exit : ${harga:,.4f}\n"
                f"📉 P/L  : <b>{profit_pct:.2f}%</b> ❌\n"
                f"🕐 {waktu}"
            )
            posisi_spot[symbol]["aktif"] = False

# ── HITUNG QTY SPOT ───────────────────────────
def hitung_qty_spot(symbol, harga):
    qty = TRADE_USDT_SPOT / harga
    if harga > 1000:   return round(qty, 3)
    elif harga > 1:    return round(qty, 2)
    else:              return round(qty, 0)

# ── BUKA POSISI SPOT ──────────────────────────
def buka_posisi_spot(hasil):
    waktu  = time.strftime("%Y-%m-%d %H:%M:%S")
    symbol = hasil["symbol"]; harga = hasil["harga"]; atr = hasil["atr"]
    qty    = hitung_qty_spot(symbol, harga)
    sl     = harga - (atr * 1.5); tp = harga + (atr * 3.0)
    sl_pct = ((harga - sl) / harga) * 100
    tp_pct = ((tp - harga) / harga) * 100

    print(f"\n  💰 [{symbol}] SPOT BUY! Skor:{hasil['skor']} Qty:{qty}")
    try: client.order_market_buy(symbol=symbol, quantity=qty)
    except Exception as e: print(f"  ⚠️  Gagal buy: {e}"); return

    posisi_spot[symbol] = {
        "aktif": True, "harga_beli": harga, "harga_tertinggi": harga,
        "stop_loss": sl, "take_profit": tp, "waktu_beli": waktu,
        "qty": qty, "atr": atr, "trailing_aktif": False,
    }

    mtf = hasil.get("mtf", {}); ob = hasil.get("ob", {})
    geo = hasil.get("geo", {}); mx = hasil.get("mx", {})

    # Harga dari semua exchange
    harga_mx = ""
    if mx.get("all_prices"):
        harga_mx = " | ".join([
            f"{ex.upper()[:3]}:${d['price']:,.2f}"
            for ex, d in mx["all_prices"].get("per_exchange", {}).items()
        ])

    kirim_telegram(
        f"💰 <b>SPOT BUY - {symbol}</b>\n"
        f"⭐ Skor    : <b>{hasil['skor']}</b>\n"
        f"🤖 ML      : {hasil['ml_pred']} ({hasil['ml_conf']:.0f}%)\n"
        f"📊 MTF     : {mtf.get('summary','N/A')}\n"
        f"📗 OB      : {ob.get('depth',{}).get('sinyal','N/A')}\n"
        f"🌐 Multi-Ex: {mx.get('cross_ob',{}).get('sinyal','N/A')}\n"
        + (f"💱 Harga   : {harga_mx}\n" if harga_mx else "")
        + f"🌍 Geo     : {geo.get('sentiment','N/A')}\n\n"
        f"💰 Entry : <b>${harga:,.4f}</b>\n"
        f"🔢 Qty   : {qty}\n"
        f"🛑 SL    : <b>${sl:,.4f}</b> (-{sl_pct:.1f}%)\n"
        f"🎯 TP    : <b>${tp:,.4f}</b> (+{tp_pct:.1f}%)\n"
        f"🔄 Trailing: aktif setelah +{TRAILING_AKTIVASI}%\n\n"
        f"✅ {' | '.join(hasil['detail'])}\n🕐 {waktu}"
    )

# ── STATUS SPOT ───────────────────────────────
def print_status_spot():
    aktif = [(s, p) for s, p in posisi_spot.items() if p["aktif"]]
    if not aktif:
        print("  📭 Tidak ada posisi spot aktif")
        return
    print(f"  💰 Spot aktif: {len(aktif)}/{MAX_POSISI_SPOT}")
    for symbol, pos in aktif:
        try:
            harga  = float(client.get_symbol_ticker(symbol=symbol)["price"])
            pl_pct = ((harga - pos["harga_beli"]) / pos["harga_beli"]) * 100
            trail  = " 🔄" if pos.get("trailing_aktif") else ""
            print(f"  {'📈' if pl_pct>=0 else '📉'} {symbol:12} "
                  f"${pos['harga_beli']:,.4f}→${harga:,.4f} "
                  f"P/L:{pl_pct:+.2f}%{trail}")
        except: pass

# ══════════════════════════════════════════════
# SATU SIKLUS HYBRID MULTI EXCHANGE
# ══════════════════════════════════════════════

def jalankan_siklus(siklus):
    waktu = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*60}")
    print(f"⏰ {waktu} | Siklus #{siklus} | 🌐 MULTI EXCHANGE")
    print(f"{'='*60}")

    # ── Cek posisi aktif ──
    print("\n💰 Posisi SPOT:")
    print_status_spot()
    cek_semua_sl_tp_spot()

    print("\n⚡ Posisi FUTURES:")
    print_status_futures()
    cek_posisi_futures(client, kirim_telegram, simpan_transaksi)

    # ── Cek arbitrase setiap 3 siklus ──
    if siklus % 3 == 0:
        cek_arbitrase_semua_koin()

    # ── Hitung slot ──
    n_spot    = sum(1 for p in posisi_spot.values() if p["aktif"])
    n_futures = sum(1 for p in posisi_futures.values() if p.get("aktif"))

    print(f"\n  💰 Spot   : {n_spot}/{MAX_POSISI_SPOT}")
    print(f"  ⚡ Futures: {n_futures}/{MAX_POSISI_FUTURES}")

    slot_spot    = MAX_POSISI_SPOT - n_spot
    slot_futures = MAX_POSISI_FUTURES - n_futures

    if slot_spot <= 0 and slot_futures <= 0:
        print(f"  ✋ Semua slot penuh!")
        return

    # ── Scan koin ──
    hasil_scan = scan_semua_koin()

    for hasil in hasil_scan:
        if slot_spot <= 0 and slot_futures <= 0:
            break

        symbol     = hasil["symbol"]
        skor       = hasil["skor"]
        mode_fut   = hasil["mode_futures"]
        harga      = hasil["harga"]
        atr        = hasil["atr"]
        detail_str = " | ".join(hasil["detail"])

        if (symbol in posisi_spot and posisi_spot[symbol]["aktif"]) or \
           (symbol in posisi_futures and posisi_futures[symbol].get("aktif")):
            continue

        # ══ KEPUTUSAN HYBRID ══
        if mode_fut == "LONG" and slot_futures > 0:
            print(f"\n  ⚡ [{symbol}] → FUTURES LONG (Skor:{skor})")
            sukses = buka_long(
                client, symbol, harga, atr,
                skor, detail_str, kirim_telegram
            )
            if sukses:
                slot_futures -= 1; n_futures += 1

        elif mode_fut == "SHORT" and slot_futures > 0:
            print(f"\n  📉 [{symbol}] → FUTURES SHORT (Skor:{skor})")
            sukses = buka_short(
                client, symbol, harga, atr,
                skor, detail_str, kirim_telegram
            )
            if sukses:
                slot_futures -= 1; n_futures += 1

        elif skor >= MIN_SCORE_SPOT and slot_spot > 0 \
             and hasil["mtf"]["cukup_bullish"] \
             and not hasil["ob"]["block_entry"]:
            print(f"\n  💰 [{symbol}] → SPOT BUY (Skor:{skor})")
            buka_posisi_spot(hasil)
            slot_spot -= 1; n_spot += 1

# ── MAIN ──────────────════════════════════════
print("=" * 60)
print("   BINANCE TRADING BOT v9.6 - MULTI EXCHANGE")
print(f"   🌐 Exchange : Binance + Bybit + OKX + Coinbase")
print(f"   💰 Spot     : Max {MAX_POSISI_SPOT} posisi, ${TRADE_USDT_SPOT}/pos")
print(f"   ⚡ Futures  : Max {MAX_POSISI_FUTURES} posisi, {LEVERAGE}x leverage")
print(f"   🔄 Arbitrase: Auto-detect setiap 3 siklus")
print("=" * 60)

ml_aktif = load_model()
geo_awal = get_geo_cached()

# Cek exchange yang tersedia
exchange_aktif = ["Binance ✅"]
if BYBIT_KEY:    exchange_aktif.append("Bybit ✅")
else:            exchange_aktif.append("Bybit ⚠️(no key)")
if OKX_KEY:      exchange_aktif.append("OKX ✅")
else:            exchange_aktif.append("OKX ⚠️(no key)")
if CB_KEY:       exchange_aktif.append("Coinbase ✅")
else:            exchange_aktif.append("Coinbase ⚠️(no key)")

kirim_telegram(
    "🚀 <b>Trading Bot v9.6 - MULTI EXCHANGE!</b>\n\n"
    f"🌐 <b>Exchange:</b>\n"
    + "\n".join([f"   {ex}" for ex in exchange_aktif])
    + f"\n\n"
    f"🔄 Arbitrase Scanner : ✅\n"
    f"📊 Cross OB Analysis : ✅\n"
    f"⚡ Futures {LEVERAGE}x        : ✅\n"
    f"📊 Multi TF (1H+4H+1D): ✅\n"
    f"🌍 Geo               : {geo_awal['sentiment']}\n"
    f"🤖 ML                : {'✅' if ml_aktif else '⚠️'}\n"
    "📌 Status: ✅ Berjalan 24/7"
)

print("\n💰 Saldo semua exchange:")
cek_saldo()
print("=" * 60)

siklus = 0
while bot_running:
    siklus += 1
    try:
        jalankan_siklus(siklus)
        reconnect_count = 0
        print(f"\n⏳ Tunggu {SCAN_INTERVAL//60} menit...")
        time.sleep(SCAN_INTERVAL)

    except (BinanceAPIException, ConnectionError,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout) as e:
        print(f"\n📡 Koneksi error: {e}")
        reconnect_client()

    except Exception as e:
        print(f"\n⚠️  Error siklus #{siklus}: {e}")
        kirim_telegram(
            f"⚠️ <b>Bot Error #{siklus}</b>\n\n"
            f"<code>{str(e)[:200]}</code>\n"
            f"🔄 Tetap berjalan...\n"
            f"🕐 {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        time.sleep(30)