# -*- coding: utf-8 -*-
"""Этап 3. Построение векторных представлений объектов (embeddings).

Для каждого объекта строится текстовое описание (название, описание, темы,
ключевые слова, удобства, метро, типы точек интереса), из него получается
нормированный вектор фиксированной размерности (64 признака) и сохраняется
в таблицу park_embeddings (тип cube, индекс GiST).

Провайдер выбирается конфигурацией EMBEDDINGS_PROVIDER:
    * local  -- встроенное детерминированное представление (по умолчанию);
    * http   -- нейросетевые embeddings через OpenAI-совместимый API (Ollama).

Запуск:
    python scripts/generate_embeddings.py
    python scripts/generate_embeddings.py --provider http
"""
import argparse
import os
import sys

from sqlalchemy import create_engine, text

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "backend"))

from app import config  # noqa: E402
from app.models import POI_LABELS  # noqa: E402
from app.recommendation import embeddings as emb  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Генерация embeddings объектов")
    parser.add_argument("--provider", choices=["local", "http"], default=None,
                        help="провайдер embeddings (по умолчанию -- из конфигурации)")
    args = parser.parse_args()

    if args.provider:
        os.environ["EMBEDDINGS_PROVIDER"] = args.provider

    embedder = emb.get_embedder()
    print("Провайдер embeddings: %s (%s)" % (embedder.name, embedder.kind), flush=True)

    engine = create_engine(config.DATABASE_URL, future=True)
    with engine.begin() as conn:
        rows = conn.execute(
            text(
                """
                SELECT p.id, p.name, p.description, p.themes, p.keywords,
                       p.facilities, p.metro_stations,
                       coalesce(array_agg(DISTINCT i.poi_type) FILTER (WHERE i.poi_type IS NOT NULL),
                                '{}') AS poi_types
                FROM parks p
                LEFT JOIN poi i ON i.park_id = p.id
                GROUP BY p.id, p.name, p.description, p.themes, p.keywords,
                         p.facilities, p.metro_stations
                ORDER BY p.id
                """
            )
        ).fetchall()

        conn.execute(text("TRUNCATE park_embeddings"))
        total = 0
        for row in rows:
            data = dict(row._mapping)
            poi_labels = [POI_LABELS.get(t, t) for t in (data["poi_types"] or [])]
            text_value = emb.park_text(
                data["name"], data["description"], data["themes"], data["keywords"],
                data["facilities"], data["metro_stations"], poi_labels,
            )
            vector = embedder.embed(text_value)
            conn.execute(
                text(
                    """
                    INSERT INTO park_embeddings (park_id, embedding, model, updated_at)
                    VALUES (:park_id, CAST(:vec AS cube), :model, now())
                    """
                ),
                {"park_id": data["id"], "vec": emb.cube_literal(vector), "model": embedder.name},
            )
            total += 1
            if total % 20 == 0:
                print("  обработано объектов: %d" % total, flush=True)

    print("Готово: векторных представлений — %d" % total, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
