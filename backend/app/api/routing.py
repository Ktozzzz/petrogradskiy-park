# -*- coding: utf-8 -*-
"""Построение маршрута до выбранного объекта.

Один endpoint `/api/route` принимает две точки (старт и финиш) и возвращает
ломаную (GeoJSON LineString), расстояние и ориентировочное время.

Маршрут строится только по дорожной сети (пеший профиль):
    1) публичный инстанс Valhalla от OpenStreetMap;
    2) запасной роутер OSRM (routing.openstreetmap.de).

Оба роутера привязывают (snap) точки к ближайшей дорожной сети, но этого
недостаточно: точка посреди Невской губы может приклеиться к паромному
рейсу или к сети, удалённой на километры. Поэтому результат дополнительно
проверяется:
    * маршрут не должен использовать паромы (has_ferry);
    * старт и финиш не должны быть привязаны дальше MAX_SNAP_M метров.
Точки посреди воды дают HTTP 422 с понятным сообщением; если роутеры
недоступны — HTTP 502. Маршрут «по прямой» через Неву или залив
не рисуется никогда.
"""
import json
import logging
import math
from typing import Optional

import requests
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

logger = logging.getLogger("app.routing")
router = APIRouter(prefix="/api", tags=["routing"])

VALHALLA_URL = "https://valhalla1.openstreetmap.de/route"
# Запасной пеший роутер OSRM. Профиль подставляется и в поддомен, и в путь.
OSRM_URL = "https://routing.openstreetmap.de/routed-{profile}/route/v1/{profile}"
COSTING_TO_PROFILE = {"pedestrian": "foot", "bicycle": "bike", "auto": "car"}
ROUTER_TIMEOUT_S = 15
USER_AGENT = "petrogradsky-parks/1.0"
# Максимально допустимая привязка (snap) точки к дорожной сети, в метрах.
# Дальше — маршрут по сути строится не от запрошенной точки (часто это вода:
# Невская губа, Нева, залив), и мы отказываемся его рисовать.
MAX_SNAP_M = 400.0
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
    source: str                         # "valhalla" | "osrm" (роутер дорожной сети)


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
        # Пеший маршрут не должен использовать паромы: паром через Невскую
        # губу — это и есть «маршрут по воде». (Публичный инстанс опцию
        # не всегда учитывает, поэтому ниже проверяется и has_ferry.)
        "costing_options": {costing: {"use_ferry": 0}},
        "directions_options": {"units": "kilometers"},
    }
    # Публичный инстанс Valhalla принимает POST с JSON-телом (GET с ?json=
    # отклоняется кодом 400).
    resp = requests.post(
        VALHALLA_URL,
        data=json.dumps(payload),
        headers={
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        timeout=ROUTER_TIMEOUT_S,
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
    summary = (trip.get("summary") or {}) if trip else {}
    # Маршрут с паромом пеший не принимаем — это линия по воде.
    # Публичный инстанс опцию use_ferry не всегда учитывает, поэтому
    # проверяем итоговый флаг.
    if summary.get("has_ferry"):
        raise RuntimeError("Valhalla построил маршрут через паром (по воде)")
    if not coords and trip:
        legs = trip.get("legs") or []
        shape = "".join(leg.get("shape", "") for leg in legs if leg.get("shape"))
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


def _osrm_route(start, end, costing):
    """Запасной роутер OSRM (routing.openstreetmap.de, пеший профиль).

    Возвращает (coords[[lon,lat], ...], distance_m, duration_s).
    Точки также привязываются к дорожной сети — по воде линия не пойдёт.
    """
    profile = COSTING_TO_PROFILE.get(costing, "foot")
    url = "%s/%s,%s;%s,%s" % (
        OSRM_URL.format(profile=profile),
        start[0], start[1],
        end[0], end[1],
    )
    resp = requests.get(
        url,
        params={
            "overview": "full",
            "geometries": "geojson",
            "alternatives": "false",
            "steps": "false",
        },
        headers={"User-Agent": USER_AGENT},
        timeout=ROUTER_TIMEOUT_S,
    )
    if resp.status_code != 200 or not resp.text:
        raise RuntimeError("OSRM HTTP %s: %s" % (resp.status_code, resp.text[:200]))
    data = resp.json()
    if data.get("code") != "Ok":
        raise RuntimeError("OSRM: %s" % str(data.get("message") or data)[:200])
    routes = data.get("routes") or []
    if not routes:
        raise RuntimeError("OSRM вернул пустой маршрут")
    route = routes[0]
    geom = (route.get("geometry") or {})
    coords = geom.get("coordinates")
    if not coords or len(coords) < 2:
        raise RuntimeError("OSRM вернул пустую геометрию: %s" % str(data)[:200])
    coords = [[float(c[0]), float(c[1])] for c in coords]
    distance_m = route.get("distance")
    if distance_m is None:
        distance_m = _path_length_m(coords)
    duration_s = route.get("duration")
    return coords, float(distance_m), (float(duration_s) if duration_s is not None else None)


# Роутеры пробуются по очереди: сперва Valhalla, затем OSRM.
# Каждый строит путь строго по дорожной сети (snap к ближайшей дороге).
ROUTERS = (
    ("valhalla", _valhalla_route),
    ("osrm", _osrm_route),
)


@router.post("/route", response_model=RouteResponse)
def build_route(req: RouteRequest):
    """Маршрут от точки старта до выбранного объекта (пеший по умолчанию).

    Маршрут строится только по дорожной сети. Точки, которые роутеры не смогли
    привязать к сети ближе чем на MAX_SNAP_M (обычно это вода: Нева, залив,
    Невская губа), дают HTTP 422 с понятным сообщением. Если роутеры
    недоступны — HTTP 502. Линии «по прямой» через воду не бывает.
    """
    start = (req.start_lon, req.start_lat)
    end = (req.end_lon, req.end_lat)

    errors = []
    snap_errors = []
    for source, router_fn in ROUTERS:
        try:
            coords, distance_m, duration_s = router_fn(start, end, req.costing)
        except Exception as exc:  # noqa: BLE001 - внешний роутер, пробуем следующий
            logger.warning("Роутер %s недоступен: %s", source, exc)
            errors.append("%s: %s" % (source, exc))
            continue

        # Проверка привязки: если роутер приклеил точку дальше MAX_SNAP_M,
        # маршрут фактически начинается/заканчивается не там, где просил
        # пользователь (как правило - посреди воды). Такой маршрут не берём.
        d_start = _haversine_m(coords[0], start)
        d_end = _haversine_m(coords[-1], end)
        if d_start > MAX_SNAP_M or d_end > MAX_SNAP_M:
            msg = ("%s: точка привязана к сети на %.0f м (старт) / %.0f м (финиш)"
                   % (source, d_start, d_end))
            logger.warning("Маршрут отклонён: %s", msg)
            snap_errors.append(msg)
            continue

        if duration_s is None and req.costing == "pedestrian" and distance_m:
            duration_s = distance_m / WALK_SPEED_M_S

        return RouteResponse(
            geometry={"type": "LineString", "coordinates": coords},
            distance_m=round(distance_m, 1),
            duration_s=round(duration_s) if duration_s is not None else None,
            source=source,
        )

    if snap_errors:
        # Роутеры ответили, но ни одна точка не попала в дорожную сеть -
        # скорее всего, старт или финиш находится на воде.
        logger.error("Маршрут невозможен (snap): %s", "; ".join(snap_errors))
        raise HTTPException(
            status_code=422,
            detail=(
                "Не удалось построить маршрут: точка старта или финиша находится "
                "на воде либо слишком далеко от дорожной сети. Выберите точку "
                "на берегу, дороге или тропинке парка."
            ),
        )

    logger.error("Ни один роутер не ответил: %s", "; ".join(errors))
    raise HTTPException(
        status_code=502,
        detail=(
            "Не удалось построить маршрут: сервисы маршрутизации (Valhalla, OSRM) "
            "временно недоступны. Маршрут по прямой через воду не строится — "
            "повторите попытку позже."
        ),
    )
