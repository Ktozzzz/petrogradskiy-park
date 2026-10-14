# -*- coding: utf-8 -*-
"""Обработка запросов естественного языком: интерпретация и исполнение.

Цепочка:
    текст пользователя
        -> AI/NLP слой (LLM через API, иначе -- локальные правила)
        -> структурированный запрос (валидация Pydantic)
        -> Location Resolver (собственная БД, затем внешний геокодер)
        -> движок пространственных запросов (PostGIS)
        -> ответ с расстояниями и объяснением.

AI никогда не выполняет SQL и не считает расстояния сам.
"""
import logging

from pydantic import ValidationError

from .. import config
from ..models import CATEGORY_LABELS, POI_LABELS
from ..recommendation import recommender
from ..services import serializers, spatial
from . import parser as nl_parser
from .llm import get_llm_client
from .resolver import resolve
from ..schemas.schemas import StructuredQuery

logger = logging.getLogger("app.query")


class ClarificationError(Exception):
    """Запрос нельзя однозначно интерпретировать (HTTP 422)."""

    def __init__(self, message, status=422):
        super().__init__(message)
        self.message = message
        self.status = status


def _clean(mapping):
    return {key: value for key, value in mapping.items() if value is not None}


def interpret(db, user_text, latitude=None, longitude=None):
    """Текст -> валидированный структурированный запрос.

    Возвращает (StructuredQuery, source, warnings).
    source: 'llm' -- ответ модели, 'rules' -- локальные правила разбора.
    """
    warnings = []
    source = "rules"
    structured = None

    llm = get_llm_client()
    if llm.available():
        raw = llm.parse_query(user_text)
        if raw:
            # Страховка: подменяем короткие имена полей на имена схемы.
            if isinstance(raw, dict):
                if "radius" in raw and "radius_meters" not in raw:
                    raw["radius_meters"] = raw.pop("radius")
                if raw.get("poi_type") == "other":
                    raw.pop("poi_type", None)
            try:
                structured = StructuredQuery(**raw)
                source = "llm"
            except ValidationError as exc:
                logger.warning("Некорректный ответ AI: %s", exc)
                warnings.append(
                    "Модель вернула некорректную структуру, запрос разобран локальными правилами."
                )
        else:
            warnings.append("Модель не ответила, запрос разобран локальными правилами.")
    else:
        warnings.append(
            "AI-модель недоступна: запрос разобран локальными правилами, "
            "пространственный анализ выполняется как обычно."
        )

    rules = nl_parser.parse(user_text, latitude, longitude)

    if structured is None:
        structured = StructuredQuery(**_clean(rules))
    else:
        # Страховка: если модель не указала точку отсчёта, берём её из правил.
        if structured.location is None and rules.get("location"):
            try:
                structured = structured.model_copy(update={"location": rules["location"]})
            except AttributeError:  # Pydantic 1.x
                structured = structured.copy(update={"location": rules["location"]})
        # Аналогично — тип точек интереса («где поесть» -> food): без него
        # ответ не содержит кафе/рестораны, хотя правила запрос распознали.
        if structured.poi_type is None and rules.get("poi_type"):
            try:
                structured = structured.model_copy(update={"poi_type": rules["poi_type"]})
            except AttributeError:  # Pydantic 1.x
                structured = structured.copy(update={"poi_type": rules["poi_type"]})

    return structured, source, warnings


def _resolve_or_clarify(db, location, latitude, longitude):
    result = resolve(db, location, latitude, longitude)
    if not result.get("ok"):
        raise ClarificationError(result.get("message") or "Не удалось определить точку отсчёта.")
    return result


def _center(res):
    return {
        "latitude": res["lat"],
        "longitude": res["lon"],
        "name": res.get("name"),
        "source": res.get("source"),
    }


def _category_summary(rows):
    counts = {}
    for row in rows:
        counts[row["category"]] = counts.get(row["category"], 0) + 1
    return ", ".join(
        "%s — %d" % (CATEGORY_LABELS.get(key, key).lower(), value)
        for key, value in sorted(counts.items())
    )


def _poi_note(response):
    """Краткая приписка о найденных интересных локациях для текста ответа."""
    count = len(response.get("poi") or [])
    if not count:
        return ""
    return " Также найдено интересных локаций: %d." % count


def _add_poi(response, fetch_rows, limit=10):
    """Приложить интересные локации к ответу (не ломает запрос при сбое).

    fetch_rows -- вызываемый без аргументов запрос к БД со списком POI.
    """
    try:
        response["poi"] = [serializers.poi_out(row) for row in fetch_rows()[:limit]]
    except Exception:  # noqa: BLE001 - POI вторичны относительно основного ответа
        logger.exception("Не удалось подготовить список точек интереса")
        response["poi"] = []
    return response


def execute(db, structured, user_text, latitude=None, longitude=None, warnings=None):
    """Исполнить структурированный запрос движком пространственных запросов."""
    warnings = list(warnings or [])
    intent = structured.intent
    limit = min(structured.limit or 10, config.MAX_LIMIT)
    response = {
        "text": "",
        "source": "rules",
        "mode": "ai_search",
        "structured": structured,
        "center": None,
        "radius_m": None,
        "count": 0,
        "results": [],
        "poi": [],
        "warnings": warnings,
    }

    if intent == "nearest_distance":
        res = _resolve_or_clarify(db, structured.location, latitude, longitude)
        row = spatial.nearest_park(db, res["lat"], res["lon"], structured.category)
        if not row:
            raise ClarificationError("В районе не найдено ни одного объекта заданной категории.", status=404)
        item = serializers.distance_item(row)
        response["center"] = _center(res)
        response["results"] = [item]
        response["count"] = 1
        response["text"] = (
            "Ближайший объект (%s) к точке отсчёта «%s»: %s — %s, около %d мин пешком."
            % (
                row["category"] and CATEGORY_LABELS.get(row["category"], row["category"]).lower(),
                res.get("name"),
                row["name"],
                serializers.format_distance(item["distance_m"]),
                serializers.walking_minutes(item["distance_m"]),
            )
        )
        return response

    if intent in ("nearby", "location_search"):
        res = _resolve_or_clarify(db, structured.location, latitude, longitude)
        rows = spatial.nearby_parks(db, res["lat"], res["lon"], structured.category, limit=limit)
        items = [serializers.distance_item(row) for row in rows]
        _add_poi(response, lambda: spatial.poi_near(db, res["lat"], res["lon"], None,
                                                    poi_type=structured.poi_type))
        response["center"] = _center(res)
        response["results"] = items
        response["count"] = len(items)
        poi_note = _poi_note(response)
        if items:
            response["text"] = (
                "Найдено %d объектов ближе всего к «%s». Ближайший: %s — %s.%s"
                % (len(items), res.get("name"), items[0]["park"]["name"],
                   serializers.format_distance(items[0]["distance_m"]), poi_note)
            )
        else:
            response["text"] = "По заданным условиям объектов не найдено." + poi_note
        return response

    if intent == "radius_search":
        res = _resolve_or_clarify(db, structured.location, latitude, longitude)
        radius = min(structured.radius_meters or 1000, config.MAX_RADIUS_METERS)
        rows = spatial.radius_parks(db, res["lat"], res["lon"], radius,
                                    structured.category, limit=limit)
        items = [serializers.distance_item(row) for row in rows]
        _add_poi(response, lambda: spatial.poi_near(db, res["lat"], res["lon"], radius,
                                                    poi_type=structured.poi_type))
        response["center"] = _center(res)
        response["center"]["radius_m"] = radius
        response["radius_m"] = radius
        response["results"] = items
        response["count"] = len(items)
        response["text"] = (
            "В радиусе %s от «%s» найдено %d: %s.%s"
            % (serializers.format_distance(radius), res.get("name"), len(items),
               _category_summary(rows) or "нет данных", _poi_note(response))
        )
        if not items:
            response["text"] = "В радиусе %s от «%s» объектов не найдено.%s" % (
                serializers.format_distance(radius), res.get("name"), _poi_note(response),
            )
        return response

    if intent == "search":
        query = structured.text or user_text
        rows = spatial.search_parks(db, query, limit=limit)
        items = [serializers.distance_item({**row, "distance_m": None}) for row in rows]
        _add_poi(response, lambda: spatial.search_poi(db, query, limit=min(limit, 20)))
        # Текстовый поиск по всей фразе («Где поесть в Петроградском районе»)
        # почти никогда не совпадает с названиями POI — для запросов о точках
        # интереса добавляем локации запрошенного типа: при точке отсчёта —
        # поблизости, иначе — по всему району.
        if structured.poi_type and not response.get("poi"):
            if structured.location is not None:
                try:
                    res = _resolve_or_clarify(db, structured.location, latitude, longitude)
                    _add_poi(response, lambda: spatial.poi_near(
                        db, res["lat"], res["lon"], None, poi_type=structured.poi_type))
                except ClarificationError:
                    _add_poi(response, lambda: spatial.poi_by_type(
                        db, structured.poi_type, limit=20))
            else:
                _add_poi(response, lambda: spatial.poi_by_type(
                    db, structured.poi_type, limit=20))
        response["results"] = items
        response["count"] = len(items)
        response["text"] = "По запросу «%s» найдено объектов: %d.%s" % (
            query, len(items), _poi_note(response))
        return response

    if intent == "category_search":
        category = structured.category
        total, rows = spatial.list_parks(db, category=category, limit=limit)
        items = [serializers.distance_item({**row, "distance_m": None}) for row in rows]
        # Если запрос о точках интереса («где поесть», «кафе»), прикладываем
        # соответствующие локации: без точки отсчёта — все такого типа в районе,
        # с точкой — поблизости от неё.
        if structured.poi_type:
            if structured.location is not None:
                try:
                    res = _resolve_or_clarify(db, structured.location, latitude, longitude)
                    _add_poi(response, lambda: spatial.poi_near(
                        db, res["lat"], res["lon"], None, poi_type=structured.poi_type))
                except ClarificationError:
                    _add_poi(response, lambda: spatial.poi_by_type(
                        db, structured.poi_type, limit=20))
            else:
                _add_poi(response, lambda: spatial.poi_by_type(
                    db, structured.poi_type, limit=20))
        response["results"] = items
        response["count"] = total
        label = CATEGORY_LABELS.get(category, category) if category else "все объекты"
        response["text"] = "Категория «%s»: объектов в районе — %d, показано %d.%s" % (
            label, total, len(items), _poi_note(response))
        return response

    if intent == "poi_search":
        park = _find_park(db, structured, latitude, longitude)
        rows = spatial.park_poi(db, park["id"], structured.poi_type)
        response["results"] = [{
            "park": serializers.park_out(park),
            "distance_m": None,
            "distance_km": None,
        }]
        response["count"] = len(rows)
        response["poi"] = [serializers.poi_out(row) for row in rows]
        response["center"] = {"latitude": park["latitude"], "longitude": park["longitude"],
                              "name": park["name"], "source": "park"}
        if rows:
            by_type = {}
            for row in rows:
                by_type[row["poi_type"]] = by_type.get(row["poi_type"], 0) + 1
            summary = ", ".join(
                "%s — %d" % (POI_LABELS.get(key, key).lower(), value)
                for key, value in sorted(by_type.items())
            )
            response["text"] = "Внутри «%s» найдено точек интереса: %d (%s)." % (
                park["name"], len(rows), summary)
        else:
            response["text"] = "Внутри «%s» точек интереса не найдено." % park["name"]
        return response

    if intent == "distance":
        if not structured.location2:
            raise ClarificationError(
                "Укажите два объекта: например «расстояние от Летнего сада до Таврического сада»."
            )
        res_a = _resolve_or_clarify(db, structured.location, latitude, longitude)
        res_b = _resolve_or_clarify(db, structured.location2, None, None)
        id_a = res_a.get("park_id")
        id_b = res_b.get("park_id")
        if not id_a or not id_b:
            raise ClarificationError(
                "Расстояние пока поддерживается между парками и садами проекта. "
                "Укажите два объекта с точными названиями."
            )
        distance_m = spatial.distance_between_parks(db, id_a, id_b)
        response["count"] = 1
        response["text"] = "Расстояние между «%s» и «%s»: %s." % (
            res_a.get("name"), res_b.get("name"), serializers.format_distance(distance_m))
        response["results"] = [{
            "park": serializers.park_out(spatial.get_park(db, id_a)),
            "distance_m": round(distance_m, 1),
            "distance_km": round(distance_m / 1000.0, 3),
        }]
        return response

    if intent == "recommend":
        lat, lon = None, None
        center_name = None
        if structured.location:
            res = resolve(db, structured.location, latitude, longitude)
            if res.get("ok"):
                lat, lon, center_name = res["lat"], res["lon"], res.get("name")
            else:
                warnings.append(res.get("message"))
                center_name = "указанная точка"
        elif latitude is not None and longitude is not None:
            lat, lon, center_name = latitude, longitude, "текущая точка"

        # Интересные локации рядом с точкой отсчёта: при явном запросе
        # «где поесть» (poi_type=food) показываем места питания, иначе —
        # ближайшие разные локации. Если точка отсчёта не определилась
        # (неизвестное название), показываем запрошенный тип локаций
        # по всему району — ответ про кафе/рестораны всё равно будет.
        if lat is not None and lon is not None:
            _add_poi(
                response,
                lambda: spatial.poi_near(
                    db, lat, lon,
                    structured.radius_meters or 1000,
                    poi_type=structured.poi_type,
                ),
            )
        elif structured.poi_type:
            _add_poi(response, lambda: spatial.poi_by_type(
                db, structured.poi_type, limit=20))

        result = recommender.recommend(
            db, structured.text or user_text, lat, lon,
            structured.radius_meters, limit=max(limit, 5),
        )
        response["warnings"] = warnings + result.get("warnings", [])
        response["results"] = result["results"]
        response["count"] = result["count"]
        response["center"] = {"latitude": lat, "longitude": lon, "name": center_name} if lat else None
        if result["results"]:
            best = result["results"][0]
            response["text"] = "Рекомендации по запросу «%s». Лучший вариант: %s (%s).%s" % (
                user_text, best["park"]["name"], best["reason"].lower(), _poi_note(response))
        else:
            response["text"] = "Подходящих объектов не найдено.%s" % _poi_note(response)
        return response

    raise ClarificationError("Не удалось определить, что нужно выполнить по запросу.")


def _find_park(db, structured, latitude, longitude):
    """Найти объект, о котором идёт речь в запросе (для poi_search)."""
    name = structured.park_name
    if not name and structured.location:
        loc = structured.location
        name = loc.get("name") if isinstance(loc, dict) else getattr(loc, "name", None)
    if name:
        row = spatial.get_park_by_name(db, name)
        if row:
            return row
        res = resolve(db, {"type": "place", "name": name}, latitude, longitude)
        if res.get("ok") and res.get("park_id"):
            row = spatial.get_park(db, res["park_id"])
            if row:
                return row
    if latitude is not None and longitude is not None:
        row = spatial.nearest_park(db, latitude, longitude)
        if row:
            return row
    raise ClarificationError(
        "Укажите, в каком парке или саде искать — название объекта не распознано."
    )


def run_query(db, user_text, latitude=None, longitude=None):
    """Полный цикл: интерпретация + исполнение."""
    structured, source, warnings = interpret(db, user_text, latitude, longitude)
    response = execute(db, structured, user_text, latitude, longitude, warnings)
    # Прямой поиск иногда не даёт совпадений (незнакомое название, слишком
    # строгий intent). Чтобы на любой запрос был понятный ответ, повторяем
    # запрос как рекомендацию по смыслу (семантический поиск) и, если там
    # есть результат, возвращаем его с пометкой.
    if response.get("count", 0) == 0 and structured.intent in (
        "search", "category_search", "poi_search"
    ):
        try:
            # Сохраняем тип точек интереса и точку отсчёта исходного запроса,
            # иначе «Где поесть в Петроградском районе» потеряло бы poi_type=food.
            alt = StructuredQuery(
                intent="recommend",
                text=user_text,
                poi_type=structured.poi_type,
                location=structured.location,
                category=structured.category,
                radius_meters=structured.radius_meters,
            )
            alt_response = execute(db, alt, user_text, latitude, longitude, warnings)
            if alt_response.get("count", 0) > 0:
                alt_response["warnings"] = list(alt_response.get("warnings") or []) + [
                    "Прямой поиск не дал точных совпадений — показаны рекомендации по смыслу запроса."
                ]
                alt_response["source"] = source
                alt_response["mode"] = "ai_search" if source == "llm" else "gis_search"
                logger.info("query fallback->recommend source=%s results=%s",
                            source, alt_response["count"])
                return alt_response
        except Exception:  # noqa: BLE001 - резервный путь не должен ломать запрос
            logger.exception("Ошибка резервной рекомендации")
    response["source"] = source
    response["mode"] = "ai_search" if source == "llm" else "gis_search"
    logger.info("query source=%s intent=%s results=%s", source, structured.intent, response["count"])
    return response
