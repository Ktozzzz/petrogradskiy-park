# -*- coding: utf-8 -*-
"""Дозагрузка конкретных объектов (rel/way) по id и слияние с parks.json."""
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_remaining import fetch  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
RAW_DIR = os.path.join(ROOT, "data", "raw")

RELS = [16031, 3767927, 5284742, 7251259, 8398732, 8770203, 9436210]
WAYS = [95386362, 433374748, 1004357493, 1450289764]


def main():
    ids = [("rel", r) for r in RELS] + [("way", w) for w in WAYS]
    fresh = []
    for kind, oid in ids:
        query = "[out:json][timeout:120];%s(%d);out geom;" % (kind, oid)
        data = fetch(query, rounds=6, pause=15)
        if data and data.get("elements"):
            el = data["elements"][0]
            name = (el.get("tags") or {}).get("name", "?")
            fresh.append(el)
            print("  ok %s(%d) %s (geom pts %d)" % (
                kind, oid, name,
                sum(len(m.get("geometry") or []) for m in el.get("members", []) or [])
                if kind == "rel" else len(el.get("geometry") or []),
            ), flush=True)
        else:
            print("  ПРОПУЩЕН %s(%d)" % (kind, oid), flush=True)

    path = os.path.join(RAW_DIR, "parks.json")
    with io.open(path, encoding="utf-8") as fh:
        existing = json.load(fh)
    keys = {(e.get("type"), e.get("id")) for e in existing.get("elements", [])}
    merged = list(existing.get("elements", []))
    added = 0
    for el in fresh:
        key = (el.get("type"), el.get("id"))
        if key in keys:
            continue
        merged.append(el)
        added += 1
    with io.open(path, "w", encoding="utf-8") as fh:
        json.dump({"version": 0.6, "elements": merged}, fh, ensure_ascii=False)
    print("Добавлено: %d (всего %d)" % (added, len(merged)), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
