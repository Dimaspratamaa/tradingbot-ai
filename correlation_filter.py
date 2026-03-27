# ============================================
# CORRELATION FILTER v1.0
# Hindari entry koin yang berkorelasi tinggi
#
# Masalah: Kalau sudah hold BTC dan ETH,
# jangan beli SOL (semua bergerak sama)
# = risiko portofolio terkonsentrasi
#
# Solusi: Hitung korelasi 24 jam dan block
# entry koin baru jika sudah ada posisi koin
# berkorelasi tinggi
# ============================================

import time
import numpy as np
import pandas as pd

# ── KONFIGURASI ───────────────────────────────
CORR_THRESHOLD    = 0.85   # Korelasi > 0.85 = terlalu mirip
CORR_LOOKBACK     = 24     # Gunakan 24 candle untuk hitung korelasi
_corr_cache       = {}     # Cache matriks korelasi
_corr_waktu       = 0
_corr_ttl         = 1800   # Cache 30 menit

# Grup koin yang biasanya berkorelasi tinggi
CORR_GROUPS = {
    "large_cap" : ["BTCUSDT", "ETHUSDT", "BNBUSDT"],
    "layer1"    : ["SOLUSDT", "AVAXUSDT", "NEARUSDT", "APTUSDT", "SUIUSDT"],
    "layer2"    : ["ARBUSDT", "OPUSDT", "MATICUSDT"],
    "defi"      : ["UNIUSDT", "AAVEUSDT"],
    "ai_crypto" : ["FETUSDT", "RENDERUSDT", "WLDUSDT"],
    "meme"      : ["PEPEUSDT", "SHIBUSDT", "WIFUSDT", "DOGEUSDT"],
}

# ══════════════════════════════════════════════
# HITUNG KORELASI
# ══════════════════════════════════════════════

def hitung_korelasi(client, symbol_a, symbol_b, limit=CORR_LOOKBACK):
    """
    Hitung korelasi return antara dua koin.
    Return: float -1 to 1 (1 = sempurna positif)
    """
    try:
        from binance.client import Client as BClient

        klines_a = client.get_klines(
            symbol=symbol_a,
            interval=BClient.KLINE_INTERVAL_1HOUR,
            limit=limit
        )
        klines_b = client.get_klines(
            symbol=symbol_b,
            interval=BClient.KLINE_INTERVAL_1HOUR,
            limit=limit
        )

        close_a = np.array([float(k[4]) for k in klines_a])
        close_b = np.array([float(k[4]) for k in klines_b])

        if len(close_a) < 10 or len(close_b) < 10:
            return 0.0

        # Return percentage
        ret_a = np.diff(close_a) / close_a[:-1]
        ret_b = np.diff(close_b) / close_b[:-1]

        # Pearson correlation
        corr = np.corrcoef(ret_a, ret_b)[0, 1]
        return round(float(corr), 3) if not np.isnan(corr) else 0.0

    except Exception as e:
        return 0.0

# ══════════════════════════════════════════════
# CEK KORELASI DENGAN POSISI AKTIF
# ══════════════════════════════════════════════

def cek_korelasi_dengan_posisi(client, symbol_baru, posisi_aktif):
    """
    Cek apakah symbol_baru berkorelasi tinggi
    dengan koin yang sudah di posisi.

    Return: (bool boleh_entry, str alasan)
    """
    if not posisi_aktif:
        return True, ""

    symbol_posisi = list(posisi_aktif.keys())

    for sym_aktif in symbol_posisi:
        # Cek grup korelasi dulu (cepat, tanpa API call)
        grup_baru   = _cari_grup(symbol_baru)
        grup_aktif  = _cari_grup(sym_aktif)

        if grup_baru and grup_baru == grup_aktif:
            return False, (
                f"❌ Korelasi grup: {symbol_baru} dan {sym_aktif} "
                f"di grup {grup_baru}"
            )

        # Hitung korelasi aktual (jika tidak ketemu dari grup)
        corr = _get_corr_cached(client, symbol_baru, sym_aktif)

        if corr > CORR_THRESHOLD:
            return False, (
                f"❌ Korelasi tinggi: {symbol_baru} vs {sym_aktif} "
                f"= {corr:.2f} (>{CORR_THRESHOLD})"
            )

    return True, f"✅ Korelasi OK dengan {len(symbol_posisi)} posisi aktif"

def _cari_grup(symbol):
    """Cari grup korelasi dari symbol"""
    for nama_grup, anggota in CORR_GROUPS.items():
        if symbol in anggota:
            return nama_grup
    return None

def _get_corr_cached(client, sym_a, sym_b):
    """Ambil korelasi dengan cache"""
    global _corr_cache, _corr_waktu
    sekarang = time.time()

    key = f"{min(sym_a,sym_b)}_{max(sym_a,sym_b)}"

    if (key in _corr_cache and
            sekarang - _corr_waktu < _corr_ttl):
        return _corr_cache[key]

    corr = hitung_korelasi(client, sym_a, sym_b)
    _corr_cache[key] = corr
    _corr_waktu = sekarang
    return corr

# ══════════════════════════════════════════════
# DIVERSIFIKASI PORTOFOLIO
# ══════════════════════════════════════════════

def filter_kandidat_diversifikasi(client, kandidat_list,
                                   posisi_aktif, max_posisi=3):
    """
    Filter daftar kandidat entry untuk memastikan diversifikasi.
    Pilih kombinasi koin dengan korelasi terendah.

    Return: list kandidat yang sudah difilter
    """
    if len(kandidat_list) <= 1:
        return kandidat_list

    terpilih = []
    for kandidat in kandidat_list:
        if len(terpilih) >= max_posisi:
            break

        symbol = kandidat["symbol"]

        # Cek korelasi dengan posisi aktif
        boleh, alasan = cek_korelasi_dengan_posisi(
            client, symbol, posisi_aktif
        )
        if not boleh:
            print(f"  🔄 [{symbol}] Skip: {alasan}")
            continue

        # Cek korelasi dengan kandidat yang sudah terpilih
        korelasi_ok = True
        for terpilih_sym in [k["symbol"] for k in terpilih]:
            corr = _get_corr_cached(client, symbol, terpilih_sym)
            if corr > CORR_THRESHOLD:
                print(f"  🔄 [{symbol}] Korelasi tinggi dgn {terpilih_sym}: {corr:.2f}")
                korelasi_ok = False
                break

        if korelasi_ok:
            terpilih.append(kandidat)

    return terpilih

def print_korelasi_matrix(client, symbols):
    """Print matriks korelasi untuk monitoring"""
    print("\n📊 Matriks Korelasi (24H):")
    for i, s1 in enumerate(symbols[:5]):
        for s2 in symbols[i+1:5]:
            corr = _get_corr_cached(client, s1, s2)
            em   = "🔴" if corr > 0.85 else ("🟡" if corr > 0.7 else "🟢")
            print(f"  {em} {s1.replace('USDT','')} vs "
                  f"{s2.replace('USDT','')}: {corr:.2f}")