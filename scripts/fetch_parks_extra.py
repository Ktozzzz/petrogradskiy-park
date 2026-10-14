# -*- coding: utf-8 -*-
"""Дозагрузка именованных парков/садов и слияние с parks.json.

Исходная выгрузка parks.json собиралась по частям, и часть отношений могла
быть пропущена из-за перегрузки Overpass. Скрипт заново запрашивает все
именованные зелёные объекты исследуемой рамки и объединяет их с уже
имеющимися данными (с дедупликацией по типу и id).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_remaining import ENDPOINTS, FALLBACK_BBOX, UA, bbox_str, fetch  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW_DIR = os.path.join(ROOT, "data", "raw")

PARTS = [
    ('relation["leisure"~"^(park|garden|square|common|nature_reserve)$"]["name"]({bbox});', 240),
    ('way["leisure"~"^(park|garden|square|common)$"]["name"]({bbox});', 240),
]


def main():
    box = bbox_str(FALLBACK_BBOX)
    fresh = []
    seen = set()
    for index, (body, timeout) in enumerate(PARTS, start=1):
        query = "[out:json][timeout:%d];\n(%s);\nout geom;" % (timeout, body.format(bbox=box))
        print("часть %d/%d ..." % (index, len(PARTS)), flush=True)
        payload = fetch(query, rounds=10, pause=20)
        if payload is None:
            print("  часть пропущена", flush=True)
            continue
        added = 0
        for el in payload.get("elements", []):
            key = (el.get("type"), el.get("id"))
            if key in seen:
                continue
            seen.add(key)
            fresh.append(el)
            added += 1
        print("  +%d" % added, flush=True)

    path = os.path.join(RAW_DIR, "parks.json")
    with open(path, encoding="utf-8") as fh:
        existing = json.load(fh)
    existing_keys = {(e.get("type"), e.get("id")) for e in existing.get("elements", [])}
    merged = list(existing.get("elements", []))
    added_total = 0
    for el in fresh:
        key = (el.get("type"), el.get("id"))
        if key in existing_keys:
            continue
        merged.append(el)
        added_total += 1
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"version": 0.6, "elements": merged}, fh, ensure_ascii=False)
    print("Добавлено новых объектов: %d (всего %d)" % (added_total, len(merged)), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
