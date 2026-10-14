import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import MapView, { DisplayMode } from "./components/MapView";
import Sidebar, { View } from "./components/Sidebar";
import { api } from "./api";
import {
  CategoriesResponse,
  FeatureCollection,
  Park,
  RouteResponse,
  Scenario,
  Statistics,
} from "./types";

export type RouteMode = "pedestrian" | "auto" | "transit";

/** Режимы маршрута: пешком, на машине, общественный транспорт. */
const ROUTE_MODES: { id: RouteMode; icon: string; label: string; hint: string }[] = [
  { id: "pedestrian", icon: "🚶", label: "Пешком", hint: "Пеший маршрут по дорожной сети парков" },
  { id: "auto", icon: "🚗", label: "На машине", hint: "Автомобильный маршрут по дорожной сети" },
  {
    id: "transit",
    icon: "🚌",
    label: "Транспорт",
    hint: "Общественный транспорт (данные OpenStreetMap; расписание — в Яндекс Картах)",
  },
];

export default function App() {
  const [parks, setParks] = useState<Park[]>([]);
  const [parksGeo, setParksGeo] = useState<FeatureCollection | null>(null);
  const [poiGeo, setPoiGeo] = useState<FeatureCollection | null>(null);
  const [roadsGeo, setRoadsGeo] = useState<FeatureCollection | null>(null);
  const [districtGeo, setDistrictGeo] = useState<FeatureCollection | null>(null);
  const [categories, setCategories] = useState<CategoriesResponse | null>(null);
  const [statistics, setStatistics] = useState<Statistics | null>(null);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);

  const [view, setView] = useState<View>("stats");
  const [mode, setMode] = useState<DisplayMode>("polygons");
  const [hiddenPoiTypes, setHiddenPoiTypes] = useState<Set<string>>(new Set());
  const [hiddenParkCats, setHiddenParkCats] = useState<Set<string>>(new Set());
  const [showPoi, setShowPoi] = useState(true);
  const [showRoads, setShowRoads] = useState(true);
  const [showDistrict, setShowDistrict] = useState(true);
  const [selectedParkId, setSelectedParkId] = useState<number | null>(null);
  // Полные данные объекта (карточка): подтягиваются из API при выборе,
  // чтобы не зависеть от набора полей в GeoJSON-слое.
  const [selectedParkDetail, setSelectedParkDetail] = useState<{
    id: number;
    park: Park | null;
  } | null>(null);
  const [results, setResults] = useState<{ park: Park; distance_m: number | null }[]>([]);
  const [resultCenter, setResultCenter] = useState<{ latitude: number; longitude: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // маршрут до выбранного объекта
  const [route, setRoute] = useState<RouteResponse | null>(null);
  const [routeDest, setRouteDest] = useState<{ lat: number; lon: number; name: string } | null>(null);
  const [pickingStart, setPickingStart] = useState(false);
  const [routeBusy, setRouteBusy] = useState(false);
  const [routeHint, setRouteHint] = useState<string | null>(null);
  // Режим маршрута: пешком / на машине / общественный транспорт.
  const [routeMode, setRouteMode] = useState<RouteMode>("pedestrian");
  // Точка старта — чтобы пересчитывать маршрут при смене режима и строить
  // ссылку на Яндекс Карты для общественного транспорта.
  const [routeStart, setRouteStart] = useState<{ lat: number; lon: number } | null>(null);
  // Реф режима: doRoute вызывается из старых замыканий (колбэк геолокации)
  // и обязан брать актуальный режим, а не значение на момент создания.
  const routeModeRef = useRef<RouteMode>("pedestrian");

  useEffect(() => {
    (async () => {
      try {
        const [parkList, cat, stat, scen] = await Promise.all([
          api.parksGeoJSON(),
          api.categories(),
          api.statistics(),
          api.scenarios(),
        ]);
        setParksGeo(parkList);
        setCategories(cat);
        setStatistics(stat);
        setScenarios(scen);
        const items: Park[] = (parkList.features as any[]).map((f) => ({
          ...f.properties,
          latitude: f.properties.latitude,
          longitude: f.properties.longitude,
        })) as Park[];
        setParks(items);
      } catch (e: any) {
        setError("Не удалось загрузить данные: " + (e?.message || e));
      } finally {
        setLoading(false);
      }
    })();

    api.poiGeoJSON().then(setPoiGeo).catch(() => undefined);
    api.roadsGeoJSON().then(setRoadsGeo).catch(() => undefined);
    api.districtsGeoJSON().then(setDistrictGeo).catch(() => undefined);
  }, []);

  const selectPark = useCallback((id: number) => {
    setSelectedParkId(id);
    setSelectedParkDetail({ id, park: null });
    setView("park");
    api
      .park(id)
      .then((full) =>
        // ответ применяется, только если объект всё ещё выбран
        setSelectedParkDetail((cur) => (cur && cur.id === id ? { id, park: full } : cur)),
      )
      .catch((e) => console.warn("Не удалось загрузить карточку объекта:", e));
  }, []);

  const onResults = useCallback(
    (
      items: { park: Park; distance_m: number | null }[],
      center?: { latitude: number; longitude: number },
    ) => {
      setResults(items);
      setResultCenter(center ?? null);
    },
    [],
  );

  const clearRoute = useCallback(() => {
    setRoute(null);
    setRouteDest(null);
    setRouteStart(null);
    setPickingStart(false);
    setRouteHint(null);
  }, []);

  const doRoute = useCallback(
    async (
      start: { lat: number; lon: number },
      dest: { lat: number; lon: number; name: string },
      mode: RouteMode = routeModeRef.current,
    ) => {
      setRouteBusy(true);
      setRoute(null); // при пересчёте не оставляем старую линию при ошибке
      setRouteStart(start);
      setRouteHint("Строим маршрут до «" + dest.name + "»…");
      try {
        const r = await api.route(start.lat, start.lon, dest.lat, dest.lon, mode);
        setRoute(r);
        setPickingStart(false);
        setRouteHint(null);
      } catch (e: any) {
        setRouteHint("Не удалось построить маршрут: " + (e?.message || e));
      } finally {
        setRouteBusy(false);
      }
    },
    [],
  );

  // Смена режима маршрута: если маршрут уже построен — пересчитываем его
  // в новом режиме от той же точки старта.
  const changeRouteMode = useCallback(
    (mode: RouteMode) => {
      routeModeRef.current = mode;
      setRouteMode(mode);
      if (!routeBusy && !pickingStart && routeStart && routeDest) {
        doRoute(routeStart, routeDest, mode);
      }
    },
    [routeBusy, pickingStart, routeStart, routeDest, doRoute],
  );

  // Официальная ссылка Яндекс Карт: маршрут «общественный транспорт» (rtt=mt)
  // с точками старта и финиша — настоящее расписание ОТ без API-ключей.
  const yandexTransitHref = useMemo(() => {
    if (!routeStart || !routeDest) return null;
    return (
      "https://yandex.ru/maps/213/saint-petersburg/?rtext=" +
      `${routeStart.lat},${routeStart.lon}~${routeDest.lat},${routeDest.lon}&rtt=mt`
    );
  }, [routeStart, routeDest]);

  const enterPickMode = useCallback((dest: { lat: number; lon: number; name: string }) => {
    setPickingStart(true);
    setRouteHint("Кликните на карте — точка старта маршрута до «" + dest.name + "»");
  }, []);

  const startRouteFlow = useCallback(
    (dest: { lat: number; lon: number; name: string }) => {
      setRoute(null);
      setRouteDest(dest);
      setRouteStart(null); // старый старт относится к прошлому маршруту
      setPickingStart(false);
      if (!("geolocation" in navigator)) {
        enterPickMode(dest);
        return;
      }
      setRouteHint("Определяем ваше местоположение…");
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          doRoute({ lat: pos.coords.latitude, lon: pos.coords.longitude }, dest);
        },
        () => enterPickMode(dest),
        { timeout: 8000, enableHighAccuracy: true },
      );
    },
    [doRoute, enterPickMode],
  );

  const useMyLocationForRoute = useCallback(() => {
    if (!routeDest || !("geolocation" in navigator)) return;
    setRouteHint("Определяем ваше местоположение…");
    navigator.geolocation.getCurrentPosition(
      (pos) => doRoute({ lat: pos.coords.latitude, lon: pos.coords.longitude }, routeDest),
      () => setRouteHint("Геолокация недоступна — кликните на карте, чтобы задать старт."),
      { timeout: 8000, enableHighAccuracy: true },
    );
  }, [routeDest, doRoute]);

  const onMapClick = useCallback(
    (lat: number, lon: number) => {
      if (pickingStart && routeDest) {
        doRoute({ lat, lon }, routeDest);
      }
    },
    [pickingStart, routeDest, doRoute],
  );

  const onPoiRoute = useCallback(
    (lat: number, lon: number, name: string) => {
      startRouteFlow({ lat, lon, name });
    },
    [startRouteFlow],
  );

  const selectedPark = useMemo(() => {
    if (selectedParkId == null) return null;
    if (
      selectedParkDetail &&
      selectedParkDetail.id === selectedParkId &&
      selectedParkDetail.park
    ) {
      return selectedParkDetail.park;
    }
    return parks.find((p) => p.id === selectedParkId) ?? null;
  }, [parks, selectedParkId, selectedParkDetail]);

  const togglePoiType = (code: string) =>
    setHiddenPoiTypes((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });

  const toggleParkCat = (code: string) =>
    setHiddenParkCats((prev) => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });

  return (
    <div className="app">
      <Sidebar
        view={view}
        setView={setView}
        categories={categories}
        statistics={statistics}
        scenarios={scenarios}
        selectedPark={selectedPark}
        results={results}
        loading={loading}
        error={error}
        onSelectPark={selectPark}
        onResults={onResults}
        onRouteToPark={(park) =>
          startRouteFlow({ lat: park.latitude, lon: park.longitude, name: park.name })
        }
        onRouteToPoint={onPoiRoute}
      />
      <main className="main">
        <div className="toolbar">
          <div className="switch">
            <button
              className={mode === "points" ? "active" : ""}
              onClick={() => setMode("points")}
            >
              Точки
            </button>
            <button
              className={mode === "polygons" ? "active" : ""}
              onClick={() => setMode("polygons")}
            >
              Полигоны
            </button>
          </div>
          <div className="filters">
            <button
              className={"filter" + (showDistrict ? "" : " off")}
              onClick={() => setShowDistrict((v) => !v)}
              title="Показать / скрыть границу района"
            >
              Граница района
            </button>
            <button
              className={"filter" + (showRoads ? "" : " off")}
              onClick={() => setShowRoads((v) => !v)}
              title="Показать / скрыть дороги"
            >
              Дороги
            </button>
            <button
              className={"filter" + (showPoi ? "" : " off")}
              onClick={() => setShowPoi((v) => !v)}
              title="Показать / скрыть все точки интереса"
            >
              Точки интереса
            </button>
            {(categories?.categories ?? [])
              .filter((c) => c.count > 0)
              .map((c) => (
                <button
                  key={c.code}
                  className={"filter" + (hiddenParkCats.has(c.code) ? " off" : "")}
                  onClick={() => toggleParkCat(c.code)}
                  title="Показать / скрыть слой"
                >
                  <span className="legend-symbol" style={{ background: catColor(c.code) }}>
                    {catSymbol(c.code)}
                  </span>
                  {c.label}
                </button>
              ))}
            {(categories?.poi_types ?? [])
              .filter((t) => t.count > 0)
              .map((t) => (
                <button
                  key={t.code}
                  className={"filter" + (hiddenPoiTypes.has(t.code) ? " off" : "") + (showPoi ? "" : " disabled")}
                  onClick={() => togglePoiType(t.code)}
                  title="Показать / скрыть слой"
                >
                  <span className="poi-badge sm" style={{ background: t.color || "#607d8b" }}>
                    {t.icon}
                  </span>
                  {t.label}
                </button>
              ))}
          </div>
        </div>
        <MapView
          parksGeo={parksGeo}
          poiGeo={poiGeo}
          roadsGeo={roadsGeo}
          districtGeo={districtGeo}
          mode={mode}
          hiddenPoiTypes={hiddenPoiTypes}
          hiddenParkCats={hiddenParkCats}
          showPoi={showPoi}
          showRoads={showRoads}
          showDistrict={showDistrict}
          selectedParkId={selectedParkId}
          results={results}
          resultParks={parks}
          onParkClick={selectPark}
          route={route}
          routeDest={routeDest}
          pickingStart={pickingStart}
          onMapClick={onMapClick}
          onPoiRoute={onPoiRoute}
        />
        {resultCenter && (
          <div className="center-hint">
            Точка отсчёта: {resultCenter.latitude.toFixed(5)}, {resultCenter.longitude.toFixed(5)}
          </div>
        )}
        {(route || pickingStart || routeBusy || routeHint) && (
          <div className="route-panel">
            <div className="route-modes" role="group" aria-label="Режим маршрута">
              {ROUTE_MODES.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  className={"route-mode" + (routeMode === m.id ? " active" : "")}
                  onClick={() => changeRouteMode(m.id)}
                  disabled={routeBusy}
                  title={m.hint}
                >
                  {m.icon} {m.label}
                </button>
              ))}
            </div>
            <div className="route-main">
              {route ? (
                <>
                  <span className="route-info">
                    {route.costing === "auto" ? "🚗" : route.costing === "transit" ? "🚌" : "🚶"}{" "}
                    {route.distance_m < 1000
                      ? Math.round(route.distance_m) + " м"
                      : (route.distance_m / 1000).toFixed(2) + " км"}
                    {route.duration_s != null && <> · ≈ {Math.max(1, Math.round(route.duration_s / 60))} мин</>}
                    {route.approximate && <> · пеший ориентир</>}
                    <> · {route.source === "osrm" ? "дорожная сеть OSRM" : "дорожная сеть Valhalla"}</>
                    {routeDest && <> · до «{routeDest.name}»</>}
                  </span>
                  <button onClick={clearRoute}>Сбросить маршрут</button>
                </>
              ) : pickingStart ? (
                <>
                  <span className="route-info">📍 {routeHint}</span>
                  <button onClick={useMyLocationForRoute}>Моё местоположение</button>
                  <button onClick={clearRoute}>Отмена</button>
                </>
              ) : routeBusy ? (
                <span className="route-info">⏳ {routeHint}</span>
              ) : (
                <>
                  <span className="route-info">⚠ {routeHint}</span>
                  <button onClick={clearRoute}>Закрыть</button>
                </>
              )}
            </div>
            {route?.notice && <div className="route-notice">⚠ {route.notice}</div>}
            {routeMode === "transit" && yandexTransitHref && (
              <a
                className="route-yandex"
                href={yandexTransitHref}
                target="_blank"
                rel="noopener noreferrer"
                title="Маршрут общественного транспорта с расписанием в Яндекс Картах"
              >
                🚌 Точное расписание ОТ — в Яндекс Картах →
              </a>
            )}
          </div>
        )}
      </main>
    </div>
  );
}

function catColor(code: string) {
  return code === "garden" ? "#6a1b9a" : code === "square" ? "#1565c0" : code === "boulevard" ? "#ef6c00" : "#2e7d32";
}
function catSymbol(code: string) {
  return code === "garden" ? "✿" : code === "square" ? "◇" : code === "boulevard" ? "═" : "♣";
}
