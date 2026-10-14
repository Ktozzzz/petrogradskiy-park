-- =====================================================================
-- 0001_init.sql — структура пространственной базы данных проекта
-- «Парки и сады Петроградского района Санкт-Петербурга»
-- PostgreSQL 16+ / PostGIS 3.x, CRS: EPSG:4326
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS cube;      -- векторные представления текста (семантика)
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- нечёткий поиск по названиям

-- ---------------------------------------------------------------------
-- Границы административных районов (polygon layer)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS districts (
    id            serial PRIMARY KEY,
    name          text NOT NULL UNIQUE,
    geometry      geometry(MultiPolygon, 4326) NOT NULL,
    osm_id        bigint,
    source        text NOT NULL DEFAULT 'OpenStreetMap',
    created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_districts_geom ON districts USING gist (geometry);

-- ---------------------------------------------------------------------
-- Основная сущность: парки, сады, скверы, бульвары и аллеи
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS parks (
    id                serial PRIMARY KEY,
    name              text NOT NULL,
    category          text NOT NULL
                      CHECK (category IN ('park','garden','square','boulevard')),
    description       text,
    short_description text,
    long_description  text,
    address           text,
    borough           text NOT NULL DEFAULT 'Петроградский',
    latitude          double precision NOT NULL,
    longitude         double precision NOT NULL,
    geometry          geometry(MultiPolygon, 4326) NOT NULL,
    centroid          geometry(Point, 4326) NOT NULL,
    area_sqm          double precision,
    themes            text[] DEFAULT '{}',
    keywords          text[] DEFAULT '{}',
    metro_stations    text[] DEFAULT '{}',
    facilities        text[] DEFAULT '{}',
    year_established  integer,
    is_free           boolean,
    working_hours     text,
    website           text,
    phone             text,
    image_url         text,
    has_poi           boolean NOT NULL DEFAULT false,
    has_roads         boolean NOT NULL DEFAULT false,
    has_exits         boolean NOT NULL DEFAULT false,
    osm_id            bigint,
    osm_type          text,
    source            text NOT NULL DEFAULT 'OpenStreetMap',
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_parks_geom        ON parks USING gist (geometry);
CREATE INDEX IF NOT EXISTS idx_parks_centroid    ON parks USING gist (centroid);
CREATE INDEX IF NOT EXISTS idx_parks_category    ON parks (category);
CREATE INDEX IF NOT EXISTS idx_parks_name_trgm   ON parks USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_parks_keywords    ON parks USING gin (keywords);

-- ---------------------------------------------------------------------
-- Точки интереса внутри парков и садов
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS poi (
    id          serial PRIMARY KEY,
    park_id     integer NOT NULL REFERENCES parks (id) ON DELETE CASCADE,
    poi_type    text NOT NULL
                CHECK (poi_type IN ('food','monument','attraction','playground',
                                    'sport','fountain','viewpoint','toilet',
                                    'parking','other')),
    name        text,
    description text,
    latitude    double precision NOT NULL,
    longitude   double precision NOT NULL,
    geometry    geometry(Point, 4326) NOT NULL,
    osm_id      bigint,
    osm_type    text,
    source      text NOT NULL DEFAULT 'OpenStreetMap',
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_poi_geom   ON poi USING gist (geometry);
CREATE INDEX IF NOT EXISTS idx_poi_park   ON poi (park_id);
CREATE INDEX IF NOT EXISTS idx_poi_type   ON poi (poi_type);

-- ---------------------------------------------------------------------
-- Дороги и дорожки внутри парков
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS park_roads (
    id          serial PRIMARY KEY,
    park_id     integer NOT NULL REFERENCES parks (id) ON DELETE CASCADE,
    road_type   text NOT NULL CHECK (road_type IN ('main','path','service','bike')),
    name        text,
    geometry    geometry(LineString, 4326) NOT NULL,
    length_m    double precision,
    osm_id      bigint,
    osm_type    text,
    source      text NOT NULL DEFAULT 'OpenStreetMap',
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_roads_geom  ON park_roads USING gist (geometry);
CREATE INDEX IF NOT EXISTS idx_roads_park  ON park_roads (park_id);

-- ---------------------------------------------------------------------
-- Входы и выходы
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS park_exits (
    id          serial PRIMARY KEY,
    park_id     integer NOT NULL REFERENCES parks (id) ON DELETE CASCADE,
    exit_type   text NOT NULL CHECK (exit_type IN ('entrance','exit')),
    name        text,
    latitude    double precision NOT NULL,
    longitude   double precision NOT NULL,
    geometry    geometry(Point, 4326) NOT NULL,
    rotation_deg double precision NOT NULL DEFAULT 0,
    osm_id      bigint,
    osm_type    text,
    source      text NOT NULL DEFAULT 'OpenStreetMap',
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_exits_geom ON park_exits USING gist (geometry);
CREATE INDEX IF NOT EXISTS idx_exits_park ON park_exits (park_id);

-- ---------------------------------------------------------------------
-- Справочник географических названий (Location Resolver)
-- Ориентиры: метро, проспекты, площади, острова и т. п.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS geo_places (
    id          serial PRIMARY KEY,
    name        text NOT NULL,
    aliases     text[] DEFAULT '{}',
    kind        text NOT NULL DEFAULT 'landmark',
    latitude    double precision NOT NULL,
    longitude   double precision NOT NULL,
    geometry    geometry(Point, 4326) NOT NULL,
    source      text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_places_geom ON geo_places USING gist (geometry);
CREATE INDEX IF NOT EXISTS idx_places_name ON geo_places USING gin (name gin_trgm_ops);

-- ---------------------------------------------------------------------
-- Семантические векторные представления объектов.
-- Хранится в типе cube (расширение PostgreSQL) с индексом GiST,
-- что даёт поиск ближайших соседей в векторном пространстве на стороне БД.
-- При подключении pgvector колонка заменяется на vector без изменения API.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS park_embeddings (
    park_id     integer PRIMARY KEY REFERENCES parks (id) ON DELETE CASCADE,
    embedding   cube NOT NULL,
    model       text NOT NULL,
    text_hash   text,
    updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_embeddings_gist ON park_embeddings USING gist (embedding);

-- ---------------------------------------------------------------------
-- Источники данных (происхождение каждой записи)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS data_sources (
    id          serial PRIMARY KEY,
    source      text NOT NULL UNIQUE,
    url         text,
    description text,
    imported_at timestamptz NOT NULL DEFAULT now()
);
