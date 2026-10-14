# -*- coding: utf-8 -*-
"""Построение маршрута до выбранного объекта.

Один endpoint `/api/route` принимает две точки (старт и финиш) и возвращает
ломаную (GeoJSON LineString), расстояние и ориентировочное время.

Основной источник — публичный инстанс Valhalla от OpenStreetMap (пеший профиль),
без ключей и регистрации. Если внешний роутер недоступен, возвращаем прямую
линию (маршрут «по прямой»), чтобы линия всегда рисовалась на карте.
"""
import json
import logging
import math
from typing import Optional

import requests
from fastapi import APIRouter
from pydantic import BaseModel, Field

logger = logging.getLogger("app.routing")
router = APIRouter(prefix="/api", tags=["routing"])

VALHALLA_URL = "https://valhalla1.openstreetmap.de/route"
# Средняя скорость пешего движения (м/с) — для оценки времени в пути,
# если роутер не вернул duration.
WALK_SPEED_M_S = 1.35


class RouteRequest(BaseModel):
    start_lat: float = Field(..., ge=-90, le=90)
    start_lon: float = Field(..., ge=-180, le=180)
    end_lat: float = Field(..., ge=-90, le=90)
    end_lon: float = Field(..., ge=-180, le=180)
    costing: str = Field("pedestrian", pattern="^(pedestrian|bicycle|auto)$")


class RouteResponse(BaseModel):
    geometry: dict                      # GeoJSON LineString (координаты [lon, lat])
    distance_m: float
    duration_s: Optional[float] = None
    source: str                         # "valhalla" (реальный) | "straight" (по прямой)


def _haversine_m(a, b):
    """Расстояние между двумя точками [lon, lat] в метрах."""
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(h))


def _path_length_m(coords):
    if not coords or len(coords) < 2:
        return 0.0
    return sum(_haversine_m(coords[i], coords[i + 1]) for i in range(len(coords) - 1))


def _decode_polyline(encoded, precision=6):
    """Декодирование закодированной полилинии (алгоритм Google)."""
    coords = []
    index = 0
    lat = 0
    lng = 0
    factor = 10 ** precision
    while index < len(encoded):
        result = 0
        shift = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        lat += ~(result >> 1) if result & 1 else (result >> 1)
        result = 0
        shift = 0
        while True:
            b = ord(encoded[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break
        lng += ~(result >> 1) if result & 1 else (result >> 1)
        coords.append([lng / factor, lat / factor])
    return coords


def _valhalla_route(start, end, costing):
    """Запрос к публичному Valhalla.

    Возвращает (coords[[lon,lat], ...], distance_m, duration_s|None).
    Разбирает формат geojson, а при неудаче — формат по умолчанию
    (trip.legs[].shape — закодированная полилиния).
    """
    payload = {
        "locations": [
            {"lat": start[1], "lon": start[0]},
            {"lat": end[1], "lon": end[0]},
        ],
        "costing": costing,
        "directions_options": {"units": "kilometers"},
    }
    # Публичный инстанс Valhalla принимает POST с JSON-телом (GET с ?json=
    # отклоняется кодом 400).
    resp = requests.post(
        VALHALLA_URL,
        data=json.dumps(payload),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "petrogradsky-parks/1.0",
        },
        timeout=18,
    )
    if resp.status_code != 200 or not resp.text:
        raise RuntimeError("Valhalla HTTP %s: %s"
                           % (resp.status_code, resp.text[:200]))
    data = resp.json()

    coords = None
    distance_m = None
    duration_s = None

    # 1) Формат geojson, похожий на OSRM: routes[0].geometry.coordinates
    routes = data.get("routes")
    if isinstance(routes, list) and routes:
        geom = routes[0].get("geometry") or {}
        coords = geom.get("coordinates")
        distance_m = routes[0].get("distance")
        duration_s = routes[0].get("duration")

    # 2) FeatureCollection: features[0].geometry.coordinates
    if not coords:
        feats = data.get("features")
        if isinstance(feats, list) and feats:
            geom = feats[0].get("geometry") or {}
            coords = geom.get("coordinates")

    # 3) Формат Valhalla по умолчанию: trip.legs[].shape (encoded polyline),
    #    расстояние/время -- в trip.summary (length в км, time в секундах).
    trip = data.get("trip")
    if not coords and trip:
        legs = trip.get("legs") or []
        shape = "".join(leg.get("shape", "") for leg in legs if leg.get("shape"))
        summary = trip.get("summary") or {}
        if shape:
            # Точность кодирования подбирается по опорной рамке из summary.
            for precision in (6, 5):
                try:
                    decoded = _decode_polyline(shape, precision)
                except Exception:  # noqa: BLE001 - неверная точность кодирования
                    continue
                if not decoded or len(decoded) < 2:
                    continue
                if summary.get("min_lat") is not None:
                    lats = [c[1] for c in decoded]
                    lons = [c[0] for c in decoded]
                    if (abs(min(lats) - summary["min_lat"]) > 0.05
                            or abs(max(lats) - summary["max_lat"]) > 0.05
                            or abs(min(lons) - summary["min_lon"]) > 0.05
                            or abs(max(lons) - summary["max_lon"]) > 0.05):
                        continue
                coords = decoded
                break
        if coords:
            if summary.get("length") is not None:
                distance_m = float(summary["length"]) * 1000.0  # км -> м
            if summary.get("time") is not None:
                duration_s = float(summary["time"])             # секунды

    if not coords:
        raise RuntimeError("Valhalla вернул пустую геометрию: %s"
                           % str(data)[:200])

    coords = [[float(c[0]), float(c[1])] for c in coords]
    if distance_m is None:
        distance_m = _path_length_m(coords)
    return coords, float(distance_m), (float(duration_s) if duration_s else None)


@router.post("/route", response_model=RouteResponse)
def build_route(req: RouteRequest):
    """Маршрут от точки старта до выбранного объекта (пеший по умолчанию)."""
    start = (req.start_lon, req.start_lat)
    end = (req.end_lon, req.end_lat)

    coords = None
    distance_m = None
    duration_s = None
    source = "valhalla"
    try:
        coords, distance_m, duration_s = _valhalla_route(start, end, req.costing)
    except Exception as exc:  # noqa: BLE001 - внешний роутер не обязателен
        logger.warning("Valhalla недоступен, строим по прямой: %s", exc)
        source = "straight"
        coords = [[start[0], start[1]], [end[0], end[1]]]
        distance_m = _path_length_m(coords)

    if duration_s is None and req.costing == "pedestrian" and distance_m:
        duration_s = distance_m / WALK_SPEED_M_S

    return RouteResponse(
        geometry={"type": "LineString", "coordinates": coords},
        distance_m=round(distance_m, 1),
        duration_s=round(duration_s) if duration_s is not None else None,
        source=source,
    )
