# ============================================
# STORAGE.PY v2 — SQLite + Atomic JSON
# 
# Fix #2: riwayat_trade.json → SQLite
#   - Tidak korup saat crash (WAL mode)
#   - Thread-safe built-in (check_same_thread=False + Lock)
#   - Query fleksibel (filter by symbol, date, dll)
#   - JSON state tetap atomic write (posisi_state.json)
# ============================================

import json, os, shutil, sqlite3, threading, time
from contextlib import contextmanager

# ── SQLite untuk riwayat trade ────────────────
_DB_PATH  = "riwayat_trade.db"
_db_lock  = threading.Lock()

def _get_conn():
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    # WAL mode: tidak corrupt saat crash, baca-tulis bisa paralel
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn

def init_db():
    """Buat tabel jika belum ada. Panggil sekali saat startup."""
    with _db_lock:
        conn = _get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS riwayat_trade (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol       TEXT    NOT NULL,
                harga_beli   REAL    NOT NULL,
                harga_jual   REAL    NOT NULL,
                profit_pct   REAL    NOT NULL,
                waktu_beli   TEXT    NOT NULL,
                waktu_jual   TEXT    NOT NULL,
                alasan       TEXT,
                created_at   TEXT    DEFAULT (datetime('now','localtime'))
            )
        """)
        # Index untuk query cepat per symbol / tanggal
        conn.execute("CREATE INDEX IF NOT EXISTS idx_symbol ON riwayat_trade(symbol)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_waktu  ON riwayat_trade(waktu_jual)")
        conn.commit()
        conn.close()

        # Migrasi otomatis dari JSON lama jika ada
        _migrasi_dari_json()


def _migrasi_dari_json():
    """Pindahkan data lama dari riwayat_trade.json ke SQLite (sekali saja)."""
    json_path = "riwayat_trade.json"
    done_flag = "riwayat_trade.migrated"
    if not os.path.exists(json_path) or os.path.exists(done_flag):
        return
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list) or not data:
            return
        conn = _get_conn()
        conn.executemany("""
            INSERT OR IGNORE INTO riwayat_trade
              (symbol, harga_beli, harga_jual, profit_pct, waktu_beli, waktu_jual, alasan)
            VALUES (:symbol, :harga_beli, :harga_jual, :profit_pct, :waktu_beli, :waktu_jual, :alasan)
        """, data)
        conn.commit()
        conn.close()
        # Tandai sudah dimigrasi, backup JSON lama
        open(done_flag, "w").write(f"migrated {len(data)} rows")
        shutil.copy2(json_path, json_path + ".migrated_backup")
        print(f"  ✅ [storage] Migrasi {len(data)} trade dari JSON → SQLite")
    except Exception as e:
        print(f"  ⚠️  [storage] Migrasi JSON gagal (data lama tetap aman): {e}")


def simpan_trade(symbol, harga_beli, harga_jual, profit_pct,
                 waktu_beli, waktu_jual, alasan):
    """Simpan satu transaksi ke SQLite. Thread-safe."""
    with _db_lock:
        try:
            conn = _get_conn()
            conn.execute("""
                INSERT INTO riwayat_trade
                  (symbol, harga_beli, harga_jual, profit_pct, waktu_beli, waktu_jual, alasan)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (symbol, harga_beli, harga_jual, profit_pct,
                  waktu_beli, waktu_jual, alasan))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            print(f"  ⚠️  [storage] Gagal simpan trade {symbol}: {e}")
            return False


def get_riwayat(symbol=None, limit=500):
    """Ambil riwayat trade. Bisa filter by symbol."""
    with _db_lock:
        try:
            conn = _get_conn()
            if symbol:
                rows = conn.execute(
                    "SELECT * FROM riwayat_trade WHERE symbol=? ORDER BY id DESC LIMIT ?",
                    (symbol, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM riwayat_trade ORDER BY id DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            conn.close()
            return [dict(r) for r in rows]
        except Exception as e:
            print(f"  ⚠️  [storage] Gagal baca riwayat: {e}")
            return []


def get_statistik():
    """Statistik ringkas: total trade, win rate, total P/L."""
    with _db_lock:
        try:
            conn = _get_conn()
            row = conn.execute("""
                SELECT
                    COUNT(*)                                   AS total,
                    SUM(CASE WHEN profit_pct > 0 THEN 1 END)  AS menang,
                    SUM(profit_pct)                            AS total_pct,
                    AVG(profit_pct)                            AS avg_pct,
                    MAX(profit_pct)                            AS best,
                    MIN(profit_pct)                            AS worst
                FROM riwayat_trade
            """).fetchone()
            conn.close()
            d = dict(row)
            total = d["total"] or 1
            d["win_rate"] = round((d["menang"] or 0) / total * 100, 1)
            return d
        except Exception as e:
            print(f"  ⚠️  [storage] Gagal statistik: {e}")
            return {}


# ── Atomic JSON untuk state posisi (posisi_state.json) ────────────
_file_locks: dict[str, threading.Lock] = {}
_meta_lock = threading.Lock()

def _get_file_lock(path: str) -> threading.Lock:
    with _meta_lock:
        if path not in _file_locks:
            _file_locks[path] = threading.Lock()
        return _file_locks[path]


def simpan_json(path: str, data, backup: bool = True) -> bool:
    """Atomic write JSON. Tidak corrupt saat crash."""
    lock = _get_file_lock(path)
    with lock:
        try:
            json_str = json.dumps(data, indent=2, ensure_ascii=False)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(json_str)
                f.flush()
                os.fsync(f.fileno())
            if backup and os.path.exists(path):
                shutil.copy2(path, path + ".bak")
            os.replace(tmp, path)
            return True
        except Exception as e:
            print(f"  ⚠️  [storage] Gagal simpan {path}: {e}")
            try:
                if os.path.exists(path + ".tmp"):
                    os.remove(path + ".tmp")
            except Exception:
                pass
            return False


def muat_json(path: str, default=None):
    """Load JSON dengan auto-fallback ke .bak jika file utama rusak."""
    lock = _get_file_lock(path)
    with lock:
        for try_path in [path, path + ".bak"]:
            if not os.path.exists(try_path):
                continue
            try:
                with open(try_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if try_path != path:
                    print(f"  ⚠️  [storage] File utama rusak, recovery dari: {try_path}")
                return data
            except Exception as e:
                print(f"  ⚠️  [storage] Gagal baca {try_path}: {e}")
        return default if default is not None else {}
