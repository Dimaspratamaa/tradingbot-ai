# ============================================
# ALPHA ENGINE v1.0 — Phase 4
# ============================================

import os, json, time, pathlib
import numpy as np
import warnings
warnings.filterwarnings("ignore")

BASE_DIR         = pathlib.Path(__file__).parent
ALPHA_STATE_FILE = BASE_DIR / "alpha_state.json"

IC_WINDOW     = 50
IC_MIN_VALID  = 0.03
IC_MIN_BOOST  = 0.08
ALPHA_DECAY   = 0.95
MIN_OBSERVASI = 10

ALPHA_DEFINITIONS = {
    "rsi_oversold"  : {"kategori":"technical","bobot_awal":0.08,"aktif":True},
    "rsi_divergence": {"kategori":"technical","bobot_awal":0.10,"aktif":True},
    "macd_cross"    : {"kategori":"technical","bobot_awal":0.07,"aktif":True},
    "bb_bounce"     : {"kategori":"technical","bobot_awal":0.06,"aktif":True},
    "ichimoku_bull" : {"kategori":"technical","bobot_awal":0.07,"aktif":True},
    "ema_alignment" : {"kategori":"technical","bobot_awal":0.08,"aktif":True},
    "candle_pattern": {"kategori":"technical","bobot_awal":0.05,"aktif":True},
    "momentum_3h"   : {"kategori":"momentum","bobot_awal":0.09,"aktif":True},
    "momentum_24h"  : {"kategori":"momentum","bobot_awal":0.10,"aktif":True},
    "mtf_alignment" : {"kategori":"momentum","bobot_awal":0.12,"aktif":True},
    "adx_strong"    : {"kategori":"momentum","bobot_awal":0.07,"aktif":True},
    "volume_spike"  : {"kategori":"volume","bobot_awal":0.10,"aktif":True},
    "obv_trend"     : {"kategori":"volume","bobot_awal":0.08,"aktif":True},
    "mfi_oversold"  : {"kategori":"volume","bobot_awal":0.07,"aktif":True},
    "ml_ensemble"   : {"kategori":"ml","bobot_awal":0.15,"aktif":True},
    "bayesian"      : {"kategori":"ml","bobot_awal":0.10,"aktif":True},
    "hurst_trending": {"kategori":"quant","bobot_awal":0.08,"aktif":True},
    "hmm_bull"      : {"kategori":"quant","bobot_awal":0.09,"aktif":True},
    "fft_up"        : {"kategori":"quant","bobot_awal":0.06,"aktif":True},
    "mean_rev_buy"  : {"kategori":"quant","bobot_awal":0.09,"aktif":True},
    "geo_bullish"   : {"kategori":"macro","bobot_awal":0.06,"aktif":True},
    "macro_bullish" : {"kategori":"macro","bobot_awal":0.07,"aktif":True},
    "sentiment_bull": {"kategori":"macro","bobot_awal":0.07,"aktif":True},
    "fear_greed_low": {"kategori":"macro","bobot_awal":0.08,"aktif":True},
    "onchain_bull"  : {"kategori":"onchain","bobot_awal":0.09,"aktif":True},
    "funding_neg"   : {"kategori":"onchain","bobot_awal":0.07,"aktif":True},
    "ob_pressure"   : {"kategori":"orderbook","bobot_awal":0.08,"aktif":True},
    "multi_exchange": {"kategori":"orderbook","bobot_awal":0.08,"aktif":True},
}

def _load_alpha_state():
    default = {"alpha":{}, "trade_history":[], "update_terakhir":""}
    if not ALPHA_STATE_FILE.exists():
        return default
    try:
        state = json.loads(ALPHA_STATE_FILE.read_text())
        for nama, defn in ALPHA_DEFINITIONS.items():
            if nama not in state["alpha"]:
                state["alpha"][nama] = {
                    "bobot":defn["bobot_awal"],"ic_history":[],
                    "n_obs":0,"aktif":defn["aktif"],"ic_mean":0.0}
        return state
    except Exception:
        return default

def _save_alpha_state(state):
    state["update_terakhir"] = time.strftime("%Y-%m-%d %H:%M:%S")
    ALPHA_STATE_FILE.write_text(json.dumps(state, indent=2))

def hitung_ic(alpha_signals, returns):
    if len(alpha_signals) < MIN_OBSERVASI:
        return 0.0
    sig = np.array(alpha_signals, dtype=float)
    ret = np.array(returns, dtype=float)
    mask = ~(np.isnan(sig)|np.isnan(ret))
    sig, ret = sig[mask], ret[mask]
    if len(sig) < MIN_OBSERVASI:
        return 0.0
    try:
        from scipy.stats import spearmanr
        corr, _ = spearmanr(sig, ret)
        return float(corr) if not np.isnan(corr) else 0.0
    except Exception:
        try:
            return float(np.corrcoef(sig, ret)[0,1])
        except Exception:
            return 0.0

class AlphaEngine:
    def __init__(self):
        self.state = _load_alpha_state()
        for nama, defn in ALPHA_DEFINITIONS.items():
            if nama not in self.state["alpha"]:
                self.state["alpha"][nama] = {
                    "bobot":defn["bobot_awal"],"ic_history":[],
                    "n_obs":0,"aktif":defn["aktif"],"ic_mean":0.0}

    def hitung_alpha_score(self, sinyal_dict):
        alpha_state = self.state["alpha"]
        total_score = total_bobot = 0.0
        detail = []
        bobot_aktif = {}
        for nama, nilai in sinyal_dict.items():
            if nama not in alpha_state: continue
            a = alpha_state[nama]
            if not a.get("aktif", True): continue
            bobot = a["bobot"]
            ic = a.get("ic_mean", 0.0)
            if ic > IC_MIN_BOOST:
                be = bobot * (1 + ic * 2)
            elif ic < 0:
                be = bobot * max(0.1, 1 + ic)
            else:
                be = bobot
            contrib = float(nilai) * be
            total_score += contrib
            total_bobot += be
            bobot_aktif[nama] = round(be, 4)
            if float(nilai) > 0.1:
                ic_str = f" IC={ic:.3f}" if a["n_obs"] >= MIN_OBSERVASI else ""
                detail.append(f"α:{nama[:12]}={float(nilai):.2f}×{be:.3f}{ic_str}")
        alpha_score = (total_score/total_bobot*100) if total_bobot > 0 else 50.0
        return round(alpha_score, 2), detail, bobot_aktif

    def skor_ke_trading_score(self, alpha_score, threshold=55):
        if alpha_score >= 80: return 12
        elif alpha_score >= 70: return 9
        elif alpha_score >= 60: return 6
        elif alpha_score >= threshold: return 3
        elif alpha_score < 30: return -3
        elif alpha_score < 40: return -1
        else: return 0

    def catat_trade(self, sinyal_dict, return_aktual, waktu=None):
        if waktu is None:
            waktu = time.strftime("%Y-%m-%d %H:%M:%S")
        self.state["trade_history"].append({
            "waktu":waktu,"sinyal":sinyal_dict,"return_aktual":return_aktual})
        self.state["trade_history"] = self.state["trade_history"][-500:]
        self._update_ic()
        _save_alpha_state(self.state)

    def _update_ic(self):
        history = self.state["trade_history"][-IC_WINDOW:]
        if len(history) < MIN_OBSERVASI: return
        for nama in ALPHA_DEFINITIONS.keys():
            signals, rets = [], []
            for h in history:
                sig = h["sinyal"].get(nama, 0)
                if sig is not None:
                    signals.append(float(sig))
                    rets.append(h["return_aktual"])
            if len(signals) < MIN_OBSERVASI: continue
            ic = hitung_ic(signals, rets)
            a  = self.state["alpha"][nama]
            a["ic_history"].append(ic)
            a["ic_history"] = a["ic_history"][-IC_WINDOW:]
            a["n_obs"]      = len(signals)
            a["ic_mean"]    = round(float(np.mean(a["ic_history"])), 4)
            defn = ALPHA_DEFINITIONS[nama]
            b0   = defn["bobot_awal"]
            ic_m = a["ic_mean"]
            if ic_m > IC_MIN_BOOST:
                a["bobot"] = min(b0*2.0, b0*(1+ic_m*5))
            elif ic_m < 0 and a["n_obs"] >= MIN_OBSERVASI*2:
                a["bobot"] = max(b0*0.1, b0*(1+ic_m))
                if ic_m < -0.05:
                    print(f"  Alpha [{nama}] IC={ic_m:.3f} bobot dikurangi")
            else:
                a["bobot"] = a["bobot"]*ALPHA_DECAY + b0*(1-ALPHA_DECAY)
            if ic_m < -0.10 and a["n_obs"] >= MIN_OBSERVASI*3:
                a["aktif"] = False
                print(f"  Alpha [{nama}] DIMATIKAN IC={ic_m:.3f}")

    def get_alpha_report(self):
        rows = []
        for nama, a in self.state["alpha"].items():
            defn = ALPHA_DEFINITIONS.get(nama, {})
            rows.append({
                "nama":nama,"kategori":defn.get("kategori","?"),
                "bobot":round(a["bobot"],4),"ic_mean":a.get("ic_mean",0.0),
                "n_obs":a.get("n_obs",0),"aktif":a.get("aktif",True),
                "status":("MATI" if not a.get("aktif") else
                          "BAGUS" if a.get("ic_mean",0) > IC_MIN_BOOST else
                          "LEMAH" if a.get("ic_mean",0) < 0 else "OK")})
        return sorted(rows, key=lambda x: -x["ic_mean"])

    def format_telegram_report(self):
        report = self.get_alpha_report()
        aktif  = sum(1 for r in report if r["aktif"])
        teks   = f"Alpha Engine: {len(report)} factors | {aktif} aktif\n"
        for r in report[:10]:
            teks += f"{r['status']} {r['nama']:15} IC={r['ic_mean']:+.3f} w={r['bobot']:.3f}\n"
        return teks

def extract_alpha_signals(ind, ml_pred, ml_conf, onchain, geo,
                           bayes, mtf, ob, mx, btc, sent,
                           macro, pattern=None):
    s = {}
    s["rsi_oversold"]   = max(0,(35-ind["rsi"])/35) if ind["rsi"]<35 else 0
    s["rsi_divergence"] = float(ind.get("bull_div",False))
    s["macd_cross"]     = float(ind.get("macd_up",False))
    s["bb_bounce"]      = float(ind.get("bb_bawah",False))
    s["ichimoku_bull"]  = float(ind.get("ichi_atas",False) or ind.get("tk_up",False))
    s["ema_alignment"]  = float(ind.get("ema_bull",False))
    s["candle_pattern"] = float(ind.get("candle_bullish",False))
    mom = ind.get("momentum",0)
    s["momentum_3h"]    = min(1.0,max(0,mom/10))
    s["momentum_24h"]   = min(1.0,max(0,mom/5)) if mom>3 else 0
    s["mtf_alignment"]  = mtf.get("n_konfirmasi",0)/3.0
    adx = ind.get("adx",0)
    s["adx_strong"]     = min(1.0,max(0,(adx-25)/25)) if adx>25 else 0
    vol_r = ind.get("vol_ratio",1)
    s["volume_spike"]   = min(1.0,max(0,(vol_r-1)/2)) if vol_r>1.2 else 0
    s["obv_trend"]      = float(ind.get("vol_tinggi",False))
    s["mfi_oversold"]   = 0
    s["ml_ensemble"]    = ml_conf/100 if ml_pred=="BUY" else 0
    s["bayesian"]       = min(1.0,max(0,(bayes-50)/50)) if bayes>50 else 0
    if pattern:
        h = pattern.get("hurst",{})
        hmm = pattern.get("hmm",{})
        fft = pattern.get("fourier",{})
        mr  = pattern.get("mean_reversion",{})
        h50 = h.get("hurst_50",{}).get("H",0.5)
        s["hurst_trending"] = min(1.0,max(0,(h50-0.5)*4)) if h50>0.5 else 0
        s["hmm_bull"]  = hmm.get("confidence",0) if hmm.get("regime")=="BULL" else 0
        s["fft_up"]    = 1.0 if fft.get("prediksi")=="UP" else 0
        z = mr.get("z_score",0)
        s["mean_rev_buy"] = min(1.0,max(0,(-z-1.5)/2)) if z<-1.5 else 0
    else:
        s["hurst_trending"]=s["hmm_bull"]=s["fft_up"]=s["mean_rev_buy"]=0
    s["geo_bullish"]    = min(1.0,geo.get("skor_buy",0)/3)
    s["macro_bullish"]  = min(1.0,macro.get("skor_buy",0)/3)
    s["sentiment_bull"] = min(1.0,sent.get("skor_buy",0)/3)
    fg = onchain.get("fear_greed",{}).get("score",50)
    s["fear_greed_low"] = min(1.0,max(0,(30-fg)/30)) if fg<30 else 0
    s["onchain_bull"]   = min(1.0,onchain.get("skor_buy",0)/3)
    fr = onchain.get("funding_rate",{}).get("rate",0)
    s["funding_neg"]    = min(1.0,max(0,-fr*100)) if fr<0 else 0
    s["ob_pressure"]    = min(1.0,ob.get("skor_buy",0)/3)
    s["multi_exchange"] = min(1.0,mx.get("skor_buy",0)/3)
    return s

_alpha_engine_instance = None

def get_alpha_engine():
    global _alpha_engine_instance
    if _alpha_engine_instance is None:
        _alpha_engine_instance = AlphaEngine()
    return _alpha_engine_instance