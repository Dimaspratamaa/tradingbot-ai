-- ============================================================
-- INIT.SQL — Inisialisasi database PostgreSQL
-- Dijalankan otomatis saat container postgres pertama kali start
-- ============================================================

-- Schema untuk N8N (agar tidak bentrok dengan tabel bot)
CREATE SCHEMA IF NOT EXISTS n8n;

-- Tabel riwayat trade
CREATE TABLE IF NOT EXISTS riwayat_trade (
    id            SERIAL PRIMARY KEY,
    symbol        VARCHAR(20)    NOT NULL,
    side          VARCHAR(10)    NOT NULL,  -- BUY / SELL
    harga_entry   NUMERIC(20,8),
    harga_exit    NUMERIC(20,8),
    qty           NUMERIC(20,8),
    modal         NUMERIC(20,2),
    pnl           NUMERIC(20,2),
    pnl_pct       NUMERIC(10,4),
    strategi      VARCHAR(50),
    mode          VARCHAR(10)    DEFAULT 'paper',
    alasan_exit   TEXT,
    created_at    TIMESTAMPTZ    DEFAULT NOW(),
    closed_at     TIMESTAMPTZ
);

-- Tabel posisi aktif
CREATE TABLE IF NOT EXISTS posisi_aktif (
    id            SERIAL PRIMARY KEY,
    symbol        VARCHAR(20)    NOT NULL UNIQUE,
    side          VARCHAR(10),
    harga_entry   NUMERIC(20,8),
    qty           NUMERIC(20,8),
    modal         NUMERIC(20,2),
    sl_price      NUMERIC(20,8),
    tp_price      NUMERIC(20,8),
    strategi      VARCHAR(50),
    mode          VARCHAR(10)    DEFAULT 'paper',
    opened_at     TIMESTAMPTZ    DEFAULT NOW(),
    updated_at    TIMESTAMPTZ    DEFAULT NOW()
);

-- Tabel log sinyal (semua sinyal, termasuk yang tidak dieksekusi)
CREATE TABLE IF NOT EXISTS signal_log (
    id            SERIAL PRIMARY KEY,
    symbol        VARCHAR(20),
    skor          NUMERIC(5,2),
    sinyal        VARCHAR(10),   -- BUY / HOLD / SELL
    alasan        TEXT,
    harga         NUMERIC(20,8),
    dieksekusi    BOOLEAN        DEFAULT FALSE,
    created_at    TIMESTAMPTZ    DEFAULT NOW()
);

-- Tabel performa harian
CREATE TABLE IF NOT EXISTS performa_harian (
    id            SERIAL PRIMARY KEY,
    tanggal       DATE           UNIQUE,
    total_trade   INT            DEFAULT 0,
    win           INT            DEFAULT 0,
    loss          INT            DEFAULT 0,
    pnl_total     NUMERIC(20,2)  DEFAULT 0,
    win_rate      NUMERIC(5,2),
    avg_rr        NUMERIC(5,2),
    created_at    TIMESTAMPTZ    DEFAULT NOW()
);

-- Index untuk query cepat
CREATE INDEX IF NOT EXISTS idx_riwayat_symbol    ON riwayat_trade(symbol);
CREATE INDEX IF NOT EXISTS idx_riwayat_created   ON riwayat_trade(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_signal_symbol     ON signal_log(symbol);
CREATE INDEX IF NOT EXISTS idx_signal_created    ON signal_log(created_at DESC);

-- Notifikasi sukses
DO $$ BEGIN
  RAISE NOTICE 'Database tradingbot berhasil diinisialisasi';
END $$;
