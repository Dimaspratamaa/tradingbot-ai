# ============================================
# GRID TRADING v1.0
# Strategi otomatis untuk sideways/ranging market
#
# Cara kerja:
#   1. Bot deteksi market CHOP via HMM
#   2. Buat grid: N level harga di atas & bawah harga saat ini
#   3. Setiap level bawah → pasang BUY order
#   4. Setiap BUY terisi → langsung pasang SELL di atasnya
#   5. Profit = spread antar grid (misal 0.5% per grid)
#
# Contoh grid BTCUSDT @ $65,000:
#   Level 5: $65,650 ← SELL
#   Level 4: $65,325 ← SELL
#   Level 3: $65,000 ← Harga sekarang
#   Level 2: $64,675 ← BUY
#   Level 1: $64,350 ← BUY
#
# Profit per siklus = grid_pct = 0.5%
# Jika harga bolak-balik 3x sehari = 1.5%/hari
# ============================================

import os
import json
import time
import pathlib

from datetime import datetime

BASE_DIR        = pathlib.Path(__file__).parent
GRID_STATE_FILE = BASE_DIR / "grid_state.json"
GRID_LOG_FILE   = BASE_DIR / "grid_trades.json"

# ── KONFIGURASI ───────────────────────────────
GRID_PCT        = 0.005   # jarak antar grid = 0.5%
GRID_LEVELS     = 4       # 4 level atas + 4 level bawah
GRID_SIZE_USD   = 20.0    # $20 per grid order
GRID_MAX_SIMBOL = 2       # max 2 koin yang di-grid sekaligus
GRID_MIN_VOLUME = 500_000_000   # min volume 24H $500M

# Regime yang cocok untuk grid
GRID_REGIMES    = ["CHOP", "VOLATILE"]
MIN_CONFIDENCE  = 0.40    # min confidence HMM untuk aktifkan grid


# ══════════════════════════════════════════════
# 1. DETEKSI KONDISI GRID
# ══════════════════════════════════════════════

def cek_kondisi_grid(symbol, client):
    """
    Cek apakah kondisi saat ini cocok untuk grid trading.
    Butuh: regime CHOP + volume cukup + Hurst rendah (mean-reverting).

    Return dict:
        cocok       : bool
        regime      : str
        hurst       : float
        alasan      : str
        harga       : float
    """
    try:
        # Ambil data 100 candle 1H
        klines = client.get_klines(
            symbol=symbol, interval="1h", limit=100)
        import pandas as pd, numpy as np
        df = pd.DataFrame(klines, columns=[
            "time","open","high","low","close","volume",
            "ct","qv","n","tb","tq","i"])
        for c in ["open","high","low","close","volume"]:
            df[c] = df[c].astype(float)

        close  = df["close"]
        volume = df["volume"]
        harga  = float(close.iloc[-1])

        # 1. Cek HMM regime
        from pattern_detector import deteksi_regime_hmm, hitung_hurst
        hmm     = deteksi_regime_hmm(close, volume)
        regime  = hmm.get("regime", "BULL")
        conf    = hmm.get("confidence", 0)

        # 2. Cek Hurst (mean-reverting = H < 0.45)
        returns = close.pct_change().dropna().values
        H, r    = hitung_hurst(returns)

        # 3. Cek volume 24H
        vol_24h = float(df["volume"].sum() * harga)

        # 4. Cek ATR (volatilitas sedang = cocok untuk grid)
        high = df["high"]
        low  = df["low"]
        tr   = pd.concat([
            high - low,
            (high - close.shift()).abs(),
            (low  - close.shift()).abs()
        ], axis=1).max(axis=1)
        atr_pct = float(tr.rolling(14).mean().iloc[-1] / harga * 100)

        # Keputusan
        cocok  = (
            regime in GRID_REGIMES and
            conf >= MIN_CONFIDENCE and
            H < 0.50 and       # mean-reverting
            vol_24h >= GRID_MIN_VOLUME and
            1.0 <= atr_pct <= 5.0  # tidak terlalu tenang, tidak terlalu volatile
        )

        alasan_list = []
        if regime not in GRID_REGIMES:
            alasan_list.append(f"Regime {regime} bukan CHOP/VOLATILE")
        if conf < MIN_CONFIDENCE:
            alasan_list.append(f"HMM confidence {conf:.0%} rendah")
        if H >= 0.50:
            alasan_list.append(f"Hurst {H:.2f} terlalu tinggi (trending)")
        if vol_24h < GRID_MIN_VOLUME:
            alasan_list.append(f"Volume {vol_24h/1e6:.0f}M terlalu rendah")
        if atr_pct < 1.0:
            alasan_list.append(f"ATR {atr_pct:.2f}% terlalu kecil")
        if atr_pct > 5.0:
            alasan_list.append(f"ATR {atr_pct:.2f}% terlalu besar")

        if cocok:
            alasan = (f"Grid cocok: {regime} H={H:.2f} "
                      f"ATR={atr_pct:.2f}%")
        else:
            alasan = " | ".join(alasan_list)

        return {
            "cocok"    : cocok,
            "regime"   : regime,
            "confidence": conf,
            "hurst"    : round(H, 3),
            "hurst_r"  : r,
            "atr_pct"  : round(atr_pct, 3),
            "vol_24h"  : round(vol_24h / 1e6, 1),
            "harga"    : harga,
            "alasan"   : alasan,
        }

    except Exception as e:
        return {
            "cocok" : False,
            "regime": "ERROR",
            "harga" : 0,
            "alasan": f"Error: {e}",
        }


# ══════════════════════════════════════════════
# 2. BUAT GRID
# ══════════════════════════════════════════════

def buat_grid(harga_tengah, n_level=GRID_LEVELS,
              grid_pct=GRID_PCT):
    """
    Hitung semua level harga untuk grid.

    Return list of dict:
        level     : int (negatif = bawah, positif = atas)
        harga     : float
        tipe      : "BUY" / "SELL"
        pct_dari_tengah: float
    """
    levels = []

    for i in range(1, n_level + 1):
        # Level bawah → BUY
        harga_beli = round(harga_tengah * (1 - grid_pct * i), 8)
        levels.append({
            "level"            : -i,
            "harga"            : harga_beli,
            "tipe"             : "BUY",
            "pct_dari_tengah"  : round(-grid_pct * i * 100, 3),
            "status"           : "PENDING",
            "order_id"         : None,
        })

        # Level atas → SELL (akan dipasang setelah BUY terisi)
        harga_jual = round(harga_tengah * (1 + grid_pct * i), 8)
        levels.append({
            "level"            : i,
            "harga"            : harga_jual,
            "tipe"             : "SELL",
            "pct_dari_tengah"  : round(grid_pct * i * 100, 3),
            "status"           : "WAITING",  # tunggu BUY terisi
            "order_id"         : None,
        })

    # Urutkan dari bawah ke atas
    levels.sort(key=lambda x: x["harga"])
    return levels


def print_grid(grid_state):
    """Print visualisasi grid ke terminal."""
    symbol   = grid_state.get("symbol", "?")
    harga_t  = grid_state.get("harga_tengah", 0)
    levels   = grid_state.get("levels", [])

    print(f"\n  Grid {symbol} (tengah: ${harga_t:,.4f})")
    print(f"  {'─'*45}")

    for lv in reversed(levels):  # dari atas ke bawah
        em = {
            "BUY"    : "🟢",
            "SELL"   : "🔴",
            "FILLED" : "✅",
        }.get(lv["status"], "⬜")

        bar  = f"{'▲' * abs(lv['level']):<6}"
        dist = f"{lv['pct_dari_tengah']:+.2f}%"

        print(f"  {em} ${lv['harga']:>12,.4f} {dist:>7} "
              f"{lv['tipe']:4} [{lv['status']:7}] {bar}")

    profit_per_grid = GRID_PCT * 2 * 100
    print(f"  {'─'*45}")
    print(f"  Profit/grid: ~{profit_per_grid:.2f}% | "
          f"Max levels: {GRID_LEVELS} | "
          f"Size: ${GRID_SIZE_USD}/order")


# ══════════════════════════════════════════════
# 3. STATE MANAGEMENT
# ══════════════════════════════════════════════

def load_grid_state():
    if GRID_STATE_FILE.exists():
        try:
            return json.loads(GRID_STATE_FILE.read_text())
        except Exception:
            pass
    return {"grids": {}, "total_profit": 0.0, "n_trades": 0}


def save_grid_state(state):
    try:
        GRID_STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception as e:
        print(f"  ⚠️  [GRID] Save error: {e}")


def get_grid_aktif():
    state = load_grid_state()
    return {s: g for s, g in state.get("grids", {}).items()
            if g.get("aktif")}


# ══════════════════════════════════════════════
# 4. BUKA & KELOLA GRID
# ══════════════════════════════════════════════

def mulai_grid(symbol, client, paper_mode=True,
               n_level=GRID_LEVELS, grid_pct=GRID_PCT,
               size_usd=GRID_SIZE_USD):
    """
    Mulai grid trading untuk satu simbol.
    Pasang BUY orders di semua level bawah.
    """
    # Cek kondisi
    kondisi = cek_kondisi_grid(symbol, client)
    if not kondisi["cocok"]:
        print(f"  ⚠️  [GRID] {symbol} tidak cocok: {kondisi['alasan']}")
        return None

    harga_tengah = kondisi["harga"]
    levels       = buat_grid(harga_tengah, n_level, grid_pct)

    grid_data = {
        "symbol"         : symbol,
        "harga_tengah"   : harga_tengah,
        "grid_pct"       : grid_pct,
        "n_level"        : n_level,
        "size_usd"       : size_usd,
        "levels"         : levels,
        "aktif"          : True,
        "paper_mode"     : paper_mode,
        "waktu_mulai"    : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "n_buy_filled"   : 0,
        "n_sell_filled"  : 0,
        "total_profit"   : 0.0,
        "regime_saat_buka": kondisi["regime"],
    }

    print(f"\n  🔲 [GRID] Mulai grid {symbol}")
    print(f"     Regime   : {kondisi['regime']} "
          f"(H={kondisi['hurst']:.2f})")
    print(f"     Harga    : ${harga_tengah:,.4f}")
    print(f"     Grid pct : {grid_pct*100:.2f}%")
    print(f"     Levels   : {n_level} atas + {n_level} bawah")
    print(f"     Total    : ${size_usd * n_level:.0f} modal")

    if not paper_mode and client:
        # Pasang BUY limit orders di semua level bawah
        for lv in levels:
            if lv["tipe"] != "BUY":
                continue
            try:
                # Hitung qty
                qty = round(size_usd / lv["harga"], 6)

                order = client.order_limit_buy(
                    symbol   = symbol,
                    price    = str(round(lv["harga"], 2)),
                    quantity = qty,
                )
                lv["order_id"] = order.get("orderId")
                lv["status"]   = "OPEN"
                print(f"     BUY order @ ${lv['harga']:,.4f}: "
                      f"ID={lv['order_id']}")
            except Exception as e:
                print(f"     ⚠️  BUY @ ${lv['harga']:,.4f}: {e}")
    else:
        # Paper mode: tandai semua BUY sebagai OPEN
        for lv in levels:
            if lv["tipe"] == "BUY":
                lv["status"] = "OPEN"
        print(f"     [PAPER] {n_level} BUY orders disimulasikan")

    # Simpan state
    state = load_grid_state()
    state["grids"][symbol] = grid_data
    save_grid_state(state)

    print_grid(grid_data)
    return grid_data


def cek_grid_fills(client, kirim_telegram=None, paper_mode=True):
    """
    Cek apakah ada grid order yang terisi.
    Dipanggil dari main loop setiap siklus.

    Paper mode: simulasi fill berdasarkan harga sekarang.
    Live mode: cek status order di Binance.
    """
    grids  = get_grid_aktif()
    if not grids:
        return

    state = load_grid_state()

    for symbol, grid in grids.items():
        try:
            # Ambil harga sekarang
            ticker = client.get_symbol_ticker(symbol=symbol)
            harga  = float(ticker["price"])
            levels = grid["levels"]

            changed = False

            for lv in levels:
                # ── Paper mode: cek apakah harga melewati level ──
                if paper_mode:
                    if (lv["tipe"] == "BUY" and
                            lv["status"] == "OPEN" and
                            harga <= lv["harga"]):
                        # BUY terisi
                        lv["status"]      = "FILLED"
                        lv["fill_price"]  = lv["harga"]
                        lv["fill_time"]   = datetime.now().strftime(
                            "%Y-%m-%d %H:%M:%S")
                        grid["n_buy_filled"] += 1
                        changed = True

                        # Aktifkan SELL di level atas
                        sell_harga = round(
                            lv["harga"] * (1 + grid["grid_pct"]), 8)
                        for sv in levels:
                            if (sv["tipe"] == "SELL" and
                                    abs(sv["harga"] - sell_harga) /
                                    sell_harga < 0.001):
                                sv["status"] = "OPEN"
                                break

                        profit_pct = grid["grid_pct"] * 100
                        print(f"  ✅ [GRID] {symbol} BUY filled "
                              f"@ ${lv['harga']:,.4f} "
                              f"→ SELL di ${sell_harga:,.4f} "
                              f"(+{profit_pct:.2f}%)")

                    elif (lv["tipe"] == "SELL" and
                          lv["status"] == "OPEN" and
                          harga >= lv["harga"]):
                        # SELL terisi
                        lv["status"]     = "FILLED"
                        lv["fill_price"] = lv["harga"]
                        lv["fill_time"]  = datetime.now().strftime(
                            "%Y-%m-%d %H:%M:%S")

                        # Hitung profit
                        buy_harga    = lv["harga"] / (1 + grid["grid_pct"])
                        profit_usd   = grid["size_usd"] * grid["grid_pct"]
                        grid["n_sell_filled"] += 1
                        grid["total_profit"]  += profit_usd
                        state["total_profit"] = round(
                            state.get("total_profit", 0) + profit_usd, 4)
                        state["n_trades"]     = state.get("n_trades", 0) + 1
                        changed = True

                        print(f"  💰 [GRID] {symbol} SELL filled "
                              f"@ ${lv['harga']:,.4f} "
                              f"+${profit_usd:.4f}")

                        # Reset BUY di level ini untuk siklus berikutnya
                        for bv in levels:
                            if (bv["tipe"] == "BUY" and
                                    bv["status"] == "FILLED" and
                                    abs(bv["harga"] -
                                        lv["harga"] / (1 + grid["grid_pct"])) /
                                    lv["harga"] < 0.002):
                                bv["status"] = "OPEN"
                                break

                        if kirim_telegram:
                            total_p = grid["total_profit"]
                            kirim_telegram(
                                f"💰 <b>Grid Profit — {symbol}</b>\n"
                                f"Sell @ ${lv['harga']:,.4f}\n"
                                f"Profit : +${profit_usd:.4f} "
                                f"({grid['grid_pct']*100:.2f}%)\n"
                                f"Total  : +${total_p:.4f}\n"
                                f"Trades : {grid['n_sell_filled']}"
                            )

                else:
                    # Live mode: cek order status di Binance
                    if lv.get("order_id") and lv["status"] == "OPEN":
                        try:
                            order = client.get_order(
                                symbol=symbol,
                                orderId=lv["order_id"])
                            if order["status"] == "FILLED":
                                lv["status"]     = "FILLED"
                                lv["fill_price"] = float(order["price"])
                                changed          = True
                        except Exception:
                            pass

            if changed:
                state["grids"][symbol] = grid
                save_grid_state(state)

        except Exception as e:
            print(f"  ⚠️  [GRID] Cek fills {symbol}: {e}")


def hentikan_grid(symbol, client, paper_mode=True):
    """Hentikan grid dan cancel semua open orders."""
    state = load_grid_state()
    grids = state.get("grids", {})

    if symbol not in grids:
        print(f"  ⚠️  [GRID] {symbol} tidak ada grid aktif")
        return False

    grid = grids[symbol]

    if not paper_mode and client:
        # Cancel semua open orders
        for lv in grid.get("levels", []):
            if lv.get("order_id") and lv["status"] == "OPEN":
                try:
                    client.cancel_order(
                        symbol=symbol, orderId=lv["order_id"])
                    print(f"  ❌ [GRID] Cancel order "
                          f"@ ${lv['harga']:,.4f}")
                except Exception as e:
                    print(f"  ⚠️  Cancel error: {e}")

    grid["aktif"]          = False
    grid["waktu_henti"]    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    state["grids"][symbol] = grid
    save_grid_state(state)

    profit = grid.get("total_profit", 0)
    n_sell = grid.get("n_sell_filled", 0)
    print(f"  🔲 [GRID] {symbol} dihentikan | "
          f"Trades: {n_sell} | Profit: +${profit:.4f}")
    return True


# ══════════════════════════════════════════════
# 5. AUTO SWITCH — Deteksi regime & aktifkan grid
# ══════════════════════════════════════════════

_last_regime_check = 0
REGIME_CHECK_INTERVAL = 1800  # cek regime setiap 30 menit


def auto_switch_grid(koin_list, client, kirim_telegram=None,
                     paper_mode=True):
    """
    Auto-deteksi regime dan aktifkan/nonaktifkan grid.
    Dipanggil dari main loop setiap 30 menit.

    Logic:
    - Jika koin di CHOP → aktifkan grid
    - Jika koin trending (BULL/BEAR) → hentikan grid
    """
    global _last_regime_check
    now = time.time()

    if now - _last_regime_check < REGIME_CHECK_INTERVAL:
        return

    _last_regime_check = now

    state        = load_grid_state()
    grids_aktif  = {s for s, g in state.get("grids", {}).items()
                    if g.get("aktif")}
    n_grid_aktif = len(grids_aktif)

    print(f"\n  🔲 [GRID] Auto-check regime "
          f"({len(koin_list)} koin)...")

    for symbol in koin_list[:5]:
        try:
            kondisi = cek_kondisi_grid(symbol, client)
            regime  = kondisi.get("regime", "BULL")
            cocok   = kondisi.get("cocok", False)

            if symbol in grids_aktif:
                # Grid sudah aktif — cek apakah perlu dihentikan
                if regime in ["BULL", "BEAR"]:
                    print(f"  🔄 [GRID] {symbol} trending ({regime})"
                          f" → hentikan grid")
                    hentikan_grid(symbol, client, paper_mode)
                    grids_aktif.discard(symbol)
                    n_grid_aktif -= 1

                    if kirim_telegram:
                        kirim_telegram(
                            f"🔄 <b>Grid Dinonaktifkan — {symbol}</b>\n"
                            f"Regime berubah ke {regime}\n"
                            f"Bot beralih ke trend-following mode"
                        )
            else:
                # Grid belum aktif — cek apakah perlu diaktifkan
                if (cocok and
                        n_grid_aktif < GRID_MAX_SIMBOL):
                    print(f"  ✅ [GRID] {symbol} CHOP → aktifkan grid")
                    result = mulai_grid(
                        symbol, client, paper_mode)
                    if result:
                        n_grid_aktif += 1
                        grids_aktif.add(symbol)

                        if kirim_telegram:
                            kirim_telegram(
                                f"🔲 <b>Grid Diaktifkan — {symbol}</b>\n"
                                f"Regime : {regime} "
                                f"(H={kondisi['hurst']:.2f})\n"
                                f"Grid   : {GRID_LEVELS} level × "
                                f"{GRID_PCT*100:.1f}%\n"
                                f"Size   : ${GRID_SIZE_USD}/order\n"
                                f"{'📝 PAPER' if paper_mode else '🔴 LIVE'}"
                            )

        except Exception as e:
            print(f"  ⚠️  [GRID] Auto-switch {symbol}: {e}")


# ══════════════════════════════════════════════
# 6. FORMAT LAPORAN TELEGRAM
# ══════════════════════════════════════════════

def format_grid_laporan():
    """Format laporan grid untuk /grid command."""
    state   = load_grid_state()
    grids   = state.get("grids", {})
    aktif   = {s: g for s, g in grids.items() if g.get("aktif")}
    total_p = state.get("total_profit", 0)
    n_trade = state.get("n_trades", 0)

    teks = (
        f"🔲 <b>Grid Trading Status</b>\n"
        f"{'─'*26}\n"
        f"Grid aktif : {len(aktif)}/{GRID_MAX_SIMBOL}\n"
        f"Total trade: {n_trade}\n"
        f"Total profit: +${total_p:.4f}\n\n"
    )

    if aktif:
        for sym, g in aktif.items():
            levels  = g.get("levels", [])
            n_open  = sum(1 for lv in levels
                          if lv["status"] == "OPEN")
            n_fill  = sum(1 for lv in levels
                          if lv["status"] == "FILLED")
            profit  = g.get("total_profit", 0)
            n_sell  = g.get("n_sell_filled", 0)
            regime  = g.get("regime_saat_buka", "?")
            mode    = "📝 PAPER" if g.get("paper_mode") else "🔴 LIVE"

            teks += (
                f"<b>{sym}</b> {mode}\n"
                f"  Regime  : {regime}\n"
                f"  Open    : {n_open} orders\n"
                f"  Filled  : {n_fill} orders\n"
                f"  Trades  : {n_sell}\n"
                f"  Profit  : +${profit:.4f}\n\n"
            )
    else:
        teks += "Tidak ada grid aktif saat ini.\n"
        teks += "Grid akan aktif otomatis saat market CHOP."

    return teks