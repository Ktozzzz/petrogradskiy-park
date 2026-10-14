# -*- coding: utf-8 -*-
"""Создание/настройка базы данных и применение миграций.

Поддерживает два режима:
  * `--create`  -- создать базу данных (если её нет), расширения и применить миграции;
  * по умолчанию -- только применить миграции к уже существующей базе.

Структура БД описана в db/migrations/*.sql (версионированные миграции,
история хранится в таблице schema_migrations).

Запуск:
    python scripts/setup_db.py --create
"""
import argparse
import os
import re
import sys

import psycopg

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MIGRATIONS_DIR = os.path.join(ROOT, "db", "migrations")


def load_env(path: str) -> dict:
    """Минимальный загрузчик .env (без внешних зависимостей)."""
    values = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def dsn_from_env(env, override=None):
    if override:
        return override
    url = env.get("DATABASE_URL")
    if url:
        return url
    host = env.get("PGHOST", "127.0.0.1")
    port = env.get("PGPORT", "5432")
    user = env.get("PGUSER", "postgres")
    dbname = env.get("PGDATABASE", "parks")
    return "host=%s port=%s user=%s dbname=%s" % (host, port, user, dbname)


def ensure_database(dsn: str, dbname: str) -> str:
    """Создать базу данных, если она отсутствует. Возвращает DSN к ней."""
    conn = psycopg.connect(dsn, autocommit=True)
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
        if cur.fetchone() is None:
            cur.execute('CREATE DATABASE "%s"' % dbname)
            print("Создана база данных %s" % dbname)
    conn.close()

    if "dbname=" in dsn:
        return re.sub(r"dbname=\S+", "dbname=%s" % dbname, dsn)
    if dsn.startswith("postgresql"):
        return re.sub(r"/[^/?]+(\?|$)", "/%s\\1" % dbname, dsn)
    return dsn


def apply_migrations(dsn: str) -> None:
    conn = psycopg.connect(dsn, autocommit=True)
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """
        )
        cur.execute("SELECT version FROM schema_migrations")
        applied = {row[0] for row in cur.fetchall()}

        files = sorted(f for f in os.listdir(MIGRATIONS_DIR) if f.endswith(".sql"))
        for fname in files:
            version = fname[:-4]
            if version in applied:
                continue
            path = os.path.join(MIGRATIONS_DIR, fname)
            with open(path, encoding="utf-8") as fh:
                sql = fh.read()
            print("Применяется миграция %s" % fname)
            cur.execute(sql)
            cur.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
        print("Миграции применены (всего: %d)." % len(files))
    conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Настройка базы данных проекта")
    parser.add_argument("--create", action="store_true", help="создать базу данных, если не существует")
    parser.add_argument("--dsn", help="DSN подключения (переопределяет DATABASE_URL)")
    args = parser.parse_args()

    env = load_env(os.path.join(ROOT, ".env"))
    dsn = dsn_from_env(env, args.dsn)

    if args.create:
        # Имя базы из DSN
        dbname = env.get("PGDATABASE", "parks")
        if "dbname=" in dsn:
            dbname = dsn.split("dbname=")[1].split()[0]
        dsn = ensure_database(dsn, dbname)

    # Расширения PostGIS/cube создаются на уровне базы.
    conn = psycopg.connect(dsn, autocommit=True)
    with conn.cursor() as cur:
        for ext in ("postgis", "cube", "pg_trgm"):
            cur.execute("CREATE EXTENSION IF NOT EXISTS %s" % ext)
        cur.execute("SELECT extversion FROM pg_extension WHERE extname='postgis'")
        row = cur.fetchone()
        print("PostGIS: %s" % (row[0] if row else "не установлен!"))
    conn.close()

    apply_migrations(dsn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
