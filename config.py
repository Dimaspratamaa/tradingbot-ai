# ============================================
# CONFIG.PY — Konstanta global terpusat
# Memecah circular import: risk_manager ↔ trading_bot
# Import modul ini dari mana saja tanpa circular dependency
# ============================================

# ── SAFEGUARD MODAL ───────────────────────────
MAX_MODAL_PER_TRADE    = 300.0   # Hard cap: tidak pernah order > $300 sekali
MIN_MODAL_PER_TRADE    = 15.0    # Hard floor: order minimal $15
MAX_PORTFOLIO_RISK_PCT = 0.05    # Max 5% saldo total per trade

# ── SCAN INTERVAL ─────────────────────────────
SCAN_FAST_INTERVAL     = 90      # detik — fast scan
SCAN_FULL_INTERVAL     = 300     # detik — full scan

# ── POSISI ────────────────────────────────────
PARTIAL_CLOSE_AKTIF    = True
PARTIAL_CLOSE_PROFIT   = 2.0
PARTIAL_CLOSE_PCT      = 0.5
SCALE_UP_AKTIF         = False
MAX_HOLD_JAM           = 72

# ── FILE STATE ────────────────────────────────
POSISI_STATE_FILE      = "posisi_state.json"
RIWAYAT_FILE           = "riwayat_trade.json"
