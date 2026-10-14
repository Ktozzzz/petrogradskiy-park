# -*- coding: utf-8 -*-
"""Устойчивая загрузка данных Overpass (с ротацией серверов и повторами).

Overpass-серверы периодически возвращают 504/timeout при большой нагрузке.
Скрипт ждёт и повторяет запрос, последовательно перебирая все серверы,
пока нужные данные не будут получены. Уже сохранённые файлы не перезаписываются.
"""
import json
import os
import sys
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW_DIR = os.path.join(ROOT, "data", "raw")

UA = {"User-Agent": "petrogradsky-parks-gis/1.0 (course research project)"}
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

FALLBACK_BBOX = (59.92, 30.23, 59.995, 30.35)

ROADS_PARTS = [
    ('way["highway"~"^(footway|path|pedestrian|steps|bridleway)$"]({bbox});', 240),
    ('way["highway"~"^(service|living_street)"]({bbox});', 240),
    ('way["highway"="cycleway"]({bbox});', 240),
]

PLACES_PARTS = [
    ('node["railway"="station"]["station"="subway"]({bbox});', 180),
    ('node["railway"="station"]["name"]({bbox});', 180),
    ('node["public_transport"="station"]["name"]({bbox});', 180),
    ('node["tourism"="attraction"]["name"]({bbox});', 240),
    ('node["place"~"^(square|neighbourhood|island)$"]["name"]({bbox});', 180),
    ('way["place"~"^(square|island)$"]["name"]({bbox});', 180),
    ('way["highway"~"^(primary|secondary|tertiary|pedestrian|trunk)$"]["name"]({bbox});', 240),
]

SUBAREAS = [1187391, 1187392, 1187393, 1187394, 1187395, 1187396]


def bbox_str(bbox):
    return "%.5f,%.5f,%.5f,%.5f" % (bbox[0], bbox[1], bbox[2], bbox[3])


def load_json(name):
    path = os.path.join(RAW_DIR, name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def save(name, payload):
    path = os.path.join(RAW_DIR, name + ".json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False)
    print("  сохранено: %s (элементов: %d)" % (name, len(payload.get("elements", []))), flush=True)


def fetch(query, rounds=8, pause=25):
    """Запрос с ротацией серверов и ожиданием, пока сервер оживёт."""
    for rnd in range(rounds):
        for endpoint in ENDPOINTS:
            try:
                resp = requests.post(endpoint, data={"data": query}, headers=UA, timeout=(15, 180))
                if resp.status_code == 200:
                    return resp.json()
                print("    %s -> HTTP %s" % (endpoint.split("//")[1].split("/")[0], resp.status_code), flush=True)
            except Exception as exc:  # noqa: BLE001
                print("    %s -> %s" % (endpoint.split("//")[1].split("/")[0], type(exc).__name__), flush=True)
        print("  повтор через %ds (раунд %d/%d)" % (pause, rnd + 1, rounds), flush=True)
        time.sleep(pause)
    return None


def run_parts(parts, box, label):
    elements, seen = [], set()
    for index, (body, timeout) in enumerate(parts, start=1):
        query = "[out:json][timeout:%d];\n(%s);\nout geom;" % (timeout, body.format(bbox=box))
        print("  %s часть %d/%d ..." % (label, index, len(parts)), flush=True)
        payload = fetch(query)
        if payload is None:
            print("  ЧАСТЬ %d ПРОПУШЕНА (серверы недоступны)" % index, flush=True)
            continue
        added = 0
        for el in payload.get("elements", []):
            key = (el.get("type"), el.get("id"))
            if key in seen:
                continue
            seen.add(key)
            elements.append(el)
            added += 1
        print("    +%d (всего %d)" % (added, len(elements)), flush=True)
    return {"version": 0.6, "elements": elements}


def main():
    os.makedirs(RAW_DIR, exist_ok=True)
    box = bbox_str(FALLBACK_BBOX)

    # --- подчинённые отношения границы района (реальная территория) ---
    if not os.path.exists(os.path.join(RAW_DIR, "district_subareas.json")):
        print("=== Граница района: подчинённые отношения ===", flush=True)
        elements = []
        for ref in SUBAREAS:
            print("  отношение %d ..." % ref, flush=True)
            data = fetch("[out:json][timeout:90];rel(%d);out geom;" % ref, rounds=6, pause=20)
            if data and data.get("elements"):
                elements.extend(data["elements"])
                print("    ok (members %d)" % len(data["elements"][0].get("members", [])), flush=True)
        if elements:
            save("district_subareas", {"version": 0.6, "elements": elements})
        else:
            print("  Отношения не загружены — используем рамку проекта.", flush=True)

    # --- дороги ---
    if not os.path.exists(os.path.join(RAW_DIR, "roads.json")):
        print("=== Дороги ===", flush=True)
        payload = run_parts(ROADS_PARTS, box, "roads")
        if payload.get("elements"):
            save("roads", payload)
        else:
            print("  Дороги не загружены.", flush=True)

    # --- ориентиры ---
    if not os.path.exists(os.path.join(RAW_DIR, "places.json")):
        print("=== Ориентиры ===", flush=True)
        payload = run_parts(PLACES_PARTS, box, "places")
        if payload.get("elements"):
            save("places", payload)
        else:
            print("  Ориентиры не загружены.", flush=True)

    print("Готово.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
