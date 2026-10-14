# -*- coding: utf-8 -*-
"""Pydantic-схемы API и валидация структурированных запросов.

Структурированный запрос (StructuredQuery) -- это тот формат, который
должен вернуть AI/NLP слой. Схема валидирует его на стороне backend:
intent, категория, координаты, радиус и limit проверяются до выполнения
запроса к базе. AI не имеет доступа к SQL.
"""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from ..models import CATEGORIES, POI_TYPES

CategoryLiteral = Literal["park", "garden", "square", "boulevard"]
PoiTypeLiteral = Literal[
    "food", "monument", "attraction", "playground", "sport",
    "fountain", "viewpoint", "toilet", "parking",
]
IntentLiteral = Literal[
    "nearby",           # ближайшие объекты
    "radius_search",    # поиск в радиусе
    "search",           # текстовый поиск
    "distance",         # расстояние между двумя объектами
    "nearest_distance", # расстояние до ближайшего объекта
    "poi_search",       # поиск точек интереса внутри объекта
    "recommend",        # рекомендации
    "category_search",  # выборка по категории
    "location_search",  # поиск относительно географического названия
]


class ParkOut(BaseModel):
    id: int
    name: str
    category: str
    category_label: str
    description: Optional[str] = None
    address: Optional[str] = None
    borough: Optional[str] = "Петроградский"
    latitude: float
    longitude: float
    area_sqm: Optional[float] = None
    is_free: Optional[bool] = None
    working_hours: Optional[str] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    image_url: Optional[str] = None
    year_established: Optional[int] = None
    metro_stations: List[str] = []
    facilities: List[str] = []
    themes: List[str] = []
    keywords: List[str] = []
    has_poi: bool = False
    has_roads: bool = False
    has_exits: bool = False
    poi_count: int = 0
    road_count: int = 0
    exit_count: int = 0
    osm_id: Optional[int] = None
    osm_type: Optional[str] = None
    source: str = "OpenStreetMap"


class ParkListResponse(BaseModel):
    total: int
    items: List[ParkOut]


class ParkPhoto(BaseModel):
    url: str
    title: Optional[str] = None
    page: Optional[str] = None


class ParkPhotosResponse(BaseModel):
    park_id: int
    park_name: str
    photos: List[ParkPhoto] = []


class NearbyItem(BaseModel):
    park: ParkOut
    distance_m: float
    distance_km: float


class NearbyResponse(BaseModel):
    center: dict
    count: int
    items: List[NearbyItem]


class RadiusResponse(BaseModel):
    center: dict
    radius_m: float
    count: int
    items: List[NearbyItem]
    by_category: List[dict] = []


class NearestDistanceResponse(BaseModel):
    latitude: float
    longitude: float
    distance_m: float
    distance_km: float
    nearest_park: ParkOut
    walking_minutes: Optional[int] = None


class DistanceResponse(BaseModel):
    from_id: int
    to_id: int
    distance_m: float
    distance_km: float


class PoiOut(BaseModel):
    id: int
    park_id: int
    poi_type: str
    poi_type_label: str
    icon: Optional[str] = None
    color: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    park_name: Optional[str] = None
    latitude: float
    longitude: float
    distance_m: Optional[float] = None


class SearchResponse(BaseModel):
    """Текстовый поиск: объекты + интересные локации."""

    total: int
    items: List[ParkOut] = []
    poi: List[PoiOut] = []


class RoadOut(BaseModel):
    id: int
    park_id: int
    road_type: str
    road_type_label: str
    name: Optional[str] = None
    length_m: Optional[float] = None


class ExitOut(BaseModel):
    id: int
    park_id: int
    exit_type: str
    name: Optional[str] = None
    latitude: float
    longitude: float


class CategoryItem(BaseModel):
    code: str
    label: str
    count: int


class PoiTypeItem(BaseModel):
    code: str
    label: str
    icon: str
    color: Optional[str] = None
    count: int


class CategoriesResponse(BaseModel):
    categories: List[CategoryItem]
    poi_types: List[PoiTypeItem]
    road_types: List[dict]


# ---------------------------------------------------------------------
# Структурированный запрос (результат работы AI/NLP слоя)
# ---------------------------------------------------------------------
class LocationSpec(BaseModel):
    """Географическая точка отсчёта запроса."""

    type: Literal["coords", "place", "park", "here"] = "place"
    name: Optional[str] = None
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)

    class Config:
        extra = "ignore"


class StructuredQuery(BaseModel):
    """Строгая схема запроса, который возвращает NLP/AI слой."""

    intent: IntentLiteral
    category: Optional[CategoryLiteral] = None
    poi_type: Optional[PoiTypeLiteral] = None
    location: Optional[LocationSpec] = None
    location2: Optional[LocationSpec] = None
    radius_meters: Optional[int] = Field(None, ge=1, le=50000)
    limit: Optional[int] = Field(None, ge=1, le=100)
    sort: Optional[Literal["distance", "relevance", "name"]] = None
    text: Optional[str] = Field(None, max_length=300)
    park_name: Optional[str] = Field(None, max_length=200)

    class Config:
        extra = "ignore"


class QueryRequest(BaseModel):
    text: str = Field(..., min_length=2, max_length=500)
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)


class QueryResultItem(BaseModel):
    park: ParkOut
    distance_m: Optional[float] = None
    distance_km: Optional[float] = None
    score: Optional[float] = None
    reason: Optional[str] = None


class QueryResponse(BaseModel):
    """Ответ на запрос естественным языком."""

    text: str
    source: Literal["llm", "rules", "cached"]
    mode: Literal["ai_search", "gis_search"]
    structured: StructuredQuery
    center: Optional[dict] = None
    radius_m: Optional[float] = None
    count: int = 0
    results: List[QueryResultItem] = []
    poi: List[PoiOut] = []
    warnings: List[str] = []


class RecommendRequest(BaseModel):
    query: str = Field(..., min_length=2, max_length=500)
    latitude: Optional[float] = Field(None, ge=-90, le=90)
    longitude: Optional[float] = Field(None, ge=-180, le=180)
    radius_meters: Optional[int] = Field(None, ge=1, le=20000)
    limit: Optional[int] = Field(None, ge=1, le=50)


class RecommendItem(BaseModel):
    park: ParkOut
    score: float
    semantic_score: float
    spatial_score: Optional[float] = None
    category_score: Optional[float] = None
    distance_m: Optional[float] = None
    distance_km: Optional[float] = None
    reason: str


class RecommendResponse(BaseModel):
    query: str
    weights: dict
    count: int
    center: Optional[dict] = None
    results: List[RecommendItem]


class HealthResponse(BaseModel):
    status: str
    database: dict
    ai: dict


class StatisticsResponse(BaseModel):
    parks_total: int
    area_total_sqm: float
    area_avg_by_category: List[dict] = []
    by_category: List[dict] = []
    poi_total: int
    poi_by_type: List[dict] = []
    roads_total: int
    roads_length_m: float
    exits_total: int
    avg_nearest_neighbor_m: float
    densest_zones: List[dict] = []
    coverage: dict = {}


class ScenarioItem(BaseModel):
    id: str
    title: str
    text: str
    kind: Literal["gis", "ai", "recommend"]
