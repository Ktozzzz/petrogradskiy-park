# -*- coding: utf-8 -*-
"""Подключение к PostgreSQL + PostGIS."""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

from . import config

engine = create_engine(
    config.DATABASE_URL,
    pool_pre_ping=True,
    future=True,
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

Base = declarative_base()


def get_db():
    """FastAPI dependency: сессия БД на один запрос."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def db_health():
    """Проверка состояния базы для /api/health."""
    result = {"ok": False, "postgis": None, "parks": None, "error": None}
    try:
        with engine.connect() as conn:
            postgis = conn.execute(text("SELECT postgis_version()")).scalar()
            parks = conn.execute(text("SELECT count(*) FROM parks")).scalar()
            result.update({"ok": True, "postgis": str(postgis), "parks": int(parks)})
    except Exception as exc:  # noqa: BLE001 - здоровье сервиса не должно падать
        result["error"] = str(exc)
    return result
