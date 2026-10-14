# Деплой на постоянный бесплатный хостинг (Render + Neon)

После этих шагов сайт открывается по **постоянной ссылке** вида
`https://petrogradsky-parks.onrender.com` — посетителю не нужны никакие файлы проекта.

## Архитектура

| Компонент | Где | Зачем | Бесплатно |
|---|---|---|---|
| Код + собранный фронтенд (`frontend/dist`) | **GitHub** | Render берёт код оттуда | да |
| PostgreSQL + PostGIS (+`cube`, `pg_trgm`) | **Neon** | парки, POI, дороги, выходы, эмбеддинги | да (1 ГБ) |
| Веб-сервис FastAPI + раздача карты (Docker) | **Render** | отдаёт сайт и API по ссылке | да |

> **Почему Neon, а не база Render:** бесплатная Postgres-база Render удаляется примерно
> через 30 дней. Neon бесплатен бессрочно, поддерживает все нужные расширения
> (`postgis`, `cube`, `pg_trgm`) и сам просыпается при обращении.

Нужны три бесплатные учётные записи — **GitHub, Neon, Render**. Банковская карта не нужна.

---

## Шаг 0. Установить Git

Пропустите, если `git --version` уже работает.

Windows (PowerShell):
```powershell
winget install --id Git.Git -e
```
После установки закройте и заново откройте терминал.

---

## Шаг 1. Загрузить код на GitHub

1. Откройте https://github.com → **New repository**.
   - Имя: `petrogradsky-parks`
   - **Public** (для бесплатного Render проще всего)
   - без README, без .gitignore (они уже есть в проекте)
2. В терминале перейдите во **внутреннюю** папку проекта (где лежат `backend`,
   `frontend`, `scripts`, `db`, `data`, `requirements.txt`):
```powershell
cd "C:\Users\Asus\Desktop\кикин рочев\petrogradsky-parks\petrogradsky-parks"
git init
git add .
git commit -m "Парки Петроградского: API + карта"
git branch -M main
git remote add origin https://github.com/<ВАШ_ЛОГИН>/petrogradsky-parks.git
git push -u origin main
```
При первом `git push` Windows предложит войти в GitHub (откроется браузер — просто подтвердите).

> В репозиторий должны попасть папки `data` (сырые и обработанные данные — нужны для
> импорта в базу) и `frontend/dist` (собранный фронтенд — его раздаёт Docker-образ).
> Папки `venv`, `node_modules` и файл `.env` исключены через `.gitignore` и не загружаются.

---

## Шаг 2. Создать базу в Neon

1. Регистрация: https://neon.tech (бесплатно).
2. Создайте проект, выберите регион — **лучше Frankfurt** (совпадает с регионом Render
   в `render.yaml`, меньше задержка).
3. В разделе **Connection Details** скопируйте строку вида
   `postgresql://user:password@ep-xxxx.aws.neon.tech/neondb`.
   - Берите **Direct** подключение (порт `5432`), а не **Pooled** (`6543`):
     прямое надёжнее для серверного приложения и обязательно для `CREATE EXTENSION`.
   - Допишите в конец `?sslmode=require` (Neon требует SSL).

База `neondb` уже существует — создавать её не нужно.

---

## Шаг 3. Перенести схему и данные в Neon

Выполняется **один раз**, с компьютера, где лежит проект (Python уже настроен в `venv`).

```powershell
cd "C:\Users\Asus\Desktop\кикин рочев\petrogradsky-parks\petrogradsky-parks"

# строка Neon: Direct + SSL (подставьте свои значения)
$NEON = "postgresql://user:password@ep-xxxx.aws.neon.tech/neondb?sslmode=require"

# 1) расширения (postgis, cube, pg_trgm) + структура таблиц
.\venv\Scripts\python.exe scripts\setup_db.py --dsn $NEON

# 2) данные: 79 парков/скверов, 424 точки интереса, дороги, выходы
$env:DATABASE_URL = $NEON -replace '^postgresql://', 'postgresql+psycopg://'
.\venv\Scripts\python.exe scripts\import_data.py

# 3) эмбеддинги — нужны для раздела «Рекомендации»
.\venv\Scripts\python.exe scripts\generate_embeddings.py
```

Проверка в SQL Editor Neon:
```sql
SELECT count(*) FROM parks;      -- ожидается 79
SELECT count(*) FROM poi;        -- ожидается 424
```

> Команда `import_data.py` пишет в БД по сети — впервые это займёт минуту-две.
> Если что-то пошло не так, перезапустите её: она идемпотентна (очищает и загружает заново).

---

## Шаг 4. Развернуть сайт на Render

1. Регистрация: https://render.com → **Sign Up** (удобно «Continue with GitHub»).
2. **New + → Web Service** → подключите репозиторий `petrogradsky-parks`.
3. Настройки сервиса:
   - **Name**: `petrogradsky-parks`
   - **Runtime / Environment**: **Docker**
   - **Dockerfile Path**: `backend/Dockerfile`
   - **Build Context / Root Directory**: `.` (корень репозитория; обычно уже по умолчанию)
   - **Instance Type / Plan**: **Free**
4. В разделе **Environment** добавьте переменные окружения:
   - `DATABASE_URL` — строка Neon **в SQLAlchemy-формате** (обратите внимание на `+psycopg`):
     ```
     postgresql+psycopg://user:password@ep-xxxx.aws.neon.tech/neondb?sslmode=require
     ```
   - `AI_BASE_URL` = `https://api.groq.com/openai/v1`
   - `AI_MODEL` = `qwen/qwen3.8-27b`
   - `AI_API_KEY` = бесплатный ключ Groq: https://console.groq.com → **API Keys** →
     **Create API Key** (без карты; ключ вида `gsk_...`)
5. Нажмите **Create Web Service**. Render соберёт Docker-образ и задеплоит (2–4 минуты).
6. Сайт станет доступен по адресу вида `https://petrogradsky-parks.onrender.com`.

> **AI на бесплатном хостинге.** Ollama здесь запустить нельзя (free Render — 512 МБ RAM,
> модели нужно ~2 ГБ), поэтому разбор запросов идёт во внешний бесплатный API **Groq**
> (OpenAI-совместимый, ключ шлётся только через `AI_API_KEY` и в репозиторий не попадает).
> Если AI недоступен (нет ключа, закончились лимиты), приложение **автоматически**
> переключается на GIS-поиск по правилам: карта, поиск, сценарии и рекомендации работают всегда.

### Альтернатива: Blueprint в один клик

В корне репозитория лежит готовый `render.yaml`. Вместо ручной настройки: на Render
**New + → Blueprint** → выбрать репозиторий → при создании Render спросит
`DATABASE_URL` и `AI_API_KEY`, вставьте значения из шага 4.

---

## Шаг 5. Проверить

Откройте `https://<ваш-проект>.onrender.com` (с телефона тоже сработает):

- карта Петроградского района с парками и скверами;
- поиск, выбор объекта, панель свойств справа;
- кнопка **«Маршрут до объекта»** — строит пеший маршрут от вашего местоположения
  (геолокация работает, т.к. сайт по HTTPS); если геолокация запрещена — старт
  выбирается кликом по карте;
- клик по точке интереса — маршрут до неё;
- разделы **«Запросы»** и **«Рекомендации»**.

Проверка API: `https://<ваш-проект>.onrender.com/api/health`

---

## Примечания и лимиты

- **Холодный старт.** Бесплатный Render засыпает после ~15 минут без посещений;
  первый запрос после простоя занимает 30–50 секунд, дальше всё быстро. Это нормально.
- **Обновления.** Изменили код → `git add . && git commit -m "..." && git push` —
  Render задеплоит автоматически.
- **Если меняли фронтенд** (`frontend/src`), пересоберите и закоммитьте `frontend/dist`:
  ```powershell
  cd frontend
  npm install
  npm run build
  cd ..
  git add frontend/dist
  git commit -m "обновление фронтенда"
  git push
  ```
- **Лимиты Render (free):** 512 МБ RAM, ~100 ГБ трафика/мес, сервис засыпает в простое.
- **Лимиты Neon (free):** 1 ГБ данных (нам нужно ~30 МБ), база засыпает в простое и
  просыпается сама при обращении.
- **Безопасность.** Пароль от Neon передаётся только как переменная окружения на Render.
  Файл `.env` в репозиторий не попадает (он в `.gitignore`). Не публикуйте DSN.

## Если что-то не работает

| Симптом | Причина / решение |
|---|---|
| Сайт открывается, но карта пустая | Не выполнены шаги 3 (данные в Neon) или `DATABASE_URL` указывает не туда. |
| `relation "parks" does not exist` | Не выполнена команда `setup_db.py` (шаг 3.1). |
| Ошибка при `CREATE EXTENSION` | Взяли **Pooled** строку Neon. Нужна **Direct** (`:5432`) + `?sslmode=require`. |
| 502 на Render, в логах ошибка БД | `DATABASE_URL` должен начинаться с `postgresql+psycopg://`, а не `postgresql://`. |
| Рекомендации возвращают 0 | Не выполнена команда `generate_embeddings.py` (шаг 3.3). |
| Первый заход грузится 30+ сек | Холодный старт бесплатного Render (см. выше). Нормально. |
