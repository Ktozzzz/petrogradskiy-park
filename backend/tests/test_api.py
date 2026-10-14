# -*- coding: utf-8 -*-
"""Интраструктурные тесты REST API.

Тесты требуют работающую базу данных (scripts/setup_db.py + import_data.py).
Если база недоступна, тесты пропускаются с пометкой, а не падают.
"""
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app  # noqa: E402

client = TestClient(app)


def _db_ok():
    try:
        return client.get("/api/health").json()["database"]["ok"]
    except Exception:
        return False


requires_db = pytest.mark.skipif(
    not _db_ok(), reason="База данных недоступна (запустите scripts/setup_db.py и import_data.py)"
)


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert "status" in body and "database" in body and "ai" in body


def test_route():
    """Маршрут строится всегда (реальный или по прямой — без внешней сети)."""
    r = client.post(
        "/api/route",
        json={
            "start_lat": 59.9563,
            "start_lon": 30.3165,
            "end_lat": 59.9650,
            "end_lon": 30.3200,
            "costing": "pedestrian",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["geometry"]["type"] == "LineString"
    assert len(body["geometry"]["coordinates"]) >= 2
    assert body["distance_m"] > 0
    assert body["source"] in ("valhalla", "straight")


def test_openapi_docs():
    r = client.get("/openapi.json")
    assert r.status_code == 200
    paths = r.json()["paths"]
    for path in (
        "/api/parks",
        "/api/parks/nearby",
        "/api/parks/radius",
        "/api/parks/nearest_distance",
        "/api/parks/search",
        "/api/parks/geojson",
        "/api/categories",
        "/api/statistics",
        "/api/query",
        "/api/recommend",
    ):
        assert path in paths, "Отсутствует endpoint %s" % path


def test_config():
    r = client.get("/api/config")
    assert r.status_code == 200
    body = r.json()
    assert body["ranking_weights"]["semantic"] > 0
    assert "tile_url" in body


@requires_db
def test_parks_list():
    r = client.get("/api/parks")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 60, "ТЗ требует не менее 60 объектов, получено %s" % body["total"]
    assert len(body["items"]) > 0
    item = body["items"][0]
    for key in ("id", "name", "category", "latitude", "longitude"):
        assert key in item


@requires_db
def test_park_filters():
    r = client.get("/api/parks", params={"category": "park"})
    assert r.status_code == 200
    assert all(i["category"] == "park" for i in r.json()["items"])


@requires_db
def test_nearby():
    r = client.get("/api/parks/nearby", params={"latitude": 59.9563, "longitude": 30.3165, "limit": 5})
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) > 0
    assert items[0]["distance_m"] <= items[-1]["distance_m"]


@requires_db
def test_radius():
    r = client.get(
        "/api/parks/radius",
        params={"latitude": 59.9563, "longitude": 30.3165, "radius_m": 1500},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    assert all(i["distance_m"] <= 1500 for i in body["items"])


@requires_db
def test_nearest_distance():
    r = client.get(
        "/api/parks/nearest_distance",
        params={"latitude": 59.9598, "longitude": 30.3126},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["distance_m"] >= 0
    assert "nearest_park" in body
    assert body["walking_minutes"] >= 1


@requires_db
def test_search():
    r = client.get("/api/parks/search", params={"q": "Петровский"})
    assert r.status_code == 200
    assert r.json()["total"] >= 1


@requires_db
def test_parks_geojson():
    r = client.get("/api/parks/geojson")
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "FeatureCollection"
    assert len(body["features"]) >= 60


@requires_db
def test_poi_volume():
    r = client.get("/api/parks/geojson")
    features = r.json()["features"]
    total_poi = sum(f["properties"]["poi_count"] for f in features)
    assert total_poi >= 300, "ТЗ требует не менее 300 точек интереса, получено %s" % total_poi


@requires_db
def test_roads_volume():
    r = client.get("/api/parks/geojson")
    features = r.json()["features"]
    total = sum(f["properties"]["road_count"] for f in features)
    assert total >= 500, "ТЗ требует не менее 500 дорог, получено %s" % total


@requires_db
def test_exits_volume():
    r = client.get("/api/parks/geojson")
    features = r.json()["features"]
    total = sum(f["properties"]["exit_count"] for f in features)
    assert total >= 150, "ТЗ требует не менее 150 входов/выходов, получено %s" % total


@requires_db
def test_park_layers():
    park_id = client.get("/api/parks").json()["items"][0]["id"]
    for suffix in ("poi", "roads", "exits"):
        r = client.get("/api/parks/%d/%s" % (park_id, suffix))
        assert r.status_code == 200
        assert "items" in r.json()
    for suffix in ("poi/geojson", "roads/geojson", "exits/geojson"):
        r = client.get("/api/parks/%d/%s" % (park_id, suffix))
        assert r.status_code == 200
        assert r.json()["type"] == "FeatureCollection"


@requires_db
def test_distance_between_parks():
    items = client.get("/api/parks").json()["items"]
    a, b = items[0], items[1]
    r = client.get("/api/parks/%d/distance/%d" % (a["id"], b["id"]))
    assert r.status_code == 200
    assert r.json()["distance_m"] >= 0


@requires_db
def test_categories():
    r = client.get("/api/categories")
    assert r.status_code == 200
    body = r.json()
    assert len(body["categories"]) == 4
    assert sum(c["count"] for c in body["categories"]) >= 60
    assert sum(p["count"] for p in body["poi_types"]) >= 300


@requires_db
def test_statistics():
    r = client.get("/api/statistics")
    assert r.status_code == 200
    body = r.json()
    assert body["parks_total"] >= 60
    assert body["poi_total"] >= 300
    assert body["roads_total"] >= 500
    assert body["exits_total"] >= 150
    assert 0 <= body["coverage"]["covered_pct"] <= 100


@requires_db
def test_query_rules_fallback(monkeypatch):
    """Запрос естественным языком работает даже без AI-модели.

    Искусственно отключаем LLM, чтобы проверить именно локальные правила
    разбора (результат не зависит от того, запущен ли Ollama в системе).
    """
    from app.ai import service as ai_service

    class _NoLLM:
        def available(self):
            return False

        def parse_query(self, _text):
            return None

    monkeypatch.setattr(ai_service, "get_llm_client", lambda: _NoLLM())

    r = client.post("/api/query", json={"text": "Какие парки есть в Петроградском районе?"})
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "rules"
    assert body["structured"]["intent"]
    assert body["count"] >= 1


@requires_db
def test_query_radius():
    r = client.post(
        "/api/query",
        json={"text": "Покажи скверы в радиусе 1 км от Чкаловского проспекта"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["structured"]["intent"] in ("radius_search", "location_search", "search")
    assert body["count"] >= 1


@requires_db
def test_query_validation():
    """Слишком короткий запрос отклоняется схемой."""
    r = client.post("/api/query", json={"text": "а"})
    assert r.status_code == 422


@requires_db
def test_recommend():
    r = client.post(
        "/api/recommend",
        json={
            "query": "детская площадка и место для пикника",
            "latitude": 59.9563,
            "longitude": 30.3165,
            "radius_meters": 3000,
            "limit": 5,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["count"] >= 1
    first = body["results"][0]
    assert 0 <= first["score"] <= 1
    assert first["reason"]
    weights = body["weights"]
    assert abs(sum(weights.values()) - 1.0) < 0.02


@requires_db
def test_scenarios():
    r = client.get("/api/scenarios")
    assert r.status_code == 200
    assert len(r.json()) >= 3


@requires_db
def test_analytics_coverage():
    r = client.get("/api/analytics/coverage", params={"step_m": 500, "distance_m": 500})
    assert r.status_code == 200
    body = r.json()
    assert body["cells_total"] > 0
    assert 0 <= body["covered_pct"] <= 100


@requires_db
def test_analytics_radius():
    r = client.get(
        "/api/analytics/radius",
        params={"latitude": 59.9563, "longitude": 30.3165, "radius_m": 1000},
    )
    assert r.status_code == 200
    assert "by_category" in r.json()


@requires_db
def test_analytics_category_distribution():
    r = client.get("/api/analytics/category-distribution")
    assert r.status_code == 200
    assert len(r.json()["cells"]) > 0


@requires_db
def test_analytics_nearest_neighbor():
    r = client.get("/api/analytics/nearest-neighbor")
    assert r.status_code == 200
    assert r.json()["avg_nearest_neighbor_m"] >= 0


def test_frontend_served():
    """Собранный фронтенд раздаётся из корня (одна точка входа)."""
    r = client.get("/")
    if os.path.isdir(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "frontend", "dist")):
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
