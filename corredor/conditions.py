"""Situación de cada cruce, calculada a partir de los CSV, el pronóstico y el modelo.

Es la ÚNICA fuente de verdad para la web, Telegram y WhatsApp: todos muestran
lo que devuelve `snapshot()`.

  - Estado oficial: lo último que publicó TABSA (si es reciente).
  - Probabilidad de que el cruce no esté normal: modelo aprendido (o regla base).
  - Pronóstico hora por hora (48 h) con esa probabilidad.
  - Historial: períodos no normales, con su duración.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from . import config, forecast, model, storage
from .sources import num
from .timeutil import fmt_local, local_to_utc, parse_ts, to_local

LEVEL_EMOJI = {"bajo": "🟢", "medio": "🟡", "alto": "🔴", None: "⚪"}
OFFICIAL_EMOJI = {True: "🟢", False: "🔴", None: "⚪"}


def is_normal(status: str | None) -> bool | None:
    return None if not status else status.strip().upper() == "NORMAL"


@dataclass
class HourRisk:
    t: datetime
    p: float
    gust: float | None


@dataclass
class Episode:
    """Un período en que un cruce no estuvo normal, según TABSA."""
    subject: str
    name: str
    status: str
    start: datetime
    end: datetime | None  # None = sigue así

    def duration(self, now: datetime) -> timedelta:
        return (self.end or now) - self.start


@dataclass
class SailingView:
    departure_utc: datetime
    date: str
    departure: str
    origin: str
    destination: str
    status: str
    p: float | None  # probabilidad estimada para la hora de salida


@dataclass
class RouteStatus:
    key: str
    name: str
    detail: str
    model: model.RouteModel
    ts: datetime | None = None              # hora del último dato de clima
    gust_kmh: float | None = None
    wind_kmh: float | None = None
    wind_dir_deg: float | None = None
    forecast_gust_kmh: float | None = None  # ráfaga máxima pronosticada, próximas 24 h
    wave_m: float | None = None
    p_now: float | None = None
    hours: list[HourRisk] = field(default_factory=list)                 # próximas 48 h
    history: list[tuple[datetime, float]] = field(default_factory=list)  # (hora, ráfaga) 24 h
    official: str | None = None
    official_ts: datetime | None = None
    official_fresh: bool = False

    @property
    def level(self) -> str | None:
        return model.level_for_prob(self.p_now)

    def peak(self, hours: int = 24) -> HourRisk | None:
        window = self.hours[:hours]
        return max(window, key=lambda h: h.p) if window else None

    @property
    def forecast_level(self) -> str | None:
        pk = self.peak()
        return model.level_for_prob(pk.p) if pk else model.level_for_prob(
            self.model.predict(self.forecast_gust_kmh))


@dataclass
class Snapshot:
    routes: list[RouteStatus]
    places: dict[str, dict]                  # último dato de clima por lugar
    latest: datetime | None                  # última corrida con clima
    tabsa_latest: datetime | None            # última lectura de TABSA
    sailings: list[SailingView]              # próximas salidas Punta Arenas ↔ Porvenir
    episodes: list[Episode]                  # períodos no normales, más recientes primero
    heat: dict[tuple[int, int], list[int]]   # (día semana, hora local) -> [muestras, no normales]
    tabsa_days: int
    tabsa_samples: int
    forecast_source: str | None
    now: datetime

    def is_stale(self, now: datetime | None = None) -> bool:
        if self.latest is None:
            return True
        return (now or self.now) - self.latest > timedelta(hours=config.STALE_AFTER_H)

    def route(self, key: str) -> RouteStatus | None:
        return next((r for r in self.routes if r.key == key), None)

    def next_sailing(self) -> SailingView | None:
        """Próxima salida programada que todavía no zarpó."""
        return next((s for s in self.sailings if s.departure_utc >= self.now), None)

    def official_for(self, st: RouteStatus) -> tuple[str | None, str]:
        """(estado oficial, texto) del cruce; para cruces con horario, el de la próxima salida."""
        if config.ROUTES[st.key].get("scheduled"):
            nxt = self.next_sailing()
            if nxt and self.tabsa_latest and self.now - self.tabsa_latest <= timedelta(hours=config.STALE_AFTER_H):
                return nxt.status, f"Próxima salida {nxt.departure} {nxt.origin} → {nxt.destination}: {nxt.status}"
            return None, "Sin salidas programadas recientes"
        if st.official and st.official_fresh:
            return st.official, f"TABSA: {st.official}"
        return None, "TABSA: sin dato reciente"


# ------------------------------------------------------------------ armado

def group_runs(rows: list[dict]) -> list[tuple[str, dict[str, dict]]]:
    """Agrupa filas por corrida, en orden: [(ts, {lugar: fila}), ...]."""
    runs: dict[str, dict[str, dict]] = {}
    for r in rows:
        runs.setdefault(r["ts_utc"], {})[r["place"]] = r
    return sorted(runs.items(), key=lambda kv: kv[0])


def _max(values) -> float | None:
    values = [v for v in values if v is not None]
    return max(values) if values else None


def route_probability_at(key: str, by_place: dict[str, dict], route_model: model.RouteModel) -> float | None:
    x = model.route_vector(by_place, config.ROUTES[key]["places"])
    return None if x is None else route_model.predict_vector(x)


def _hourly(key: str, fc: dict | None, route_model: model.RouteModel, now: datetime) -> list[HourRisk]:
    if not fc:
        return []
    places = [fc["places"].get(p) or [] for p in config.ROUTES[key]["places"]]
    by_time: dict[str, list[dict]] = defaultdict(list)
    for series in places:
        for h in series:
            by_time[h["t"]].append(h)
    out = []
    for t_str in sorted(by_time):
        t = parse_ts(t_str)
        if t < now - timedelta(minutes=59):
            continue
        hs = by_time[t_str]
        gust = _max(num(h.get("gust")) for h in hs)
        if gust is None:
            continue
        p = route_model.predict(gust, _max(num(h.get("wind")) for h in hs), num(hs[0].get("dir")))
        out.append(HourRisk(t, p, gust))
    return out[:48]


def _episodes(state_rows: list[dict], names: dict[str, str]) -> list[Episode]:
    """Períodos no normales por cruce, a partir de las muestras de TABSA."""
    episodes: list[Episode] = []
    open_: dict[str, Episode] = {}
    for r in state_rows:
        key, status, ts = r["crossing"], r["status"], parse_ts(r["ts_utc"])
        normal = is_normal(status)
        current = open_.get(key)
        if normal is False and current is None:
            open_[key] = Episode(key, names.get(key, key), status, ts, None)
        elif normal and current is not None:
            current.end = ts
            episodes.append(current)
            del open_[key]
    episodes.extend(open_.values())
    return sorted(episodes, key=lambda e: e.start, reverse=True)


def snapshot(now: datetime | None = None, fetch_forecast: bool = True) -> Snapshot:
    now = now or datetime.now(timezone.utc)
    models = model.load()
    weather_runs = group_runs(storage.read_rows(storage.WEATHER))
    marine_by_ts = dict(group_runs(storage.read_rows(storage.MARINE)))
    state_rows = storage.read_rows(storage.TABSA_STATE)
    fc = forecast.load(now=now, refresh=fetch_forecast)

    last_official: dict[str, dict] = {}
    for r in state_rows:
        last_official[r["crossing"]] = r

    routes = []
    for key, cfg in config.ROUTES.items():
        st = RouteStatus(key=key, name=cfg["name"], detail=cfg["detail"], model=models[key])
        places = cfg["places"]
        runs = [(ts, bp) for ts, bp in weather_runs if any(p in bp for p in places)]
        if runs:
            ts, bp = runs[-1]
            rows = [bp[p] for p in places if p in bp]
            st.ts = parse_ts(ts)
            st.gust_kmh = _max(num(r["gust_kmh"]) for r in rows)
            st.wind_kmh = _max(num(r["wind_kmh"]) for r in rows)
            st.wind_dir_deg = num(rows[0]["wind_dir_deg"])
            st.forecast_gust_kmh = _max(num(r["forecast_gust_max_24h_kmh"]) for r in rows)
            marine = marine_by_ts.get(ts, {})
            st.wave_m = _max(num(marine[p]["wave_height_m"]) for p in places if p in marine)
            st.p_now = route_probability_at(key, bp, st.model)
            since = st.ts - timedelta(hours=24)
            for h_ts, h_bp in runs:
                dt = parse_ts(h_ts)
                gust = _max(num(h_bp[p]["gust_kmh"]) for p in places if p in h_bp)
                if dt >= since and gust is not None:
                    st.history.append((dt, gust))
        st.hours = _hourly(key, fc, st.model, now)
        off = last_official.get(cfg.get("tabsa") or "")
        if off:
            st.official, st.official_ts = off["status"], parse_ts(off["ts_utc"])
            st.official_fresh = now - st.official_ts <= timedelta(hours=config.STALE_AFTER_H)
        routes.append(st)

    # Próximas salidas programadas (última lectura de TABSA).
    sailing_rows = storage.read_rows(storage.TABSA_SAILINGS)
    sailings: list[SailingView] = []
    if sailing_rows:
        last_ts = sailing_rows[-1]["ts_utc"]
        pap = next((r for r in routes if r.key == "punta_arenas_porvenir"), None)
        for r in (r for r in sailing_rows if r["ts_utc"] == last_ts):
            dep = local_to_utc(r["date"], r["departure"])
            if dep < now - timedelta(hours=1):
                continue
            p = None
            if pap and pap.hours:
                nearest = min(pap.hours, key=lambda h: abs(h.t - dep))
                if abs(nearest.t - dep) <= timedelta(hours=1):
                    p = nearest.p
            sailings.append(SailingView(dep, r["date"], r["departure"], r["origin"], r["destination"],
                                        r["status"], p))
        sailings.sort(key=lambda s: s.departure_utc)

    # Historial: episodios y mapa de calor (Primera Angostura, el cruce principal).
    names = {cfg.get("tabsa"): cfg["name"] for cfg in config.ROUTES.values() if cfg.get("tabsa")}
    heat: dict[tuple[int, int], list[int]] = defaultdict(lambda: [0, 0])
    days = set()
    for r in state_rows:
        if r["crossing"] != "primera_angostura" or not r["status"]:
            continue
        local = to_local(parse_ts(r["ts_utc"]))
        days.add(local.date())
        cell = heat[(local.weekday(), local.hour)]
        cell[0] += 1
        cell[1] += 0 if is_normal(r["status"]) else 1

    places: dict[str, dict] = {}
    for _, by_place in weather_runs:
        places.update(by_place)

    return Snapshot(
        routes=routes,
        places=places,
        latest=parse_ts(weather_runs[-1][0]) if weather_runs else None,
        tabsa_latest=parse_ts(state_rows[-1]["ts_utc"]) if state_rows else None,
        sailings=sailings,
        episodes=_episodes(state_rows, names),
        heat=dict(heat),
        tabsa_days=len(days),
        tabsa_samples=sum(c[0] for c in heat.values()),
        forecast_source=(fc or {}).get("source"),
        now=now,
    )


# ------------------------------------------------------------------ textos

def pct(p: float | None) -> str:
    return "s/d" if p is None else f"{round(p * 100):.0f} %"


def fmt_duration(d: timedelta) -> str:
    minutes = int(d.total_seconds() // 60)
    h, m = divmod(minutes, 60)
    return f"{h} h {m:02d} min" if h else f"{m} min"


def summary_text(snap: Snapshot) -> str:
    """Resumen corto para Telegram y WhatsApp."""
    head = "Corredor Austral (BETA)"
    if snap.latest:
        head += f" · {fmt_local(snap.latest)} (UTC-3)"
    lines = [head, ""]
    for r in snap.routes:
        status, off = snap.official_for(r)
        emoji = OFFICIAL_EMOJI[is_normal(status)] if status else LEVEL_EMOJI[r.level]
        lines.append(f"{emoji} {r.name} · {off}")
        detail = f"   Ráfagas {r.gust_kmh:.0f} km/h · riesgo {r.level or 's/d'} ({pct(r.p_now)})" \
            if r.gust_kmh is not None else "   Sin datos de viento"
        lines.append(detail)
        pk = r.peak()
        if pk:
            lines.append(f"   Próximas 24 h: pico {pct(pk.p)} a las {fmt_local(pk.t, '%H:%M')}")
    if snap.is_stale():
        lines += ["", "⚠️ Datos desactualizados."]
    lines += ["", "El riesgo es una estimación. Estado oficial:", config.OFFICIAL_URL]
    if config.SITE_URL:
        lines.append(f"Más info: {config.SITE_URL}")
    return "\n".join(lines)
