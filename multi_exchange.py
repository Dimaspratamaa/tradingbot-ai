# ============================================
# MULTI EXCHANGE ENGINE v2.0
# Exchange: Binance + Indodax + Tokocrypto + Hyperliquid
#
# Indodax    : Exchange rupiah Indonesia terbesar
# Tokocrypto : Exchange Indonesia (ex-Binance partner)
# Hyperliquid: DEX on-chain perpetual futures
#
# Fitur:
#   1. Price aggregator semua exchange
#   2. Cross Order Book analysis
#   3. Arbitrase scanner IDR vs USDT
#   4. Hyperliquid funding rate & OI
# ============================================

import requests
import ssl as _ssl_patch
import urllib3 as _urllib3_patch
_urllib3_patch.disable_warnings(_urllib3_patch.exceptions.InsecureRequestWarning)
try:
    _ssl_patch._create_default_https_context = _ssl_patch._create_unverified_context
except Exception:
    pass

import time
import hmac
import hashlib
import json
import os
from datetime import datetime

# ── API CREDENTIALS ───────────────────────────
# Indodax
# ── API KEYS — dari environment variable SAJA ──
# Jangan hardcode key di sini! Isi di file .env
import pathlib as _pl
_env_file = _pl.Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

INDODAX_KEY    = os.environ.get("INDODAX_API_KEY", "WSPHWXIV-BVUCOUQQ-VUSGPPQ2-USAVODEX-FTWCJDHH")
INDODAX_SECRET = os.environ.get("INDODAX_API_SECRET", "9c7773e8fdaab356eb551ed99814536e02e6d30aead2410035a7c63c21b1019268a25ddbdcadb52b")

# Tokocrypto
TOKO_KEY       = os.environ.get("TOKOCRYPTO_API_KEY", "F87dB12E5a0979897F94A76012B4aB14ENIvMv6w2bUvLubgUg5ujiu1h6lNPMlz")
TOKO_SECRET    = os.environ.get("TOKOCRYPTO_API_SECRET", "f153E5B1cc5aa45b76f4E583b5bF6f21MjXDwtsfFJVmnLEPdWOaObyggxRkhruo")

# Hyperliquid (wallet address untuk trading)
# PERINGATAN: HL_SECRET adalah private key Ethereum!
HL_WALLET      = os.environ.get("HYPERLIQUID_WALLET", "0x5026D53f5B4A882bF4baFe5D4487E1885B96C29a")
HL_SECRET      = os.environ.get("HYPERLIQUID_SECRET", "0x24fd1d859639b85da24de77d397821e72994cadeca11e695169d91a3713044cb")

# Rate IDR/USD — update berkala
IDR_PER_USD    = 16200   # Estimasi, diupdate otomatis

# Threshold arbitrase
ARBI_THRESHOLD = 0.5     # 0.5% profit minimum setelah fee

# ── SYMBOL MAPPING ────────────────────────────
# Format berbeda tiap exchange
SYMBOL_MAP = {
    "BTCUSDT" : {"indodax": "btc_idr",  "toko": "BTC_USDT",  "hl": "BTC"},
    "ETHUSDT" : {"indodax": "eth_idr",  "toko": "ETH_USDT",  "hl": "ETH"},
    "BNBUSDT" : {"indodax": "bnb_idr",  "toko": "BNB_USDT",  "hl": None},
    "SOLUSDT" : {"indodax": "sol_idr",  "toko": "SOL_USDT",  "hl": "SOL"},
    "XRPUSDT" : {"indodax": "xrp_idr",  "toko": "XRP_USDT",  "hl": "XRP"},
    "ADAUSDT" : {"indodax": "ada_idr",  "toko": "ADA_USDT",  "hl": "ADA"},
    "DOGEUSDT": {"indodax": "doge_idr", "toko": "DOGE_USDT", "hl": "DOGE"},
    "AVAXUSDT": {"indodax": "avax_idr", "toko": "AVAX_USDT", "hl": "AVAX"},
    "DOTUSDT" : {"indodax": "dot_idr",  "toko": "DOT_USDT",  "hl": "DOT"},
    "LINKUSDT": {"indodax": "link_idr", "toko": "LINK_USDT", "hl": "LINK"},
    "POLUSDT" : {"indodax": "pol_idr",  "toko": "POL_USDT",  "hl": None},
    "UNIUSDT" : {"indodax": "uni_idr",  "toko": "UNI_USDT",  "hl": "UNI"},
    "TONUSDT" : {"indodax": "ton_idr",  "toko": "TON_USDT",  "hl": None},
    "NEARUSDT": {"indodax": "near_idr", "toko": "NEAR_USDT", "hl": "NEAR"},
    "ARBUSDT" : {"indodax": None,        "toko": "ARB_USDT",  "hl": "ARB"},
    "SUIUSDT" : {"indodax": None,        "toko": "SUI_USDT",  "hl": "SUI"},
}

# ══════════════════════════════════════════════
# HELPER: UPDATE KURS IDR
# ══════════════════════════════════════════════

_idr_cache = {"rate": 16200, "waktu": 0}

def get_idr_rate():
    """Ambil kurs IDR/USD terkini"""
    global _idr_cache
    if time.time() - _idr_cache["waktu"] < 3600:
        return _idr_cache["rate"]
    try:
        resp = requests.get(
            "https://open.er-api.com/v6/latest/USD",
            timeout=5
        )
        data = resp.json()
        rate = data.get("rates", {}).get("IDR", 16200)
        _idr_cache = {"rate": rate, "waktu": time.time()}
        return rate
    except:
        return _idr_cache["rate"]

def idr_to_usd(harga_idr):
    """Konversi harga IDR ke USD"""
    return harga_idr / get_idr_rate()

# ══════════════════════════════════════════════
# INDODAX CONNECTOR
# ══════════════════════════════════════════════

def indodax_get_price(pair="btc_idr"):
    """
    Ambil harga dari Indodax Public API (tanpa key).
    Return harga dalam USD (dikonversi dari IDR).
    """
    try:
        url  = f"https://indodax.com/api/{pair}/ticker"
        resp = requests.get(url, timeout=8)
        data = resp.json()
        ticker = data.get("ticker", {})
        if ticker:
            harga_idr = float(ticker.get("last", 0))
            harga_usd = idr_to_usd(harga_idr)
            vol_idr   = float(ticker.get("vol_idr", 0))
            return {
                "exchange" : "indodax",
                "pair"     : pair,
                "harga_idr": harga_idr,
                "harga_usd": harga_usd,
                "volume"   : vol_idr / get_idr_rate(),
                "bid_usd"  : idr_to_usd(float(ticker.get("buy", 0))),
                "ask_usd"  : idr_to_usd(float(ticker.get("sell", 0))),
            }
    except Exception as e:
        print(f"  ⚠️  Indodax {pair} error: {e}")
    return None

def indodax_place_order(pair, order_type, price_idr, amount):
    """Eksekusi order di Indodax"""
    if not INDODAX_KEY or not INDODAX_SECRET:
        return {"error": "Indodax API key tidak tersedia"}
    try:
        nonce     = str(int(time.time() * 1000))
        params    = {
            "method"     : "trade",
            "pair"       : pair,
            "type"       : order_type,   # "buy" atau "sell"
            "price"      : str(int(price_idr)),
            "idr"        : str(int(amount)) if order_type == "buy" else "",
            "nonce"      : nonce
        }
        body      = "&".join(f"{k}={v}" for k,v in params.items())
        signature = hmac.new(
            INDODAX_SECRET.encode(),
            body.encode(),
            hashlib.sha512
        ).hexdigest()
        headers   = {
            "Key"  : INDODAX_KEY,
            "Sign" : signature
        }
        resp = requests.post(
            "https://indodax.com/tapi",
            data=params, headers=headers, timeout=15
        )
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

def indodax_get_balance():
    """Cek saldo IDR di Indodax"""
    if not INDODAX_KEY:
        return {"idr": 0, "usd": 0}
    try:
        nonce  = str(int(time.time() * 1000))
        params = {"method": "getInfo", "nonce": nonce}
        body   = "&".join(f"{k}={v}" for k,v in params.items())
        sig    = hmac.new(
            INDODAX_SECRET.encode(),
            body.encode(), hashlib.sha512
        ).hexdigest()
        headers = {"Key": INDODAX_KEY, "Sign": sig}
        resp    = requests.post(
            "https://indodax.com/tapi",
            data=params, headers=headers, timeout=10
        )
        data    = resp.json()
        if data.get("success"):
            balance = data["return"]["balance"]
            idr_bal = float(balance.get("idr", 0))
            return {"idr": idr_bal, "usd": idr_to_usd(idr_bal)}
    except Exception as e:
        print(f"  ⚠️  Indodax balance error: {e}")
    return {"idr": 0, "usd": 0}

# ══════════════════════════════════════════════
# TOKOCRYPTO CONNECTOR
# ══════════════════════════════════════════════

def toko_get_price(symbol="BTC_USDT"):
    """Ambil harga dari Tokocrypto Public API"""
    try:
        url    = "https://www.tokocrypto.com/open/v1/market/ticker"
        params = {"symbol": symbol}
        resp   = requests.get(url, params=params, timeout=8)
        data   = resp.json()
        if data.get("code") == 0 and data.get("data"):
            d = data["data"]
            return {
                "exchange": "tokocrypto",
                "symbol"  : symbol,
                "harga_usd": float(d.get("c", 0)),
                "volume"  : float(d.get("q", 0)),
                "bid_usd" : float(d.get("b", 0)),
                "ask_usd" : float(d.get("a", 0)),
                "change"  : float(d.get("p", 0))
            }
    except Exception as e:
        print(f"  ⚠️  Tokocrypto {symbol} error: {e}")
    return None

def _toko_sign(params, secret):
    """Generate signature Tokocrypto"""
    query  = "&".join(f"{k}={v}" for k,v in sorted(params.items()))
    return hmac.new(
        secret.encode(),
        query.encode(),
        hashlib.sha256
    ).hexdigest()

def toko_place_order(symbol, side, qty, order_type="MARKET"):
    """Eksekusi order di Tokocrypto"""
    if not TOKO_KEY or not TOKO_SECRET:
        return {"error": "Tokocrypto API key tidak tersedia"}
    try:
        ts     = int(time.time() * 1000)
        params = {
            "symbol"    : symbol,
            "side"      : side.upper(),
            "type"      : order_type,
            "quantity"  : str(qty),
            "timestamp" : ts,
            "recvWindow": 5000
        }
        params["signature"] = _toko_sign(params, TOKO_SECRET)
        headers = {"X-MBX-APIKEY": TOKO_KEY}
        resp    = requests.post(
            "https://www.tokocrypto.com/open/v1/orders",
            params=params, headers=headers, timeout=15
        )
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

def toko_get_balance():
    """Cek saldo USDT di Tokocrypto"""
    if not TOKO_KEY:
        return 0.0
    try:
        ts     = int(time.time() * 1000)
        params = {"timestamp": ts, "recvWindow": 5000}
        params["signature"] = _toko_sign(params, TOKO_SECRET)
        headers = {"X-MBX-APIKEY": TOKO_KEY}
        resp    = requests.get(
            "https://www.tokocrypto.com/open/v1/account/spot",
            params=params, headers=headers, timeout=10
        )
        data = resp.json()
        if data.get("code") == 0:
            for asset in data.get("data", {}).get("balances", []):
                if asset.get("asset") == "USDT":
                    return float(asset.get("free", 0))
    except Exception as e:
        print(f"  ⚠️  Tokocrypto balance error: {e}")
    return 0.0

# ══════════════════════════════════════════════
# HYPERLIQUID DEX CONNECTOR
# ══════════════════════════════════════════════

HL_BASE = "https://api.hyperliquid.xyz"

def hl_get_price(coin="BTC"):
    """
    Ambil harga dari Hyperliquid DEX perpetual.
    """
    try:
        data = _hl_safe_post({"type": "allMids"})
        if data is None:
            return None
        if isinstance(data, dict) and coin in data:
            harga = float(data[coin])
            return {
                "exchange" : "hyperliquid",
                "coin"     : coin,
                "harga_usd": harga,
                "tipe"     : "perp_dex"
            }
    except Exception as e:
        print(f"  ⚠️  Hyperliquid price {coin} error: {e}")
    return None

def hl_get_funding_rate(coin="BTC"):
    """
    Ambil funding rate dari Hyperliquid.
    Funding rate DEX = indikator sentimen futures on-chain.
    """
    try:
        data = _hl_safe_post({"type": "metaAndAssetCtxs"})
        if data is None:
            return None

        if isinstance(data, list) and len(data) >= 2:
            meta      = data[0]
            asset_ctx = data[1]
            universe  = meta.get("universe", [])

            for i, asset in enumerate(universe):
                if asset.get("name") == coin and i < len(asset_ctx):
                    ctx = asset_ctx[i]
                    return {
                        "coin"         : coin,
                        "funding_rate" : float(ctx.get("funding", 0)),
                        "open_interest": float(ctx.get("openInterest", 0)),
                        "mark_price"   : float(ctx.get("markPx", 0)),
                        "premium"      : float(ctx.get("premium", 0))
                    }
    except Exception as e:
        print(f"  ⚠️  Hyperliquid funding {coin} error: {e}")
    return None

def hl_get_orderbook(coin="BTC"):
    """Ambil order book dari Hyperliquid"""
    try:
        data = _hl_safe_post({"type": "l2Book", "coin": coin})
        if data is None:
            return None
        levels = data.get("levels", [[], []])
        bids   = [[float(b["px"]), float(b["sz"])] for b in levels[0][:10]]
        asks   = [[float(a["px"]), float(a["sz"])] for a in levels[1][:10]]
        return {
            "exchange": "hyperliquid",
            "coin"    : coin,
            "bids"    : bids,
            "asks"    : asks
        }
    except Exception as e:
        print(f"  ⚠️  Hyperliquid OB {coin} error: {e}")
    return None

def hl_place_order(coin, is_buy, sz, limit_px=None, order_type="market"):
    """
    Eksekusi order di Hyperliquid DEX.
    Butuh wallet address dan private key.
    """
    if not HL_WALLET or not HL_SECRET:
        return {"error": "Hyperliquid wallet/secret tidak tersedia"}
    try:
        # Hyperliquid pakai EIP-712 signing
        # Untuk market order sederhana
        ts   = int(time.time() * 1000)
        body = {
            "action": {
                "type"  : "order",
                "orders": [{
                    "a"   : 0,           # Asset index
                    "b"   : is_buy,
                    "p"   : str(limit_px) if limit_px else "0",
                    "s"   : str(sz),
                    "r"   : False,       # reduce only
                    "t"   : {"limit": {"tif": "Ioc"}} if not limit_px
                             else {"limit": {"tif": "Gtc"}}
                }],
                "grouping": "na"
            },
            "nonce" : ts,
            "signature": {"r": "0x0", "s": "0x0", "v": 0}  # Placeholder
        }
        resp = requests.post(
            f"{HL_BASE}/exchange",
            json=body,
            headers={"Content-Type": "application/json"},
            timeout=15
        )
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

def _hl_safe_post(body, timeout=8):
    """
    Helper POST ke Hyperliquid dengan validasi response.
    Return parsed JSON atau None jika response kosong/bukan JSON.
    """
    try:
        resp = requests.post(
            f"{HL_BASE}/info",
            json=body,
            headers={"Content-Type": "application/json"},
            timeout=timeout
        )
        if resp.status_code != 200:
            return None
        text = resp.text.strip()
        if not text or text == "null":
            return None
        return resp.json()
    except (requests.exceptions.JSONDecodeError, ValueError):
        return None
    except Exception as e:
        raise e   # biarkan caller handle

def hl_get_balance():
    """Cek saldo USDC di Hyperliquid"""
    if not HL_WALLET:
        return 0.0
    try:
        data = _hl_safe_post({
            "type": "clearinghouseState",
            "user": HL_WALLET
        })
        if data is None:
            return 0.0
        margin = data.get("marginSummary", {})
        return float(margin.get("accountValue", 0))
    except Exception as e:
        print(f"  ⚠️  Hyperliquid balance error: {e}")
    return 0.0

def hl_get_positions():
    """Cek posisi futures di Hyperliquid"""
    if not HL_WALLET:
        return []
    try:
        data = _hl_safe_post({
            "type": "clearinghouseState",
            "user": HL_WALLET
        })
        if data is None:
            return []
        positions = []
        for pos in data.get("assetPositions", []):
            p = pos.get("position", {})
            if float(p.get("szi", 0)) != 0:
                positions.append({
                    "coin"       : p.get("coin", ""),
                    "size"       : float(p.get("szi", 0)),
                    "entry_price": float(p.get("entryPx", 0)),
                    "unrealized" : float(p.get("unrealizedPnl", 0)),
                    "leverage"   : p.get("leverage", {})
                })
        return positions
    except Exception as e:
        print(f"  ⚠️  Hyperliquid positions error: {e}")
    return []

# ══════════════════════════════════════════════
# PRICE AGGREGATOR
# ══════════════════════════════════════════════

def get_all_prices(binance_client, symbol):
    """Ambil harga dari semua exchange"""
    sym_map  = SYMBOL_MAP.get(symbol, {})
    hasil    = {}

    # Binance (selalu)
    try:
        ticker = binance_client.get_symbol_ticker(symbol=symbol)
        ob     = binance_client.get_order_book(symbol=symbol, limit=5)
        hasil["binance"] = {
            "exchange" : "binance",
            "harga_usd": float(ticker["price"]),
            "bid_usd"  : float(ob["bids"][0][0]),
            "ask_usd"  : float(ob["asks"][0][0]),
            "volume"   : 0
        }
    except: pass

    # Indodax
    indodax_pair = sym_map.get("indodax")
    if indodax_pair:
        d = indodax_get_price(indodax_pair)
        if d: hasil["indodax"] = d

    # Tokocrypto
    toko_sym = sym_map.get("toko")
    if toko_sym:
        d = toko_get_price(toko_sym)
        if d: hasil["tokocrypto"] = d

    # Hyperliquid
    hl_coin = sym_map.get("hl")
    if hl_coin:
        d = hl_get_price(hl_coin)
        if d: hasil["hyperliquid"] = d

    if not hasil:
        return None

    harga_list = [v["harga_usd"] for v in hasil.values() if v.get("harga_usd",0) > 0]
    if not harga_list:
        return None

    agregat = {
        "n_exchange"  : len(hasil),
        "harga_avg"   : sum(harga_list) / len(harga_list),
        "harga_max"   : max(harga_list),
        "harga_min"   : min(harga_list),
        "spread_pct"  : ((max(harga_list)-min(harga_list))/min(harga_list))*100,
        "exchanges"   : list(hasil.keys())
    }

    return {"per_exchange": hasil, "agregat": agregat}

# ══════════════════════════════════════════════
# CROSS ORDER BOOK ANALYSIS
# ══════════════════════════════════════════════

def cross_orderbook_analysis(binance_client, symbol):
    """Analisis order book dari semua exchange"""
    sym_map  = SYMBOL_MAP.get(symbol, {})
    semua_ob = []

    try:
        ob = binance_client.get_order_book(symbol=symbol, limit=20)
        semua_ob.append({
            "exchange": "binance",
            "bids": [[float(b[0]),float(b[1])] for b in ob["bids"]],
            "asks": [[float(a[0]),float(a[1])] for a in ob["asks"]]
        })
    except: pass

    hl_coin = sym_map.get("hl")
    if hl_coin:
        ob = hl_get_orderbook(hl_coin)
        if ob: semua_ob.append(ob)

    if not semua_ob:
        return _default_cross_ob()

    imbalances = []
    bull_count = bear_count = 0

    for ob in semua_ob:
        bid_vol = sum(p*q for p,q in ob["bids"][:10])
        ask_vol = sum(p*q for p,q in ob["asks"][:10])
        if ask_vol > 0:
            imb = bid_vol / ask_vol
            imbalances.append(imb)
            if imb >= 1.3: bull_count += 1
            elif imb <= 0.7: bear_count += 1

    avg_imb  = sum(imbalances)/len(imbalances) if imbalances else 1.0
    n_ex     = len(semua_ob)

    if bull_count == n_ex:
        sinyal    = "BULLISH_KONSENSUS"; skor_buy = 3; skor_sell = 0
    elif bull_count >= n_ex*0.6:
        sinyal    = "BULLISH_MAYORITAS"; skor_buy = 2; skor_sell = 0
    elif bear_count == n_ex:
        sinyal    = "BEARISH_KONSENSUS"; skor_buy = 0; skor_sell = 3
    elif bear_count >= n_ex*0.6:
        sinyal    = "BEARISH_MAYORITAS"; skor_buy = 0; skor_sell = 2
    else:
        sinyal    = "NETRAL_MIXED";      skor_buy = 0; skor_sell = 0

    return {
        "sinyal"       : sinyal,
        "skor_buy"     : skor_buy,
        "skor_sell"    : skor_sell,
        "avg_imbalance": round(avg_imb, 3),
        "bullish_count": bull_count,
        "bearish_count": bear_count,
        "n_exchange"   : n_ex,
        "detail"       : f"CrossOB:{sinyal} ({bull_count}B/{bear_count}S/{n_ex}ex)"
    }

# ══════════════════════════════════════════════
# ARBITRASE SCANNER
# ══════════════════════════════════════════════

def scan_arbitrase(binance_client, symbol):
    """Deteksi peluang arbitrase antar exchange"""
    all_prices = get_all_prices(binance_client, symbol)
    if not all_prices or all_prices["agregat"]["n_exchange"] < 2:
        return {"ada_peluang": False, "detail": "Data tidak cukup"}

    per_ex  = all_prices["per_exchange"]
    harga_valid = {k: v for k,v in per_ex.items()
                   if v.get("harga_usd",0) > 0}

    if len(harga_valid) < 2:
        return {"ada_peluang": False, "detail": "Harga tidak valid"}

    ex_beli  = min(harga_valid, key=lambda x: harga_valid[x]["harga_usd"])
    ex_jual  = max(harga_valid, key=lambda x: harga_valid[x]["harga_usd"])
    h_beli   = harga_valid[ex_beli]["harga_usd"]
    h_jual   = harga_valid[ex_jual]["harga_usd"]

    spread   = ((h_jual - h_beli) / h_beli) * 100
    fee      = 0.2 + 0.1   # Trading fee + transfer
    net      = spread - fee
    ada      = net > ARBI_THRESHOLD

    return {
        "ada_peluang"   : ada,
        "exchange_beli" : ex_beli,
        "exchange_jual" : ex_jual,
        "harga_beli"    : h_beli,
        "harga_jual"    : h_jual,
        "spread_pct"    : round(spread, 4),
        "net_profit_pct": round(net, 4),
        "semua_harga"   : {ex: d["harga_usd"] for ex,d in harga_valid.items()},
        "detail"        : (
            f"🔄 {ex_beli}→{ex_jual} "
            f"${h_beli:,.4f}→${h_jual:,.4f} "
            f"(Net: {net:+.3f}%)"
            if ada else f"Spread: {spread:.3f}% (belum profitable)"
        )
    }

# ══════════════════════════════════════════════
# ANALISIS MULTI EXCHANGE
# ══════════════════════════════════════════════

def analisis_multi_exchange(binance_client, symbol):
    """
    Analisis lengkap dari semua exchange.
    Dipanggil dari hitung_skor_koin().
    """
    detail   = []
    skor_buy = skor_sell = 0

    all_prices = get_all_prices(binance_client, symbol)
    cross_ob   = cross_orderbook_analysis(binance_client, symbol)

    if all_prices:
        agr = all_prices["agregat"]
        skor_buy  += cross_ob["skor_buy"]
        skor_sell += cross_ob["skor_sell"]

        if agr["n_exchange"] >= 3 and cross_ob["bullish_count"] >= 3:
            skor_buy += 1; detail.append(f"🌐{agr['n_exchange']}ex bullish!")
        if agr["spread_pct"] > 0.5:
            detail.append(f"⚡Spread:{agr['spread_pct']:.2f}%")
        detail.append(cross_ob["detail"])

    # Hyperliquid funding rate bonus signal
    sym_map = SYMBOL_MAP.get(symbol, {})
    hl_coin = sym_map.get("hl")
    if hl_coin:
        fr = hl_get_funding_rate(hl_coin)
        if fr:
            rate = fr["funding_rate"] * 100
            if rate < -0.03:
                skor_buy += 1; detail.append(f"💧HL Funding:{rate:.4f}%(bullish)")
            elif rate > 0.08:
                skor_sell += 1; detail.append(f"💧HL Funding:{rate:.4f}%(bearish)")

    arbi = scan_arbitrase(binance_client, symbol)
    if arbi["ada_peluang"]:
        detail.append(
            f"🔄Arbi:{arbi['exchange_beli']}→"
            f"{arbi['exchange_jual']} "
            f"({arbi['net_profit_pct']:+.2f}%)"
        )

    harga_str = ""
    if all_prices:
        harga_str = " | ".join([
            f"{ex[:4].upper()}:${d['harga_usd']:,.2f}"
            for ex,d in all_prices["per_exchange"].items()
            if d.get("harga_usd",0) > 0
        ])

    return {
        "skor_buy" : min(skor_buy, 5),
        "skor_sell": min(skor_sell, 5),
        "cross_ob" : cross_ob,
        "arbitrase": arbi,
        "all_prices": all_prices,
        "detail"   : detail,
        "summary"  : f"MultiEx:{cross_ob['sinyal']} | {harga_str}"
    }

# ══════════════════════════════════════════════
# CEK SALDO SEMUA EXCHANGE
# ══════════════════════════════════════════════

def cek_saldo_semua_exchange(binance_client):
    """Print saldo di semua exchange"""
    print("\n💰 Saldo Multi Exchange:")

    try:
        akun = binance_client.get_account()
        usdt = next((float(a["free"]) for a in akun["balances"]
                     if a["asset"] == "USDT"), 0)
        print(f"  Binance     : ${usdt:,.2f} USDT")
    except: pass

    # Indodax
    if INDODAX_KEY:
        bal = indodax_get_balance()
        print(f"  Indodax     : Rp{bal['idr']:,.0f} "
              f"(≈${bal['usd']:,.2f})")
    else:
        print("  Indodax     : (API key belum diisi)")

    # Tokocrypto
    if TOKO_KEY:
        bal = toko_get_balance()
        print(f"  Tokocrypto  : ${bal:,.2f} USDT")
    else:
        print("  Tokocrypto  : (API key belum diisi)")

    # Hyperliquid
    if HL_WALLET:
        bal = hl_get_balance()
        print(f"  Hyperliquid : ${bal:,.2f} USDC")
        pos = hl_get_positions()
        if pos:
            print(f"  HL Positions: {len(pos)} posisi aktif")
            for p in pos:
                em = "📈" if p["size"] > 0 else "📉"
                print(f"    {em} {p['coin']}: {p['size']} "
                      f"@ ${p['entry_price']:,.2f} "
                      f"PnL: ${p['unrealized']:,.2f}")
    else:
        print("  Hyperliquid : (Wallet address belum diisi)")

def _default_cross_ob():
    return {
        "sinyal": "NETRAL", "skor_buy": 0, "skor_sell": 0,
        "avg_imbalance": 1.0, "bullish_count": 0, "bearish_count": 0,
        "n_exchange": 0, "detail": "CrossOB: N/A"
    }