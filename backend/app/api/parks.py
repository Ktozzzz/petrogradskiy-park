# -*- coding: utf-8 -*-
"""REST API: парки и сады, пространственные операции, слои карты."""
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import config
from ..database import get_db
from ..models import (
    CATEGORIES,
    CATEGORY_LABELS,
    POI_ICONS,
    POI_LABELS,
    POI_COLORS,
    POI_TYPES,
    ROAD_LABELS,
    ROAD_TYPES,
)
from ..schemas import schemas
from ..services import geojson_service, serializers, spatial, stats_service
from ..services import photos as photos_service

router = APIRouter(prefix="/api", tags=["parks"])


def _park_out(row):
    return serializers.park_out(row)


@router.get("/parks", response_model=schemas.ParkListResponse)
def list_parks(
    category: Optional[List[str]] = Query(None),
    q: Optional[str] = None,
    has_poi: Optional[bool] = None,
    poi_type: Optional[str] = None,
    limit: int = Query(50, ge=1, le=config.MAX_LIMIT),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Список объектов с фильтрами (категория, название, тип точек интереса)."""
    total, rows = spatial.list_parks(
        db, category=category, q=q, has_poi=has_poi, poi_type=poi_type,
        limit=limit, offset=offset,
    )
    return {"total": total, "items": [_park_out(row) for row in rows]}


@router.get("/parks/geojson")
def parks_geojson(
    category: Optional[List[str]] = Query(None),
    ids: Optional[List[int]] = Query(None),
    mode: str = Query("polygon", pattern="^(polygon|point)$"),
    db: Session = Depends(get_db),
):
    """GeoJSON-слой объектов: mode=polygon (контуры) или mode=point (центроиды)."""
    return geojson_service.parks_geojson(db, category=category, ids=ids, mode=mode)


@router.get("/parks/nearby", response_model=schemas.NearbyResponse)
def nearby(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    category: Optional[str] = None,
    limit: int = Query(10, ge=1, le=config.MAX_LIMIT),
    db: Session = Depends(get_db),
):
    """Ближайшие объекты к точке (KNN-запрос с индексом GiST)."""
    if category and category not in CATEGORIES:
        raise HTTPException(status_code=400, detail="Недопустимая категория: %s" % category)
    rows = spatial.nearby_parks(db, latitude, longitude, category, limit)
    return {
        "center": {"latitude": latitude, "longitude": longitude},
        "count": len(rows),
        "items": [serializers.distance_item(row) for row in rows],
    }


@router.get("/parks/radius", response_model=schemas.RadiusResponse)
def radius(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    radius_m: float = Query(1000, gt=0, le=config.MAX_RADIUS_METERS),
    category: Optional[str] = None,
    limit: int = Query(50, ge=1, le=config.MAX_LIMIT),
    db: Session = Depends(get_db),
):
    """Объекты в радиусе от точки (ST_DWithin + точный расчёт geography)."""
    if category and category not in CATEGORIES:
        raise HTTPException(status_code=400, detail="Недопустимая категория: %s" % category)
    rows = spatial.radius_parks(db, latitude, longitude, radius_m, category, limit)
    return {
        "center": {"latitude": latitude, "longitude": longitude},
        "radius_m": radius_m,
        "count": len(rows),
        "items": [serializers.distance_item(row) for row in rows],
    }


@router.get("/parks/nearest_distance", response_model=schemas.NearestDistanceResponse)
def nearest_distance(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    category: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Расстояние до ближайшего объекта от точки."""
    row = spatial.nearest_park(db, latitude, longitude, category)
    if not row:
        raise HTTPException(status_code=404, detail="Объекты не найдены")
    distance_m = float(row["distance_m"])
    return {
        "latitude": latitude,
        "longitude": longitude,
        "distance_m": round(distance_m, 1),
        "distance_km": round(distance_m / 1000.0, 3),
        "nearest_park": _park_out(row),
        "walking_minutes": serializers.walking_minutes(distance_m),
    }


@router.get("/parks/search", response_model=schemas.SearchResponse)
def search(
    q: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(20, ge=1, le=config.MAX_LIMIT),
    db: Session = Depends(get_db),
):
    """Текстовый поиск: объекты (парки/сады/скверы) и интересные локации (POI)."""
    rows = spatial.search_parks(db, q, limit=limit)
    poi_rows = spatial.search_poi(db, q, limit=min(limit, 20))
    return {
        "total": len(rows),
        "items": [_park_out(row) for row in rows],
        "poi": [serializers.poi_out(row) for row in poi_rows],
    }


@router.get("/parks/{park_id}/photos", response_model=schemas.ParkPhotosResponse)
def park_photos(
    park_id: int,
    limit: int = Query(6, ge=1, le=12),
    db: Session = Depends(get_db),
):
    """Фотографии объекта (Wikimedia Commons + фото из БД, с кэшем)."""
    row = spatial.get_park(db, park_id)
    if not row:
        raise HTTPException(status_code=404, detail="Объект не найден")

    photos = []
    if row.get("image_url"):
        photos.append({"url": row["image_url"], "title": None, "page": None})
    photos.extend(photos_service.search_photos(row["name"], limit=limit))
    return {
        "park_id": row["id"],
        "park_name": row["name"],
        "photos": photos[:limit],
    }


@router.get("/parks/{park_id}", response_model=schemas.ParkOut)
def get_park(park_id: int, db: Session = Depends(get_db)):
    row = spatial.get_park(db, park_id)
    if not row:
        raise HTTPException(status_code=404, detail="Объект не найден")
    return _park_out(row)


@router.get("/parks/{park_id}/distance/{other_id}")
def distance(park_id: int, other_id: int, db: Session = Depends(get_db)):
    """Расстояние между двумя объектами (metres/kilometres)."""
    distance_m = spatial.distance_between_parks(db, park_id, other_id)
    if distance_m is None:
        raise HTTPException(status_code=404, detail="Объект не найден")
    return {
        "from_id": park_id,
        "to_id": other_id,
        "distance_m": round(distance_m, 1),
        "distance_km": round(distance_m / 1000.0, 3),
    }


@router.get("/parks/{park_id}/poi")
def park_poi(park_id: int, poi_type: Optional[str] = None, db: Session = Depends(get_db)):
    if poi_type and poi_type not in POI_TYPES:
        raise HTTPException(status_code=400, detail="Недопустимый тип точки интереса")
    rows = spatial.park_poi(db, park_id, poi_type)
    return {"total": len(rows), "items": [serializers.poi_out(row) for row in rows]}


@router.get("/parks/{park_id}/roads")
def park_roads(park_id: int, db: Session = Depends(get_db)):
    rows = spatial.park_roads(db, park_id)
    return {"total": len(rows), "items": [serializers.road_out(row) for row in rows]}


@router.get("/parks/{park_id}/exits")
def park_exits(park_id: int, db: Session = Depends(get_db)):
    rows = spatial.park_exits(db, park_id)
    return {"total": len(rows), "items": [serializers.exit_out(row) for row in rows]}


@router.get("/parks/{park_id}/poi/geojson")
def park_poi_geojson(park_id: int, db: Session = Depends(get_db)):
    return geojson_service.poi_geojson(db, park_id=park_id)


@router.get("/parks/{park_id}/roads/geojson")
def park_roads_geojson(park_id: int, db: Session = Depends(get_db)):
    return geojson_service.roads_geojson(db, park_id=park_id)


@router.get("/parks/{park_id}/exits/geojson")
def park_exits_geojson(park_id: int, db: Session = Depends(get_db)):
    return geojson_service.exits_geojson(db, park_id=park_id)


@router.get("/parks/{park_id}/nearby", response_model=schemas.RadiusResponse)
def park_nearby(
    park_id: int,
    radius_m: float = Query(1000, gt=0, le=config.MAX_RADIUS_METERS),
    db: Session = Depends(get_db),
):
    """Функция «Что рядом?» -- объекты в радиусе от центроида объекта."""
    park = spatial.get_park(db, park_id)
    if not park:
        raise HTTPException(status_code=404, detail="Объект не найден")
    rows = spatial.objects_in_radius_from_park(db, park_id, radius_m)
    groups = spatial.poi_counts_near_park(db, park_id, radius_m)
    return {
        "center": {"latitude": park["latitude"], "longitude": park["longitude"], "name": park["name"]},
        "radius_m": radius_m,
        "count": len(rows),
        "items": [serializers.distance_item(row) for row in rows],
        "by_category": groups,
    }


@router.get("/poi/geojson")
def all_poi_geojson(types: Optional[List[str]] = Query(None), db: Session = Depends(get_db)):
    return geojson_service.poi_geojson(db, poi_types=types)


@router.get("/roads/geojson")
def all_roads_geojson(db: Session = Depends(get_db)):
    return geojson_service.roads_geojson(db)


@router.get("/exits/geojson")
def all_exits_geojson(db: Session = Depends(get_db)):
    return geojson_service.exits_geojson(db)


@router.get("/districts/geojson")
def districts_geojson(db: Session = Depends(get_db)):
    """Граница Петроградского района (polygon layer)."""
    return geojson_service.districts_geojson(db)


@router.get("/categories", response_model=schemas.CategoriesResponse)
def categories(db: Session = Depends(get_db)):
    """Категории объектов, типы точек интереса и дорог с количеством записей."""
    counts = {
        row[0]: row[1]
        for row in db.execute(
            text("SELECT category, count(*) FROM parks GROUP BY category")
        ).fetchall()
    }
    poi_counts = {
        row[0]: row[1]
        for row in db.execute(
            text("SELECT poi_type, count(*) FROM poi GROUP BY poi_type")
        ).fetchall()
    }
    road_counts = {
        row[0]: row[1]
        for row in db.execute(
            text("SELECT road_type, count(*) FROM park_roads GROUP BY road_type")
        ).fetchall()
    }
    return {
        "categories": [
            {"code": code, "label": CATEGORY_LABELS[code], "count": int(counts.get(code, 0))}
            for code in CATEGORIES
        ],
        "poi_types": [
            {
                "code": code,
                "label": POI_LABELS[code],
                "icon": POI_ICONS[code],
                "color": POI_COLORS.get(code, "#607d8b"),
                "count": int(poi_counts.get(code, 0)),
            }
            for code in POI_TYPES
        ],
        "road_types": [
            {"code": code, "label": ROAD_LABELS[code], "count": int(road_counts.get(code, 0))}
            for code in ROAD_TYPES
        ],
    }


@router.get("/statistics", response_model=schemas.StatisticsResponse)
def statistics(db: Session = Depends(get_db)):
    """Статистика: объекты, площади, точки интереса, дороги, покрытие района."""
    data = stats_service.basic_statistics(db)
    coverage = stats_service.coverage_analysis(db, step_m=250, distance_m=500)
    return {**data, "coverage": coverage}
