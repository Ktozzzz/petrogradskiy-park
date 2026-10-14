# -*- coding: utf-8 -*-
"""Этап 2. Сбор исходных данных из OpenStreetMap через Overpass API.

Скрипт выполняет серию небольших запросов (чтобы не перегружать сервер
и не получать HTTP 504) и сохраняет «сырые» ответы в data/raw/:
    district.json  -- граница Петроградского района (polygon layer);
    parks.json     -- зелёные объекты (парки, сады, скверы, зелёные участки);
    poi.json       -- точки интереса, входы/выходы, именованные объекты;
    roads.json     -- дороги и дорожки;
    places.json    -- станции метро и крупные ориентиры.

Ответы сохраняются как есть (raw), чтобы импорт был воспроизводимым
и не зависел от доступности сети.

Запуск:
    python scripts/fetch_osm.py
    python scripts/fetch_osm.py --only parks
"""
import argparse
import json
import os
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW_DIR = os.path.join(ROOT, "data", "raw")

USER_AGENT = "petrogradsky-parks-gis/1.0 (course research project)"
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

# Резервная рамка (юг, запад, север, восток), если отношение границы не найдено.
FALLBACK_BBOX = (59.92, 30.23, 59.995, 30.35)

QUERY_DISTRICT = """
[out:json][timeout:180];
rel["name"="Петроградский район"]["boundary"="administrative"];
out geom;
"""

# Каждая часть -- отдельный лёгкий запрос; результаты склеиваются.
PARKS_PARTS = [
    ('relation["leisure"~"^(park|garden|square|common|nature_reserve)$"]({bbox});', 240),
    ('way["leisure"~"^(park|garden|square|common|playground)$"]({bbox});', 300),
    ('way["landuse"~"^(grass|forest|recreation_ground|village_green|meadow|cemetery)$"]({bbox});', 300),
    ('way["natural"~"^(scrub|wood|grassland)"]({bbox});', 300),
    ('way["place"="square"]({bbox});', 240),
    ('way["highway"="pedestrian"]["area"="yes"]({bbox});', 240),
]

POI_PARTS = [
    ('node["amenity"~"^(cafe|restaurant|fast_food|ice_cream|kiosk|fountain|toilet|parking|drinking_water|shelter|picnic_table|bbq)$"]({bbox});', 300),
    ('node["tourism"~"^(attraction|artwork|viewpoint|information)$"]({bbox});', 300),
    ('node["historic"~"^(memorial|memorial_plaque|monument|sculpture|artwork)$"]({bbox});', 300),
    ('node["leisure"~"^(playground|pitch|fitness_centre|track|stadium)$"]({bbox});', 300),
    ('node["highway"~"^(entrance|rest_area)$"]({bbox});', 300),
    ('node["entrance"]({bbox});', 300),
    ('node["barrier"~"^(gate|entrance|lift_gate|stile)$"]({bbox});', 300),
    ('node["railway"="station"]({bbox});', 240),
    ('node["public_transport"="station"]({bbox});', 240),
    ('way["amenity"~"^(cafe|restaurant|fast_food|fountain|toilet|parking|playground|shelter|bbq|picnic_table)$"]({bbox});', 300),
    ('way["leisure"~"^(playground|pitch|track|fitness_centre)"]({bbox});', 300),
    ('way["tourism"~"^(attraction|artwork|viewpoint)"]({bbox});', 300),
    ('way["historic"~"^(memorial|monument|sculpture)"]({bbox});', 300),
]

ROADS_PARTS = [
    ('way["highway"~"^(footway|path|pedestrian|steps|bridleway)$"]({bbox});', 300),
    ('way["highway"~"^(service|living_street)"]({bbox});', 300),
    ('way["highway"="cycleway"]({bbox});', 300),
]

PLACES_PARTS = [
    ('node["railway"="station"]["station"="subway"]({bbox});', 240),
    ('node["railway"="station"]["name"]({bbox});', 240),
    ('node["public_transport"="station"]["name"]({bbox});', 240),
    ('node["tourism"="attraction"]["name"]({bbox});', 300),
    ('node["place"~"^(square|neighbourhood|island)$"]["name"]({bbox});', 240),
    ('way["place"~"^(square|island)$"]["name"]({bbox});', 240),
    ('way["highway"~"^(primary|secondary|tertiary|pedestrian|trunk)$"]["name"]({bbox});', 300),
]

GROUPS = {
    "parks": PARKS_PARTS,
    "poi": POI_PARTS,
    "roads": ROADS_PARTS,
    "places": PLACES_PARTS,
}


def run_query(query, retries=4, timeout=300):
    """Выполнить один запрос к Overpass API: ротация endpoint'ов и повторы."""
    last_error = None
    for attempt in range(retries):
        for endpoint in ENDPOINTS:
            try:
                resp = requests.post(
                    endpoint,
                    data={"data": query},
                    headers={"User-Agent": USER_AGENT},
                    timeout=timeout + 60,
                )
                if resp.status_code == 200:
                    return resp.json()
                last_error = "HTTP %s: %s" % (resp.status_code, resp.text[:300])
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
            time.sleep(2 * (attempt + 1))
    raise RuntimeError("Overpass API недоступен: %s" % last_error)


def run_parts(parts, bbox):
    """Склеить несколько лёгких запросов в один набор элементов (с дедупликацией)."""
    box = bbox_str(bbox)
    elements = []
    seen = set()
    for index, (body, timeout) in enumerate(parts, start=1):
        query = "[out:json][timeout:%d];\n(%s);\nout geom;" % (timeout, body.format(bbox=box))
        print("    часть %d/%d ..." % (index, len(parts)), flush=True)
        payload = run_query(query)
        added = 0
        for el in payload.get("elements", []):
            key = (el.get("type"), el.get("id"))
            if key in seen:
                continue
            seen.add(key)
            elements.append(el)
            added += 1
        print("      + %d (всего %d)" % (added, len(elements)), flush=True)
    return {"version": 0.6, "elements": elements}


def bbox_from_district(district_json):
    lons, lats = [], []
    for rel in district_json.get("elements", []):
        for member in rel.get("members", []) or []:
            for pt in member.get("geometry") or []:
                lons.append(pt["lon"])
                lats.append(pt["lat"])
    if not lats:
        return FALLBACK_BBOX
    pad = 0.004
    return (min(lats) - pad, min(lons) - pad, max(lats) + pad, max(lons) + pad)


def bbox_str(bbox):
    return "%.5f,%.5f,%.5f,%.5f" % (bbox[0], bbox[1], bbox[2], bbox[3])


def save(name, payload):
    path = os.path.join(RAW_DIR, name + ".json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    print("  сохранено: %s (элементов: %d)" % (os.path.relpath(path, ROOT), len(payload.get("elements", []))))
    return path


def main():
    parser = argparse.ArgumentParser(description="Загрузка данных OSM для проекта")
    parser.add_argument("--only", choices=list(GROUPS.keys()) + ["district"],
                        help="загрузить только один набор")
    args = parser.parse_args()

    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(os.path.join(ROOT, "data", "processed"), exist_ok=True)

    district_path = os.path.join(RAW_DIR, "district.json")
    names = [args.only] if args.only else ["district", "parks", "poi", "roads", "places"]

    district_json = {}
    if os.path.exists(district_path):
        with open(district_path, encoding="utf-8") as fh:
            district_json = json.load(fh)

    if "district" in names:
        print("Запрос: district", flush=True)
        district_json = run_query(QUERY_DISTRICT)
        save("district", district_json)
        names = [n for n in names if n != "district"]

    bbox = bbox_from_district(district_json) if district_json else FALLBACK_BBOX
    print("Рамка района (s,w,n,e): %s" % (bbox,), flush=True)

    for name in names:
        print("Запрос: %s" % name, flush=True)
        payload = run_parts(GROUPS[name], bbox)
        save(name, payload)

    print("Готово.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
