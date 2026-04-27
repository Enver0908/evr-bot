# ═══════════════════════════════════════════════════════════════
# EVR Trading Bot — Production Dockerfile
# Multi-stage build: slim Python image
# ═══════════════════════════════════════════════════════════════
FROM python:3.12-slim AS base

# Sistem bağımlılıkları (psycopg2-binary ve genel derleme)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       gcc libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# Çalışma dizini
WORKDIR /app

# Bağımlılıkları önce kopyala (Docker cache)
COPY requirements.txt .

# playwright hariç kur — headless browser sunucuda gereksiz
# psycopg2-binary PostgreSQL için gerekli
RUN pip install --no-cache-dir -r requirements.txt \
    || pip install --no-cache-dir $(grep -v '^playwright' requirements.txt | tr '\n' ' ')

# Uygulama kodunu kopyala
COPY evr_bot/ ./evr_bot/
COPY static/ ./static/
COPY run.py .
COPY daily_updater.py .
COPY evr_scraper.py .


# .env.example'ı referans olarak kopyala
COPY .env.example .

# Data dizini (SQLite db, log, fernet key)
RUN mkdir -p /app/data

# Port
EXPOSE 8000

# Sağlık kontrolü
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Varsayılan: API sunucusu
CMD ["python", "run.py", "api"]
