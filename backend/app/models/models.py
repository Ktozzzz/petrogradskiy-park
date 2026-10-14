# -*- coding: utf-8 -*-
"""SQLAlchemy-модели (SQLAlchemy 2.0 + GeoAlchemy2).

Геометрия хранится в PostGIS (EPSG:4326):
    parks.geometry      geometry(MultiPolygon, 4326)
    parks.centroid      geometry(Point, 4326)
    poi.geometry        geometry(Point, 4326)
    park_roads.geometry geometry(LineString, 4326)
    park_exits.geometry geometry(Point, 4326)

Семантические вектора хранятся в типе cube расширения PostgreSQL
(колонка объявлена как Text, значение -- литерал cube; запросы к ней
выполняются средствами SQL на стороне БД).
"""
from geoalchemy2 import Geometry
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import ARRAY, TIMESTAMP
from sqlalchemy.orm import relationship

from ..database import Base

CATEGORIES = ("park", "garden", "square", "boulevard")

CATEGORY_LABELS = {
    "park": "Парки",
    "garden": "Сады",
    "square": "Скверы",
    "boulevard": "Бульвары и аллеи",
}

POI_TYPES = (
    "food",
    "monument",
    "attraction",
    "playground",
    "sport",
    "fountain",
    "viewpoint",
    "toilet",
    "parking",
)

POI_LABELS = {
    "food": "Места питания",
    "monument": "Памятники и скульптуры",
    "attraction": "Аттракционы и площадки",
    "playground": "Детские площадки",
    "sport": "Спортивные площадки",
    "fountain": "Фонтаны",
    "viewpoint": "Смотровые площадки",
    "toilet": "Туалеты",
    "parking": "Парковки",
}

# Значки подобраны так, чтобы на цветном кружке оставались видимыми
# (категория «Прочее» удалена по ТЗ).
POI_ICONS = {
    "food": "☕",
    "monument": "🏛",
    "attraction": "🎡",
    "playground": "⛄",
    "sport": "⚽",
    "fountain": "⛲",
    "viewpoint": "🔭",
    "toilet": "WC",
    "parking": "🅿",
}

# Цветовая подложка значка (условный знак) по типу точки интереса.
POI_COLORS = {
    "food": "#8d4a2f",
    "monument": "#37474f",
    "attraction": "#6a1b9a",
    "playground": "#ef6c00",
    "sport": "#2e7d32",
    "fountain": "#0277bd",
    "viewpoint": "#00695c",
    "toilet": "#546e7a",
    "parking": "#263238",
}

ROAD_TYPES = ("main", "path", "service", "bike")

ROAD_LABELS = {
    "main": "Основные дорожки",
    "path": "Прогулочные дорожки",
    "service": "Служебные проезды",
    "bike": "Велодорожки",
}


class District(Base):
    __tablename__ = "districts"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False, unique=True)
    geometry = Column(Geometry("MultiPolygon", srid=4326), nullable=False)
    osm_id = Column(BigInteger, nullable=True)
    source = Column(Text, nullable=False, default="OpenStreetMap")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False)


class Park(Base):
    __tablename__ = "parks"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    category = Column(String(32), nullable=False)
    description = Column(Text)
    short_description = Column(Text)
    long_description = Column(Text)
    address = Column(Text)
    borough = Column(Text, nullable=False, default="Петроградский")
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    geometry = Column(Geometry("MultiPolygon", srid=4326), nullable=False)
    centroid = Column(Geometry("Point", srid=4326), nullable=False)
    area_sqm = Column(Float)
    themes = Column(ARRAY(Text))
    keywords = Column(ARRAY(Text))
    metro_stations = Column(ARRAY(Text))
    facilities = Column(ARRAY(Text))
    year_established = Column(Integer)
    is_free = Column(Boolean)
    working_hours = Column(Text)
    website = Column(Text)
    phone = Column(Text)
    image_url = Column(Text)
    has_poi = Column(Boolean, nullable=False, default=False)
    has_roads = Column(Boolean, nullable=False, default=False)
    has_exits = Column(Boolean, nullable=False, default=False)
    osm_id = Column(BigInteger, nullable=True)
    osm_type = Column(Text)
    source = Column(Text, nullable=False, default="OpenStreetMap")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False)

    poi = relationship("Poi", back_populates="park", cascade="all, delete-orphan")
    roads = relationship("ParkRoad", back_populates="park", cascade="all, delete-orphan")
    exits = relationship("ParkExit", back_populates="park", cascade="all, delete-orphan")


class Poi(Base):
    __tablename__ = "poi"

    id = Column(Integer, primary_key=True)
    park_id = Column(Integer, ForeignKey("parks.id", ondelete="CASCADE"), nullable=False)
    poi_type = Column(String(32), nullable=False)
    name = Column(Text)
    description = Column(Text)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    geometry = Column(Geometry("Point", srid=4326), nullable=False)
    osm_id = Column(BigInteger, nullable=True)
    osm_type = Column(Text)
    source = Column(Text, nullable=False, default="OpenStreetMap")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False)

    park = relationship("Park", back_populates="poi")


class ParkRoad(Base):
    __tablename__ = "park_roads"

    id = Column(Integer, primary_key=True)
    park_id = Column(Integer, ForeignKey("parks.id", ondelete="CASCADE"), nullable=False)
    road_type = Column(String(32), nullable=False)
    name = Column(Text)
    geometry = Column(Geometry("LineString", srid=4326), nullable=False)
    length_m = Column(Float)
    osm_id = Column(BigInteger, nullable=True)
    osm_type = Column(Text)
    source = Column(Text, nullable=False, default="OpenStreetMap")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False)

    park = relationship("Park", back_populates="roads")


class ParkExit(Base):
    __tablename__ = "park_exits"

    id = Column(Integer, primary_key=True)
    park_id = Column(Integer, ForeignKey("parks.id", ondelete="CASCADE"), nullable=False)
    exit_type = Column(String(16), nullable=False)
    name = Column(Text)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    geometry = Column(Geometry("Point", srid=4326), nullable=False)
    osm_id = Column(BigInteger, nullable=True)
    osm_type = Column(Text)
    source = Column(Text, nullable=False, default="OpenStreetMap")
    created_at = Column(TIMESTAMP(timezone=True), nullable=False)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False)

    park = relationship("Park", back_populates="exits")


class GeoPlace(Base):
    __tablename__ = "geo_places"

    id = Column(Integer, primary_key=True)
    name = Column(Text, nullable=False)
    aliases = Column(ARRAY(Text))
    kind = Column(Text, nullable=False, default="landmark")
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    geometry = Column(Geometry("Point", srid=4326), nullable=False)
    source = Column(Text, nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), nullable=False)


class ParkEmbedding(Base):
    """Векторные представления объектов (семантический поиск).

    Колонка embedding хранит литерал типа cube (расширение PostgreSQL),
    запросы расстояния выполняются оператором <-> на стороне БД.
    """

    __tablename__ = "park_embeddings"

    park_id = Column(Integer, ForeignKey("parks.id", ondelete="CASCADE"), primary_key=True)
    embedding = Column(Text, nullable=False)
    model = Column(Text, nullable=False)
    text_hash = Column(Text)
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False)
