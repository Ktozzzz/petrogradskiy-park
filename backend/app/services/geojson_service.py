# -*- coding: utf-8 -*-
"""Сборка GeoJSON-слоёв для отображения на карте.

Строится на стороне backend из данных PostGIS (ST_AsGeoJSON),
что позволяет отдавать фронтенду готовые полигоны, точки и линии.
"""
import json

from sqlalchemy import text

from ..models import CATEGORY_LABELS, POI_COLORS, POI_ICONS, POI_LABELS, ROAD_LABELS


def _feature(geometry, properties, feature_id=None):
    if isinstance(geometry, str):
        geometry = json.loads(geometry)
    return {
        "type": "Feature",
        "id": feature_id,
        "geometry": geometry,
        "properties": properties,
    }


def _collection(features):
    return {"type": "FeatureCollection", "features": features}


def parks_geojson(db, category=None, ids=None, mode="polygon"):
    """Слой объектов: полигоны или точки в центроидах.

    mode=polygon -> geometry(MultiPolygon), mode=point -> geometry(Point)
    """
    where = ["TRUE"]
    params = {}
    if category:
        if isinstance(category, (list, tuple)):
            where.append("p.category = ANY(:categories)")
            params["categories"] = list(category)
        else:
            where.append("p.category = :category")
            params["category"] = category
    if ids:
        where.append("p.id = ANY(:ids)")
        params["ids"] = list(ids)

    geom_col = "ST_AsGeoJSON(p.centroid)" if mode == "point" else "ST_AsGeoJSON(p.geometry)"
    rows = db.execute(
        text(
            """
            SELECT p.id, p.name, p.category, p.description, p.address,
                   p.borough, p.latitude, p.longitude, p.area_sqm, p.is_free,
                   p.working_hours, p.website, p.phone, p.image_url,
                   p.year_established, p.metro_stations, p.facilities,
                   p.themes, p.keywords, p.osm_id, p.osm_type,
                   p.has_poi, p.has_roads, p.has_exits, p.source,
                   %s AS gj,
                   (SELECT count(*) FROM poi i WHERE i.park_id = p.id) AS poi_count,
                   (SELECT count(*) FROM park_roads r WHERE r.park_id = p.id) AS road_count,
                   (SELECT count(*) FROM park_exits e WHERE e.park_id = p.id) AS exit_count
            FROM parks p
            WHERE %s
            ORDER BY p.name
            """
            % (geom_col, " AND ".join(where))
        ),
        params,
    ).fetchall()

    features = []
    for row in rows:
        item = dict(row._mapping)
        features.append(
            _feature(
                item.pop("gj"),
                {
                    "id": item["id"],
                    "name": item["name"],
                    "category": item["category"],
                    "category_label": CATEGORY_LABELS.get(item["category"], item["category"]),
                    "description": item["description"],
                    "address": item["address"],
                    "borough": item["borough"] or "Петроградский",
                    "latitude": item["latitude"],
                    "longitude": item["longitude"],
                    "area_sqm": item["area_sqm"],
                    "is_free": item["is_free"],
                    "working_hours": item["working_hours"],
                    "website": item["website"],
                    "phone": item["phone"],
                    "image_url": item["image_url"],
                    "year_established": item["year_established"],
                    "metro_stations": item["metro_stations"] or [],
                    "facilities": item["facilities"] or [],
                    "themes": item["themes"] or [],
                    "keywords": item["keywords"] or [],
                    "osm_id": item["osm_id"],
                    "osm_type": item["osm_type"],
                    "has_poi": item["has_poi"],
                    "has_roads": item["has_roads"],
                    "has_exits": item["has_exits"],
                    "poi_count": item["poi_count"],
                    "road_count": item["road_count"],
                    "exit_count": item["exit_count"],
                    "source": item["source"],
                    # для режима «точки» фронтенд размещает знак по центроиду
                    "centroid": [item["longitude"], item["latitude"]],
                },
                item["id"],
            )
        )
    return _collection(features)


def poi_geojson(db, park_id=None, poi_types=None):
    where = ["TRUE"]
    params = {}
    if park_id is not None:
        where.append("i.park_id = :park_id")
        params["park_id"] = park_id
    if poi_types:
        where.append("i.poi_type = ANY(:types)")
        params["types"] = list(poi_types)

    rows = db.execute(
        text(
            """
            SELECT i.id, i.park_id, i.poi_type, i.name, i.description,
                   i.latitude, i.longitude, i.source, p.name AS park_name,
                   ST_AsGeoJSON(i.geometry) AS gj
            FROM poi i
            JOIN parks p ON p.id = i.park_id
            WHERE %s
            ORDER BY i.poi_type, i.name
            """
            % " AND ".join(where)
        ),
        params,
    ).fetchall()

    features = []
    for row in rows:
        item = dict(row._mapping)
        features.append(
            _feature(
                item.pop("gj"),
                {
                    "id": item["id"],
                    "park_id": item["park_id"],
                    "park_name": item["park_name"],
                    "poi_type": item["poi_type"],
                    "poi_type_label": POI_LABELS.get(item["poi_type"], item["poi_type"]),
                    "icon": POI_ICONS.get(item["poi_type"], "•"),
                    "color": POI_COLORS.get(item["poi_type"], "#607d8b"),
                    "name": item["name"],
                    "description": item["description"],
                    "latitude": item["latitude"],
                    "longitude": item["longitude"],
                    "source": item["source"],
                },
                item["id"],
            )
        )
    return _collection(features)


def roads_geojson(db, park_id=None):
    params = {}
    where = "TRUE"
    if park_id is not None:
        where = "r.park_id = :park_id"
        params["park_id"] = park_id

    rows = db.execute(
        text(
            """
            SELECT r.id, r.park_id, r.road_type, r.name, r.length_m, r.source,
                   p.name AS park_name, ST_AsGeoJSON(r.geometry) AS gj
            FROM park_roads r
            JOIN parks p ON p.id = r.park_id
            WHERE %s
            ORDER BY r.road_type, r.id
            """
            % where
        ),
        params,
    ).fetchall()

    features = []
    for row in rows:
        item = dict(row._mapping)
        features.append(
            _feature(
                item.pop("gj"),
                {
                    "id": item["id"],
                    "park_id": item["park_id"],
                    "park_name": item["park_name"],
                    "road_type": item["road_type"],
                    "road_type_label": ROAD_LABELS.get(item["road_type"], item["road_type"]),
                    "name": item["name"],
                    "length_m": item["length_m"],
                    "source": item["source"],
                },
                item["id"],
            )
        )
    return _collection(features)


def exits_geojson(db, park_id=None):
    params = {}
    where = "TRUE"
    if park_id is not None:
        where = "e.park_id = :park_id"
        params["park_id"] = park_id

    rows = db.execute(
        text(
            """
            SELECT e.id, e.park_id, e.exit_type, e.name,
                   e.latitude, e.longitude, e.rotation_deg, e.source,
                   p.name AS park_name, ST_AsGeoJSON(e.geometry) AS gj
            FROM park_exits e
            JOIN parks p ON p.id = e.park_id
            WHERE %s
            ORDER BY e.exit_type, e.id
            """
            % where
        ),
        params,
    ).fetchall()

    features = []
    for row in rows:
        item = dict(row._mapping)
        features.append(
            _feature(
                item.pop("gj"),
                {
                    "id": item["id"],
                    "park_id": item["park_id"],
                    "park_name": item["park_name"],
                    "exit_type": item["exit_type"],
                    "name": item["name"],
                    "latitude": item["latitude"],
                    "longitude": item["longitude"],
                    "rotation_deg": item["rotation_deg"],
                    "source": item["source"],
                },
                item["id"],
            )
        )
    return _collection(features)


def districts_geojson(db):
    rows = db.execute(
        text("SELECT id, name, source, ST_AsGeoJSON(geometry) AS gj FROM districts")
    ).fetchall()
    features = []
    for row in rows:
        item = dict(row._mapping)
        features.append(
            _feature(item.pop("gj"), {"id": item["id"], "name": item["name"], "source": item["source"]}, item["id"])
        )
    return _collection(features)
