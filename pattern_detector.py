# ============================================
# STATISTICAL PATTERN DETECTOR v1.0
# Phase 2 dari Quant Trading Roadmap
#
# Terinspirasi Renaissance Technologies:
# "Harga pasar tidak acak sepenuhnya —
#  ada pola kecil yang bisa dieksploitasi"
#
# Modul ini mencari pola TERSEMBUNYI yang
# tidak terlihat oleh trader biasa:
#
#   1. Hurst Exponent       — trending vs mean-reverting
#   2. Fourier / FFT        — siklus periodik tersembunyi
#   3. Autocorrelation      — apakah return bisa diprediksi
#   4. Cointegration        — pairs trading opportunities
#   5. Hidden Markov Model  — regime tersembunyi
#   6. Mean Reversion Test  — seberapa kuat pull ke mean
#   7. Fractal Analysis     — self-similarity patterns
# ============================================

import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

# ══════════════════════════════════════════════
# 1. HURST EXPONENT — Trending vs Mean-Reverting
# ══════════════════════════════════════════════

def hitung_hurst(series, max_lag=20):
    """
    Hurst Exponent via Variance Ratio Method.
    Lebih akurat dari R/S untuk financial returns.

    Interpretasi:
      H < 0.45 → Mean-reverting (harga cenderung balik ke mean)
      H = 0.5  → Random walk (tidak bisa diprediksi)
      H > 0.55 → Trending (momentum berlanjut)

    Renaissance menggunakan ini untuk memilih strategi:
    - H < 0.45: pakai mean-reversion strategy
    - H > 0.55: pakai momentum/trend-following
    """
    s = np.array(series, dtype=float)
    n = len(s)
    if n < 32:
        return 0.5, "RANDOM"

    var1 = np.var(s, ddof=1)
    if var1 < 1e-12:
        return 0.5, "RANDOM"

    hrs = []
    for q in [2, 4, 8, 16]:
        if q * 4 > n:
            break
        # q-period aggregated returns
        ret_q = np.array([s[i:i+q].sum() for i in range(n - q + 1)])
        var_q = np.var(ret_q, ddof=1)
        if var_q > 0 and q > 1:
            vr  = var_q / (q * var1)
            H_q = np.log(max(vr, 1e-10)) / (2 * np.log(q)) + 0.5
            hrs.append(float(np.clip(H_q, 0.01, 0.99)))

    if not hrs:
        return 0.5, "RANDOM"

    H = float(np.mean(hrs))

    if H > 0.55:
        regime = "TRENDING"
    elif H < 0.45:
        regime = "MEAN_REVERTING"
    else:
        regime = "RANDOM"

    return round(H, 4), regime


def analisis_hurst_multi(close, windows=[50, 100, 200]):
    """
    Hitung Hurst di beberapa window untuk konfirmasi.
    Jika semua window agree → sinyal lebih kuat.
    """
    hasil = {}
    for w in windows:
        if len(close) >= w:
            data = close.tail(w).pct_change().dropna().values
            H, regime = hitung_hurst(data)
            hasil[f"hurst_{w}"] = {"H": H, "regime": regime}

    # Konsensus regime
    regimes = [v["regime"] for v in hasil.values()]
    if regimes.count("TRENDING") >= len(regimes) // 2 + 1:
        konsensus = "TRENDING"
    elif regimes.count("MEAN_REVERTING") >= len(regimes) // 2 + 1:
        konsensus = "MEAN_REVERTING"
    else:
        konsensus = "MIXED"

    hasil["konsensus"] = konsensus
    return hasil


# ══════════════════════════════════════════════
# 2. FOURIER TRANSFORM — Siklus Tersembunyi
# ══════════════════════════════════════════════

def deteksi_siklus_fft(close, top_n=5):
    """
    Fast Fourier Transform untuk menemukan siklus periodik.

    Renaissance menemukan bahwa banyak aset punya pola
    berulang yang tidak terlihat di chart biasa:
    misalnya siklus 7 hari, 14 hari, 30 hari, dll.

    Return:
        siklus_dominan : list of (periode_candle, kekuatan)
        prediksi_arah  : "UP", "DOWN", atau "NETRAL"
    """
    if len(close) < 64:
        return [], "NETRAL"

    # Detrend dulu — hilangkan trend linear agar FFT bersih
    n     = len(close)
    x     = np.arange(n)
    trend = np.polyfit(x, close.values, 1)
    detrended = close.values - np.polyval(trend, x)

    # Apply Hanning window untuk kurangi spectral leakage
    window    = np.hanning(n)
    windowed  = detrended * window

    # FFT
    fft_vals  = np.fft.rfft(windowed)
    fft_freq  = np.fft.rfftfreq(n)
    amplitudes = np.abs(fft_vals)

    # Ambil top N frekuensi terkuat (kecualikan DC component / freq=0)
    freq_nonzero  = fft_freq[1:]
    amp_nonzero   = amplitudes[1:]
    top_idx       = np.argsort(amp_nonzero)[::-1][:top_n]

    siklus_dominan = []
    for idx in top_idx:
        freq   = freq_nonzero[idx]
        periode = round(1 / freq) if freq > 0 else 0
        kekuatan = amp_nonzero[idx]
        if 2 <= periode <= n // 2:  # filter periode yang masuk akal
            siklus_dominan.append({
                "periode_candle": int(periode),
                "kekuatan"      : round(float(kekuatan), 2),
                "frekuensi"     : round(float(freq), 6)
            })

    # Prediksi arah berdasarkan fase siklus terkuat
    prediksi_arah = "NETRAL"
    if siklus_dominan:
        siklus_terkuat = siklus_dominan[0]["periode_candle"]
        if siklus_terkuat > 0:
            fase = n % siklus_terkuat
            # Jika di separuh pertama siklus → cenderung naik
            if fase < siklus_terkuat * 0.5:
                prediksi_arah = "UP"
            else:
                prediksi_arah = "DOWN"

    return siklus_dominan, prediksi_arah


# ══════════════════════════════════════════════
# 3. AUTOCORRELATION — Apakah Return Bisa Diprediksi?
# ══════════════════════════════════════════════

def analisis_autocorrelation(close, max_lag=20):
    """
    Uji apakah return historis bisa memprediksi return berikutnya.

    Jika autocorrelation lag-1 positif → momentum (beli setelah naik)
    Jika autocorrelation lag-1 negatif → mean-reversion (beli setelah turun)
    Jika mendekati 0 → random, tidak bisa diprediksi

    Renaissance mencari lag yang punya autocorrelation konsisten > 0.05
    """
    ret = close.pct_change().dropna()
    if len(ret) < max_lag + 10:
        return {}

    hasil     = {}
    signifikan = []

    for lag in range(1, max_lag + 1):
        ac = ret.autocorr(lag=lag)
        if np.isnan(ac):
            continue
        hasil[f"ac_lag_{lag}"] = round(ac, 4)

        # Cek signifikansi statistik (threshold sederhana: 2/sqrt(n))
        threshold = 2 / np.sqrt(len(ret))
        if abs(ac) > threshold:
            arah = "MOMENTUM" if ac > 0 else "REVERSAL"
            signifikan.append({"lag": lag, "ac": round(ac, 4), "arah": arah})

    # Lag mana yang paling signifikan?
    hasil["lag_signifikan"] = signifikan[:5]  # top 5
    hasil["punya_pola"]     = len(signifikan) > 0

    # Prediksi dari lag-1 (paling dekat)
    ac1 = hasil.get("ac_lag_1", 0)
    if ac1 > 0.05:
        hasil["sinyal_ac"] = "MOMENTUM"
    elif ac1 < -0.05:
        hasil["sinyal_ac"] = "MEAN_REVERSION"
    else:
        hasil["sinyal_ac"] = "NETRAL"

    return hasil


# ══════════════════════════════════════════════
# 4. MEAN REVERSION STRENGTH
# ══════════════════════════════════════════════

def ukur_mean_reversion(close, window=20):
    """
    Seberapa kuat harga ditarik kembali ke rata-rata?

    Ornstein-Uhlenbeck half-life:
    Makin kecil half-life → makin cepat revert → lebih cocok mean-reversion strategy

    Half-life < 5 candle  → sangat mean-reverting (scalp)
    Half-life 5-20 candle → sedang (swing)
    Half-life > 20 candle → lemah (trend-following lebih baik)
    """
    if len(close) < window + 10:
        return {}

    ret   = close.pct_change().dropna()
    lag1  = ret.shift(1).dropna()
    ret_a = ret.iloc[1:]

    if len(ret_a) < 10 or len(lag1) < 10:
        return {}

    # Regresi OLS sederhana: ret_t = alpha + beta * ret_{t-1}
    try:
        x = lag1.values[:len(ret_a)]
        y = ret_a.values
        beta  = np.cov(x, y)[0, 1] / (np.var(x) + 1e-10)
        alpha = np.mean(y) - beta * np.mean(x)

        # Half-life dari mean reversion
        if beta < 0:
            half_life = -np.log(2) / np.log(1 + beta)
            half_life = max(1, min(half_life, 1000))
        else:
            half_life = float('inf')

        # Z-score sekarang (berapa std dev dari mean?)
        mean_price = close.rolling(window).mean().iloc[-1]
        std_price  = close.rolling(window).std().iloc[-1]
        z_score    = (close.iloc[-1] - mean_price) / (std_price + 1e-10)

        # Sinyal mean reversion
        sinyal = "NETRAL"
        if half_life < 20 and abs(z_score) > 1.5:
            sinyal = "BELI" if z_score < -1.5 else "JUAL"

        return {
            "half_life" : round(float(half_life), 2),
            "z_score"   : round(float(z_score), 4),
            "beta_ou"   : round(float(beta), 4),
            "sinyal_mr" : sinyal,
            "kuat"      : half_life < 20
        }
    except Exception:
        return {}


# ══════════════════════════════════════════════
# 5. HIDDEN MARKOV MODEL — Deteksi Regime Tersembunyi
# ══════════════════════════════════════════════

def deteksi_regime_hmm(close, volume=None, n_states=3):
    """
    Simplified Hidden Markov Model untuk deteksi market regime.
    (Versi sederhana tanpa library hmmlearn — bisa jalan di Railway)

    3 regime tersembunyi:
      State 0: BULL  (return positif, volatilitas rendah)
      State 1: BEAR  (return negatif, volatilitas tinggi)
      State 2: CHOP  (return kecil, volatilitas sedang)

    Renaissance menggunakan HMM jauh lebih kompleks,
    tapi prinsipnya sama: deteksi "state" pasar saat ini.
    """
    if len(close) < 50:
        return {"regime": "UNKNOWN", "confidence": 0}

    ret    = close.pct_change().dropna()
    vol    = ret.rolling(10).std().dropna()

    if len(ret) < 20:
        return {"regime": "UNKNOWN", "confidence": 0}

    # Fitur untuk klasifikasi regime
    ret_recent  = ret.tail(10).mean()
    vol_recent  = vol.tail(5).mean()
    ret_hist    = ret.tail(50).mean()
    vol_hist    = vol.tail(50).mean() if len(vol) >= 50 else vol.mean()

    # Normalisasi
    ret_z  = (ret_recent - ret_hist) / (vol_hist + 1e-10)
    vol_ratio = vol_recent / (vol_hist + 1e-10)

    # Klasifikasi rule-based (approximasi HMM)
    if ret_z > 0.5 and vol_ratio < 1.2:
        regime     = "BULL"
        confidence = min(0.9, 0.5 + abs(ret_z) * 0.2)
        skor_buy   = 2
        skor_sell  = 0
    elif ret_z < -0.5 and vol_ratio > 1.0:
        regime     = "BEAR"
        confidence = min(0.9, 0.5 + abs(ret_z) * 0.2)
        skor_buy   = 0
        skor_sell  = 2
    elif vol_ratio > 1.5:
        regime     = "VOLATILE"
        confidence = min(0.8, 0.4 + vol_ratio * 0.15)
        skor_buy   = 0
        skor_sell  = 1
    else:
        regime     = "CHOP"
        confidence = 0.5
        skor_buy   = 0
        skor_sell  = 0

    # Volume confirmation
    if volume is not None and len(volume) >= 10:
        vol_price    = volume.tail(5).mean()
        vol_price_h  = volume.tail(20).mean()
        vol_confirm  = vol_price / (vol_price_h + 1e-10)

        if regime == "BULL" and vol_confirm > 1.2:
            confidence = min(0.95, confidence + 0.1)
        elif regime == "BEAR" and vol_confirm > 1.2:
            confidence = min(0.95, confidence + 0.1)

    return {
        "regime"    : regime,
        "confidence": round(confidence, 3),
        "ret_z"     : round(ret_z, 4),
        "vol_ratio" : round(vol_ratio, 4),
        "skor_buy"  : skor_buy,
        "skor_sell" : skor_sell,
    }


# ══════════════════════════════════════════════
# 6. COINTEGRATION — Pairs Trading Signal
# ══════════════════════════════════════════════

def cek_cointegration_sederhana(close_a, close_b, window=60):
    """
    Uji apakah 2 aset bergerak bersama (cointegrated).
    Jika ya → saat spread melebar bisa masuk posisi.

    Contoh pasangan yang sering cointegrated di crypto:
    - BTC vs ETH
    - SOL vs AVAX
    - BNB vs MATIC

    Return:
        spread_z     : z-score spread sekarang
        sinyal_pairs : "LONG_A_SHORT_B", "SHORT_A_LONG_B", "NETRAL"
    """
    if len(close_a) < window or len(close_b) < window:
        return {"sinyal_pairs": "NETRAL", "spread_z": 0}

    a = close_a.tail(window).values
    b = close_b.tail(window).values

    # Regresi linear: a = alpha + beta * b
    try:
        beta  = np.cov(a, b)[0, 1] / (np.var(b) + 1e-10)
        alpha = np.mean(a) - beta * np.mean(b)
        spread = a - (alpha + beta * b)

        # Z-score spread
        spread_mean = np.mean(spread)
        spread_std  = np.std(spread)
        z = (spread[-1] - spread_mean) / (spread_std + 1e-10)

        # Sinyal
        if z > 2.0:
            sinyal = "SHORT_A_LONG_B"   # A terlalu mahal relatif B
        elif z < -2.0:
            sinyal = "LONG_A_SHORT_B"   # A terlalu murah relatif B
        else:
            sinyal = "NETRAL"

        return {
            "spread_z"   : round(float(z), 4),
            "spread_now" : round(float(spread[-1]), 6),
            "spread_mean": round(float(spread_mean), 6),
            "beta"       : round(float(beta), 4),
            "sinyal_pairs": sinyal
        }
    except Exception:
        return {"sinyal_pairs": "NETRAL", "spread_z": 0}


# ══════════════════════════════════════════════
# FUNGSI UTAMA: ANALISIS PATTERN LENGKAP
# ══════════════════════════════════════════════

def analisis_pattern_quant(df_1h, df_ref=None, symbol=""):
    """
    Jalankan semua analisis statistik pada satu simbol.

    Args:
        df_1h  : DataFrame OHLCV 1H
        df_ref : DataFrame aset referensi untuk pairs (opsional)
        symbol : nama simbol untuk logging

    Returns:
        dict lengkap berisi semua hasil analisis + sinyal trading
    """
    if df_1h is None or len(df_1h) < 60:
        return {"error": "Data tidak cukup", "skor_buy": 0, "skor_sell": 0}

    close  = df_1h["close"].astype(float)
    volume = df_1h["volume"].astype(float) if "volume" in df_1h else None

    hasil      = {}
    skor_buy   = 0
    skor_sell  = 0
    detail     = []

    # ── 1. HURST EXPONENT ──
    hurst_data = analisis_hurst_multi(close)
    hasil["hurst"] = hurst_data
    konsensus  = hurst_data.get("konsensus", "MIXED")

    if konsensus == "TRENDING":
        skor_buy += 1
        detail.append(f"📈 Hurst: TRENDING")
    elif konsensus == "MEAN_REVERTING":
        detail.append(f"🔄 Hurst: MEAN_REVERTING")
        # Mean reversion — cek apakah harga oversold
        z50 = hurst_data.get("hurst_50", {}).get("H", 0.5)
        if z50 < 0.4:
            skor_buy += 1
            detail.append(f"🔄 Strong mean-reversion (H={z50:.2f})")

    # ── 2. FOURIER / SIKLUS ──
    siklus, prediksi_fft = deteksi_siklus_fft(close)
    hasil["fourier"] = {"siklus_dominan": siklus[:3], "prediksi": prediksi_fft}

    if siklus:
        top = siklus[0]
        detail.append(f"🌊 FFT: siklus {top['periode_candle']}H (kekuatan:{top['kekuatan']:.0f})")
        if prediksi_fft == "UP":
            skor_buy += 1
            detail.append(f"🌊 FFT prediksi: UP")
        elif prediksi_fft == "DOWN":
            skor_sell += 1

    # ── 3. AUTOCORRELATION ──
    ac_data = analisis_autocorrelation(close)
    hasil["autocorr"] = ac_data
    sinyal_ac = ac_data.get("sinyal_ac", "NETRAL")

    if sinyal_ac == "MOMENTUM":
        skor_buy += 1
        detail.append(f"🔁 Autocorr: MOMENTUM (ac1={ac_data.get('ac_lag_1',0):.3f})")
    elif sinyal_ac == "MEAN_REVERSION":
        detail.append(f"🔁 Autocorr: REVERSAL")

    # ── 4. MEAN REVERSION ──
    mr_data = ukur_mean_reversion(close)
    hasil["mean_reversion"] = mr_data
    sinyal_mr = mr_data.get("sinyal_mr", "NETRAL")

    if sinyal_mr == "BELI":
        skor_buy  += 2
        detail.append(f"📉 MR: OVERSOLD z={mr_data.get('z_score',0):.2f} (HL={mr_data.get('half_life',0):.0f}H)")
    elif sinyal_mr == "JUAL":
        skor_sell += 2
        detail.append(f"📈 MR: OVERBOUGHT z={mr_data.get('z_score',0):.2f}")

    # ── 5. HIDDEN MARKOV MODEL ──
    hmm_data = deteksi_regime_hmm(close, volume)
    hasil["hmm"] = hmm_data
    regime    = hmm_data.get("regime", "UNKNOWN")
    conf      = hmm_data.get("confidence", 0)

    skor_buy  += hmm_data.get("skor_buy", 0)
    skor_sell += hmm_data.get("skor_sell", 0)
    detail.append(f"🎯 HMM: {regime} ({conf:.0%})")

    # ── 6. PAIRS TRADING (jika ada referensi) ──
    if df_ref is not None and len(df_ref) >= 60:
        close_ref = df_ref["close"].astype(float)
        pairs_data = cek_cointegration_sederhana(close, close_ref)
        hasil["pairs"] = pairs_data
        sinyal_pairs = pairs_data.get("sinyal_pairs", "NETRAL")
        z_pairs      = pairs_data.get("spread_z", 0)
        if sinyal_pairs != "NETRAL":
            detail.append(f"🔗 Pairs: {sinyal_pairs} (z={z_pairs:.2f})")
            if "LONG_A" in sinyal_pairs:
                skor_buy += 1

    # ── SUMMARY ──
    hasil["skor_buy"]  = min(skor_buy, 5)
    hasil["skor_sell"] = min(skor_sell, 5)
    hasil["detail"]    = detail
    hasil["summary"]   = f"Quant: {konsensus} | {regime} | FFT:{prediksi_fft} | AC:{sinyal_ac}"

    return hasil


def print_quant_analysis(symbol, hasil):
    """Print hasil analisis quant ke terminal."""
    print(f"\n  📊 QUANT ANALYSIS — {symbol}")
    print(f"  {'─'*40}")
    hurst = hasil.get("hurst", {})
    print(f"  Hurst   : {hurst.get('konsensus','?')} "
          f"(H50={hurst.get('hurst_50',{}).get('H',0):.3f})")
    hmm = hasil.get("hmm", {})
    print(f"  Regime  : {hmm.get('regime','?')} "
          f"({hmm.get('confidence',0):.0%})")
    fft = hasil.get("fourier", {})
    print(f"  FFT     : prediksi {fft.get('prediksi','?')} "
          f"| {len(fft.get('siklus_dominan',[]))} siklus")
    mr = hasil.get("mean_reversion", {})
    print(f"  MeanRev : z={mr.get('z_score',0):.2f} "
          f"half-life={mr.get('half_life',0):.1f}H")
    print(f"  Signal  : Buy+{hasil.get('skor_buy',0)} "
          f"Sell+{hasil.get('skor_sell',0)}")
    for d in hasil.get("detail", []):
        print(f"    {d}")