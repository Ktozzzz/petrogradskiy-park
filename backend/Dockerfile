# Backend: FastAPI + PostGIS. Контекст сборки -- корень проекта.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        libgeos-dev libproj-dev postgresql-client curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend /app/backend
COPY scripts /app/scripts
COPY db /app/db
COPY data /app/data
COPY frontend/dist /app/frontend/dist

WORKDIR /app/backend
ENV PYTHONPATH=/app/backend

# Render (и аналоги) передают порт через переменную окружения PORT.
# Локально/Docker Compose её нет -> используется 8000 по умолчанию.
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --retries=12 \
    CMD curl -fsS "http://127.0.0.1:${PORT:-8000}/api/health" || exit 1

# Shell-форма нужна, чтобы подставить ${PORT} из окружения.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
