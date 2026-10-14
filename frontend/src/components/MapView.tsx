import { useEffect, useRef } from "react";
import L from "leaflet";
import { FeatureCollection, Park, RouteResponse } from "../types";

export type DisplayMode = "points" | "polygons";

type Props = {
  parksGeo: FeatureCollection | null;
  poiGeo: FeatureCollection | null;
  roadsGeo: FeatureCollection | null;
  districtGeo: FeatureCollection | null;
  mode: DisplayMode;
  hiddenPoiTypes: Set<string>;
  hiddenParkCats: Set<string>;
  showPoi: boolean;
  showRoads: boolean;
  showDistrict: boolean;
  selectedParkId: number | null;
  results: { park: Park; distance_m: number | null }[];
  resultParks: Park[];
  onParkClick: (id: number) => void;
  route: RouteResponse | null;
  routeDest: { lat: number; lon: number; name: string } | null;
  pickingStart: boolean;
  onMapClick: (lat: number, lon: number) => void;
  onPoiRoute: (lat: number, lon: number, name: string) => void;
};

const CATEGORY_COLORS: Record<string, string> = {
  park: "#2e7d32",
  garden: "#6a1b9a",
  square: "#1565c0",
  boulevard: "#ef6c00",
};

const CATEGORY_SYMBOLS: Record<string, string> = {
  park: "♣",
  garden: "✿",
  square: "◇",
  boulevard: "═",
};

const POI_COLORS: Record<string, string> = {
  food: "#8d4a2f",
  monument: "#37474f",
  attraction: "#6a1b9a",
  playground: "#ef6c00",
  sport: "#2e7d32",
  fountain: "#0277bd",
  viewpoint: "#00695c",
  toilet: "#546e7a",
  parking: "#263238",
};

const ROAD_STYLES: Record<string, { color: string; weight: number; dash?: string }> = {
  main: { color: "#5d4037", weight: 4 },
  path: { color: "#f9a825", weight: 2, dash: "6 4" },
  service: { color: "#9e9e9e", weight: 1.5 },
  bike: { color: "#0288d1", weight: 2.5, dash: "8 3" },
};

export default function MapView(props: Props) {
  const {
    parksGeo, poiGeo, roadsGeo, districtGeo,
    mode, hiddenPoiTypes, hiddenParkCats,
    showPoi, showRoads, showDistrict,
    selectedParkId, results, resultParks, onParkClick,
    route, routeDest, pickingStart, onMapClick, onPoiRoute,
  } = props;

  const divRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const layersRef = useRef<Record<string, L.LayerGroup> | null>(null);
  const clickRef = useRef(onParkClick);
  const mapClickRef = useRef(onMapClick);
  const poiRouteRef = useRef(onPoiRoute);
  const pickingRef = useRef(pickingStart);
  mapClickRef.current = onMapClick;
  poiRouteRef.current = onPoiRoute;
  pickingRef.current = pickingStart;
  clickRef.current = onParkClick;

  useEffect(() => {
    if (!divRef.current || mapRef.current) return;
    const map = L.map(divRef.current, {
      center: [59.956, 30.306],
      zoom: 13,
      zoomControl: true,
    });
    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: "&copy; <a href='https://www.openstreetmap.org/copyright'>OpenStreetMap</a>",
    }).addTo(map);
    const names = ["district", "parks", "roads", "poi", "results", "route"];
    const layers: Record<string, L.LayerGroup> = {};
    names.forEach((n) => {
      layers[n] = L.layerGroup().addTo(map);
    });
    layersRef.current = layers;
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
      layersRef.current = null;
    };
  }, []);

  // district border
  useEffect(() => {
    const layers = layersRef.current;
    if (!layers) return;
    layers.district.clearLayers();
    if (!districtGeo || !showDistrict) return;
    L.geoJSON(districtGeo as any, {
      style: { color: "#37474f", weight: 2, dashArray: "8 6", fillOpacity: 0.02, fillColor: "#90a4ae" },
      interactive: false,
    }).addTo(layers.district);
  }, [districtGeo, showDistrict]);

  // parks: polygons (mode=polygons) or centroid point signs (mode=points)
  useEffect(() => {
    const layers = layersRef.current;
    if (!layers) return;
    layers.parks.clearLayers();
    if (!parksGeo) return;

    if (mode === "points") {
      // Точки в центроиде каждого парка/сада/сквера/бульвара.
      (parksGeo.features as any[]).forEach((f) => {
        const p = f?.properties || {};
        if (hiddenParkCats.has(p.category)) return;
        const lat = p.latitude as number;
        const lon = p.longitude as number;
        if (!lat || !lon) return;
        const color = CATEGORY_COLORS[p.category] || "#2e7d32";
        const symbol = CATEGORY_SYMBOLS[p.category] || "♣";
        const selected = p.id === selectedParkId;
        const marker = L.marker([lat, lon], {
          icon: L.divIcon({
            className: "park-icon",
            html: `<span class="park-badge${selected ? " selected" : ""}" style="background:${color}">${symbol}</span>`,
            iconSize: [26, 26],
            iconAnchor: [13, 13],
          }),
          title: p.name || "",
        });
        marker.bindTooltip(
          `<b>${p.name || ""}</b><br/>${p.category_label || ""}` +
            (p.area_sqm ? `<br/>${((p.area_sqm as number) / 10000).toFixed(1)} га` : ""),
          { direction: "top", offset: [0, -12] as [number, number] },
        );
        marker.on("click", () => clickRef.current(p.id));
        marker.addTo(layers.parks);
      });
      return;
    }

    L.geoJSON(parksGeo as any, {
      filter: (f: any) => !hiddenParkCats.has(f?.properties?.category),
      style: (f: any) => {
        const color = CATEGORY_COLORS[f?.properties?.category] || "#2e7d32";
        const selected = f?.properties?.id === selectedParkId;
        return {
          color: selected ? "#d84315" : color,
          weight: selected ? 4 : 2,
          fillColor: color,
          fillOpacity: 0.25,
        };
      },
      onEachFeature: (f: any, layer: L.Layer) => {
        const p = f?.properties || {};
        layer.on("click", () => clickRef.current(p.id));
        layer.bindTooltip(
          `<b>${p.name}</b><br/>${p.category_label || ""}` +
            (p.area_sqm ? `<br/>${(p.area_sqm / 10000).toFixed(1)} га` : ""),
          { sticky: true },
        );
      },
    }).addTo(layers.parks);
  }, [parksGeo, mode, selectedParkId, hiddenParkCats]);

  // roads
  useEffect(() => {
    const layers = layersRef.current;
    if (!layers) return;
    layers.roads.clearLayers();
    if (!roadsGeo || !showRoads) return;
    L.geoJSON(roadsGeo as any, {
      style: (f: any) => {
        const s = ROAD_STYLES[f?.properties?.road_type] || ROAD_STYLES.path;
        return { color: s.color, weight: s.weight, dashArray: s.dash, opacity: 0.85 };
      },
      onEachFeature: (f: any, layer: L.Layer) => {
        const p = f?.properties || {};
        layer.bindTooltip(`${p.road_type_label || "Дорога"}${p.name ? ": " + p.name : ""}`);
      },
    }).addTo(layers.roads);
  }, [roadsGeo, showRoads]);

  // POI conditional signs
  useEffect(() => {
    const layers = layersRef.current;
    if (!layers) return;
    layers.poi.clearLayers();
    if (!poiGeo || !showPoi) return;
    L.geoJSON(poiGeo as any, {
      filter: (f: any) => !hiddenPoiTypes.has(f?.properties?.poi_type),
      pointToLayer: (f: any, latlng: L.LatLng) => {
        const p = f?.properties || {};
        const bg = (p.color as string) || POI_COLORS[p.poi_type as string] || "#607d8b";
        return L.marker(latlng, {
          icon: L.divIcon({
            className: "poi-icon",
            html: `<span class="poi-badge" style="background:${bg}" title="${p.poi_type_label || ""}">${p.icon || "•"}</span>`,
            iconSize: [22, 22],
            iconAnchor: [11, 11],
          }),
          title: (p.name as string) || (p.poi_type_label as string) || "",
        });
      },
      onEachFeature: (f: any, layer: L.Layer) => {
        const p = f?.properties || {};
        layer.bindTooltip(
          `<b>${p.name || p.poi_type_label}</b><br/>${p.park_name || ""}`,
          { direction: "top", offset: [0, -10] as [number, number] },
        );
        // Клик по точке интереса — строим маршрут до неё (если не ждём старт).
        layer.on("click", () => {
          if (pickingRef.current) return;
          const ll = (layer as L.Marker).getLatLng();
          poiRouteRef.current(ll.lat, ll.lng, p.name || p.poi_type_label || "точка интереса");
        });
      },
    }).addTo(layers.poi);
  }, [poiGeo, hiddenPoiTypes, showPoi]);

  // numbered result markers
  useEffect(() => {
    const layers = layersRef.current;
    if (!layers) return;
    layers.results.clearLayers();
    results.forEach((item, idx) => {
      const p = item.park;
      const m = L.marker([p.latitude, p.longitude], {
        icon: L.divIcon({
          className: "result-icon",
          html: `<span class="result-badge">${idx + 1}</span>`,
          iconSize: [26, 26],
          iconAnchor: [13, 13],
        }),
        title: p.name,
      });
      m.bindTooltip(
        `<b>${idx + 1}. ${p.name}</b>` +
          (item.distance_m != null ? `<br/>${Math.round(item.distance_m)} м` : ""),
      );
      m.on("click", () => clickRef.current(p.id));
      m.addTo(layers.results);
    });
    if (results.length && mapRef.current) {
      const bounds = L.latLngBounds(results.map((i) => [i.park.latitude, i.park.longitude] as [number, number]));
      mapRef.current.fitBounds(bounds, { padding: [60, 60], maxZoom: 15 });
    }
  }, [results]);

  // route: линия маршрута + метки старта и финиша
  useEffect(() => {
    const layers = layersRef.current;
    if (!layers) return;
    layers.route.clearLayers();
    if (!route) return;
    const latlngs = route.geometry.coordinates.map(
      ([lon, lat]) => [lat, lon] as [number, number],
    );
    if (latlngs.length < 2) return;
    // Цвет линии зависит от режима: пешком — синий, машина — оранжевый,
    // транспорт — бирюзовый; приближённый маршрут (пеший ориентир вместо ОТ)
    // показываем пунктиром, чтобы не выдавать его за точный.
    const routeColor =
      route.costing === "auto" ? "#ef6c00" : route.costing === "transit" ? "#00695c" : "#1565c0";
    L.polyline(latlngs, {
      color: routeColor,
      weight: 5,
      opacity: 0.9,
      dashArray: route.approximate ? "10 8" : undefined,
    }).addTo(layers.route);
    const start = latlngs[0];
    const finish = latlngs[latlngs.length - 1];
    L.marker(start, {
      icon: L.divIcon({
        className: "route-icon",
        html: '<span class="route-dot" style="background:#2e7d32">▶</span>',
        iconSize: [20, 20],
        iconAnchor: [10, 10],
      }),
      title: "Старт",
    }).addTo(layers.route);
    L.marker(finish, {
      icon: L.divIcon({
        className: "route-icon",
        html: '<span class="route-dot" style="background:#c62828">★</span>',
        iconSize: [20, 20],
        iconAnchor: [10, 10],
      }),
      title: routeDest ? routeDest.name : "Финиш",
    }).addTo(layers.route);
    if (mapRef.current) {
      mapRef.current.fitBounds(L.latLngBounds(latlngs), { padding: [70, 70], maxZoom: 16 });
    }
  }, [route, routeDest]);

  // выбор точки старта маршрута кликом по карте
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (divRef.current) divRef.current.classList.toggle("picking", pickingStart);
    if (!pickingStart) return;
    const handler = (e: L.LeafletMouseEvent) => {
      mapClickRef.current(e.latlng.lat, e.latlng.lng);
    };
    map.on("click", handler);
    return () => {
      map.off("click", handler);
      if (divRef.current) divRef.current.classList.remove("picking");
    };
  }, [pickingStart]);

  // fly to selected park
  useEffect(() => {
    if (!selectedParkId || !mapRef.current) return;
    const target =
      resultParks.find((p) => p.id === selectedParkId) ||
      (parksGeo?.features.find((f: any) => f.properties?.id === selectedParkId) as any);
    const lat = target?.latitude ?? target?.properties?.latitude;
    const lon = target?.longitude ?? target?.properties?.longitude;
    if (lat && lon) {
      mapRef.current.flyTo([lat, lon], Math.max(mapRef.current.getZoom(), 15), { duration: 0.6 });
    }
  }, [selectedParkId]);

  return <div ref={divRef} className="map-container" />;
}
