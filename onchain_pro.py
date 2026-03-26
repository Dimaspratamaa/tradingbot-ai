# ============================================
# ON-CHAIN PRO ANALYZER v1.0
# Upgrade dari onchain.py dengan data Glassnode
#
# Glassnode Lite (GRATIS):
#   - Exchange netflow BTC/ETH
#   - Active addresses
#   - SOPR (Spent Output Profit Ratio)
#   - NUPL (Net Unrealized Profit/Loss)
#   - Exchange balance
#
# Daftar: https://glassnode.com
# API docs: https://docs.glassnode.com
# ============================================

import requests
import time
import os
from datetime import datetime, timedelta

# ── API KEY ───────────────────────────────────
GLASSNODE_KEY = os.environ.get("GLASSNODE_API_KEY", "")

# ── CACHE ─────────────────────────────────────
_onchain_cache = {"data": {}, "waktu": {}, "ttl": 1800}  # 30 menit

# ── ENDPOINT ──────────────────────────────────
GLASSNODE_BASE = "https://api.glassnode.com/v1/metrics"

# ══════════════════════════════════════════════
# 1. EXCHANGE NETFLOW (paling penting!)
# ══════════════════════════════════════════════

def get_exchange_netflow(asset="BTC"):
    """
    Net flow BTC/ETH ke/dari exchange.

    NEGATIF = lebih banyak yang keluar dari exchange
              = whale akumulasi = BULLISH 🟢

    POSITIF = lebih banyak yang masuk ke exchange
              = whale mau jual = BEARISH 🔴
    """
    if not GLASSNODE_KEY:
        return None
    try:
        url    = f"{GLASSNODE_BASE}/transactions/transfers_volume_exchanges_net"
        params = {
            "a"        : asset,
            "i"        : "24h",
            "api_key"  : GLASSNODE_KEY,
            "limit"    : 3,
            "timestamp_format": "humanized"
        }
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()

        if data and isinstance(data, list):
            latest = data[-1]
            nilai  = latest.get("v", 0)
            return {
                "asset"    : asset,
                "netflow"  : nilai,
                "arah"     : "OUTFLOW" if nilai < 0 else "INFLOW",
                "tanggal"  : latest.get("t", "")
            }
    except Exception as e:
        print(f"  ⚠️  Glassnode netflow {asset} error: {e}")
    return None

# ══════════════════════════════════════════════
# 2. SOPR — SPENT OUTPUT PROFIT RATIO
# ══════════════════════════════════════════════

def get_sopr(asset="BTC"):
    """
    SOPR > 1 = holder jual dengan profit (take profit)
    SOPR < 1 = holder jual dengan rugi (capitulation)
    SOPR = 1 = breakeven, sering jadi support/resistance
    """
    if not GLASSNODE_KEY:
        return None
    try:
        url    = f"{GLASSNODE_BASE}/indicators/sopr"
        params = {
            "a"      : asset,
            "i"      : "24h",
            "api_key": GLASSNODE_KEY,
            "limit"  : 3
        }
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()

        if data and isinstance(data, list):
            vals = [d.get("v", 1) for d in data if d.get("v")]
            if vals:
                return {
                    "asset"    : asset,
                    "sopr"     : vals[-1],
                    "sopr_prev": vals[-2] if len(vals) > 1 else vals[-1],
                    "trend"    : "UP" if vals[-1] > (vals[-2] if len(vals) > 1 else vals[-1]) else "DOWN"
                }
    except Exception as e:
        print(f"  ⚠️  Glassnode SOPR error: {e}")
    return None

# ══════════════════════════════════════════════
# 3. NUPL — NET UNREALIZED PROFIT/LOSS
# ══════════════════════════════════════════════

def get_nupl(asset="BTC"):
    """
    NUPL mengukur sentiment holder:
    < 0         = Capitulation (semua rugi)
    0 - 0.25    = Hope/Fear
    0.25 - 0.5  = Optimism/Denial
    0.5 - 0.75  = Belief/Thrill (BULLISH)
    > 0.75      = Euphoria (WARNING - bisa bubble)
    """
    if not GLASSNODE_KEY:
        return None
    try:
        url    = f"{GLASSNODE_BASE}/indicators/nupl"
        params = {
            "a"      : asset,
            "i"      : "24h",
            "api_key": GLASSNODE_KEY,
            "limit"  : 2
        }
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()

        if data and isinstance(data, list):
            latest = data[-1].get("v", 0)
            fase   = _nupl_fase(latest)
            return {
                "asset": asset,
                "nupl" : latest,
                "fase" : fase
            }
    except Exception as e:
        print(f"  ⚠️  Glassnode NUPL error: {e}")
    return None

def _nupl_fase(nupl):
    if nupl < 0:     return "CAPITULATION"
    elif nupl < 0.25: return "HOPE_FEAR"
    elif nupl < 0.5:  return "OPTIMISM"
    elif nupl < 0.75: return "BELIEF_THRILL"
    else:             return "EUPHORIA"

# ══════════════════════════════════════════════
# 4. ACTIVE ADDRESSES
# ══════════════════════════════════════════════

def get_active_addresses(asset="BTC"):
    """
    Jumlah address aktif — proxy untuk adoption dan usage.
    Naik tajam = adoption naik = bullish
    """
    if not GLASSNODE_KEY:
        return None
    try:
        url    = f"{GLASSNODE_BASE}/addresses/active_count"
        params = {
            "a"      : asset,
            "i"      : "24h",
            "api_key": GLASSNODE_KEY,
            "limit"  : 7
        }
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()

        if data and isinstance(data, list):
            vals = [d.get("v", 0) for d in data if d.get("v")]
            if vals:
                current = vals[-1]
                avg_7d  = sum(vals) / len(vals)
                return {
                    "asset"      : asset,
                    "aktif"      : current,
                    "avg_7d"     : avg_7d,
                    "vs_avg"     : (current - avg_7d) / avg_7d * 100
                }
    except Exception as e:
        print(f"  ⚠️  Glassnode active addr error: {e}")
    return None

# ══════════════════════════════════════════════
# 5. EXCHANGE BALANCE
# ══════════════════════════════════════════════

def get_exchange_balance(asset="BTC"):
    """
    Total BTC di semua exchange.
    Menurun = whale tarik dari exchange = long-term hold = bullish
    Meningkat = whale siap jual = bearish
    """
    if not GLASSNODE_KEY:
        return None
    try:
        url    = f"{GLASSNODE_BASE}/distribution/balance_exchanges"
        params = {
            "a"      : asset,
            "i"      : "24h",
            "api_key": GLASSNODE_KEY,
            "limit"  : 7
        }
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()

        if data and isinstance(data, list):
            vals = [d.get("v", 0) for d in data if d.get("v")]
            if len(vals) >= 2:
                current  = vals[-1]
                prev_7d  = vals[0]
                chg_7d   = ((current - prev_7d) / prev_7d) * 100
                return {
                    "asset"  : asset,
                    "balance": current,
                    "chg_7d" : chg_7d,
                    "trend"  : "NAIK" if chg_7d > 0 else "TURUN"
                }
    except Exception as e:
        print(f"  ⚠️  Glassnode exchange balance error: {e}")
    return None

# ══════════════════════════════════════════════
# ANALISIS SINYAL ON-CHAIN
# ══════════════════════════════════════════════

def analisis_onchain_pro(asset="BTC"):
    """
    Gabungkan semua metrik on-chain jadi sinyal.
    """
    skor_buy  = 0
    skor_sell = 0
    detail    = []

    # ── Exchange Netflow ──
    netflow = get_exchange_netflow(asset)
    if netflow:
        nf = netflow["netflow"]
        if nf < -5000:     # Outflow besar (dalam BTC)
            skor_buy += 3
            detail.append(f"🟢 Exchange outflow besar: {nf:,.0f} BTC (akumulasi whale)")
        elif nf < -1000:
            skor_buy += 2
            detail.append(f"🟢 Exchange outflow: {nf:,.0f} BTC")
        elif nf < 0:
            skor_buy += 1
            detail.append(f"🟢 Netflow keluar: {nf:,.0f} BTC")
        elif nf > 5000:    # Inflow besar = sell pressure
            skor_sell += 3
            detail.append(f"🔴 Exchange inflow besar: {nf:,.0f} BTC (sell pressure)")
        elif nf > 1000:
            skor_sell += 2
            detail.append(f"🔴 Exchange inflow: {nf:,.0f} BTC")
        elif nf > 0:
            skor_sell += 1
            detail.append(f"🔴 Netflow masuk: {nf:,.0f} BTC")

    # ── SOPR ──
    sopr = get_sopr(asset)
    if sopr:
        s = sopr["sopr"]
        if s < 0.95:       # Capitulation = bottom signal
            skor_buy += 2
            detail.append(f"🟢 SOPR rendah: {s:.3f} (capitulation, beli opportunity)")
        elif s > 1.10:     # Profit taking besar
            skor_sell += 1
            detail.append(f"🟡 SOPR tinggi: {s:.3f} (profit taking)")
        else:
            detail.append(f"⚪ SOPR: {s:.3f} (normal)")

    # ── NUPL ──
    nupl = get_nupl(asset)
    if nupl:
        n    = nupl["nupl"]
        fase = nupl["fase"]
        if fase == "CAPITULATION":
            skor_buy += 3
            detail.append(f"🟢 NUPL Capitulation: {n:.2f} (bottom zone!)")
        elif fase == "BELIEF_THRILL":
            skor_buy += 1
            detail.append(f"🟢 NUPL Belief: {n:.2f}")
        elif fase == "EUPHORIA":
            skor_sell += 2
            detail.append(f"🔴 NUPL Euphoria: {n:.2f} (bubble warning!)")
        else:
            detail.append(f"⚪ NUPL {fase}: {n:.2f}")

    # ── Exchange Balance ──
    balance = get_exchange_balance(asset)
    if balance:
        chg = balance["chg_7d"]
        if chg < -3:       # Balance turun = whale tarik
            skor_buy += 2
            detail.append(f"🟢 Exchange balance turun {chg:.1f}% (7d) — whale akumulasi")
        elif chg > 3:      # Balance naik = whale deposit
            skor_sell += 2
            detail.append(f"🔴 Exchange balance naik {chg:.1f}% (7d) — whale siap jual")

    # ── Active Addresses ──
    addr = get_active_addresses(asset)
    if addr:
        vs_avg = addr["vs_avg"]
        if vs_avg > 20:
            skor_buy += 1
            detail.append(f"🟢 Active addresses +{vs_avg:.0f}% vs 7d avg")
        elif vs_avg < -20:
            skor_sell += 1
            detail.append(f"🔴 Active addresses {vs_avg:.0f}% vs 7d avg")

    if not detail:
        detail.append("⚪ On-chain data tidak tersedia (isi GLASSNODE_API_KEY)")

    net = skor_buy - skor_sell
    if net >= 3:     sentimen = "ONCHAIN_BULLISH_KUAT"
    elif net >= 1:   sentimen = "ONCHAIN_BULLISH"
    elif net <= -3:  sentimen = "ONCHAIN_BEARISH_KUAT"
    elif net <= -1:  sentimen = "ONCHAIN_BEARISH"
    else:            sentimen = "ONCHAIN_NETRAL"

    return {
        "skor_buy"  : min(skor_buy, 4),
        "skor_sell" : min(skor_sell, 4),
        "sentimen"  : sentimen,
        "detail"    : detail,
        "netflow"   : netflow,
        "sopr"      : sopr,
        "nupl"      : nupl,
        "summary"   : f"OnChain:{sentimen}"
    }

# ── FUNGSI UTAMA ─────────────────────────────
def get_onchain_pro_score(symbol_usdt="BTCUSDT"):
    """Entry point — dipanggil dari hitung_skor_koin()"""
    global _onchain_cache
    sekarang = time.time()

    # Hanya support BTC dan ETH untuk on-chain
    asset = "BTC" if "BTC" in symbol_usdt else (
            "ETH" if "ETH" in symbol_usdt else "BTC")

    cache_key = asset
    if (cache_key in _onchain_cache["data"] and
            sekarang - _onchain_cache["waktu"].get(cache_key, 0) < _onchain_cache["ttl"]):
        return _onchain_cache["data"][cache_key]

    print(f"  🔗 Menganalisis on-chain {asset} (Glassnode)...")
    hasil = analisis_onchain_pro(asset)

    _onchain_cache["data"][cache_key]  = hasil
    _onchain_cache["waktu"][cache_key] = sekarang
    return hasil