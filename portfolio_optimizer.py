# ============================================
# PORTFOLIO OPTIMIZER v1.0 — Phase 5
# Terinspirasi Bridgewater & Renaissance Technologies
#
# 3 strategi optimasi portofolio institusional:
#
#   1. Markowitz Mean-Variance Optimization
#      → Maksimalkan return per unit risiko
#      → "Efficient Frontier" — kombinasi optimal
#
#   2. Risk Parity (Bridgewater style)
#      → Setiap aset berkontribusi risiko yang sama
#      → Tidak ada aset yang mendominasi risiko
#
#   3. CVaR Optimization (Conditional Value at Risk)
#      → Batasi kerugian di skenario terburuk 5%
#      → Lebih robust dari Markowitz untuk crypto
#
# Output: alokasi modal optimal per koin (dalam %)
# ============================================

import numpy as np
import pandas as pd
import json
import time
import pathlib
import warnings
warnings.filterwarnings('ignore')

BASE_DIR   = pathlib.Path(__file__).parent
PORT_FILE  = BASE_DIR / "portfolio_state.json"

# ── KONFIGURASI ───────────────────────────────
PORT_LOOKBACK    = 72     # 72 candle (3 hari data 1H) untuk estimasi
MIN_MODAL_PCT    = 0.05   # Minimum 5% per posisi
MAX_MODAL_PCT    = 0.40   # Maximum 40% per posisi (konsentrasi)
RISK_FREE_RATE   = 0.05   # 5% per tahun (risk-free rate)
TARGET_VOL       = 0.20   # Target volatilitas portofolio 20%/tahun
REBALANCE_HOURS  = 24     # Rebalance setiap 24 jam

# ══════════════════════════════════════════════
# 1. DATA PREPARATION
# ══════════════════════════════════════════════

def ambil_returns_historis(client, symbols, limit=PORT_LOOKBACK):
    """
    Ambil return historis semua simbol dari Binance.
    Return: DataFrame returns (kolom = simbol)
    """
    returns_dict = {}

    for sym in symbols:
        try:
            from binance.client import Client as BC
            klines = client.get_klines(
                symbol=sym,
                interval=BC.KLINE_INTERVAL_1HOUR,
                limit=limit + 1
            )
            closes = np.array([float(k[4]) for k in klines])
            if len(closes) < 10:
                continue
            ret = np.diff(np.log(closes))  # log returns
            returns_dict[sym] = ret
        except Exception:
            pass

    if not returns_dict:
        return None

    # Samakan panjang
    min_len = min(len(v) for v in returns_dict.values())
    df = pd.DataFrame({
        sym: ret[-min_len:]
        for sym, ret in returns_dict.items()
    })
    return df.dropna()


def hitung_statistik_returns(returns_df):
    """
    Hitung mean returns dan covariance matrix.
    Annualized untuk crypto (24*365 jam per tahun).
    """
    n_hours_per_year = 24 * 365

    mean_ret = returns_df.mean() * n_hours_per_year
    cov_mat  = returns_df.cov() * n_hours_per_year
    std_ret  = returns_df.std() * np.sqrt(n_hours_per_year)

    return mean_ret, cov_mat, std_ret

# ══════════════════════════════════════════════
# 2. MARKOWITZ MEAN-VARIANCE OPTIMIZATION
# ══════════════════════════════════════════════

def markowitz_optimize(mean_ret, cov_mat, n_simulations=3000):
    """
    Monte Carlo simulation untuk Efficient Frontier.
    Temukan portofolio dengan Sharpe Ratio tertinggi.

    Return:
        weights_optimal : array bobot per aset
        metrics         : dict {sharpe, return, volatility}
    """
    n_assets = len(mean_ret)
    if n_assets < 2:
        return np.array([1.0]), {}

    best_sharpe = -np.inf
    best_weights = np.ones(n_assets) / n_assets

    results = {
        "sharpe"    : [],
        "returns"   : [],
        "volatility": [],
        "weights"   : []
    }

    for _ in range(n_simulations):
        # Random weights yang sum = 1
        w = np.random.dirichlet(np.ones(n_assets))

        # Portfolio metrics
        port_ret  = np.dot(w, mean_ret)
        cov_arr   = cov_mat.values if hasattr(cov_mat, "values") else cov_mat
        port_var  = w @ cov_arr @ w
        port_vol  = np.sqrt(max(port_var, 1e-10))
        sharpe    = (port_ret - RISK_FREE_RATE) / port_vol

        results["sharpe"].append(sharpe)
        results["returns"].append(port_ret)
        results["volatility"].append(port_vol)
        results["weights"].append(w)

        if sharpe > best_sharpe:
            best_sharpe  = sharpe
            best_weights = w

    # Terapkan batas min/max
    best_weights = _apply_weight_constraints(best_weights, n_assets)

    idx_best = np.argmax(results["sharpe"])
    metrics = {
        "sharpe"    : round(float(results["sharpe"][idx_best]), 4),
        "return"    : round(float(results["returns"][idx_best]), 4),
        "volatility": round(float(results["volatility"][idx_best]), 4),
        "metode"    : "Markowitz"
    }

    return best_weights, metrics


# ══════════════════════════════════════════════
# 3. RISK PARITY (Bridgewater Style)
# ══════════════════════════════════════════════

def risk_parity_optimize(cov_mat, max_iter=200, tol=1e-6):
    """
    Risk Parity: setiap aset berkontribusi risiko yang sama.

    Algoritma: Iterative Risk Parity (Maillard et al.)
    - Mulai dari equal weight
    - Iterasi sampai kontribusi risiko sama rata

    Keunggulan: lebih stabil dari Markowitz saat crypto volatile
    """
    n = len(cov_mat)
    cov = cov_mat.values if hasattr(cov_mat, "values") else np.array(cov_mat)

    # Mulai dari equal weight
    w = np.ones(n) / n

    for _ in range(max_iter):
        # Hitung kontribusi risiko setiap aset
        sigma  = np.sqrt(w @ cov @ w)
        if sigma < 1e-10:
            break
        mrc    = cov @ w / sigma          # Marginal Risk Contribution
        rc     = w * mrc                  # Risk Contribution
        target = sigma / n                # Target: rata-rata sama

        # Update weights
        w_new = w * (target / (rc + 1e-10))
        w_new = w_new / w_new.sum()

        # Cek konvergensi
        if np.max(np.abs(w_new - w)) < tol:
            break
        w = w_new

    w = _apply_weight_constraints(w, n)

    # Hitung metrics
    port_vol = np.sqrt(w @ cov @ w)
    rc_final = w * (cov @ w / (port_vol + 1e-10))
    rc_pct   = rc_final / rc_final.sum()

    metrics = {
        "volatility" : round(float(port_vol), 4),
        "rc_max"     : round(float(rc_pct.max()), 4),
        "rc_min"     : round(float(rc_pct.min()), 4),
        "metode"     : "RiskParity"
    }

    return w, metrics


# ══════════════════════════════════════════════
# 4. CVaR OPTIMIZATION
# ══════════════════════════════════════════════

def cvar_optimize(returns_df, confidence=0.95, n_simulations=2000):
    """
    Conditional Value at Risk (CVaR) Optimization.

    CVaR = rata-rata kerugian di (1-confidence)% skenario terburuk
    Minimasi CVaR sambil memaksimalkan return.

    Lebih robust untuk crypto karena:
    - Menangani fat-tail distribution
    - Tidak asumsikan distribusi normal
    """
    n_assets = len(returns_df.columns)
    n_obs    = len(returns_df)

    if n_assets < 2 or n_obs < 20:
        return np.ones(n_assets) / n_assets, {}

    returns = returns_df.values

    best_ratio = -np.inf
    best_w     = np.ones(n_assets) / n_assets

    for _ in range(n_simulations):
        w = np.random.dirichlet(np.ones(n_assets))

        # Portfolio returns per periode
        port_ret_series = returns @ w

        # CVaR: rata-rata loss di tail terburuk
        alpha    = 1 - confidence
        var_idx  = int(n_obs * alpha)
        if var_idx < 1:
            var_idx = 1
        sorted_ret = np.sort(port_ret_series)
        cvar       = -np.mean(sorted_ret[:var_idx])  # positif = kerugian

        # Expected return
        exp_ret = np.mean(port_ret_series) * 24 * 365

        # Reward / Risk ratio
        if cvar > 0:
            ratio = exp_ret / cvar
        else:
            ratio = exp_ret

        if ratio > best_ratio:
            best_ratio = ratio
            best_w     = w

    best_w = _apply_weight_constraints(best_w, n_assets)

    # Hitung CVaR final
    port_final = returns @ best_w
    sorted_f   = np.sort(port_final)
    var_idx    = max(1, int(n_obs * (1 - confidence)))
    cvar_final = -np.mean(sorted_f[:var_idx]) * np.sqrt(24 * 365)

    metrics = {
        "cvar_annual" : round(float(cvar_final), 4),
        "ratio"       : round(float(best_ratio), 4),
        "metode"      : "CVaR"
    }

    return best_w, metrics


# ══════════════════════════════════════════════
# 5. ENSEMBLE ALLOCATION
# ══════════════════════════════════════════════

def ensemble_allocation(returns_df, metode="auto"):
    """
    Gabungkan 3 metode optimasi dengan voting berbobot.

    Bobot default:
    - Markowitz : 30% (return optimal)
    - Risk Parity: 40% (stabilitas)
    - CVaR       : 30% (tail risk)

    Return:
        weights_final : dict {symbol: float}
        detail        : info metode dan metrics
    """
    symbols  = list(returns_df.columns)
    n        = len(symbols)

    if n == 0:
        return {}, {}

    if n == 1:
        return {symbols[0]: 1.0}, {"metode": "single"}

    mean_ret, cov_mat, std_ret = hitung_statistik_returns(returns_df)

    results  = {}
    metrics  = {}
    bobot_metode = {"markowitz": 0.3, "risk_parity": 0.4, "cvar": 0.3}

    # Markowitz
    try:
        w_mw, m_mw = markowitz_optimize(mean_ret, cov_mat)
        results["markowitz"] = w_mw
        metrics["markowitz"] = m_mw
    except Exception as e:
        bobot_metode["markowitz"] = 0
        print(f"  ⚠️  Markowitz error: {e}")

    # Risk Parity
    try:
        w_rp, m_rp = risk_parity_optimize(cov_mat)
        results["risk_parity"] = w_rp
        metrics["risk_parity"] = m_rp
    except Exception as e:
        bobot_metode["risk_parity"] = 0
        print(f"  ⚠️  Risk Parity error: {e}")

    # CVaR
    try:
        w_cv, m_cv = cvar_optimize(returns_df)
        results["cvar"] = w_cv
        metrics["cvar"] = m_cv
    except Exception as e:
        bobot_metode["cvar"] = 0
        print(f"  ⚠️  CVaR error: {e}")

    if not results:
        # Fallback equal weight
        w_eq = np.ones(n) / n
        return dict(zip(symbols, w_eq.tolist())), {"metode": "equal"}

    # Normalize bobot metode
    total_bm = sum(bobot_metode[m] for m in results)
    if total_bm <= 0:
        total_bm = 1

    # Weighted average
    w_ensemble = np.zeros(n)
    for metode_name, w in results.items():
        bm = bobot_metode.get(metode_name, 0) / total_bm
        w_ensemble += bm * w

    # Normalize final
    w_ensemble = w_ensemble / w_ensemble.sum()
    w_ensemble = _apply_weight_constraints(w_ensemble, n)

    weights_dict = {
        sym: round(float(w), 4)
        for sym, w in zip(symbols, w_ensemble)
    }

    # Sharpe dari ensemble
    port_var   = w_ensemble @ cov_mat.values @ w_ensemble
    port_vol   = np.sqrt(max(port_var, 1e-10))
    port_ret   = np.dot(w_ensemble, mean_ret)
    sharpe_ens = (port_ret - RISK_FREE_RATE) / port_vol

    detail = {
        "metode"   : "Ensemble (MW+RP+CVaR)",
        "sharpe"   : round(float(sharpe_ens), 4),
        "vol"      : round(float(port_vol), 4),
        "return"   : round(float(port_ret), 4),
        "sub_metrics": metrics,
        "n_assets" : n,
    }

    return weights_dict, detail


# ══════════════════════════════════════════════
# 6. DYNAMIC REBALANCING
# ══════════════════════════════════════════════

class PortfolioOptimizer:
    """
    Portfolio Optimizer dengan auto-rebalancing.
    Simpan state ke disk agar persist setelah Railway restart.
    """

    def __init__(self):
        self.state = self._load()

    def _load(self):
        if PORT_FILE.exists():
            try:
                return json.loads(PORT_FILE.read_text())
            except Exception:
                pass
        return {
            "weights_target"  : {},
            "weights_aktual"  : {},
            "last_rebalance"  : "",
            "last_metrics"    : {},
            "history"         : []
        }

    def _save(self):
        self.state["update"] = time.strftime("%Y-%m-%d %H:%M:%S")
        PORT_FILE.write_text(json.dumps(self.state, indent=2))

    def perlu_rebalance(self):
        """Cek apakah sudah waktunya rebalance."""
        last = self.state.get("last_rebalance", "")
        if not last:
            return True
        try:
            from datetime import datetime
            last_dt  = datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
            elapsed  = (datetime.now() - last_dt).total_seconds() / 3600
            return elapsed >= REBALANCE_HOURS
        except Exception:
            return True

    def hitung_alokasi_optimal(self, client, symbols_aktif,
                                saldo_total, metode="ensemble"):
        """
        Hitung alokasi modal optimal untuk daftar simbol.

        Args:
            client       : Binance client
            symbols_aktif: list simbol yang ingin di-hold
            saldo_total  : total saldo USDT
            metode       : "markowitz", "risk_parity", "cvar", "ensemble"

        Return:
            alokasi_usd: dict {symbol: float USD}
        """
        if not symbols_aktif or saldo_total <= 0:
            return {}

        print(f"\n  📊 Optimasi portofolio ({len(symbols_aktif)} aset)...")

        # Ambil data return historis
        returns_df = ambil_returns_historis(client, symbols_aktif)
        if returns_df is None or returns_df.empty:
            # Fallback equal weight
            per_aset = saldo_total / len(symbols_aktif)
            return {sym: round(per_aset, 2) for sym in symbols_aktif}

        # Hitung alokasi optimal
        if metode == "markowitz":
            mean_r, cov_m, _ = hitung_statistik_returns(returns_df)
            weights, detail   = markowitz_optimize(mean_r, cov_m)
            weights_dict = dict(zip(returns_df.columns, weights))
        elif metode == "risk_parity":
            _, cov_m, _    = hitung_statistik_returns(returns_df)
            weights, detail = risk_parity_optimize(cov_m)
            weights_dict = dict(zip(returns_df.columns, weights))
        elif metode == "cvar":
            weights, detail = cvar_optimize(returns_df)
            weights_dict = dict(zip(returns_df.columns, weights))
        else:
            weights_dict, detail = ensemble_allocation(returns_df)

        # Konversi ke USD
        alokasi_usd = {}
        for sym, w in weights_dict.items():
            usd = saldo_total * w
            # Clamp ke min/max
            usd = max(saldo_total * MIN_MODAL_PCT,
                      min(saldo_total * MAX_MODAL_PCT, usd))
            alokasi_usd[sym] = round(usd, 2)

        # Simpan state
        self.state["weights_target"]  = weights_dict
        self.state["last_rebalance"]  = time.strftime("%Y-%m-%d %H:%M:%S")
        self.state["last_metrics"]    = detail
        self.state["history"].append({
            "waktu"  : self.state["last_rebalance"],
            "weights": weights_dict,
            "metode" : detail.get("metode", metode)
        })
        self.state["history"] = self.state["history"][-30:]
        self._save()

        # Print summary
        print(f"  Metode : {detail.get('metode','?')}")
        print(f"  Sharpe : {detail.get('sharpe', 0):.3f}")
        print(f"  Vol    : {detail.get('vol', 0):.1%}")
        for sym, usd in sorted(alokasi_usd.items(),
                                key=lambda x: -x[1]):
            w_pct = weights_dict.get(sym, 0) * 100
            print(f"    {sym:14} ${usd:8.2f} ({w_pct:.1f}%)")

        return alokasi_usd

    def get_modal_untuk_symbol(self, symbol, saldo_total,
                                kandidat_symbols, client=None):
        """
        Return modal optimal untuk satu simbol berdasarkan
        bobot portofolio yang sudah dihitung.

        Jika belum ada bobot → equal weight.
        """
        weights = self.state.get("weights_target", {})

        if symbol in weights and weights[symbol] > 0:
            modal = saldo_total * weights[symbol]
        elif kandidat_symbols:
            # Equal weight sebagai fallback
            modal = saldo_total / max(len(kandidat_symbols), 1)
        else:
            modal = saldo_total * 0.25  # default 25%

        # Clamp
        modal = max(saldo_total * MIN_MODAL_PCT,
                    min(saldo_total * MAX_MODAL_PCT, modal))
        return round(modal, 2)

    def format_telegram(self):
        """Format laporan portofolio untuk Telegram."""
        weights = self.state.get("weights_target", {})
        metrics = self.state.get("last_metrics", {})
        if not weights:
            return "📊 Portfolio optimizer belum berjalan"

        teks  = "📊 <b>PORTFOLIO ALLOCATION</b>\n"
        teks += f"Metode: {metrics.get('metode','?')}\n"
        teks += f"Sharpe: {metrics.get('sharpe',0):.3f} | "
        teks += f"Vol: {metrics.get('vol',0):.1%}\n\n"
        for sym, w in sorted(weights.items(), key=lambda x: -x[1]):
            bar   = "█" * int(w * 20)
            teks += f"{sym:14} {w:.1%} {bar}\n"
        return teks


# ── HELPER ────────────────────────────────────

def _apply_weight_constraints(weights, n_assets):
    """Terapkan batas min/max per aset dan renormalisasi."""
    w = np.array(weights, dtype=float)
    w = np.clip(w, MIN_MODAL_PCT, MAX_MODAL_PCT)
    total = w.sum()
    if total > 0:
        w = w / total
    else:
        w = np.ones(n_assets) / n_assets
    return w


# ── SINGLETON ─────────────────────────────────
_optimizer = None

def get_portfolio_optimizer():
    global _optimizer
    if _optimizer is None:
        _optimizer = PortfolioOptimizer()
    return _optimizer