# Парки и сады Петроградского района Санкт-Петербурга

Интеллектуальный геопространственный веб-сервис: пространственная база данных
(PostgreSQL + PostGIS), REST API (FastAPI) и интерактивная карта (React + Leaflet)
с запросами на естественном языке, семантическим поиском и рекомендациями.

## Состав проекта

```
petrogradsky-parks/
├── backend/                 FastAPI-приложение
│   ├── app/
│   │   ├── api/             REST-эндпоинты (parks, query, analytics)
│   │   ├── ai/              LLM-клиент, разбор запросов, Location Resolver
│   │   ├── recommendation/  эмбеддинги и гибридный рейтинг
│   │   ├── services/        PostGIS-запросы, GeoJSON, статистика
│   │   ├── schemas/         Pydantic-схемы и валидация структурированного запроса
│   │   └── main.py          точка входа, раздача собранного фронтенда
│   ├── tests/               тесты REST API (pytest)
│   └── Dockerfile
├── frontend/                React 18 + TypeScript + Vite + Leaflet
│   ├── src/components/      карта и боковая панель
│   ├── dist/                продакшен-сборка (раздаёт backend, доступна сразу)
│   ├── nginx.conf, Dockerfile
├── db/migrations/           SQL-схема (parks, poi, park_roads, park_exits, districts, geo_places)
├── scripts/                 setup_db.py, fetch_osm.py, import_data.py, generate_embeddings.py
├── data/raw/                «сырые» ответы Overpass API (воспроизводимость)
├── data/processed/          очищенные слои GeoJSON + import_report.json
├── docs/                    архитектура, примеры запросов, SQL, сценарии
├── docker-compose.yml       db (postgis) + backend + frontend
├── start.bat                запуск сервиса на Windows в один клик
└── .env.example             все настройки с комментариями
```

## Быстрый старт (Docker)

```bash
cp .env.example .env
docker compose up -d db
# загрузка данных OSM (нужен Python 3.10+ и requests)
pip install -r requirements.txt
DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/parks python scripts/fetch_osm.py
DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/parks python scripts/import_data.py
docker compose up -d
```

Сервис: <http://localhost:8000> (карта), документация: <http://localhost:8000/docs>.

## Быстрый старт (Windows, one-click)

```bat
start.bat
```

Скрипт сам проверит наличие виртуального окружения, доступность базы и запустит
сервис на <http://127.0.0.1:8000>. Требуется только установленный PostgreSQL с PostGIS
и база `parks` с данными (см. раздел «Данные»).

## Данные

Проект поставляется с уже подготовленным набором данных OpenStreetMap, поэтому
отдельная загрузка из сети не требуется:

- `data/raw/` — «сырые» ответы Overpass API (границы района, парки, точки интереса,
  дорожки, ориентиры). Хранятся для воспроизводимости ETL.
- `data/processed/` — очищенные и обработанные слои в GeoJSON + `import_report.json`
  с отчётом о выполнении требований ТЗ (парки ≥ 60, POI ≥ 300, дороги ≥ 500,
  входы/выходы ≥ 150).

Импортировать данные в чистую базу (после `setup_db.py --create`):

```bash
python scripts/import_data.py          # ETL: data/raw -> PostGIS + data/processed
python scripts/generate_embeddings.py  # векторные представления для рекомендаций
```

## Быстрый старт (без Docker)

Нужны PostgreSQL 14+ с расширениями `postgis`, `cube`, `pg_trgm`, Python 3.10+, Node 18+.

```bash
# 1. база данных
python scripts/setup_db.py --create          # создать БД, включить расширения, применить миграцию
python scripts/fetch_osm.py                  # скачать данные OpenStreetMap (необязательно: data/raw уже есть)
python scripts/import_data.py                # ETL-импорт в PostGIS
python scripts/generate_embeddings.py        # векторные представления для рекомендаций

# 2. backend
pip install -r requirements.txt
cd backend && uvicorn app.main:app --reload  # http://127.0.0.1:8000

# 3. frontend (разработка)
cd frontend && npm install && npm run dev    # http://127.0.0.1:5173, proxy /api -> :8000
cd frontend && npm run build                 # продакшен-сборка в frontend/dist (её раздаёт backend)

# 4. тесты
cd backend && python -m pytest tests -v
```

## Возможности

- **Карта** с переключателем «Точки / Полигоны» (центроид или контур объекта), цветными
  условными знаками точек интереса (☕ 🏛 🎡 ⛄ ⚽ ⛲ 🔭 WC 🅿), линиями дорожек и легендой.
- **Фильтры**: можно включить/выключить любой слой — границу района, дороги,
  категории объектов (парки/сады/скверы/бульвары) и каждый тип точек интереса.
  Категория «Прочее» удалена.
- **Пространственные запросы**: ближайшие объекты (KNN по GiST-индексу), поиск в радиусе,
  расстояние до ближайшего объекта, расстояние между двумя объектами.
- **Запросы естественным языком**: AI-модель (OpenAI-совместимый API, Ollama + qwen2.5:3b)
  разбирает текст в строгую структурированную схему, которую валидирует backend; при
  недоступности AI работает автоматический fallback на локальные правила разбора
  (см. раздел «AI-модель»).
- **Location Resolver**: собственная БД географических названий -> внешний геокодер (Nominatim).
- **Рекомендации**: гибридный рейтинг «семантика + близость + категория» с весами из
  конфигурации (по умолчанию 0.50 / 0.30 / 0.20) и объяснением каждого результата.
- **Статистика**: количество объектов, площади, точки интереса, дороги, покрытие района
  по сетке, самые насыщенные зоны.

## Конфигурация

Все параметры — в `.env` (см. `.env.example`): строка подключения, адрес AI-модели,
геокодер, веса ранжирования, тайлы карты, ограничения API. Код не содержит настроек.

## AI-модель («Умный запрос»)

Поиск по естественному языку реализован через **open-source LLM за OpenAI-совместимым
API** (по умолчанию — [Ollama](https://ollama.com) + `qwen2.5:3b`). Модель получает текст
пользователя и системный промпт со строгой схемой и возвращает JSON, который backend
валидирует Pydantic-схемой `StructuredQuery`. **AI не выполняет SQL и не считает
расстояния сам** — он только преобразует текст в структурированный запрос, а все
пространственные вычисления делает PostGIS.

Включение (одна команда на чистой машине):

```bash
# 1. установить Ollama (Windows: https://ollama.com/download) или winget install Ollama.Ollama
# 2. скачать модель (~2 ГБ) и запустить сервер
ollama pull qwen2.5:3b
ollama serve                 # API на http://127.0.0.1:11434
# 3. в .env указать (уже настроено):
#    AI_BASE_URL=http://127.0.0.1:11434/v1
#    AI_MODEL=qwen2.5:3b
```

После этого `/api/health` покажет `"ai": {"available": true, "mode": "llm + rules fallback"}`,
а запросы к `/api/query` будут разбираться моделью (`"source": "llm"`).

Если Ollama не запущен, сервис **автоматически** переходит на локальные правила разбора
(`"source": "rules"`), поэтому «Умный запрос» работает в любом случае. Любую другую
OpenAI-совместимую систему (vLLM, llama.cpp server, LM Studio, OpenRouter, hosted API)
можно подключить, задав `AI_BASE_URL` и `AI_MODEL` в `.env` — код менять не нужно.

## Публичный деплой (Render + Neon)

Чтобы сайт открывался по постоянной ссылке в браузере — без файлов проекта у посетителя —
разверните его на бесплатном хостинге: код на **GitHub**, база PostGIS на **Neon**,
веб-сервис на **Render**. Подробная пошаговая инструкция — в [DEPLOY.md](DEPLOY.md),
готовая конфигурация — в [render.yaml](render.yaml).

После деплойа сайт доступен по адресу вида `https://<проект>.onrender.com`
(карта, поиск, запросы, рекомендации и построение маршрутов). AI (Ollama) на хостинге
не обязателен: без него работает GIS-поиск по правилам.

## Лицензия и данные

Данные: © участники OpenStreetMap (ODbL). Код проекта — учебный материал.
