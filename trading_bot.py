# ============================================
# BINANCE TRADING BOT v10.1 - OPTIMIZED
# Perbaikan:
#   1. Min skor 6→7, wajib MTF 3/3 untuk futures
#   2. Volume filter ketat (wajib 1.5x)
#   3. Dual-speed scanner (90dtk + 5mnt)
#   4. Smart session bypass saat momentum kuat
#   5. Parallel scan + timeout 3 dtk/koin
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
    analisis_multi_exchange, cek_saldo_semua_exchange, scan_arbitrase
)
from risk_manager import (
    hitung_dynamic_sl, get_btc_kondisi, cek_early_exit,
    cek_session_aktif, validasi_entry, print_kondisi_market
)
from sentiment_analyzer import get_market_sentiment
from portfolio_tracker import cek_jadwal_laporan
from ml_retrainer import cek_jadwal_retrain as _cek_retrain_internal
from macro_analyzer import get_macro_score
from market_depth import get_depth_score
from onchain_pro import get_onchain_pro_score
from position_sizer import hitung_posisi_size, get_position_info
from market_regime import get_regime_params, print_regime_status
from feature_engineering import compute_all_features
from pattern_detector import analisis_pattern_quant, print_quant_analysis
from ml_ensemble import prediksi_ensemble, load_ensemble, get_model_accuracy_live
from alpha_engine import (
    get_alpha_engine, extract_alpha_signals, AlphaEngine
)
from alpha_engine import (
    hitung_alpha_score, extract_sinyal,
    update_alpha_result, print_alpha_status,
    get_laporan_alpha, reaktivasi_alpha
)
from exchange_executor import (
    eksekusi_beli_multi, eksekusi_jual_multi,
    get_total_portfolio, format_portfolio_message,
    print_exchange_status, get_exchange_status
)
from paper_trading import (
    is_paper_mode, load_state as paper_load_state,
    paper_beli_spot, paper_jual_spot,
    cek_paper_sl_tp, print_status_paper,
    get_laporan_paper, handle_paper_command,
    PAPER_MODAL_AWAL
)
from correlation_filter import (
    cek_korelasi_dengan_posisi,
    filter_kandidat_diversifikasi
)

def cek_jadwal_retrain(client, kirim_telegram):
    """
    Wrapper retrain - hanya aktif jika ada cukup data.
    Tidak akan pernah spam Telegram.
    """
    try:
        return _cek_retrain_internal(client, kirim_telegram)
    except Exception as e:
        # Tangkap semua error retrain DISINI, tidak dikirim ke Telegram
        print(f"  ⚠️  Retrain error (silent): {e}")
        return False
from pyramiding import (
    cek_semua_pyramid, reset_pyramid, get_pyramid_info,
    PYRAMID_PROFIT_TRIGGER, PYRAMID_MAX_LEVEL
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
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
warnings.filterwarnings('ignore')

# SSL normal — Railway server tidak perlu bypass
import urllib3 as _urllib3
_urllib3.disable_warnings(_urllib3.exceptions.InsecureRequestWarning)

# ── KONFIGURASI ───────────────────────────────
# ── Load .env jika ada (development lokal) ────
import pathlib
_env_file = pathlib.Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# ── API KEYS — dari environment variable SAJA ──
# Jangan hardcode key di sini! Isi di file .env
API_KEY    = os.environ.get("BINANCE_API_KEY",    "U0LiHucqGcPDj3L8bAHp0Qzfa9ocMxbEilQJeOihSwpmioNnl33WV4wyJcytSkkG")
API_SECRET = os.environ.get("BINANCE_API_SECRET", "pg412rXf0oSLFUqSn0914FCyYnJtZ32GCtBEwGPjT9UdawZz1BX2rVpxuwJmn0up")
TG_TOKEN   = os.environ.get("TG_TOKEN",   "8370727642:AAG6BPyiaa4h9ayS5D7cvXkkhujJjjBYHhE")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "8604266478")

if not TG_TOKEN or not TG_CHAT_ID:
    print("⚠️  TG_TOKEN / TG_CHAT_ID belum diisi di .env atau Railway Variables!")
    print("   Bot berjalan tapi notifikasi Telegram tidak aktif.")

if not API_KEY or not API_SECRET:
    print("⛔ BINANCE_API_KEY / BINANCE_API_SECRET belum diisi di .env!")
    print("   Salin .env.example ke .env lalu isi dengan key Anda.")
    import sys; sys.exit(1)

# ── KOIN PRIORITAS ────────────────────────────
KOIN_PRIORITAS = [
    "BTCUSDT","ETHUSDT","BNBUSDT","SOLUSDT","XRPUSDT",
    "ADAUSDT","AVAXUSDT","DOTUSDT","LINKUSDT","DOGEUSDT",
    "NEARUSDT","APTUSDT","SUIUSDT","TONUSDT",
    "ARBUSDT","OPUSDT","POLUSDT",       # MATIC → POL (rename Binance 2024)
    "FETUSDT","RENDERUSDT","WLDUSDT",
    "UNIUSDT","AAVEUSDT",
    "PEPEUSDT","SHIBUSDT","WIFUSDT",
    "JUPUSDT","STRKUSDT",               # ganti HYPE & XAUT yg tidak ada di spot
]

KOIN_BLACKLIST = {
    "USDCUSDT","BUSDUSDT","TUSDUSDT","USDTUSDT",
    "FDUSDUSDT","DAIUSDT","EURUSDT",
    "BTCUPUSDT","BTCDOWNUSDT","ETHUPUSDT","ETHDOWNUSDT",
    "BNBUPUSDT","BNBDOWNUSDT",
}

# ══════════════════════════════════════════════
# KONFIGURASI TRADING v10.1 — DIOPTIMASI
# ══════════════════════════════════════════════

# FIX 1: Naikkan skor minimum untuk kurangi SL
MIN_SCORE_SPOT         = 7      # ← naik dari 6 ke 7
MIN_SCORE_FUTURES_LONG = 9      # ← naik dari 8 ke 9
MIN_SCORE_FUTURES_SHORT= 7      # ← naik dari 7 ke 8
MTF_WAJIB_FUTURES      = True   # ← Futures WAJIB MTF 3/3
MTF_MIN_SPOT           = 2      # ← Spot minimal 2/3 MTF (tetap)

# FIX 2: Volume filter lebih ketat
VOLUME_FILTER_MIN      = 1.5    # ← Wajib volume 1.5x rata-rata
CANDLE_KONFIRMASI      = True   # ← Wajib candle bullish terakhir

# FIX 3: Dual-speed scanner
SCAN_CEPAT_INTERVAL    = 90     # ← Scan cepat setiap 90 detik
SCAN_FULL_INTERVAL     = 300    # ← Scan lengkap setiap 5 menit

# FIX 4: Smart session bypass
SESSION_BYPASS_SKOR    = 10     # ← Bypass session jika skor >= 10
SESSION_BYPASS_VOL     = 2.5    # ← Bypass session jika volume >= 2.5x

# FIX 5: Parallel scan
SCAN_TIMEOUT_PER_KOIN  = 8      # ← Timeout 8 detik per koin
SCAN_MAX_WORKERS       = 4      # ← 4 thread parallel
TOP_N_VOLUME           = 50
MIN_HARGA              = 0.00001
MIN_VOLUME_USD         = 5_000_000

MAX_POSISI_SPOT        = 3
TRADE_USDT_SPOT        = 100.0
TRAILING_AKTIVASI      = 1.5
TRAILING_JARAK         = 1.0
SCAN_INTERVAL          = SCAN_FULL_INTERVAL

# ── STATE ─────────────────────────────────────
posisi_spot      = {}
onchain_cache    = {"data": None, "waktu": 0}
geo_cache        = {"data": None, "waktu": 0}
koin_cache       = {"data": [], "waktu": 0}
sentiment_cache  = {"data": None, "waktu": 0}
macro_cache      = {"data": None, "waktu": 0}  # Cache makro 1 jam
regime_cache     = {"data": None, "waktu": 0}  # Cache regime 15 menit
pattern_cache    = {}   # {symbol: {"data": ..., "waktu": ...}}
PATTERN_CACHE_TTL = 1800  # 30 menit
bot_running      = True
reconnect_count  = 0
MAX_RECONNECT    = 10
RECONNECT_DELAY  = 30
last_entry_time  = {}
siklus_cepat     = 0

# ── PERLINDUNGAN BARU v10.2 ───────────────────
sl_cooldown      = {}   # {symbol: timestamp} — block entry X jam setelah SL
sl_harian        = {"tanggal": "", "count": 0}  # Hitung SL hari ini
MAX_SL_HARIAN    = 3    # Stop entry jika sudah 3 SL dalam sehari
SL_COOLDOWN_JAM  = 4    # Block entry 4 jam setelah kena SL di koin sama

def buat_client():
    """
    Buat Binance client.
    Di Railway: koneksi langsung tanpa SSL bypass (server luar negeri).
    Di lokal  : otomatis deteksi dan handle Cloudflare block.
    """
    from binance.client import Client as _Client

    # Cek apakah di Railway (ada env variable RAILWAY_ENVIRONMENT)
    is_railway = bool(os.environ.get("RAILWAY_ENVIRONMENT") or
                      os.environ.get("RAILWAY_PROJECT_ID"))

    if is_railway:
        # Railway — koneksi normal, tidak perlu workaround
        print("  ☁️  Mode: Railway Cloud")
        client = _Client(API_KEY, API_SECRET, testnet=False)
        client.ping()
        print("  ✅ Binance terkoneksi di Railway!")
        return client

    # Lokal — pakai header browser untuk bypass Cloudflare
    print("  💻 Mode: Lokal")
    BROWSER_HEADERS = {
        "User-Agent"     : "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                           "AppleWebKit/537.36 (KHTML, like Gecko) "
                           "Chrome/122.0.0.0 Safari/537.36",
        "Accept"         : "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control"  : "no-cache",
    }

    class BrowserClient(_Client):
        def _init_session(self):
            sess = super()._init_session()
            sess.headers.update(BROWSER_HEADERS)
            return sess

    proxies = {}
    proxy_url = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    if proxy_url:
        proxies = {"http": proxy_url, "https": proxy_url}
        print(f"  🔀 Proxy: {proxy_url}")

    try:
        c = BrowserClient(API_KEY, API_SECRET, testnet=False,
                          requests_params={"proxies": proxies} if proxies else {})
        c.ping()
        print("  ✅ Binance terkoneksi (lokal)")
        return c
    except Exception as e:
        err = str(e)
        if "Just a moment" in err or "challenge" in err:
            print("  🚫 Cloudflare block — gunakan VPN atau deploy ke Railway")
            print("  ⚠️  Bot berjalan tapi koneksi Binance tidak stabil")
        else:
            print(f"  ⚠️  Connect error: {err[:80]}")
        return _Client(API_KEY, API_SECRET, testnet=False)

client = buat_client()
bayes  = BayesianTradingModel()
bayes.load_model()

def handle_shutdown(signum, frame):
    global bot_running
    bot_running = False
    kirim_telegram("⛔ <b>Bot dihentikan</b>\n📌 Posisi tetap terbuka")
    sys.exit(0)

signal.signal(signal.SIGTERM, handle_shutdown)
signal.signal(signal.SIGINT,  handle_shutdown)

# ── FUNGSI DASAR ──────────────────────────────
# ── Status Telegram global (untuk hindari spam log) ──
_tg_valid = None   # None=belum dicek, True=OK, False=error

def kirim_telegram(pesan, retry=2):
    """
    Kirim pesan Telegram. Bot TIDAK akan crash jika Telegram gagal.
    Error hanya di-print ke log, tidak raise exception.
    """
    global _tg_valid

    # Cek credentials
    if not TG_TOKEN or not TG_CHAT_ID:
        return False   # Silent — sudah ada warning di startup

    # Jika token sudah terbukti invalid, skip langsung
    if _tg_valid is False:
        return False

    for attempt in range(retry):
        try:
            url  = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
            data = {"chat_id": TG_CHAT_ID, "text": pesan, "parse_mode": "HTML"}
            resp = requests.post(url, data=data, timeout=10)

            if resp.status_code == 200:
                _tg_valid = True
                return True

            elif resp.status_code == 404:
                # Token tidak ditemukan — stop retry, jangan crash
                if _tg_valid is None:
                    print("  ❌ [TELEGRAM] Token tidak ditemukan (404)")
                    print("  💡 Buat token baru via @BotFather lalu update Railway Variables")
                _tg_valid = False
                return False

            elif resp.status_code == 401:
                if _tg_valid is None:
                    print("  ❌ [TELEGRAM] Unauthorized (401) — cek TG_TOKEN")
                _tg_valid = False
                return False

            elif resp.status_code == 400:
                err = resp.json().get("description", "")
                if "chat not found" in err.lower():
                    if _tg_valid is None:
                        print(f"  ❌ [TELEGRAM] Chat tidak ditemukan — cek TG_CHAT_ID")
                    _tg_valid = False
                    return False
                print(f"  ⚠️  [TELEGRAM] Bad request: {err[:60]}")
                return False

            else:
                if attempt < retry - 1:
                    time.sleep(3)

        except requests.exceptions.ConnectionError:
            if attempt < retry - 1:
                time.sleep(3)
        except Exception as e:
            print(f"  ⚠️  [TELEGRAM] Error: {str(e)[:60]}")
            if attempt < retry - 1:
                time.sleep(3)

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

def simpan_transaksi(symbol, harga_beli, harga_jual,
                     waktu_beli, waktu_jual, alasan, alpha_sigs=None):
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

    # Update Alpha Engine IC dengan hasil trade ini
    if alpha_sigs:
        try:
            get_alpha_engine().catat_trade(alpha_sigs, profit_pct / 100)
        except Exception:
            pass

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

# ══════════════════════════════════════════════
# FIX 5: DYNAMIC COIN LIST
# ══════════════════════════════════════════════

def get_top_koin_by_volume():
    global koin_cache
    sekarang = time.time()
    if koin_cache["data"] and sekarang - koin_cache["waktu"] < 900:
        return koin_cache["data"]
    print("\n  🔄 Refresh daftar koin...")
    try:
        tickers    = client.get_ticker()
        usdt_pairs = []
        for t in tickers:
            symbol = t["symbol"]
            if not symbol.endswith("USDT"): continue
            if symbol in KOIN_BLACKLIST: continue
            base = symbol.replace("USDT","")
            if any(x in base for x in ["UP","DOWN","BULL","BEAR","3L","3S"]): continue
            harga = float(t.get("lastPrice",0))
            vol   = float(t.get("quoteVolume",0))
            if harga < MIN_HARGA or vol < MIN_VOLUME_USD: continue
            usdt_pairs.append({"symbol":symbol,"volume_usd":vol})
        usdt_pairs.sort(key=lambda x: x["volume_usd"], reverse=True)
        top       = [p["symbol"] for p in usdt_pairs[:TOP_N_VOLUME]]
        koin_list = list(dict.fromkeys(KOIN_PRIORITAS + top))
        koin_cache["data"]  = koin_list
        koin_cache["waktu"] = sekarang
        print(f"  ✅ {len(koin_list)} koin siap discan")
        return koin_list
    except Exception as e:
        print(f"  ⚠️  Gagal refresh koin: {e}")
        return KOIN_PRIORITAS

# ── FUNGSI: AMBIL DATA ────────────────────────
def get_data(symbol, interval=Client.KLINE_INTERVAL_1HOUR, limit=150):
    try:
        klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
        df = pd.DataFrame(klines, columns=[
            'time','open','high','low','close','volume',
            'close_time','quote_vol','trades','taker_base','taker_quote','ignore'])
        for col in ['open','high','low','close','volume']:
            df[col] = df[col].astype(float)
        return df
    except Exception as e:
        print(f"  ⚠️  Gagal ambil {symbol}: {e}")
        return None

# ── FUNGSI: HITUNG INDIKATOR ──────────────────
def hitung_indikator(df):
    close=df['close'];high=df['high'];low=df['low'];volume=df['volume']
    delta=close.diff()
    gain=delta.where(delta>0,0).rolling(14).mean()
    loss=(-delta.where(delta<0,0)).rolling(14).mean()
    rsi=(100-(100/(1+gain/loss))).iloc[-1]
    ema12=close.ewm(span=12,adjust=False).mean()
    ema26=close.ewm(span=26,adjust=False).mean()
    macd_line=ema12-ema26
    signal_line=macd_line.ewm(span=9,adjust=False).mean()
    macd_up=(macd_line.iloc[-1]>signal_line.iloc[-1] and macd_line.iloc[-2]<=signal_line.iloc[-2])
    macd_down=(macd_line.iloc[-1]<signal_line.iloc[-1] and macd_line.iloc[-2]>=signal_line.iloc[-2])
    sma20=close.rolling(20).mean();std20=close.rolling(20).std()
    harga=close.iloc[-1]
    bb_bawah=harga<=(sma20-std20*2).iloc[-1];bb_atas=harga>=(sma20+std20*2).iloc[-1]
    tr=pd.concat([high-low,(high-close.shift()).abs(),(low-close.shift()).abs()],axis=1).max(axis=1)
    atr=tr.rolling(14).mean().iloc[-1]
    tenkan=(high.rolling(9).max()+low.rolling(9).min())/2
    kijun=(high.rolling(26).max()+low.rolling(26).min())/2
    span_a=((tenkan+kijun)/2).shift(26)
    span_b=((high.rolling(52).max()+low.rolling(52).min())/2).shift(26)
    ichi_atas=harga>max(span_a.iloc[-1],span_b.iloc[-1])
    tk_up=(tenkan.iloc[-1]>kijun.iloc[-1] and tenkan.iloc[-2]<=kijun.iloc[-2])
    vol_avg=volume.rolling(20).mean().iloc[-1];vol_skrng=volume.iloc[-1]
    vol_tinggi=vol_skrng>(vol_avg*1.5);vol_ratio=vol_skrng/vol_avg
    rsi_ser=100-(100/(1+gain/loss))
    harga_r=close.iloc[-5:].values;rsi_r=rsi_ser.iloc[-5:].values
    bull_div=harga_r[-1]<harga_r[0] and rsi_r[-1]>rsi_r[0]
    bear_div=harga_r[-1]>harga_r[0] and rsi_r[-1]<rsi_r[0]
    momentum_24h=((harga-close.iloc[-25])/close.iloc[-25])*100
    ema20=close.ewm(span=20,adjust=False).mean().iloc[-1]
    ema50=close.ewm(span=50,adjust=False).mean().iloc[-1]
    candle_bullish=(close.iloc[-1] > df['open'].iloc[-1])
    return {
        "harga":harga,"rsi":rsi,"macd_up":macd_up,"macd_down":macd_down,
        "bb_bawah":bb_bawah,"bb_atas":bb_atas,"atr":atr,
        "ichi_atas":ichi_atas,"tk_up":tk_up,
        "vol_tinggi":vol_tinggi,"vol_ratio":vol_ratio,
        "bull_div":bull_div,"bear_div":bear_div,
        "momentum":momentum_24h,"ema_bull":ema20>ema50,
        "ema20":ema20,"ema50":ema50,
        "candle_bullish":candle_bullish,  # ← FIX 2
    }

# ── MULTI TIMEFRAME ───────────────────────────
def analisis_timeframe(symbol, interval, nama_tf):
    df = get_data(symbol, interval=interval)
    if df is None: return {"tf":nama_tf,"konfirmasi":False,"skor":0}
    ind  = hitung_indikator(df)
    skor = sum([ind["rsi"]<50, ind["macd_up"], ind["ema_bull"],
                ind["ichi_atas"] or ind["tk_up"], ind["momentum"]>0])
    return {"tf":nama_tf,"konfirmasi":skor>=3,"skor":skor,"ind":ind}

def multi_timeframe_analysis(symbol):
    tf_list = [(Client.KLINE_INTERVAL_1HOUR,"1H"),
               (Client.KLINE_INTERVAL_4HOUR,"4H"),
               (Client.KLINE_INTERVAL_1DAY,"1D")]
    hasil_tf  = [analisis_timeframe(symbol,iv,nm) for iv,nm in tf_list]
    n_konfirm = sum(1 for h in hasil_tf if h["konfirmasi"])
    return {
        "timeframes":hasil_tf,"n_konfirmasi":n_konfirm,
        "semua_bullish":n_konfirm==3,
        "cukup_bullish":n_konfirm>=MTF_MIN_SPOT,
        "summary":" | ".join([f"{h['tf']}:{'✅' if h['konfirmasi'] else '❌'}({h['skor']}/5)" for h in hasil_tf])
    }

# ── TRAILING STOP ─────────────────────────────
def update_trailing_spot(symbol, harga_skrng):
    if symbol not in posisi_spot: return False
    pos=posisi_spot[symbol]
    if not pos["aktif"]: return False
    profit_pct=((harga_skrng-pos["harga_beli"])/pos["harga_beli"])*100
    harga_tinggi=pos.get("harga_tertinggi",pos["harga_beli"])
    if harga_skrng>harga_tinggi:
        posisi_spot[symbol]["harga_tertinggi"]=harga_skrng
        harga_tinggi=harga_skrng
    if not pos.get("trailing_aktif") and profit_pct>=TRAILING_AKTIVASI:
        posisi_spot[symbol]["trailing_aktif"]=True
        kirim_telegram(f"🔄 <b>Trailing Aktif - {symbol}</b>\n📈 Profit: <b>+{profit_pct:.2f}%</b>")
    if pos.get("trailing_aktif"):
        sl_baru=harga_tinggi*(1-TRAILING_JARAK/100)
        if sl_baru>pos["stop_loss"]:
            posisi_spot[symbol]["stop_loss"]=sl_baru
            return True
    return False

# ── PREDIKSI ML ───────────────────────────────
def prediksi_ml(df, df_4h=None, df_1d=None):
    """
    Prediksi ML v3.0 — Ensemble Edition.
    Priority: Ensemble (XGB+LGB+RF+LSTM) > Model lama > HOLD
    """
    # Coba ensemble dulu (model v3.0)
    try:
        sinyal, conf, votes = prediksi_ensemble(df, df_4h, df_1d)
        if votes:  # ensemble berhasil
            vote_str = " ".join(f"{k}:{v:.2f}" for k,v in votes.items())
            # print(f"  🤖 Ensemble: {sinyal} ({conf:.1f}%) [{vote_str}]")
            return sinyal, conf
    except Exception:
        pass

    # Fallback ke model lama
    _pred_lama = _prediksi_ml_lama(df)
    return _pred_lama


def _prediksi_ml_lama(df):
    """Model lama sebagai fallback."""
    """
    Prediksi ML v2.0 — menggunakan 85+ quant features.
    Otomatis fallback ke versi lama jika model belum diretrain.
    """
    if model_ml is None: return "HOLD", 50.0
    try:
        # Cek apakah model pakai fitur baru (v2.0) atau lama
        is_quant_model = (features_ml is not None and
                          len(features_ml) > 20)  # model baru punya 60+ fitur

        if is_quant_model:
            # ── Model v2.0: pakai 85+ quant features ──
            feat_dict, feat_names = compute_all_features(df, df_4h, df_1d)
            if not feat_dict:
                return "HOLD", 50.0

            # Buat vector sesuai urutan features_ml
            X_vec = []
            for fname in features_ml:
                X_vec.append(feat_dict.get(fname, 0.0))
            X = np.array(X_vec).reshape(1, -1)

        else:
            # ── Fallback: model lama 14 fitur ──
            d=df.copy()
            delta=d['close'].diff()
            gain=delta.where(delta>0,0).rolling(14).mean()
            loss=(-delta.where(delta<0,0)).rolling(14).mean()
            d['rsi']=100-(100/(1+gain/loss))
            ema12=d['close'].ewm(span=12,adjust=False).mean()
            ema26=d['close'].ewm(span=26,adjust=False).mean()
            d['macd']=ema12-ema26
            d['macd_signal']=d['macd'].ewm(span=9,adjust=False).mean()
            d['macd_hist']=d['macd']-d['macd_signal']
            sma20=d['close'].rolling(20).mean()
            std20=d['close'].rolling(20).std()
            bb_upper=sma20+(std20*2); bb_lower=sma20-(std20*2)
            d['bb_width']=(bb_upper-bb_lower)/sma20
            d['bb_pos']=(d['close']-bb_lower)/(bb_upper-bb_lower)
            tr=pd.concat([d['high']-d['low'],
                          (d['high']-d['close'].shift()).abs(),
                          (d['low']-d['close'].shift()).abs()],axis=1).max(axis=1)
            d['atr']=tr.rolling(14).mean()
            d['atr_pct']=d['atr']/d['close']*100
            d['vol_ratio']=d['volume']/d['volume'].rolling(20).mean()
            d['ema20']=d['close'].ewm(span=20,adjust=False).mean()
            d['ema50']=d['close'].ewm(span=50,adjust=False).mean()
            d['ema_diff']=(d['ema20']-d['ema50'])/d['close']*100
            d['momentum_3']=d['close'].pct_change(3)*100
            d['momentum_7']=d['close'].pct_change(7)*100
            d['momentum_14']=d['close'].pct_change(14)*100
            d['candle_body']=(d['close']-d['open']).abs()/d['close']*100
            d['candle_dir']=(d['close']>d['open']).astype(int)
            d=d.dropna()
            X=d[features_ml].iloc[-1:].values

        X_scaled = scaler_ml.transform(X)
        pred  = model_ml.predict(X_scaled)[0]
        proba = model_ml.predict_proba(X_scaled)[0]
        return ("BUY" if pred == 1 else "HOLD"), proba[pred] * 100

    except Exception:
        return "HOLD", 50.0

# ── CACHE ─────────────────────────────────────
def get_onchain_cached():
    global onchain_cache
    sekarang=time.time()
    if onchain_cache["data"] is None or sekarang-onchain_cache["waktu"]>300:
        try:
            onchain_cache["data"]=get_onchain_score();onchain_cache["waktu"]=sekarang
        except:
            if onchain_cache["data"] is None:
                onchain_cache["data"]={"skor_buy":0,"fear_greed":{"score":50},"funding_rate":{"rate":0},"btc_dominance":{"dominance":50}}
    return onchain_cache["data"]

def get_geo_cached():
    global geo_cache
    sekarang=time.time()
    if geo_cache["data"] is None or sekarang-geo_cache["waktu"]>600:
        try:
            geo_cache["data"]=get_geo_score();geo_cache["waktu"]=sekarang
            if geo_cache["data"].get("alert"):
                kirim_telegram("🚨 <b>GEO ALERT!</b>\n\n"+geo_cache["data"]["alert_pesan"])
        except:
            if geo_cache["data"] is None:
                geo_cache["data"]={"skor_buy":0,"skor_sell":0,"sentiment":"NETRAL","rata_skor":0.0,"n_berita":0,"alert":False,"alert_pesan":""}
    return geo_cache["data"]

def get_sentiment_cached():
    global sentiment_cache
    sekarang=time.time()
    if sentiment_cache["data"] is None or sekarang-sentiment_cache["waktu"]>1800:
        try:
            sentiment_cache["data"]=get_market_sentiment();sentiment_cache["waktu"]=sekarang
        except:
            if sentiment_cache["data"] is None:
                sentiment_cache["data"]={"skor_buy":0,"skor_sell":0,"sentiment":"NEUTRAL","summary":"N/A"}
    return sentiment_cache["data"]

def get_pattern_cached(symbol, df_1h, df_ref=None):
    """Cache hasil analisis quant pattern — berat, cache 30 menit."""
    global pattern_cache
    sekarang = time.time()
    cached   = pattern_cache.get(symbol)
    if cached and sekarang - cached["waktu"] < PATTERN_CACHE_TTL:
        return cached["data"]
    try:
        data = analisis_pattern_quant(df_1h, df_ref, symbol)
        pattern_cache[symbol] = {"data": data, "waktu": sekarang}
        return data
    except Exception as e:
        print(f"  ⚠️  Pattern analysis {symbol}: {e}")
        return {"skor_buy": 0, "skor_sell": 0, "detail": [], "summary": "N/A"}

def get_macro_cached():
    """Cache data makro 1 jam — data makro tidak berubah cepat"""
    global macro_cache
    sekarang = time.time()
    if macro_cache["data"] is None or sekarang - macro_cache["waktu"] > 3600:
        try:
            macro_cache["data"]  = get_macro_score()
            macro_cache["waktu"] = sekarang
        except Exception as e:
            print(f"  ⚠️  Macro cache error: {e}")
            if macro_cache["data"] is None:
                macro_cache["data"] = {
                    "skor_buy": 0, "skor_sell": 0,
                    "sentimen": "MACRO_NETRAL", "detail": []
                }
    return macro_cache["data"]

# ══════════════════════════════════════════════
# HITUNG SKOR KOIN v10.1
# ══════════════════════════════════════════════

def hitung_skor_koin(symbol):
    """Hitung skor dengan filter lebih ketat (v10.4)"""
    df = get_data(symbol, interval=Client.KLINE_INTERVAL_1HOUR)
    if df is None: return None

    ind=hitung_indikator(df)
    ml_pred,ml_conf=prediksi_ml(df)
    onchain=get_onchain_cached();geo=get_geo_cached()
    skor=0;detail=[]

    # ── FIX 2: Filter volume WAJIB di awal ──
    if CANDLE_KONFIRMASI and not ind["candle_bullish"] and ind["vol_ratio"] < VOLUME_FILTER_MIN:
        return None   # Skip koin tanpa konfirmasi volume + candle

    # ── Hitung legacy signals untuk Alpha Engine ──
    sb=bayes.buat_sinyal_list(
        rsi=ind["rsi"],macd_up=ind["macd_up"],macd_down=ind["macd_down"],
        bb_bawah=ind["bb_bawah"],bb_atas=ind["bb_atas"],
        ichi_bullish=(ind["ichi_atas"] or ind["tk_up"]),
        vol_tinggi=ind["vol_tinggi"],bull_div=ind["bull_div"],
        ml_pred=ml_pred,ml_conf=ml_conf,
        fear_score=onchain["fear_greed"]["score"],
        funding_rate=onchain["funding_rate"]["rate"],
        btc_dom=onchain["btc_dominance"]["dominance"])
    bh=bayes.hitung_probabilitas(sb)
    mtf=multi_timeframe_analysis(symbol)
    ob=analisis_orderbook(client,symbol)
    mx=analisis_multi_exchange(client,symbol)
    btc=get_btc_kondisi(client)
    sent=get_sentiment_cached()

    # ══ ALPHA ENGINE v1.0 — Phase 4 ════════════
    sinyal_alpha = extract_sinyal(
        ind=ind, ml_pred=ml_pred, ml_conf=ml_conf,
        bh=bh, onchain=onchain, geo=geo, mtf=mtf,
        ob=ob, mx=mx, btc=btc, sent=sent,
        macro=get_macro_cached(), pattern=pattern
    )
    alpha_result = hitung_alpha_score(sinyal_alpha)
    skor         = alpha_result["skor_int"]
    detail       = alpha_result["detail"]

    # Penalty dari sinyal negatif
    if ind["rsi"]>72:         skor-=2;detail.append(f"RSOB({ind['rsi']:.1f})")
    if ind["macd_down"]:      skor-=1;detail.append("MACD↓")
    if ind["bb_atas"]:        skor-=1;detail.append("BB↑")
    if ind["bear_div"]:       skor-=2;detail.append("BearDiv⚠️")
    if ind["momentum"]<-3:    skor-=1;detail.append(f"Mom{ind['momentum']:.1f}%")
    if geo["skor_sell"]>=3:   skor-=4;detail.append("🔴GeoBlock")
    elif geo["skor_sell"]==2: skor-=2;detail.append("🟠Geo-2")
    if ob.get("block_entry"): skor-=5;detail.append("🚫OB:MANIP!")
    if btc["skor_market"]<=-2:skor-=3;detail.append(f"₿DUMP{btc['btc_change_1h']:+.1f}%")
    if sent["skor_sell"]>=2:  skor-=2;detail.append(f"🧠BEAR-{sent['skor_sell']}")
    if mtf["n_konfirmasi"]==0:skor-=2;detail.append("📊MTF0/3❌")
    # ═══════════════════════════════════════════

    # ══ INSTITUSIONAL DATA LAYER ═══════════════
    # Macro (FRED + AlphaVantage)
    try:
        macro = get_macro_cached()
        if macro["skor_buy"] >= 2:
            skor += 2; detail.append(f"📊Macro:{macro['sentimen'][:12]}+{macro['skor_buy']}")
        elif macro["skor_buy"] == 1:
            skor += 1; detail.append(f"📊Macro+1")
        if macro["skor_sell"] >= 2:
            skor -= 2; detail.append(f"📊Macro:{macro['sentimen'][:12]}-{macro['skor_sell']}")
        elif macro["skor_sell"] == 1:
            skor -= 1; detail.append(f"📊Macro-1")
    except Exception as e:
        macro = {"skor_buy": 0, "skor_sell": 0, "sentimen": "N/A"}

    # Market Depth (CoinGlass + Polygon) — hanya untuk BTC/ETH
    depth = {"skor_buy": 0, "skor_sell": 0, "sentimen": "N/A"}
    if any(k in symbol for k in ["BTC","ETH","SOL","BNB"]):
        try:
            depth = get_depth_score(symbol)
            if depth["skor_buy"] >= 2:
                skor += 2; detail.append(f"🌊Depth:{depth['sentimen'][:10]}+{depth['skor_buy']}")
            elif depth["skor_buy"] == 1:
                skor += 1; detail.append("🌊Depth+1")
            if depth["skor_sell"] >= 2:
                skor -= 2; detail.append(f"🌊Depth-{depth['skor_sell']}")
            elif depth["skor_sell"] == 1:
                skor -= 1; detail.append("🌊Depth-1")
        except Exception as e:
            pass

    # On-chain Pro (Glassnode) — hanya BTC/ETH
    onchain_pro = {"skor_buy": 0, "skor_sell": 0, "sentimen": "N/A"}
    if any(k in symbol for k in ["BTC","ETH"]):
        try:
            onchain_pro = get_onchain_pro_score(symbol)
            if onchain_pro["skor_buy"] >= 3:
                skor += 3; detail.append(f"🔗OnChain:{onchain_pro['sentimen'][:12]}🔥")
            elif onchain_pro["skor_buy"] >= 1:
                skor += onchain_pro["skor_buy"]
                detail.append(f"🔗OnChain+{onchain_pro['skor_buy']}")
            if onchain_pro["skor_sell"] >= 2:
                skor -= onchain_pro["skor_sell"]
                detail.append(f"🔗OnChain-{onchain_pro['skor_sell']}")
        except Exception as e:
            pass
    # ═══════════════════════════════════════════

    # ══ QUANT PATTERN ANALYSIS (Phase 2) ═══════
    try:
        pattern = get_pattern_cached(symbol, df)
        pb = pattern.get("skor_buy", 0)
        ps = pattern.get("skor_sell", 0)
        if pb > 0:
            skor += pb
            detail.append(f"🔬Quant+{pb}({pattern.get('summary','')[:20]})")
        if ps > 0:
            skor -= ps
            detail.append(f"🔬Quant-{ps}")
    except Exception:
        pattern = {"skor_buy": 0, "skor_sell": 0, "summary": "N/A"}
    # ═══════════════════════════════════════════

    # ══ ALPHA ENGINE (Phase 4) ════════════════
    try:
        alpha_eng  = get_alpha_engine()
        alpha_sigs = extract_alpha_signals(
            ind, ml_pred, ml_conf, onchain, geo,
            bayes["prob_buy"] if isinstance(bayes, dict) else bayes,
            mtf, ob, mx, btc, sent, macro,
            pattern if isinstance(pattern, dict) else None
        )
        alpha_score, alpha_detail, _ = alpha_eng.hitung_alpha_score(alpha_sigs)
        alpha_bonus = alpha_eng.skor_ke_trading_score(alpha_score)
        if alpha_bonus != 0:
            skor += alpha_bonus
            emoji = "🔥" if alpha_bonus > 0 else "❄️"
            detail.append(f"{emoji}Alpha:{alpha_score:.0f}({alpha_bonus:+d})")
    except Exception as e:
        alpha_sigs  = {}
        alpha_score = 50.0
    # ═══════════════════════════════════════════

    return {
        "symbol":symbol,"skor":skor,"harga":ind["harga"],"rsi":ind["rsi"],
        "alpha_sigs":alpha_sigs if 'alpha_sigs' in dir() else {},
        "alpha_score":alpha_score if 'alpha_score' in dir() else 50.0,
        "atr":ind["atr"],"momentum":ind["momentum"],"ml_pred":ml_pred,
        "ml_conf":ml_conf,"bayes":bh["prob_buy"],"detail":detail,
        "ind":ind,"df":df,"geo":geo,"mtf":mtf,"ob":ob,"mx":mx,
        "btc":btc,"sent":sent,"macro":macro,"depth":depth,"onchain_pro":onchain_pro
    }

# ══════════════════════════════════════════════
# FIX 5: PARALLEL SCAN ENGINE
# ══════════════════════════════════════════════

def scan_satu_koin(symbol):
    """Scan satu koin dengan timeout - dengan guard symbol key"""
    try:
        hasil = hitung_skor_koin(symbol)
        # Pastikan hasil punya key 'symbol'
        if hasil and "symbol" not in hasil:
            hasil["symbol"] = symbol
        return hasil
    except Exception as e:
        return None

def scan_semua_koin(koin_list, mode_cepat=False):
    """
    Scan koin dengan ThreadPoolExecutor untuk parallel processing.
    mode_cepat=True → hanya scan koin prioritas (lebih cepat)
    """
    if mode_cepat:
        target = KOIN_PRIORITAS[:15]   # Hanya 15 koin prioritas untuk scan cepat
        print(f"\n⚡ Quick Scan {len(target)} koin prioritas...")
    else:
        target = koin_list
        print(f"\n🔍 Full Scan {len(target)} koin (parallel)...")

    # Filter koin yang sudah ada posisi
    to_scan = []
    for symbol in target:
        spot_aktif    = symbol in posisi_spot and posisi_spot[symbol]["aktif"]
        futures_aktif = symbol in posisi_futures and posisi_futures[symbol].get("aktif")
        if not spot_aktif and not futures_aktif:
            to_scan.append(symbol)

    hasil_scan = []
    error_count = 0

    with ThreadPoolExecutor(max_workers=SCAN_MAX_WORKERS) as executor:
        futures_map = {executor.submit(scan_satu_koin, sym): sym
                       for sym in to_scan}

        for future in futures_map:
            symbol = futures_map[future]
            try:
                hasil = future.result(timeout=SCAN_TIMEOUT_PER_KOIN)
                if hasil:
                    mode_fut = tentukan_mode_futures(
                        hasil["skor"], hasil["ind"],
                        hasil["geo"], hasil["mtf"], hasil["ob"]
                    )
                    emoji = "🔥" if hasil["skor"] >= MIN_SCORE_SPOT else (
                            "📉" if hasil["skor"] <= -3 else "⚪")
                    print(f"  {emoji} {symbol:14} "
                          f"Skor:{hasil['skor']:+3} | "
                          f"Vol:{hasil['ind']['vol_ratio']:.1f}x | "
                          f"MTF:{hasil['mtf']['n_konfirmasi']}/3")
                    hasil["mode_futures"] = mode_fut
                    hasil_scan.append(hasil)
            except FuturesTimeout:
                error_count += 1
            except Exception as e:
                error_count += 1

    if error_count > 0:
        print(f"  ⚠️  {error_count} koin timeout/error (skip)")

    hasil_scan.sort(key=lambda x: x["skor"], reverse=True)
    return hasil_scan

# ══════════════════════════════════════════════
# HELPER: SL COOLDOWN & TREND FILTER
# ══════════════════════════════════════════════

def catat_sl_koin(symbol):
    """Catat bahwa symbol baru kena SL — block entry beberapa jam"""
    global sl_cooldown, sl_harian
    sl_cooldown[symbol] = time.time()

    # Hitung SL harian
    hari_ini = time.strftime("%Y-%m-%d")
    if sl_harian["tanggal"] != hari_ini:
        sl_harian = {"tanggal": hari_ini, "count": 0}
    sl_harian["count"] += 1

    print(f"  🛑 SL cooldown aktif untuk {symbol} "
          f"({SL_COOLDOWN_JAM} jam) | SL hari ini: {sl_harian['count']}")

def cek_sl_cooldown(symbol):
    """Cek apakah symbol masih dalam cooldown setelah SL"""
    if symbol not in sl_cooldown:
        return False
    selisih_jam = (time.time() - sl_cooldown[symbol]) / 3600
    return selisih_jam < SL_COOLDOWN_JAM

def cek_max_sl_harian():
    """Cek apakah sudah mencapai batas SL harian"""
    hari_ini = time.strftime("%Y-%m-%d")
    if sl_harian["tanggal"] != hari_ini:
        return False  # Hari baru, reset
    return sl_harian["count"] >= MAX_SL_HARIAN

def cek_trend_bullish(ind):
    """
    Cek apakah trend koin bullish untuk entry spot.
    Harga harus di atas EMA50 (uptrend).
    """
    harga = ind.get("harga", 0)
    ema50 = ind.get("ema50", 0)
    ema20 = ind.get("ema20", 0)
    if harga <= 0 or ema50 <= 0:
        return True  # Tidak bisa cek, default allow
    return harga > ema50 and ema20 > ema50

# ══════════════════════════════════════════════
# VALIDASI ENTRY v10.2
# ══════════════════════════════════════════════

def validasi_entry_ketat(symbol, skor, hasil, client):
    """
    Validasi entry v10.4 — tambah SL cooldown, trend filter, max SL harian.
    """
    alasan  = []
    warning = []
    boleh   = True

    ind = hasil.get("ind", {})
    mtf = hasil.get("mtf", {})
    btc = hasil.get("btc", {})

    # ── v10.2: Cek SL cooldown ──
    if cek_sl_cooldown(symbol):
        boleh = False
        jam_sisa = SL_COOLDOWN_JAM - (time.time() - sl_cooldown[symbol]) / 3600
        alasan.append(f"❌ Cooldown SL ({jam_sisa:.1f} jam lagi)")

    # ── v10.2: Cek max SL harian ──
    if cek_max_sl_harian():
        boleh = False
        alasan.append(f"❌ Max SL harian tercapai ({sl_harian['count']}/{MAX_SL_HARIAN})")

    # ── v10.2: Trend filter — harus uptrend ──
    if not cek_trend_bullish(ind):
        boleh = False
        alasan.append(
            f"❌ Downtrend: harga ${ind.get('harga',0):.4f} "
            f"< EMA50 ${ind.get('ema50',0):.4f}"
        )

    # ── FIX 1: Skor minimum ──
    if skor < MIN_SCORE_SPOT:
        boleh = False
        alasan.append(f"❌ Skor {skor} < min {MIN_SCORE_SPOT}")

    # ── FIX 2: Volume WAJIB ──
    vol_ratio = ind.get("vol_ratio", 0)
    if vol_ratio < VOLUME_FILTER_MIN:
        boleh = False
        alasan.append(f"❌ Volume {vol_ratio:.1f}x < {VOLUME_FILTER_MIN}x")

    # ── FIX 2: Candle konfirmasi ──
    if CANDLE_KONFIRMASI and not ind.get("candle_bullish", True):
        boleh = False
        alasan.append("❌ Candle terakhir bearish")

    # ── BTC filter ──
    if not btc.get("boleh_entry", True):
        boleh = False
        alasan.append(f"❌ BTC {btc.get('kondisi','?')}: {btc.get('alasan','')}")

    # ── Session filter ──
    from risk_manager import cek_session_aktif
    session = cek_session_aktif(client, symbol)

    if not session["aktif"]:
        bypass = (
            skor >= SESSION_BYPASS_SKOR and
            vol_ratio >= SESSION_BYPASS_VOL and
            mtf.get("semua_bullish", False)
        )
        if bypass:
            warning.append(
                f"⚡ Session bypass! Skor:{skor} "
                f"Vol:{vol_ratio:.1f}x MTF:3/3"
            )
        else:
            boleh = False
            alasan.append(f"❌ Session tidak aktif ({session['sesi']})")

    if boleh and not alasan:
        alasan.append(
            f"✅ Entry OK | Skor:{skor} | "
            f"Vol:{vol_ratio:.1f}x | "
            f"MTF:{mtf.get('n_konfirmasi',0)}/3"
        )

    return {"boleh": boleh, "alasan": alasan, "warning": warning}

# ── CEK SL/TP SPOT ────────────────────────────
def cek_semua_sl_tp_spot():
    waktu=time.strftime("%Y-%m-%d %H:%M:%S")
    for symbol in list(posisi_spot.keys()):
        pos=posisi_spot[symbol]
        if not pos["aktif"]: continue
        try:
            harga=float(client.get_symbol_ticker(symbol=symbol)["price"])
        except Exception as e:
            print(f"  ⚠️  Gagal harga {symbol}: {e}"); continue

        profit_pct=((harga-pos["harga_beli"])/pos["harga_beli"])*100
        update_trailing_spot(symbol,harga)
        trail=" 🔄" if pos.get("trailing_aktif") else ""
        sl_mode=f"[{pos.get('sl_kondisi','?')}]"
        pyr_info=get_pyramid_info(symbol)
        print(f"  💰 {symbol}: ${harga:,.4f} | P/L:{profit_pct:+.2f}%{trail} {sl_mode}{pyr_info}")

        early=cek_early_exit(symbol,pos,client)
        if early["exit_sekarang"] and profit_pct>0:
            try: client.order_market_sell(symbol=symbol,quantity=pos["qty"])
            except Exception as e: print(f"  ⚠️  Gagal sell: {e}")
            simpan_transaksi(symbol,pos["harga_beli"],harga,pos["waktu_beli"],waktu,"EARLY_EXIT")
            reset_pyramid(symbol)
            kirim_telegram(
                f"🚪 <b>EARLY EXIT - {symbol}</b>\n"
                f"💰 Entry: ${pos['harga_beli']:,.4f}\n"
                f"💰 Exit : ${harga:,.4f}\n"
                f"📈 Profit: <b>+{profit_pct:.2f}%</b> ✅\n"
                f"📋 {early['alasan']}\n🕐 {waktu}"
            )
            posisi_spot[symbol]["aktif"]=False; continue

        if harga>=pos["take_profit"]:
            if is_paper_mode():
                paper_jual_spot(symbol, harga, "PAPER_TP")
            else:
                try: client.order_market_sell(symbol=symbol,quantity=pos["qty"])
                except Exception as e: print(f"  ⚠️  Gagal sell: {e}")
            simpan_transaksi(symbol,pos["harga_beli"],harga,pos["waktu_beli"],waktu,"SPOT_TP")
            try:
                update_alpha_result("ml_ensemble_buy", True)
                update_alpha_result("mtf_3_3", pos.get("mtf_all_bull", False))
            except Exception: pass
            reset_pyramid(symbol)
            mode_label = "📝[PAPER] " if is_paper_mode() else ""
            kirim_telegram(
                f"🎯 <b>{mode_label}TAKE PROFIT! - {symbol}</b>\n"
                f"💰 Entry: ${pos['harga_beli']:,.4f}\n"
                f"💰 Exit : ${harga:,.4f}\n"
                f"📈 Profit: <b>+{profit_pct:.2f}%</b> ✅\n🕐 {waktu}"
            )
            posisi_spot[symbol]["aktif"]=False

        elif harga<=pos["stop_loss"]:
            alasan="SPOT_TRAILING" if pos.get("trailing_aktif") else "SPOT_SL"
            emoji="🔄" if pos.get("trailing_aktif") else "🛑"
            if is_paper_mode():
                paper_jual_spot(symbol, harga, alasan)
            else:
                eksekusi_jual_multi(
                    client, symbol, harga, pos["qty"],
                    alasan=alasan, kirim_telegram=kirim_telegram,
                    paper_mode=False
                )
            simpan_transaksi(symbol,pos["harga_beli"],harga,pos["waktu_beli"],waktu,alasan)
            try:
                update_alpha_result("ml_ensemble_buy", False)
            except Exception: pass
            reset_pyramid(symbol)
            catat_sl_koin(symbol)  # ← v10.2: aktifkan cooldown
            kirim_telegram(
                f"{emoji} <b>{alasan}! - {symbol}</b>\n"
                f"💰 Entry: ${pos['harga_beli']:,.4f}\n"
                f"💰 Exit : ${harga:,.4f}\n"
                f"📉 P/L: <b>{profit_pct:.2f}%</b> ❌\n"
                f"📊 SL mode: {pos.get('sl_kondisi','NORMAL')}\n"
                f"⏳ Cooldown: {SL_COOLDOWN_JAM} jam\n🕐 {waktu}"
            )
            posisi_spot[symbol]["aktif"]=False

# ── CACHE LOT SIZE — hindari spam exchange info API ───────────
_lot_size_cache = {}   # {symbol: {"step": float, "min_qty": float, "min_notional": float, "waktu": float}}
_LOT_CACHE_TTL  = 3600  # 1 jam

def _get_lot_size(symbol):
    """
    Ambil LOT_SIZE & MIN_NOTIONAL filter dari Binance spot exchange info.
    Di-cache 1 jam agar tidak spam API setiap order.

    Return dict:
        step         : float  — stepSize (granularitas qty, mis. 0.001)
        min_qty      : float  — minQty Binance
        min_notional : float  — nilai order minimum dalam USDT (biasanya 5–10 USDT)
    """
    global _lot_size_cache
    sekarang = time.time()
    cached   = _lot_size_cache.get(symbol)
    if cached and sekarang - cached["waktu"] < _LOT_CACHE_TTL:
        return cached

    try:
        info = client.get_symbol_info(symbol)
        if not info:
            raise ValueError(f"Symbol {symbol} tidak ditemukan")

        step         = 1.0
        min_qty      = 0.0
        min_notional = 10.0   # default aman

        for f in info.get("filters", []):
            ft = f.get("filterType", "")
            if ft == "LOT_SIZE":
                step    = float(f["stepSize"])
                min_qty = float(f["minQty"])
            elif ft in ("MIN_NOTIONAL", "NOTIONAL"):
                min_notional = float(f.get("minNotional") or f.get("minQty", 10.0))

        result = {"step": step, "min_qty": min_qty,
                  "min_notional": min_notional, "waktu": sekarang}
        _lot_size_cache[symbol] = result
        return result

    except Exception as e:
        print(f"  ⚠️  Gagal ambil LOT_SIZE {symbol}: {e} — pakai fallback")
        # Fallback konservatif: cache sebentar agar tidak spam
        fallback = {"step": 0.001, "min_qty": 0.0,
                    "min_notional": 10.0, "waktu": sekarang}
        _lot_size_cache[symbol] = fallback
        return fallback

def _bulatkan_ke_step(qty, step):
    """
    Bulatkan qty ke bawah sesuai stepSize Binance.
    Contoh: qty=0.12345, step=0.001 → 0.123
    Pakai integer math untuk hindari floating-point error.
    """
    if step <= 0:
        return qty
    # Hitung presisi desimal dari step (mis. 0.001 → 3)
    precision = max(0, round(-round(float(f"{step:.10f}").rstrip("0").find(".") - len(
        float(f"{step:.10f}").rstrip("0").replace(".", "")), 0)))
    # Cara lebih robust: floor ke kelipatan step
    qty_floored = (qty // step) * step
    return round(qty_floored, 8)

def _validasi_min_notional(symbol, qty, harga, lot):
    """
    Cek apakah qty * harga memenuhi MIN_NOTIONAL Binance.
    Kembalikan qty yang sudah aman, atau None jika tidak bisa dipenuhi.
    """
    notional = qty * harga
    if notional < lot["min_notional"]:
        # Coba naikkan qty ke minimum yang memenuhi notional
        qty_min = lot["min_notional"] / harga
        qty_min = _bulatkan_ke_step(qty_min, lot["step"])
        # Tambah 1 step sebagai buffer untuk floating-point
        qty_min += lot["step"]
        qty_min  = round(qty_min, 8)
        print(f"  🔧 [{symbol}] Qty dinaikkan ke {qty_min} "
              f"(min notional ${lot['min_notional']:.2f})")
        return qty_min
    return qty

def hitung_qty_spot(symbol, harga):
    """
    Hitung qty spot menggunakan modal TRADE_USDT_SPOT,
    disesuaikan dengan LOT_SIZE & MIN_NOTIONAL filter Binance.
    """
    lot = _get_lot_size(symbol)
    qty = TRADE_USDT_SPOT / harga
    qty = _bulatkan_ke_step(qty, lot["step"])

    # Cek min qty Binance
    if lot["min_qty"] > 0 and qty < lot["min_qty"]:
        print(f"  ⚠️  [{symbol}] Qty {qty} < minQty {lot['min_qty']} — skip")
        return None

    # Cek min notional
    qty = _validasi_min_notional(symbol, qty, harga, lot)
    return qty

def _hitung_qty_dari_modal(symbol, harga, modal):
    """
    Hitung qty berdasarkan modal dinamis (Kelly Criterion),
    disesuaikan dengan LOT_SIZE & MIN_NOTIONAL filter Binance.
    """
    lot = _get_lot_size(symbol)
    qty = modal / harga
    qty = _bulatkan_ke_step(qty, lot["step"])

    # Cek min qty Binance
    if lot["min_qty"] > 0 and qty < lot["min_qty"]:
        print(f"  ⚠️  [{symbol}] Qty Kelly {qty} < minQty {lot['min_qty']} — pakai minQty")
        qty = lot["min_qty"]

    # Cek min notional
    qty = _validasi_min_notional(symbol, qty, harga, lot)
    return qty

def buka_posisi_spot(hasil):
    waktu=time.strftime("%Y-%m-%d %H:%M:%S")
    symbol=hasil["symbol"];harga=hasil["harga"];atr=hasil["atr"]

    # ── v10.4: Kelly Criterion Position Sizing ──
    try:
        akun    = client.get_account()
        saldo   = next((float(a["free"]) for a in akun["balances"]
                       if a["asset"] == "USDT"), TRADE_USDT_SPOT)
        modal   = hitung_posisi_size(saldo, hasil["skor"])
        pos_info = get_position_info(saldo, hasil["skor"])
    except Exception:
        modal    = TRADE_USDT_SPOT
        pos_info = {"metode": "DEFAULT", "kelly_f": 0,
                    "win_rate": 0, "modal": modal}

    qty = _hitung_qty_dari_modal(symbol, harga, modal)
    if qty is None:
        print(f"  ⚠️  [{symbol}] Qty tidak valid (LOT_SIZE check gagal) — batal beli")
        kirim_telegram(
            f"⚠️ <b>Order Batal - {symbol}</b>\n"
            f"❌ Qty tidak memenuhi LOT_SIZE/MIN_NOTIONAL Binance\n"
            f"💡 Coba naikkan TRADE_USDT_SPOT\n"
            f"🕐 {waktu}"
        )
        return
    dyn_sl=hitung_dynamic_sl(harga,atr,hasil.get("df"))
    sl=dyn_sl["sl"];tp=dyn_sl["tp"]
    sl_pct=dyn_sl["sl_pct"];tp_pct=dyn_sl["tp_pct"]

    print(f"\n  {'📝[PAPER]' if is_paper_mode() else '💰[LIVE]'} [{symbol}] SPOT BUY v10.4! "
          f"Skor:{hasil['skor']} Modal:${modal:.0f} "
          f"({pos_info['metode']}) Qty:{qty}")

    if is_paper_mode():
        # ── PAPER MODE: simulasi tanpa order nyata ──
        ok = paper_beli_spot(symbol, harga, qty,
                             dyn_sl["sl"], dyn_sl["tp"],
                             " | ".join(hasil["detail"][:4]))
        if not ok:
            return
    else:
        # ── LIVE MODE: eksekusi di semua exchange ──
        print(f"  🌐 Eksekusi multi-exchange untuk {symbol}...")
        hasil_exec = eksekusi_beli_multi(
            client, symbol, harga, qty,
            skor=hasil["skor"],
            kirim_telegram=kirim_telegram,
            paper_mode=False
        )
        if "binance" not in hasil_exec.get("sukses", []):
            print(f"  ⚠️  Binance gagal — posisi tidak dicatat")
            return

    last_entry_time[symbol]=time.time()
    posisi_spot[symbol]={
        "aktif":True,"harga_beli":harga,"harga_tertinggi":harga,
        "stop_loss":sl,"take_profit":tp,"waktu_beli":waktu,
        "qty":qty,"atr":atr,"trailing_aktif":False,
        "sl_kondisi":dyn_sl["kondisi"],"sl_multiplier":dyn_sl["multiplier"],
        "modal":modal,"kelly_f":pos_info.get("kelly_f",0)
    }

    mtf=hasil.get("mtf",{});ob=hasil.get("ob",{})
    geo=hasil.get("geo",{});mx=hasil.get("mx",{})
    btc=hasil.get("btc",{});sent=hasil.get("sent",{})
    ind=hasil.get("ind",{})

    kirim_telegram(
        f"💰 <b>SPOT BUY v10.4 - {symbol}</b>\n"
        f"⭐ Skor    : <b>{hasil['skor']}</b> (min {MIN_SCORE_SPOT})\n"
        f"🤖 ML      : {hasil['ml_pred']} ({hasil['ml_conf']:.0f}%)\n"
        f"📊 MTF     : {mtf.get('summary','N/A')}\n"
        f"📊 Volume  : {ind.get('vol_ratio',0):.2f}x rata-rata\n"
        f"🌐 Multi-Ex: {mx.get('cross_ob',{}).get('sinyal','N/A')}\n"
        f"₿  BTC     : {btc.get('kondisi','N/A')} ({btc.get('btc_change_1h',0):+.2f}%)\n"
        f"🌍 Geo     : {geo.get('sentiment','N/A')}\n\n"
        f"💰 Entry : <b>${harga:,.4f}</b>\n"
        f"🔢 Qty   : {qty}\n"
        f"🛑 SL    : <b>${sl:,.4f}</b> (-{sl_pct:.1f}%) [{dyn_sl['kondisi']}]\n"
        f"🎯 TP    : <b>${tp:,.4f}</b> (+{tp_pct:.1f}%)\n\n"
        f"✅ {' | '.join(hasil['detail'][:6])}\n🕐 {waktu}"
    )

def print_status_spot():
    aktif=[(s,p) for s,p in posisi_spot.items() if p["aktif"]]
    if not aktif: print("  📭 Tidak ada posisi spot aktif"); return
    print(f"  💰 Spot aktif: {len(aktif)}/{MAX_POSISI_SPOT}")
    for symbol,pos in aktif:
        try:
            harga=float(client.get_symbol_ticker(symbol=symbol)["price"])
            pl_pct=((harga-pos["harga_beli"])/pos["harga_beli"])*100
            trail=" 🔄" if pos.get("trailing_aktif") else ""
            print(f"  {'📈' if pl_pct>=0 else '📉'} {symbol:14} "
                  f"${pos['harga_beli']:,.4f}→${harga:,.4f} "
                  f"P/L:{pl_pct:+.2f}%{trail}")
        except: pass

# ══════════════════════════════════════════════
# FIX 3: DUAL-SPEED SCAN LOOP
# ══════════════════════════════════════════════

def jalankan_siklus(siklus, mode_cepat=False):
    waktu=time.strftime("%Y-%m-%d %H:%M:%S")
    tipe="⚡ QUICK" if mode_cepat else "🔍 FULL"
    print(f"\n{'='*65}")
    print(f"⏰ {waktu} | Siklus #{siklus} | {tipe} SCAN | v10.4")
    print(f"{'='*65}")

    if not mode_cepat:
        print("\n📊 Kondisi Market:")
        print_kondisi_market(client)
        print_regime_status(client)  # ← v10.4: regime detection
        sent=get_sentiment_cached()
        print(f"  🧠 Sentiment: {sent.get('sentiment','N/A')}")

    if is_paper_mode():
        print_status_paper(client)
        cek_paper_sl_tp(client, kirim_telegram)
    else:
        print("\n💰 Posisi SPOT:")
        print_status_spot()
        cek_semua_sl_tp_spot()
    cek_semua_pyramid(posisi_spot,client,TRADE_USDT_SPOT,kirim_telegram)

    if not mode_cepat:
        print("\n⚡ Posisi FUTURES:")
        print_status_futures()
        cek_posisi_futures(client,kirim_telegram,simpan_transaksi)
        cek_jadwal_laporan(posisi_spot,posisi_futures,kirim_telegram,TRADE_USDT_SPOT)
        cek_jadwal_retrain(client,kirim_telegram)

    n_spot=sum(1 for p in posisi_spot.values() if p["aktif"])
    n_futures=sum(1 for p in posisi_futures.values() if p.get("aktif"))
    slot_spot=MAX_POSISI_SPOT-n_spot
    slot_futures=MAX_POSISI_FUTURES-n_futures

    # ── v10.2: Info SL harian ──
    hari_ini = time.strftime("%Y-%m-%d")
    sl_hari  = sl_harian["count"] if sl_harian["tanggal"] == hari_ini else 0
    n_cooldown = sum(1 for s,t in sl_cooldown.items()
                     if (time.time()-t)/3600 < SL_COOLDOWN_JAM)
    print(f"\n  💰 Spot: {n_spot}/{MAX_POSISI_SPOT} | "
          f"⚡ Futures: {n_futures}/{MAX_POSISI_FUTURES} | "
          f"🛑 SL hari ini: {sl_hari}/{MAX_SL_HARIAN} | "
          f"⏳ Cooldown: {n_cooldown} koin")

    # ── v10.2: Stop semua entry jika max SL harian tercapai ──
    if cek_max_sl_harian():
        print(f"  🚫 MAX SL HARIAN TERCAPAI ({sl_hari}/{MAX_SL_HARIAN}) — entry diblokir!")
        if sl_hari == MAX_SL_HARIAN:  # Kirim notif hanya sekali
            kirim_telegram(
                f"🚫 <b>Max SL Harian Tercapai!</b>\n\n"
                f"📊 SL hari ini: {sl_hari}/{MAX_SL_HARIAN}\n"
                f"⏰ Entry diblokir hingga besok\n"
                f"🛡️ Modal terlindungi dari kerugian lebih lanjut\n"
                f"🕐 {time.strftime('%Y-%m-%d %H:%M:%S')}"
            )
        return

    if slot_spot<=0 and slot_futures<=0:
        print("  ✋ Semua slot penuh!"); return

    koin_list  = get_top_koin_by_volume()
    hasil_scan = scan_semua_koin(koin_list, mode_cepat=mode_cepat)

    # ── v10.4: Ambil regime dan sesuaikan min skor ──
    try:
        regime     = get_regime_params(client)
        min_skor_r = regime["min_skor"]
        max_pos_r  = regime["max_posisi"]
        print(f"  📊 Regime: {regime['regime']} | "
              f"MinSkor:{min_skor_r} | MaxPos:{max_pos_r}")
        # Stop entry jika regime BEAR_KUAT
        if max_pos_r == 0:
            print("  🐻 BEAR KUAT — entry spot diblokir!")
            return
    except Exception:
        min_skor_r = MIN_SCORE_SPOT
        max_pos_r  = MAX_POSISI_SPOT

    # Gunakan min skor yang lebih ketat antara config dan regime
    min_skor_efektif = max(MIN_SCORE_SPOT, min_skor_r)

    kandidat = [h for h in hasil_scan if h["skor"] >= min_skor_efektif]

    # ── v10.4: Correlation filter ──
    posisi_aktif_sym = {s: p for s, p in posisi_spot.items() if p.get("aktif")}
    try:
        kandidat = filter_kandidat_diversifikasi(
            client, kandidat, posisi_aktif_sym, max_pos_r
        )
    except Exception as e:
        print(f"  ⚠️  Correlation filter error: {e}")

    if kandidat:
        print(f"\n🏆 Kandidat ({len(kandidat)} lolos skor ≥ {min_skor_efektif}):")
        for i,k in enumerate(kandidat[:3],1):
            print(f"  {i}. {k['symbol']:14} "
                  f"Skor:{k['skor']:+3} | "
                  f"Vol:{k['ind']['vol_ratio']:.1f}x | "
                  f"MTF:{k['mtf']['n_konfirmasi']}/3")

    for hasil in kandidat:  # ← Iterasi kandidat yang sudah difilter
        if slot_spot<=0 and slot_futures<=0: break
        symbol=hasil["symbol"];skor=hasil["skor"]
        mode_fut=hasil["mode_futures"];harga=hasil["harga"]
        atr=hasil["atr"];detail_str=" | ".join(hasil["detail"])

        if (symbol in posisi_spot and posisi_spot[symbol]["aktif"]) or \
           (symbol in posisi_futures and posisi_futures[symbol].get("aktif")):
            continue

        if time.time()-last_entry_time.get(symbol,0)<3600: continue

        # ── FIX 1+2+4: Validasi ketat ──
        validasi=validasi_entry_ketat(symbol,skor,hasil,client)
        if not validasi["boleh"]:
            if skor >= MIN_SCORE_SPOT - 1:  # Hanya print yang hampir lolos
                print(f"  🚫 [{symbol}] {' | '.join(validasi['alasan'])}")
            continue
        if validasi["warning"]:
            print(f"  ⚠️  [{symbol}] {' | '.join(validasi['warning'])}")

        # ── FIX 1: Futures wajib MTF 3/3 ──
        if mode_fut in ["LONG","SHORT"] and MTF_WAJIB_FUTURES:
            if not hasil["mtf"]["semua_bullish"] and mode_fut=="LONG":
                print(f"  🚫 [{symbol}] Futures LONG wajib MTF 3/3")
                mode_fut = "SKIP"

        if mode_fut=="LONG" and slot_futures>0:
            print(f"\n  ⚡ [{symbol}] → FUTURES LONG (Skor:{skor})")
            sukses=buka_long(client,symbol,harga,atr,skor,detail_str,kirim_telegram)
            if sukses: slot_futures-=1;n_futures+=1;last_entry_time[symbol]=time.time()

        elif mode_fut=="SHORT" and slot_futures>0:
            print(f"\n  📉 [{symbol}] → FUTURES SHORT (Skor:{skor})")
            sukses=buka_short(client,symbol,harga,atr,skor,detail_str,kirim_telegram)
            if sukses: slot_futures-=1;n_futures+=1;last_entry_time[symbol]=time.time()

        elif skor>=MIN_SCORE_SPOT and slot_spot>0 \
             and hasil["mtf"]["cukup_bullish"] \
             and not hasil["ob"]["block_entry"]:
            print(f"\n  💰 [{symbol}] → SPOT BUY (Skor:{skor})")
            buka_posisi_spot(hasil)
            slot_spot-=1;n_spot+=1

# ── MAIN ──────────────════════════════════════
print("="*65)
print("   BINANCE TRADING BOT v10.4 - FULL AI HEDGE FUND")
print(f"   📊 Kelly Sizing   : otomatis dari win rate")
print(f"   🌊 Market Regime  : Bull/Bear/Sideways adaptif")
print(f"   🔄 Corr Filter    : hindari koin berkorelasi")
print(f"   📊 FRED+CoinGlass+Glassnode: aktif")
print(f"   📊 FRED API     : Macro Fed, inflasi, yield curve")
print(f"   🌊 CoinGlass    : Liquidasi, OI, Long/Short ratio")
print(f"   🔗 Glassnode    : On-chain whale movement")
print(f"   💹 AlphaVantage : Forex, commodity correlation")
print(f"   📈 Polygon.io   : Market microstructure")
print("="*65)

ml_aktif=load_model()
geo_awal=get_geo_cached()
btc_awal=get_btc_kondisi(client)
ses_awal=cek_session_aktif(client)
sent_awal=get_sentiment_cached()
koin_awal=get_top_koin_by_volume()

kirim_telegram(
    "🚀 <b>Trading Bot v10.4 - Full AI Hedge Fund!</b>\n\n"
    f"📊 <b>Data institusional baru:</b>\n"
    f"  📊 FRED API    : Makro Fed, inflasi, yield\n"
    f"  🌊 CoinGlass   : Liquidasi, OI, L/S ratio\n"
    f"  🔗 Glassnode   : Whale on-chain movement\n"
    f"  💹 AlphaVantage: Forex & commodity\n"
    f"  📈 Polygon.io  : Market microstructure\n\n"
    f"🛡️ Anti-SL: cooldown {SL_COOLDOWN_JAM}h, max {MAX_SL_HARIAN}/hari\n"
    f"📊 Total scan : {len(koin_awal)} koin\n"
    f"₿  BTC Filter : {btc_awal['kondisi']}\n"
    f"🌍 Geo        : {geo_awal['sentiment']}\n"
    f"🤖 ML         : {'✅' if ml_aktif else '⚠️'}\n"
    f"📌 Mode   : {'📝 PAPER TRADING' if is_paper_mode() else '🔴 LIVE TRADING'}\n"
    "📌 Status: ✅ Berjalan 24/7"
)

print("\n💰 Saldo:")
cek_saldo_semua_exchange(client)
print_exchange_status()
print_alpha_status()
print("="*65)

siklus=0
waktu_full_terakhir=time.time()

while bot_running:
    siklus+=1
    sekarang=time.time()

    # ── FIX 3: Dual-speed logic ──
    sudah_cukup_waktu_full = (sekarang - waktu_full_terakhir) >= SCAN_FULL_INTERVAL
    mode_cepat = not sudah_cukup_waktu_full

    if sudah_cukup_waktu_full:
        waktu_full_terakhir = sekarang

    try:
        jalankan_siklus(siklus, mode_cepat=mode_cepat)
        reconnect_count=0

        interval = SCAN_CEPAT_INTERVAL if mode_cepat else SCAN_FULL_INTERVAL
        print(f"\n⏳ Tunggu {interval}dtk "
              f"({'quick' if mode_cepat else 'full'} mode)...")
        time.sleep(interval)

    except (BinanceAPIException,ConnectionError,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout) as e:
        print(f"\n📡 Koneksi error: {e}"); reconnect_client()

    except Exception as e:
        print(f"\n⚠️  Error siklus #{siklus}: {e}")
        kirim_telegram(
            f"⚠️ <b>Bot Error #{siklus}</b>\n\n"
            f"<code>{str(e)[:200]}</code>\n"
            f"🔄 Tetap berjalan...\n"
            f"🕐 {time.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        time.sleep(30)