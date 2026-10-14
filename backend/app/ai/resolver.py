# -*- coding: utf-8 -*-
"""Location Resolver: преобразование географического названия в координаты.

Порядок определения (внешний геокодер -- только как запасной вариант):
  1) собственная база: парки и сады проекта;
  2) собственный справочник географических названий (geo_places);
  3) внешний геокодер (если разрешён конфигурацией GEOCODER_ENABLED).

Сопоставление устойчиво к русским падежам: сравнение по префиксам основ слов.
"""
import re

import requests
from sqlalchemy import text

from .. import config

_geocoder_cache = {}
_MATCH_CACHE = {}

CANDIDATES_SQL = (
    "SELECT id, name, latitude, longitude, 'park' AS kind FROM parks "
    "UNION ALL "
    "SELECT id, name, latitude, longitude, 'place' AS kind FROM geo_places"
)

# Слова-типы объектов: сами по себе они не указывают на конкретный объект
# («Летний сад» и «Таврический сад» оба содержат «сад»). Падежные формы
# сопоставляются тем же префиксным сравнением _same.
_GENERIC_STEMS = (
    "сад", "сквер", "парк", "бульвар", "аллея", "площадь", "площадка",
    "набережная", "проспект", "улица", "переулок", "шоссе", "линия",
    "остров", "город", "район", "метро", "станция",
)


def _is_generic(token):
    """Слово — лишь тип объекта, а не его имя («сад», «парка», «сквера»…)."""
    return any(_same(token, stem) for stem in _GENERIC_STEMS)


def _tokens(value):
    value = (value or "").lower().replace("ё", "е")
    return [t for t in re.split(r"[^a-zа-я0-9]+", value) if t]


def _significant(value, min_len=3):
    return [t for t in _tokens(value) if len(t) >= min_len]


def _common_prefix_len(word_a, word_b):
    """Длина общего префикса слов."""
    limit = min(len(word_a), len(word_b))
    index = 0
    while index < limit and word_a[index] == word_b[index]:
        index += 1
    return index


def _same(word_a, word_b):
    """Слова — одна основа с учётом падежных окончаний.

    «Летний»/«Летнего» различаются на 5-й букве (и/е), поэтому сравнение
    идёт по общему префиксу: 4 совпавшие буквы для слов длиной 5+.
    """
    common = _common_prefix_len(word_a, word_b)
    if common < 3:
        return False
    if min(len(word_a), len(word_b)) >= 5 and common < 4:
        return False
    return True


def match_score(query, candidate):
    """Оценка совпадения падежной формы запроса с названием объекта.

    Совпадение только через слова-типы объектов («сад», «сквер», «парк»…)
    не считается найденным объектом: иначе запросы «Летний сад» и
    «Таврический сад» совпали бы с первым попавшимся садом — у них
    общим остаётся лишь слово «сад», и обе точки резолвятся в один парк.
    """
    query_tokens = _significant(query)
    cand_tokens = _significant(candidate)
    if not query_tokens or not cand_tokens:
        return 0.0
    matched = 0
    distinctive = False
    for cand_token in cand_tokens:
        hits = [q for q in query_tokens if _same(cand_token, q)]
        if hits:
            matched += 1
            if any(not _is_generic(q) for q in hits):
                distinctive = True
    if not matched or not distinctive:
        return 0.0
    score = matched + matched / float(len(cand_tokens))
    if _same(cand_tokens[0], query_tokens[0]):
        score += 1.0
    return score


def _candidates(db):
    rows = db.execute(text(CANDIDATES_SQL)).fetchall()
    return [dict(row._mapping) for row in rows]


def resolve(db, location, latitude=None, longitude=None):
    """LocationSpec -> {'ok', 'lat', 'lon', 'name', 'source', 'park_id', 'message'}."""
    if location is not None and not isinstance(location, dict):
        # Pydantic-модель LocationSpec -> словарь для единообразной работы.
        location = location.model_dump() if hasattr(location, "model_dump") else dict(location)
    if not location:
        return {
            "ok": False,
            "message": "Укажите адрес, объект или координаты, относительно которых выполнить поиск.",
        }

    ltype = location.get("type")
    if ltype == "coords":
        lat, lon = location.get("latitude"), location.get("longitude")
        if lat is None or lon is None:
            return {"ok": False, "message": "Не заданы координаты точки."}
        return {
            "ok": True,
            "lat": float(lat),
            "lon": float(lon),
            "name": "координаты %s, %s" % (lat, lon),
            "source": "coords",
        }

    if ltype == "here":
        if latitude is None or longitude is None:
            return {
                "ok": False,
                "message": "Укажите точку на карте или разрешите доступ к местоположению, "
                           "чтобы выполнить поиск от текущего места.",
            }
        return {
            "ok": True,
            "lat": float(latitude),
            "lon": float(longitude),
            "name": "текущая точка",
            "source": "here",
        }

    name = (location.get("name") or "").strip()
    if not name or name.lower() in ("метро", "станция метро"):
        return {
            "ok": False,
            "message": "Уточните станцию метро или конкретный ориентир — запрос слишком общий.",
        }

    cache_key = name.lower()
    if cache_key in _MATCH_CACHE:
        return _MATCH_CACHE[cache_key]

    best, best_score = None, 0.0
    for candidate in _candidates(db):
        score = match_score(name, candidate["name"])
        if score > best_score:
            best, best_score = candidate, score

    if best is not None and best_score >= 1.5:
        result = {
            "ok": True,
            "lat": float(best["latitude"]),
            "lon": float(best["longitude"]),
            "name": best["name"],
            "source": best["kind"],
            "park_id": int(best["id"]) if best["kind"] == "park" else None,
        }
        _MATCH_CACHE[cache_key] = result
        return result

    if config.GEOCODER_ENABLED:
        result = _geocode(name)
        if result:
            _MATCH_CACHE[cache_key] = result
            return result

    return {
        "ok": False,
        "message": "Не удалось определить «%s». Укажите другой ориентир или координаты." % name,
    }


def _geocode(name):
    if name in _geocoder_cache:
        return _geocoder_cache[name]
    try:
        resp = requests.get(
            config.GEOCODER_URL.rstrip("/") + "/search",
            params={"q": name + ", Санкт-Петербург", "format": "json", "limit": 1},
            headers={"User-Agent": "petrogradsky-parks-gis/1.0"},
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            if data:
                result = {
                    "ok": True,
                    "lat": float(data[0]["lat"]),
                    "lon": float(data[0]["lon"]),
                    "name": data[0].get("display_name", name),
                    "source": "geocoder",
                }
                _geocoder_cache[name] = result
                return result
    except Exception:  # noqa: BLE001 - внешний геокодер запасной, сбой не критичен
        return None
    return None


def reset_caches():
    _MATCH_CACHE.clear()
    _geocoder_cache.clear()
