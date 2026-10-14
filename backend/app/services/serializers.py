# -*- coding: utf-8 -*-
"""Сериализация строк БД в ответы API."""
from ..models import CATEGORY_LABELS, POI_COLORS, POI_ICONS, POI_LABELS, ROAD_LABELS


def park_out(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "category": row["category"],
        "category_label": CATEGORY_LABELS.get(row["category"], row["category"]),
        "description": row.get("description"),
        "address": row.get("address"),
        "borough": row.get("borough") or "Петроградский",
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "area_sqm": row.get("area_sqm"),
        "is_free": row.get("is_free"),
        "working_hours": row.get("working_hours"),
        "website": row.get("website"),
        "phone": row.get("phone"),
        "image_url": row.get("image_url"),
        "year_established": row.get("year_established"),
        "metro_stations": list(row.get("metro_stations") or []),
        "facilities": list(row.get("facilities") or []),
        "themes": list(row.get("themes") or []),
        "keywords": list(row.get("keywords") or []),
        "has_poi": bool(row.get("has_poi")),
        "has_roads": bool(row.get("has_roads")),
        "has_exits": bool(row.get("has_exits")),
        "poi_count": int(row.get("poi_count") or 0),
        "road_count": int(row.get("road_count") or 0),
        "exit_count": int(row.get("exit_count") or 0),
        "osm_id": row.get("osm_id"),
        "osm_type": row.get("osm_type"),
        "source": row.get("source") or "OpenStreetMap",
    }


def distance_item(row):
    raw = row.get("distance_m")
    if raw is None:
        distance_m = None
        distance_km = None
    else:
        distance_m = round(float(raw), 1)
        distance_km = round(float(raw) / 1000.0, 3)
    return {
        "park": park_out(row),
        "distance_m": distance_m,
        "distance_km": distance_km,
    }


def poi_out(row):
    return {
        "id": row["id"],
        "park_id": row["park_id"],
        "poi_type": row["poi_type"],
        "poi_type_label": POI_LABELS.get(row["poi_type"], row["poi_type"]),
        "icon": POI_ICONS.get(row["poi_type"], "•"),
        "color": POI_COLORS.get(row["poi_type"], "#607d8b"),
        "name": row.get("name"),
        "description": row.get("description"),
        "park_name": row.get("park_name"),
        "latitude": row["latitude"],
        "longitude": row["longitude"],
        "distance_m": row.get("distance_m"),
    }


def road_out(row):
    return {
        "id": row["id"],
        "park_id": row["park_id"],
        "road_type": row["road_type"],
        "road_type_label": ROAD_LABELS.get(row["road_type"], row["road_type"]),
        "name": row.get("name"),
        "length_m": row.get("length_m"),
    }


def exit_out(row):
    return {
        "id": row["id"],
        "park_id": row["park_id"],
        "exit_type": row["exit_type"],
        "name": row.get("name"),
        "latitude": row["latitude"],
        "longitude": row["longitude"],
    }


def walking_minutes(distance_m):
    """Ориентировочное время в пути (пешком, ~4,8 км/ч)."""
    return max(1, int(round(float(distance_m) / 80.0)))


def format_distance(distance_m):
    if distance_m < 1000:
        return "%d м" % round(distance_m)
    return "%.1f км" % (distance_m / 1000.0)
