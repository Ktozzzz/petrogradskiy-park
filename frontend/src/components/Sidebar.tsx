import { useEffect, useState } from "react";
import { api } from "../api";
import {
  CategoriesResponse,
  DistanceResponse,
  NearestDistanceResponse,
  Park,
  QueryResponse,
  RadiusResponse,
  RecommendResponse,
  Scenario,
  Statistics,
} from "../types";

export type View =
  | "search"
  | "park"
  | "nearby"
  | "radius"
  | "nearest"
  | "distance"
  | "stats"
  | "query"
  | "recommend";

type Props = {
  view: View;
  setView: (v: View) => void;
  categories: CategoriesResponse | null;
  statistics: Statistics | null;
  scenarios: Scenario[];
  selectedPark: Park | null;
  results: { park: Park; distance_m: number | null }[];
  loading: boolean;
  error: string | null;
  onSelectPark: (id: number) => void;
  onResults: (
    results: { park: Park; distance_m: number | null }[],
    center?: { latitude: number; longitude: number },
  ) => void;
  onRouteToPark: (park: Park) => void;
};

export default function Sidebar(p: Props) {
  const [q, setQ] = useState("");
  const [searchResults, setSearchResults] = useState<Park[] | null>(null);
  const [searching, setSearching] = useState(false);

  const doSearch = async () => {
    if (!q.trim()) return;
    setSearching(true);
    try {
      const res = await api.search(q.trim());
      setSearchResults(res.items);
      p.setView("search");
    } catch (e: any) {
      alert("Поиск недоступен: " + (e?.message || e));
    } finally {
      setSearching(false);
    }
  };

  return (
    <aside className="sidebar">
      <header className="brand">
        <h1>Парки и сады Петроградского района</h1>
        <p>Интеллектуальный геопространственный сервис · Санкт-Петербург</p>
      </header>

      <div className="search-box">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && doSearch()}
          placeholder="Поиск: парк, сад, сквер…"
        />
        <button onClick={doSearch} disabled={searching}>
          {searching ? "…" : "Найти"}
        </button>
      </div>

      <nav className="nav">
        {(
          [
            ["stats", "📊 Статистика"],
            ["nearby", "📍 Что рядом"],
            ["radius", "⭕ В радиусе"],
            ["nearest", "🎯 Ближайший"],
            ["distance", "↔️ Расстояние"],
            ["query", "🤖 Умный запрос"],
            ["recommend", "✨ Рекомендации"],
          ] as const
        ).map(([v, label]) => (
          <button key={v} className={p.view === v ? "active" : ""} onClick={() => p.setView(v)}>
            {label}
          </button>
        ))}
      </nav>

      <div className="panel">
        {p.error && <div className="error">{p.error}</div>}
        {p.loading && <div className="muted">Загрузка данных…</div>}

        {p.view === "search" && (
          <>
            <h2>Результаты поиска</h2>
            {searchResults === null && <p className="muted">Введите запрос и нажмите «Найти».</p>}
            {searchResults && searchResults.length === 0 && <p className="muted">Ничего не найдено.</p>}
            {searchResults && searchResults.length > 0 && (
              <ul className="list">
                {searchResults.map((r) => (
                  <li key={r.id}>
                    <button className="link" onClick={() => p.onSelectPark(r.id)}>
                      {r.name}
                    </button>
                    <span className="muted"> · {r.category_label}</span>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}

        {p.view === "park" && p.selectedPark && (
          <ParkCard park={p.selectedPark} onRoute={() => p.onRouteToPark(p.selectedPark!)} />
        )}

        {p.view === "nearby" && <NearbyForm onResults={p.onResults} results={p.results} onSelect={p.onSelectPark} />}

        {p.view === "radius" && <RadiusForm onResults={p.onResults} results={p.results} onSelect={p.onSelectPark} />}

        {p.view === "nearest" && <NearestForm onSelect={p.onSelectPark} categories={p.categories} />}

        {p.view === "distance" && <DistanceForm />}

        {p.view === "stats" && p.statistics && <StatsCard s={p.statistics} categories={p.categories} />}

        {p.view === "query" && (
          <QueryForm
            scenarios={p.scenarios}
            onResults={p.onResults}
            onSelect={p.onSelectPark}
          />
        )}

        {p.view === "recommend" && <RecommendForm onResults={p.onResults} onSelect={p.onSelectPark} />}
      </div>

      <footer className="legend">
        <h3>Условные знаки</h3>
        <div className="legend-grid">
          {(p.categories?.categories ?? []).map((c) => (
            <div key={c.code} className="legend-item">
              <span className="legend-symbol" style={{ background: catColor(c.code) }}>
                {catSymbol(c.code)}
              </span>
              <span>{c.label} ({c.count})</span>
            </div>
          ))}
          {(p.categories?.poi_types ?? []).filter((t) => t.count > 0).map((t) => (
            <div key={t.code} className="legend-item">
              <span className="poi-badge sm" style={{ background: t.color || "#607d8b" }}>{t.icon}</span>
              <span>{t.label} ({t.count})</span>
            </div>
          ))}
        </div>
        <div className="legend-lines">
          <div><span className="line brown" /> главные дорожки</div>
          <div><span className="line yellow" /> тропинки и аллеи</div>
          <div><span className="line grey" /> служебные проезды</div>
          <div><span className="line blue" /> велодорожки</div>
        </div>
      </footer>
    </aside>
  );
}

function catColor(code: string) {
  return code === "garden" ? "#6a1b9a" : code === "square" ? "#1565c0" : code === "boulevard" ? "#ef6c00" : "#2e7d32";
}
function catSymbol(code: string) {
  return code === "garden" ? "✿" : code === "square" ? "◇" : code === "boulevard" ? "═" : "♣";
}

/* ------------------------------------------------------------------ */

function ParkCard({ park, onRoute }: { park: Park; onRoute?: () => void }) {
  return (
    <>
      <h2>{park.name}</h2>
      {onRoute && (
        <button className="route-btn" onClick={onRoute}>
          📍 Маршрут до объекта
        </button>
      )}
      <table className="kv">
        <tbody>
          <tr><td>Тип</td><td>{park.category_label}</td></tr>
          <tr><td>Район</td><td>{park.borough || "—"}</td></tr>
          <tr><td>Адрес</td><td>{park.address || "—"}</td></tr>
          <tr><td>Площадь</td><td>{park.area_sqm ? (park.area_sqm / 10000).toFixed(2) + " га" : "—"}</td></tr>
          <tr><td>Вход</td><td>{park.is_free == null ? "—" : park.is_free ? "Бесплатный" : "Платный"}</td></tr>
          <tr><td>Часы работы</td><td>{park.working_hours || "—"}</td></tr>
          <tr><td>Метро</td><td>{park.metro_stations.length ? park.metro_stations.join(", ") : "—"}</td></tr>
          <tr><td>Описание</td><td>{park.description || "—"}</td></tr>
          <tr><td>POI / дороги / входы</td>
            <td>{park.poi_count} / {park.road_count} / {park.exit_count}</td></tr>
          {park.facilities.length > 0 && (
            <tr><td>Объекты</td><td>{park.facilities.slice(0, 12).join(", ")}</td></tr>
          )}
          {park.themes.length > 0 && (
            <tr><td>Темы</td><td>{park.themes.join(", ")}</td></tr>
          )}
          <tr><td>Источник</td><td>{park.source}</td></tr>
        </tbody>
      </table>
    </>
  );
}

function ResultList({
  results,
  onSelect,
}: {
  results: { park: Park; distance_m: number | null }[];
  onSelect: (id: number) => void;
}) {
  if (!results.length) return null;
  return (
    <ol className="list numbered">
      {results.map((r, i) => (
        <li key={r.park.id}>
          <button className="link" onClick={() => onSelect(r.park.id)}>{r.park.name}</button>
          <span className="muted"> · {r.park.category_label}</span>
          {r.distance_m != null && <span className="muted"> · {fmt(r.distance_m)}</span>}
        </li>
      ))}
    </ol>
  );
}

function fmt(m: number | null | undefined) {
  if (m == null) return "";
  return m < 1000 ? `${Math.round(m)} м` : `${(m / 1000).toFixed(2)} км`;
}

function NearbyForm(p: {
  onResults: Props["onResults"];
  results: Props["results"];
  onSelect: (id: number) => void;
}) {
  const [limit, setLimit] = useState(10);
  const [category, setCategory] = useState("");
  const [status, setStatus] = useState("");
  const run = async () => {
    setStatus("Определяем позицию…");
    let latitude = 59.956;
    let longitude = 30.306;
    try {
      const pos = await new Promise<GeolocationPosition>((res, rej) =>
        navigator.geolocation.getCurrentPosition(res, rej, { timeout: 5000 }),
      );
      latitude = pos.coords.latitude;
      longitude = pos.coords.longitude;
      setStatus("");
    } catch {
      setStatus("Геолокация недоступна — используем центр района.");
    }
    const res = await api.nearby(latitude, longitude, category || undefined, limit);
    p.onResults(res.items.map((i) => ({ park: i.park, distance_m: i.distance_m })), {
      latitude,
      longitude,
    });
  };
  return (
    <div className="form">
      <h2>Что рядом со мной</h2>
      <label>Категория
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">Все объекты</option>
          <option value="park">Парки</option>
          <option value="garden">Сады</option>
          <option value="square">Скверы</option>
          <option value="boulevard">Бульвары и аллеи</option>
        </select>
      </label>
      <label>Показать объектов
        <input type="number" min={1} max={50} value={limit}
          onChange={(e) => setLimit(Number(e.target.value) || 10)} />
      </label>
      <button onClick={run}>Найти</button>
      {status && <p className="muted">{status}</p>}
      <ResultList results={p.results} onSelect={p.onSelect} />
    </div>
  );
}

function RadiusForm(p: {
  onResults: Props["onResults"];
  results: Props["results"];
  onSelect: (id: number) => void;
}) {
  const [latitude, setLat] = useState(59.956);
  const [longitude, setLon] = useState(30.306);
  const [radiusM, setRadius] = useState(1000);
  const [res, setRes] = useState<RadiusResponse | null>(null);
  const run = async () => {
    const r = await api.radius(latitude, longitude, radiusM, undefined, 50);
    setRes(r);
    p.onResults(r.items.map((i) => ({ park: i.park, distance_m: i.distance_m })), {
      latitude,
      longitude,
    });
  };
  return (
    <div className="form">
      <h2>Объекты в радиусе</h2>
      <label>Широта
        <input type="number" step="0.0001" value={latitude} onChange={(e) => setLat(Number(e.target.value))} />
      </label>
      <label>Долгота
        <input type="number" step="0.0001" value={longitude} onChange={(e) => setLon(Number(e.target.value))} />
      </label>
      <label>Радиус, м
        <input type="number" min={10} max={20000} value={radiusM} onChange={(e) => setRadius(Number(e.target.value) || 1000)} />
      </label>
      <button onClick={run}>Показать</button>
      {res && <p className="muted">Найдено объектов: {res.count} (радиус {res.radius_m} м)</p>}
      {res && (res.by_category ?? []).length > 0 && (
        <p className="muted">
          {(res.by_category ?? []).map((g) => `${g.category}: ${g.count}`).join(" · ")}
        </p>
      )}
      <ResultList results={p.results} onSelect={p.onSelect} />
    </div>
  );
}

function NearestForm(p: { onSelect: (id: number) => void; categories: CategoriesResponse | null }) {
  const [latitude, setLat] = useState(59.956);
  const [longitude, setLon] = useState(30.306);
  const [category, setCategory] = useState("");
  const [res, setRes] = useState<NearestDistanceResponse | null>(null);
  const run = async () => {
    const r = await api.nearestDistance(latitude, longitude, category || undefined);
    setRes(r);
    p.onSelect(r.nearest_park.id);
  };
  return (
    <div className="form">
      <h2>Ближайший объект</h2>
      <label>Широта
        <input type="number" step="0.0001" value={latitude} onChange={(e) => setLat(Number(e.target.value))} />
      </label>
      <label>Долгота
        <input type="number" step="0.0001" value={longitude} onChange={(e) => setLon(Number(e.target.value))} />
      </label>
      <label>Категория
        <select value={category} onChange={(e) => setCategory(e.target.value)}>
          <option value="">Любая</option>
          {(p.categories?.categories ?? []).map((c) => (
            <option key={c.code} value={c.code}>{c.label}</option>
          ))}
        </select>
      </label>
      <button onClick={run}>Рассчитать</button>
      {res && (
        <table className="kv">
          <tbody>
            <tr><td>Объект</td><td>{res.nearest_park.name}</td></tr>
            <tr><td>Расстояние</td><td>{fmt(res.distance_m)}</td></tr>
            <tr><td>Пешком</td><td>≈ {res.walking_minutes} мин</td></tr>
          </tbody>
        </table>
      )}
    </div>
  );
}

function DistanceForm() {
  const [parks, setParks] = useState<Park[]>([]);
  const [fromId, setFrom] = useState<number | "">("");
  const [toId, setTo] = useState<number | "">("");
  const [res, setRes] = useState<DistanceResponse | null>(null);

  useEffect(() => {
    api.search("", 1).catch(() => undefined);
    fetch("/api/parks?limit=200")
      .then((r) => r.json())
      .then((j) => setParks(j.items || []))
      .catch(() => undefined);
  }, []);

  const run = async () => {
    if (fromId === "" || toId === "") return;
    setRes(await api.distance(Number(fromId), Number(toId)));
  };

  return (
    <div className="form">
      <h2>Расстояние между объектами</h2>
      <label>Объект A
        <select value={fromId} onChange={(e) => setFrom(e.target.value === "" ? "" : Number(e.target.value))}>
          <option value="">— выберите —</option>
          {parks.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
        </select>
      </label>
      <label>Объект B
        <select value={toId} onChange={(e) => setTo(e.target.value === "" ? "" : Number(e.target.value))}>
          <option value="">— выберите —</option>
          {parks.map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
        </select>
      </label>
      <button onClick={run}>Рассчитать</button>
      {res && (
        <table className="kv">
          <tbody>
            <tr><td>Расстояние</td><td>{fmt(res.distance_m)}</td></tr>
            <tr><td>В километрах</td><td>{res.distance_km} км</td></tr>
          </tbody>
        </table>
      )}
    </div>
  );
}

function StatsCard({ s, categories }: { s: Statistics; categories: CategoriesResponse | null }) {
  return (
    <>
      <h2>Статистика по району</h2>
      <table className="kv">
        <tbody>
          <tr><td>Парков, садов и скверов</td><td><b>{s.parks_total}</b></td></tr>
          <tr><td>Общая площадь</td><td>{(s.area_total_sqm / 10000).toFixed(1)} га</td></tr>
          <tr><td>Точек интереса</td><td><b>{s.poi_total}</b></td></tr>
          <tr><td>Дорог и тропинок</td><td><b>{s.roads_total}</b></td></tr>
          <tr><td>Общая длина дорог</td><td>{(s.roads_length_m / 1000).toFixed(2)} км</td></tr>
          <tr><td>Входов и выходов</td><td><b>{s.exits_total}</b></td></tr>
          <tr><td>Среднее расстояние до соседа</td><td>{fmt(s.avg_nearest_neighbor_m)}</td></tr>
        </tbody>
      </table>

      <h3>По категориям</h3>
      <ul className="list">
        {s.by_category.map((c) => (
          <li key={c.category}>
            {categories?.categories.find((x) => x.code === c.category)?.label || c.category}
            : <b>{c.count}</b> · {(c.area_sum_sqm / 10000).toFixed(1)} га
          </li>
        ))}
      </ul>

      <h3>Точки интереса по типам</h3>
      <ul className="list">
        {s.poi_by_type.map((t) => {
          const meta = categories?.poi_types.find((x) => x.code === t.poi_type);
          return (
            <li key={t.poi_type}>
              <span className="poi-badge sm" style={{ background: meta?.color || "#607d8b" }}>{meta?.icon || "•"}</span>{" "}
              {meta?.label || t.poi_type}: <b>{t.count}</b>
            </li>
          );
        })}
      </ul>

      {s.coverage && (
        <>
          <h3>Покрытие района</h3>
          <ul className="list">
            <li>Шаг сетки: {s.coverage.step_m} м</li>
            <li>Объектов в {s.coverage.distance_m} м: <b>{s.coverage.covered_pct}%</b> клеток</li>
            <li>Среднее расстояние: {fmt(s.coverage.avg_distance_m)}</li>
            <li>Максимальное расстояние: {fmt(s.coverage.max_distance_m)}</li>
          </ul>
        </>
      )}

      {s.densest_zones.length > 0 && (
        <>
          <h3>Самые насыщенные зоны</h3>
          <ul className="list">
            {s.densest_zones.slice(0, 5).map((z, i) => (
              <li key={i}>
                {i + 1}. {z.count} объектов около {z.center_lat.toFixed(4)}, {z.center_lon.toFixed(4)}
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}

function QueryForm(p: {
  scenarios: Scenario[];
  onResults: Props["onResults"];
  onSelect: (id: number) => void;
}) {
  const [text, setText] = useState("");
  const [res, setRes] = useState<QueryResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const run = async (value?: string) => {
    const query = (value ?? text).trim();
    if (query.length < 2) return;
    setBusy(true);
    setErr(null);
    try {
      const r = await api.query(query);
      setRes(r);
      p.onResults(r.results.map((i) => ({ park: i.park, distance_m: i.distance_m })));
    } catch (e: any) {
      setRes(null);
      setErr(e?.message || "Не удалось выполнить запрос");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="form">
      <h2>Поиск по запросу:</h2>
      <textarea
        rows={3}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="Например: покажи скверы в радиусе 1 км от Чкаловского проспекта"
      />
      <button onClick={() => run()} disabled={busy}>
        {busy ? "Выполняю…" : "Выполнить"}
      </button>
      {err && <div className="error">{err}</div>}

      {p.scenarios.length > 0 && (
        <>
          <h3>Подсказки запросов</h3>
          <div className="hints">
            {p.scenarios.map((s) => (
              <button
                key={s.id}
                className="hint"
                title={s.title}
                onClick={() => {
                  setText(s.text);
                  run(s.text);
                }}
              >
                {s.text}
              </button>
            ))}
          </div>
        </>
      )}

      {res && (
        <div className="query-result">
          <p className="muted">
            Источник: {res.source === "llm" ? "🤖 нейросеть" : res.source === "cached" ? "💾 кэш" : "⚙️ правила"}
            {" · "}режим: {res.mode === "ai_search" ? "AI-поиск" : "GIS-поиск"}
          </p>
          <p>
            <b>Понято так:</b> {res.structured.intent}
            {res.structured.category ? `, категория: ${res.structured.category}` : ""}
            {res.structured.poi_type ? `, тип POI: ${res.structured.poi_type}` : ""}
            {res.structured.location?.name ? `, от: ${res.structured.location.name}` : ""}
            {res.radius_m ? `, радиус ${Math.round(res.radius_m)} м` : ""}
          </p>
          {res.center && (res.center as any).name && (
            <p className="muted">Точка отсчёта: {(res.center as any).name}</p>
          )}
          {res.warnings.length > 0 && (
            <p className="muted">⚠ {res.warnings.join("; ")}</p>
          )}
          {res.poi.length > 0 && (
            <>
              <h3>Найденные точки интереса ({res.poi.length})</h3>
              <ul className="list">
                {res.poi.slice(0, 15).map((x) => (
                  <li key={x.id}>
                    <span className="poi-badge sm" style={{ background: x.color || "#607d8b" }}>{x.icon || "•"}</span>{" "}
                    {x.name || x.poi_type_label}
                    <span className="muted"> · {(x as any).park_name ?? ""}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
      <ResultList
        results={res ? res.results.map((i) => ({ park: i.park, distance_m: i.distance_m })) : []}
        onSelect={p.onSelect}
      />
    </div>
  );
}

function RecommendForm(p: {
  onResults: Props["onResults"];
  onSelect: (id: number) => void;
}) {
  const [query, setQuery] = useState("");
  const [useGeo, setUseGeo] = useState(true);
  const [radius, setRadius] = useState(3000);
  const [limit, setLimit] = useState(5);
  const [res, setRes] = useState<RecommendResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const run = async () => {
    if (query.trim().length < 2) return;
    setBusy(true);
    setErr(null);
    let latitude: number | undefined;
    let longitude: number | undefined;
    if (useGeo) {
      try {
        const pos = await new Promise<GeolocationPosition>((res2, rej) =>
          navigator.geolocation.getCurrentPosition(res2, rej, { timeout: 4000 }),
        );
        latitude = pos.coords.latitude;
        longitude = pos.coords.longitude;
      } catch {
        /* без координат — чисто семантическая выдача */
      }
    }
    try {
      const r = await api.recommend(query.trim(), {
        latitude,
        longitude,
        radius_meters: radius,
        limit,
      });
      setRes(r);
      p.onResults(
        r.results.map((i) => ({ park: i.park, distance_m: i.distance_m })),
      );
    } catch (e: any) {
      setErr(e?.message || "Не удалось построить рекомендации");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="form">
      <h2>Рекомендации по смыслу</h2>
      <label>Что вы хотите найти?
        <textarea
          rows={2}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Тихое место с детской площадкой и кофейней"
        />
      </label>
      <label className="row">
        <input type="checkbox" checked={useGeo} onChange={(e) => setUseGeo(e.target.checked)} />
        Учитывать моё местоположение
      </label>
      <label>Радиус поиска, м
        <input type="number" min={100} max={20000} value={radius} onChange={(e) => setRadius(Number(e.target.value) || 3000)} />
      </label>
      <label>Сколько вариантов
        <input type="number" min={1} max={20} value={limit} onChange={(e) => setLimit(Number(e.target.value) || 5)} />
      </label>
      <button onClick={run} disabled={busy}>
        {busy ? "Подбираю…" : "Подобрать"}
      </button>
      {err && <div className="error">{err}</div>}

      {res && (
        <div className="query-result">
          <p className="muted">
            Веса рейтинга: смысл {Math.round((res.weights.semantic ?? 0) * 100)}% ·
            близость {Math.round((res.weights.spatial ?? 0) * 100)}% ·
            категория {Math.round((res.weights.category ?? 0) * 100)}%
          </p>
          <ol className="list rec-list">
            {res.results.map((r) => (
              <li key={r.park.id}>
                <button className="link" onClick={() => p.onSelect(r.park.id)}>
                  {r.park.name}
                </button>{" "}
                <span className="muted">
                  ({r.park.category_label}{r.distance_m != null ? `, ${fmt(r.distance_m)}` : ""})
                </span>
                <div className="explain">
                  <span className="chip">итог {Math.round(r.score * 100)}%</span>
                  <span className="chip">смысл {Math.round((r.semantic_score ?? 0) * 100)}%</span>
                  {r.spatial_score != null && (
                    <span className="chip">близость {Math.round(r.spatial_score * 100)}%</span>
                  )}
                  {r.category_score != null && (
                    <span className="chip">категория {Math.round(r.category_score * 100)}%</span>
                  )}
                </div>
                <div className="muted">💡 {r.reason}</div>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
}
