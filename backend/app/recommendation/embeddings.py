# -*- coding: utf-8 -*-
"""Семантические векторные представления объектов.

Два взаимозаменяемых провайдера embeddings:
  * LocalEmbedder -- встроенное взвешенное векторное представление текста
    (feature hashing + синонимическое расширение предметной области);
    работает без внешних сервисов и модели, детерминировано;
  * HttpEmbedder -- нейросетевые embeddings через внешний API
    (OpenAI-совместимый /embeddings, например Ollama).

Контракт один и тот же: embed(text) -> list[float] (нормированный вектор).
Вектор хранится в БД в типе cube (расширение PostgreSQL) и ранжируется
оператором <-> на стороне базы (индекс GiST). При подключении pgvector
колонка заменяется на vector, код ранжирования не меняется.
"""
import math
import re
import zlib

import requests

from .. import config

EMBEDDING_DIM = 64  # ограничение типа cube: не более 100 измерений

STOPWORDS = {
    "и", "в", "во", "на", "по", "с", "со", "у", "к", "ко", "от", "до", "для",
    "за", "из", "о", "об", "что", "какой", "какие", "где", "ли", "а", "но",
    "или", "же", "бы", "не", "нет", "мне", "мой", "моя", "это", "этот",
    "найди", "найти", "покажи", "показать", "хочу", "есть", "можно", "чтобы",
    "рядом", "около", "вблизи", "недалеко", "ближе", "ближайший", "самый",
}

# Синонимическое расширение предметной области «парки и сады».
SYNONYMS = {
    "дет": ["дети", "ребенок", "игров", "семейн", "площадк"],
    "площадк": ["дет", "игров", "спорт"],
    "пикник": ["отдых", "газон", "барбекю", "гастро", "покой", "трава"],
    "отдых": ["пикник", "прогул", "релакс", "спокойн", "зелен"],
    "прогул": ["дорожк", "аллея", "маршрут", "отдых", "прогулочн"],
    "скульптур": ["памятник", "искусств", "монумент", "арт", "бюст"],
    "памятник": ["скульптур", "монумент", "истори", "искусств", "бюст"],
    "истори": ["старинн", "петровск", "памятник", "культур", "антикв"],
    "стар": ["истори", "старинн", "антикв", "легенд"],
    "природ": ["зелен", "дерев", "растени", "экопарк", "тих"],
    "зелен": ["природ", "трава", "дерев", "озеленен", "тенист"],
    "спорт": ["бег", "футбол", "тренажер", "велосипед", "разминк"],
    "тих": ["спокойн", "уютн", "малолюдн", "прогул", "тишина"],
    "красив": ["живописн", "атмосфер", "пейзаж", "фото", "видов"],
    "вод": ["фонтан", "пруд", "набережн", "река", "увлажн"],
    "кофе": ["кафе", "кофейн", "еда", "перекус", "питани"],
    "еда": ["кафе", "ресторан", "столов", "перекус", "барбекю"],
    "барбекю": ["пикник", "гастро", "еда", "жарк"],
    "туалет": ["уборн", "wc", "санузел"],
    "вел": ["велосипед", "велодорожк", "bike"],
    "набережн": ["река", "вид", "прогул", "вод", "набережная"],
    "мемориал": ["памятник", "истори", "воин", "геро"],
    "фонтан": ["вод", "бассейн", "украшен"],
    "вид": ["смотров", "панорам", "живописн"],
    "смотров": ["вид", "панорам", "беседк"],
    "луна": ["сказк", "дет", "малыш"],
    "украшен": ["цвет", "клумб", "розарий", "декоративн"],
    "цвет": ["клумб", "розарий", "ботанич", "декоративн"],
    "тенист": ["тень", "дерев", "прохладн", "зелен"],
    "venice": ["венецианск", "мост"],
    "остров": ["река", "набережн", "прогул"],
}


def tokenize(text):
    text = (text or "").lower().replace("ё", "е")
    return [t for t in re.split(r"[^a-zа-я0-9]+", text) if t]


def _features(text):
    feats = {}
    for token in tokenize(text):
        if len(token) < 3 or token in STOPWORDS:
            continue
        feats[token] = feats.get(token, 0.0) + 1.0
        for key, extra in SYNONYMS.items():
            if token.startswith(key) or (len(token) >= 4 and key.startswith(token[:4])):
                for word in extra:
                    feats[word] = feats.get(word, 0.0) + 0.5
    return feats


def local_embed(text, dim=EMBEDDING_DIM):
    """Взвешенное векторное представление текста (детерминированное)."""
    vec = [0.0] * dim
    for token, weight in _features(text).items():
        crc = zlib.crc32(token.encode("utf-8"))
        idx = crc % dim
        sign = 1.0 if ((crc // dim) % 2 == 0) else -1.0
        length_factor = 1.0 if len(token) >= 5 else 0.7
        vec[idx] += sign * (1.0 + math.log(1.0 + weight)) * length_factor
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [round(v / norm, 6) for v in vec]


def cube_literal(vector):
    return "(" + ",".join("%.6f" % v for v in vector) + ")"


class LocalEmbedder:
    """Встроенный провайдер embeddings (без внешних сервисов)."""

    name = "hashing-synonym-%d" % EMBEDDING_DIM
    kind = "local"

    def embed(self, text):
        return local_embed(text)


class HttpEmbedder:
    """Нейросетевые embeddings через внешний API (OpenAI-совместимый)."""

    kind = "http"

    def __init__(self, base_url=None, model=None, timeout=30):
        self.base_url = (base_url or config.AI_BASE_URL).rstrip("/")
        self.model = model or config.AI_MODEL
        self.timeout = timeout
        self.name = self.model

    def embed(self, text):
        resp = requests.post(
            self.base_url + "/embeddings",
            json={"model": self.model, "input": text},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()["data"][0]["embedding"]
        norm = math.sqrt(sum(v * v for v in data)) or 1.0
        return [round(v / norm, 6) for v in data]


def get_embedder():
    """Выбор провайдера embeddings по конфигурации."""
    if (config.get("EMBEDDINGS_PROVIDER") or "local").lower() == "http":
        try:
            return HttpEmbedder()
        except Exception:  # noqa: BLE001
            return LocalEmbedder()
    return LocalEmbedder()


def park_text(name, description=None, themes=None, keywords=None, facilities=None,
              metro=None, poi_labels=None):
    """Собственный текст объекта для построения вектора."""
    parts = [name or ""]
    for value in (description, themes, keywords, facilities, metro, poi_labels):
        if isinstance(value, (list, tuple)):
            parts.append(" ".join(str(v) for v in value))
        elif value:
            parts.append(str(value))
    return " ".join(parts)
