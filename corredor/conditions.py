"""Condiciones por cruce, calculadas a partir de los CSV.

Es la única fuente de verdad para la web, Telegram y WhatsApp: todos muestran
lo que devuelve este módulo.

BETA: el "riesgo" sale solo de la ráfaga de viento con umbrales provisorios
(config.GUST_LEVELS). NO es el estado oficial del cruce.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import config, storage

LEVEL_EMOJI = {"bajo": "🟢", "medio": "🟡", "alto": "🔴", None: "⚪"}


def parse_ts(value: str) -> datetime:
    """'2026-11-17T20:29:16Z' -> datetime en UTC (compatible con Python 3.10)."""
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def to_local(dt: datetime) -> datetime:
    return dt.astimezone(timezone(timedelta(hours=config.LOCAL_UTC_OFFSET_H)))


def fmt_local(dt: datetime) -> str:
    return to_local(dt).strftime("%d/%m %H:%M")


def level_for(gust_kmh: float | None) -> str | None:
    if gust_kmh is None:
        return None
    for limit, name in config.GUST_LEVELS:
        if gust_kmh >= limit:
            return name
    return "bajo"


def _num(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def _max(values) -> float | None:
    values = [v for v in values if v is not None]
    return max(values) if values else None


@dataclass
class RouteStatus:
    key: str
    name: str
    detail: str
    ts: datetime | None = None            # hora del último dato
    gust_kmh: float | None = None          # ráfaga actual (la mayor entre los puntos del cruce)
    wind_kmh: float | None = None
    forecast_gust_kmh: float | None = None  # ráfaga máxima pronosticada, próximas 24 h
    wave_m: float | None = None
    history: list[tuple[datetime, float]] = field(default_factory=list)  # (hora, ráfaga)

    @property
    def level(self) -> str | None:
        return level_for(self.gust_kmh)

    @property
    def forecast_level(self) -> str | None:
        return level_for(self.forecast_gust_kmh)


@dataclass
class Snapshot:
    """Todo lo que hace falta para mostrar: un cruce por fila + los demás puntos."""
    routes: list[RouteStatus]
    places: dict[str, dict]           # último dato de clima por lugar
    latest: datetime | None           # hora de la última corrida con datos

    def is_stale(self, now: datetime | None = None) -> bool:
        if self.latest is None:
            return True
        now = now or datetime.now(timezone.utc)
        return now - self.latest > timedelta(hours=config.STALE_AFTER_H)


def group_runs(rows: list[dict]) -> list[tuple[str, dict[str, dict]]]:
    """Agrupa filas por corrida, en orden: [(ts, {lugar: fila}), ...]."""
    runs: dict[str, dict[str, dict]] = {}
    for r in rows:
        runs.setdefault(r["ts_utc"], {})[r["place"]] = r
    return sorted(runs.items(), key=lambda kv: kv[0])


def route_status_at(key: str, runs, marine_by_ts, index: int = -1, history_h: int = 24) -> RouteStatus:
    """Estado de un cruce en la corrida `index` (por defecto, la última)."""
    route = config.ROUTES[key]
    st = RouteStatus(key=key, name=route["name"], detail=route["detail"])
    places = route["places"]
    runs = [(ts, by_place) for ts, by_place in runs if any(p in by_place for p in places)]
    if not runs:
        return st
    pos = index % len(runs)  # -1 -> última, -2 -> anterior, ...
    ts, by_place = runs[pos]
    rows = [by_place[p] for p in places if p in by_place]
    st.ts = parse_ts(ts)
    st.gust_kmh = _max(_num(r["gust_kmh"]) for r in rows)
    st.wind_kmh = _max(_num(r["wind_kmh"]) for r in rows)
    st.forecast_gust_kmh = _max(_num(r["forecast_gust_max_24h_kmh"]) for r in rows)
    marine = marine_by_ts.get(ts, {})
    st.wave_m = _max(_num(marine[p]["wave_height_m"]) for p in places if p in marine)
    since = st.ts - timedelta(hours=history_h)
    for h_ts, h_places in runs[: pos + 1]:
        dt = parse_ts(h_ts)
        gust = _max(_num(h_places[p]["gust_kmh"]) for p in places if p in h_places)
        if dt >= since and gust is not None:
            st.history.append((dt, gust))
    return st


def snapshot() -> Snapshot:
    weather_runs = group_runs(storage.read_rows(storage.WEATHER))
    marine_by_ts = dict(group_runs(storage.read_rows(storage.MARINE)))
    routes = [route_status_at(key, weather_runs, marine_by_ts) for key in config.ROUTES]
    places: dict[str, dict] = {}
    for _, by_place in weather_runs:
        places.update(by_place)
    latest = parse_ts(weather_runs[-1][0]) if weather_runs else None
    return Snapshot(routes=routes, places=places, latest=latest)


def _n(value: float | None, unit: str) -> str:
    return "s/d" if value is None else f"{value:.0f} {unit}"


def summary_text(snap: Snapshot) -> str:
    """Resumen corto para Telegram y WhatsApp."""
    head = "Corredor Austral (BETA)"
    if snap.latest:
        head += f" · {fmt_local(snap.latest)} (UTC-3)"
    lines = [head, ""]
    for r in snap.routes:
        lines.append(f"{LEVEL_EMOJI[r.level]} {r.name}: ráfagas {_n(r.gust_kmh, 'km/h')}"
                     f" · riesgo {r.level or 's/d'}")
        lines.append(f"   Próximas 24 h: hasta {_n(r.forecast_gust_kmh, 'km/h')}"
                     f" ({r.forecast_level or 's/d'})")
    if snap.is_stale():
        lines += ["", "⚠️ Datos desactualizados."]
    lines += ["", "Riesgo estimado solo por viento, NO es el estado oficial.",
              f"Estado oficial: {config.OFFICIAL_URL}"]
    if config.SITE_URL:
        lines.append(f"Más info: {config.SITE_URL}")
    return "\n".join(lines)
