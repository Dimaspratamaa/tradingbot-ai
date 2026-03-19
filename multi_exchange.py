# ============================================
# MULTI EXCHANGE ENGINE v1.0
# Exchange: Binance + Bybit + OKX + Coinbase
# Fitur:
#   1. Price & Volume Aggregator
#   2. Cross Order Book Analysis  
#   3. Arbitrage Scanner
#   4. Smart Order Routing
# ============================================

import requests
import time
import hmac
import hashlib
import json
import os
from datetime import datetime

# ── API CREDENTIALS ───────────────────────────
BYBIT_KEY       = os.environ.get("BYBIT_API_KEY", "")
BYBIT_SECRET    = os.environ.get("BYBIT_API_SECRET", "")
OKX_KEY         = os.environ.get("OKX_API_KEY", "")
OKX_SECRET      = os.environ.get("OKX_API_SECRET", "")
OKX_PASSPHRASE  = os.environ.get("OKX_PASSPHRASE", "")
COINBASE_KEY    = os.environ.get("COINBASE_API_KEY", "")
COINBASE_SECRET = os.environ.get("COINBASE_API_SECRET", "")

# ── KONFIGURASI ───────────────────────────────
ARBI_THRESHOLD  = 0.3    # Selisih harga >0.3% = arbitrase opportunity
TRADE_MIN_USD   = 10.0   # Modal minimum per posisi per exchange
TRADE_MAX_USD   = 50.0   # Modal maksimum per posisi per exchange

# ── SYMBOL MAPPING ────────────────────────────
# Setiap exchange punya format symbol berbeda
SYMBOL_MAP = {
    "BTCUSDT" : {"bybit": "BTCUSDT", "okx": "BTC-USDT", "coinbase": "BTC-USDT"},
    "ETHUSDT" : {"bybit": "ETHUSDT", "okx": "ETH-USDT", "coinbase": "ETH-USDT"},
    "BNBUSDT" : {"bybit": "BNBUSDT", "okx": "BNB-USDT", "coinbase": None},
    "SOLUSDT" : {"bybit": "SOLUSDT", "okx": "SOL-USDT", "coinbase": "SOL-USDT"},
    "ADAUSDT" : {"bybit": "ADAUSDT", "okx": "ADA-USDT", "coinbase": "ADA-USDT"},
    "XRPUSDT" : {"bybit": "XRPUSDT", "okx": "XRP-USDT", "coinbase": "XRP-USD"},
    "DOGEUSDT": {"bybit": "DOGEUSDT","okx": "DOGE-USDT","coinbase": "DOGE-USDT"},
    "AVAXUSDT": {"bybit": "AVAXUSDT","okx": "AVAX-USDT","coinbase": "AVAX-USDT"},
    "DOTUSDT" : {"bybit": "DOTUSDT", "okx": "DOT-USDT", "coinbase": "DOT-USDT"},
    "LINKUSDT": {"bybit": "LINKUSDT","okx": "LINK-USDT","coinbase": "LINK-USDT"},
}

# ══════════════════════════════════════════════
# BYBIT CONNECTOR
# ══════════════════════════════════════════════

def _bybit_sign(params, secret):
    """Generate signature untuk Bybit API"""
    timestamp  = str(int(time.time() * 1000))
    recv_window = "5000"
    param_str  = timestamp + BYBIT_KEY + recv_window + params
    signature  = hmac.new(
        secret.encode("utf-8"),
        param_str.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()
    return timestamp, signature

def bybit_get_price(symbol):
    """Ambil harga terbaru dari Bybit"""
    try:
        url    = f"https://api.bybit.com/v5/market/tickers"
        params = {"category": "spot", "symbol": symbol}
        resp   = requests.get(url, params=params, timeout=5)
        data   = resp.json()
        if data["retCode"] == 0:
            ticker = data["result"]["list"][0]
            return {
                "exchange": "bybit",
                "symbol"  : symbol,
                "price"   : float(ticker["lastPrice"]),
                "volume"  : float(ticker["volume24h"]),
                "bid"     : float(ticker["bid1Price"]),
                "ask"     : float(ticker["ask1Price"]),
                "change"  : float(ticker["price24hPcnt"]) * 100
            }
    except Exception as e:
        print(f"  ⚠️  Bybit price error {symbol}: {e}")
    return None

def bybit_get_orderbook(symbol, limit=20):
    """Ambil order book dari Bybit"""
    try:
        url    = "https://api.bybit.com/v5/market/orderbook"
        params = {"category": "spot", "symbol": symbol, "limit": limit}
        resp   = requests.get(url, params=params, timeout=5)
        data   = resp.json()
        if data["retCode"] == 0:
            return {
                "exchange": "bybit",
                "bids"    : [[float(b[0]), float(b[1])] for b in data["result"]["b"]],
                "asks"    : [[float(a[0]), float(a[1])] for a in data["result"]["a"]]
            }
    except Exception as e:
        print(f"  ⚠️  Bybit OB error {symbol}: {e}")
    return None

def bybit_place_order(symbol, side, qty, order_type="Market"):
    """Eksekusi order di Bybit"""
    if not BYBIT_KEY or not BYBIT_SECRET:
        return {"error": "Bybit API key tidak tersedia"}
    try:
        url       = "https://api.bybit.com/v5/order/create"
        body      = json.dumps({
            "category"  : "spot",
            "symbol"    : symbol,
            "side"      : side.capitalize(),
            "orderType" : order_type,
            "qty"       : str(qty),
            "marketUnit": "quoteCoin"
        })
        timestamp, sig = _bybit_sign(body, BYBIT_SECRET)
        headers = {
            "X-BAPI-API-KEY"    : BYBIT_KEY,
            "X-BAPI-TIMESTAMP"  : timestamp,
            "X-BAPI-SIGN"       : sig,
            "X-BAPI-RECV-WINDOW": "5000",
            "Content-Type"      : "application/json"
        }
        resp = requests.post(url, headers=headers, data=body, timeout=10)
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

def bybit_get_balance():
    """Cek saldo USDT di Bybit"""
    if not BYBIT_KEY:
        return 0.0
    try:
        url    = "https://api.bybit.com/v5/account/wallet-balance"
        params = "accountType=UNIFIED"
        timestamp, sig = _bybit_sign(params, BYBIT_SECRET)
        headers = {
            "X-BAPI-API-KEY"    : BYBIT_KEY,
            "X-BAPI-TIMESTAMP"  : timestamp,
            "X-BAPI-SIGN"       : sig,
            "X-BAPI-RECV-WINDOW": "5000"
        }
        resp = requests.get(
            f"https://api.bybit.com/v5/account/wallet-balance?{params}",
            headers=headers, timeout=5
        )
        data = resp.json()
        if data["retCode"] == 0:
            for coin in data["result"]["list"][0]["coin"]:
                if coin["coin"] == "USDT":
                    return float(coin["availableToWithdraw"])
    except Exception as e:
        print(f"  ⚠️  Bybit balance error: {e}")
    return 0.0

# ══════════════════════════════════════════════
# OKX CONNECTOR
# ══════════════════════════════════════════════

def _okx_sign(timestamp, method, path, body=""):
    """Generate signature untuk OKX API"""
    msg = timestamp + method + path + body
    sig = hmac.new(
        OKX_SECRET.encode("utf-8"),
        msg.encode("utf-8"),
        hashlib.sha256
    ).digest()
    import base64
    return base64.b64encode(sig).decode()

def _okx_headers(method, path, body=""):
    timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
    sig = _okx_sign(timestamp, method, path, body)
    return {
        "OK-ACCESS-KEY"       : OKX_KEY,
        "OK-ACCESS-SIGN"      : sig,
        "OK-ACCESS-TIMESTAMP" : timestamp,
        "OK-ACCESS-PASSPHRASE": OKX_PASSPHRASE,
        "Content-Type"        : "application/json"
    }

def okx_get_price(symbol):
    """Ambil harga dari OKX"""
    try:
        url  = f"https://www.okx.com/api/v5/market/ticker"
        params = {"instId": symbol}
        resp = requests.get(url, params=params, timeout=5)
        data = resp.json()
        if data["code"] == "0" and data["data"]:
            d = data["data"][0]
            return {
                "exchange": "okx",
                "symbol"  : symbol,
                "price"   : float(d["last"]),
                "volume"  : float(d["vol24h"]),
                "bid"     : float(d["bidPx"]),
                "ask"     : float(d["askPx"]),
                "change"  : float(d["sodUtc8"]) if d.get("sodUtc8") else 0
            }
    except Exception as e:
        print(f"  ⚠️  OKX price error {symbol}: {e}")
    return None

def okx_get_orderbook(symbol, limit=20):
    """Ambil order book dari OKX"""
    try:
        url    = "https://www.okx.com/api/v5/market/books"
        params = {"instId": symbol, "sz": limit}
        resp   = requests.get(url, params=params, timeout=5)
        data   = resp.json()
        if data["code"] == "0" and data["data"]:
            ob = data["data"][0]
            return {
                "exchange": "okx",
                "bids"    : [[float(b[0]), float(b[1])] for b in ob["bids"]],
                "asks"    : [[float(a[0]), float(a[1])] for a in ob["asks"]]
            }
    except Exception as e:
        print(f"  ⚠️  OKX OB error {symbol}: {e}")
    return None

def okx_place_order(symbol, side, qty_usdt):
    """Eksekusi order di OKX"""
    if not OKX_KEY:
        return {"error": "OKX API key tidak tersedia"}
    try:
        path = "/api/v5/trade/order"
        body = json.dumps({
            "instId" : symbol,
            "tdMode" : "cash",
            "side"   : side.lower(),
            "ordType": "market",
            "sz"     : str(qty_usdt),
            "tgtCcy" : "quote_ccy"
        })
        headers = _okx_headers("POST", path, body)
        resp    = requests.post(
            f"https://www.okx.com{path}",
            headers=headers, data=body, timeout=10
        )
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

def okx_get_balance():
    """Cek saldo USDT di OKX"""
    if not OKX_KEY:
        return 0.0
    try:
        path    = "/api/v5/account/balance?ccy=USDT"
        headers = _okx_headers("GET", path)
        resp    = requests.get(
            f"https://www.okx.com{path}",
            headers=headers, timeout=5
        )
        data = resp.json()
        if data["code"] == "0" and data["data"]:
            for detail in data["data"][0]["details"]:
                if detail["ccy"] == "USDT":
                    return float(detail["availBal"])
    except Exception as e:
        print(f"  ⚠️  OKX balance error: {e}")
    return 0.0

# ══════════════════════════════════════════════
# COINBASE CONNECTOR
# ══════════════════════════════════════════════

def coinbase_get_price(symbol):
    """Ambil harga dari Coinbase (public API, no key needed)"""
    try:
        url  = f"https://api.coinbase.com/api/v3/brokerage/market/products/{symbol}"
        resp = requests.get(url, timeout=5)
        data = resp.json()
        if "price" in data:
            return {
                "exchange": "coinbase",
                "symbol"  : symbol,
                "price"   : float(data["price"]),
                "volume"  : float(data.get("volume_24h", 0)),
                "bid"     : float(data.get("best_bid", 0)),
                "ask"     : float(data.get("best_ask", 0)),
                "change"  : float(data.get("price_percentage_change_24h", 0))
            }
    except Exception as e:
        print(f"  ⚠️  Coinbase price error {symbol}: {e}")
    return None

def coinbase_get_orderbook(symbol, limit=20):
    """Ambil order book dari Coinbase"""
    try:
        url    = f"https://api.coinbase.com/api/v3/brokerage/market/product_book"
        params = {"product_id": symbol, "limit": limit}
        resp   = requests.get(url, params=params, timeout=5)
        data   = resp.json()
        if "pricebook" in data:
            pb = data["pricebook"]
            return {
                "exchange": "coinbase",
                "bids"    : [[float(b["price"]), float(b["size"])] for b in pb.get("bids", [])],
                "asks"    : [[float(a["price"]), float(a["size"])] for a in pb.get("asks", [])]
            }
    except Exception as e:
        print(f"  ⚠️  Coinbase OB error {symbol}: {e}")
    return None

def coinbase_place_order(symbol, side, qty_usdt):
    """Eksekusi order di Coinbase"""
    if not COINBASE_KEY:
        return {"error": "Coinbase API key tidak tersedia"}
    try:
        import uuid
        path = "/api/v3/brokerage/orders"
        body = json.dumps({
            "client_order_id": str(uuid.uuid4()),
            "product_id"     : symbol,
            "side"           : side.upper(),
            "order_configuration": {
                "market_market_ioc": {
                    "quote_size": str(qty_usdt)
                }
            }
        })
        # Coinbase JWT auth (simplified)
        timestamp = str(int(time.time()))
        msg       = f"{timestamp}POST{path}{body}"
        sig       = hmac.new(
            COINBASE_SECRET.encode(),
            msg.encode(), hashlib.sha256
        ).hexdigest()
        headers = {
            "CB-ACCESS-KEY"      : COINBASE_KEY,
            "CB-ACCESS-SIGN"     : sig,
            "CB-ACCESS-TIMESTAMP": timestamp,
            "Content-Type"       : "application/json"
        }
        resp = requests.post(
            f"https://api.coinbase.com{path}",
            headers=headers, data=body, timeout=10
        )
        return resp.json()
    except Exception as e:
        return {"error": str(e)}

def coinbase_get_balance():
    """Cek saldo USD/USDT di Coinbase"""
    if not COINBASE_KEY:
        return 0.0
    try:
        timestamp = str(int(time.time()))
        path      = "/api/v3/brokerage/accounts"
        msg       = f"{timestamp}GET{path}"
        sig       = hmac.new(
            COINBASE_SECRET.encode(),
            msg.encode(), hashlib.sha256
        ).hexdigest()
        headers = {
            "CB-ACCESS-KEY"      : COINBASE_KEY,
            "CB-ACCESS-SIGN"     : sig,
            "CB-ACCESS-TIMESTAMP": timestamp
        }
        resp = requests.get(
            f"https://api.coinbase.com{path}",
            headers=headers, timeout=5
        )
        data = resp.json()
        for acc in data.get("accounts", []):
            if acc.get("currency") in ["USD", "USDT"]:
                return float(acc["available_balance"]["value"])
    except Exception as e:
        print(f"  ⚠️  Coinbase balance error: {e}")
    return 0.0

# ══════════════════════════════════════════════
# PRICE AGGREGATOR
# ══════════════════════════════════════════════

def get_all_prices(binance_client, symbol):
    """
    Ambil harga dari semua exchange sekaligus.
    Return: dict dengan harga per exchange + agregat
    """
    # Symbol mapping
    sym_map = SYMBOL_MAP.get(symbol, {})
    hasil   = {}

    # Binance
    try:
        ticker = binance_client.get_symbol_ticker(symbol=symbol)
        ob     = binance_client.get_order_book(symbol=symbol, limit=5)
        hasil["binance"] = {
            "exchange": "binance",
            "symbol"  : symbol,
            "price"   : float(ticker["price"]),
            "bid"     : float(ob["bids"][0][0]),
            "ask"     : float(ob["asks"][0][0]),
            "volume"  : 0,
            "change"  : 0
        }
    except Exception as e:
        print(f"  ⚠️  Binance price error: {e}")

    # Bybit
    bybit_sym = sym_map.get("bybit")
    if bybit_sym:
        data = bybit_get_price(bybit_sym)
        if data:
            hasil["bybit"] = data

    # OKX
    okx_sym = sym_map.get("okx")
    if okx_sym:
        data = okx_get_price(okx_sym)
        if data:
            hasil["okx"] = data

    # Coinbase
    cb_sym = sym_map.get("coinbase")
    if cb_sym:
        data = coinbase_get_price(cb_sym)
        if data:
            hasil["coinbase"] = data

    if not hasil:
        return None

    # ── Hitung agregat ──
    harga_list  = [v["price"] for v in hasil.values()]
    volume_list = [v.get("volume", 0) for v in hasil.values()]

    agregat = {
        "n_exchange"  : len(hasil),
        "harga_avg"   : sum(harga_list) / len(harga_list),
        "harga_max"   : max(harga_list),
        "harga_min"   : min(harga_list),
        "spread_pct"  : ((max(harga_list) - min(harga_list)) / min(harga_list)) * 100,
        "volume_total": sum(volume_list),
        "exchanges"   : list(hasil.keys())
    }

    return {"per_exchange": hasil, "agregat": agregat}

# ══════════════════════════════════════════════
# CROSS ORDER BOOK ANALYSIS
# ══════════════════════════════════════════════

def cross_orderbook_analysis(binance_client, symbol):
    """
    Analisis order book dari semua exchange.
    Cari tekanan beli/jual yang konsisten.
    """
    sym_map = SYMBOL_MAP.get(symbol, {})
    semua_ob = []

    # Binance OB
    try:
        ob = binance_client.get_order_book(symbol=symbol, limit=20)
        semua_ob.append({
            "exchange": "binance",
            "bids"    : [[float(b[0]), float(b[1])] for b in ob["bids"]],
            "asks"    : [[float(a[0]), float(a[1])] for a in ob["asks"]]
        })
    except: pass

    # Bybit OB
    if sym_map.get("bybit"):
        ob = bybit_get_orderbook(sym_map["bybit"])
        if ob: semua_ob.append(ob)

    # OKX OB
    if sym_map.get("okx"):
        ob = okx_get_orderbook(sym_map["okx"])
        if ob: semua_ob.append(ob)

    # Coinbase OB
    if sym_map.get("coinbase"):
        ob = coinbase_get_orderbook(sym_map["coinbase"])
        if ob: semua_ob.append(ob)

    if not semua_ob:
        return _default_cross_ob()

    # ── Analisis per exchange ──
    imbalances = []
    bullish_count = 0
    bearish_count = 0

    for ob in semua_ob:
        bid_vol = sum(p * q for p, q in ob["bids"][:10])
        ask_vol = sum(p * q for p, q in ob["asks"][:10])
        if ask_vol > 0:
            imb = bid_vol / ask_vol
            imbalances.append(imb)
            if imb >= 1.3:
                bullish_count += 1
            elif imb <= 0.7:
                bearish_count += 1

    avg_imbalance = sum(imbalances) / len(imbalances) if imbalances else 1.0
    n_exchange    = len(semua_ob)

    # ── Konsensus cross-exchange ──
    # Lebih kuat jika semua exchange sepakat
    if bullish_count == n_exchange:
        sinyal    = "BULLISH_KONSENSUS"
        skor_buy  = 3
        skor_sell = 0
    elif bullish_count >= n_exchange * 0.6:
        sinyal    = "BULLISH_MAYORITAS"
        skor_buy  = 2
        skor_sell = 0
    elif bearish_count == n_exchange:
        sinyal    = "BEARISH_KONSENSUS"
        skor_buy  = 0
        skor_sell = 3
    elif bearish_count >= n_exchange * 0.6:
        sinyal    = "BEARISH_MAYORITAS"
        skor_buy  = 0
        skor_sell = 2
    else:
        sinyal    = "NETRAL_MIXED"
        skor_buy  = 0
        skor_sell = 0

    return {
        "sinyal"        : sinyal,
        "skor_buy"      : skor_buy,
        "skor_sell"     : skor_sell,
        "avg_imbalance" : round(avg_imbalance, 3),
        "bullish_count" : bullish_count,
        "bearish_count" : bearish_count,
        "n_exchange"    : n_exchange,
        "detail"        : f"CrossOB:{sinyal} ({bullish_count}B/{bearish_count}S/{n_exchange}ex)"
    }

# ══════════════════════════════════════════════
# ARBITRAGE SCANNER
# ══════════════════════════════════════════════

def scan_arbitrase(binance_client, symbol):
    """
    Deteksi peluang arbitrase antar exchange.
    Arbitrase = beli di exchange murah, jual di exchange mahal.

    Return: dict dengan peluang arbitrase jika ada
    """
    all_prices = get_all_prices(binance_client, symbol)
    if not all_prices or all_prices["agregat"]["n_exchange"] < 2:
        return {"ada_peluang": False, "detail": "Data tidak cukup"}

    per_ex  = all_prices["per_exchange"]
    agregat = all_prices["agregat"]

    # Cari exchange dengan harga terendah (beli di sini)
    exchange_beli  = min(per_ex.keys(), key=lambda x: per_ex[x]["price"])
    exchange_jual  = max(per_ex.keys(), key=lambda x: per_ex[x]["price"])

    harga_beli     = per_ex[exchange_beli]["price"]
    harga_jual     = per_ex[exchange_jual]["price"]
    spread_pct     = ((harga_jual - harga_beli) / harga_beli) * 100

    # Estimasi fee (rata-rata 0.1% per exchange × 2 transaksi)
    total_fee_pct  = 0.2
    # Fee transfer antar exchange (~$1 = ~0.1%)
    transfer_fee   = 0.1
    net_profit_pct = spread_pct - total_fee_pct - transfer_fee

    ada_peluang = net_profit_pct > ARBI_THRESHOLD

    return {
        "ada_peluang"   : ada_peluang,
        "exchange_beli" : exchange_beli,
        "exchange_jual" : exchange_jual,
        "harga_beli"    : harga_beli,
        "harga_jual"    : harga_jual,
        "spread_pct"    : round(spread_pct, 4),
        "net_profit_pct": round(net_profit_pct, 4),
        "semua_harga"   : {ex: d["price"] for ex, d in per_ex.items()},
        "detail"        : (
            f"🔄 Arbitrase: Beli di {exchange_beli} ${harga_beli:,.4f} → "
            f"Jual di {exchange_jual} ${harga_jual:,.4f} "
            f"(Net: {net_profit_pct:+.3f}%)"
            if ada_peluang else
            f"Spread: {spread_pct:.3f}% (belum profitable)"
        )
    }

# ══════════════════════════════════════════════
# SMART ORDER ROUTING
# ══════════════════════════════════════════════

def get_best_exchange_beli(binance_client, symbol, qty_usdt):
    """
    Tentukan exchange terbaik untuk BUY.
    Kriteria: harga terendah + cukup liquidity + API tersedia
    """
    all_prices = get_all_prices(binance_client, symbol)
    if not all_prices:
        return "binance"  # Default ke Binance

    per_ex     = all_prices["per_exchange"]
    kandidat   = []

    for exchange, data in per_ex.items():
        # Cek apakah API key tersedia untuk eksekusi
        api_tersedia = {
            "binance" : True,
            "bybit"   : bool(BYBIT_KEY),
            "okx"     : bool(OKX_KEY),
            "coinbase": bool(COINBASE_KEY)
        }.get(exchange, False)

        if api_tersedia:
            kandidat.append({
                "exchange": exchange,
                "price"   : data["price"],
                "spread"  : data["ask"] - data["bid"]
            })

    if not kandidat:
        return "binance"

    # Pilih yang harganya paling murah (untuk beli)
    terbaik = min(kandidat, key=lambda x: x["price"])
    return terbaik["exchange"]

def eksekusi_order_terbaik(binance_client, symbol, side,
                           qty_usdt, kirim_telegram):
    """
    Eksekusi order di exchange dengan harga terbaik.
    Untuk BUY: pilih exchange paling murah
    Untuk SELL: pilih exchange paling mahal
    """
    all_prices = get_all_prices(binance_client, symbol)
    if not all_prices:
        return {"exchange": "binance", "status": "fallback"}

    per_ex = all_prices["per_exchange"]

    if side.upper() == "BUY":
        exchange_terpilih = min(
            [ex for ex in per_ex if _cek_api(ex)],
            key=lambda x: per_ex[x]["price"],
            default="binance"
        )
        harga_ref = per_ex[exchange_terpilih]["price"]
    else:
        exchange_terpilih = max(
            [ex for ex in per_ex if _cek_api(ex)],
            key=lambda x: per_ex[x]["price"],
            default="binance"
        )
        harga_ref = per_ex[exchange_terpilih]["price"]

    # Bandingkan dengan Binance
    harga_binance = per_ex.get("binance", {}).get("price", harga_ref)
    keuntungan    = abs(harga_ref - harga_binance) / harga_binance * 100

    print(f"  🎯 Smart Route: {side} {symbol} di {exchange_terpilih} "
          f"${harga_ref:,.4f} (vs Binance ${harga_binance:,.4f}, "
          f"selisih {keuntungan:.3f}%)")

    # Eksekusi di exchange terpilih
    sym_map = SYMBOL_MAP.get(symbol, {})
    result  = None

    if exchange_terpilih == "bybit":
        bybit_sym = sym_map.get("bybit", symbol)
        result    = bybit_place_order(bybit_sym, side, qty_usdt)

    elif exchange_terpilih == "okx":
        okx_sym = sym_map.get("okx", symbol)
        result  = okx_place_order(okx_sym, side, qty_usdt)

    elif exchange_terpilih == "coinbase":
        cb_sym = sym_map.get("coinbase", symbol)
        result = coinbase_place_order(cb_sym, side, qty_usdt)

    else:  # Binance (default)
        result = {"exchange": "binance", "note": "handled by main bot"}

    if keuntungan > 0.1:
        kirim_telegram(
            f"🎯 <b>Smart Routing - {symbol}</b>\n"
            f"📊 Exchange terpilih: <b>{exchange_terpilih.upper()}</b>\n"
            f"💰 Harga: ${harga_ref:,.4f} vs Binance ${harga_binance:,.4f}\n"
            f"✅ Hemat: {keuntungan:.3f}%"
        )

    return {
        "exchange": exchange_terpilih,
        "harga"   : harga_ref,
        "result"  : result
    }

def _cek_api(exchange):
    """Cek apakah API key tersedia untuk exchange"""
    return {
        "binance" : True,
        "bybit"   : bool(BYBIT_KEY),
        "okx"     : bool(OKX_KEY),
        "coinbase": bool(COINBASE_KEY)
    }.get(exchange, False)

# ══════════════════════════════════════════════
# FUNGSI UTAMA: ANALISIS MULTI EXCHANGE
# ══════════════════════════════════════════════

def analisis_multi_exchange(binance_client, symbol):
    """
    Analisis lengkap dari semua exchange.
    Dipanggil dari bot utama saat scan koin.

    Return:
        skor_buy     : int (0-5)
        skor_sell    : int (0-5)
        arbitrase    : dict
        cross_ob     : dict
        all_prices   : dict
        summary      : str
        detail       : list[str]
    """
    detail = []

    # 1. Ambil harga semua exchange
    all_prices = get_all_prices(binance_client, symbol)

    if not all_prices:
        return _default_result()

    agr = all_prices["agregat"]

    # 2. Cross OB analysis
    cross_ob = cross_orderbook_analysis(binance_client, symbol)

    # 3. Arbitrase scan
    arbi = scan_arbitrase(binance_client, symbol)

    # ── Hitung skor ──
    skor_buy  = cross_ob["skor_buy"]
    skor_sell = cross_ob["skor_sell"]

    # Bonus jika banyak exchange konfirmasi
    if agr["n_exchange"] >= 3:
        if cross_ob["bullish_count"] >= 3:
            skor_buy += 1
            detail.append(f"🌐 {agr['n_exchange']} exchange bullish!")
        elif cross_ob["bearish_count"] >= 3:
            skor_sell += 1
            detail.append(f"🌐 {agr['n_exchange']} exchange bearish!")

    # Info spread harga antar exchange
    if agr["spread_pct"] > 0.5:
        detail.append(f"⚡ Spread tinggi: {agr['spread_pct']:.3f}%")
    else:
        detail.append(f"✅ Spread normal: {agr['spread_pct']:.3f}%")

    # Info arbitrase
    if arbi["ada_peluang"]:
        detail.append(
            f"🔄 Arbitrase: {arbi['exchange_beli']}→{arbi['exchange_jual']} "
            f"({arbi['net_profit_pct']:+.3f}%)"
        )

    detail.append(cross_ob["detail"])

    harga_str = " | ".join([
        f"{ex}: ${d['price']:,.2f}"
        for ex, d in all_prices["per_exchange"].items()
    ])

    return {
        "skor_buy"  : min(skor_buy, 5),
        "skor_sell" : min(skor_sell, 5),
        "cross_ob"  : cross_ob,
        "arbitrase" : arbi,
        "all_prices": all_prices,
        "detail"    : detail,
        "summary"   : f"MultiEx:{cross_ob['sinyal']} | {harga_str}"
    }

def cek_saldo_semua_exchange(binance_client):
    """Print saldo di semua exchange"""
    print("\n💰 Saldo Multi Exchange:")
    try:
        akun = binance_client.get_account()
        usdt = next((float(a["free"]) for a in akun["balances"]
                     if a["asset"] == "USDT"), 0)
        print(f"  Binance  : ${usdt:,.2f}")
    except: pass

    bybit_bal = bybit_get_balance()
    print(f"  Bybit    : ${bybit_bal:,.2f}" if bybit_bal > 0
          else "  Bybit    : (API key belum tersedia)")

    okx_bal = okx_get_balance()
    print(f"  OKX      : ${okx_bal:,.2f}" if okx_bal > 0
          else "  OKX      : (API key belum tersedia)")

    coinbase_bal = coinbase_get_balance()
    print(f"  Coinbase : ${coinbase_bal:,.2f}" if coinbase_bal > 0
          else "  Coinbase : (API key belum tersedia)")

def _default_cross_ob():
    return {
        "sinyal": "NETRAL", "skor_buy": 0, "skor_sell": 0,
        "avg_imbalance": 1.0, "bullish_count": 0, "bearish_count": 0,
        "n_exchange": 0, "detail": "CrossOB: data tidak tersedia"
    }

def _default_result():
    return {
        "skor_buy": 0, "skor_sell": 0,
        "cross_ob": _default_cross_ob(),
        "arbitrase": {"ada_peluang": False},
        "all_prices": None,
        "detail": ["⚠️ Multi-exchange data tidak tersedia"],
        "summary": "N/A"
    }
