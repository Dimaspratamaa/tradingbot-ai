# ============================================
# FEATURE ENGINEERING v1.0 — Quant Edition
# Terinspirasi Renaissance Technologies / Two Sigma
#
# 85+ fitur dalam 7 kategori:
#   1. Price Action & Momentum      (18 fitur)
#   2. Volatility & Risk            (12 fitur)
#   3. Volume & Market Microstructure (12 fitur)
#   4. Trend & Structure            (14 fitur)
#   5. Pattern Recognition          (10 fitur)
#   6. Statistical / Math           (11 fitur)
#   7. Multi-Timeframe Composite    (8 fitur)
#
# Output: dict fitur siap pakai untuk ML model
# ============================================

import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings('ignore')

# ══════════════════════════════════════════════
# KATEGORI 1: PRICE ACTION & MOMENTUM (18 fitur)
# ══════════════════════════════════════════════

def feat_momentum(close):
    """
    Return/momentum di berbagai window.
    Inti dari semua strategi quant — "trend is your friend".
    """
    f = {}
    for n in [1, 2, 3, 5, 7, 10, 14, 20, 30]:
        f[f"ret_{n}"] = close.pct_change(n).iloc[-1] * 100

    # Rate of Change (RoC)
    f["roc_5"]  = (close.iloc[-1] / close.iloc[-6]  - 1) * 100
    f["roc_10"] = (close.iloc[-1] / close.iloc[-11] - 1) * 100

    # Candle features
    return f

def feat_rsi_advanced(close, periods=[7, 14, 21]):
    """
    RSI multi-period + divergence + overbought/oversold score.
    RSI tunggal seringkali terlambat — kombinasi 3 periode lebih akurat.
    """
    f = {}
    for p in periods:
        delta = close.diff()
        gain  = delta.where(delta > 0, 0).rolling(p).mean()
        loss  = (-delta.where(delta < 0, 0)).rolling(p).mean()
        rs    = gain / loss.replace(0, np.nan)
        rsi   = (100 - 100 / (1 + rs))
        f[f"rsi_{p}"]       = rsi.iloc[-1]
        f[f"rsi_{p}_slope"] = rsi.iloc[-1] - rsi.iloc[-3]  # arah RSI

    # RSI divergence score: harga turun tapi RSI naik = bullish divergence
    rsi14 = 100 - 100 / (1 + close.diff().where(
        close.diff() > 0, 0).rolling(14).mean() /
        (-close.diff().where(close.diff() < 0, 0)).rolling(14).mean())
    price_5  = (close.iloc[-1] - close.iloc[-6]) / close.iloc[-6]
    rsi_5    = (rsi14.iloc[-1] - rsi14.iloc[-6]) / 100
    f["bull_div_score"] = float(price_5 < -0.01 and rsi_5 > 0.02)
    f["bear_div_score"] = float(price_5 > 0.01  and rsi_5 < -0.02)
    return f

def feat_macd_advanced(close):
    """
    MACD standar + histogram trend + crossover timing.
    """
    f = {}
    for fast, slow, sig in [(12, 26, 9), (5, 13, 5)]:
        ema_f  = close.ewm(span=fast, adjust=False).mean()
        ema_s  = close.ewm(span=slow, adjust=False).mean()
        macd   = ema_f - ema_s
        signal = macd.ewm(span=sig, adjust=False).mean()
        hist   = macd - signal
        tag    = f"macd_{fast}_{slow}"
        f[f"{tag}_val"]       = macd.iloc[-1]
        f[f"{tag}_hist"]      = hist.iloc[-1]
        f[f"{tag}_hist_prev"] = hist.iloc[-2]
        f[f"{tag}_slope"]     = hist.iloc[-1] - hist.iloc[-3]
        # Crossover: 1=bullish cross, -1=bearish cross, 0=none
        cross = 0
        if macd.iloc[-1] > signal.iloc[-1] and macd.iloc[-2] <= signal.iloc[-2]:
            cross = 1
        elif macd.iloc[-1] < signal.iloc[-1] and macd.iloc[-2] >= signal.iloc[-2]:
            cross = -1
        f[f"{tag}_cross"] = cross
    return f

# ══════════════════════════════════════════════
# KATEGORI 2: VOLATILITY & RISK (12 fitur)
# ══════════════════════════════════════════════

def feat_volatility(high, low, close):
    """
    Volatilitas multi-metode.
    Pasar volatil = ukuran posisi lebih kecil, SL lebih lebar.
    """
    f = {}

    # ATR multi-period
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low  - close.shift()).abs()
    ], axis=1).max(axis=1)

    for p in [7, 14, 21]:
        atr = tr.rolling(p).mean()
        f[f"atr_{p}"]     = atr.iloc[-1]
        f[f"atr_{p}_pct"] = (atr.iloc[-1] / close.iloc[-1]) * 100

    # ATR ratio: ATR sekarang vs rata2 — deteksi volatility spike
    f["atr_ratio"] = tr.rolling(7).mean().iloc[-1] / tr.rolling(21).mean().iloc[-1]

    # Historical Volatility (std log returns)
    log_ret = np.log(close / close.shift(1))
    f["hvol_10"]  = log_ret.rolling(10).std().iloc[-1]  * np.sqrt(24) * 100
    f["hvol_20"]  = log_ret.rolling(20).std().iloc[-1]  * np.sqrt(24) * 100

    # Chaikin Volatility: rate of change ATR
    atr14 = tr.rolling(14).mean()
    f["chaikin_vol"] = ((atr14.iloc[-1] - atr14.iloc[-10]) / atr14.iloc[-10]) * 100

    # Ulcer Index: ukur drawdown severity
    rolling_max = close.rolling(14).max()
    drawdown    = (close - rolling_max) / rolling_max * 100
    f["ulcer_index"] = np.sqrt((drawdown ** 2).rolling(14).mean().iloc[-1])

    return f

def feat_bollinger(close, high, low):
    """
    Bollinger Bands + Keltner Channel + Squeeze.
    Squeeze = low volatility → akan ada breakout besar.
    """
    f = {}

    # Bollinger Bands
    sma20  = close.rolling(20).mean()
    std20  = close.rolling(20).std()
    bb_up  = sma20 + 2 * std20
    bb_dn  = sma20 - 2 * std20
    f["bb_width"]    = ((bb_up - bb_dn) / sma20).iloc[-1]
    f["bb_pos"]      = ((close - bb_dn) / (bb_up - bb_dn)).iloc[-1]
    f["bb_pct_b"]    = f["bb_pos"]  # alias

    # Keltner Channel (ATR-based)
    tr      = pd.concat([high-low, (high-close.shift()).abs(),
                         (low-close.shift()).abs()], axis=1).max(axis=1)
    atr20   = tr.rolling(20).mean()
    ema20   = close.ewm(span=20, adjust=False).mean()
    kc_up   = ema20 + 1.5 * atr20
    kc_dn   = ema20 - 1.5 * atr20

    # Squeeze: BB dalam KC = volatilitas sangat rendah → potensi breakout
    squeeze = (bb_up < kc_up) & (bb_dn > kc_dn)
    f["bb_squeeze"]      = float(squeeze.iloc[-1])
    f["bb_squeeze_bars"] = float(squeeze.rolling(5).sum().iloc[-1])  # durasi squeeze
    return f

# ══════════════════════════════════════════════
# KATEGORI 3: VOLUME & MICROSTRUCTURE (12 fitur)
# ══════════════════════════════════════════════

def feat_volume(close, volume, high, low):
    """
    Analisis volume — jejak "smart money".
    Renaissance percaya volume mencerminkan informasi yang belum masuk ke harga.
    """
    f = {}

    vol_sma20 = volume.rolling(20).mean()
    vol_sma5  = volume.rolling(5).mean()

    f["vol_ratio_20"]  = (volume.iloc[-1] / vol_sma20.iloc[-1])
    f["vol_ratio_5"]   = (volume.iloc[-1] / vol_sma5.iloc[-1])
    f["vol_trend"]     = (vol_sma5.iloc[-1] / vol_sma20.iloc[-1])  # tren volume
    f["vol_spike"]     = float(f["vol_ratio_20"] > 2.0)

    # On-Balance Volume (OBV) — akumulasi/distribusi
    obv = (np.sign(close.diff()) * volume).fillna(0).cumsum()
    f["obv_slope"]   = (obv.iloc[-1] - obv.iloc[-5]) / (abs(obv.iloc[-5]) + 1)

    # Volume-Weighted Momentum: momentum dengan bobot volume
    ret1    = close.pct_change(1)
    vwm     = (ret1 * volume).rolling(10).sum() / volume.rolling(10).sum()
    f["vwm_10"] = vwm.iloc[-1] * 100

    # Money Flow Index (MFI) — RSI versi volume
    tp   = (high + low + close) / 3
    mf   = tp * volume
    pmf  = mf.where(tp > tp.shift(1), 0).rolling(14).sum()
    nmf  = mf.where(tp < tp.shift(1), 0).rolling(14).sum()
    mfi  = 100 - (100 / (1 + pmf / (nmf + 1e-10)))
    f["mfi_14"] = mfi.iloc[-1]

    # Accumulation/Distribution
    clv  = ((close - low) - (high - close)) / (high - low + 1e-10)
    adl  = (clv * volume).cumsum()
    f["adl_slope"] = (adl.iloc[-1] - adl.iloc[-5]) / (abs(adl.iloc[-5]) + 1)

    # Force Index: kekuatan pergerakan
    fi   = close.diff(1) * volume
    f["force_idx_2"]  = fi.ewm(span=2, adjust=False).mean().iloc[-1]
    f["force_idx_13"] = fi.ewm(span=13, adjust=False).mean().iloc[-1]

    return f

# ══════════════════════════════════════════════
# KATEGORI 4: TREND & STRUCTURE (14 fitur)
# ══════════════════════════════════════════════

def feat_trend(close, high, low):
    """
    Struktur trend multi-timeframe internal.
    Bukan hanya "apakah naik" tapi "seberapa kuat dan matang" trennya.
    """
    f = {}

    # EMA stack: bullish = EMA20 > EMA50 > EMA200
    ema20  = close.ewm(span=20,  adjust=False).mean()
    ema50  = close.ewm(span=50,  adjust=False).mean()
    ema100 = close.ewm(span=100, adjust=False).mean()
    ema200 = close.ewm(span=200, adjust=False).mean()

    f["ema20"]       = ema20.iloc[-1]
    f["ema50"]       = ema50.iloc[-1]
    f["ema_20_50"]   = (ema20.iloc[-1] / ema50.iloc[-1] - 1) * 100
    f["ema_50_200"]  = (ema50.iloc[-1] / ema200.iloc[-1] - 1) * 100
    f["price_ema20"] = (close.iloc[-1] / ema20.iloc[-1] - 1) * 100
    f["price_ema50"] = (close.iloc[-1] / ema50.iloc[-1] - 1) * 100

    # EMA stack score: 1 jika bullish alignment sempurna
    f["ema_stack_bull"] = float(
        close.iloc[-1] > ema20.iloc[-1] > ema50.iloc[-1] > ema100.iloc[-1]
    )
    f["ema_stack_bear"] = float(
        close.iloc[-1] < ema20.iloc[-1] < ema50.iloc[-1] < ema100.iloc[-1]
    )

    # ADX — kekuatan trend (bukan arah)
    plus_dm  = (high.diff()).where(
        (high.diff() > 0) & (high.diff() > -low.diff()), 0)
    minus_dm = (-low.diff()).where(
        (-low.diff() > 0) & (-low.diff() > high.diff()), 0)
    tr       = pd.concat([high-low, (high-close.shift()).abs(),
                          (low-close.shift()).abs()], axis=1).max(axis=1)
    atr14    = tr.ewm(span=14, adjust=False).mean()
    pdi      = 100 * plus_dm.ewm(span=14, adjust=False).mean() / (atr14 + 1e-10)
    mdi      = 100 * minus_dm.ewm(span=14, adjust=False).mean() / (atr14 + 1e-10)
    dx       = 100 * (pdi - mdi).abs() / (pdi + mdi + 1e-10)
    adx      = dx.ewm(span=14, adjust=False).mean()
    f["adx"]     = adx.iloc[-1]
    f["pdi"]     = pdi.iloc[-1]
    f["mdi"]     = mdi.iloc[-1]
    f["adx_bull"]= float(adx.iloc[-1] > 25 and pdi.iloc[-1] > mdi.iloc[-1])

    # Parabolic SAR (simplified)
    f["sar_bull"] = float(close.iloc[-1] > close.rolling(20).min().iloc[-1] * 1.02)

    # Ichimoku (cloud position)
    tenkan = (high.rolling(9).max() + low.rolling(9).min()) / 2
    kijun  = (high.rolling(26).max() + low.rolling(26).min()) / 2
    span_a = ((tenkan + kijun) / 2).shift(26)
    span_b = ((high.rolling(52).max() + low.rolling(52).min()) / 2).shift(26)
    kumo_top    = pd.concat([span_a, span_b], axis=1).max(axis=1)
    kumo_bottom = pd.concat([span_a, span_b], axis=1).min(axis=1)
    f["ichi_above_cloud"] = float(close.iloc[-1] > kumo_top.iloc[-1])
    f["ichi_tk_cross"]    = float(tenkan.iloc[-1] > kijun.iloc[-1] and
                                   tenkan.iloc[-2] <= kijun.iloc[-2])

    return f

# ══════════════════════════════════════════════
# KATEGORI 5: PATTERN RECOGNITION (10 fitur)
# ══════════════════════════════════════════════

def feat_candle_patterns(open_, high, low, close):
    """
    Pola candlestick yang sudah terbukti secara statistik.
    Bukan semua pola valid — hanya yang memiliki edge positif.
    """
    f = {}
    o  = open_.values
    h  = high.values
    l  = low.values
    c  = close.values

    def body(i):   return abs(c[i] - o[i])
    def shadow_up(i):  return h[i] - max(c[i], o[i])
    def shadow_dn(i):  return min(c[i], o[i]) - l[i]
    def candle_range(i): return h[i] - l[i] + 1e-10

    n = len(c) - 1  # candle terakhir

    # Doji: body kecil = ketidakpastian
    f["doji"] = float(body(n) / candle_range(n) < 0.1)

    # Hammer: shadow bawah panjang di downtrend = bullish reversal
    f["hammer"] = float(
        shadow_dn(n) > 2 * body(n) and
        shadow_up(n) < body(n) and
        c[n-1] < c[n-5]  # setelah downtrend
    )

    # Shooting star: shadow atas panjang di uptrend = bearish reversal
    f["shooting_star"] = float(
        shadow_up(n) > 2 * body(n) and
        shadow_dn(n) < body(n) and
        c[n-1] > c[n-5]
    )

    # Engulfing bullish: candle hijau besar menelan candle merah
    f["bull_engulf"] = float(
        c[n] > o[n] and c[n-1] < o[n-1] and  # hijau setelah merah
        c[n] > o[n-1] and o[n] < c[n-1]       # menelan sepenuhnya
    )

    # Engulfing bearish
    f["bear_engulf"] = float(
        c[n] < o[n] and c[n-1] > o[n-1] and
        c[n] < o[n-1] and o[n] > c[n-1]
    )

    # Marubozu: full body, hampir tidak ada shadow
    f["bull_marubozu"] = float(
        c[n] > o[n] and
        shadow_up(n) < 0.05 * body(n) and
        shadow_dn(n) < 0.05 * body(n)
    )

    # Inside bar: range hari ini dalam range kemarin = konsolidasi
    f["inside_bar"] = float(h[n] < h[n-1] and l[n] > l[n-1])

    # 3 candle bullish: 3 candle hijau berturut-turut
    f["three_bull"] = float(c[n] > o[n] and c[n-1] > o[n-1] and c[n-2] > o[n-2])
    f["three_bear"] = float(c[n] < o[n] and c[n-1] < o[n-1] and c[n-2] < o[n-2])

    # Body ratio: ukuran body relatif terhadap range
    f["body_ratio"] = body(n) / candle_range(n)

    return f

# ══════════════════════════════════════════════
# KATEGORI 6: STATISTICAL / MATHEMATICAL (11 fitur)
# ══════════════════════════════════════════════

def feat_statistical(close):
    """
    Fitur matematika/statistik — inti dari quant trading.
    Ini yang Renaissance gunakan dan trader biasa tidak pernah lihat.
    """
    f = {}
    log_ret = np.log(close / close.shift(1)).dropna()

    # Hurst Exponent (simplified R/S analysis)
    # < 0.5 = mean-reverting, > 0.5 = trending, = 0.5 = random walk
    def hurst_rs(series, min_n=10):
        n = len(series)
        if n < min_n * 2:
            return 0.5
        rs_list = []
        for lag in [n//4, n//3, n//2]:
            if lag < min_n:
                continue
            subset = series.values[-lag:]
            mean   = np.mean(subset)
            dev    = np.cumsum(subset - mean)
            r      = np.max(dev) - np.min(dev)
            s      = np.std(subset, ddof=1)
            if s > 0:
                rs_list.append((lag, r / s))
        if len(rs_list) < 2:
            return 0.5
        lags = np.log([x[0] for x in rs_list])
        rs   = np.log([x[1] for x in rs_list])
        return float(np.polyfit(lags, rs, 1)[0])

    f["hurst_20"] = hurst_rs(log_ret.tail(40))
    f["hurst_50"] = hurst_rs(log_ret.tail(100))

    # Mean reversion z-score: berapa std dev dari mean?
    window = 20
    mean   = close.rolling(window).mean()
    std    = close.rolling(window).std()
    f["zscore_20"] = ((close - mean) / (std + 1e-10)).iloc[-1]

    # Skewness & Kurtosis returns 20 period (deteksi distribusi fat-tail)
    ret20 = log_ret.tail(20)
    f["ret_skew_20"] = float(ret20.skew())
    f["ret_kurt_20"] = float(ret20.kurtosis())

    # Autocorrelation lag-1: apakah return hari ini prediksi hari besok?
    f["autocorr_1"] = float(log_ret.tail(30).autocorr(lag=1))
    f["autocorr_3"] = float(log_ret.tail(30).autocorr(lag=3))

    # Realized variance ratio: apakah volatilitas meningkat?
    rv5  = (log_ret ** 2).rolling(5).sum().iloc[-1]
    rv20 = (log_ret ** 2).rolling(20).sum().iloc[-1]
    f["rv_ratio"]  = rv5 / (rv20 / 4 + 1e-10)

    # Linear regression slope (trend strength matematika murni)
    n_reg = 20
    x_reg = np.arange(n_reg)
    y_reg = close.tail(n_reg).values
    if len(y_reg) == n_reg:
        slope, intercept = np.polyfit(x_reg, y_reg, 1)
        f["linreg_slope"] = slope / (y_reg.mean() + 1e-10) * 100  # dalam %
        predicted = slope * (n_reg - 1) + intercept
        f["linreg_r2"]  = float(1 - np.sum((y_reg - (slope * x_reg + intercept))**2) /
                                 (np.sum((y_reg - y_reg.mean())**2) + 1e-10))
    else:
        f["linreg_slope"] = 0.0
        f["linreg_r2"]    = 0.0

    return f

# ══════════════════════════════════════════════
# KATEGORI 7: MULTI-TIMEFRAME COMPOSITE (8 fitur)
# ══════════════════════════════════════════════

def feat_mtf_composite(df_1h, df_4h=None, df_1d=None):
    """
    Fitur komposit dari beberapa timeframe.
    Alignment multi-TF adalah salah satu alpha terkuat dalam trading.
    """
    f = {}

    # Dari 1H
    close_1h = df_1h["close"]
    f["trend_1h"]   = float(close_1h.ewm(span=20).mean().iloc[-1] >
                             close_1h.ewm(span=50).mean().iloc[-1])
    f["momentum_1h"]= close_1h.pct_change(8).iloc[-1] * 100

    # Dari 4H (jika tersedia)
    if df_4h is not None and len(df_4h) >= 50:
        close_4h = df_4h["close"]
        f["trend_4h"]    = float(close_4h.ewm(span=20).mean().iloc[-1] >
                                  close_4h.ewm(span=50).mean().iloc[-1])
        f["momentum_4h"] = close_4h.pct_change(5).iloc[-1] * 100
        f["vol_ratio_4h"]= (df_4h["volume"].iloc[-1] /
                             df_4h["volume"].rolling(20).mean().iloc[-1])
    else:
        f["trend_4h"]    = 0.5
        f["momentum_4h"] = 0.0
        f["vol_ratio_4h"]= 1.0

    # Dari 1D (jika tersedia)
    if df_1d is not None and len(df_1d) >= 50:
        close_1d = df_1d["close"]
        f["trend_1d"]    = float(close_1d.ewm(span=20).mean().iloc[-1] >
                                  close_1d.ewm(span=50).mean().iloc[-1])
        f["momentum_1d"] = close_1d.pct_change(5).iloc[-1] * 100
    else:
        f["trend_1d"]    = 0.5
        f["momentum_1d"] = 0.0

    # Alignment score: berapa banyak TF yang agree?
    alignment = f["trend_1h"] + f["trend_4h"] + f["trend_1d"]
    f["mtf_alignment"] = alignment / 3.0  # 0=semua bearish, 1=semua bullish

    return f

# ══════════════════════════════════════════════
# FUNGSI UTAMA: COMPUTE ALL FEATURES
# ══════════════════════════════════════════════

def compute_all_features(df_1h, df_4h=None, df_1d=None):
    """
    Hitung semua 85+ fitur dari dataframe OHLCV.

    Args:
        df_1h : DataFrame 1H dengan kolom open/high/low/close/volume
        df_4h : DataFrame 4H (opsional, untuk MTF)
        df_1d : DataFrame 1D (opsional, untuk MTF)

    Returns:
        dict: semua fitur (key=nama fitur, value=float)
        list: nama fitur (untuk training model)
    """
    if len(df_1h) < 60:
        return {}, []

    o = df_1h["open"].astype(float)
    h = df_1h["high"].astype(float)
    l = df_1h["low"].astype(float)
    c = df_1h["close"].astype(float)
    v = df_1h["volume"].astype(float)

    features = {}

    # 1. Momentum
    features.update(feat_momentum(c))

    # 2. RSI advanced
    features.update(feat_rsi_advanced(c))

    # 3. MACD advanced
    features.update(feat_macd_advanced(c))

    # 4. Volatility
    features.update(feat_volatility(h, l, c))

    # 5. Bollinger + Squeeze
    features.update(feat_bollinger(c, h, l))

    # 6. Volume & Microstructure
    features.update(feat_volume(c, v, h, l))

    # 7. Trend & Structure
    features.update(feat_trend(c, h, l))

    # 8. Candle patterns
    features.update(feat_candle_patterns(o, h, l, c))

    # 9. Statistical
    features.update(feat_statistical(c))

    # 10. Multi-timeframe
    features.update(feat_mtf_composite(df_1h, df_4h, df_1d))

    # Bersihkan NaN dan Inf
    clean = {}
    for k, v_val in features.items():
        try:
            val = float(v_val)
            if np.isnan(val) or np.isinf(val):
                clean[k] = 0.0
            else:
                clean[k] = round(val, 8)
        except Exception:
            clean[k] = 0.0

    feature_names = sorted(clean.keys())
    return clean, feature_names


def features_to_series(df_1h, df_4h=None, df_1d=None):
    """
    Return fitur sebagai pd.Series — siap masuk ML model.
    """
    feat_dict, feat_names = compute_all_features(df_1h, df_4h, df_1d)
    return pd.Series(feat_dict), feat_names


def get_feature_groups():
    """Return daftar fitur per kategori untuk analisis."""
    return {
        "momentum" : [f"ret_{n}" for n in [1,2,3,5,7,10,14,20,30]] +
                     ["roc_5","roc_10"],
        "rsi"      : [f"rsi_{p}" for p in [7,14,21]] +
                     [f"rsi_{p}_slope" for p in [7,14,21]] +
                     ["bull_div_score","bear_div_score"],
        "macd"     : [c for c in ["macd_12_26_val","macd_12_26_hist",
                      "macd_12_26_slope","macd_12_26_cross",
                      "macd_5_13_val","macd_5_13_hist",
                      "macd_5_13_slope","macd_5_13_cross"]],
        "volatility": [f"atr_{p}" for p in [7,14,21]] +
                      [f"atr_{p}_pct" for p in [7,14,21]] +
                      ["atr_ratio","hvol_10","hvol_20",
                       "chaikin_vol","ulcer_index"],
        "bollinger" : ["bb_width","bb_pos","bb_pct_b",
                       "bb_squeeze","bb_squeeze_bars"],
        "volume"    : ["vol_ratio_20","vol_ratio_5","vol_trend","vol_spike",
                       "obv_slope","vwm_10","mfi_14","adl_slope",
                       "force_idx_2","force_idx_13"],
        "trend"     : ["ema20","ema50","ema_20_50","ema_50_200",
                       "price_ema20","price_ema50","ema_stack_bull",
                       "ema_stack_bear","adx","pdi","mdi","adx_bull",
                       "sar_bull","ichi_above_cloud","ichi_tk_cross"],
        "patterns"  : ["doji","hammer","shooting_star","bull_engulf",
                       "bear_engulf","bull_marubozu","inside_bar",
                       "three_bull","three_bear","body_ratio"],
        "statistical": ["hurst_20","hurst_50","zscore_20","ret_skew_20",
                        "ret_kurt_20","autocorr_1","autocorr_3",
                        "rv_ratio","linreg_slope","linreg_r2"],
        "mtf"       : ["trend_1h","momentum_1h","trend_4h","momentum_4h",
                       "vol_ratio_4h","trend_1d","momentum_1d",
                       "mtf_alignment"],
    }