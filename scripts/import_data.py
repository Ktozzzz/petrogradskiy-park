# -*- coding: utf-8 -*-
"""Этап 2. ETL: обработка данных OpenStreetMap и загрузка в PostGIS.

Вход:  data/raw/*.json  (сырые ответы Overpass API)
Выход: data/processed/*.geojson + наполненная база данных.

Этапы:
    1. граница района (polygon layer);
    2. парки, сады, скверы, бульвары -- полигоны, валидация (ST_IsValid),
       удаление дубликатов, отбор по принадлежности району;
    3. точки интереса -- отбор внутри контуров объектов;
    4. внутренние дороги -- обрезка по контуру, нормализация типов;
    5. входы и выходы -- отбор по контуру и границе;
    6. географические названия (справочник для Location Resolver);
    7. загрузка в PostGIS, центроиды (ST_Centroid), производные поля;
    8. экспорт GeoJSON + отчёт о количествах.

Запуск:
    python scripts/import_data.py
    python scripts/import_data.py --skip-db      (только GeoJSON, без загрузки)
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

from shapely.geometry import LineString, MultiPolygon, Point, Polygon, mapping, shape
from shapely.ops import linemerge, polygonize, unary_union
from shapely.strtree import STRtree
from sqlalchemy import create_engine, text

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW_DIR = os.path.join(ROOT, "data", "raw")
PROC_DIR = os.path.join(ROOT, "data", "processed")

sys.path.insert(0, os.path.join(ROOT, "backend"))
from app import config  # noqa: E402

SOURCE = "OpenStreetMap"

# Целевые объёмы (ТЗ): парки >= 60, точки интереса >= 300,
# дороги >= 500, входы/выходы >= 150.
TARGETS = {"parks": 60, "poi": 300, "roads": 500, "exits": 150}

# Если контур района меньше этой площади — считаем его неполным и берём рамку.
MIN_DISTRICT_KM2 = 5.0

BOULEVARD_RE = re.compile(r"бульвар|аллея", re.I)
GREEN_NAME_RE = re.compile(r"сквер|сад|парк|аллея|бульвар|площадь|озелен|боскет|цветник|ротонда|грот", re.I)

FOOD = ("cafe", "restaurant", "fast_food", "ice_cream", "kiosk", "bar", "pub")
PLAYGROUND = ("playground",)
SPORT = ("pitch", "fitness_centre", "track", "swimming_pool", "stadium", "sports_centre")
MONUMENT = ("memorial", "memorial_plaque", "monument", "sculpture", "artwork", "castle", "ruins")
ATTRACTION = ("attraction", "theme_park", "artwork", "picnic_site", "viewpoint")


def log(message):
    print(message, flush=True)


# ---------------------------------------------------------------------
# Метрические измерения (градусы -> метры через UTM зону 36N)
# ---------------------------------------------------------------------
try:
    from pyproj import Transformer
    from shapely.ops import transform as shapely_transform

    _TO_METRIC = Transformer.from_crs("EPSG:4326", "EPSG:32636", always_xy=True).transform
    _TO_WGS84 = Transformer.from_crs("EPSG:32636", "EPSG:4326", always_xy=True).transform

    def to_metric(geom):
        """Геометрия в метрах (проекция UTM 36N)."""
        return shapely_transform(_TO_METRIC, geom)

    def distance_m(geom_a, geom_b):
        """Минимальное расстояние между геометриями в метрах."""
        return to_metric(geom_a).distance(to_metric(geom_b))

    def length_m(geom):
        """Длина линии в метрах."""
        return to_metric(geom).length

    def buffer_m(geom, meters, cap_style=2, join_style=2):
        """Буферизация линии в метрах (результат в градусах)."""
        buffered = to_metric(geom).buffer(meters, cap_style=cap_style, join_style=join_style)
        return shapely_transform(_TO_WGS84, buffered)
except ImportError:  # pyproj обязателен, но защищаем импорт скрипта
    def to_metric(geom):
        return geom

    def distance_m(geom_a, geom_b):
        return geom_a.distance(geom_b)

    def length_m(geom):
        return geom.length

    def buffer_m(geom, meters, cap_style=2, join_style=2):
        return geom.buffer(meters / 100000.0, cap_style=cap_style, join_style=join_style)


# ---------------------------------------------------------------------
# Геометрия
# ---------------------------------------------------------------------
def way_geometry(element):
    geom = element.get("geometry") or []
    if len(geom) < 2:
        return None
    coords = [(pt["lon"], pt["lat"]) for pt in geom]
    if coords[0] == coords[-1] and len(coords) >= 4:
        poly = Polygon(coords)
        if not poly.is_valid:
            poly = poly.buffer(0)
        return poly if not poly.is_empty else None
    return LineString(coords)


def _safe_union(geoms):
    """Объединение полигонов с восстановлением топологии.

    Отдельные отношения OSM содержат самопересекающиеся контуры, из-за чего
    unary_union может выбросить TopologyException; такие геометрии чиним
    буферизацией нулевым радиусом.
    """
    try:
        merged = unary_union(geoms)
    except Exception:  # noqa: BLE001 - топологические ошибки сырой геометрии OSM
        fixed = []
        for geom in geoms:
            if not geom.is_valid:
                geom = geom.buffer(0)
            if not geom.is_empty:
                fixed.append(geom)
        merged = unary_union(fixed) if fixed else None
    if merged is not None and not merged.is_valid:
        merged = merged.buffer(0)
    return merged


def fill_holes(multipolygon):
    """Заполняет внутренние кольца полигона.

    В OSM внутри парков отдельно размечены здания и водоёмы (role=inner),
    из-за чего территория парка «дырявится». По ТЗ здания и водные объекты
    на территории парка должны покрываться полигоном парка — снимаем дыры.
    """
    if multipolygon is None or multipolygon.is_empty:
        return multipolygon
    polys = (list(multipolygon.geoms)
             if multipolygon.geom_type == "MultiPolygon" else [multipolygon])
    filled = []
    for poly in polys:
        if poly.is_empty:
            continue
        try:
            filled.append(Polygon(poly.exterior))
        except Exception:  # noqa: BLE001 - битое кольцо, берём как есть
            filled.append(poly)
    if not filled:
        return multipolygon
    united = _safe_union(filled)
    if united is None or united.is_empty:
        return multipolygon
    return as_multipolygon(united) if united is not None else multipolygon


def unify_parts(geom, gaps=(10, 15, 25, 35, 45), max_growth=0.30):
    """Стягивает разрозненные части одного объекта в fewer полигонов.

    Крупные парки в OSM размечены множеством отдельных участков, разделённых
    внутренними дорожками/тропинками, и отображаются «кучей полигонов».
    Морфологическое замыкание (buffer(+g) → buffer(−g)) соединяет такие
    участки, заполняя промежутки между ними, при этом внешняя граница почти
    не меняется (растёт только счёт внутренних дорожек, ставших парком).
    Применяется только к.multipart объектам и не даёт площади вырасти
    сильнее max_growth.
    """
    if geom is None or geom.is_empty or geom.geom_type != "MultiPolygon":
        return geom
    if len(geom.geoms) <= 1:
        return geom
    metric = to_metric(geom)
    base = metric.area
    if base <= 0:
        return geom
    best = geom
    for gap in gaps:
        closed = metric.buffer(gap).buffer(-gap)
        if closed.is_empty:
            continue
        if (closed.area - base) / base > max_growth:
            break  # дальше граница раздувается слишком сильно
        try:
            candidate = as_multipolygon(shapely_transform(_TO_WGS84, closed))
        except Exception:  # noqa: BLE001 - битая топология после замыкания
            continue
        if candidate is None or candidate.is_empty or not candidate.is_valid:
            continue
        best = candidate
        if len(candidate.geoms) == 1:
            break
    return best if best is not None and not best.is_empty else geom


def arrow_rotation(polygon, point):
    """Совмещает точку входа/выхода с границей и считает угол стрелки.

    Возвращает (snap_point, rotation_deg). Точка проецируется на ближайший
    отрезок внешней границы (чтобы стрелка не стояла внутри полигона), а
    rotation_deg — азимут (от севера, по часовой) нормали к границе, смотрящий
    наружу. Стрелка «⟶» в Leaflet смотрит вправо (восток, азимут 90°),
    поэтому фронтенд повернёт её на (rotation_deg - 90).
    """
    import math

    from shapely.ops import nearest_points

    if polygon is None or polygon.is_empty:
        return point, 0.0
    # внешнее кольцо самой крупной части
    part = max(polygon.geoms, key=lambda g: g.area) if polygon.geom_type == "MultiPolygon" else polygon
    ring = getattr(part, "exterior", None)
    if ring is None:
        return point, 0.0
    ring_coords = list(ring.coords)

    # ближайший отрезок кольца к точке
    best = None
    for i in range(len(ring_coords) - 1):
        seg = LineString([ring_coords[i], ring_coords[i + 1]])
        if seg.length == 0:
            continue
        d = seg.distance(point)
        if best is None or d < best[0]:
            best = (d, seg, ring_coords[i], ring_coords[i + 1])
    if best is None:
        return point, 0.0
    _d, seg, p1, p2 = best
    snap = nearest_points(seg, point)[0]

    lat0 = math.radians(snap.y)
    # касательная в плоских метриках (масштаб по долготе учитываем)
    tx = (p2[0] - p1[0]) * math.cos(lat0)
    ty = (p2[1] - p1[1])
    if tx == 0 and ty == 0:
        return snap, 0.0
    # нормаль (поворот касательной на 90°)
    nx, ny = -ty, tx
    norm = math.hypot(nx, ny)
    nx, ny = nx / norm, ny / norm
    # проверяем направление: делаем шаг наружу от границы
    eps = 0.00003  # ~3 м
    probe = Point(snap.x + nx * eps, snap.y + ny * eps)
    if part.covers(probe):  # нормаль смотрит внутрь — разворачиваем
        nx, ny = -nx, -ny
    bearing = (math.degrees(math.atan2(nx, ny)) + 360.0) % 360.0
    rotation = (bearing - 90.0) % 360.0
    return snap, rotation


def relation_geometry(element):
    outer_lines, inner_lines = [], []
    for member in element.get("members") or []:
        geometry = member.get("geometry") or []
        if len(geometry) < 2:
            continue
        coords = [(pt["lon"], pt["lat"]) for pt in geometry]
        # Замкнутая линия остаётся кольцом; открытый отрезок границы не
        # замыкаем на себя — linemerge/polygonize соединят отрезки в контур.
        # Раньше отрезки из двух точек отбрасывались и замыкались на себя,
        # из-за чего граница района и парков строилась неполной.
        if len(coords) < 2:
            continue
        line = LineString(coords)
        if member.get("role") == "inner":
            inner_lines.append(line)
        else:
            outer_lines.append(line)
    if not outer_lines:
        return None
    try:
        # Важно: сначала объединяем линии (это «расщепляет» их в точках
        # пересечения), иначе polygonize не замкнет кольца границы района.
        noded = unary_union(outer_lines)
        merged = linemerge(noded)
        pieces = list(polygonize(merged))
    except Exception:  # noqa: BLE001 - битая топология отношения
        return None
    if not pieces:
        # Граница состоит из отрезков с разрывами (типично для районов,
        # границы которых идут по рекам): замыкаем их буферизацией.
        try:
            closed = linemerge(noded).buffer(0.00005)
            outer = _safe_union([closed]) if not closed.is_empty else None
        except Exception:  # noqa: BLE001
            outer = None
        if outer is None or outer.is_empty:
            return None
    else:
        outer = _safe_union(pieces)
        if outer is None or outer.is_empty:
            return None
        if inner_lines:
            try:
                holes = _safe_union(list(polygonize(linemerge(unary_union(inner_lines)))))
                if holes is not None and not holes.is_empty:
                    outer = outer.difference(holes)
            except Exception:  # noqa: BLE001 - «внутренние» пути не обязательны
                pass
        if not outer.is_valid:
            outer = outer.buffer(0)
    return outer if not outer.is_empty else None


def district_geometry(district_raw, subarea_raw=None):
    """Лучший доступный контур района.

    Приоритет: подчинённые отношения (subarea) с полной территорией ->
    верхнеуровневое отношение границы -> прямоугольная рамка проекта.
    """
    if subarea_raw:
        geom = _union_relations_geom(subarea_raw)
        if geom is not None:
            return geom
    if district_raw:
        geom = _union_relations_geom(district_raw)
        if geom is not None:
            return geom
    return None


def _union_relations_geom(raw):
    """Объединённый контур всех отношений файла Overpass."""
    parts = []
    for element in (raw or {}).get("elements", []):
        if element.get("type") != "relation":
            continue
        geom = relation_geometry(element)
        if geom is not None and not geom.is_empty:
            parts.append(geom)
    if not parts:
        return None
    merged = _safe_union(parts)
    return merged if merged is not None and not merged.is_empty else None


def _area_km2(geom):
    """Площадь геометрии в км² через тип geography (точный пересчёт)."""
    if geom is None or geom.is_empty:
        return 0.0
    from sqlalchemy import create_engine, text as sql_text
    from app import config as _config

    engine = create_engine(_config.DATABASE_URL, future=True)
    try:
        with engine.connect() as conn:
            gj = geojson_str(geom)
            area = conn.execute(
                sql_text(
                    "SELECT ST_Area(ST_SetSRID(ST_GeomFromGeoJSON(:gj), 4326)::geography)"
                ),
                {"gj": gj},
            ).scalar()
        return float(area or 0) / 1_000_000.0
    except Exception:  # noqa: BLE001 - без БД берём грубую оценку по градусам
        return geom.area * 60.0
    finally:
        engine.dispose()


def as_multipolygon(geom):
    if geom is None or geom.is_empty:
        return None
    if geom.geom_type == "Polygon":
        return MultiPolygon([geom])
    if geom.geom_type == "MultiPolygon":
        return geom
    if geom.geom_type == "GeometryCollection":
        polys = [g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
        if not polys:
            return None
        merged = unary_union(polys)
        return as_multipolygon(merged)
    return None


def polygonize_element(element):
    if element["type"] == "way":
        geom = way_geometry(element)
    elif element["type"] == "relation":
        geom = relation_geometry(element)
    else:
        geom = None
    if isinstance(geom, (Polygon, MultiPolygon)):
        return as_multipolygon(geom)
    return None


def point_of(element):
    if element["type"] == "node":
        return Point(element["lon"], element["lat"])
    geometry = element.get("geometry") or []
    if not geometry:
        return None
    if element["type"] == "way":
        coords = [(pt["lon"], pt["lat"]) for pt in geometry]
        if coords[0] == coords[-1] and len(coords) >= 4:
            return Polygon(coords).centroid
        return LineString(coords).centroid
    return None


# ---------------------------------------------------------------------
# Классификация
# ---------------------------------------------------------------------
def has_vegetation(tags):
    """Есть ли у объекта признаки растительности (зелени).

    Мощёные городские площади (place=square) без зелени — не скверы, их не
    отображаем в категории «Скверы» (по требованию заказчика).
    """
    return (
        tags.get("leisure") in ("garden", "park", "nature_reserve")
        or tags.get("landuse") in ("grass", "forest", "meadow", "village_green",
                                   "recreation_ground", "orchard")
        or tags.get("natural") in ("wood", "scrub", "grassland", "meadow")
        or tags.get("garden:type") is not None
        or tags.get("trees") is not None
        or tags.get("plant") is not None
    )


def classify_park(tags, name):
    leisure = tags.get("leisure")
    place = tags.get("place")
    landuse = tags.get("landuse")
    natural = tags.get("natural")

    # Имя приоритетнее тега leisure: скверы и сады в OSM часто размечены как
    # leisure=park. Уточняем категорию по названию объекта.
    if name:
        low = name.lower()
        if "сквер" in low:
            return "square"
        if BOULEVARD_RE.search(low):
            return "boulevard"
        if re.search(r"\bсад\b|садик|сады", low):
            return "garden"
        if "парк" in low:
            return "park"

    if name and BOULEVARD_RE.search(name):
        return "boulevard"
    if leisure == "park":
        return "park"
    if leisure == "garden":
        return "garden"
    if leisure in ("square", "common"):
        return "square"
    if place == "square":
        # Мощёные городские площади без зелени (напр. «Австрийская площадь»)
        # скверами не являются — не отображаем.
        return "square" if has_vegetation(tags) else None
    if landuse in ("grass", "forest", "recreation_ground", "village_green", "meadow") and name \
            and GREEN_NAME_RE.search(name):
        return "square"
    if natural in ("scrub", "wood", "grassland") and name and GREEN_NAME_RE.search(name):
        return "square"
    return None


def classify_poi(tags):
    amenity = tags.get("amenity")
    tourism = tags.get("tourism")
    historic = tags.get("historic")
    leisure = tags.get("leisure")

    if amenity in FOOD:
        return "food"
    if amenity == "fountain" or tags.get("fountain"):
        return "fountain"
    if amenity in ("drinking_water", "water_point"):
        return "fountain"
    if amenity == "toilet":
        return "toilet"
    if amenity == "parking" or tags.get("amenity") == "parking_entrance":
        return "parking"
    if leisure == "playground":
        return "playground"
    if leisure in SPORT or tags.get("sport"):
        return "sport"
    if leisure in ("bowling_alley", "golf_course", "escape_game", "fitness_station"):
        return "sport"
    if tourism == "viewpoint" or tags.get("viewpoint"):
        return "viewpoint"
    if historic in MONUMENT:
        return "monument"
    if tourism in ATTRACTION:
        return "attraction"
    if amenity in ("shelter", "picnic_table", "bbq", "firepit", "bicycle_rental",
                   "vending_machine", "arts_centre", "community_centre"):
        return "attraction"
    if tourism in ("museum", "gallery", "information", "artwork", "theme_park"):
        return "attraction"
    if tags.get("memorial") or tags.get("sculpture") or tags.get("artwork_type"):
        return "monument" if historic or tags.get("memorial") else "attraction"
    return None


def classify_road(tags):
    highway = tags.get("highway") or ""
    if highway in ("motorway", "trunk", "primary", "secondary", "tertiary",
                   "residential", "living_street", "pedestrian"):
        return "main"
    if highway in ("service", "track"):
        return "service"
    if highway in ("cycleway", "bridleway"):
        return "bike"
    if highway in ("footway", "path", "steps", "footpath"):
        return "path"
    return None


def load_json(name):
    path = os.path.join(RAW_DIR, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save_geojson(name, features):
    path = os.path.join(PROC_DIR, name + ".geojson")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": features}, fh, ensure_ascii=False)
    return path


def geojson_str(geom):
    return json.dumps(mapping(geom), ensure_ascii=False)


def build_description(name, category, tags, area_sqm, poi_types, facilities, road_length):
    """Фактическое описание, собранное из атрибутов OpenStreetMap."""
    labels = {"park": "Парк", "garden": "Сад", "square": "Сквер", "boulevard": "Бульвар"}
    parts = ["%s в Петроградском районе Санкт-Петербурга." % labels.get(category, "Объект")]
    if tags.get("description"):
        parts.append(tags["description"])
    facts = []
    if area_sqm:
        facts.append("площадь %.1f га" % (area_sqm / 10000.0))
    if road_length:
        facts.append("прогулочные дорожки — %.0f м" % road_length)
    if poi_types:
        facts.append("точки интереса: " + ", ".join(sorted(poi_types)))
    if facilities:
        parts.append("Удобства: " + ", ".join(facilities) + ".")
    if facts:
        parts.append("Характеристики: " + "; ".join(facts) + ".")
    if tags.get("heritage"):
        parts.append("Объект культурного наследия.")
    return " ".join(parts)


def derive_facilities(poi_types):
    mapping_ = {
        "playground": "детская площадка",
        "food": "кафе",
        "toilet": "туалет",
        "parking": "парковка",
        "sport": "спортивная площадка",
        "fountain": "фонтан",
        "monument": "памятники и скульптуры",
        "viewpoint": "смотровая площадка",
        "attraction": "аттракционы",
    }
    return [mapping_[t] for t in sorted(poi_types) if t in mapping_]


def derive_themes(category, facilities, poi_types):
    base = {
        "park": ["прогулки", "отдых на природе", "зелёная зона"],
        "garden": ["прогулки", "уход за растениями", "зелёная зона"],
        "square": ["прогулки", "городское озеленение"],
        "boulevard": ["прогулки", "маршрут", "зелёная зона"],
    }.get(category, ["прогулки"])
    extra = list(facilities)
    if "monument" in poi_types:
        extra.append("памятники и искусство")
    if "sport" in poi_types:
        extra.append("спорт")
    if "playground" in poi_types:
        extra.append("семейный отдых")
    return base + extra


def derive_keywords(name, category, tags, poi_types, facilities):
    words = set()
    for token in re.split(r"[^0-9A-Za-zА-Яа-яЁё]+", name or ""):
        if len(token) > 3:
            words.add(token.lower())
    for key in ("historic", "heritage", "memorial", "sport", "material", "surface",
                "plant", "denomination", "cuisine"):
        value = tags.get(key)
        if value and len(value) < 40:
            words.add(value.split(";")[0].lower())
    words.update(facilities)
    words.update(poi_types)
    return sorted(w for w in words if w)[:20]


def iou(a, b):
    try:
        inter = a.intersection(b).area
        union = a.union(b).area
        return inter / union if union else 0.0
    except Exception:  # noqa: BLE001
        return 0.0


def main():
    parser = argparse.ArgumentParser(description="Импорт данных OSM в PostGIS")
    parser.add_argument("--skip-db", action="store_true", help="не загружать данные в базу")
    args = parser.parse_args()

    os.makedirs(PROC_DIR, exist_ok=True)

    # ---------------- 1. граница района ----------------------------
    district_geom = None
    district_name = "Петроградский район"
    district_raw = load_json("district.json")
    subarea_raw = load_json("district_subareas.json")
    district_geom = district_geometry(district_raw, subarea_raw)
    if district_raw and district_raw.get("elements"):
        district_name = district_raw["elements"][0].get("tags", {}).get("name", district_name)
    if district_geom is None or _area_km2(district_geom) < MIN_DISTRICT_KM2:
        log("ВНИМАНИЕ: контур района неполный (%s км2), используется рамка проекта." % (
            ("%.2f" % _area_km2(district_geom)) if district_geom else "нет"))
        district_geom = as_multipolygon(Polygon([
            (30.24, 59.93), (30.35, 59.93), (30.35, 59.99), (30.24, 59.99), (30.24, 59.93)
        ]))
        district_name = "Петроградский район (рамка проекта)"
    district_area_km2 = _area_km2(district_geom)
    log("Граница района: %s, площадь %.1f км2" % (district_name, district_area_km2))

    # ---------------- 2. парки, сады, скверы, бульвары --------------
    parks_raw = load_json("parks.json") or {"elements": []}
    roads_raw = load_json("roads.json") or {"elements": []}
    poi_raw = load_json("poi.json") or {"elements": []}

    candidates = []  # (geom, category, name, tags, osm_id, osm_type)
    skipped_no_name = 0
    skipped_invalid = 0
    outside = 0

    for element in parks_raw["elements"]:
        tags = element.get("tags") or {}
        if not tags:
            continue
        name = tags.get("name") or tags.get("name:ru")
        category = classify_park(tags, name)
        if category is None:
            continue
        if not name:
            skipped_no_name += 1
            continue
        geom = polygonize_element(element)
        if geom is None:
            continue
        if not geom.is_valid:
            geom = as_multipolygon(geom.buffer(0))
            if geom is None or not geom.is_valid:
                skipped_invalid += 1
                continue
        # здания/водоёмы внутри парка должны покрываться полигоном парка
        geom = fill_holes(geom)
        if geom is None or geom.is_empty or not geom.is_valid:
            skipped_invalid += 1
            continue
        if geom.area <= 0:
            skipped_invalid += 1
            continue
        # принадлежность исследуемой территории (ST_Within по центроиду)
        if not district_geom.covers(geom.centroid):
            outside += 1
            continue
        candidates.append([geom, category, name, tags, element.get("id"), element["type"]])

    # Линейные бульвары и аллеи -> контур (буферизация 8 м).
    boulevard_lines = []
    for element in roads_raw["elements"]:
        tags = element.get("tags") or {}
        name = tags.get("name")
        if not name or not BOULEVARD_RE.search(name):
            continue
        if element["type"] != "way":
            continue
        line = way_geometry(element)
        if isinstance(line, Polygon):
            geom = as_multipolygon(line)
            if geom and district_geom.covers(geom.centroid):
                candidates.append([geom, "boulevard", name, tags, element.get("id"), "way"])
            continue
        if isinstance(line, LineString) and district_geom.covers(line.centroid):
            boulevard_lines.append((line, name, tags, element.get("id")))

    for line, name, tags, osm_id in boulevard_lines:
        if any(name == row[2] for row in candidates):
            continue  # уже есть полигон с тем же названием
        buffered = as_multipolygon(buffer_m(line, 8, cap_style=2, join_style=2))
        if buffered is None or not buffered.is_valid:
            continue
        if not district_geom.covers(buffered.centroid):
            continue
        candidates.append([buffered, "boulevard", name, tags, osm_id, "way"])

    # Склеивание фрагментов одного объекта: если одноимённые контуры одной
    # категории соприкасаются или близки (< 30 м), объединяем их в один
    # полигон — так убираются «разрывы» и дубликаты названий.
    _groups = defaultdict(list)
    for _i, _cand in enumerate(candidates):
        _groups[(_cand[1], _cand[2])].append(_i)
    _merged = [None] * len(candidates)
    _merged_count = 0
    for _key, _idxs in _groups.items():
        _parent = list(range(len(_idxs)))

        def _find(a):
            while _parent[a] != a:
                _parent[a] = _parent[_parent[a]]
                a = _parent[a]
            return a

        for a in range(len(_idxs)):
            for b in range(a + 1, len(_idxs)):
                ga = candidates[_idxs[a]][0]
                gb = candidates[_idxs[b]][0]
                if ga.intersects(gb) or distance_m(ga, gb) <= 30:
                    ra, rb = _find(a), _find(b)
                    if ra != rb:
                        _parent[rb] = ra
        _comp = defaultdict(list)
        for a in range(len(_idxs)):
            _comp[_find(a)].append(_idxs[a])
        for _members in _comp.values():
            if len(_members) == 1:
                _merged[_members[0]] = candidates[_members[0]]
                continue
            _geoms = [candidates[m][0] for m in _members]
            _united = _safe_union(_geoms)
            if _united is not None and not _united.is_empty:
                _united = fill_holes(as_multipolygon(_united))
            if _united is None or _united.is_empty or not _united.is_valid:
                for m in _members:
                    _merged[m] = candidates[m]
            else:
                _row = list(candidates[_members[0]])
                _row[0] = _united
                _merged[_members[0]] = _row
                _merged_count += 1
    candidates = [r for r in _merged if r is not None]

    # Стягивание разрозненных частей одного объекта: крупные парки, размеченные
    # в OSM множеством участков (разделены внутренними дорожками), сливаем
    # морфологическим замыканием, чтобы не отображаться «кучей полигонов».
    for _row in candidates:
        _row[0] = unify_parts(_row[0])

    # Удаление дубликатов (один и тот же объект может быть и отношением, и линией).
    deduped = []
    duplicates = 0
    for cand in sorted(candidates, key=lambda c: -c[0].area):
        dup = False
        for kept in deduped:
            if kept[1] == cand[1] and kept[2] == cand[2] and iou(kept[0], cand[0]) > 0.5:
                dup = True
                break
            if kept[4] == cand[4] and kept[5] == cand[5]:
                dup = True
                break
        if dup:
            duplicates += 1
        else:
            deduped.append(cand)
    candidates = deduped
    log("Парки: кандидатов %d, после дедупликации %d, без названия %d, "
        "невалидных %d, вне района %d, дубликатов %d"
        % (len(candidates) + duplicates + skipped_no_name + outside,
           len(candidates), skipped_no_name, skipped_invalid, outside, duplicates))

    # ---------------- 3. точки интереса ----------------------------
    park_tree = STRtree([row[0] for row in candidates])

    def find_park(point, near=5):
        """Содержащий парк (при вложенности -- самый маленький)."""
        matches = []
        for idx in park_tree.query(point):
            idx = int(idx)
            if candidates[idx][0].covers(point):
                matches.append(idx)
        if not matches:
            nearest = park_tree.nearest(point)
            if nearest is not None and distance_m(candidates[int(nearest)][0], point) <= near:
                matches.append(int(nearest))
        if not matches:
            return None
        return min(matches, key=lambda i: candidates[i][0].area)

    poi_rows = []
    poi_skipped_outside = 0
    poi_no_type = 0
    for element in poi_raw["elements"]:
        tags = element.get("tags") or {}
        poi_type = classify_poi(tags)
        point = point_of(element)
        if point is None:
            continue
        if poi_type is None:
            # категория «Прочее» удалена по ТZ — нераспознанные объекты не импортируем
            poi_no_type += 1
            continue
        park_idx = find_park(point, near=25)
        if park_idx is None:
            poi_skipped_outside += 1
            continue
        poi_rows.append({
            "park_idx": park_idx,
            "poi_type": poi_type,
            "name": tags.get("name"),
            "description": tags.get("description"),
            "point": point,
            "osm_id": element.get("id"),
            "osm_type": element["type"],
            "tags": tags,
        })

    # ---------------- 4. внутренние дороги -------------------------
    road_rows = []
    roads_outside = 0
    for element in roads_raw["elements"]:
        tags = element.get("tags") or {}
        road_type = classify_road(tags)
        if road_type is None:
            continue
        line = way_geometry(element)
        if not isinstance(line, LineString):
            continue
        park_idx = find_park(line.centroid)
        if park_idx is None or distance_m(candidates[park_idx][0], line.centroid) > 10:
            roads_outside += 1
            continue
        park_geom = candidates[park_idx][0]
        inside = line.intersection(park_geom)
        if inside.is_empty:
            roads_outside += 1
            continue
        parts = []
        if isinstance(inside, LineString):
            parts = [inside]
        elif hasattr(inside, "geoms"):
            parts = [g for g in inside.geoms if isinstance(g, LineString)]
        for part in parts:
            if length_m(part) < 5:  # отсечь шум из единичных отрезков
                continue
            road_rows.append({
                "park_idx": park_idx,
                "road_type": road_type,
                "name": tags.get("name"),
                "geometry": part,
                "length_m": None,  # заполняется в БД через ST_Length(geography)
                "osm_id": element.get("id"),
                "osm_type": element["type"],
            })

    # ---------------- 5. входы и выходы ----------------------------
    exit_rows = []
    exits_outside = 0
    for element in poi_raw["elements"]:
        tags = element.get("tags") or {}
        is_entrance = (
            tags.get("highway") == "entrance"
            or "entrance" in tags
            or tags.get("barrier") in ("gate", "entrance", "lift_gate", "stile")
            or tags.get("barrier") == "stile"
        )
        if not is_entrance:
            continue
        point = point_of(element)
        if point is None:
            continue
        park_idx = find_park(point)
        if park_idx is None:
            exits_outside += 1
            continue
        if distance_m(candidates[park_idx][0], point) > 8:
            exits_outside += 1
            continue
        exit_type = "exit" if tags.get("entrance") == "exit" or tags.get("exit") else "entrance"
        # стрелку ставим на саму границу полигона и направляем перпендикулярно ей
        snap, rotation = arrow_rotation(candidates[park_idx][0], point)
        exit_rows.append({
            "park_idx": park_idx,
            "exit_type": exit_type,
            "name": tags.get("name"),
            "point": snap,
            "rotation_deg": rotation,
            "osm_id": element.get("id"),
            "osm_type": element["type"],
        })

    log("Точки интереса: %d (вне объектов %d, без типа %d)" % (len(poi_rows), poi_skipped_outside, poi_no_type))
    log("Дороги: %d (вне объектов %d)" % (len(road_rows), roads_outside))
    log("Входы/выходы: %d (вне объектов %d)" % (len(exit_rows), exits_outside))

    # ---------------- 6. географические названия -------------------
    places = {}
    places_raw = load_json("places.json") or {"elements": []}
    extra_raw = load_json("places_extra.json") or {"elements": []}
    for element in places_raw["elements"] + extra_raw["elements"]:
        tags = element.get("tags") or {}
        name = tags.get("name")
        point = point_of(element)
        if not name or point is None:
            continue
        if tags.get("railway") == "station" or tags.get("station") == "subway" \
                or tags.get("public_transport") == "station" or tags.get("route") == "subway":
            kind = "metro"
        elif tags.get("place") in ("square", "island", "neighbourhood"):
            kind = tags.get("place")
        elif tags.get("waterway") in ("river", "canal"):
            kind = "water"
        elif tags.get("highway") in ("primary", "secondary", "pedestrian", "tertiary", "trunk"):
            kind = "street"
        else:
            kind = "landmark"
        key = (name.lower(), kind)
        if key not in places:
            places[key] = {
                "name": name, "kind": kind, "point": point, "source": SOURCE,
            }
    # Ключевые ориентиры (реальные объекты СПб) — резерв для Location Resolver,
    # если Overpass не вернул справочник places.json.
    for name, kind, coords in (
        ("Чкаловский проспект", "street", (59.9557, 30.3205)),
        ("Каменноостровский проспект", "street", (59.9600, 30.3180)),
        ("Сенная площадь", "square", (59.9275, 30.3175)),
        ("Дворцовая площадь", "square", (59.9390, 30.3158)),
        ("Невский проспект", "street", (59.9350, 30.3250)),
        ("Электровокзал", "metro", (59.9563, 30.3199)),
        ("Петроградская", "metro", (59.9562, 30.3186)),
        ("Чкаловская", "metro", (59.9557, 30.3205)),
        ("Горьковская", "metro", (59.9619, 30.3214)),
        ("Василеостровская", "metro", (59.9410, 30.3310)),
        ("Пионерская", "metro", (59.9745, 30.2950)),
    ):
        if not any(p["name"].lower() == name.lower() for p in places.values()):
            places[("fallback:" + name.lower(), kind)] = {
                "name": name, "kind": kind,
                "point": Point(coords[1], coords[0]) if coords else None,
                "source": "справочник ориентиров проекта",
            }
    log("Географические названия: %d" % len(places))

    # ---------------- 7. загрузка в PostGIS ------------------------
    engine = create_engine(config.DATABASE_URL, future=True)
    counts = {
        "parks": len(candidates),
        "poi": len(poi_rows),
        "roads": len(road_rows),
        "exits": len(exit_rows),
        "districts": 1,
        "geo_places": len([p for p in places.values() if p["point"]]),
    }

    if not args.skip_db:
        with engine.begin() as conn:
            # миграция: колонка угла стрелки входа/выхода (для старых БД)
            conn.execute(text(
                "ALTER TABLE park_exits ADD COLUMN IF NOT EXISTS "
                "rotation_deg double precision NOT NULL DEFAULT 0"))
            conn.execute(text("TRUNCATE park_embeddings, poi, park_roads, park_exits, "
                              "parks, districts, geo_places, data_sources RESTART IDENTITY"))
            conn.execute(
                text(
                    "INSERT INTO districts (name, geometry, source) VALUES "
                    "(:name, ST_SetSRID(ST_GeomFromGeoJSON(:gj), 4326), :source)"
                ),
                {"name": district_name, "gj": geojson_str(district_geom), "source": SOURCE},
            )

            park_ids = {}
            for idx, (geom, category, name, tags, osm_id, osm_type) in enumerate(candidates):
                centroid = geom.centroid
                row = conn.execute(
                    text(
                        """
                        INSERT INTO parks
                          (name, category, description, address, borough,
                           latitude, longitude, geometry, centroid,
                           themes, keywords, metro_stations, facilities,
                           is_free, working_hours, website, phone,
                           osm_id, osm_type, source, created_at, updated_at)
                        VALUES
                          (:name, :category, :description, :address, :borough,
                           :lat, :lon,
                           ST_SetSRID(ST_GeomFromGeoJSON(:gj), 4326),
                           ST_SetSRID(ST_GeomFromGeoJSON(:cj), 4326),
                           :themes, :keywords, '{}', '{}',
                           :is_free, :working_hours, :website, :phone,
                           :osm_id, :osm_type, :source, now(), now())
                        RETURNING id
                        """
                    ),
                    {
                        "name": name,
                        "category": category,
                        "description": None,
                        "address": tags.get("addr:street") and (
                            tags.get("addr:street")
                            + (", " + tags["addr:housenumber"] if tags.get("addr:housenumber") else "")
                        ),
                        "borough": "Петроградский",
                        "lat": centroid.y,
                        "lon": centroid.x,
                        "gj": geojson_str(geom),
                        "cj": geojson_str(Point(centroid.x, centroid.y)),
                        "themes": "{}",
                        "keywords": "{}",
                        "is_free": tags.get("fee") not in ("yes",),
                        "working_hours": tags.get("opening_hours"),
                        "website": tags.get("website") or tags.get("contact:website"),
                        "phone": tags.get("phone") or tags.get("contact:phone"),
                        "osm_id": osm_id,
                        "osm_type": osm_type,
                        "source": SOURCE,
                    },
                ).scalar()
                park_ids[osm_id if osm_id is not None else name] = row
                # соответствие «индекс кандидата -> id в БД»
                park_ids[("idx", idx)] = row

            # Точки интереса
            for row in poi_rows:
                idx_key = ("idx", row["park_idx"])
                conn.execute(
                    text(
                        """
                        INSERT INTO poi
                          (park_id, poi_type, name, description, latitude, longitude,
                           geometry, osm_id, osm_type, source, created_at, updated_at)
                        VALUES
                          (:park_id, :poi_type, :name, :description, :lat, :lon,
                           ST_SetSRID(ST_GeomFromGeoJSON(:gj), 4326),
                           :osm_id, :osm_type, :source, now(), now())
                        """
                    ),
                    {
                        "park_id": park_ids[idx_key],
                        "poi_type": row["poi_type"],
                        "name": row["name"],
                        "description": row["description"],
                        "lat": row["point"].y,
                        "lon": row["point"].x,
                        "gj": geojson_str(row["point"]),
                        "osm_id": row["osm_id"],
                        "osm_type": row["osm_type"],
                        "source": SOURCE,
                    },
                )

            # Дороги
            for row in road_rows:
                conn.execute(
                    text(
                        """
                        INSERT INTO park_roads
                          (park_id, road_type, name, geometry, length_m,
                           osm_id, osm_type, source, created_at, updated_at)
                        VALUES
                          (:park_id, :road_type, :name,
                           ST_SetSRID(ST_GeomFromGeoJSON(:gj), 4326),
                           ST_Length(ST_SetSRID(ST_GeomFromGeoJSON(:gj), 4326)::geography),
                           :osm_id, :osm_type, :source, now(), now())
                        """
                    ),
                    {
                        "park_id": park_ids[("idx", row["park_idx"])],
                        "road_type": row["road_type"],
                        "name": row["name"],
                        "gj": geojson_str(row["geometry"]),
                        "osm_id": row["osm_id"],
                        "osm_type": row["osm_type"],
                        "source": SOURCE,
                    },
                )

            # Входы и выходы
            for row in exit_rows:
                conn.execute(
                    text(
                        """
                        INSERT INTO park_exits
                          (park_id, exit_type, name, latitude, longitude, geometry,
                           rotation_deg, osm_id, osm_type, source, created_at, updated_at)
                        VALUES
                          (:park_id, :exit_type, :name, :lat, :lon,
                           ST_SetSRID(ST_GeomFromGeoJSON(:gj), 4326),
                           :rotation_deg, :osm_id, :osm_type, :source, now(), now())
                        """
                    ),
                    {
                        "park_id": park_ids[("idx", row["park_idx"])],
                        "exit_type": row["exit_type"],
                        "name": row["name"],
                        "lat": row["point"].y,
                        "lon": row["point"].x,
                        "gj": geojson_str(row["point"]),
                        "rotation_deg": row.get("rotation_deg", 0.0),
                        "osm_id": row["osm_id"],
                        "osm_type": row["osm_type"],
                        "source": SOURCE,
                    },
                )

            # Географические названия
            for place in places.values():
                if place["point"] is None:
                    continue
                conn.execute(
                    text(
                        """
                        INSERT INTO geo_places (name, kind, latitude, longitude, geometry,
                                                source, created_at)
                        VALUES (:name, :kind, :lat, :lon,
                                ST_SetSRID(ST_GeomFromGeoJSON(:gj), 4326), :source, now())
                        """
                    ),
                    {
                        "name": place["name"],
                        "kind": place["kind"],
                        "lat": place["point"].y,
                        "lon": place["point"].x,
                        "gj": geojson_str(place["point"]),
                        "source": place["source"],
                    },
                )

            # Источники данных
            conn.execute(
                text(
                    """
                    INSERT INTO data_sources (source, url, description, imported_at)
                    VALUES (:source, :url, :description, now())
                    ON CONFLICT (source) DO UPDATE SET imported_at = now()
                    """
                ),
                {
                    "source": SOURCE,
                    "url": "https://www.openstreetmap.org",
                    "description": "Данные OpenStreetMap, получены через Overpass API "
                                   "и обработаны скриптом scripts/import_data.py",
                },
            )

        # ---- производные поля: площадь, описания, удобства, метро ----
        with engine.begin() as conn:
            conn.execute(text("UPDATE parks SET area_sqm = ST_Area(geometry::geography)"))
            conn.execute(
                text(
                    """
                    UPDATE parks p SET
                      metro_stations = COALESCE((
                        SELECT array_agg(g.name ORDER BY g.name)
                        FROM geo_places g
                        WHERE g.kind = 'metro'
                          AND ST_DWithin(g.geometry::geography, p.centroid::geography, 900)
                      ), '{}')
                    """
                )
            )
            conn.execute(
                text(
                    """
                    UPDATE parks p SET facilities = COALESCE((
                        SELECT array_agg(DISTINCT x.label)
                        FROM (
                          SELECT CASE i.poi_type
                                   WHEN 'playground' THEN 'детская площадка'
                                   WHEN 'food' THEN 'кафе'
                                   WHEN 'toilet' THEN 'туалет'
                                   WHEN 'parking' THEN 'парковка'
                                   WHEN 'sport' THEN 'спортивная площадка'
                                   WHEN 'fountain' THEN 'фонтан'
                                   WHEN 'monument' THEN 'памятники и скульптуры'
                                   WHEN 'viewpoint' THEN 'смотровая площадка'
                                   WHEN 'attraction' THEN 'аттракционы'
                                 END AS label
                          FROM poi i
                          WHERE i.park_id = p.id
                        ) x
                        WHERE x.label IS NOT NULL
                      ), '{}')
                    """
                )
            )
            conn.execute(
                text(
                    """
                    UPDATE parks p SET
                      has_poi    = EXISTS (SELECT 1 FROM poi i WHERE i.park_id = p.id),
                      has_roads  = EXISTS (SELECT 1 FROM park_roads r WHERE r.park_id = p.id),
                      has_exits  = EXISTS (SELECT 1 FROM park_exits e WHERE e.park_id = p.id)
                    """
                )
            )
            # Описания, темы и ключевые слова -- на основе фактических атрибутов.
            rows = conn.execute(
                text(
                    """
                    SELECT p.id, p.name, p.category, p.area_sqm, p.facilities,
                           coalesce(array_agg(DISTINCT i.poi_type) FILTER (WHERE i.poi_type IS NOT NULL),
                                    '{}') AS poi_types,
                           coalesce(sum(r.length_m), 0) AS road_length
                    FROM parks p
                    LEFT JOIN poi i ON i.park_id = p.id
                    LEFT JOIN park_roads r ON r.park_id = p.id
                    GROUP BY p.id, p.name, p.category, p.area_sqm, p.facilities
                    """
                )
            ).fetchall()
            for row in rows:
                data = dict(row._mapping)
                poi_types = list(data["poi_types"] or [])
                facilities = list(data["facilities"] or [])
                description = build_description(
                    data["name"], data["category"], {}, data["area_sqm"],
                    poi_types, facilities, float(data["road_length"] or 0),
                )
                themes = derive_themes(data["category"], facilities, poi_types)
                keywords = derive_keywords(
                    data["name"], data["category"], {}, poi_types, facilities
                )
                conn.execute(
                    text(
                        """
                        UPDATE parks
                        SET description = :description,
                            short_description = :short_description,
                            themes = :themes,
                            keywords = :keywords,
                            updated_at = now()
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": data["id"],
                        "description": description,
                        "short_description": description.split(". ")[0] + ".",
                        "themes": "{%s}" % ",".join('"%s"' % t for t in themes),
                        "keywords": "{%s}" % ",".join('"%s"' % w for w in keywords),
                    },
                )
        log("Данные загружены в базу: %s" % config.DATABASE_URL)

    # ---------------- 8. GeoJSON для фронтенда ---------------------
    features = []
    for geom, category, name, tags, osm_id, osm_type in candidates:
        centroid = geom.centroid
        features.append({
            "type": "Feature",
            "properties": {"name": name, "category": category, "osm_id": osm_id, "source": SOURCE},
            "geometry": mapping(geom),
        })
    save_geojson("parks", features)

    save_geojson("district", [{
        "type": "Feature",
        "properties": {"name": district_name, "source": SOURCE},
        "geometry": mapping(district_geom),
    }])
    save_geojson("poi", [
        {
            "type": "Feature",
            "properties": {
                "park": candidates[r["park_idx"]][2],
                "poi_type": r["poi_type"],
                "name": r["name"],
                "source": SOURCE,
            },
            "geometry": mapping(r["point"]),
        }
        for r in poi_rows
    ])
    save_geojson("roads", [
        {
            "type": "Feature",
            "properties": {
                "park": candidates[r["park_idx"]][2],
                "road_type": r["road_type"],
                "name": r["name"],
                "source": SOURCE,
            },
            "geometry": mapping(r["geometry"]),
        }
        for r in road_rows
    ])
    save_geojson("exits", [
        {
            "type": "Feature",
            "properties": {
                "park": candidates[r["park_idx"]][2],
                "exit_type": r["exit_type"],
                "name": r["name"],
                "source": SOURCE,
            },
            "geometry": mapping(r["point"]),
        }
        for r in exit_rows
    ])

    # ---------------- отчёт ----------------------------------------
    log("")
    log("=== Отчёт импорта ===")
    by_cat = Counter(row[1] for row in candidates)
    for key in ("park", "garden", "square", "boulevard"):
        log("  %-10s %d" % (key, by_cat.get(key, 0)))
    log("")
    log("%-12s %8s %8s %s" % ("Слой", "Факт", "Цель", "Статус"))
    for key in ("parks", "poi", "roads", "exits"):
        actual, target = counts[key], TARGETS[key]
        status = "OK" if actual >= target else "меньше цели"
        log("%-12s %8d %8d %s" % (key, actual, target, status))
    log("")
    log("GeoJSON сохранён в %s" % PROC_DIR)

    with open(os.path.join(PROC_DIR, "import_report.json"), "w", encoding="utf-8") as fh:
        json.dump(
            {
                "counts": counts,
                "targets": TARGETS,
                "categories": dict(by_cat),
                "district": district_name,
                "source": SOURCE,
            },
            fh,
            ensure_ascii=False,
            indent=2,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
