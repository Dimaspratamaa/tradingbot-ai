# ============================================================
# DOCKERFILE — Trading Bot AI
# Base: Python 3.11 slim
# ============================================================

FROM python:3.11-slim

# System deps
RUN apt-get update && apt-get install -y \
    gcc g++ curl libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps dulu (cache layer)
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir fastapi uvicorn[standard] redis psycopg2-binary asyncpg

# Copy semua source code
COPY . .

# Buat folder data & logs
RUN mkdir -p /app/data /app/logs

# Non-root user untuk keamanan
RUN useradd -m -u 1000 botuser && chown -R botuser:botuser /app
USER botuser

EXPOSE 8000

CMD ["python", "trading_bot.py"]
