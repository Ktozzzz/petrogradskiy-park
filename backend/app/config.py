# -*- coding: utf-8 -*-
"""Конфигурация приложения.

Все наименования, веса ранжирования и ограничения вынесены в переменные
окружения (файл .env в корне проекта), код их не содержит.
"""
import os

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../backend
ROOT_DIR = os.path.dirname(BACKEND_DIR)                                    # .../project root


def load_env(path):
    """Минимальный загрузчик .env без внешних зависимостей."""
    values = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                values[key.strip()] = val.strip().strip('"').strip("'")
    return values


_ENV = load_env(os.path.join(ROOT_DIR, ".env"))


def get(name, default=None):
    """Значение из переменных окружения (process env имеет приоритет над .env)."""
    if name in os.environ:
        return os.environ[name]
    return _ENV.get(name, default)


def get_float(name, default):
    try:
        return float(get(name, default))
    except (TypeError, ValueError):
        return float(default)


def get_int(name, default):
    try:
        return int(get(name, default))
    except (TypeError, ValueError):
        return int(default)


DATABASE_URL = get("DATABASE_URL", "postgresql+psycopg://postgres@127.0.0.1:5433/parks")
AI_BASE_URL = get("AI_BASE_URL", "http://127.0.0.1:11434/v1")
AI_MODEL = get("AI_MODEL", "qwen2.5:3b")
AI_TIMEOUT = get_int("AI_TIMEOUT", 30)
GEOCODER_URL = get("GEOCODER_URL", "https://nominatim.openstreetmap.org")
GEOCODER_ENABLED = get("GEOCODER_ENABLED", "true").lower() in ("1", "true", "yes", "on")
MAP_TILE_URL = get("MAP_TILE_URL", "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png")
MAP_TILE_ATTRIBUTION = get(
    "MAP_TILE_ATTRIBUTION", "© OpenStreetMap contributors"
)

# Веса гибридного ранжирования (semantic + spatial + category).
RANK_WEIGHT_SEMANTIC = get_float("RANK_WEIGHT_SEMANTIC", 0.50)
RANK_WEIGHT_SPATIAL = get_float("RANK_WEIGHT_SPATIAL", 0.30)
RANK_WEIGHT_CATEGORY = get_float("RANK_WEIGHT_CATEGORY", 0.20)

# Ограничения API.
MAX_RADIUS_METERS = get_int("MAX_RADIUS_METERS", 5000)
MAX_LIMIT = get_int("MAX_LIMIT", 100)
DEFAULT_LIMIT = get_int("DEFAULT_LIMIT", 20)

FRONTEND_DIST = get("FRONTEND_DIST", "frontend/dist")
LOG_LEVEL = get("LOG_LEVEL", "INFO")

# Целевая область проекта.
BOROUGH = get("BOROUGH", "Петроградский")


def ranking_weights():
    """Веса гибридного ранжирования как единый конфигурационный объект."""
    weights = {
        "semantic": RANK_WEIGHT_SEMANTIC,
        "spatial": RANK_WEIGHT_SPATIAL,
        "category": RANK_WEIGHT_CATEGORY,
    }
    total = sum(weights.values()) or 1.0
    return {key: round(value / total, 4) for key, value in weights.items()}
