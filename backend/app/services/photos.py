# -*- coding: utf-8 -*-
"""Фотографии объектов из Wikimedia Commons.

В данных OpenStreetMap у парков почти нет тегов image/wikimedia_commons,
поэтому фото ищем через публичный MediaWiki API (без ключей):

    https://commons.wikimedia.org/w/api.php
        ?action=query
        &generator=search   -- поиск по названию объекта
        &gsrnamespace=6     -- файлы (File:)
        &prop=imageinfo     -- ссылки на изображения
        &iiurlwidth=900     -- уменьшенная копия для карточки

Ответы кэшируются: фото статичны, а публичный API не должен получать
один и тот же запрос при каждом открытии карточки.
"""
import logging
import threading
import time

import requests

logger = logging.getLogger("app.photos")

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "petrogradsky-parks/1.0 (geoservice; contact: petrogradsky-parks)"
TIMEOUT_S = 10
CACHE_TTL_S = 6 * 3600          # 6 часов
CACHE_MAX_ENTRIES = 500
ALLOWED_MIME = ("image/jpeg", "image/png", "image/webp", "image/gif")

_cache = {}
_lock = threading.Lock()


def _fetch(term, limit):
    """Поиск файлов в Wikimedia Commons. Возвращает список dict'ов."""
    params = {
        "action": "query",
        "generator": "search",
        "gsrsearch": term,
        "gsrnamespace": 6,
        "gsrlimit": max(limit * 2, 10),
        "prop": "imageinfo",
        "iiprop": "url|mime",
        "iiurlwidth": 900,
        "format": "json",
        "formatversion": 2,
    }
    resp = requests.get(
        COMMONS_API,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT_S,
    )
    if resp.status_code != 200:
        raise RuntimeError("Commons HTTP %s" % resp.status_code)
    data = resp.json()
    pages = (data.get("query") or {}).get("pages") or []

    photos = []
    for page in pages:
        infos = page.get("imageinfo") or []
        if not infos:
            continue
        info = infos[0]
        mime = info.get("mime") or ""
        title = page.get("title") or ""
        if mime not in ALLOWED_MIME or title.lower().endswith(".svg"):
            continue
        url = info.get("thumburl") or info.get("url")
        if not url or not url.startswith("https://"):
            continue
        photos.append({
            "url": url,
            "title": title,
            "page": info.get("descriptionurl"),
        })
        if len(photos) >= limit:
            break
    return photos


def search_photos(name, limit=6):
    """Фото объекта по названию (с кэшем). Ошибки не ломают карточку."""
    key = (name or "").strip().lower()
    if not key:
        return []

    now = time.time()
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return list(hit[1])

    photos = []
    # 1) точное название объекта, 2) уточнение по району/городу.
    for term in (name, "%s Санкт-Петербург" % name):
        try:
            photos = _fetch(term, limit)
        except Exception as exc:  # noqa: BLE001 - фото не должны ломать карточку
            logger.warning("Wikimedia Commons недоступен (%s): %s", term, exc)
            photos = []
        if photos:
            break

    with _lock:
        if len(_cache) >= CACHE_MAX_ENTRIES:
            _cache.clear()
        _cache[key] = (time.time() + CACHE_TTL_S, list(photos))
    return photos
