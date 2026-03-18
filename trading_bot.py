# ============================================
# BINANCE TRADING BOT v9.2 - CLOUD EDITION
# Auto-reconnect, graceful shutdown,
# health check & robust error handling
# ============================================

from binance.client import Client
from binance.exceptions import BinanceAPIException
from onchain import get_onchain_score
from bayesian_model import BayesianTradingModel
from geopolitik import get_geo_score
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
from datetime import datetime
warnings.filterwarnings('ignore')

# ── KONFIGURASI ───────────────────────────────
API_KEY    = os.environ.get("BINANCE_API_KEY",    "U0LiHucqGcPDj3L8bAHp0Qzfa9ocMxbEilQJeOihSwpmioNnl33WV4wyJcytSkkG")
API_SECRET = os.environ.get("BINANCE_API_SECRET", "pg412rXf0oSLFUqSn0914FCyYnJtZ32GCtBEwGPjT9UdawZz1BX2rVpxuwJmn0up")
TG_TOKEN   = os.environ.get("TG_TOKEN",           "8735682075:AAE6N7YtKgGkxK-1dZl-RVKCvQplGgaUN8M")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID",         "8604266478")

# ── DAFTAR KOIN ───────────────────────────────
KOIN_LIST = [
    "BTCUSDT", "ETHUSDT", "BNBUSDT",
    "SOLUSDT", "ADAUSDT", "XRPUSDT",
    "DOGEUSDT", "AVAXUSDT", "DOTUSDT",
    "LINKUSDT"
]

# ── KONFIGURASI TRADING ───────────────────────
INTERVAL           = Client.KLINE_INTERVAL_1HOUR
MAX_POSISI         = 3
MIN_SCORE_EKSEKUSI = 6
TRADE_USDT         = 100.0

# ── KONFIGURASI RECONNECT ─────────────────────
MAX_RECONNECT      = 10       # Maksimal percobaan reconnect
RECONNECT_DELAY    = 30       # Detik antar reconnect
SCAN_INTERVAL      = 300      # 5 menit antar siklus

# ── STATE ─────────────────────────────────────
semua_posisi  = {}
onchain_cache = {"data": None, "waktu": 0}
geo_cache     = {"data": None, "waktu": 0}
bot_running   = True          # Flag untuk graceful shutdown
reconnect_count = 0

# ── INIT CLIENT ───────────────────────────────
def buat_client():
    """Buat Binance client dengan retry"""
    return Client(API_KEY, API_SECRET, testnet=True)

client = buat_client()

# Inisialisasi Bayesian Model
bayes = BayesianTradingModel()
bayes.load_model()

# ── GRACEFUL SHUTDOWN ─────────────────────────
def handle_shutdown(signum, frame):
    """Tangani SIGTERM/SIGINT dengan bersih"""
    global bot_running
    print("\n⛔ Sinyal shutdown diterima, menghentikan bot...")
    bot_running = False
    kirim_telegram(
        "⛔ <b>Bot dihentikan dengan aman</b>\n"
        f"🕐 {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
        "📌 Semua posisi tetap terbuka di exchange"
    )
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT,  handle_shutdown)

# ── FUNGSI: KIRIM TELEGRAM ────────────────────
def kirim_telegram(pesan, retry=3):
    """Kirim pesan Telegram dengan retry otomatis"""
    for attempt in range(retry):
        try:
            url  = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
            data = {
                "chat_id"   : TG_CHAT_ID,
                "text"      : pesan,
                "parse_mode": "HTML"
            }
            resp = requests.post(url, data=data, timeout=15)
            if resp.status_code == 200:
                return True
            else:
                print(f"  ⚠️  Telegram HTTP {resp.status_code}")
        except Exception as e:
            print(f"  ⚠️  Telegram gagal (percobaan {attempt+1}): {e}")
            if attempt < retry - 1:
                time.sleep(5)
    return False

# ── FUNGSI: RECONNECT CLIENT ──────────────────
def reconnect_client():
    """Reconnect ke Binance dengan exponential backoff"""
    global client, reconnect_count
    reconnect_count += 1

    if reconnect_count > MAX_RECONNECT:
        pesan = (
            "🚨 <b>Bot OFFLINE!</b>\n\n"
            f"❌ Gagal reconnect setelah {MAX_RECONNECT}x percobaan\n"
            f"🕐 {time.strftime('%Y-%m-%d %H:%M:%S')}\n"
            "⚠️ Perlu restart manual!"
        )
        kirim_telegram(pesan)
        print(f"\n🚨 Maksimal reconnect tercapai! Bot berhenti.")
        sys.exit(1)

    delay = min(RECONNECT_DELAY * reconnect_count, 300)  # Max 5 menit
    print(f"\n  🔄 Reconnect #{reconnect_count} dalam {delay} detik...")

    if reconnect_count == 1:
        kirim_telegram(
            "⚠️ <b>Koneksi terputus, mencoba reconnect...</b>\n"
            f"🔄 Percobaan ke-{reconnect_count}/{MAX_RECONNECT}\n"
            f"🕐 {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )

    time.sleep(delay)

    try:
        client = buat_client()
        # Test koneksi
        client.ping()
        print(f"  ✅ Reconnect berhasil!")
        kirim_telegram(
            "✅ <b>Koneksi pulih!</b>\n"
            f"🔄 Berhasil reconnect ke-{reconnect_count}\n"
            f"🕐 {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        reconnect_count = 0  # Reset counter
        return True
    except Exception as e:
        print(f"  ❌ Reconnect gagal: {e}")
        return False

# ── FUNGSI: SIMPAN TRANSAKSI ──────────────────
def simpan_transaksi(symbol, harga_beli, harga_jual,
                     waktu_beli, waktu_jual, alasan):
    profit_pct = ((harga_jual - harga_beli) / harga_beli) * 100
    transaksi  = {
        "symbol"     : symbol,
        "harga_beli" : harga_beli,
        "harga_jual" : harga_jual,
        "profit_pct" : round(profit_pct, 4),
        "waktu_beli" : waktu_beli,
        "waktu_jual" : waktu_jual,
        "alasan"     : alasan
    }
    riwayat = []
    if os.path.exists("riwayat_trade.json"):
        with open("riwayat_trade.json", "r") as f:
            riwayat = json.load(f)
    riwayat.append(transaksi)
    with open("riwayat_trade.json", "w") as f:
        json.dump(riwayat, f, indent=2)
    print(f"  💾 [{symbol}] Tersimpan! P/L: {profit_pct:+.2f}%")

# ── FUNGSI: CEK SALDO ─────────────────────────
def cek_saldo():
    saldo = {}
    try:
        akun = client.get_account()
        for aset in akun["balances"]:
            if float(aset["free"]) > 0:
                saldo[aset["asset"]] = float(aset["free"])
        usdt = saldo.get("USDT", 0)
        print(f"  Saldo USDT : {usdt:,.2f}")
    except Exception as e:
        print(f"  ⚠️  Gagal cek saldo: {e}")
    return saldo

# ── FUNGSI: LOAD MODEL ML ─────────────────────
model_ml    = None
scaler_ml   = None
features_ml = None

def load_model():
    global model_ml, scaler_ml, features_ml
    try:
        model_ml    = joblib.load("model_ml.pkl")
        scaler_ml   = joblib.load("scaler_ml.pkl")
        features_ml = joblib.load("features_ml.pkl")
        print("  🤖 Model ML berhasil dimuat!")
        return True
    except:
        print("  ⚠️  Model ML belum ada!")
        return False

# ── FUNGSI: AMBIL DATA KOIN ───────────────────
def get_data(symbol):
    try:
        klines = client.get_klines(
            symbol=symbol, interval=INTERVAL, limit=150)
        df = pd.DataFrame(klines, columns=[
            'time','open','high','low','close','volume',
            'close_time','quote_vol','trades',
            'taker_base','taker_quote','ignore'
        ])
        for col in ['open','high','low','close','volume']:
            df[col] = df[col].astype(float)
        return df
    except Exception as e:
        print(f"  ⚠️  Gagal ambil data {symbol}: {e}")
        return None

# ── FUNGSI: HITUNG SEMUA INDIKATOR ───────────
def hitung_indikator(df):
    close  = df['close']
    high   = df['high']
    low    = df['low']
    volume = df['volume']

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
    bb_upper = (sma20 + std20 * 2).iloc[-1]
    bb_lower = (sma20 - std20 * 2).iloc[-1]
    harga    = close.iloc[-1]
    bb_bawah = harga <= bb_lower
    bb_atas  = harga >= bb_upper

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

    momentum_24h = ((harga - close.iloc[-25]) / close.iloc[-25]) * 100

    return {
        "harga"      : harga,
        "rsi"        : rsi,
        "macd_up"    : macd_up,
        "macd_down"  : macd_down,
        "bb_bawah"   : bb_bawah,
        "bb_atas"    : bb_atas,
        "atr"        : atr,
        "ichi_atas"  : ichi_atas,
        "tk_up"      : tk_up,
        "vol_tinggi" : vol_tinggi,
        "vol_ratio"  : vol_ratio,
        "bull_div"   : bull_div,
        "momentum"   : momentum_24h
    }

# ── FUNGSI: PREDIKSI ML ───────────────────────
def prediksi_ml(df):
    if model_ml is None:
        return "HOLD", 50.0
    try:
        d     = df.copy()
        delta = d['close'].diff()
        gain  = delta.where(delta > 0, 0).rolling(14).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
        d['rsi'] = 100 - (100 / (1 + gain / loss))
        ema12 = d['close'].ewm(span=12, adjust=False).mean()
        ema26 = d['close'].ewm(span=26, adjust=False).mean()
        d['macd']        = ema12 - ema26
        d['macd_signal'] = d['macd'].ewm(span=9, adjust=False).mean()
        d['macd_hist']   = d['macd'] - d['macd_signal']
        sma20 = d['close'].rolling(20).mean()
        std20 = d['close'].rolling(20).std()
        bb_upper = sma20 + (std20 * 2)
        bb_lower = sma20 - (std20 * 2)
        d['bb_width'] = (bb_upper - bb_lower) / sma20
        d['bb_pos']   = (d['close'] - bb_lower) / (bb_upper - bb_lower)
        tr = pd.concat([
            d['high'] - d['low'],
            (d['high'] - d['close'].shift()).abs(),
            (d['low']  - d['close'].shift()).abs()
        ], axis=1).max(axis=1)
        d['atr']         = tr.rolling(14).mean()
        d['atr_pct']     = d['atr'] / d['close'] * 100
        d['vol_ratio']   = d['volume'] / d['volume'].rolling(20).mean()
        d['ema20']       = d['close'].ewm(span=20, adjust=False).mean()
        d['ema50']       = d['close'].ewm(span=50, adjust=False).mean()
        d['ema_diff']    = (d['ema20'] - d['ema50']) / d['close'] * 100
        d['momentum_3']  = d['close'].pct_change(3) * 100
        d['momentum_7']  = d['close'].pct_change(7) * 100
        d['momentum_14'] = d['close'].pct_change(14) * 100
        d['candle_body'] = (d['close'] - d['open']).abs() / d['close'] * 100
        d['candle_dir']  = (d['close'] > d['open']).astype(int)
        d = d.dropna()
        X        = d[features_ml].iloc[-1:].values
        X_scaled = scaler_ml.transform(X)
        pred     = model_ml.predict(X_scaled)[0]
        proba    = model_ml.predict_proba(X_scaled)[0]
        conf     = proba[pred] * 100
        return ("BUY" if pred == 1 else "HOLD"), conf
    except:
        return "HOLD", 50.0

# ── FUNGSI: CACHE ONCHAIN ─────────────────────
def get_onchain_cached():
    global onchain_cache
    sekarang = time.time()
    if (onchain_cache["data"] is None or
            sekarang - onchain_cache["waktu"] > 300):
        try:
            onchain_cache["data"]  = get_onchain_score()
            onchain_cache["waktu"] = sekarang
        except Exception as e:
            print(f"  ⚠️  OnChain error: {e}")
            if onchain_cache["data"] is None:
                onchain_cache["data"] = _default_onchain()
    return onchain_cache["data"]

def _default_onchain():
    return {
        "skor_buy"      : 0,
        "fear_greed"    : {"score": 50},
        "funding_rate"  : {"rate": 0},
        "btc_dominance" : {"dominance": 50}
    }

# ── FUNGSI: CACHE GEOPOLITIK ──────────────────
def get_geo_cached():
    global geo_cache
    sekarang = time.time()
    if (geo_cache["data"] is None or
            sekarang - geo_cache["waktu"] > 600):
        try:
            geo_cache["data"]  = get_geo_score()
            geo_cache["waktu"] = sekarang
            if geo_cache["data"].get("alert"):
                kirim_telegram(
                    "🚨 <b>GEO ALERT - BERITA BESAR TERDETEKSI!</b>\n\n"
                    + geo_cache["data"]["alert_pesan"]
                    + "\n\n⚠️ Bot lebih konservatif sementara waktu"
                )
        except Exception as e:
            print(f"  ⚠️  Geo error: {e}")
            if geo_cache["data"] is None:
                geo_cache["data"] = _default_geo()
    return geo_cache["data"]

def _default_geo():
    return {
        "skor_buy": 0, "skor_sell": 0,
        "sentiment": "NETRAL", "rata_skor": 0.0,
        "n_berita": 0, "top_berita": [],
        "alert": False, "alert_pesan": "",
        "breakdown": {
            "sangat_positif": 0, "positif": 0,
            "netral": 0, "negatif": 0, "sangat_negatif": 0
        }
    }

# ── FUNGSI: PRINT STATUS GEOPOLITIK ──────────
def print_geo_status():
    geo = get_geo_cached()
    sent_emoji = {
        "SANGAT_POSITIF" : "🟢🟢",
        "POSITIF"        : "🟢",
        "SEDIKIT_POSITIF": "🟡",
        "NETRAL"         : "⚪",
        "SEDIKIT_NEGATIF": "🟠",
        "NEGATIF"        : "🔴",
        "SANGAT_NEGATIF" : "🔴🔴",
    }
    emoji = sent_emoji.get(geo["sentiment"], "⚪")
    print(f"  🌍 Geo: {emoji} {geo['sentiment']} | "
          f"Rata:{geo['rata_skor']:+.2f} | "
          f"Berita:{geo['n_berita']} | "
          f"Buy:+{geo['skor_buy']} Sell:-{geo['skor_sell']}")
    if geo.get("alert"):
        print(f"  🚨 ALERT AKTIF!")

# ── FUNGSI: HITUNG SKOR KOIN ──────────────────
def hitung_skor_koin(symbol):
    df = get_data(symbol)
    if df is None:
        return None

    ind              = hitung_indikator(df)
    ml_pred, ml_conf = prediksi_ml(df)
    onchain          = get_onchain_cached()
    geo              = get_geo_cached()

    skor   = 0
    detail = []

    if ind["rsi"] < 35:
        skor += 1
        detail.append(f"RSI oversold ({ind['rsi']:.1f})")
    if ind["macd_up"]:
        skor += 1
        detail.append("MACD cross UP")
    if ind["bb_bawah"]:
        skor += 1
        detail.append("BB bawah")
    if ind["ichi_atas"] or ind["tk_up"]:
        skor += 1
        detail.append("Ichimoku bullish")
    if ind["vol_tinggi"]:
        skor += 1
        detail.append(f"Volume {ind['vol_ratio']:.1f}x")
    if ind["bull_div"]:
        skor += 1
        detail.append("Bull Divergence")
    if ind["momentum"] > 3:
        skor += 1
        detail.append(f"Momentum +{ind['momentum']:.1f}%")
    if ml_pred == "BUY" and ml_conf >= 60:
        skor += 2
        detail.append(f"ML BUY ({ml_conf:.0f}%)")
    if onchain["skor_buy"] >= 1:
        skor += onchain["skor_buy"]

    sinyal_bayes = bayes.buat_sinyal_list(
        rsi=ind["rsi"],
        macd_up=ind["macd_up"], macd_down=ind["macd_down"],
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
        skor += 3
        detail.append(f"Bayes {bayes_hasil['prob_buy']}% 🔥")
    elif bayes_hasil["keputusan"] == "BUY_LEMAH":
        skor += 1
        detail.append(f"Bayes {bayes_hasil['prob_buy']}% ✅")

    # ── Geopolitik ──
    if geo["skor_buy"] >= 2:
        skor += geo["skor_buy"]
        detail.append(f"🌍 Geo {geo['sentiment']} (+{geo['skor_buy']})")
    elif geo["skor_buy"] == 1:
        skor += 1
        detail.append(f"🌍 Geo {geo['sentiment']} (+1)")

    if geo["skor_sell"] >= 3:
        skor -= 4
        detail.append(f"🔴 Geo SANGAT NEG! Block ({geo['sentiment']})")
    elif geo["skor_sell"] == 2:
        skor -= 2
        detail.append(f"🟠 Geo NEGATIF (-2)")
    elif geo["skor_sell"] == 1:
        skor -= 1
        detail.append(f"🟡 Geo sedikit negatif (-1)")

    return {
        "symbol"  : symbol,
        "skor"    : skor,
        "harga"   : ind["harga"],
        "rsi"     : ind["rsi"],
        "atr"     : ind["atr"],
        "momentum": ind["momentum"],
        "ml_pred" : ml_pred,
        "ml_conf" : ml_conf,
        "bayes"   : bayes_hasil["prob_buy"],
        "detail"  : detail,
        "ind"     : ind,
        "geo"     : geo,
    }

# ── FUNGSI: SCAN SEMUA KOIN ───────────────────
def scan_semua_koin():
    print(f"\n🔍 Scanning {len(KOIN_LIST)} koin...")
    hasil_scan = []

    for symbol in KOIN_LIST:
        if (symbol in semua_posisi and
                semua_posisi[symbol]["aktif"]):
            print(f"  ⏭️  {symbol:12} - Posisi aktif, skip")
            continue

        try:
            hasil = hitung_skor_koin(symbol)
            if hasil:
                emoji = "🔥" if hasil["skor"] >= MIN_SCORE_EKSEKUSI else "⚪"
                print(f"  {emoji} {symbol:12} "
                      f"Skor:{hasil['skor']:2} | "
                      f"RSI:{hasil['rsi']:5.1f} | "
                      f"Momentum:{hasil['momentum']:+5.1f}% | "
                      f"Bayes:{hasil['bayes']:5.1f}%")
                hasil_scan.append(hasil)
        except Exception as e:
            print(f"  ⚠️  Error scan {symbol}: {e}")
            continue

    hasil_scan.sort(key=lambda x: x["skor"], reverse=True)
    return hasil_scan

# ── FUNGSI: CEK SL/TP SEMUA POSISI ───────────
def cek_semua_sl_tp():
    waktu = time.strftime("%Y-%m-%d %H:%M:%S")

    for symbol in list(semua_posisi.keys()):
        pos = semua_posisi[symbol]
        if not pos["aktif"]:
            continue

        try:
            ticker = client.get_symbol_ticker(symbol=symbol)
            harga  = float(ticker["price"])
        except Exception as e:
            print(f"  ⚠️  Gagal ambil harga {symbol}: {e}")
            continue

        profit_pct = ((harga - pos["harga_beli"]) / pos["harga_beli"]) * 100
        print(f"  📊 {symbol}: ${harga:,.4f} | P/L: {profit_pct:+.2f}%")

        if harga >= pos["take_profit"]:
            print(f"  🎯 [{symbol}] TAKE PROFIT!")
            try:
                client.order_market_sell(symbol=symbol, quantity=pos["qty"])
            except Exception as e:
                print(f"  ⚠️  Gagal sell {symbol}: {e}")

            simpan_transaksi(symbol, pos["harga_beli"],
                             harga, pos["waktu_beli"], waktu, "TAKE_PROFIT")
            kirim_telegram(
                f"🎯 <b>TAKE PROFIT! - {symbol}</b>\n\n"
                f"💰 Beli  : <b>${pos['harga_beli']:,.4f}</b>\n"
                f"💰 Jual  : <b>${harga:,.4f}</b>\n"
                f"📈 Profit: <b>+{profit_pct:.2f}%</b> ✅\n"
                f"🕐 {waktu}"
            )
            semua_posisi[symbol]["aktif"] = False

        elif harga <= pos["stop_loss"]:
            print(f"  🛑 [{symbol}] STOP LOSS!")
            try:
                client.order_market_sell(symbol=symbol, quantity=pos["qty"])
            except Exception as e:
                print(f"  ⚠️  Gagal sell {symbol}: {e}")

            simpan_transaksi(symbol, pos["harga_beli"],
                             harga, pos["waktu_beli"], waktu, "STOP_LOSS")
            kirim_telegram(
                f"🛑 <b>STOP LOSS! - {symbol}</b>\n\n"
                f"💰 Beli  : <b>${pos['harga_beli']:,.4f}</b>\n"
                f"💰 Jual  : <b>${harga:,.4f}</b>\n"
                f"📉 Loss  : <b>{profit_pct:.2f}%</b> ❌\n"
                f"🕐 {waktu}"
            )
            semua_posisi[symbol]["aktif"] = False

# ── FUNGSI: HITUNG QTY ────────────────────────
def hitung_qty(symbol, harga):
    qty = TRADE_USDT / harga
    if harga > 1000:
        qty = round(qty, 3)
    elif harga > 1:
        qty = round(qty, 2)
    else:
        qty = round(qty, 0)
    return qty

# ── FUNGSI: BUKA POSISI ───────────────────────
def buka_posisi(hasil):
    waktu  = time.strftime("%Y-%m-%d %H:%M:%S")
    symbol = hasil["symbol"]
    harga  = hasil["harga"]
    atr    = hasil["atr"]
    qty    = hitung_qty(symbol, harga)
    sl     = harga - (atr * 1.5)
    tp     = harga + (atr * 3.0)
    sl_pct = ((harga - sl) / harga) * 100
    tp_pct = ((tp - harga) / harga) * 100

    print(f"\n  🟢 [{symbol}] BUY! Skor:{hasil['skor']} | Qty:{qty}")

    try:
        client.order_market_buy(symbol=symbol, quantity=qty)
    except Exception as e:
        print(f"  ⚠️  Gagal buy {symbol}: {e}")
        return

    semua_posisi[symbol] = {
        "aktif"      : True,
        "harga_beli" : harga,
        "stop_loss"  : sl,
        "take_profit": tp,
        "waktu_beli" : waktu,
        "qty"        : qty,
        "atr"        : atr
    }

    geo        = hasil.get("geo", {})
    geo_sent   = geo.get("sentiment", "N/A")
    geo_buy    = geo.get("skor_buy", 0)
    geo_sell   = geo.get("skor_sell", 0)
    geo_berita = geo.get("n_berita", 0)
    detail_str = " | ".join(hasil["detail"])

    kirim_telegram(
        f"🟢 <b>ORDER BUY - {symbol}</b>\n"
        f"⭐ Skor    : <b>{hasil['skor']}</b>\n"
        f"🤖 ML      : {hasil['ml_pred']} ({hasil['ml_conf']:.0f}%)\n"
        f"🧠 Bayes   : {hasil['bayes']:.1f}%\n"
        f"📈 Momentum: {hasil['momentum']:+.1f}%\n"
        f"🌍 Geo     : {geo_sent} (+{geo_buy}/-{geo_sell}, {geo_berita} berita)\n\n"
        f"💰 Harga : <b>${harga:,.4f}</b>\n"
        f"🔢 Qty   : {qty}\n"
        f"🛑 SL    : <b>${sl:,.4f}</b> (-{sl_pct:.1f}%)\n"
        f"🎯 TP    : <b>${tp:,.4f}</b> (+{tp_pct:.1f}%)\n\n"
        f"✅ {detail_str}\n\n"
        f"🕐 {waktu}"
    )

# ── FUNGSI: STATUS SEMUA POSISI ───────────────
def print_status_posisi():
    aktif = [(s, p) for s, p in semua_posisi.items() if p["aktif"]]
    if not aktif:
        print("  📭 Tidak ada posisi aktif")
        return

    print(f"  📊 Posisi aktif: {len(aktif)}/{MAX_POSISI}")
    for symbol, pos in aktif:
        try:
            ticker = client.get_symbol_ticker(symbol=symbol)
            harga  = float(ticker["price"])
            pl_pct = ((harga - pos["harga_beli"]) / pos["harga_beli"]) * 100
            emoji  = "📈" if pl_pct >= 0 else "📉"
            print(f"  {emoji} {symbol:12} "
                  f"Beli:${pos['harga_beli']:,.4f} | "
                  f"Skrg:${harga:,.4f} | "
                  f"P/L:{pl_pct:+.2f}%")
        except:
            pass

# ── FUNGSI: SATU SIKLUS TRADING ───────────────
def jalankan_siklus(siklus):
    """Jalankan satu siklus penuh — dipisah agar mudah di-retry"""
    waktu = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*60}")
    print(f"⏰ {waktu} | Siklus #{siklus}")
    print(f"{'='*60}")

    # Step 1: Cek SL/TP
    print("\n📊 Cek posisi aktif:")
    print_status_posisi()
    cek_semua_sl_tp()

    # Step 2: Status geo
    print("\n🌍 Kondisi geopolitik:")
    print_geo_status()

    # Step 3: Hitung posisi aktif
    n_posisi_aktif = sum(1 for p in semua_posisi.values() if p["aktif"])
    print(f"\n  Posisi aktif: {n_posisi_aktif}/{MAX_POSISI}")

    # Step 4: Scan koin
    if n_posisi_aktif < MAX_POSISI:
        slot_tersisa = MAX_POSISI - n_posisi_aktif
        print(f"  Slot tersisa: {slot_tersisa}")

        hasil_scan = scan_semua_koin()
        kandidat   = [h for h in hasil_scan
                      if h["skor"] >= MIN_SCORE_EKSEKUSI]

        if kandidat:
            print(f"\n🏆 Top Kandidat:")
            for i, k in enumerate(kandidat[:3], 1):
                print(f"  {i}. {k['symbol']:12} "
                      f"Skor:{k['skor']} | "
                      f"RSI:{k['rsi']:.1f} | "
                      f"Momentum:{k['momentum']:+.1f}%")

            for kandidat_koin in kandidat[:slot_tersisa]:
                buka_posisi(kandidat_koin)
                n_posisi_aktif += 1
                if n_posisi_aktif >= MAX_POSISI:
                    break
        else:
            print("\n  ⚪ Tidak ada koin dengan skor cukup")
            if hasil_scan:
                print(f"     Skor tertinggi: "
                      f"{hasil_scan[0]['symbol']} = {hasil_scan[0]['skor']}")
    else:
        print(f"  ✋ Posisi penuh ({MAX_POSISI}/{MAX_POSISI})")

# ── MAIN ──────────────────────────────────────
print("=" * 60)
print("   BINANCE TRADING BOT v9.2 - CLOUD EDITION")
print(f"   Koin        : {', '.join([k.replace('USDT','') for k in KOIN_LIST])}")
print(f"   Max Posisi  : {MAX_POSISI}")
print(f"   Modal/Posisi: ${TRADE_USDT}")
print(f"   Min Skor    : {MIN_SCORE_EKSEKUSI}")
print(f"   Environment : {'Cloud ☁️' if os.environ.get('RAILWAY_ENVIRONMENT') else 'Local 💻'}")
print("=" * 60)

ml_aktif = load_model()

print("\n🌍 Cek kondisi geopolitik awal...")
geo_awal = get_geo_cached()
print(f"  Sentiment : {geo_awal['sentiment']}")
print(f"  Berita    : {geo_awal['n_berita']} artikel")

kirim_telegram(
    "🚀 <b>Trading Bot v9.2 - Cloud Edition!</b>\n\n"
    f"☁️ Deploy: {'Railway' if os.environ.get('RAILWAY_ENVIRONMENT') else 'Local'}\n"
    f"🔍 Scan : {', '.join([k.replace('USDT','') for k in KOIN_LIST])}\n\n"
    f"📊 Max posisi : {MAX_POSISI}\n"
    f"💰 Modal/pos  : ${TRADE_USDT}\n"
    f"🤖 ML         : {'✅' if ml_aktif else '⚠️'}\n"
    f"🧠 Bayesian   : ✅\n"
    f"🌍 Geo        : ✅ ({geo_awal['sentiment']}, {geo_awal['n_berita']} berita)\n"
    f"🔄 Auto-reconnect: ✅\n"
    "📌 Status: ✅ Berjalan 24/7"
)

print("\n💰 Saldo:")
cek_saldo()
print("=" * 60)

siklus = 0

while bot_running:
    siklus += 1
    try:
        jalankan_siklus(siklus)
        reconnect_count = 0  # Reset jika siklus sukses
        print(f"\n⏳ Menunggu {SCAN_INTERVAL//60} menit...")
        time.sleep(SCAN_INTERVAL)

    except (BinanceAPIException, ConnectionError,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout) as e:
        # Error koneksi → reconnect
        print(f"\n📡 Koneksi error: {e}")
        reconnect_client()

    except Exception as e:
        # Error tak terduga → log + kirim Telegram + lanjut
        tb = traceback.format_exc()
        print(f"\n⚠️  Error tak terduga di siklus #{siklus}:")
        print(tb)
        kirim_telegram(
            f"⚠️ <b>Bot Error - Siklus #{siklus}</b>\n\n"
            f"<code>{str(e)[:200]}</code>\n\n"
            f"🔄 Bot tetap berjalan...\n"
            f"🕐 {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        time.sleep(30)  # Tunggu sebentar lalu lanjut