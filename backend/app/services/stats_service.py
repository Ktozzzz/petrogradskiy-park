# -*- coding: utf-8 -*-
"""Статистика и пространственная аналитика.

Все агрегаты выполняются средствами SQL/PostGIS (SUM, avg, FILTER,
пространственные функции), Python только форматирует ответ.
"""
from sqlalchemy import text

from . import spatial


def _fetch(db, sql, params=None):
    row = db.execute(text(sql), params or {}).first()
    return dict(row._mapping) if row else {}


def _fetch_all(db, sql, params=None):
    return [dict(r._mapping) for r in db.execute(text(sql), params or {}).fetchall()]


def basic_statistics(db):
    by_category = _fetch_all(
        db,
        """
        SELECT p.category,
               count(*) AS count,
               coalesce(sum(p.area_sqm), 0) AS area_sum_sqm,
               coalesce(avg(p.area_sqm), 0) AS area_avg_sqm
        FROM parks p
        GROUP BY p.category
        ORDER BY count DESC
        """,
    )
    poi_by_type = _fetch_all(
        db,
        "SELECT poi_type, count(*) AS count FROM poi GROUP BY poi_type ORDER BY count DESC",
    )
    roads = _fetch(
        db,
        "SELECT count(*) AS roads_total, coalesce(sum(length_m), 0) AS roads_length_m FROM park_roads",
    )
    exits = _fetch(db, "SELECT count(*) AS exits_total FROM park_exits")
    totals = _fetch(
        db,
        """
        SELECT count(*) AS parks_total,
               coalesce(sum(area_sqm), 0) AS area_total_sqm
        FROM parks
        """,
    )
    poi_total = db.execute(text("SELECT count(*) FROM poi")).scalar() or 0

    avg_nn = db.execute(
        text(
            """
            SELECT coalesce(avg(d), 0) FROM (
                SELECT (SELECT min(ST_Distance(a.centroid::geography, b.centroid::geography))
                        FROM parks b WHERE b.id <> a.id) AS d
                FROM parks a
            ) s
            """
        )
    ).scalar() or 0

    densest = _fetch_all(
        db,
        """
        SELECT floor(p.longitude / 0.004)::int AS cell_x,
               floor(p.latitude / 0.003)::int AS cell_y,
               count(*) AS count,
               avg(p.latitude) AS center_lat,
               avg(p.longitude) AS center_lon
        FROM parks p
        GROUP BY 1, 2
        HAVING count(*) > 1
        ORDER BY count DESC
        LIMIT 5
        """,
    )

    return {
        "parks_total": int(totals.get("parks_total") or 0),
        "area_total_sqm": float(totals.get("area_total_sqm") or 0),
        "by_category": by_category,
        "poi_total": int(poi_total),
        "poi_by_type": poi_by_type,
        "roads_total": int(roads.get("roads_total") or 0),
        "roads_length_m": float(roads.get("roads_length_m") or 0),
        "exits_total": int(exits.get("exits_total") or 0),
        "avg_nearest_neighbor_m": float(avg_nn),
        "densest_zones": densest,
    }


def coverage_analysis(db, step_m=100, distance_m=500):
    """Coverage Analysis: доля территории района в пешей доступности.

    Район разбивается на регулярную сетку (шаг задаётся), для каждой
    точки сетки внутри границы вычисляется расстояние до ближайшего
    объекта средствами PostGIS.
    """
    bounds = _fetch(
        db,
        """
        SELECT ST_XMin(geometry) AS minx, ST_YMin(geometry) AS miny,
               ST_XMax(geometry) AS maxx, ST_YMax(geometry) AS maxy
        FROM districts
        ORDER BY id
        LIMIT 1
        """,
    )
    if not bounds:
        return {"step_m": step_m, "distance_m": distance_m, "cells_total": 0, "cells_covered": 0, "covered_pct": 0.0}

    import math

    lat_center = (bounds["miny"] + bounds["maxy"]) / 2.0
    dx_deg = step_m / (111320.0 * math.cos(math.radians(lat_center)))
    dy_deg = step_m / 111320.0
    nx = max(1, int((bounds["maxx"] - bounds["minx"]) / dx_deg))
    ny = max(1, int((bounds["maxy"] - bounds["miny"]) / dy_deg))

    row = _fetch(
        db,
        """
        WITH grid AS (
            SELECT ST_SetSRID(ST_MakePoint(:minx + k * :dx, :miny + l * :dy), 4326) AS pt
            FROM generate_series(0, :nx) AS k, generate_series(0, :ny) AS l
        ),
        inside AS (
            SELECT g.pt FROM grid g, districts d
            WHERE ST_Intersects(g.pt, d.geometry)
        ),
        dist AS (
            SELECT i.pt,
                   (SELECT min(ST_Distance(i.pt::geography, p.centroid::geography))
                    FROM parks p) AS d
            FROM inside i
        )
        SELECT count(*) AS cells_total,
               count(*) FILTER (WHERE d <= :dist) AS cells_covered,
               coalesce(avg(d), 0) AS avg_distance_m,
               coalesce(max(d), 0) AS max_distance_m
        FROM dist
        """,
        {
            "minx": bounds["minx"],
            "miny": bounds["miny"],
            "dx": dx_deg,
            "dy": dy_deg,
            "nx": nx,
            "ny": ny,
            "dist": distance_m,
        },
    )
    total = int(row.get("cells_total") or 0)
    covered = int(row.get("cells_covered") or 0)
    return {
        "step_m": step_m,
        "distance_m": distance_m,
        "grid_size": [nx + 1, ny + 1],
        "cells_total": total,
        "cells_covered": covered,
        "covered_pct": round(covered * 100.0 / total, 1) if total else 0.0,
        "avg_distance_m": round(float(row.get("avg_distance_m") or 0), 1),
        "max_distance_m": round(float(row.get("max_distance_m") or 0), 1),
    }


def radius_analysis(db, latitude, longitude, radius_m):
    """Radius Analysis: распределение объектов в радиусе по категориям."""
    items = spatial.radius_parks(db, latitude, longitude, radius_m, limit=500)
    by_category = {}
    for item in items:
        by_category[item["category"]] = by_category.get(item["category"], 0) + 1
    return {
        "center": {"latitude": latitude, "longitude": longitude},
        "radius_m": radius_m,
        "total": len(items),
        "by_category": [
            {"category": key, "count": value} for key, value in sorted(by_category.items())
        ],
    }


def category_distribution(db):
    """Пространственное распределение категорий по сетке района."""
    return _fetch_all(
        db,
        """
        SELECT p.category,
               floor(p.longitude / 0.004)::int AS cell_x,
               floor(p.latitude / 0.003)::int AS cell_y,
               count(*) AS count
        FROM parks p
        GROUP BY 1, 2, 3
        ORDER BY 1, 4 DESC
        """,
    )
