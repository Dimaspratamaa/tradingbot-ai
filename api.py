# ============================================================
# API.PY — FastAPI wrapper
# Jembatan antara N8N dan Python trading bot
# Endpoint: /health /status /scan /signal /positions /trade
# ============================================================

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import os, json, redis, psycopg2
from datetime import datetime

app = FastAPI(title="Trading Bot API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Koneksi Redis & Postgres ──────────────────────────────
def get_redis():
    return redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"))

def get_db():
    return psycopg2.connect(os.getenv("DATABASE_URL"))

# ── Models ────────────────────────────────────────────────
class ScanRequest(BaseModel):
    symbol: str
    timeframe: Optional[str] = "1h"

class ModeRequest(BaseModel):
    mode: str  # paper / live

# ── ENDPOINTS ─────────────────────────────────────────────

@app.get("/health")
def health_check():
    """N8N gunakan ini untuk cek apakah bot hidup"""
    return {"status": "ok", "timestamp": datetime.now().isoformat(), "version": "1.0.0"}

@app.get("/status")
def get_status():
    """Ringkasan kondisi bot saat ini"""
    try:
        r = get_redis()
        posisi_raw = r.get("posisi_aktif")
        posisi = json.loads(posisi_raw) if posisi_raw else {}
        mode = r.get("bot_mode") or b"paper"
        return {
            "status": "running",
            "mode": mode.decode() if isinstance(mode, bytes) else mode,
            "posisi_aktif": len(posisi),
            "symbols": list(posisi.keys()),
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"status": "error", "detail": str(e)}

@app.post("/scan")
def scan_symbol(req: ScanRequest):
    """
    N8N panggil ini tiap 90 detik.
    Return: skor + sinyal + alasan
    """
    try:
        from trading_bot import hitung_skor_koin
        hasil = hitung_skor_koin(req.symbol)
        skor = hasil.get("skor", 0)
        sinyal = "BUY" if skor >= 7 else ("WATCH" if skor >= 5 else "HOLD")

        # Cache hasil di Redis selama 60 detik
        r = get_redis()
        r.setex(f"signal:{req.symbol}", 60, json.dumps({"skor": skor, "sinyal": sinyal}))

        return {
            "symbol": req.symbol,
            "skor": round(skor, 2),
            "sinyal": sinyal,
            "detail": hasil,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/signal/{symbol}")
def get_last_signal(symbol: str):
    """Ambil sinyal terakhir dari cache Redis"""
    try:
        r = get_redis()
        cached = r.get(f"signal:{symbol}")
        if cached:
            return json.loads(cached)
        return {"symbol": symbol, "sinyal": "NO_DATA", "skor": 0}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/positions")
def get_positions():
    """Semua posisi aktif — N8N pakai untuk weekly report"""
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute("""
            SELECT symbol, side, harga_entry, modal, strategi, opened_at
            FROM posisi_aktif ORDER BY opened_at DESC
        """)
        rows = cur.fetchall()
        db.close()
        return {"posisi": [
            {"symbol": r[0], "side": r[1], "entry": float(r[2]),
             "modal": float(r[3]), "strategi": r[4], "since": str(r[5])}
            for r in rows
        ], "total": len(rows)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/performance")
def get_performance():
    """P&L summary — N8N pakai untuk daily/weekly report ke Discord"""
    try:
        db = get_db()
        cur = db.cursor()
        cur.execute("""
            SELECT
                COUNT(*)                              AS total_trade,
                COUNT(*) FILTER (WHERE pnl > 0)       AS win,
                COUNT(*) FILTER (WHERE pnl <= 0)      AS loss,
                COALESCE(SUM(pnl), 0)                 AS total_pnl,
                COALESCE(AVG(pnl_pct), 0)             AS avg_pnl_pct
            FROM riwayat_trade
            WHERE created_at >= NOW() - INTERVAL '30 days'
        """)
        row = cur.fetchone()
        db.close()
        total, win, loss, pnl, avg_pct = row
        win_rate = round((win / total * 100), 1) if total > 0 else 0
        return {
            "periode": "30 hari",
            "total_trade": total,
            "win": win, "loss": loss,
            "win_rate": win_rate,
            "total_pnl_usd": round(float(pnl), 2),
            "avg_pnl_pct": round(float(avg_pct), 2)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/mode")
def set_mode(req: ModeRequest):
    """Switch paper/live mode dari N8N atau manual"""
    if req.mode not in ["paper", "live"]:
        raise HTTPException(status_code=400, detail="Mode harus 'paper' atau 'live'")
    try:
        r = get_redis()
        r.set("bot_mode", req.mode)
        return {"status": "ok", "mode": req.mode, "timestamp": datetime.now().isoformat()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/pause")
def pause_bot():
    """N8N bisa pause bot saat market crash / circuit breaker"""
    r = get_redis()
    r.set("bot_paused", "1")
    return {"status": "paused", "timestamp": datetime.now().isoformat()}

@app.post("/resume")
def resume_bot():
    r = get_redis()
    r.delete("bot_paused")
    return {"status": "resumed", "timestamp": datetime.now().isoformat()}
