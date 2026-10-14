# -*- coding: utf-8 -*-
"""Точка входа веб-сервиса (FastAPI).

Приложение раздаёт:
  * REST API  /api/*
  * документацию OpenAPI /docs
  * собранный фронтенд (frontend/dist) -- одна точка входа для просмотра.
"""
import logging
import os
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import config
from .ai.llm import get_llm_client
from .api import analytics, parks, query, routing
from .database import db_health

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("app")

app = FastAPI(
    title="Парки и сады Петроградского района Санкт-Петербурга",
    description=(
        "Интеллектуальный геопространственный веб-сервис: пространственная база "
        "данных PostgreSQL + PostGIS, REST API, интерактивная карта по тайлам, "
        "запросы естественным языком, семантический поиск и рекомендации."
    ),
    version="1.0.0",
    docs_url="/docs",
    openapi_url="/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Логирование запросов: endpoint, время выполнения, код ответа."""
    start = time.time()
    response = await call_next(request)
    elapsed = (time.time() - start) * 1000
    if request.url.path.startswith("/api"):
        logger.info("%s %s -> %s (%.0f мс)", request.method, request.url.path,
                    response.status_code, elapsed)
    response.headers["X-Response-Time-Ms"] = "%.0f" % elapsed
    return response


app.include_router(parks.router)
app.include_router(query.router)
app.include_router(analytics.router)
app.include_router(routing.router)


@app.get("/api/health", tags=["service"])
def health():
    """Состояние сервиса: база данных и AI-интерфейс."""
    database = db_health()
    llm = get_llm_client()
    return {
        "status": "ok" if database["ok"] else "degraded",
        "database": database,
        "ai": {
            "available": llm.available(),
            "model": llm.model,
            "base_url": llm.base_url,
            "mode": "llm + rules fallback" if llm.available() else "rules (GIS-поиск без AI)",
        },
    }


@app.get("/api/config", tags=["service"])
def app_config():
    """Конфигурация карты для фронтенда (тайлы, ограничения, центр)."""
    return {
        "tile_url": config.MAP_TILE_URL,
        "tile_attribution": config.MAP_TILE_ATTRIBUTION,
        "max_radius_m": config.MAX_RADIUS_METERS,
        "max_limit": config.MAX_LIMIT,
        "borough": config.BOROUGH,
        "center": {"latitude": 59.9563, "longitude": 30.3165},
        "zoom": 13,
        "ranking_weights": config.ranking_weights(),
    }


# ---------------------------------------------------------------------
# Статика: собранный фронтенд (SPA)
# ---------------------------------------------------------------------
DIST_DIR = os.path.join(config.ROOT_DIR, config.FRONTEND_DIST)
if os.path.isdir(DIST_DIR):
    app.mount("/", StaticFiles(directory=DIST_DIR, html=True), name="frontend")
    logger.info("Фронтенд раздаётся из %s", DIST_DIR)
else:
    logger.warning(
        "Каталог %s не найден: интерфейс не будет доступен. "
        "Соберите фронтенд: cd frontend && npm install && npm run build", DIST_DIR,
    )
