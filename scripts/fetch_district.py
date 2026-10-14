# -*- coding: utf-8 -*-
"""Загрузка территории Петроградского района (по одному отношению).

Верхнеуровневое отношение границы содержит подчинённые отношения (subarea)
с реальной территорией, но без геометрии. Скрипт запрашивает каждое отношение
отдельно (короткие запросы устойчивее к перегрузке Overpass) и сохраняет
все найденные контуры в data/raw/district_subareas.json.
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
]

SUBAREAS = [1187391, 1187392, 1187393, 1187394, 1187395, 1187396]


def run(query, retries=3, timeout=90):
    last = None
    for attempt in range(retries):
        for endpoint in ENDPOINTS:
            try:
                r = requests.post(endpoint, data={"data": query}, headers=UA, timeout=timeout)
                if r.status_code == 200:
                    return r.json()
                last = "HTTP %s" % r.status_code
            except Exception as exc:  # noqa: BLE001
                last = str(exc)
            time.sleep(1.5 * (attempt + 1))
    print("  не удалось: %s" % last, flush=True)
    return None


def main():
    elements = []
    for ref in SUBAREAS:
        print("Отношение %d ..." % ref, flush=True)
        data = run("[out:json][timeout:90];rel(%d);out geom;" % ref)
        if data and data.get("elements"):
            elements.extend(data["elements"])
            print("  ok (members %d)" % len(data["elements"][0].get("members", [])), flush=True)
        else:
            print("  пропущено", flush=True)

    if not elements:
        print("Ни одно отношение не загружено.", flush=True)
        return 1

    path = os.path.join(RAW_DIR, "district_subareas.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"version": 0.6, "elements": elements}, fh, ensure_ascii=False)
    print("Сохранено %d отношений -> %s" % (len(elements), path), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
