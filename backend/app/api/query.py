# -*- coding: utf-8 -*-
"""REST API: запросы естественным языком, рекомендации, подсказки."""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from ..ai import service as query_service
from ..ai.service import ClarificationError
from ..database import get_db
from ..recommendation import recommender
from ..schemas import schemas

logger = logging.getLogger("app.api")

router = APIRouter(prefix="/api", tags=["query"])

# Демонстрационные сценарии (используются как подсказки в интерфейсе).
SCENARIOS = [
    {
        "id": "nearest",
        "title": "Ближайший объект к координатам",
        "text": "Какой парк находится ближе всего к координатам 59.9598, 30.3126?",
        "kind": "gis",
    },
    {
        "id": "walk",
        "title": "Сколько идти от ориентира",
        "text": "Сколько до ближайшего парка от Электровокзала?",
        "kind": "gis",
    },
    {
        "id": "radius",
        "title": "Объекты в радиусе",
        "text": "Покажи все скверы в радиусе 1 км от Чкаловского проспекта",
        "kind": "gis",
    },
    {
        "id": "inside",
        "title": "Что внутри объекта",
        "text": "Что интересного внутри Александровского парка?",
        "kind": "ai",
    },
    {
        "id": "recommend",
        "title": "Рекомендация по смыслу",
        "text": "Найди парк с детской площадкой и местом для пикника недалеко от метро",
        "kind": "recommend",
    },
]


@router.post("/query", response_model=schemas.QueryResponse)
def post_query(request: schemas.QueryRequest, db: Session = Depends(get_db)):
    """Запрос на естественном языке -> структурированный запрос -> PostGIS."""
    try:
        result = query_service.run_query(db, request.text, request.latitude, request.longitude)
    except ClarificationError as exc:
        logger.info("query clarified: %s", exc.message)
        raise HTTPException(status_code=exc.status, detail=exc.message)
    except ValidationError:
        raise HTTPException(status_code=422, detail="Не удалось интерпретировать запрос.")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ошибка выполнения запроса")
        raise HTTPException(status_code=500, detail="Внутренняя ошибка при выполнении запроса.")
    return result


@router.post("/recommend", response_model=schemas.RecommendResponse)
def post_recommend(request: schemas.RecommendRequest, db: Session = Depends(get_db)):
    """Гибридные рекомендации: семантика + пространственная близость + категория."""
    radius = request.radius_meters
    try:
        result = recommender.recommend(
            db,
            request.query,
            request.latitude,
            request.longitude,
            radius,
            limit=request.limit or 10,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Ошибка рекомендаций")
        raise HTTPException(status_code=500, detail="Не удалось построить рекомендации.")
    return {
        "query": request.query,
        "weights": result["weights"],
        "count": result["count"],
        "center": result["center"],
        "results": result["results"],
    }


@router.get("/scenarios")
def scenarios():
    """Подсказки по типовым запросам."""
    return SCENARIOS


@router.get("/places")
def places(q: str = None, limit: int = 50, db: Session = Depends(get_db)):
    """Справочник географических названий (ориентиры района)."""
    from sqlalchemy import text

    if q:
        rows = db.execute(
            text(
                """
                SELECT id, name, kind, latitude, longitude, source
                FROM geo_places
                WHERE name ILIKE :q
                ORDER BY name
                LIMIT :limit
                """
            ),
            {"q": "%" + q + "%", "limit": limit},
        ).fetchall()
    else:
        rows = db.execute(
            text(
                """
                SELECT id, name, kind, latitude, longitude, source
                FROM geo_places
                ORDER BY kind, name
                LIMIT :limit
                """
            ),
            {"limit": limit},
        ).fetchall()
    return [dict(row._mapping) for row in rows]
