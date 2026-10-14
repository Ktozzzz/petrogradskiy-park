# -*- coding: utf-8 -*-
"""Детерминированный разбор запросов естественного языка (правила).

Используется, когда AI-модель недоступна (режим «GIS-поиск без AI»).
Правила дают тот же результат -- структурированный запрос StrictQuery, --
который затем валидируется Pydantic-схемой и исполняется движком
пространственных запросов. Модель и правила подменяют друг друга
без изменения дальнейшей обработки.
"""
import re

# Категории (слово -> код), приоритет определяется порядком проверки.
CATEGORY_WORDS = [
    ("boulevard", ["бульвар", "бульваре", "бульвара", "аллея", "аллее", "аллеи"]),
    ("square", ["сквер", "сквере", "сквера", "скверы"]),
    ("garden", ["сад", "сада", "саде", "сады", "садик"]),
    ("park", ["парк", "парке", "парка", "парки", "парков"]),
]

POI_WORDS = [
    ("playground", ["детская площадка", "детские площадки", "площадк", "детьми", "ребенком", "дети"]),
    ("food", ["кафе", "кофейн", "столов", "еда", "питани", "перекус", "барбекю"]),
    ("monument", ["памятник", "скульптур", "монумент", "бюст", "стату"]),
    ("fountain", ["фонтан"]),
    ("toilet", ["туалет", "уборн"]),
    ("parking", ["парковк"]),
    ("sport", ["спорт", "футболь", "баскетбол", "велодорож", "бегов"]),
    ("viewpoint", ["смотров"]),
    ("attraction", ["аттракцион", "карусел"]),
]

RECOMMEND_CUES = [
    "хочу", "посоветуй", "рекоменд", "что посмотреть", "где прогуля",
    "погулять", "отдых", "пикник", "с ребенком", "с детьми", "интересн",
]

COORD_RE = re.compile(
    r"(-?\d{1,3})[.,]\s*(\d{3,9})\s*[,; ]\s*(-?\d{1,3})[.,]\s*(\d{3,9})"
)
RADIUS_RE = re.compile(r"(\d+[.,]?\d*)\s*(км|километр\w*|м\b|метр\w*)", re.I)

HERE_WORDS = ["здесь", "тут", "тута", "этой точке", "этой точкой", "мое местоположение",
              "моё местоположение", "здесь находится", "по текущему местоположению",
              "со мной", "с мной", "рядом со мной", "отсюда"]

# Название объекта-контейнера: «в Екатерининском парке», «внутри Летнего сада».
PARK_NOUN_RE = re.compile(
    r"\b(?:в|во|внутри)\s+(?:метро\s+|станции\s+метро\s+)?"
    r"(?:[a-zа-яё\-]+\s+){0,3}?(?:парк\w*|сад\w*|сквер\w*|бульвар\w*|алле\w*|набережн\w*)"
)

# Предлоги, за которыми идёт географическое название.
# Порядок важен: более специфичные («рядом с», «вблизи») приоритетнее
# общеупотребимых («с», «у», «к»), которые часто встречаются в описаниях
# объектов («парки с детскими площадками»).
LOCATION_PREPOSITIONS = [
    "рядом с", "рядом со", "вблизи", "около", "внутри", "улица",
    "от", "до", "к", "у", "с",
]

# Слова, обрывающие фразу-название (вопросительные конструкции и рамки поиска).
TAIL_STOP = [" и сколько", " сколько", " что ", " какой", " какая", " какие", " где ",
             " есть ли", " в радиусе", " радиусом", " на расстоянии"]

# Фразы, начинающиеся с этих слов, — обычно не название («с детскими площадками»).
AMBIGUOUS_HEADS = {
    "парк", "парки", "парков", "парками", "сад", "сады", "садами", "сквер", "скверы",
    "площадками", "площадкой", "площадке", "фонтан", "фонтаны", "дети", "детьми",
    "детьми", "кафе", "кофе", "аллеи", "аллеями", "бульвар", "бульвары", "дороги",
    "дорожками", "тропинки", "лавочки", "лавочками", "пусто", "многого", "чего",
}


def normalize(text):
    text = (text or "").strip().lower().replace("ё", "е")
    text = re.sub(r"\s+", " ", text)
    return text


def _strip_tail(phrase):
    """Обрезать вопросительный «хвост» фразы: «... от Летнего сада и сколько идти»."""
    for stop in TAIL_STOP:
        idx = phrase.find(stop)
        if idx > 0:
            phrase = phrase[:idx]
    phrase = phrase.strip(" ?!.,;:—-")
    # Убираем глаголы в конце: «от Электровокзала дойти», «от Чкаловского проспекта».
    words = phrase.split()
    while words and words[-1] in (
        "дойти", "идти", "дорога", "путь", "отсюда", "здесь", "находится", "стоит", "есть"
    ):
        words.pop()
    return " ".join(words).strip()


def detect_coordinates(text):
    match = COORD_RE.search(text)
    if not match:
        return None
    lat = float(match.group(1) + "." + match.group(2))
    lon = float(match.group(3) + "." + match.group(4))
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    if not (30.0 <= lon <= 31.0 and 59.0 <= lat <= 60.5):
        return None
    return lat, lon


def detect_radius(text):
    match = RADIUS_RE.search(text)
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    unit = match.group(2).lower()
    if unit.startswith("к"):
        value *= 1000
    if value <= 0:
        return None
    return int(round(value))


def detect_category(text):
    for code, words in CATEGORY_WORDS:
        for word in words:
            if word in text:
                return code
    return None


def detect_poi_type(text):
    for code, words in POI_WORDS:
        for word in words:
            if word in text:
                return code
    return None


def detect_location_phrase(text):
    """Выделить географическое название из запроса."""
    for word in HERE_WORDS:
        if word in text:
            return {"type": "here"}

    # Приоритет — специфичным предлогам («рядом с метро Гоголевская»), а не
    # общеупотребимым («с детскими площадками»): берём первое совпадение
    # по порядку в LOCATION_PREPOSITIONS, а не самую длинную фразу.
    for prep in LOCATION_PREPOSITIONS:
        pattern = r"\b%s\s+(?:метро\s+|станции\s+метро\s+|пл\w*\s+)?(.+)$" % re.escape(prep)
        matches = [m for m in re.finditer(pattern, text)]
        best = None
        for match in matches:
            phrase = _strip_tail(match.group(1))
            if len(phrase) < 3:
                continue
            # отбрасываем случайные совпадения: «с парками», «к скверу»
            if phrase.split()[0] in AMBIGUOUS_HEADS and len(phrase.split()) < 3:
                continue
            if best is None or len(phrase) > len(best):
                best = phrase
        if best:
            if best in ("метро", "станция метро"):
                return {"type": "place", "name": "метро", "unresolved": True}
            return {"type": "place", "name": best[0].upper() + best[1:]}
    return None


def detect_park_name(text):
    """Найти в тексте объект-контейнер: «кофейня в Екатерининском парке»."""
    match = PARK_NOUN_RE.search(text)
    if not match:
        return None
    phrase = match.group(0)
    # отбросить предлог в начале: «в Екатерининском парке» -> «Екатерининском парке»
    phrase = re.sub(r"^(?:в|во|внутри)\s+", "", phrase)
    return _capitalize(phrase.strip(" ?!.,;:—-"))


def _has_any(text, words):
    return any(word in text for word in words)


def _capitalize(value):
    value = value.strip(" ?!.,;")
    return value[:1].upper() + value[1:] if value else value


def parse(text, latitude=None, longitude=None):
    """Разобрать запрос естественного языка в структурированный словарь.

    Словарь проходит валидацию Pydantic (StructuredQuery) до исполнения.
    """
    norm = normalize(text)

    result = {
        "intent": None,
        "category": detect_category(norm),
        "poi_type": detect_poi_type(norm),
        "location": None,
        "location2": None,
        "radius_meters": detect_radius(norm),
        "limit": None,
        "sort": None,
        "text": text.strip(),
        "park_name": None,
    }

    coords = detect_coordinates(norm)
    location = detect_location_phrase(norm)
    if coords:
        result["location"] = {"type": "coords", "latitude": coords[0], "longitude": coords[1]}
    elif location:
        result["location"] = location
    elif latitude is not None and longitude is not None:
        result["location"] = {"type": "coords", "latitude": latitude, "longitude": longitude}

    has_recommend_cue = _has_any(norm, RECOMMEND_CUES)
    is_here = bool(location and location.get("type") == "here")
    has_radius_word = bool(re.search(r"в радиусе|в пределах|недалеко|поблизости", norm))
    has_near_word = bool(re.search(r"рядом|около|вблизи|ближайш|ближе всего|по близости", norm))

    # poi_search: объект внутри конкретного парка («кофейня в Екатерининском парке»)
    park_container = detect_park_name(norm)
    if result["poi_type"] and park_container:
        result["park_name"] = park_container
        result["location"] = {"type": "park", "name": park_container}

    # «расстояние от A до B» / «сколько идти от A до B» -- два объекта
    distance_match = re.search(
        r"(?:расстояние|сколько (?:идти|дойти|времени)|путь|дистанция)\s+от\s+(.+?)\s+до\s+(.+?)(?:\?|$)",
        norm,
    )
    if distance_match:
        result["location"] = {"type": "place", "name": _capitalize(distance_match.group(1))}
        result["location2"] = {"type": "place", "name": _capitalize(distance_match.group(2))}
        result["intent"] = "distance"
        return result

    # --- определение intent -----------------------------------------
    if re.search(r"расстояние от .* до |расстояние между", norm):
        result["intent"] = "distance"
        result["sort"] = "distance"
    elif ("сколько" in norm and "ближайш" in norm) or "ближе всего" in norm:
        result["intent"] = "nearest_distance"
        result["sort"] = "distance"
        result["limit"] = 1
    elif re.search(r"внутри|что (интересного|есть|находится) в ", norm) and (
        location or result["park_name"]
    ):
        result["intent"] = "poi_search"
    elif result["poi_type"] and result["park_name"]:
        # точка интереса внутри конкретного объекта («кофейня в Екатерининском парке»)
        result["intent"] = "poi_search"
    elif has_recommend_cue or (result["poi_type"] and (has_radius_word or has_near_word)):
        result["intent"] = "recommend"
    elif has_radius_word or (
        result["radius_meters"] and (location or coords)
    ):
        result["intent"] = "radius_search"
        result["radius_meters"] = result["radius_meters"] or 1000
        result["sort"] = "distance"
    elif has_near_word:
        result["intent"] = "nearby"
        result["limit"] = result["limit"] or 10
        result["sort"] = "distance"
    elif result["category"] and not location:
        result["intent"] = "category_search"
        result["limit"] = result["limit"] or 30
    elif result["category"] and location:
        result["intent"] = "location_search"
        result["limit"] = result["limit"] or 30
    else:
        result["intent"] = "search"
        result["limit"] = result["limit"] or 20

    # poi_search: название объекта берём из location, если это сад/парк
    if result["intent"] == "poi_search" and result.get("location"):
        name = result["location"].get("name")
        if name:
            result["park_name"] = name

    # Для «здесь» без координат оставляем type=here: сервис попросит уточнить точку.
    return result
