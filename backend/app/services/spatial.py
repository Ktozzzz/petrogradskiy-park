# -*- coding: utf-8 -*-
"""Пространственные запросы к PostGIS.

Все расстояния и пространственные отборы выполняются на стороне базы данных:
    * KNN-поиск ближайших      -- оператор `<->` + индекс GiST;
    * поиск в радиусе          -- ST_DWithin (грубый отбор по индексу)
                                  + точный расчёт ST_Distance(geography);
    * принадлежность территории -- ST_Within / ST_Intersects;
    * длина дорог               -- ST_Length(geography).

Python не перебирает объекты циклом: БД возвращает готовый отсортированный
результат (см. README, раздел «Пространственные запросы»).
"""
import math

from sqlalchemy import text

PARK_COLUMNS = """
    p.id, p.name, p.category, p.description, p.address, p.borough,
    p.latitude, p.longitude, p.area_sqm, p.is_free, p.working_hours, p.website,
    p.metro_stations, p.facilities, p.themes, p.keywords, p.source,
    p.has_poi, p.has_roads, p.has_exits,
    (SELECT count(*) FROM poi i WHERE i.park_id = p.id) AS poi_count,
    (SELECT count(*) FROM park_roads r WHERE r.park_id = p.id) AS road_count,
    (SELECT count(*) FROM park_exits e WHERE e.park_id = p.id) AS exit_count
"""

POINT = "ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)"


def _rows(db, sql, params):
    result = db.execute(text(sql), params)
    return [dict(row._mapping) for row in result.fetchall()]


def point_degrees_tolerance(radius_m):
    """Запас в градусах для грубого отбора по индексу.

    1 градус широты ~ 111.32 км, 1 градус долготы на широте Петроградского
    района (~59.96) ~ 55.8 км. Берём меньший метровый масштаб с запасом,
    чтобы точный отбор по географии ничего не потерял.
    """
    meters_per_degree = 111320.0 * math.cos(math.radians(59.96))  # ~55 700 м
    return radius_m / meters_per_degree * 1.15


# ---------------------------------------------------------------------
# Список объектов и фильтрация
# ---------------------------------------------------------------------
def list_parks(db, category=None, q=None, has_poi=None, poi_type=None,
               limit=20, offset=0):
    where = ["TRUE"]
    params = {"limit": limit, "offset": offset}
    if category:
        if isinstance(category, (list, tuple)):
            where.append("p.category = ANY(:categories)")
            params["categories"] = list(category)
        else:
            where.append("p.category = :category")
            params["category"] = category
    if q:
        where.append("(p.name ILIKE :q OR coalesce(p.description,'') ILIKE :q)")
        params["q"] = "%" + q + "%"
    if has_poi is not None:
        where.append("p.has_poi = :has_poi")
        params["has_poi"] = has_poi
    if poi_type:
        where.append(
            "EXISTS (SELECT 1 FROM poi i WHERE i.park_id = p.id AND i.poi_type = :poi_type)"
        )
        params["poi_type"] = poi_type

    where_sql = " AND ".join(where)
    total = db.execute(
        text("SELECT count(*) FROM parks p WHERE " + where_sql), params
    ).scalar()
    items = _rows(
        db,
        "SELECT %s FROM parks p WHERE %s ORDER BY p.name LIMIT :limit OFFSET :offset"
        % (PARK_COLUMNS, where_sql),
        params,
    )
    return int(total or 0), items


def get_park(db, park_id):
    rows = _rows(
        db,
        "SELECT %s FROM parks p WHERE p.id = :id" % PARK_COLUMNS,
        {"id": park_id},
    )
    return rows[0] if rows else None


def get_park_by_name(db, name):
    """Нечёткий поиск объекта по названию (pg_trgm)."""
    rows = _rows(
        db,
        """
        SELECT %s, similarity(p.name, :name) AS sim
        FROM parks p
        WHERE p.name %% :name OR p.name ILIKE :like
        ORDER BY sim DESC, length(p.name)
        LIMIT 1
        """
        % PARK_COLUMNS,
        {"name": name, "like": "%" + name + "%"},
    )
    return rows[0] if rows else None


def search_parks(db, q, limit=20):
    """Текстовый поиск по названию, описанию, темам и ключевым словам."""
    return _rows(
        db,
        """
        SELECT %s,
               GREATEST(
                   similarity(p.name, :q),
                   CASE WHEN coalesce(p.description,'') ILIKE :like THEN 0.4 ELSE 0 END,
                   CASE WHEN p.keywords::text ILIKE :like THEN 0.3 ELSE 0 END,
                   CASE WHEN p.themes::text ILIKE :like THEN 0.3 ELSE 0 END
               ) AS rank
        FROM parks p
        WHERE p.name %% :q OR p.name ILIKE :like
           OR coalesce(p.description,'') ILIKE :like
           OR p.keywords::text ILIKE :like
           OR p.themes::text ILIKE :like
        ORDER BY rank DESC, p.name
        LIMIT :limit
        """
        % PARK_COLUMNS,
        {"q": q, "like": "%" + q + "%", "limit": limit},
    )


# ---------------------------------------------------------------------
# Ближайшие объекты (KNN, индекс GiST)
# ---------------------------------------------------------------------
def nearby_parks(db, latitude, longitude, category=None, limit=10):
    params = {"lon": longitude, "lat": latitude, "limit": limit}
    cat_filter = ""
    if category:
        cat_filter = "AND p.category = :category"
        params["category"] = category
    return _rows(
        db,
        (
            """
        SELECT %s,
               ST_Distance(p.geometry::geography, __POINT__::geography) AS distance_m
        FROM parks p
        WHERE TRUE %s
        ORDER BY p.geometry <-> __POINT__
        LIMIT :limit
        """
            .replace("__POINT__", POINT)
            % (PARK_COLUMNS, cat_filter)
        ),
        params,
    )


# ---------------------------------------------------------------------
# Поиск в радиусе (ST_DWithin + точный расчёт geography)
# ---------------------------------------------------------------------
def radius_parks(db, latitude, longitude, radius_m, category=None, limit=50):
    params = {
        "lon": longitude,
        "lat": latitude,
        "radius": radius_m,
        "deg": point_degrees_tolerance(radius_m),
        "limit": limit,
    }
    cat_filter = ""
    if category:
        cat_filter = "AND p.category = :category"
        params["category"] = category
    return _rows(
        db,
        (
            """
        WITH cand AS (
            SELECT %s,
                   ST_Distance(p.geometry::geography, __POINT__::geography) AS distance_m
            FROM parks p
            WHERE ST_DWithin(p.geometry, __POINT__, :deg) %s
        )
        SELECT * FROM cand
        WHERE distance_m <= :radius
        ORDER BY distance_m
        LIMIT :limit
        """
            .replace("__POINT__", POINT)
            % (PARK_COLUMNS, cat_filter)
        ),
        params,
    )


# ---------------------------------------------------------------------
# Расстояния
# ---------------------------------------------------------------------
def nearest_park(db, latitude, longitude, category=None):
    params = {"lon": longitude, "lat": latitude}
    cat_filter = ""
    if category:
        cat_filter = "AND p.category = :category"
        params["category"] = category
    rows = _rows(
        db,
        (
            """
        SELECT %s,
               ST_Distance(p.geometry::geography, __POINT__::geography) AS distance_m
        FROM parks p
        WHERE TRUE %s
        ORDER BY p.geometry <-> __POINT__
        LIMIT 1
        """
            .replace("__POINT__", POINT)
            % (PARK_COLUMNS, cat_filter)
        ),
        params,
    )
    return rows[0] if rows else None


def distance_between_parks(db, id_a, id_b):
    """Расстояние между контурами двух объектов (metres, geography)."""
    row = db.execute(
        text(
            """
            SELECT ST_Distance(a.geometry::geography, b.geometry::geography) AS distance_m
            FROM parks a, parks b
            WHERE a.id = :a AND b.id = :b
            """
        ),
        {"a": id_a, "b": id_b},
    ).first()
    return float(row[0]) if row else None


# ---------------------------------------------------------------------
# Принадлежность территории (ST_Within / ST_Contains)
# ---------------------------------------------------------------------
def point_in_district(db, latitude, longitude):
    return bool(
        db.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1 FROM districts d
                    WHERE ST_Contains(d.geometry, %(point)s)
                )
                """
                % {"point": POINT}
            ),
            {"lon": longitude, "lat": latitude},
        ).scalar()
    )


def point_in_park(db, latitude, longitude, park_id):
    return bool(
        db.execute(
            text(
                """
                SELECT EXISTS (
                    SELECT 1 FROM parks p
                    WHERE p.id = :id AND ST_Contains(p.geometry, %(point)s)
                )
                """
                % {"point": POINT}
            ),
            {"id": park_id, "lon": longitude, "lat": latitude},
        ).scalar()
    )


def district_geometry(db):
    row = db.execute(
        text("SELECT name, ST_AsGeoJSON(geometry) AS gj FROM districts LIMIT 1")
    ).first()
    if not row:
        return None, None
    return row[0], row[1]


# ---------------------------------------------------------------------
# Связанные слои объекта
# ---------------------------------------------------------------------
def park_poi(db, park_id, poi_type=None):
    params = {"park_id": park_id}
    cond = "AND i.poi_type = :poi_type" if poi_type else ""
    if poi_type:
        params["poi_type"] = poi_type
    return _rows(
        db,
        """
        SELECT i.id, i.park_id, i.poi_type, i.name, i.description,
               i.latitude, i.longitude, i.source
        FROM poi i
        WHERE i.park_id = :park_id %s
        ORDER BY i.poi_type, i.name
        """
        % cond,
        params,
    )


def park_roads(db, park_id):
    return _rows(
        db,
        """
        SELECT r.id, r.park_id, r.road_type, r.name, r.length_m, r.source
        FROM park_roads r
        WHERE r.park_id = :park_id
        ORDER BY r.road_type, r.id
        """,
        {"park_id": park_id},
    )


def park_exits(db, park_id):
    return _rows(
        db,
        """
        SELECT e.id, e.park_id, e.exit_type, e.name,
               e.latitude, e.longitude, e.source
        FROM park_exits e
        WHERE e.park_id = :park_id
        ORDER BY e.exit_type, e.id
        """,
        {"park_id": park_id},
    )


# ---------------------------------------------------------------------
# «Что рядом?» -- объекты в радиусе от центроида объекта
# ---------------------------------------------------------------------
def objects_in_radius_from_park(db, park_id, radius_m):
    return _rows(
        db,
        """
        SELECT %s,
               ST_Distance(
                   p.geometry::geography,
                   (SELECT centroid FROM parks WHERE id = :park_id)::geography
               ) AS distance_m
        FROM parks p
        WHERE p.id <> :park_id
          AND ST_DWithin(
              p.geometry,
              (SELECT centroid FROM parks WHERE id = :park_id),
              :deg
          )
        ORDER BY distance_m
        LIMIT 50
        """
        % PARK_COLUMNS,
        {"park_id": park_id, "deg": point_degrees_tolerance(radius_m)},
    )


def poi_counts_near_park(db, park_id, radius_m):
    """Группировка «что рядом» по категориям."""
    return _rows(
        db,
        """
        SELECT p.category, count(*) AS count
        FROM parks p
        WHERE p.id <> :park_id
          AND ST_DWithin(
              p.geometry,
              (SELECT centroid FROM parks WHERE id = :park_id),
              :deg
          )
        GROUP BY p.category
        ORDER BY count DESC
        """,
        {"park_id": park_id, "deg": point_degrees_tolerance(radius_m)},
    )
