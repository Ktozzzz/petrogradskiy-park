# -*- coding: utf-8 -*-
"""REST API: аналитика (coverage, radius analysis, распределение категорий)."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from .. import config
from ..database import get_db
from ..services import stats_service

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/coverage")
def coverage(
    step_m: int = Query(250, ge=50, le=1000),
    distance_m: int = Query(500, ge=50, le=5000),
    db: Session = Depends(get_db),
):
    """Coverage Analysis: какая часть района в пешей доступности от объектов."""
    return stats_service.coverage_analysis(db, step_m=step_m, distance_m=distance_m)


@router.get("/radius")
def radius_analysis(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    radius_m: float = Query(1000, gt=0, le=config.MAX_RADIUS_METERS),
    db: Session = Depends(get_db),
):
    """Radius Analysis: количество и распределение объектов в радиусе."""
    return stats_service.radius_analysis(db, latitude, longitude, radius_m)


@router.get("/category-distribution")
def category_distribution(db: Session = Depends(get_db)):
    """Category Distribution: распределение категорий по сетке района."""
    return {"cells": stats_service.category_distribution(db)}


@router.get("/nearest-neighbor")
def nearest_neighbor(db: Session = Depends(get_db)):
    """Nearest Neighbor: среднее расстояние до ближайшего соседа."""
    data = stats_service.basic_statistics(db)
    return {"avg_nearest_neighbor_m": data["avg_nearest_neighbor_m"]}
