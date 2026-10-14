# -*- coding: utf-8 -*-
"""Интраструктурные тесты REST API.

Тесты требуют работающую базу данных (scripts/setup_db.py + import_data.py).
Если база недоступна, тесты пропускаются с пометкой, а не падают.
"""
import math
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


def _haversine_m(a, b):
    """Расстояние между точками [lon, lat] в метрах (для проверок snap)."""
    lon1, lat1, lon2, lat2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(h))


def test_route():
    """Маршрут строится по дорожной сети (Valhalla/OSRM), без линии по воде.

    Если оба роутера недоступны — API возвращает 502, но ни при каких
    условиях не отдаёт «прямую» линию через воду.
    """
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
    if r.status_code == 502:
        detail = r.json()["detail"]
        assert "прямой" in detail.lower(), "Ошибка должна объяснять отказ от линии по прямой"
        return
    assert r.status_code == 200
    body = r.json()
    assert body["geometry"]["type"] == "LineString"
    assert len(body["geometry"]["coordinates"]) >= 2
    assert body["distance_m"] > 0
    assert body["source"] in ("valhalla", "osrm"), "Маршрут обязан строить роутер дорожной сети"


def test_route_snaps_water_start_to_shore():
    """Точка посреди Невской губы не даёт линию по воде.

    Допустимы два исходa:
      * HTTP 422 — роутер не смог привязать точку к дорожной сети ближе
        MAX_SNAP_M (это и есть «точка на воде»);
      * HTTP 200 — но тогда первая вершина обязана лежать на суше, в пределах
        разумной привязки, а геометрия — ломаная по сети, не прямая.
    """
    start = [30.15, 59.955]   # Невская губа (вода)
    end = [30.3165, 59.9563]  # центр района
    r = client.post(
        "/api/route",
        json={
            "start_lat": start[1], "start_lon": start[0],
            "end_lat": end[1], "end_lon": end[0],
            "costing": "pedestrian",
        },
    )
    if r.status_code == 502:
        pytest.skip("Внешние роутеры недоступны (нет сети)")

    if r.status_code == 422:
        detail = r.json()["detail"]
        assert "вод" in detail.lower() or "дорожн" in detail.lower(), (
            "422 должен объяснять, что точка на воде/вне дорожной сети")
        return

    assert r.status_code == 200
    body = r.json()
    coords = body["geometry"]["coordinates"]
    # 1) первая вершина — точка на берегу, а не исходная точка посреди воды
    assert _haversine_m(coords[0], start) > 100, (
        "Старт не привязан к дорожной сети: линия начинается в воде")
    # 2) привязка в разумных пределах (не на километры в стороне)
    assert _haversine_m(coords[0], start) < 4000, (
        "Старт привязан слишком далеко — маршрут строится не от запрошенной точки")
    # 3) это ломаная по сети, а не две вершины «по прямой»
    assert len(coords) > 2, "Маршрут не может быть прямой линией через воду"
    assert body["source"] in ("valhalla", "osrm")


def test_route_mode_auto():
    """Режим «на машине» строится по дорожной сети и возвращает режим в ответе."""
    r = client.post(
        "/api/route",
        json={
            "start_lat": 59.9563,
            "start_lon": 30.3165,
            "end_lat": 59.9650,
            "end_lon": 30.3200,
            "costing": "auto",
        },
    )
    if r.status_code == 502:
        pytest.skip("Внешние роутеры недоступны (нет сети)")
    assert r.status_code == 200
    body = r.json()
    assert body["geometry"]["type"] == "LineString"
    assert body["distance_m"] > 0
    assert body["costing"] == "auto", "Ответ должен подтверждать запрошенный режим"
    assert body["source"] in ("valhalla", "osrm")


def test_route_mode_transit_fallback():
    """Режим «общественный транспорт»: OSM-транзит либо пеший ориентир с пометкой.

    Публичный Valhalla сейчас не отдаёт транспортные данные по Петроградскому
    району — тогда API обязано вернуть пеший ориентир с пометкой approximate
    и пояснением (notice), а не выдать пеший маршрут за транспортный молча.
    """
    r = client.post(
        "/api/route",
        json={
            "start_lat": 59.9563,
            "start_lon": 30.3165,
            "end_lat": 59.9650,
            "end_lon": 30.3200,
            "costing": "transit",
        },
    )
    if r.status_code == 502:
        pytest.skip("Внешние роутеры недоступны (нет сети)")
    assert r.status_code == 200
    body = r.json()
    assert body["costing"] == "transit"
    assert body["distance_m"] > 0
    assert len(body["geometry"]["coordinates"]) >= 2
    if body["approximate"]:
        assert body["notice"], "Приблизительный маршрут обязан сопровождаться пояснением"
        assert "транспорт" in body["notice"].lower() or "общественн" in body["notice"].lower()


def test_route_rejects_unknown_costing():
    """Неизвестный режим маршрута отклоняется схемой (422), а не игнорируется."""
    r = client.post(
        "/api/route",
        json={
            "start_lat": 59.9563,
            "start_lon": 30.3165,
            "end_lat": 59.9650,
            "end_lon": 30.3200,
            "costing": "taxi",
        },
    )
    assert r.status_code == 422


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
def test_search_includes_poi():
    """Поиск выдаёт не только парки/сады/скверы, но и интересные локации."""
    # объект с точками интереса — ищем по его названию
    park = client.get("/api/parks", params={"has_poi": True, "limit": 1}).json()["items"][0]
    r = client.get("/api/parks/search", params={"q": park["name"]})
    assert r.status_code == 200
    body = r.json()
    assert "poi" in body, "Ответ поиска должен содержать список локаций"
    assert isinstance(body["poi"], list)
    assert body["total"] >= 1
    if park.get("poi_count"):
        assert len(body["poi"]) > 0, "POI объекта должны находиться по его названию"
        first = body["poi"][0]
        for key in ("id", "park_id", "poi_type", "poi_type_label", "latitude", "longitude"):
            assert key in first
        # локации самого объекта присутствуют в выдаче
        assert any(x.get("park_name") == park["name"] for x in body["poi"]), (
            "Среди локаций нет ни одной из объекта %s" % park["name"])


@requires_db
def test_park_detail_fields():
    """Карточка объекта отдаёт контакты и osm-ссылки для ресурсов."""
    park_id = client.get("/api/parks").json()["items"][0]["id"]
    r = client.get("/api/parks/%d" % park_id)
    assert r.status_code == 200
    body = r.json()
    for key in ("phone", "website", "image_url", "year_established",
                "osm_id", "osm_type", "borough", "themes"):
        assert key in body, "В карточке нет поля %s" % key
    # GeoJSON-слой, из которого собирается выбор на карте, обязан содержать темы
    geo = client.get("/api/parks/geojson", params={"ids": park_id}).json()
    props = geo["features"][0]["properties"]
    for key in ("themes", "borough", "keywords"):
        assert key in props, "В свойствах GeoJSON нет поля %s" % key


@requires_db
def test_park_photos():
    """Фотографии для карточки (Wikimedia Commons, с кэшем)."""
    park_id = client.get("/api/parks").json()["items"][0]["id"]
    r = client.get("/api/parks/%d/photos" % park_id)
    assert r.status_code == 200
    body = r.json()
    assert body["park_id"] == park_id
    assert isinstance(body["photos"], list)
    for photo in body["photos"][:3]:
        assert photo["url"].startswith("https://")


@requires_db
def test_park_photos_unknown_park():
    r = client.get("/api/parks/999999/photos")
    assert r.status_code == 404


def test_search_response_schema():
    """Открытая схема поиска документирует блок локаций."""
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/parks/search" in paths
    assert "/api/parks/{park_id}/photos" in paths


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
def test_query_includes_poi(monkeypatch):
    """Умный запрос возвращает не только объекты, но и интересные локации.

    LLM отключаем, чтобы результат не зависел от внешней модели.
    """
    from app.ai import service as ai_service

    class _NoLLM:
        def available(self):
            return False

        def parse_query(self, _text):
            return None

    monkeypatch.setattr(ai_service, "get_llm_client", lambda: _NoLLM())

    r = client.post(
        "/api/query",
        json={"text": "Покажи скверы в радиусе 1 км от Чкаловского проспекта"},
    )
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["poi"], list), "Ответ запроса должен содержать блок poi"
    if body["structured"]["intent"] == "radius_search":
        assert len(body["poi"]) > 0, "В радиусе должны найтись интересные локации"
        first = body["poi"][0]
        assert first["poi_type_label"]
        assert first.get("park_name"), "POI должен знать, в каком объекте находится"


def _force_rules(client_, monkeypatch):
    """Отключаем LLM, чтобы разбор запроса не зависел от внешней модели."""
    from app.ai import service as ai_service

    class _NoLLM:
        def available(self):
            return False

        def parse_query(self, _text):
            return None

    monkeypatch.setattr(ai_service, "get_llm_client", lambda: _NoLLM())


@requires_db
def test_query_food_near_park(monkeypatch):
    """«Где поесть вкусный суп возле Александровского парка» -> кафе/рестораны.

    Ответ обязан содержать места питания (poi_type=food), а не только парки.
    """
    _force_rules(client, monkeypatch)
    r = client.post(
        "/api/query",
        json={"text": "Где поесть вкусный суп возле Александровского парка"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["structured"].get("poi_type") == "food"
    assert len(body["poi"]) > 0, "Рядом с парком должны найтись места питания"
    assert all(x["poi_type"] == "food" for x in body["poi"]), (
        "На запрос «где поесть» в списке не должно быть не-еды: %s"
        % [x["poi_type"] for x in body["poi"]])


@requires_db
def test_query_food_without_known_location(monkeypatch):
    """«Где поесть в Петроградском районе» -> места питания по району.

    Раньше потерянный из fallback-рекомендации poi_type давал пустой ответ.
    """
    _force_rules(client, monkeypatch)
    r = client.post(
        "/api/query",
        json={"text": "Где поесть в Петроградском районе"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["structured"].get("poi_type") == "food"
    assert len(body["poi"]) > 0, "По запросу «где поесть» обязаны вернуться места питания"
    assert all(x["poi_type"] == "food" for x in body["poi"])


@requires_db
def test_query_cafe_near_unresolved_park(monkeypatch):
    """Кафе рядом с неизвестным объектом: место питания всё равно показываются."""
    _force_rules(client, monkeypatch)
    r = client.post(
        "/api/query",
        json={"text": "кафе рядом с Екатерининским парком"},
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["poi"]) > 0, (
        "Даже если объект не распознан, ответ про кафе не должен быть пустым")
    assert all(x["poi_type"] == "food" for x in body["poi"])


@requires_db
def test_query_food_radius_empty_falls_back_to_nearest(monkeypatch):
    """Вокруг точки отсчёта нет мест этого типа — берутся ближайшие по району.

    У Лопухинского сада ближайшее место питания дальше километра, а центр
    может вообще оказаться вне района — в обоих случаях ответ на «где поесть»
    обязан содержать места питания, а не быть пустым.
    """
    _force_rules(client, monkeypatch)
    r = client.post(
        "/api/query",
        json={"text": "Где поесть возле Лопухинского сада"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["structured"].get("poi_type") == "food"
    assert len(body["poi"]) > 0, "Пустой список кафе недопустим — ближайшие должны найтись"
    assert all(x["poi_type"] == "food" for x in body["poi"])


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
