#!/bin/bash
# ============================================================
# SETUP_VPS.SH — Jalankan sekali di VPS baru (Ubuntu 22.04)
# Usage: chmod +x setup_vps.sh && ./setup_vps.sh
# ============================================================

echo ">>> Update sistem..."
sudo apt update && sudo apt upgrade -y

echo ">>> Install Docker..."
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

echo ">>> Install Docker Compose..."
sudo apt install -y docker-compose-plugin

echo ">>> Install utilitas..."
sudo apt install -y git curl ufw htop

echo ">>> Setup firewall..."
sudo ufw allow 22    # SSH
sudo ufw allow 8000  # FastAPI
sudo ufw allow 5678  # N8N
sudo ufw --force enable

echo ">>> Clone repo dari GitHub..."
# Ganti URL di bawah dengan repo kamu
# git clone https://github.com/USERNAME/REPO_NAME.git tradingbot
# cd tradingbot

echo ">>> Selesai! Langkah selanjutnya:"
echo "  1. git clone repo kamu"
echo "  2. cp .env.example .env && nano .env  (isi semua variabel)"
echo "  3. docker compose up -d"
echo "  4. docker compose logs -f  (pantau log)"
