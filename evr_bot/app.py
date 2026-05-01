"""
EVR Trading Bot — FastAPI REST API (Ana Şalter / Entrypoint)
=============================================================
Tüm endpoint'ler api klasöründeki router'lardan alınır.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from evr_bot.config import BASE_DIR
from evr_bot.database import init_db
from evr_bot.api import auth, dashboard, keys, backtest, portfolio

STATIC_DIR = BASE_DIR / "static"
logger = logging.getLogger("evr_bot.api")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info("Veritabani baslatildi.")
    yield

app = FastAPI(
    title="EVR Trading Bot API",
    description="Kantitatif BTC/USDT alim-satim bot platformu",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None if os.getenv("ENVIRONMENT", "production") == "production" else "/docs",
    redoc_url=None if os.getenv("ENVIRONMENT", "production") == "production" else "/redoc",
)

allowed_origins_str = os.getenv("ALLOWED_ORIGINS", "")
allowed_origins = [o.strip() for o in allowed_origins_str.split(",")] if allowed_origins_str else []

allow_all = "*" in allowed_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if allow_all else allowed_origins,
    allow_credentials=not allow_all,  # GUVENLIK: * varsa credentials kullanilamaz
    allow_methods=["*"],
    allow_headers=["*"],
)

# Router'ları bağla
app.include_router(auth.router, tags=["Authentication"])
app.include_router(keys.router, tags=["API Keys"])
app.include_router(dashboard.router, tags=["Dashboard & Data"])
app.include_router(backtest.router, tags=["Backtesting"])
app.include_router(portfolio.router, tags=["Portfolio"])

# Rate Limiter (slowapi) — auth rate limiter'i uygulamaya kaydet
app.state.limiter = auth.limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Static dosyalar (CSS, JS)
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Ana sayfa
@app.get("/", include_in_schema=False)
def serve_index():
    index_file = STATIC_DIR / "index.html"
    return FileResponse(str(index_file))

@app.get("/health")
def health():
    """
    Deep health check:
    - DB baglantisi
    - Bot/Updater heartbeat dosya yasini kontrol eder
    """
    from sqlalchemy import text as sa_text
    from evr_bot.database import SessionLocal
    from pathlib import Path

    status = "ok"
    details = {}

    # 1. DB baglantisi
    try:
        db = SessionLocal()
        db.execute(sa_text("SELECT 1"))
        db.close()
        details["database"] = "connected"
    except Exception as e:
        details["database"] = f"error: {str(e)[:80]}"
        status = "degraded"

    # 2. Heartbeat dosyalari
    data_dir = Path(os.getenv("DATA_DIR", "."))
    now_ts = datetime.now(timezone.utc).timestamp()

    for name in ["bot_heartbeat", "updater_heartbeat"]:
        hb_path = data_dir / name
        if hb_path.exists():
            age_minutes = (now_ts - hb_path.stat().st_mtime) / 60
            if age_minutes > 1560:  # 26 saat
                details[name] = f"stale ({age_minutes:.0f} min)"
                status = "degraded"
            else:
                details[name] = f"fresh ({age_minutes:.0f} min ago)"
        else:
            details[name] = "missing"
            status = "degraded"

    return {
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "details": details,
    }
