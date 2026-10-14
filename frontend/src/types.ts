// Типы, соответствующие контракту REST API бэкенда.

export interface Park {
  id: number;
  name: string;
  category: string;
  category_label: string;
  description?: string | null;
  address?: string | null;
  borough?: string | null;
  latitude: number;
  longitude: number;
  area_sqm?: number | null;
  is_free?: boolean | null;
  working_hours?: string | null;
  website?: string | null;
  phone?: string | null;
  image_url?: string | null;
  year_established?: number | null;
  metro_stations: string[];
  facilities: string[];
  themes: string[];
  keywords: string[];
  has_poi: boolean;
  has_roads: boolean;
  has_exits: boolean;
  poi_count: number;
  road_count: number;
  exit_count: number;
  osm_id?: number | null;
  osm_type?: string | null;
  source: string;
}

export interface NearbyItem {
  park: Park;
  distance_m: number | null;
  distance_km: number | null;
  score?: number | null;
  reason?: string | null;
  semantic_score?: number | null;
  spatial_score?: number | null;
  category_score?: number | null;
}

export interface StructuredQuery {
  intent: string;
  category?: string | null;
  poi_type?: string | null;
  location?: {
    type: string;
    name?: string | null;
    latitude?: number | null;
    longitude?: number | null;
  } | null;
  location2?: { type: string; name?: string | null } | null;
  radius_meters?: number | null;
  limit?: number | null;
  sort?: string | null;
  text?: string | null;
  park_name?: string | null;
}

export interface QueryResponse {
  text: string;
  source: "llm" | "rules" | "cached";
  mode: "ai_search" | "gis_search";
  structured: StructuredQuery;
  center?: {
    latitude: number | null;
    longitude: number | null;
    name?: string | null;
    radius_m?: number;
  } | null;
  radius_m?: number | null;
  count: number;
  results: NearbyItem[];
  poi: PoiItem[];
  warnings: string[];
}

export interface PoiItem {
  id: number;
  park_id: number;
  poi_type: string;
  poi_type_label: string;
  icon?: string;
  color?: string;
  name?: string | null;
  description?: string | null;
  park_name?: string | null;
  latitude: number;
  longitude: number;
  distance_m?: number | null;
}

export interface ParkPhoto {
  url: string;
  title?: string | null;
  page?: string | null;
}

export interface ParkPhotosResponse {
  park_id: number;
  park_name: string;
  photos: ParkPhoto[];
}

export interface SearchResponse {
  total: number;
  items: Park[];
  poi: PoiItem[];
}

export interface RoadItem {
  id: number;
  park_id: number;
  road_type: string;
  road_type_label: string;
  name?: string | null;
  length_m?: number | null;
}

export interface ExitItem {
  id: number;
  park_id: number;
  exit_type: "entrance" | "exit";
  name?: string | null;
  latitude: number;
  longitude: number;
}

export interface CategoryItem {
  code: string;
  label: string;
  count: number;
}

export interface PoiTypeItem {
  code: string;
  label: string;
  icon: string;
  color?: string;
  count: number;
}

export interface CategoriesResponse {
  categories: CategoryItem[];
  poi_types: PoiTypeItem[];
  road_types: { code: string; label: string; count: number }[];
}

export interface RecommendItem {
  park: Park;
  score: number;
  semantic_score: number | null;
  spatial_score: number | null;
  category_score: number | null;
  distance_m: number | null;
  distance_km: number | null;
  reason: string;
}

export interface RecommendResponse {
  query: string;
  weights: Record<string, number>;
  count: number;
  center?: Record<string, unknown> | null;
  results: RecommendItem[];
}

export interface DistanceResponse {
  from_id: number;
  to_id: number;
  distance_m: number;
  distance_km: number;
}

export interface QueryResultItem {
  park: Park;
  distance_m: number | null;
  distance_km: number | null;
  score: number | null;
  reason: string | null;
}

export interface Scenario {
  id: string;
  title: string;
  text: string;
  kind: "gis" | "ai" | "recommend";
}

export interface Statistics {
  parks_total: number;
  area_total_sqm: number;
  by_category: { category: string; count: number; area_sum_sqm: number; area_avg_sqm: number }[];
  poi_total: number;
  poi_by_type: { poi_type: string; count: number }[];
  roads_total: number;
  roads_length_m: number;
  exits_total: number;
  avg_nearest_neighbor_m: number;
  densest_zones: {
    cell_x: number;
    cell_y: number;
    count: number;
    center_lat: number;
    center_lon: number;
  }[];
  coverage: {
    step_m: number;
    distance_m: number;
    cells_total: number;
    cells_covered: number;
    covered_pct: number;
    avg_distance_m: number;
    max_distance_m: number;
  };
}

export interface AppConfig {
  tile_url: string;
  tile_attribution: string;
  max_radius_m: number;
  max_limit: number;
  borough: string;
  center: { latitude: number; longitude: number };
  zoom: number;
  ranking_weights: Record<string, number>;
}

export interface GeoJSONFeature {
  type: "Feature";
  id?: number | string;
  geometry:
    | { type: "Polygon"; coordinates: number[][][] }
    | { type: "MultiPolygon"; coordinates: number[][][][] }
    | { type: "Point"; coordinates: number[] }
    | { type: "LineString"; coordinates: number[][] };
  properties: Record<string, unknown>;
}

export interface FeatureCollection {
  type: "FeatureCollection";
  features: GeoJSONFeature[];
}

export interface NearbyResponse {
  center: Record<string, unknown>;
  count: number;
  items: NearbyItem[];
}

export interface RadiusResponse extends NearbyResponse {
  radius_m: number;
  by_category?: { category: string; count: number }[];
}

export interface NearestDistanceResponse {
  latitude: number;
  longitude: number;
  distance_m: number;
  distance_km: number;
  nearest_park: Park;
  walking_minutes?: number | null;
}

export interface ParkLayers {
  poi: PoiItem[];
  roads: RoadItem[];
  exits: ExitItem[];
}

export interface RouteResponse {
  geometry: { type: "LineString"; coordinates: [number, number][] };
  distance_m: number;
  duration_s: number | null;
  /** Роутер, построивший путь по дорожной сети (Valhalla либо OSRM). */
  source: "valhalla" | "osrm";
}
