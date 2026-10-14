# Примеры REST-запросов

Все примеры приведены для локального запуска `http://127.0.0.1:8000`.
Интерактивная документация — `/docs` (Swagger UI).

## Служебные

```bash
curl http://127.0.0.1:8000/api/health
# {"status":"ok","database":{"ok":true,"postgis":"3.4",...},"ai":{"available":false,...}}

curl http://127.0.0.1:8000/api/config
# конфигурация карты: тайлы, центр, ограничения, веса ранжирования

curl http://127.0.0.1:8000/api/categories
# категории объектов, типы точек интереса и дорог с количеством записей

curl http://127.0.0.1:8000/api/statistics
# статистика: объекты, площади, POI, дороги, покрытие района по сетке

curl http://127.0.0.1:8000/api/scenarios
# подсказки типовых запросов (используются в интерфейсе)
```

## Парки

```bash
# список с фильтрами
curl "http://127.0.0.1:8000/api/parks?category=park&limit=10"
curl "http://127.0.0.1:8000/api/parks?q=Летний"

# карточка объекта
curl http://127.0.0.1:8000/api/parks/1

# GeoJSON-слой (контуры или центроиды)
curl "http://127.0.0.1:8000/api/parks/geojson?mode=polygon"
curl "http://127.0.0.1:8000/api/parks/geojson?mode=point&category=square"

# текстовый поиск
curl "http://127.0.0.1:8000/api/parks/search?q=Таврический"
```

## Пространственные запросы

```bash
# ближайшие объекты (KNN, индекс GiST)
curl "http://127.0.0.1:8000/api/parks/nearby?latitude=59.9563&longitude=30.3165&limit=5"

# объекты в радиусе (ST_DWithin + точный расчёт geography)
curl "http://127.0.0.1:8000/api/parks/radius?latitude=59.9563&longitude=30.3165&radius_m=1000"

# расстояние до ближайшего объекта
curl "http://127.0.0.1:8000/api/parks/nearest_distance?latitude=59.9598&longitude=30.3126"

# расстояние между двумя объектами
curl "http://127.0.0.1:8000/api/parks/1/distance/7"

# «что рядом» с конкретным объектом (радиус от центроида)
curl "http://127.0.0.1:8000/api/parks/1/nearby?radius_m=500"
```

## Слои карты

```bash
curl "http://127.0.0.1:8000/api/poi/geojson"                     # все точки интереса
curl "http://127.0.0.1:8000/api/poi/geojson?types=food,toilet"   # фильтр по типам
curl "http://127.0.0.1:8000/api/roads/geojson"                   # все дорожки
curl "http://127.0.0.1:8000/api/exits/geojson"                   # входы и выходы
curl "http://127.0.0.1:8000/api/districts/geojson"               # граница района

# слои конкретного объекта
curl "http://127.0.0.1:8000/api/parks/1/poi"
curl "http://127.0.0.1:8000/api/parks/1/roads/geojson"
curl "http://127.0.0.1:8000/api/parks/1/exits"
```

## Запросы на естественном языке

```bash
curl -X POST http://127.0.0.1:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"text": "Покажи скверы в радиусе 1 км от Чкаловского проспекта"}'
```

Ответ:

```json
{
  "text": "В радиусе 1.0 км от «Чкаловский проспект» найдено 4: скверы — 4.",
  "source": "rules",
  "mode": "gis_search",
  "structured": {"intent": "radius_search", "category": "square", "radius_meters": 1000, ...},
  "center": {"latitude": 59.9598, "longitude": 30.3126, "name": "Чкаловский проспект", "source": "geo_places"},
  "radius_m": 1000.0,
  "count": 4,
  "results": [{"park": {...}, "distance_m": 320.5, "distance_km": 0.32}],
  "warnings": ["AI-модель недоступна: запрос разобран локальными правилами, ..."]
}
```

Ещё примеры:

```bash
# расстояние до ближайшего парка от ориентира
curl -X POST http://127.0.0.1:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"text": "Сколько до ближайшего парка от Электровокзала?"}'

# что внутри объекта
curl -X POST http://127.0.0.1:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"text": "Что интересного внутри Летнего сада?"}'

# неоднозначный запрос -> 422 с вопросом на уточнение
curl -X POST http://127.0.0.1:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"text": "где погулять"}'
```

## Рекомендации

```bash
curl -X POST http://127.0.0.1:8000/api/recommend \
  -H "Content-Type: application/json" \
  -d '{
        "query": "детская площадка и место для пикника недалеко от метро",
        "latitude": 59.9563,
        "longitude": 30.3165,
        "radius_meters": 3000,
        "limit": 5
      }'
```

Ответ содержит рейтинг и подробное объяснение каждого результата:

```json
{
  "query": "детская площадка и место для пикника недалеко от метро",
  "weights": {"semantic": 0.5, "spatial": 0.3, "category": 0.2},
  "count": 5,
  "results": [
    {
      "park": {"id": 3, "name": "Екатерининский парк", ...},
      "score": 0.7821,
      "semantic_score": 0.81,
      "spatial_score": 0.74,
      "category_score": 0.80,
      "distance_m": 640.2,
      "reason": "совпали темы: детская площадка, пикник; категория — парк; 640 м до точки отсчёта"
    }
  ]
}
```
