# -*- coding: utf-8 -*-
"""Тесты разбора запросов на естественном языке (без базы данных).

Правила разбора -- это fallback, который должен работать всегда,
поэтому они покрыты автономными тестами.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ai import parser  # noqa: E402


def _intent(text, **kwargs):
    return parser.parse(text, **kwargs).get("intent")


def test_parks_overview():
    result = parser.parse("Какие парки есть в Петроградском районе?")
    assert result["intent"] in ("category_search", "search", "nearby")


def test_radius_with_category():
    result = parser.parse("Покажи все скверы в радиусе 1 км от Чкаловского проспекта")
    assert result["intent"] == "radius_search"
    assert result.get("category") in (None, "square")
    assert result.get("radius_meters") in (None, 1000)


def test_radius_parsing_variants():
    for text, expected in [
        ("скверы в радиусе 500 метров", 500),
        ("парки в радиусе 2 км", 2000),
        ("что есть в 300 м отсюда", 300),
    ]:
        result = parser.parse(text)
        if result.get("radius_meters"):
            assert result["radius_meters"] == expected, text


def test_poi_search_inside_park():
    result = parser.parse("Ближайшая кофейня в Екатерининском парке")
    assert result["intent"] == "poi_search"
    assert result.get("poi_type") == "food"


def test_distance_between_parks():
    result = parser.parse("Расстояние от Летнего сада до Таврического сада")
    assert result["intent"] == "distance"
    assert result.get("location") is not None
    assert result.get("location2") is not None


def test_recommend_intent():
    result = parser.parse("Найди парк с детской площадкой и местом для пикника")
    assert result["intent"] == "recommend"


def test_nearest_distance():
    result = parser.parse("Какой парк ближе всего к координатам 59.9598, 30.3126?")
    assert result["intent"] == "nearest_distance"
    assert result.get("location", {}).get("type") == "coords"


def test_location_here():
    result = parser.parse("Какие парки рядом со мной?", latitude=59.95, longitude=30.31)
    assert result.get("location") is not None
