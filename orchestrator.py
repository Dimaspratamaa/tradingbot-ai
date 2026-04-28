# ============================================
# ORCHESTRATOR AGENT v1.0
# Koordinasi semua agent untuk keputusan final
#
# Arsitektur (Image 4):
#   Market Analysis Agent  ──┐
#   Risk Management Agent  ──┤
#   Sentiment Agent        ──┼──→ ORCHESTRATOR → Keputusan Final
#   Pattern/Quant Agent    ──┤
#   Whale/Onchain Agent    ──┘
#
# Cara kerja:
#   1. Setiap agent memberikan vote: BUY(+1), HOLD(0), SELL(-1)
#   2. Setiap agent punya bobot berdasarkan track record (IC)
#   3. Weighted sum → confidence score
#   4. Threshold: confidence > 0.6 → BUY/SELL, else HOLD
#   5. Bobot agent diupdate otomatis setelah setiap trade
# ============================================

import os
import json
import time
import pathlib
import numpy as np

from datetime import datetime

BASE_DIR    = pathlib.Path(__file__).parent
STATE_FILE  = BASE_DIR / "orchestrator_state.json"

# ── BOBOT DEFAULT SETIAP AGENT ────────────────
# Dinaikkan/diturunkan otomatis berdasarkan track record
DEFAULT_WEIGHTS = {
    "ml_ensemble"   : 0.25,   # ML — tertinggi karena data-driven
    "alpha_engine"  : 0.20,   # Alpha IC tracking
    "pattern_quant" : 0.15,   # Hurst + HMM + FFT
    "risk_manager"  : 0.15,   # Risk validation (VETO power)
    "sentiment"     : 0.10,   # FinBERT + Fear & Greed
    "whale"         : 0.08,   # Whale flow
    "onchain"       : 0.05,   # On-chain metrics
    "macro"         : 0.02,   # Macro economic
}

# Threshold untuk keputusan
BUY_THRESHOLD  = 0.55   # confidence > 55% → BUY
SELL_THRESHOLD = -0.55  # confidence < -55% → SELL
VETO_RISK      = True   # Risk Manager bisa veto keputusan apapun


# ══════════════════════════════════════════════
# STATE MANAGEMENT
# ══════════════════════════════════════════════

def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {
        "weights"      : DEFAULT_WEIGHTS.copy(),
        "agent_history": {},   # {agent: [correct, total]}
        "n_decisions"  : 0,
        "n_correct"    : 0,
        "last_update"  : "",
    }


def save_state(state):
    try:
        state["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception as e:
        print(f"  ⚠️  [ORCH] Save state error: {e}")


# ══════════════════════════════════════════════
# KUMPULKAN SINYAL DARI SEMUA AGENT
# ══════════════════════════════════════════════

def _get_ml_signal(df, atr):
    """
    Agent 1: ML Ensemble (XGBoost + RF + LSTM).
    Return: vote (-1/0/1), confidence (0-1), detail
    """
    try:
        from ml_ensemble import prediksi_ensemble
        sinyal, conf, votes = prediksi_ensemble(df)
        conf_norm = conf / 100.0

        if sinyal == "BUY":
            vote = 1
        elif sinyal == "SELL":
            vote = -1
        else:
            vote = 0

        return vote, conf_norm, f"ML:{sinyal}({conf:.0f}%)"
    except Exception as e:
        return 0, 0.5, f"ML:ERROR({e})"


def _get_alpha_signal(ind, sinyal_raw, skor_buy,
                       sentiment, onchain, mtf,
                       geo, macro, orderbook, market):
    """
    Agent 2: Alpha Engine (IC-weighted 28 factors).
    Return: vote, confidence, detail
    """
    try:
        from alpha_engine import (
            get_alpha_engine, extract_alpha_signals
        )
        ae      = get_alpha_engine()
        signals = extract_alpha_signals(
            ind, sinyal_raw, skor_buy,
            sentiment, onchain, mtf,
            skor_buy, geo, macro, market,
            orderbook, {}
        )
        score, detail, _ = ae.hitung_alpha_score(signals)
        conf = score / 100.0

        if score >= 65:
            vote = 1
        elif score <= 35:
            vote = -1
        else:
            vote = 0

        return vote, conf, f"Alpha:{score:.0f}/100"
    except Exception as e:
        return 0, 0.5, f"Alpha:ERROR"


def _get_pattern_signal(df):
    """
    Agent 3: Pattern Detector (Hurst + HMM + FFT).
    Return: vote, confidence, detail
    """
    try:
        from pattern_detector import analisis_pattern_quant
        hasil = analisis_pattern_quant(
            df["close"], df["volume"])

        regime   = hasil.get("hmm_regime", "CHOP")
        hurst_r  = hasil.get("hurst_regime", "RANDOM")
        conf_hmm = hasil.get("hmm_confidence", 0.5)

        if regime == "BULL" and hurst_r == "TRENDING":
            vote = 1
            conf = conf_hmm
        elif regime == "BEAR":
            vote = -1
            conf = conf_hmm
        elif regime == "CHOP" or hurst_r == "MEAN_REVERTING":
            vote = 0
            conf = 0.4   # tidak confident saat CHOP
        else:
            vote = 0
            conf = 0.5

        return vote, conf, f"Pattern:{regime}+{hurst_r}"
    except Exception as e:
        return 0, 0.5, f"Pattern:ERROR"


def _get_sentiment_signal(sentiment_data):
    """
    Agent 4: Sentiment (FinBERT + Fear & Greed).
    Return: vote, confidence, detail
    """
    try:
        if not sentiment_data:
            from sentiment_analyzer import get_market_sentiment
            sentiment_data = get_market_sentiment()

        skor_buy  = sentiment_data.get("skor_buy", 0)
        skor_sell = sentiment_data.get("skor_sell", 0)
        fg        = sentiment_data.get("fear_greed", {})
        fg_nilai  = fg.get("nilai", 50) if fg else 50

        net = skor_buy - skor_sell

        if net >= 2:
            vote = 1
            conf = min(0.8, 0.5 + net * 0.1)
        elif net <= -2:
            vote = -1
            conf = min(0.8, 0.5 + abs(net) * 0.1)
        else:
            vote = 0
            conf = 0.4

        # Fear & Greed boost
        if fg_nilai <= 20:   # Extreme Fear → contrarian BUY
            vote  = max(vote, 0) + 1
            vote  = min(1, vote)
            conf  = min(0.85, conf + 0.1)
        elif fg_nilai >= 80:  # Extreme Greed → contrarian caution
            vote  = min(vote, 0) - 1
            vote  = max(-1, vote)
            conf  = min(0.85, conf + 0.1)

        return vote, conf, f"Sentiment:{'BULL' if vote>0 else 'BEAR' if vote<0 else 'NEUT'}(F&G:{fg_nilai})"
    except Exception as e:
        return 0, 0.5, f"Sentiment:ERROR"


def _get_risk_signal(symbol, harga, atr, saldo,
                      posisi_spot, client, df):
    """
    Agent 5: Risk Manager — special VETO power.
    Jika risk manager bilang BLOCK → override semua.
    Return: vote, confidence, detail, veto
    """
    try:
        from risk_manager import (
            deteksi_volatility_regime, get_sizing_factor
        )

        vol     = deteksi_volatility_regime(df)
        sf      = get_sizing_factor()
        regime  = vol.get("regime", "NORMAL")
        boleh   = vol.get("boleh_entry", True)

        veto    = False

        # STORM → VETO semua entry
        if regime == "STORM":
            veto = True
            return -1, 0.9, f"Risk:VETO(STORM)", True

        # Consecutive loss → kurangi confidence
        if not sf.get("normal"):
            return 0, 0.3, f"Risk:CAUTION({sf['konsekutif']} loss)", False

        # ELEVATED → warning tapi tidak veto
        if regime == "ELEVATED":
            return 0, 0.4, f"Risk:ELEVATED(sizing-25%)", False

        # CALM/NORMAL → OK
        return 1, 0.7 if boleh else 0.3, \
               f"Risk:{regime}", False

    except Exception as e:
        return 0, 0.5, f"Risk:ERROR", False


def _get_whale_signal(symbol):
    """
    Agent 6: Whale Tracker.
    Return: vote, confidence, detail
    """
    try:
        from whale_tracker import get_whale_score
        whale = get_whale_score(symbol)
        if not whale:
            return 0, 0.5, "Whale:NO_DATA"

        skor_buy  = whale.get("skor_buy", 0)
        skor_sell = whale.get("skor_sell", 0)
        sinyal    = whale.get("sinyal", "NETRAL")
        net       = skor_buy - skor_sell

        if sinyal == "BULLISH" and net >= 1:
            return 1, 0.65, f"Whale:BULL(+{net})"
        elif sinyal == "BEARISH" and net <= -1:
            return -1, 0.65, f"Whale:BEAR({net})"
        else:
            return 0, 0.45, f"Whale:NEUTRAL"
    except Exception as e:
        return 0, 0.5, "Whale:ERROR"


def _get_onchain_signal():
    """
    Agent 7: On-chain metrics.
    Return: vote, confidence, detail
    """
    try:
        from onchain import get_onchain_score
        data = get_onchain_score()
        if not data:
            return 0, 0.5, "Onchain:NO_DATA"

        skor_buy  = data.get("skor_buy", 0)
        skor_sell = data.get("skor_sell", 0)
        net       = skor_buy - skor_sell

        if net >= 2:
            return 1, 0.6, f"Onchain:BULL(+{net})"
        elif net <= -2:
            return -1, 0.6, f"Onchain:BEAR({net})"
        return 0, 0.45, "Onchain:NEUT"
    except Exception as e:
        return 0, 0.5, "Onchain:ERROR"


def _get_macro_signal():
    """
    Agent 8: Macro economic.
    Return: vote, confidence, detail
    """
    try:
        from macro_analyzer import get_macro_score
        data = get_macro_score()
        if not data:
            return 0, 0.5, "Macro:NO_DATA"

        skor_buy  = data.get("skor_buy", 0)
        skor_sell = data.get("skor_sell", 0)
        net       = skor_buy - skor_sell

        if net >= 1:
            return 1, 0.55, f"Macro:BULL(+{net})"
        elif net <= -1:
            return -1, 0.55, f"Macro:BEAR({net})"
        return 0, 0.4, "Macro:NEUT"
    except Exception as e:
        return 0, 0.5, "Macro:ERROR"


# ══════════════════════════════════════════════
# ORCHESTRATOR CORE
# ══════════════════════════════════════════════

def orchestrate(symbol, df, harga, atr, saldo,
                posisi_spot, client,
                ind=None, sinyal_raw="HOLD",
                skor_buy=0, sentiment=None,
                onchain=None, mtf=None,
                geo=None, macro=None,
                orderbook=None, market=None):
    """
    Fungsi utama Orchestrator.
    Kumpulkan sinyal dari semua agent →
    weighted consensus → keputusan final.

    Return dict:
        keputusan   : "BUY" / "HOLD" / "SELL"
        confidence  : float 0-1
        skor_final  : float -1 to +1
        votes       : dict semua agent votes
        detail      : list penjelasan
        veto        : bool (risk veto aktif)
        bobot_pakai : dict bobot yang digunakan
    """
    state   = load_state()
    weights = state.get("weights", DEFAULT_WEIGHTS.copy())

    votes       = {}
    confs       = {}
    details     = []
    veto        = False
    veto_alasan = ""

    # ── Kumpulkan sinyal semua agent ──────────
    t0 = time.time()

    # Agent 1: ML Ensemble
    v, c, d = _get_ml_signal(df, atr)
    votes["ml_ensemble"] = v; confs["ml_ensemble"] = c
    details.append(d)

    # Agent 2: Alpha Engine
    v, c, d = _get_alpha_signal(
        ind or {}, sinyal_raw, skor_buy,
        sentiment or {}, onchain or {},
        mtf or {}, geo or {}, macro or {},
        orderbook or {}, market or {}
    )
    votes["alpha_engine"] = v; confs["alpha_engine"] = c
    details.append(d)

    # Agent 3: Pattern/Quant
    v, c, d = _get_pattern_signal(df)
    votes["pattern_quant"] = v; confs["pattern_quant"] = c
    details.append(d)

    # Agent 4: Sentiment
    v, c, d = _get_sentiment_signal(sentiment)
    votes["sentiment"] = v; confs["sentiment"] = c
    details.append(d)

    # Agent 5: Risk Manager (dengan VETO power)
    v, c, d, veto_flag = _get_risk_signal(
        symbol, harga, atr, saldo, posisi_spot, client, df)
    votes["risk_manager"] = v; confs["risk_manager"] = c
    details.append(d)
    if veto_flag and VETO_RISK:
        veto        = True
        veto_alasan = d

    # Agent 6: Whale
    v, c, d = _get_whale_signal(symbol)
    votes["whale"] = v; confs["whale"] = c
    details.append(d)

    # Agent 7: Onchain
    v, c, d = _get_onchain_signal()
    votes["onchain"] = v; confs["onchain"] = c
    details.append(d)

    # Agent 8: Macro
    v, c, d = _get_macro_signal()
    votes["macro"] = v; confs["macro"] = c
    details.append(d)

    elapsed = round(time.time() - t0, 2)

    # ── Jika VETO aktif → langsung HOLD ───────
    if veto:
        return {
            "keputusan" : "HOLD",
            "confidence": 0.0,
            "skor_final": 0.0,
            "votes"     : votes,
            "detail"    : details,
            "veto"      : True,
            "veto_alasan": veto_alasan,
            "bobot_pakai": weights,
            "elapsed"   : elapsed,
        }

    # ── Weighted consensus ────────────────────
    skor_total  = 0.0
    bobot_total = 0.0
    n_buy  = 0
    n_sell = 0
    n_hold = 0

    for agent, vote in votes.items():
        bobot = weights.get(agent, 0.05)
        conf  = confs.get(agent, 0.5)

        # Bobot efektif = bobot × confidence agent
        bobot_efektif = bobot * conf
        skor_total   += vote * bobot_efektif
        bobot_total  += bobot_efektif

        if vote > 0:   n_buy  += 1
        elif vote < 0: n_sell += 1
        else:          n_hold += 1

    # Normalize
    if bobot_total > 0:
        skor_final = skor_total / bobot_total
    else:
        skor_final = 0.0

    skor_final = float(np.clip(skor_final, -1, 1))

    # ── Keputusan final ───────────────────────
    if skor_final >= BUY_THRESHOLD:
        keputusan  = "BUY"
        confidence = skor_final
    elif skor_final <= SELL_THRESHOLD:
        keputusan  = "SELL"
        confidence = abs(skor_final)
    else:
        keputusan  = "HOLD"
        confidence = 1 - abs(skor_final)

    # Update decision counter
    state["n_decisions"] = state.get("n_decisions", 0) + 1
    save_state(state)

    return {
        "keputusan"  : keputusan,
        "confidence" : round(confidence, 4),
        "skor_final" : round(skor_final, 4),
        "votes"      : votes,
        "n_buy"      : n_buy,
        "n_sell"     : n_sell,
        "n_hold"     : n_hold,
        "detail"     : details,
        "veto"       : False,
        "bobot_pakai": weights,
        "elapsed"    : elapsed,
    }


# ══════════════════════════════════════════════
# UPDATE BOBOT — Belajar dari hasil trade
# ══════════════════════════════════════════════

def update_agent_weights(votes_saat_entry, profit_pct):
    """
    Update bobot setiap agent berdasarkan hasil trade.
    Agent yang benar prediksinya → bobot naik.
    Agent yang salah → bobot turun.

    Dipanggil dari simpan_transaksi() setelah trade selesai.
    """
    state   = load_state()
    weights = state.get("weights", DEFAULT_WEIGHTS.copy())
    history = state.setdefault("agent_history", {})

    trade_menang = profit_pct > 0

    for agent, vote in votes_saat_entry.items():
        if agent not in history:
            history[agent] = {"correct": 0, "total": 0}

        history[agent]["total"] += 1

        # Agent benar jika:
        # vote BUY (+1) dan trade profit → benar
        # vote SELL (-1) dan trade rugi → benar
        # vote HOLD (0) → netral, tidak dihitung
        if vote == 0:
            continue

        benar = (vote > 0 and trade_menang) or \
                (vote < 0 and not trade_menang)

        if benar:
            history[agent]["correct"] += 1

        # Hitung accuracy agent
        total   = history[agent]["total"]
        correct = history[agent]["correct"]
        acc     = correct / total if total > 0 else 0.5

        # Update bobot berdasarkan accuracy
        # Acc > 60% → naikkan, < 40% → turunkan
        if total >= 5:  # butuh minimal 5 trade sebelum update
            default_w = DEFAULT_WEIGHTS.get(agent, 0.05)
            if acc >= 0.60:
                # Naikkan bobot, max 2x default
                new_w = min(default_w * 2.0,
                            weights.get(agent, default_w) * 1.05)
            elif acc <= 0.40:
                # Turunkan bobot, min 0.3x default
                new_w = max(default_w * 0.3,
                            weights.get(agent, default_w) * 0.95)
            else:
                new_w = weights.get(agent, default_w)

            weights[agent] = round(new_w, 4)

    # Normalisasi total bobot = 1.0
    total_w = sum(weights.values())
    if total_w > 0:
        weights = {k: round(v/total_w, 4) for k, v in weights.items()}

    state["weights"]       = weights
    state["agent_history"] = history
    if trade_menang:
        state["n_correct"] = state.get("n_correct", 0) + 1

    save_state(state)
    return weights


# ══════════════════════════════════════════════
# FORMAT LAPORAN TELEGRAM
# ══════════════════════════════════════════════

def format_orchestrator_status():
    """Format status orchestrator untuk /orch command."""
    state   = load_state()
    weights = state.get("weights", DEFAULT_WEIGHTS)
    history = state.get("agent_history", {})
    n_dec   = state.get("n_decisions", 0)
    n_ok    = state.get("n_correct", 0)
    acc_orch= n_ok / n_dec * 100 if n_dec > 0 else 0

    teks = (
        f"🎯 <b>Orchestrator Status</b>\n"
        f"{'─'*26}\n"
        f"Keputusan : {n_dec}\n"
        f"Akurasi   : {acc_orch:.1f}%\n\n"
        f"<b>Bobot Agent (auto-update):</b>\n"
    )

    # Sort by bobot tertinggi
    sorted_w = sorted(weights.items(),
                      key=lambda x: x[1], reverse=True)
    for agent, bobot in sorted_w:
        hist  = history.get(agent, {})
        total = hist.get("total", 0)
        corr  = hist.get("correct", 0)
        acc   = corr/total*100 if total > 0 else 0
        bar   = "█" * int(bobot * 40)
        teks += (f"  {agent:15} {bobot:.3f} {bar}\n"
                 f"             acc:{acc:.0f}% ({corr}/{total})\n")

    return teks