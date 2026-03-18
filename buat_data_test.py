# Membuat data transaksi dummy untuk test grafik
import json

data_dummy = [
    {"harga_beli": 70000, "harga_jual": 72800, "profit_pct": 4.0,  "waktu_beli": "2024-03-01 08:00:00", "waktu_jual": "2024-03-01 20:00:00", "alasan": "TAKE_PROFIT"},
    {"harga_beli": 72800, "harga_jual": 71344, "profit_pct": -2.0, "waktu_beli": "2024-03-02 09:00:00", "waktu_jual": "2024-03-02 15:00:00", "alasan": "STOP_LOSS"},
    {"harga_beli": 71000, "harga_jual": 73840, "profit_pct": 4.0,  "waktu_beli": "2024-03-03 10:00:00", "waktu_jual": "2024-03-04 08:00:00", "alasan": "TAKE_PROFIT"},
    {"harga_beli": 73500, "harga_jual": 72030, "profit_pct": -2.0, "waktu_beli": "2024-03-05 11:00:00", "waktu_jual": "2024-03-05 18:00:00", "alasan": "STOP_LOSS"},
    {"harga_beli": 72000, "harga_jual": 74880, "profit_pct": 4.0,  "waktu_beli": "2024-03-06 09:00:00", "waktu_jual": "2024-03-07 10:00:00", "alasan": "TAKE_PROFIT"},
    {"harga_beli": 74500, "harga_jual": 77480, "profit_pct": 4.0,  "waktu_beli": "2024-03-08 08:00:00", "waktu_jual": "2024-03-09 12:00:00", "alasan": "TAKE_PROFIT"},
    {"harga_beli": 77000, "harga_jual": 75460, "profit_pct": -2.0, "waktu_beli": "2024-03-10 10:00:00", "waktu_jual": "2024-03-10 20:00:00", "alasan": "STOP_LOSS"},
    {"harga_beli": 75500, "harga_jual": 78520, "profit_pct": 4.0,  "waktu_beli": "2024-03-11 09:00:00", "waktu_jual": "2024-03-12 08:00:00", "alasan": "TAKE_PROFIT"},
    {"harga_beli": 78000, "harga_jual": 81120, "profit_pct": 4.0,  "waktu_beli": "2024-03-13 10:00:00", "waktu_jual": "2024-03-14 15:00:00", "alasan": "TAKE_PROFIT"},
    {"harga_beli": 81000, "harga_jual": 79380, "profit_pct": -2.0, "waktu_beli": "2024-03-15 09:00:00", "waktu_jual": "2024-03-15 22:00:00", "alasan": "STOP_LOSS"},
]

with open("riwayat_trade.json", "w") as f:
    json.dump(data_dummy, f, indent=2)

print("✅ Data dummy berhasil dibuat! (10 transaksi)")
print("   Sekarang jalankan: python lihat_grafik.py")