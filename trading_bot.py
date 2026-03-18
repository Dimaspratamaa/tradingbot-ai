# ============================================
# BINANCE TRADING BOT v9.4 - CLOUD EDITION
# Upgrade: Order Book Analysis
#   - Order Book Depth (bid/ask pressure)
#   - Spoofing Detection
#   - Iceberg Order Detection
# ============================================

from binance.client import Client
from binance.exceptions import BinanceAPIException
from onchain import get_onchain_score
from bayesian_model import BayesianTradingModel
from geopolitik import get_geo_score
from orderbook import analisis_orderbook, simpan_snapshot
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

API_KEY    = os.environ.get("BINANCE_API_KEY",    "U0LiHucqGcPDj3L8bAHp0Qzfa9ocMxbEilQJeOihSwpmioNnl33WV4wyJcytSkkG")
API_SECRET = os.environ.get("BINANCE_API_SECRET", "pg412rXf0oSLFUqSn0914FCyYnJtZ32GCtBEwGPjT9UdawZz1BX2rVpxuwJmn0up")
TG_TOKEN   = os.environ.get("TG_TOKEN",           "8735682075:AAE6N7YtKgGkxK-1dZl-RVKCvQplGgaUN8M")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID",         "8604266478")

KOIN_LIST = ["BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","ADAUSDT",
             "XRPUSDT","DOGEUSDT","AVAXUSDT","DOTUSDT","LINKUSDT"]

MAX_POSISI         = 3
MIN_SCORE_EKSEKUSI = 6
TRADE_USDT         = 100.0
SCAN_INTERVAL      = 300
TRAILING_AKTIVASI  = 1.5
TRAILING_JARAK     = 1.0
TF_REQUIRED        = 2

semua_posisi    = {}
onchain_cache   = {"data": None, "waktu": 0}
geo_cache       = {"data": None, "waktu": 0}
bot_running     = True
reconnect_count = 0
MAX_RECONNECT   = 10
RECONNECT_DELAY = 30

def buat_client():
    return Client(API_KEY, API_SECRET, testnet=True)

client = buat_client()
bayes  = BayesianTradingModel()
bayes.load_model()

def handle_shutdown(signum, frame):
    global bot_running
    bot_running = False
    kirim_telegram("⛔ <b>Bot dihentikan</b>\n📌 Posisi tetap terbuka di exchange")
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT,  handle_shutdown)

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

def simpan_transaksi(symbol, harga_beli, harga_jual, waktu_beli, waktu_jual, alasan):
    profit_pct = ((harga_jual - harga_beli) / harga_beli) * 100
    riwayat = []
    if os.path.exists("riwayat_trade.json"):
        with open("riwayat_trade.json", "r") as f:
            riwayat = json.load(f)
    riwayat.append({"symbol": symbol, "harga_beli": harga_beli,
        "harga_jual": harga_jual, "profit_pct": round(profit_pct, 4),
        "waktu_beli": waktu_beli, "waktu_jual": waktu_jual, "alasan": alasan})
    with open("riwayat_trade.json", "w") as f:
        json.dump(riwayat, f, indent=2)
    print(f"  💾 [{symbol}] P/L: {profit_pct:+.2f}%")

def cek_saldo():
    try:
        akun  = client.get_account()
        saldo = {a["asset"]: float(a["free"]) for a in akun["balances"] if float(a["free"]) > 0}
        print(f"  Saldo USDT: {saldo.get('USDT', 0):,.2f}")
        return saldo
    except Exception as e:
        print(f"  ⚠️  Gagal cek saldo: {e}")
        return {}

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

def get_data(symbol, interval=Client.KLINE_INTERVAL_1HOUR, limit=150):
    try:
        klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(klines, columns=['time','open','high','low','close','volume',
            'close_time','quote_vol','trades','taker_base','taker_quote','ignore'])
        for col in ['open','high','low','close','volume']:
            df[col] = df[col].astype(float)
        return df
    except Exception as e:
        print(f"  ⚠️  Gagal ambil {symbol}: {e}")
        return None

def hitung_indikator(df):
    close = df['close']; high = df['high']; low = df['low']; volume = df['volume']
    delta = close.diff()
    gain  = delta.where(delta > 0, 0).rolling(14).mean()
    loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rsi   = (100 - (100 / (1 + gain / loss))).iloc[-1]
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd_line   = ema12 - ema26
    signal_line = macd_line.ewm(span=9, adjust=False).mean()
    macd_up     = (macd_line.iloc[-1] > signal_line.iloc[-1] and macd_line.iloc[-2] <= signal_line.iloc[-2])
    macd_down   = (macd_line.iloc[-1] < signal_line.iloc[-1] and macd_line.iloc[-2] >= signal_line.iloc[-2])
    sma20    = close.rolling(20).mean(); std20 = close.rolling(20).std()
    bb_upper = (sma20 + std20 * 2).iloc[-1]; bb_lower = (sma20 - std20 * 2).iloc[-1]
    harga    = close.iloc[-1]
    bb_bawah = harga <= bb_lower; bb_atas = harga >= bb_upper
    tr  = pd.concat([high-low,(high-close.shift()).abs(),(low-close.shift()).abs()],axis=1).max(axis=1)
    atr = tr.rolling(14).mean().iloc[-1]
    tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2
    kijun  = (high.rolling(26).max() + low.rolling(26).min()) / 2
    span_a = ((tenkan + kijun) / 2).shift(26)
    span_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)
    ichi_atas = harga > max(span_a.iloc[-1], span_b.iloc[-1])
    tk_up     = (tenkan.iloc[-1] > kijun.iloc[-1] and tenkan.iloc[-2] <= kijun.iloc[-2])
    vol_avg   = volume.rolling(20).mean().iloc[-1]; vol_skrng = volume.iloc[-1]
    vol_tinggi = vol_skrng > (vol_avg * 1.5); vol_ratio = vol_skrng / vol_avg
    rsi_ser  = 100 - (100 / (1 + gain / loss))
    harga_r  = close.iloc[-5:].values; rsi_r = rsi_ser.iloc[-5:].values
    bull_div = harga_r[-1] < harga_r[0] and rsi_r[-1] > rsi_r[0]
    momentum_24h = ((harga - close.iloc[-25]) / close.iloc[-25]) * 100
    ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
    return {"harga": harga, "rsi": rsi, "macd_up": macd_up, "macd_down": macd_down,
            "bb_bawah": bb_bawah, "bb_atas": bb_atas, "atr": atr,
            "ichi_atas": ichi_atas, "tk_up": tk_up, "vol_tinggi": vol_tinggi,
            "vol_ratio": vol_ratio, "bull_div": bull_div, "momentum": momentum_24h,
            "ema_bull": ema20 > ema50}

def analisis_timeframe(symbol, interval, nama_tf):
    df = get_data(symbol, interval=interval)
    if df is None:
        return {"tf": nama_tf, "konfirmasi": False, "skor": 0}
    ind  = hitung_indikator(df)
    skor = sum([ind["rsi"]<50, ind["macd_up"], ind["ema_bull"],
                ind["ichi_atas"] or ind["tk_up"], ind["momentum"]>0])
    return {"tf": nama_tf, "konfirmasi": skor >= 3, "skor": skor, "ind": ind}

def multi_timeframe_analysis(symbol):
    tf_list   = [(Client.KLINE_INTERVAL_1HOUR,"1H"),(Client.KLINE_INTERVAL_4HOUR,"4H"),(Client.KLINE_INTERVAL_1DAY,"1D")]
    hasil_tf  = [analisis_timeframe(symbol, iv, nm) for iv, nm in tf_list]
    n_konfirm = sum(1 for h in hasil_tf if h["konfirmasi"])
    return {"timeframes": hasil_tf, "n_konfirmasi": n_konfirm,
            "semua_bullish": n_konfirm == 3, "cukup_bullish": n_konfirm >= TF_REQUIRED,
            "summary": " | ".join([f"{h['tf']}:{'✅' if h['konfirmasi'] else '❌'}({h['skor']}/5)" for h in hasil_tf])}

def update_trailing_stop(symbol, harga_skrng):
    if symbol not in semua_posisi: return False
    pos = semua_posisi[symbol]
    if not pos["aktif"]: return False
    profit_pct   = ((harga_skrng - pos["harga_beli"]) / pos["harga_beli"]) * 100
    harga_tinggi = pos.get("harga_tertinggi", pos["harga_beli"])
    if harga_skrng > harga_tinggi:
        semua_posisi[symbol]["harga_tertinggi"] = harga_skrng
        harga_tinggi = harga_skrng
    if not pos.get("trailing_aktif") and profit_pct >= TRAILING_AKTIVASI:
        semua_posisi[symbol]["trailing_aktif"] = True
        kirim_telegram(f"🔄 <b>Trailing Aktif - {symbol}</b>\n📈 Profit: <b>+{profit_pct:.2f}%</b>")
    if pos.get("trailing_aktif"):
        sl_baru = harga_tinggi * (1 - TRAILING_JARAK / 100)
        if sl_baru > pos["stop_loss"]:
            semua_posisi[symbol]["stop_loss"] = sl_baru
            return True
    return False

def prediksi_ml(df):
    if model_ml is None: return "HOLD", 50.0
    try:
        d = df.copy()
        delta = d['close'].diff()
        gain  = delta.where(delta > 0, 0).rolling(14).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(14).mean()
        d['rsi'] = 100 - (100 / (1 + gain / loss))
        ema12 = d['close'].ewm(span=12,adjust=False).mean()
        ema26 = d['close'].ewm(span=26,adjust=False).mean()
        d['macd'] = ema12-ema26; d['macd_signal'] = d['macd'].ewm(span=9,adjust=False).mean()
        d['macd_hist'] = d['macd']-d['macd_signal']
        sma20 = d['close'].rolling(20).mean(); std20 = d['close'].rolling(20).std()
        bb_upper = sma20+(std20*2); bb_lower = sma20-(std20*2)
        d['bb_width'] = (bb_upper-bb_lower)/sma20; d['bb_pos'] = (d['close']-bb_lower)/(bb_upper-bb_lower)
        tr = pd.concat([d['high']-d['low'],(d['high']-d['close'].shift()).abs(),(d['low']-d['close'].shift()).abs()],axis=1).max(axis=1)
        d['atr'] = tr.rolling(14).mean(); d['atr_pct'] = d['atr']/d['close']*100
        d['vol_ratio'] = d['volume']/d['volume'].rolling(20).mean()
        d['ema20'] = d['close'].ewm(span=20,adjust=False).mean(); d['ema50'] = d['close'].ewm(span=50,adjust=False).mean()
        d['ema_diff'] = (d['ema20']-d['ema50'])/d['close']*100
        d['momentum_3']  = d['close'].pct_change(3)*100; d['momentum_7']  = d['close'].pct_change(7)*100
        d['momentum_14'] = d['close'].pct_change(14)*100
        d['candle_body'] = (d['close']-d['open']).abs()/d['close']*100
        d['candle_dir']  = (d['close']>d['open']).astype(int)
        d = d.dropna()
        X = d[features_ml].iloc[-1:].values; X_scaled = scaler_ml.transform(X)
        pred = model_ml.predict(X_scaled)[0]; proba = model_ml.predict_proba(X_scaled)[0]
        return ("BUY" if pred == 1 else "HOLD"), proba[pred]*100
    except:
        return "HOLD", 50.0

def get_onchain_cached():
    global onchain_cache
    sekarang = time.time()
    if onchain_cache["data"] is None or sekarang-onchain_cache["waktu"] > 300:
        try:
            onchain_cache["data"] = get_onchain_score(); onchain_cache["waktu"] = sekarang
        except:
            if onchain_cache["data"] is None:
                onchain_cache["data"] = {"skor_buy":0,"fear_greed":{"score":50},"funding_rate":{"rate":0},"btc_dominance":{"dominance":50}}
    return onchain_cache["data"]

def get_geo_cached():
    global geo_cache
    sekarang = time.time()
    if geo_cache["data"] is None or sekarang-geo_cache["waktu"] > 600:
        try:
            geo_cache["data"] = get_geo_score(); geo_cache["waktu"] = sekarang
            if geo_cache["data"].get("alert"):
                kirim_telegram("🚨 <b>GEO ALERT!</b>\n\n" + geo_cache["data"]["alert_pesan"])
        except:
            if geo_cache["data"] is None:
                geo_cache["data"] = {"skor_buy":0,"skor_sell":0,"sentiment":"NETRAL","rata_skor":0.0,"n_berita":0,"alert":False,"alert_pesan":""}
    return geo_cache["data"]

def print_geo_status():
    geo = get_geo_cached()
    em  = {"SANGAT_POSITIF":"🟢🟢","POSITIF":"🟢","SEDIKIT_POSITIF":"🟡","NETRAL":"⚪","SEDIKIT_NEGATIF":"🟠","NEGATIF":"🔴","SANGAT_NEGATIF":"🔴🔴"}
    print(f"  🌍 Geo: {em.get(geo['sentiment'],'⚪')} {geo['sentiment']} | Buy:+{geo['skor_buy']} Sell:-{geo['skor_sell']}")

def hitung_skor_koin(symbol):
    df = get_data(symbol, interval=Client.KLINE_INTERVAL_1HOUR)
    if df is None: return None
    ind = hitung_indikator(df)
    ml_pred, ml_conf = prediksi_ml(df)
    onchain = get_onchain_cached()
    geo     = get_geo_cached()
    skor = 0; detail = []

    if ind["rsi"] < 35:    skor += 1; detail.append(f"RSI({ind['rsi']:.1f})")
    if ind["macd_up"]:     skor += 1; detail.append("MACD↑")
    if ind["bb_bawah"]:    skor += 1; detail.append("BB↓")
    if ind["ichi_atas"] or ind["tk_up"]: skor += 1; detail.append("Ichi✓")
    if ind["vol_tinggi"]:  skor += 1; detail.append(f"Vol{ind['vol_ratio']:.1f}x")
    if ind["bull_div"]:    skor += 1; detail.append("Div✓")
    if ind["momentum"] > 3: skor += 1; detail.append(f"Mom+{ind['momentum']:.1f}%")
    if ml_pred == "BUY" and ml_conf >= 60: skor += 2; detail.append(f"ML({ml_conf:.0f}%)")
    if onchain["skor_buy"] >= 1: skor += onchain["skor_buy"]

    sinyal_bayes = bayes.buat_sinyal_list(
        rsi=ind["rsi"], macd_up=ind["macd_up"], macd_down=ind["macd_down"],
        bb_bawah=ind["bb_bawah"], bb_atas=ind["bb_atas"],
        ichi_bullish=(ind["ichi_atas"] or ind["tk_up"]),
        vol_tinggi=ind["vol_tinggi"], bull_div=ind["bull_div"],
        ml_pred=ml_pred, ml_conf=ml_conf,
        fear_score=onchain["fear_greed"]["score"],
        funding_rate=onchain["funding_rate"]["rate"],
        btc_dom=onchain["btc_dominance"]["dominance"])
    bayes_hasil = bayes.hitung_probabilitas(sinyal_bayes)
    if bayes_hasil["keputusan"] == "BUY_KUAT":  skor += 3; detail.append(f"Bayes{bayes_hasil['prob_buy']}%🔥")
    elif bayes_hasil["keputusan"] == "BUY_LEMAH": skor += 1; detail.append(f"Bayes{bayes_hasil['prob_buy']}%✅")

    if geo["skor_buy"] >= 2:  skor += geo["skor_buy"]; detail.append(f"🌍+{geo['skor_buy']}")
    elif geo["skor_buy"] == 1: skor += 1; detail.append("🌍+1")
    if geo["skor_sell"] >= 3:  skor -= 4; detail.append("🔴GeoBlock")
    elif geo["skor_sell"] == 2: skor -= 2; detail.append("🟠Geo-2")
    elif geo["skor_sell"] == 1: skor -= 1; detail.append("🟡Geo-1")

    mtf = multi_timeframe_analysis(symbol)
    if mtf["semua_bullish"]:   skor += 3; detail.append("📊MTF3/3🔥")
    elif mtf["cukup_bullish"]: skor += 1; detail.append(f"📊MTF{mtf['n_konfirmasi']}/3✅")
    else:                       skor -= 1; detail.append(f"📊MTF{mtf['n_konfirmasi']}/3❌")

    # ORDER BOOK ANALYSIS
    ob = analisis_orderbook(client, symbol)
    if ob["block_entry"]:
        skor -= 5; detail.append("🚫OB:MANIP!")
        kirim_telegram(
            f"🚫 <b>MANIPULASI - {symbol}</b>\n\n"
            + "\n".join(ob["spoof"]["detail"])
            + f"\n📊 {ob['depth']['sinyal']}\n"
            f"⚠️ Entry diblokir!\n🕐 {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
    else:
        if ob["skor_buy"] >= 3:   skor += 3; detail.append(f"📗OB+{ob['skor_buy']}🔥")
        elif ob["skor_buy"] >= 1: skor += ob["skor_buy"]; detail.append(f"📗OB+{ob['skor_buy']}")
        if ob["skor_sell"] >= 2:  skor -= ob["skor_sell"]; detail.append(f"📕OB-{ob['skor_sell']}")
        elif ob["skor_sell"] == 1: skor -= 1; detail.append("📕OB-1")
    if ob["iceberg"]["iceberg_side"] == "BUY":  detail.append("🧊Ice:BUY✅")
    if ob["iceberg"]["iceberg_side"] == "SELL": skor -= 1; detail.append("🧊Ice:SELL⚠️")

    return {"symbol": symbol, "skor": skor, "harga": ind["harga"], "rsi": ind["rsi"],
            "atr": ind["atr"], "momentum": ind["momentum"], "ml_pred": ml_pred,
            "ml_conf": ml_conf, "bayes": bayes_hasil["prob_buy"],
            "detail": detail, "ind": ind, "geo": geo, "mtf": mtf, "ob": ob}

def scan_semua_koin():
    print(f"\n🔍 Scanning {len(KOIN_LIST)} koin...")
    hasil_scan = []
    for symbol in KOIN_LIST:
        if symbol in semua_posisi and semua_posisi[symbol]["aktif"]:
            print(f"  ⏭️  {symbol:12} - skip"); continue
        try:
            hasil = hitung_skor_koin(symbol)
            if hasil:
                ob    = hasil["ob"]
                emoji = "🔥" if hasil["skor"] >= MIN_SCORE_EKSEKUSI else "⚪"
                manip = "🎭" if ob["manipulasi"] else ""
                print(f"  {emoji} {symbol:12} Skor:{hasil['skor']:2} | "
                      f"MTF:{hasil['mtf']['n_konfirmasi']}/3 | "
                      f"OB:{ob['depth']['sinyal'][:8]} Imbal:{ob['depth']['imbalance']:.2f}{manip}")
                hasil_scan.append(hasil)
        except Exception as e:
            print(f"  ⚠️  {symbol}: {e}")
    hasil_scan.sort(key=lambda x: x["skor"], reverse=True)
    return hasil_scan

def cek_semua_sl_tp():
    waktu = time.strftime("%Y-%m-%d %H:%M:%S")
    for symbol in list(semua_posisi.keys()):
        pos = semua_posisi[symbol]
        if not pos["aktif"]: continue
        try:
            harga = float(client.get_symbol_ticker(symbol=symbol)["price"])
        except Exception as e:
            print(f"  ⚠️  Gagal harga {symbol}: {e}"); continue
        profit_pct = ((harga - pos["harga_beli"]) / pos["harga_beli"]) * 100
        update_trailing_stop(symbol, harga)
        trail = " 🔄" if pos.get("trailing_aktif") else ""
        print(f"  📊 {symbol}: ${harga:,.4f} | P/L:{profit_pct:+.2f}% | SL:${pos['stop_loss']:,.4f}{trail}")

        if harga >= pos["take_profit"]:
            print(f"  🎯 [{symbol}] TAKE PROFIT!")
            try: client.order_market_sell(symbol=symbol, quantity=pos["qty"])
            except Exception as e: print(f"  ⚠️  Gagal sell: {e}")
            simpan_transaksi(symbol, pos["harga_beli"], harga, pos["waktu_beli"], waktu, "TAKE_PROFIT")
            kirim_telegram(f"🎯 <b>TAKE PROFIT! - {symbol}</b>\n\n"
                f"💰 Beli : <b>${pos['harga_beli']:,.4f}</b>\n"
                f"💰 Jual : <b>${harga:,.4f}</b>\n"
                f"📈 Profit: <b>+{profit_pct:.2f}%</b> ✅\n🕐 {waktu}")
            semua_posisi[symbol]["aktif"] = False

        elif harga <= pos["stop_loss"]:
            alasan = "TRAILING_STOP" if pos.get("trailing_aktif") else "STOP_LOSS"
            emoji  = "🔄" if pos.get("trailing_aktif") else "🛑"
            try: client.order_market_sell(symbol=symbol, quantity=pos["qty"])
            except Exception as e: print(f"  ⚠️  Gagal sell: {e}")
            simpan_transaksi(symbol, pos["harga_beli"], harga, pos["waktu_beli"], waktu, alasan)
            kirim_telegram(f"{emoji} <b>{alasan}! - {symbol}</b>\n\n"
                f"💰 Beli : <b>${pos['harga_beli']:,.4f}</b>\n"
                f"💰 Jual : <b>${harga:,.4f}</b>\n"
                f"{'📈' if profit_pct>=0 else '📉'} P/L: <b>{profit_pct:+.2f}%</b> "
                f"{'✅' if profit_pct>=0 else '❌'}\n🕐 {waktu}")
            semua_posisi[symbol]["aktif"] = False

def hitung_qty(symbol, harga):
    qty = TRADE_USDT / harga
    if harga > 1000: return round(qty, 3)
    elif harga > 1:  return round(qty, 2)
    else:            return round(qty, 0)

def buka_posisi(hasil):
    waktu  = time.strftime("%Y-%m-%d %H:%M:%S")
    symbol = hasil["symbol"]; harga = hasil["harga"]; atr = hasil["atr"]
    qty    = hitung_qty(symbol, harga)
    sl     = harga - (atr * 1.5); tp = harga + (atr * 3.0)
    sl_pct = ((harga - sl) / harga) * 100; tp_pct = ((tp - harga) / harga) * 100
    print(f"\n  🟢 [{symbol}] BUY! Skor:{hasil['skor']} Qty:{qty}")
    try: client.order_market_buy(symbol=symbol, quantity=qty)
    except Exception as e: print(f"  ⚠️  Gagal buy: {e}"); return
    semua_posisi[symbol] = {"aktif": True, "harga_beli": harga, "harga_tertinggi": harga,
        "stop_loss": sl, "take_profit": tp, "waktu_beli": waktu,
        "qty": qty, "atr": atr, "trailing_aktif": False}
    geo = hasil.get("geo", {}); mtf = hasil.get("mtf", {}); ob = hasil.get("ob", {})
    kirim_telegram(
        f"🟢 <b>ORDER BUY - {symbol}</b>\n"
        f"⭐ Skor    : <b>{hasil['skor']}</b>\n"
        f"🤖 ML      : {hasil['ml_pred']} ({hasil['ml_conf']:.0f}%)\n"
        f"🧠 Bayes   : {hasil['bayes']:.1f}%\n"
        f"📊 MTF     : {mtf.get('summary','N/A')}\n"
        f"📗 OB Depth: {ob.get('depth',{}).get('sinyal','N/A')} (Imbal:{ob.get('depth',{}).get('imbalance',1):.2f})\n"
        f"🎭 Spoof   : {ob.get('spoof',{}).get('spoof_side','NONE')}\n"
        f"🧊 Iceberg : {ob.get('iceberg',{}).get('iceberg_side','NONE')}\n"
        f"🌍 Geo     : {geo.get('sentiment','N/A')}\n\n"
        f"💰 Harga : <b>${harga:,.4f}</b>\n"
        f"🔢 Qty   : {qty}\n"
        f"🛑 SL    : <b>${sl:,.4f}</b> (-{sl_pct:.1f}%)\n"
        f"🎯 TP    : <b>${tp:,.4f}</b> (+{tp_pct:.1f}%)\n"
        f"🔄 Trailing: aktif setelah +{TRAILING_AKTIVASI}%\n\n"
        f"✅ {' | '.join(hasil['detail'])}\n🕐 {waktu}"
    )

def print_status_posisi():
    aktif = [(s, p) for s, p in semua_posisi.items() if p["aktif"]]
    if not aktif: print("  📭 Tidak ada posisi aktif"); return
    print(f"  📊 {len(aktif)}/{MAX_POSISI} posisi aktif")
    for symbol, pos in aktif:
        try:
            harga  = float(client.get_symbol_ticker(symbol=symbol)["price"])
            pl_pct = ((harga - pos["harga_beli"]) / pos["harga_beli"]) * 100
            trail  = " 🔄" if pos.get("trailing_aktif") else ""
            print(f"  {'📈' if pl_pct>=0 else '📉'} {symbol:12} ${pos['harga_beli']:,.4f}→${harga:,.4f} P/L:{pl_pct:+.2f}%{trail}")
        except: pass

def jalankan_siklus(siklus):
    waktu = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*60}\n⏰ {waktu} | Siklus #{siklus}\n{'='*60}")
    print("\n📊 Posisi aktif:"); print_status_posisi(); cek_semua_sl_tp()
    print("\n🌍 Geopolitik:"); print_geo_status()
    n_aktif = sum(1 for p in semua_posisi.values() if p["aktif"])
    print(f"\n  Posisi: {n_aktif}/{MAX_POSISI}")
    if n_aktif < MAX_POSISI:
        hasil_scan = scan_semua_koin()
        kandidat   = [h for h in hasil_scan
                      if h["skor"] >= MIN_SCORE_EKSEKUSI
                      and h["mtf"]["cukup_bullish"]
                      and not h["ob"]["block_entry"]]
        if kandidat:
            print(f"\n🏆 Kandidat ({len(kandidat)}):")
            for i, k in enumerate(kandidat[:3], 1):
                print(f"  {i}. {k['symbol']} Skor:{k['skor']} MTF:{k['mtf']['n_konfirmasi']}/3 OB:{k['ob']['depth']['sinyal'][:8]}")
            for k in kandidat[:MAX_POSISI - n_aktif]:
                buka_posisi(k); n_aktif += 1
                if n_aktif >= MAX_POSISI: break
        else:
            print("\n  ⚪ Tidak ada kandidat lolos semua filter")
            if hasil_scan:
                t = hasil_scan[0]
                print(f"     Terbaik: {t['symbol']} Skor:{t['skor']} Block:{t['ob']['block_entry']}")
    else:
        print(f"  ✋ Posisi penuh")

print("=" * 60)
print("   BINANCE TRADING BOT v9.4 - CLOUD EDITION")
print(f"   🔄 Trailing Stop  : +{TRAILING_AKTIVASI}%")
print(f"   📊 Multi TF       : 1H+4H+1D (min {TF_REQUIRED}/3)")
print(f"   📗 Order Book     : Depth+Spoof+Iceberg")
print("=" * 60)

ml_aktif = load_model()
geo_awal = get_geo_cached()

kirim_telegram(
    "🚀 <b>Trading Bot v9.4 - Order Book AI!</b>\n\n"
    f"📗 Order Book Depth   : ✅\n"
    f"🎭 Spoofing Detection : ✅\n"
    f"🧊 Iceberg Detection  : ✅\n"
    f"🔄 Trailing Stop      : ✅\n"
    f"📊 Multi TF (1H+4H+1D): ✅\n"
    f"🌍 Geo : {geo_awal['sentiment']}\n"
    f"🤖 ML  : {'✅' if ml_aktif else '⚠️'}\n"
    "📌 Status: ✅ Berjalan 24/7"
)
print("\n💰 Saldo:"); cek_saldo(); print("=" * 60)

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
        print(f"\n📡 Koneksi error: {e}"); reconnect_client()
    except Exception as e:
        print(f"\n⚠️  Error siklus #{siklus}: {e}")
        kirim_telegram(f"⚠️ <b>Bot Error #{siklus}</b>\n\n<code>{str(e)[:200]}</code>\n🔄 Tetap berjalan...\n🕐 {time.strftime('%Y-%m-%d %H:%M:%S')}")
        time.sleep(30)