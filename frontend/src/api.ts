// Клиент REST API.
import type {
  AppConfig,
  CategoriesResponse,
  DistanceResponse,
  FeatureCollection,
  NearestDistanceResponse,
  NearbyResponse,
  Park,
  ParkLayers,
  ParkPhotosResponse,
  QueryResponse,
  RadiusResponse,
  RecommendResponse,
  RouteResponse,
  Scenario,
  SearchResponse,
  Statistics,
} from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    let message = "Ошибка запроса";
    try {
      const body = await response.json();
      message = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      message = `Ошибка запроса (код ${response.status})`;
    }
    const error = new Error(message) as Error & { status?: number };
    error.status = response.status;
    throw error;
  }
  return response.json() as Promise<T>;
}

export const api = {
  config: () => request<AppConfig>("/api/config"),
  health: () =>
    request<{ status: string; database: Record<string, unknown>; ai: Record<string, unknown> }>(
      "/api/health",
    ),
  categories: () => request<CategoriesResponse>("/api/categories"),
  scenarios: () => request<Scenario[]>("/api/scenarios"),
  statistics: () => request<Statistics>("/api/statistics"),

  parksGeoJSON: (category?: string[]) => {
    const params = new URLSearchParams();
    (category ?? []).forEach((c) => params.append("category", c));
    return request<FeatureCollection>(`/api/parks/geojson?${params.toString()}`);
  },
  poiGeoJSON: () => request<FeatureCollection>("/api/poi/geojson"),
  roadsGeoJSON: () => request<FeatureCollection>("/api/roads/geojson"),
  exitsGeoJSON: () => request<FeatureCollection>("/api/exits/geojson"),
  districtsGeoJSON: () => request<FeatureCollection>("/api/districts/geojson"),

  park: (id: number) => request<Park>(`/api/parks/${id}`),
  parkPhotos: (id: number) => request<ParkPhotosResponse>(`/api/parks/${id}/photos`),
  parkLayers: async (id: number): Promise<ParkLayers> => {
    const [poi, roads, exits] = await Promise.all([
      request<{ items: ParkLayers["poi"] }>(`/api/parks/${id}/poi`),
      request<{ items: ParkLayers["roads"] }>(`/api/parks/${id}/roads`),
      request<{ items: ParkLayers["exits"] }>(`/api/parks/${id}/exits`),
    ]);
    return { poi: poi.items, roads: roads.items, exits: exits.items };
  },

  nearby: (latitude: number, longitude: number, category?: string, limit = 10) => {
    const params = new URLSearchParams({
      latitude: String(latitude),
      longitude: String(longitude),
      limit: String(limit),
    });
    if (category) params.set("category", category);
    return request<NearbyResponse>(`/api/parks/nearby?${params.toString()}`);
  },
  radius: (latitude: number, longitude: number, radiusM: number, category?: string, limit = 50) => {
    const params = new URLSearchParams({
      latitude: String(latitude),
      longitude: String(longitude),
      radius_m: String(radiusM),
      limit: String(limit),
    });
    if (category) params.set("category", category);
    return request<RadiusResponse>(`/api/parks/radius?${params.toString()}`);
  },
  nearestDistance: (latitude: number, longitude: number, category?: string) => {
    const params = new URLSearchParams({
      latitude: String(latitude),
      longitude: String(longitude),
    });
    if (category) params.set("category", category);
    return request<NearestDistanceResponse>(`/api/parks/nearest_distance?${params.toString()}`);
  },
  parkRadius: (id: number, radiusM: number) =>
    request<RadiusResponse & { by_category: { category: string; count: number }[] }>(
      `/api/parks/${id}/nearby?radius_m=${radiusM}`,
    ),

  query: (text: string, latitude?: number | null, longitude?: number | null) =>
    request<QueryResponse>("/api/query", {
      method: "POST",
      body: JSON.stringify({ text, latitude, longitude }),
    }),

  recommend: (
    query: string,
    opts: { latitude?: number; longitude?: number; radius_meters?: number; limit?: number } = {},
  ) =>
    request<RecommendResponse>("/api/recommend", {
      method: "POST",
      body: JSON.stringify({ query, ...opts }),
    }),

  search: (q: string, limit = 20) =>
    request<SearchResponse>(
      `/api/parks/search?q=${encodeURIComponent(q)}&limit=${limit}`,
    ),

  distance: (fromId: number, toId: number) =>
    request<DistanceResponse>(`/api/parks/${fromId}/distance/${toId}`),

  route: (startLat: number, startLon: number, endLat: number, endLon: number, costing = "pedestrian") =>
    request<RouteResponse>("/api/route", {
      method: "POST",
      body: JSON.stringify({
        start_lat: startLat,
        start_lon: startLon,
        end_lat: endLat,
        end_lon: endLon,
        costing,
      }),
    }),

  parkGeoJSON: (id: number) =>
    request<FeatureCollection>(`/api/parks/geojson?ids=${id}`),
};
