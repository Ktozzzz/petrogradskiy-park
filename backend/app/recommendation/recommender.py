# -*- coding: utf-8 -*-
"""Рекомендательная система: гибридный ранжирование.

final_score = w_semantic * semantic + w_spatial * spatial + w_category * category

Веса берутся из конфигурации (.env), в коде не зашиты.
    semantic  -- позиция объекта в векторном пространстве (cube <-> на стороне БД);
    spatial   -- экспоненциальный спад от расстояния до точки отсчёта;
    category  -- соответствие категории, указанной в запросе.

Каждая рекомендация сопровождается объяснением (без «чёрного ящика»).
"""
import math

from sqlalchemy import text

from .. import config
from ..ai import parser as nl_parser
from ..models import CATEGORY_LABELS
from ..services import spatial
from .embeddings import cube_literal, get_embedder, local_embed


def _distance_score(distance_m):
    if distance_m is None:
        return None
    return round(math.exp(-float(distance_m) / 1000.0), 4)


def _matched_terms(db, park_id, query_text):
    """Совпадения запроса с атрибутами объекта (для объяснения)."""
    row = db.execute(
        text(
            """
            SELECT coalesce(p.keywords, '{}') AS keywords,
                   coalesce(p.facilities, '{}') AS facilities,
                   coalesce(p.themes, '{}') AS themes
            FROM parks p WHERE p.id = :id
            """
        ),
        {"id": park_id},
    ).first()
    if not row:
        return []
    data = dict(row._mapping)
    query_tokens = {t for t in nl_parser.normalize(query_text).split() if len(t) > 3}
    matched = []
    for key in ("keywords", "facilities", "themes"):
        for value in data.get(key) or []:
            tokens = nl_parser.normalize(str(value)).split()
            if any(any(qt.startswith(tok[:5]) for tok in tokens if len(tok) >= 4) for qt in query_tokens):
                matched.append(str(value))
    return matched[:4]


def _explain(park, semantic, spatial_score, category_score, distance_m, matched, category_hint):
    parts = []
    if semantic is not None:
        if semantic >= 0.6:
            parts.append("высокое смысловое соответствие запросу")
        elif semantic >= 0.4:
            parts.append("умеренное смысловое соответствие запросу")
        else:
            parts.append("частичное смысловое соответствие запросу")
    if matched:
        parts.append("соответствует запросу по признакам: " + ", ".join(matched))
    if distance_m is not None:
        if distance_m < 1000:
            parts.append("находится в %d м от точки отсчёта" % round(distance_m))
        else:
            parts.append("находится в %.1f км от точки отсчёта" % (distance_m / 1000.0))
    if category_score and category_hint:
        parts.append("категория «%s» совпадает с запросом" % CATEGORY_LABELS.get(category_hint, category_hint))
    if not parts:
        parts.append("попадает в область поиска")
    return "; ".join(parts).capitalize() + "."


def recommend(db, query_text, latitude=None, longitude=None, radius_m=None, limit=10):
    weights = config.ranking_weights()
    embedder = get_embedder()
    try:
        query_vector = embedder.embed(query_text)
    except Exception:  # noqa: BLE001 - внешний провайдер недоступен
        query_vector = local_embed(query_text)

    has_center = latitude is not None and longitude is not None
    category_hint = nl_parser.detect_category(nl_parser.normalize(query_text))

    params = {"qvec": cube_literal(query_vector), "cand": max(40, limit * 4)}
    distance_select = "NULL::float8 AS distance_m"
    where_spatial = ""
    if has_center:
        params.update({"lon": longitude, "lat": latitude})
        distance_select = (
            "ST_Distance(p.geometry::geography, "
            + spatial.POINT
            + "::geography) AS distance_m"
        )
        if radius_m:
            params.update({"radius": radius_m, "deg": spatial.point_degrees_tolerance(radius_m)})
            where_spatial = "WHERE ST_DWithin(p.geometry, " + spatial.POINT + ", :deg)"

    rows = db.execute(
        text(
            """
            SELECT p.id, p.name, p.category, p.description, p.address, p.borough,
                   p.latitude, p.longitude, p.area_sqm, p.is_free, p.working_hours,
                   p.website, p.metro_stations, p.facilities, p.themes, p.keywords,
                   p.source, p.has_poi, p.has_roads, p.has_exits,
                   0 AS poi_count, 0 AS road_count, 0 AS exit_count,
                   e.embedding <-> CAST(:qvec AS cube) AS sem_dist,
                   %s
            FROM parks p
            JOIN park_embeddings e ON e.park_id = p.id
            %s
            ORDER BY sem_dist
            LIMIT :cand
            """
            % (distance_select, where_spatial)
        ),
        params,
    ).fetchall()

    warnings = []
    if not rows:
        # Запасной вариант: векторные представления ещё не сгенерированы
        # или внешний провайдер недоступен -- используем текстовый поиск.
        warnings.append(
            "Векторные представления объектов не найдены, показаны результаты "
            "текстового поиска. Сгенерируйте их командой "
            "python scripts/generate_embeddings.py"
        )
        found = spatial.search_parks(db, query_text, limit=limit)
        results = []
        for item in found:
            item.setdefault(
                "category_label", CATEGORY_LABELS.get(item.get("category"), item.get("category"))
            )
            results.append(
                {
                    "park": item,
                    "score": round(float(item.get("rank") or 0.3), 3),
                    "semantic_score": round(float(item.get("rank") or 0.3), 3),
                    "spatial_score": None,
                    "category_score": None,
                    "distance_m": None,
                    "distance_km": None,
                    "reason": _explain(item, float(item.get("rank") or 0.3), None, None, None, [], category_hint),
                }
            )
        return {
            "query": query_text,
            "weights": weights,
            "count": len(results),
            "center": {"latitude": latitude, "longitude": longitude} if has_center else None,
            "results": results,
            "warnings": warnings,
        }

    total_weight_semantic = weights["semantic"]
    total_weight_spatial = weights["spatial"] if has_center else 0.0
    total_weight_category = weights["category"]
    normalizer = total_weight_semantic + total_weight_spatial + total_weight_category or 1.0

    candidates = []
    for row in rows:
        item = dict(row._mapping)
        item["category_label"] = CATEGORY_LABELS.get(item["category"], item["category"])
        sem_dist = float(item.pop("sem_dist") or 0.0)
        distance_m = item.pop("distance_m")
        semantic_score = round(max(0.0, 1.0 - min(sem_dist, 2.0) / 2.0), 4)
        spatial_score = _distance_score(distance_m) if has_center else None
        category_score = (
            1.0
            if category_hint and item["category"] == category_hint
            else (0.5 if not category_hint else 0.0)
        )
        score = (
            total_weight_semantic * semantic_score
            + (total_weight_spatial * (spatial_score or 0.0) if has_center else 0.0)
            + total_weight_category * category_score
        ) / normalizer
        matched = _matched_terms(db, item["id"], query_text)
        candidates.append(
            {
                "park": item,
                "score": round(score, 4),
                "semantic_score": semantic_score,
                "spatial_score": spatial_score,
                "category_score": category_score,
                "distance_m": round(float(distance_m), 1) if distance_m is not None else None,
                "distance_km": round(float(distance_m) / 1000.0, 3) if distance_m is not None else None,
                "reason": _explain(
                    item, semantic_score, spatial_score, category_score,
                    float(distance_m) if distance_m is not None else None,
                    matched, category_hint,
                ),
            }
        )

    candidates.sort(key=lambda x: x["score"], reverse=True)
    results = candidates[:limit]
    return {
        "query": query_text,
        "weights": config.ranking_weights(),
        "count": len(results),
        "center": {"latitude": latitude, "longitude": longitude} if has_center else None,
        "results": results,
        "warnings": warnings,
    }
