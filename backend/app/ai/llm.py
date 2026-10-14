# -*- coding: utf-8 -*-
"""Клиент AI-слоя: подключение к open-source LLM через единый API.

Модель подключается через OpenAI-совместимый endpoint (Ollama, llama.cpp,
vLLM, LM Studio и т. п.). Контракт формализован: один метод parse_query()
возвращает «сырой» JSON, который затем валидируется Pydantic-схемой
StructuredQuery на стороне backend.

AI не имеет доступа к базе данных и не вычисляет расстояния:
он только преобразует текст в структурированный запрос.
"""
import json
import logging
import re
import time

import requests

from .. import config

logger = logging.getLogger("app.ai")

SYSTEM_PROMPT = """Ты преобразуешь запрос пользователя на русском языке о парках и садах
Петроградского района Санкт-Петербурга в строгий JSON.

Возвращай ТОЛЬКО объект с полями (именно такие названия):
  intent         - один из списка ниже
  category       - park | garden | square | boulevard   (если применимо)
  poi_type       - food | monument | attraction | playground | sport | fountain
                   | viewpoint | toilet | parking        (если применимо)
  location       - точка отсчёта (см. формат ниже)
  location2      - вторая точка (только для intent=distance)
  radius_meters  - радиус в метрах (для radius_search)
  limit          - число объектов 1..100
  text           - поисковая строка (для intent=search)
  park_name      - название парка (для intent=poi_search)

Допустимые intent:
  nearby            - ближайшие объекты к точке
  radius_search     - объекты в радиусе от точки
  search            - текстовый поиск по названию/описанию
  distance          - расстояние между двумя объектами
  nearest_distance  - расстояние до ближайшего объекта
  poi_search        - точки интереса внутри объекта
  recommend         - рекомендации по смыслу запроса
  category_search   - выборка по категории
  location_search   - объекты относительно географического названия

Формат location: {"type": "coords", "latitude": 59.95, "longitude": 30.31}
или {"type": "place", "name": "Чкаловский проспект"} или {"type": "park", "name": "Летний сад"}
или {"type": "here"}.

Пример: запрос «скверы в радиусе 500 м от Петроградской» ->
{"intent": "radius_search", "category": "square", "location": {"type": "place", "name": "Петроградская"}, "radius_meters": 500}

Правила:
- «найди/подбери парк с [признаками]», «где есть [X]», «что посоветуешь» -> intent=recommend;
- «что интересного внутри [название]» -> intent=poi_search и park_name="[название]";
- координаты указывай ТОЛЬКО если они прямо даны в запросе, иначе location с названием;
- радиус — в поле radius_meters, в метрах;
- limit - число от 1 до 100;
- если точка отсчёта неизвестна и её нельзя определить, используй location {"type": "here"};
- отвечай ТОЛЬКО JSON без пояснений и без поля «other».
"""


def _extract_json(text):
    """Достать JSON из ответа модели (на случай пояснений вокруг)."""
    if not text:
        return None
    text = text.strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if match:
        try:
            return json.loads(match.group(0))
        except ValueError:
            return None
    return None


class LLMClient:
    """Единая точка интеграции с AI-моделью."""

    def __init__(self, base_url=None, model=None, timeout=None):
        self.base_url = (base_url or config.AI_BASE_URL).rstrip("/")
        self.model = model or config.AI_MODEL
        self.timeout = timeout or config.AI_TIMEOUT
        self._available = None
        self._checked_at = 0.0
        self._ttl = 30  # секунд между проверками доступности

    # -- доступность ---------------------------------------------------
    def available(self):
        now = time.time()
        if self._available is not None and now - self._checked_at < self._ttl:
            return self._available
        try:
            resp = requests.get(
                self.base_url.rstrip("/") + "/models", timeout=3
            )
            self._available = resp.status_code == 200
        except Exception:  # noqa: BLE001
            self._available = False
        self._checked_at = now
        if not self._available:
            logger.info("AI-сервис недоступен по адресу %s", self.base_url)
        return self._available

    def reset_cache(self):
        self._available = None
        self._checked_at = 0.0

    # -- вызов ---------------------------------------------------------
    def parse_query(self, user_text):
        """Вернуть «сырой» JSON структурированного запроса или None."""
        if not self.available():
            return None
        payload = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
        }
        try:
            resp = requests.post(
                self.base_url.rstrip("/") + "/chat/completions",
                json=payload,
                timeout=self.timeout,
            )
            if resp.status_code != 200:
                logger.warning("LLM вернул HTTP %s", resp.status_code)
                return None
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Ошибка вызова LLM: %s", exc)
            return None
        parsed = _extract_json(content)
        logger.info("AI parse: %s", json.dumps(parsed, ensure_ascii=False) if parsed else None)
        return parsed


_client = None


def get_llm_client():
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
