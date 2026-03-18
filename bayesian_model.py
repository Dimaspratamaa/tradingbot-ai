# ============================================
# BAYESIAN MODEL untuk Trading Bot
# Menghitung probabilitas harga naik/turun
# ============================================

import numpy as np
from scipy import stats
import json
import os

class BayesianTradingModel:
    """
    Model Bayesian untuk prediksi arah harga
    Menggabungkan semua sinyal menjadi probabilitas
    """

    def __init__(self):
        # ── Prior Probability ──────────────────
        # Probabilitas awal sebelum lihat indikator
        # 0.5 = 50/50 tidak tahu arah pasar
        self.prior_buy  = 0.45  # Sedikit bias ke HOLD
        self.prior_hold = 0.55

        # ── Likelihood setiap indikator ────────
        # P(indikator aktif | harga akan naik)
        # Nilai dari data historis & penelitian
        self.likelihood = {
            # Teknikal
            "rsi_oversold"    : {"buy": 0.75, "hold": 0.25},
            "rsi_overbought"  : {"buy": 0.20, "hold": 0.80},
            "macd_up"         : {"buy": 0.70, "hold": 0.30},
            "macd_down"       : {"buy": 0.25, "hold": 0.75},
            "bb_bawah"        : {"buy": 0.72, "hold": 0.28},
            "bb_atas"         : {"buy": 0.22, "hold": 0.78},
            "ichimoku_bullish": {"buy": 0.68, "hold": 0.32},
            "volume_tinggi"   : {"buy": 0.60, "hold": 0.40},
            "bull_divergence" : {"buy": 0.78, "hold": 0.22},

            # Machine Learning
            "ml_buy_high"     : {"buy": 0.85, "hold": 0.15},
            "ml_buy_medium"   : {"buy": 0.65, "hold": 0.35},
            "ml_hold"         : {"buy": 0.30, "hold": 0.70},

            # On-Chain
            "fear_extreme"    : {"buy": 0.80, "hold": 0.20},
            "fear_normal"     : {"buy": 0.62, "hold": 0.38},
            "greed_extreme"   : {"buy": 0.20, "hold": 0.80},
            "funding_negatif" : {"buy": 0.70, "hold": 0.30},
            "funding_positif" : {"buy": 0.30, "hold": 0.70},
            "btc_dominan"     : {"buy": 0.60, "hold": 0.40},
        }

        # Riwayat update untuk adaptive learning
        self.riwayat = []

    def hitung_probabilitas(self, sinyal_aktif: list) -> dict:
        """
        Hitung probabilitas BUY menggunakan Naive Bayes

        Args:
            sinyal_aktif: list sinyal yang aktif saat ini

        Returns:
            dict berisi probabilitas dan confidence
        """
        # Mulai dengan prior
        prob_buy  = self.prior_buy
        prob_hold = self.prior_hold

        detail = []

        # Update dengan setiap sinyal (Naive Bayes)
        for sinyal in sinyal_aktif:
            if sinyal in self.likelihood:
                like_buy  = self.likelihood[sinyal]["buy"]
                like_hold = self.likelihood[sinyal]["hold"]

                # Bayes update
                prob_buy  *= like_buy
                prob_hold *= like_hold

                detail.append({
                    "sinyal"   : sinyal,
                    "like_buy" : like_buy,
                    "like_hold": like_hold
                })

        # Normalisasi
        total     = prob_buy + prob_hold
        if total > 0:
            prob_buy  = prob_buy / total
            prob_hold = prob_hold / total
        else:
            prob_buy  = 0.5
            prob_hold = 0.5

        # Confidence level
        selisih = abs(prob_buy - prob_hold)
        if selisih >= 0.4:
            confidence = "SANGAT TINGGI"
            conf_emoji = "🔥"
        elif selisih >= 0.25:
            confidence = "TINGGI"
            conf_emoji = "✅"
        elif selisih >= 0.15:
            confidence = "SEDANG"
            conf_emoji = "🟡"
        else:
            confidence = "RENDAH"
            conf_emoji = "⚠️"

        # Keputusan
        if prob_buy >= 0.70:
            keputusan = "BUY_KUAT"
        elif prob_buy >= 0.60:
            keputusan = "BUY_LEMAH"
        elif prob_hold >= 0.70:
            keputusan = "HOLD_KUAT"
        else:
            keputusan = "NEUTRAL"

        return {
            "prob_buy"   : round(prob_buy * 100, 2),
            "prob_hold"  : round(prob_hold * 100, 2),
            "confidence" : confidence,
            "conf_emoji" : conf_emoji,
            "keputusan"  : keputusan,
            "n_sinyal"   : len(sinyal_aktif),
            "detail"     : detail
        }

    def buat_sinyal_list(self, rsi, macd_up, macd_down,
                         bb_bawah, bb_atas, ichi_bullish,
                         vol_tinggi, bull_div, ml_pred,
                         ml_conf, fear_score, funding_rate,
                         btc_dom) -> list:
        """
        Konversi semua indikator menjadi list sinyal aktif
        """
        sinyal = []

        # ── RSI ──
        if rsi < 30:
            sinyal.append("rsi_oversold")
        elif rsi > 70:
            sinyal.append("rsi_overbought")

        # ── MACD ──
        if macd_up:
            sinyal.append("macd_up")
        if macd_down:
            sinyal.append("macd_down")

        # ── Bollinger Bands ──
        if bb_bawah:
            sinyal.append("bb_bawah")
        if bb_atas:
            sinyal.append("bb_atas")

        # ── Ichimoku ──
        if ichi_bullish:
            sinyal.append("ichimoku_bullish")

        # ── Volume ──
        if vol_tinggi:
            sinyal.append("volume_tinggi")

        # ── Divergence ──
        if bull_div:
            sinyal.append("bull_divergence")

        # ── Machine Learning ──
        if ml_pred == "BUY":
            if ml_conf >= 75:
                sinyal.append("ml_buy_high")
            elif ml_conf >= 55:
                sinyal.append("ml_buy_medium")
        else:
            sinyal.append("ml_hold")

        # ── Fear & Greed ──
        if fear_score <= 25:
            sinyal.append("fear_extreme")
        elif fear_score <= 45:
            sinyal.append("fear_normal")
        elif fear_score >= 75:
            sinyal.append("greed_extreme")

        # ── Funding Rate ──
        if funding_rate < -0.01:
            sinyal.append("funding_negatif")
        elif funding_rate > 0.01:
            sinyal.append("funding_positif")

        # ── BTC Dominance ──
        if btc_dom > 55:
            sinyal.append("btc_dominan")

        return sinyal

    def adaptive_update(self, sinyal_aktif, hasil_nyata):
        """
        Update likelihood berdasarkan hasil trading nyata
        Membuat model semakin akurat seiring waktu

        Args:
            sinyal_aktif : sinyal yang aktif saat entry
            hasil_nyata  : "profit" atau "loss"
        """
        learning_rate = 0.05  # Seberapa cepat model belajar

        for sinyal in sinyal_aktif:
            if sinyal in self.likelihood:
                if hasil_nyata == "profit":
                    # Tingkatkan likelihood buy untuk sinyal ini
                    self.likelihood[sinyal]["buy"] = min(
                        0.95,
                        self.likelihood[sinyal]["buy"] + learning_rate
                    )
                    self.likelihood[sinyal]["hold"] = max(
                        0.05,
                        self.likelihood[sinyal]["hold"] - learning_rate
                    )
                else:
                    # Turunkan likelihood buy
                    self.likelihood[sinyal]["buy"] = max(
                        0.05,
                        self.likelihood[sinyal]["buy"] - learning_rate
                    )
                    self.likelihood[sinyal]["hold"] = min(
                        0.95,
                        self.likelihood[sinyal]["hold"] + learning_rate
                    )

        # Simpan riwayat
        self.riwayat.append({
            "sinyal" : sinyal_aktif,
            "hasil"  : hasil_nyata
        })

        # Simpan model
        self.simpan_model()

    def simpan_model(self):
        with open("bayesian_model.json", "w") as f:
            json.dump({
                "likelihood" : self.likelihood,
                "prior_buy"  : self.prior_buy,
                "riwayat"    : self.riwayat[-100:]
            }, f, indent=2)

    def load_model(self):
        if os.path.exists("bayesian_model.json"):
            with open("bayesian_model.json", "r") as f:
                data = json.load(f)
                self.likelihood = data.get("likelihood", self.likelihood)
                self.prior_buy  = data.get("prior_buy", self.prior_buy)
                self.riwayat    = data.get("riwayat", [])
            print("  🧠 Bayesian Model dimuat!")
            return True
        return False


# ── TEST ──────────────────────────────────────
if __name__ == "__main__":
    print("=" * 55)
    print("   BAYESIAN MODEL TEST")
    print("=" * 55)

    model = BayesianTradingModel()

    # Simulasi kondisi pasar saat ini
    print("\n📊 Test Skenario 1: Kondisi BUY Kuat")
    sinyal = model.buat_sinyal_list(
        rsi=28, macd_up=True, macd_down=False,
        bb_bawah=True, bb_atas=False,
        ichi_bullish=True, vol_tinggi=True,
        bull_div=True, ml_pred="BUY", ml_conf=80,
        fear_score=22, funding_rate=-0.02,
        btc_dom=57
    )
    hasil = model.hitung_probabilitas(sinyal)
    print(f"  Sinyal aktif  : {len(sinyal)} sinyal")
    print(f"  P(BUY)        : {hasil['prob_buy']}%")
    print(f"  P(HOLD)       : {hasil['prob_hold']}%")
    print(f"  Confidence    : {hasil['conf_emoji']} {hasil['confidence']}")
    print(f"  Keputusan     : {hasil['keputusan']}")

    print("\n📊 Test Skenario 2: Kondisi HOLD")
    sinyal2 = model.buat_sinyal_list(
        rsi=52, macd_up=False, macd_down=False,
        bb_bawah=False, bb_atas=False,
        ichi_bullish=False, vol_tinggi=False,
        bull_div=False, ml_pred="HOLD", ml_conf=70,
        fear_score=50, funding_rate=0,
        btc_dom=50
    )
    hasil2 = model.hitung_probabilitas(sinyal2)
    print(f"  Sinyal aktif  : {len(sinyal2)} sinyal")
    print(f"  P(BUY)        : {hasil2['prob_buy']}%")
    print(f"  P(HOLD)       : {hasil2['prob_hold']}%")
    print(f"  Confidence    : {hasil2['conf_emoji']} {hasil2['confidence']}")
    print(f"  Keputusan     : {hasil2['keputusan']}")

    print("\n📊 Test Skenario 3: Kondisi SELL")
    sinyal3 = model.buat_sinyal_list(
        rsi=78, macd_up=False, macd_down=True,
        bb_bawah=False, bb_atas=True,
        ichi_bullish=False, vol_tinggi=True,
        bull_div=False, ml_pred="HOLD", ml_conf=85,
        fear_score=82, funding_rate=0.02,
        btc_dom=48
    )
    hasil3 = model.hitung_probabilitas(sinyal3)
    print(f"  Sinyal aktif  : {len(sinyal3)} sinyal")
    print(f"  P(BUY)        : {hasil3['prob_buy']}%")
    print(f"  P(HOLD)       : {hasil3['prob_hold']}%")
    print(f"  Confidence    : {hasil3['conf_emoji']} {hasil3['confidence']}")
    print(f"  Keputusan     : {hasil3['keputusan']}")