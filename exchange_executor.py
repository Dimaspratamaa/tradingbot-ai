# ============================================
# EXCHANGE EXECUTOR v1.0
# Eksekusi order di semua exchange sekaligus
#
# Exchange yang didukung:
#   1. Binance    — spot & futures (USDT)
#   2. Indodax    — spot IDR (Rupiah)
#   3. Tokocrypto — spot USDT (Indonesia)
#   4. Hyperliquid — DEX perpetual futures
#
# Fitur:
#   - Smart routing: pilih exchange terbaik otomatis
#   - Parallel execution: order di semua exchange bersamaan
#   - Unified position tracking
#   - Paper mode support
# ============================================

import os
import time
import json
import threading
import pathlib
from datetime import datetime

# Import exchange connectors
from multi_exchange import (
    indodax_place_order, indodax_get_balance,
    toko_place_order, toko_get_balance,
    hl_place_order, hl_get_balance, hl_get_positions,
    INDODAX_KEY, INDODAX_SECRET,
    TOKO_KEY, TOKO_SECRET,
    HL_WALLET, HL_SECRET,
    SYMBOL_MAP, get_idr_rate, idr_to_usd
)

# ── KONFIGURASI ───────────────────────────────
EXEC_LOG_FILE = pathlib.Path(__file__).parent / "execution_log.json"

# Modal per exchange (bisa diset via env var)
MODAL_INDODAX    = float(os.environ.get("MODAL_INDODAX_IDR",  500_000))   # IDR
MODAL_TOKO       = float(os.environ.get("MODAL_TOKO_USDT",    50.0))      # USDT
MODAL_HL         = float(os.environ.get("MODAL_HL_USDC",      50.0))      # USDC
MODAL_HL_LEVERAGE= int(os.environ.get("HL_LEVERAGE",          3))         # 3x leverage

# Exchange yang aktif (set ke "false" untuk disable)
INDODAX_AKTIF = os.environ.get("INDODAX_AKTIF", "true").lower() == "true"
TOKO_AKTIF    = os.environ.get("TOKO_AKTIF",    "true").lower() == "true"
HL_AKTIF      = os.environ.get("HL_AKTIF",      "true").lower() == "true"

# ── EXECUTION LOG ─────────────────────────────
_log_lock = threading.Lock()

def _log_eksekusi(exchange, symbol, side, qty, harga, status, detail=""):
    """Simpan log eksekusi order ke file JSON."""
    entry = {
        "waktu"   : datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "exchange": exchange,
        "symbol"  : symbol,
        "side"    : side,
        "qty"     : qty,
        "harga"   : harga,
        "status"  : status,
        "detail"  : detail,
    }
    with _log_lock:
        log = []
        if EXEC_LOG_FILE.exists():
            try:
                log = json.loads(EXEC_LOG_FILE.read_text())
            except Exception:
                pass
        log.append(entry)
        # Simpan max 500 entri terakhir
        EXEC_LOG_FILE.write_text(json.dumps(log[-500:], indent=2))

# ══════════════════════════════════════════════
# 1. CEK EXCHANGE YANG TERSEDIA
# ══════════════════════════════════════════════

def get_exchange_status():
    """
    Cek exchange mana yang aktif dan siap digunakan.
    Return dict: {exchange: {aktif, saldo, error}}
    """
    status = {}

    # Binance — selalu tersedia (main exchange)
    status["binance"] = {
        "aktif"  : True,
        "saldo"  : 0,
        "mata_uang": "USDT",
        "error"  : None
    }

    # Indodax
    if INDODAX_AKTIF and INDODAX_KEY and INDODAX_SECRET:
        try:
            bal = indodax_get_balance()
            idr = bal.get("idr", 0)
            status["indodax"] = {
                "aktif"    : idr > 10_000,  # minimal Rp 10.000
                "saldo"    : idr,
                "saldo_usd": idr_to_usd(idr),
                "mata_uang": "IDR",
                "error"    : None if idr > 0 else "Saldo nol atau key salah"
            }
        except Exception as e:
            status["indodax"] = {"aktif": False, "saldo": 0, "error": str(e)}
    else:
        status["indodax"] = {
            "aktif": False, "saldo": 0,
            "error": "Key tidak diisi" if not INDODAX_KEY else "Dinonaktifkan"
        }

    # Tokocrypto
    if TOKO_AKTIF and TOKO_KEY and TOKO_SECRET:
        try:
            bal = toko_get_balance()
            status["tokocrypto"] = {
                "aktif"    : bal > 5.0,
                "saldo"    : bal,
                "mata_uang": "USDT",
                "error"    : None if bal > 0 else "Saldo nol atau key salah"
            }
        except Exception as e:
            status["tokocrypto"] = {"aktif": False, "saldo": 0, "error": str(e)}
    else:
        status["tokocrypto"] = {
            "aktif": False, "saldo": 0,
            "error": "Key tidak diisi" if not TOKO_KEY else "Dinonaktifkan"
        }

    # Hyperliquid
    if HL_AKTIF and HL_WALLET and HL_SECRET:
        try:
            bal = hl_get_balance()
            status["hyperliquid"] = {
                "aktif"    : bal > 5.0,
                "saldo"    : bal,
                "mata_uang": "USDC",
                "error"    : None if bal > 0 else "Saldo nol"
            }
        except Exception as e:
            status["hyperliquid"] = {"aktif": False, "saldo": 0, "error": str(e)}
    else:
        status["hyperliquid"] = {
            "aktif": False, "saldo": 0,
            "error": "Wallet/Secret tidak diisi" if not HL_WALLET else "Dinonaktifkan"
        }

    return status

def print_exchange_status():
    """Print status semua exchange ke terminal."""
    status = get_exchange_status()
    print("\n  🌐 Status Exchange:")
    for ex, info in status.items():
        if info["aktif"]:
            saldo_str = (f"Rp{info['saldo']:,.0f}" if info.get("mata_uang") == "IDR"
                        else f"${info['saldo']:,.2f}")
            print(f"    ✅ {ex:12} | Saldo: {saldo_str}")
        else:
            print(f"    ❌ {ex:12} | {info.get('error','Tidak aktif')}")
    return status

# ══════════════════════════════════════════════
# 2. SMART ORDER ROUTING — pilih exchange terbaik
# ══════════════════════════════════════════════

def pilih_exchange_terbaik(symbol, side="BUY", skor=0):
    """
    Pilih exchange terbaik untuk eksekusi order.

    Logic:
    - Binance  : selalu jadi primary untuk aset utama
    - Tokocrypto: untuk koin yang tersedia + saldo cukup
    - Indodax  : untuk koin IDR + spread IDR bisa menguntungkan
    - Hyperliquid: untuk futures/leverage (skor tinggi)
    """
    sym_map   = SYMBOL_MAP.get(symbol, {})
    exchanges = []

    # Binance selalu tersedia
    exchanges.append(("binance", 10))  # prioritas tertinggi

    # Tokocrypto — jika simbol tersedia dan saldo cukup
    if (TOKO_AKTIF and TOKO_KEY and TOKO_SECRET and
            sym_map.get("toko")):
        try:
            bal = toko_get_balance()
            if bal >= MODAL_TOKO:
                exchanges.append(("tokocrypto", 7))
        except Exception:
            pass

    # Indodax — untuk spread IDR
    if (INDODAX_AKTIF and INDODAX_KEY and INDODAX_SECRET and
            sym_map.get("indodax")):
        try:
            bal = indodax_get_balance()
            if bal.get("idr", 0) >= MODAL_INDODAX:
                exchanges.append(("indodax", 6))
        except Exception:
            pass

    # Hyperliquid — hanya untuk leverage/futures dengan skor tinggi
    if (HL_AKTIF and HL_WALLET and HL_SECRET and
            sym_map.get("hl") and skor >= 9):
        try:
            bal = hl_get_balance()
            if bal >= MODAL_HL:
                exchanges.append(("hyperliquid", 8))
        except Exception:
            pass

    # Sort by prioritas
    exchanges.sort(key=lambda x: x[1], reverse=True)
    return [ex[0] for ex in exchanges]

# ══════════════════════════════════════════════
# 3. EKSEKUSI ORDER MULTI-EXCHANGE
# ══════════════════════════════════════════════

def eksekusi_beli_multi(binance_client, symbol, harga, qty_binance,
                         skor=0, kirim_telegram=None, paper_mode=False):
    """
    Eksekusi BUY order di semua exchange yang tersedia secara paralel.

    Args:
        binance_client : Binance client object
        symbol         : e.g. "BTCUSDT"
        harga          : harga entry
        qty_binance    : qty untuk Binance (sudah dihitung sesuai LOT_SIZE)
        skor           : skor sinyal (menentukan agresivitas)
        kirim_telegram : fungsi kirim notifikasi
        paper_mode     : jika True, tidak eksekusi nyata

    Returns:
        dict: hasil eksekusi per exchange
    """
    hasil    = {}
    threads  = []
    sym_map  = SYMBOL_MAP.get(symbol, {})
    waktu    = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _beli_binance():
        try:
            if paper_mode:
                hasil["binance"] = {"status": "PAPER", "qty": qty_binance}
                return
            resp = binance_client.order_market_buy(symbol=symbol, quantity=qty_binance)
            hasil["binance"] = {"status": "OK", "orderId": resp.get("orderId")}
            _log_eksekusi("binance", symbol, "BUY", qty_binance, harga, "OK")
            print(f"    ✅ Binance BUY {symbol} qty:{qty_binance}")
        except Exception as e:
            hasil["binance"] = {"status": "ERROR", "error": str(e)}
            _log_eksekusi("binance", symbol, "BUY", qty_binance, harga, "ERROR", str(e))
            print(f"    ❌ Binance BUY error: {e}")

    def _beli_toko():
        if not (TOKO_AKTIF and TOKO_KEY and sym_map.get("toko")):
            return
        try:
            toko_sym = sym_map["toko"]
            bal      = toko_get_balance()
            if bal < MODAL_TOKO:
                print(f"    ⚠️  Toko saldo kurang: ${bal:.2f}")
                return
            qty_toko = round(MODAL_TOKO / harga, 4)
            if paper_mode:
                hasil["tokocrypto"] = {"status": "PAPER", "qty": qty_toko}
                return
            resp = toko_place_order(toko_sym, "BUY", qty_toko)
            if resp.get("code") == 0:
                hasil["tokocrypto"] = {"status": "OK"}
                _log_eksekusi("tokocrypto", symbol, "BUY", qty_toko, harga, "OK")
                print(f"    ✅ Tokocrypto BUY {toko_sym} qty:{qty_toko}")
            else:
                err = resp.get("msg", str(resp))
                hasil["tokocrypto"] = {"status": "ERROR", "error": err}
                print(f"    ❌ Tokocrypto error: {err}")
        except Exception as e:
            hasil["tokocrypto"] = {"status": "ERROR", "error": str(e)}
            print(f"    ❌ Tokocrypto BUY error: {e}")

    def _beli_indodax():
        if not (INDODAX_AKTIF and INDODAX_KEY and sym_map.get("indodax")):
            return
        try:
            pair   = sym_map["indodax"]
            idr_rt = get_idr_rate()
            bal    = indodax_get_balance()
            idr_bal = bal.get("idr", 0)
            if idr_bal < MODAL_INDODAX:
                print(f"    ⚠️  Indodax saldo kurang: Rp{idr_bal:,.0f}")
                return
            harga_idr = harga * idr_rt
            if paper_mode:
                hasil["indodax"] = {"status": "PAPER", "modal_idr": MODAL_INDODAX}
                return
            resp = indodax_place_order(pair, "buy", harga_idr, MODAL_INDODAX)
            if resp.get("success") == 1:
                hasil["indodax"] = {"status": "OK"}
                _log_eksekusi("indodax", symbol, "BUY", MODAL_INDODAX, harga_idr, "OK")
                print(f"    ✅ Indodax BUY {pair} Rp{MODAL_INDODAX:,.0f}")
            else:
                err = resp.get("error", str(resp))
                hasil["indodax"] = {"status": "ERROR", "error": err}
                print(f"    ❌ Indodax error: {err}")
        except Exception as e:
            hasil["indodax"] = {"status": "ERROR", "error": str(e)}
            print(f"    ❌ Indodax BUY error: {e}")

    def _beli_hyperliquid():
        hl_coin = sym_map.get("hl")
        if not (HL_AKTIF and HL_WALLET and HL_SECRET and hl_coin and skor >= 9):
            return
        try:
            bal = hl_get_balance()
            if bal < MODAL_HL:
                print(f"    ⚠️  Hyperliquid saldo kurang: ${bal:.2f}")
                return
            sz = round(MODAL_HL * MODAL_HL_LEVERAGE / harga, 4)
            if paper_mode:
                hasil["hyperliquid"] = {"status": "PAPER", "sz": sz}
                return
            resp = hl_place_order(hl_coin, is_buy=True, sz=sz)
            if resp.get("status") == "ok":
                hasil["hyperliquid"] = {"status": "OK"}
                _log_eksekusi("hyperliquid", symbol, "LONG", sz, harga, "OK")
                print(f"    ✅ Hyperliquid LONG {hl_coin} sz:{sz} ({MODAL_HL_LEVERAGE}x)")
            else:
                err = str(resp.get("response", resp))[:80]
                hasil["hyperliquid"] = {"status": "ERROR", "error": err}
                print(f"    ❌ Hyperliquid error: {err}")
        except Exception as e:
            hasil["hyperliquid"] = {"status": "ERROR", "error": str(e)}
            print(f"    ❌ Hyperliquid LONG error: {e}")

    # Jalankan semua eksekusi secara paralel
    fns = [_beli_binance, _beli_toko, _beli_indodax, _beli_hyperliquid]
    threads = [threading.Thread(target=fn, daemon=True) for fn in fns]
    for t in threads: t.start()
    for t in threads: t.join(timeout=20)  # timeout 20 detik per exchange

    # Summary
    sukses = [ex for ex, r in hasil.items() if r.get("status") in ("OK", "PAPER")]
    gagal  = [ex for ex, r in hasil.items() if r.get("status") == "ERROR"]

    if kirim_telegram and hasil:
        mode_label = "📝[PAPER] " if paper_mode else ""
        teks = (
            f"🌐 <b>{mode_label}MULTI-EXCHANGE BUY — {symbol}</b>\n"
            f"💰 Harga: ${harga:,.4f} | Skor: {skor}\n\n"
        )
        for ex, r in hasil.items():
            emoji = "✅" if r["status"] in ("OK","PAPER") else "❌"
            teks += f"{emoji} {ex}: {r['status']}\n"
        teks += f"\n🕐 {waktu}"
        kirim_telegram(teks)

    return {"sukses": sukses, "gagal": gagal, "detail": hasil}


def eksekusi_jual_multi(binance_client, symbol, harga, qty_binance,
                         alasan="SELL", kirim_telegram=None, paper_mode=False):
    """
    Eksekusi SELL/CLOSE di semua exchange yang punya posisi terbuka.
    """
    hasil   = {}
    waktu   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sym_map = SYMBOL_MAP.get(symbol, {})

    def _jual_binance():
        try:
            if paper_mode:
                hasil["binance"] = {"status": "PAPER"}
                return
            resp = binance_client.order_market_sell(symbol=symbol, quantity=qty_binance)
            hasil["binance"] = {"status": "OK"}
            _log_eksekusi("binance", symbol, "SELL", qty_binance, harga, "OK", alasan)
            print(f"    ✅ Binance SELL {symbol}")
        except Exception as e:
            hasil["binance"] = {"status": "ERROR", "error": str(e)}
            print(f"    ❌ Binance SELL error: {e}")

    def _jual_toko():
        if not (TOKO_AKTIF and TOKO_KEY and sym_map.get("toko")):
            return
        try:
            toko_sym = sym_map["toko"]
            # Cek saldo coin di Toko
            qty_toko = round(MODAL_TOKO / harga, 4)
            if paper_mode:
                hasil["tokocrypto"] = {"status": "PAPER"}
                return
            resp = toko_place_order(toko_sym, "SELL", qty_toko)
            if resp.get("code") == 0:
                hasil["tokocrypto"] = {"status": "OK"}
                _log_eksekusi("tokocrypto", symbol, "SELL", qty_toko, harga, "OK")
                print(f"    ✅ Tokocrypto SELL {toko_sym}")
            else:
                hasil["tokocrypto"] = {"status": "ERROR", "error": resp.get("msg","")}
        except Exception as e:
            hasil["tokocrypto"] = {"status": "ERROR", "error": str(e)}

    def _tutup_hyperliquid():
        hl_coin = sym_map.get("hl")
        if not (HL_AKTIF and HL_WALLET and HL_SECRET and hl_coin):
            return
        try:
            posisi = hl_get_positions()
            pos = next((p for p in posisi if p.get("coin") == hl_coin), None)
            if not pos:
                return
            sz = abs(pos.get("size", 0))
            if paper_mode:
                hasil["hyperliquid"] = {"status": "PAPER"}
                return
            is_buy = pos["size"] < 0  # jika short, tutup dengan buy
            resp = hl_place_order(hl_coin, is_buy=is_buy, sz=sz)
            if resp.get("status") == "ok":
                hasil["hyperliquid"] = {"status": "OK"}
                _log_eksekusi("hyperliquid", symbol, "CLOSE", sz, harga, "OK")
                print(f"    ✅ Hyperliquid CLOSE {hl_coin}")
            else:
                hasil["hyperliquid"] = {"status": "ERROR"}
        except Exception as e:
            hasil["hyperliquid"] = {"status": "ERROR", "error": str(e)}

    threads = [
        threading.Thread(target=_jual_binance,       daemon=True),
        threading.Thread(target=_jual_toko,          daemon=True),
        threading.Thread(target=_tutup_hyperliquid,  daemon=True),
    ]
    for t in threads: t.start()
    for t in threads: t.join(timeout=20)

    return hasil

# ══════════════════════════════════════════════
# 4. CEK SALDO SEMUA EXCHANGE
# ══════════════════════════════════════════════

def get_total_portfolio(binance_client):
    """
    Hitung total nilai portfolio di semua exchange dalam USD.
    """
    total_usd = 0
    detail    = {}

    # Binance
    try:
        akun = binance_client.get_account()
        usdt = next((float(a["free"]) for a in akun["balances"]
                     if a["asset"] == "USDT"), 0)
        detail["binance"] = {"usdt": usdt, "usd": usdt}
        total_usd += usdt
    except Exception as e:
        detail["binance"] = {"error": str(e)}

    # Indodax
    if INDODAX_KEY:
        try:
            bal = indodax_get_balance()
            idr = bal.get("idr", 0)
            usd = idr_to_usd(idr)
            detail["indodax"] = {"idr": idr, "usd": usd}
            total_usd += usd
        except Exception:
            pass

    # Tokocrypto
    if TOKO_KEY:
        try:
            bal = toko_get_balance()
            detail["tokocrypto"] = {"usdt": bal, "usd": bal}
            total_usd += bal
        except Exception:
            pass

    # Hyperliquid
    if HL_WALLET:
        try:
            bal = hl_get_balance()
            detail["hyperliquid"] = {"usdc": bal, "usd": bal}
            total_usd += bal
        except Exception:
            pass

    return {"total_usd": total_usd, "detail": detail}


def format_portfolio_message(binance_client):
    """Generate pesan laporan portfolio untuk Telegram."""
    port = get_total_portfolio(binance_client)
    teks = "💼 <b>TOTAL PORTFOLIO</b>\n" + "─" * 28 + "\n"
    for ex, info in port["detail"].items():
        if "error" in info:
            teks += f"❌ {ex}: Error\n"
        elif ex == "indodax":
            teks += f"🏦 Indodax   : Rp{info['idr']:,.0f} (≈${info['usd']:.2f})\n"
        elif ex == "binance":
            teks += f"🟡 Binance   : ${info['usdt']:,.2f}\n"
        elif ex == "tokocrypto":
            teks += f"🔵 Tokocrypto: ${info['usdt']:,.2f}\n"
        elif ex == "hyperliquid":
            teks += f"🟣 Hyperliquid: ${info['usdc']:,.2f} USDC\n"
    teks += f"─" * 28 + f"\n💰 <b>Total: ${port['total_usd']:,.2f}</b>\n"
    teks += f"🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    return teks