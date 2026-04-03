# ============================================
# FUTURES TRADING ENGINE v1.0
# Long & Short dengan leverage 5x
# ============================================

from binance.client import Client
from binance.exceptions import BinanceAPIException
import time
import json
import os

# ── KONFIGURASI FUTURES ───────────────────────
LEVERAGE           = 5          # 5x leverage
MARGIN_TYPE        = "ISOLATED" # ISOLATED lebih aman dari CROSS
FUTURES_USDT       = 100.0      # Modal per posisi futures
MAX_POSISI_FUTURES = 2          # Maksimal 2 posisi futures aktif

# Threshold skor untuk futures
MIN_SKOR_LONG      = 8   # Butuh skor lebih tinggi untuk futures
MIN_SKOR_SHORT     = 7   # Short bisa dengan skor lebih rendah

# ── POSISI FUTURES AKTIF ─────────────────────
# Format: {"BTCUSDT": {"side": "LONG", "entry": ..., ...}}
posisi_futures = {}

# ══════════════════════════════════════════════
# INISIALISASI FUTURES
# ══════════════════════════════════════════════

def init_futures(client, symbol):
    """Setup leverage dan margin type untuk symbol"""
    try:
        # Set leverage
        client.futures_change_leverage(
            symbol=symbol,
            leverage=LEVERAGE
        )
        # Set margin type ke ISOLATED
        try:
            client.futures_change_margin_type(
                symbol=symbol,
                marginType=MARGIN_TYPE
            )
        except BinanceAPIException as e:
            # Error "No need to change" = sudah ISOLATED
            if "No need to change" in str(e):
                pass
            else:
                print(f"  ⚠️  Margin type error {symbol}: {e}")
        return True
    except Exception as e:
        print(f"  ⚠️  Init futures {symbol} error: {e}")
        return False

def cek_saldo_futures(client):
    """Cek saldo USDT di akun futures"""
    try:
        akun = client.futures_account()
        for aset in akun["assets"]:
            if aset["asset"] == "USDT":
                return float(aset["availableBalance"])
        return 0.0
    except Exception as e:
        print(f"  ⚠️  Gagal cek saldo futures: {e}")
        return 0.0

# ══════════════════════════════════════════════
# HITUNG QUANTITY FUTURES
# ══════════════════════════════════════════════

def hitung_qty_futures(symbol, harga, client):
    """
    Hitung quantity untuk futures berdasarkan modal & leverage.
    Modal $100 x 5x leverage = kontrol $500 worth of crypto.
    """
    try:
        # Dapatkan precision dari exchange info
        info = client.futures_exchange_info()
        for s in info["symbols"]:
            if s["symbol"] == symbol:
                for f in s["filters"]:
                    if f["filterType"] == "LOT_SIZE":
                        step = float(f["stepSize"])
                        notional = FUTURES_USDT * LEVERAGE
                        qty = notional / harga
                        # Bulatkan ke step size
                        qty = round(qty - (qty % step), 8)
                        return qty
    except:
        pass

    # Fallback manual
    notional = FUTURES_USDT * LEVERAGE
    qty      = notional / harga
    if harga > 10000:  return round(qty, 3)
    elif harga > 100:  return round(qty, 2)
    elif harga > 1:    return round(qty, 1)
    else:              return round(qty, 0)

# ══════════════════════════════════════════════
# BUKA POSISI FUTURES
# ══════════════════════════════════════════════

def buka_long(client, symbol, harga, atr, skor, detail_str, kirim_telegram):
    """Buka posisi LONG futures"""
    waktu = time.strftime("%Y-%m-%d %H:%M:%S")

    if symbol in posisi_futures and posisi_futures[symbol].get("aktif"):
        print(f"  ⏭️  [{symbol}] Sudah ada posisi futures aktif")
        return False

    if len([p for p in posisi_futures.values() if p.get("aktif")]) >= MAX_POSISI_FUTURES:
        print(f"  ✋ Posisi futures penuh ({MAX_POSISI_FUTURES})")
        return False

    # Setup leverage
    if not init_futures(client, symbol):
        return False

    qty    = hitung_qty_futures(symbol, harga, client)
    sl     = harga - (atr * 1.5)        # SL 1.5x ATR
    tp     = harga + (atr * 4.0)        # TP lebih jauh karena leverage
    sl_pct = ((harga - sl) / harga) * 100
    tp_pct = ((tp - harga) / harga) * 100

    # Dengan 5x leverage, P/L dikalikan 5
    sl_lev = sl_pct * LEVERAGE
    tp_lev = tp_pct * LEVERAGE

    print(f"\n  ⚡ [{symbol}] FUTURES LONG! Qty:{qty} Lev:{LEVERAGE}x")

    if is_paper_mode():
        ok = paper_buka_futures(symbol, "LONG", harga, qty, sl, tp, LEVERAGE, detail_str)
        if not ok:
            return False
    else:
        try:
            client.futures_create_order(symbol=symbol, side="BUY", type="MARKET", quantity=qty)
            client.futures_create_order(symbol=symbol, side="SELL", type="TAKE_PROFIT_MARKET",
                stopPrice=round(tp, 4), closePosition=True, timeInForce="GTE_GTC")
            client.futures_create_order(symbol=symbol, side="SELL", type="STOP_MARKET",
                stopPrice=round(sl, 4), closePosition=True, timeInForce="GTE_GTC")
        except Exception as e:
            print(f"  ⚠️  Gagal buka LONG {symbol}: {e}")
            return False

    posisi_futures[symbol] = {
        "aktif"          : True,
        "side"           : "LONG",
        "entry"          : harga,
        "harga_tertinggi": harga,
        "stop_loss"      : sl,
        "take_profit"    : tp,
        "qty"            : qty,
        "atr"            : atr,
        "leverage"       : LEVERAGE,
        "modal"          : FUTURES_USDT,
        "waktu_beli"     : waktu,
        "trailing_aktif" : False,
    }

    kirim_telegram(
        f"⚡ <b>FUTURES LONG - {symbol}</b>\n"
        f"⭐ Skor   : <b>{skor}</b>\n"
        f"🔢 Leverage: <b>{LEVERAGE}x</b>\n"
        f"💰 Modal  : ${FUTURES_USDT} → Kontrol ${FUTURES_USDT*LEVERAGE:,.0f}\n\n"
        f"📈 Entry  : <b>${harga:,.4f}</b>\n"
        f"🔢 Qty    : {qty}\n"
        f"🛑 SL     : <b>${sl:,.4f}</b> (-{sl_pct:.1f}% / -{sl_lev:.1f}% lev)\n"
        f"🎯 TP     : <b>${tp:,.4f}</b> (+{tp_pct:.1f}% / +{tp_lev:.1f}% lev)\n\n"
        f"✅ {detail_str}\n🕐 {waktu}"
    )
    return True

def buka_short(client, symbol, harga, atr, skor, detail_str, kirim_telegram):
    """Buka posisi SHORT futures"""
    waktu = time.strftime("%Y-%m-%d %H:%M:%S")

    if symbol in posisi_futures and posisi_futures[symbol].get("aktif"):
        print(f"  ⏭️  [{symbol}] Sudah ada posisi futures aktif")
        return False

    if len([p for p in posisi_futures.values() if p.get("aktif")]) >= MAX_POSISI_FUTURES:
        print(f"  ✋ Posisi futures penuh ({MAX_POSISI_FUTURES})")
        return False

    if not init_futures(client, symbol):
        return False

    qty    = hitung_qty_futures(symbol, harga, client)
    sl     = harga + (atr * 1.5)        # SL di atas entry untuk short
    tp     = harga - (atr * 4.0)        # TP di bawah entry
    sl_pct = ((sl - harga) / harga) * 100
    tp_pct = ((harga - tp) / harga) * 100
    sl_lev = sl_pct * LEVERAGE
    tp_lev = tp_pct * LEVERAGE

    print(f"\n  📉 [{symbol}] FUTURES SHORT! Qty:{qty} Lev:{LEVERAGE}x")

    if is_paper_mode():
        ok = paper_buka_futures(symbol, "SHORT", harga, qty, sl, tp, LEVERAGE, detail_str)
        if not ok:
            return False
    else:
        try:
            client.futures_create_order(symbol=symbol, side="SELL", type="MARKET", quantity=qty)
            client.futures_create_order(symbol=symbol, side="BUY", type="TAKE_PROFIT_MARKET",
                stopPrice=round(tp, 4), closePosition=True, timeInForce="GTE_GTC")
            client.futures_create_order(symbol=symbol, side="BUY", type="STOP_MARKET",
                stopPrice=round(sl, 4), closePosition=True, timeInForce="GTE_GTC")
        except Exception as e:
            print(f"  ⚠️  Gagal buka SHORT {symbol}: {e}")
            return False

    posisi_futures[symbol] = {
        "aktif"         : True,
        "side"          : "SHORT",
        "entry"         : harga,
        "harga_terendah": harga,
        "stop_loss"     : sl,
        "take_profit"   : tp,
        "qty"           : qty,
        "atr"           : atr,
        "leverage"      : LEVERAGE,
        "modal"         : FUTURES_USDT,
        "waktu_beli"    : waktu,
        "trailing_aktif": False,
    }

    kirim_telegram(
        f"📉 <b>FUTURES SHORT - {symbol}</b>\n"
        f"⭐ Skor   : <b>{skor}</b>\n"
        f"🔢 Leverage: <b>{LEVERAGE}x</b>\n"
        f"💰 Modal  : ${FUTURES_USDT} → Kontrol ${FUTURES_USDT*LEVERAGE:,.0f}\n\n"
        f"📉 Entry  : <b>${harga:,.4f}</b>\n"
        f"🔢 Qty    : {qty}\n"
        f"🛑 SL     : <b>${sl:,.4f}</b> (+{sl_pct:.1f}% / +{sl_lev:.1f}% lev)\n"
        f"🎯 TP     : <b>${tp:,.4f}</b> (-{tp_pct:.1f}% / -{tp_lev:.1f}% lev)\n\n"
        f"✅ {detail_str}\n🕐 {waktu}"
    )
    return True

# ══════════════════════════════════════════════
# CEK & KELOLA POSISI FUTURES
# ══════════════════════════════════════════════

def update_trailing_futures(symbol, harga_skrng):
    """Trailing stop untuk futures"""
    if symbol not in posisi_futures:
        return False
    pos = posisi_futures[symbol]
    if not pos.get("aktif"):
        return False

    side = pos["side"]

    if side == "LONG":
        profit_pct = ((harga_skrng - pos["entry"]) / pos["entry"]) * 100
        harga_tinggi = pos.get("harga_tertinggi", pos["entry"])
        if harga_skrng > harga_tinggi:
            posisi_futures[symbol]["harga_tertinggi"] = harga_skrng
            harga_tinggi = harga_skrng
        # Aktifkan trailing setelah +1% (lebih sensitif di futures)
        if not pos.get("trailing_aktif") and profit_pct >= 1.0:
            posisi_futures[symbol]["trailing_aktif"] = True
            print(f"  🔄 [{symbol}] Futures Trailing AKTIF! +{profit_pct:.2f}%")
        if pos.get("trailing_aktif"):
            sl_baru = harga_tinggi * 0.99  # 1% di bawah tertinggi
            if sl_baru > pos["stop_loss"]:
                posisi_futures[symbol]["stop_loss"] = sl_baru
                return True

    elif side == "SHORT":
        profit_pct = ((pos["entry"] - harga_skrng) / pos["entry"]) * 100
        harga_rendah = pos.get("harga_terendah", pos["entry"])
        if harga_skrng < harga_rendah:
            posisi_futures[symbol]["harga_terendah"] = harga_skrng
            harga_rendah = harga_skrng
        if not pos.get("trailing_aktif") and profit_pct >= 1.0:
            posisi_futures[symbol]["trailing_aktif"] = True
            print(f"  🔄 [{symbol}] Futures Trailing AKTIF SHORT! +{profit_pct:.2f}%")
        if pos.get("trailing_aktif"):
            sl_baru = harga_rendah * 1.01  # 1% di atas terendah
            if sl_baru < pos["stop_loss"]:
                posisi_futures[symbol]["stop_loss"] = sl_baru
                return True
    return False

def cek_posisi_futures(client, kirim_telegram, simpan_transaksi):
    """Cek semua posisi futures aktif dan kelola SL/TP"""
    waktu = time.strftime("%Y-%m-%d %H:%M:%S")

    for symbol in list(posisi_futures.keys()):
        pos = posisi_futures[symbol]
        if not pos.get("aktif"):
            continue

        try:
            ticker = client.futures_symbol_ticker(symbol=symbol)
            harga  = float(ticker["price"])
        except Exception as e:
            print(f"  ⚠️  Gagal harga futures {symbol}: {e}")
            continue

        side       = pos["side"]
        entry      = pos["entry"]
        leverage   = pos["leverage"]
        trail      = " 🔄" if pos.get("trailing_aktif") else ""

        if side == "LONG":
            profit_pct     = ((harga - entry) / entry) * 100
            profit_lev     = profit_pct * leverage
            hit_tp         = harga >= pos["take_profit"]
            hit_sl         = harga <= pos["stop_loss"]
        else:  # SHORT
            profit_pct     = ((entry - harga) / entry) * 100
            profit_lev     = profit_pct * leverage
            hit_tp         = harga <= pos["take_profit"]
            hit_sl         = harga >= pos["stop_loss"]

        emoji_side = "⚡📈" if side == "LONG" else "⚡📉"
        print(f"  {emoji_side} {symbol} {side}: ${harga:,.4f} | "
              f"P/L:{profit_pct:+.2f}% ({profit_lev:+.1f}%lev){trail}")

        update_trailing_futures(symbol, harga)

        if hit_tp:
            print(f"  🎯 [{symbol}] FUTURES TAKE PROFIT {side}!")
            try:
                # Cancel semua order terbuka dulu
                client.futures_cancel_all_open_orders(symbol=symbol)
                # Close posisi
                close_side = "SELL" if side == "LONG" else "BUY"
                client.futures_create_order(
                    symbol=symbol, side=close_side,
                    type="MARKET", quantity=pos["qty"],
                    reduceOnly=True
                )
            except Exception as e:
                print(f"  ⚠️  Gagal close TP {symbol}: {e}")

            simpan_transaksi(symbol, entry, harga,
                             pos["waktu_beli"], waktu,
                             f"FUTURES_{side}_TP")
            profit_usd = FUTURES_USDT * (profit_lev / 100)
            kirim_telegram(
                f"🎯 <b>FUTURES TP! {side} - {symbol}</b>\n\n"
                f"📈 Entry : <b>${entry:,.4f}</b>\n"
                f"📈 Exit  : <b>${harga:,.4f}</b>\n"
                f"💰 P/L   : <b>+{profit_pct:.2f}%</b> "
                f"(+{profit_lev:.1f}% lev)\n"
                f"💵 Est. Profit: <b>+${profit_usd:.2f}</b> ✅\n"
                f"🕐 {waktu}"
            )
            posisi_futures[symbol]["aktif"] = False

        elif hit_sl:
            alasan = f"FUTURES_{side}_TRAILING" if pos.get("trailing_aktif") else f"FUTURES_{side}_SL"
            print(f"  🛑 [{symbol}] FUTURES SL {side}!")
            try:
                client.futures_cancel_all_open_orders(symbol=symbol)
                close_side = "SELL" if side == "LONG" else "BUY"
                client.futures_create_order(
                    symbol=symbol, side=close_side,
                    type="MARKET", quantity=pos["qty"],
                    reduceOnly=True
                )
            except Exception as e:
                print(f"  ⚠️  Gagal close SL {symbol}: {e}")

            simpan_transaksi(symbol, entry, harga,
                             pos["waktu_beli"], waktu, alasan)
            loss_usd = FUTURES_USDT * abs(profit_lev / 100)
            emoji    = "🔄" if pos.get("trailing_aktif") else "🛑"
            kirim_telegram(
                f"{emoji} <b>FUTURES SL! {side} - {symbol}</b>\n\n"
                f"📉 Entry : <b>${entry:,.4f}</b>\n"
                f"📉 Exit  : <b>${harga:,.4f}</b>\n"
                f"💸 P/L   : <b>{profit_pct:.2f}%</b> "
                f"({profit_lev:.1f}% lev)\n"
                f"💵 Est. Loss: <b>-${loss_usd:.2f}</b> ❌\n"
                f"🕐 {waktu}"
            )
            posisi_futures[symbol]["aktif"] = False

# ══════════════════════════════════════════════
# TENTUKAN MODE: LONG, SHORT, ATAU SKIP
# ══════════════════════════════════════════════

def tentukan_mode_futures(skor, ind, geo, mtf, ob):
    """
    Tentukan apakah buka LONG, SHORT, atau skip futures.

    Logika:
    - LONG  : skor tinggi + semua TF bullish + OB bullish
    - SHORT : geo/OB sangat negatif + trend bearish + spoof terdeteksi
    - SKIP  : kondisi tidak jelas

    Return: "LONG" | "SHORT" | "SKIP"
    """
    # ── Kondisi LONG ──
    kondisi_long = (
        skor >= MIN_SKOR_LONG and
        mtf["cukup_bullish"] and
        not ob["block_entry"] and
        ind["momentum"] > 0 and
        ind["ema_bull"]
    )

    # ── Kondisi SHORT ──
    # Short jika: market bearish secara teknikal + konfirmasi negatif
    kondisi_short = (
        skor <= -2 or  # Skor sangat negatif
        (
            geo["skor_sell"] >= 2 and          # Geo bearish
            ob["depth"]["sinyal"] in ["BEARISH", "BEARISH_KUAT"] and  # OB bearish
            not ind["ema_bull"] and             # Downtrend
            ind["rsi"] > 60                    # RSI belum oversold (masih ruang turun)
        ) or
        (
            ob["block_entry"] and              # Manipulasi terdeteksi
            ob["skor_sell"] >= 3 and           # OB sangat bearish
            not ind["ema_bull"]                # Downtrend
        )
    )

    if kondisi_long:
        return "LONG"
    elif kondisi_short:
        return "SHORT"
    else:
        return "SKIP"

# ── STATUS FUTURES ────────────────────────────
def print_status_futures():
    """Print semua posisi futures aktif"""
    aktif = [(s, p) for s, p in posisi_futures.items() if p.get("aktif")]
    if not aktif:
        print("  📭 Tidak ada posisi futures aktif")
        return
    print(f"  ⚡ Posisi futures: {len(aktif)}/{MAX_POSISI_FUTURES}")
    for symbol, pos in aktif:
        side  = pos["side"]
        entry = pos["entry"]
        trail = " 🔄" if pos.get("trailing_aktif") else ""
        emoji = "📈" if side == "LONG" else "📉"
        print(f"  {emoji} {symbol:12} {side} | "
              f"Entry:${entry:,.4f} | "
              f"SL:${pos['stop_loss']:,.4f} | "
              f"TP:${pos['take_profit']:,.4f}{trail}")