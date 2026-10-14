# Пространственные запросы SQL (PostGIS)

Файл схемы: `db/migrations/0001_init.sql`. Все запросы выполняются backend'ом
через `app/services/spatial.py`; здесь приведены их формулы и назначение.

## Расширения

```sql
CREATE EXTENSION IF NOT EXISTS postgis;   -- геометрия и география
CREATE EXTENSION IF NOT EXISTS cube;      -- хранение эмбеддингов и KNN-поиск
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- нечёткий поиск по названиям
```

## Индексы

```sql
CREATE INDEX idx_parks_geometry  ON parks  USING GIST (geometry);
CREATE INDEX idx_parks_centroid  ON parks  USING GIST (centroid);
CREATE INDEX idx_parks_ll        ON parks  USING GIST (ll_to_earth(latitude, longitude));
CREATE INDEX idx_poi_geometry    ON poi    USING GIST (geometry);
CREATE INDEX idx_roads_geometry  ON park_roads USING GIST (geometry);
CREATE INDEX idx_exits_geometry  ON park_exits USING GIST (geometry);
CREATE INDEX idx_places_name_trgm ON geo_places USING GIN (name gin_trgm_ops);
CREATE INDEX idx_embeddings_vec  ON parks USING GIST (embedding cube);
```

## Ближайшие объекты (KNN, «что рядом»)

Порядковый номер расстояния (`<->`) заставляет PostgreSQL использовать GiST-индекс
и возвращать строки в порядке удалённости — без сортировки всего набора:

```sql
SELECT p.*, ST_Distance(p.centroid::geography, ll_to_earth(:lat, :lon)::geography) AS distance_m
FROM parks p
ORDER BY p.centroid <-> ST_SetSRID(ST_MakePoint(:lon, :lat), 4327)
LIMIT 10;
```

## Поиск в радиусе (ST_DWithin + geography)

```sql
SELECT p.*, ST_Distance(p.centroid::geography, ll_to_earth(:lat, :lon)::geography) AS distance_m
FROM parks p
WHERE ST_DWithin(p.centroid::geography, ll_to_earth(:lat, :lon)::geography, :radius_m)
ORDER BY distance_m
LIMIT 50;
```

`geography` даёт расстояния в метрах по сфероиду (WGS84) — это критично для
корректных «500 м от Чкаловского проспекта».

## Расстояние до ближайшего объекта

```sql
SELECT p.*, ST_Distance(p.centroid::geography, :point::geography) AS distance_m
FROM parks p
ORDER BY p.centroid <-> :point
LIMIT 1;
```

## Расстояние между двумя объектами

```sql
SELECT ST_Distance(a.centroid::geography, b.centroid::geography) AS distance_m
FROM parks a, parks b
WHERE a.id = :a_id AND b.id = :b_id;
```

## Отбор дорожек и точек интереса внутри контуров

```sql
-- точки интереса, попавшие внутрь какого-либо объекта
SELECT i.*
FROM poi i
WHERE EXISTS (
  SELECT 1 FROM parks p
  WHERE ST_Covers(p.geometry, i.geometry)
);

-- протяжённые бульвары и аллеи, не имеющие контура-полигона,
-- буферизуются (8 м) и попадают в слой парков как «линейные» объекты
SELECT ST_Buffer(way.geometry, 8) AS geometry, way.tags -> 'name' AS name
FROM osm_lines way
WHERE way.tags -> 'highway' IN ('footway', 'path', 'pedestrian')
  AND way.tags -> 'name' ~* 'бульвар|аллея|набережная';
```

## Плотность объектов по сетке (аналог «зоны доступности»)

```sql
WITH grid AS (
  SELECT ST_SnapToGrid(centroid, 0.005) AS cell, count(*) AS cnt
  FROM parks GROUP BY 1
)
SELECT cell, cnt FROM grid ORDER BY cnt DESC;
```

Используется в `stats_service.coverage_analysis`: сетка 250 м по всей площади
района, для каждой клетки считается расстояние до ближайшего объекта
(`ST_DWithin` с буфером 500 м) — так получается метрика покрытия «сколько процентов
района находится не дальше 500 м от парка/сквера».

## Поиск по названию (триграммы)

```sql
SELECT * FROM geo_places
WHERE name ILIKE '%' || :q || '%'
   OR similarity(name, :q) > 0.2
ORDER BY similarity(name, :q) DESC
LIMIT 10;
```

## Эмбеддинги в cube

```sql
-- вектор (например, 64 признака) хранится как cube
ALTER TABLE parks ADD COLUMN embedding cube;

-- расстояние между запросом и объектами (используется в рекомендациях)
SELECT id, name, embedding <-> :query_vec::cube AS sem_dist
FROM parks
ORDER BY sem_dist
LIMIT 20;
```

`cube` + GiST дают тот же принцип «KNN без сортировки», что и для геометрии.
Вектор строится локально детерминированным способом (`hashing-synonym-64`):
токены текста хэшируются с учётом словаря синонимов, суммируются и нормируются —
это воспроизводимо и не требует внешних моделей; при наличии HTTP-провайдера
эмбеддингов вектор можно заменить, не меняя остальной код.
