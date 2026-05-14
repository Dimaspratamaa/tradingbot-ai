# Panduan Deploy Trading Bot AI ke VPS

## Urutan Setup (ikuti step by step)

### Step 1 — Daftar VPS
- Buka hetzner.com → Cloud → New Server
- Pilih: Ubuntu 22.04 · CX22 (2 vCPU, 4GB RAM) · Region Frankfurt
- Simpan IP VPS yang diberikan

### Step 2 — Masuk ke VPS via SSH
```bash
ssh root@IP_VPS_KAMU
```

### Step 3 — Jalankan setup otomatis
```bash
curl -fsSL https://get.docker.com | sh
sudo apt install -y docker-compose-plugin git
```

### Step 4 — Clone repo dari GitHub
```bash
git clone https://github.com/USERNAME/REPO_NAME.git tradingbot
cd tradingbot
```

### Step 5 — Isi environment variables
```bash
cp .env.example .env
nano .env
# Isi semua variabel: Binance key, DB password, Discord webhook, dll
```

### Step 6 — Jalankan semua service
```bash
docker compose up -d
```

### Step 7 — Cek semua service jalan
```bash
docker compose ps
# Semua harus status: running (healthy)
```

### Step 8 — Akses N8N
Buka browser: `http://IP_VPS_KAMU:5678`
Login dengan user/password dari .env

### Step 9 — Test API bot
```bash
curl http://IP_VPS_KAMU:8000/health
# Harus return: {"status":"ok",...}
```

## Perintah penting sehari-hari

```bash
docker compose logs -f trading_bot   # Pantau log bot
docker compose logs -f api           # Pantau log API
docker compose restart trading_bot   # Restart bot
docker compose down                  # Stop semua
docker compose up -d                 # Start semua
```

## Struktur file yang perlu ada di repo
```
tradingbot/
├── docker-compose.yml   ← file ini
├── Dockerfile
├── .env.example         ← template (commit ini)
├── .env                 ← JANGAN commit!
├── .gitignore
├── init.sql
├── api.py               ← FastAPI wrapper
├── trading_bot.py
├── config.py
├── requirements.txt
└── ... (semua file .py lainnya)
```
