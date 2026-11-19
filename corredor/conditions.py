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
    current_weather: dict[str, dict] = field(default_factory=dict)  # clima del momento por lugar

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
        for r in (r for r in sailing_rows
                  if r["ts_utc"] == last_ts and model.is_route_sailing(r, "punta_arenas_porvenir")):
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
    current_weather = {p: {k: num(v) if k != "symbol" else v for k, v in row.items()}
                       for p, row in ((fc or {}).get("current") or {}).items()}
    for p, row in places.items():  # sin caché: lo último guardado en el CSV
        current_weather.setdefault(p, {k: num(row.get(k)) for k in
                                       ("temp_c", "wind_kmh", "gust_kmh", "wind_dir_deg", "precip_mm")})

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
        current_weather=current_weather,
    )


# ------------------------------------------------------------------ lectura fácil

VERDICT = {
    "bajo": "Se espera cruce normal",
    "medio": "Atención: puede suspenderse",
    "alto": "Probable suspensión",
    None: "Sin datos suficientes",
}


def verdict(snap: "Snapshot", st: RouteStatus) -> tuple[str, str]:
    """(nivel, frase) para mostrar arriba de cada cruce. El estado oficial manda."""
    status, _ = snap.official_for(st)
    if status and is_normal(status) is False:
        return "alto", f"Suspendido según TABSA ({status.lower()})"
    return (st.level or "nd"), VERDICT[st.level]


def closure_windows(st: RouteStatus, min_level: str = "medio",
                    hours: int = 48) -> list[tuple[HourRisk, HourRisk, str]]:
    """Tramos seguidos de horas con nivel >= min_level: [(desde, hasta, peor nivel)]."""
    order = {"bajo": 0, "medio": 1, "alto": 2}
    out: list[tuple[HourRisk, HourRisk, str]] = []
    run: list[HourRisk] = []
    for h in list(st.hours[:hours]) + [None]:
        lvl = model.level_for_prob(h.p) if h else None
        if h and order.get(lvl, -1) >= order[min_level]:
            run.append(h)
            continue
        if run:
            worst = max((model.level_for_prob(x.p) for x in run), key=lambda l: order[l])
            out.append((run[0], run[-1], worst))
            run = []
    return out


def gust_threshold(route_model: model.RouteModel, p: float, dir_deg: float | None = None) -> float | None:
    """Ráfaga (km/h) a partir de la cual el modelo llega a la probabilidad p (búsqueda binaria)."""
    lo, hi = 0.0, 200.0
    if route_model.predict(hi, hi * 0.6, dir_deg) < p:
        return None
    for _ in range(40):
        mid = (lo + hi) / 2
        if route_model.predict(mid, mid * 0.6, dir_deg) >= p:
            hi = mid
        else:
            lo = mid
    return hi


WMO = (  # (códigos, texto, ícono de día, ícono de noche)
    ((0,), "Despejado", "☀️", "🌙"),
    ((1, 2), "Parcialmente nublado", "⛅", "☁️"),
    ((3,), "Nublado", "☁️", "☁️"),
    ((45, 48), "Niebla", "🌫️", "🌫️"),
    ((51, 53, 55, 56, 57), "Llovizna", "🌦️", "🌧️"),
    ((61, 63, 65, 66, 67), "Lluvia", "🌧️", "🌧️"),
    ((71, 73, 75, 77), "Nieve", "🌨️", "🌨️"),
    ((80, 81, 82), "Chaparrones", "🌦️", "🌧️"),
    ((85, 86), "Chaparrones de nieve", "🌨️", "🌨️"),
    ((95, 96, 99), "Tormenta", "⛈️", "⛈️"),
)
MET_SYMBOLS = (("thunder", 95), ("snow", 71), ("sleet", 66), ("rainshowers", 80), ("rain", 61),
               ("fog", 45), ("partlycloudy", 2), ("fair", 1), ("cloudy", 3), ("clearsky", 0))


def describe_weather(w: dict | None) -> tuple[str, str]:
    """(ícono, texto) del estado del cielo; con ráfagas de 60 km/h o más agrega 'muy ventoso'."""
    if not w:
        return "🌡️", "Sin datos"
    code, symbol = w.get("weather_code"), w.get("symbol") or ""
    is_day = w.get("is_day") != 0 and "night" not in symbol
    if code is None and symbol:
        code = next((c for key, c in MET_SYMBOLS if key in symbol), None)
    icon, text = "🌡️", ""
    if code is None and (w.get("precip_mm") or 0) > 0:
        icon, text = "🌧️", "Lluvia"
    for codes, t, day, night in WMO:
        if code is not None and int(code) in codes:
            icon, text = (day if is_day else night), t
    gust = w.get("gust_kmh")
    if gust is not None and gust >= 60:
        icon, text = (icon if text else "💨"), (f"{text}, muy ventoso" if text else "Muy ventoso")
    return icon, text or "Sin datos del cielo"


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
        if r.gust_kmh is not None:
            lines.append(f"   {VERDICT[r.level]} · ráfagas {r.gust_kmh:.0f} km/h · "
                         f"prob. de suspensión {pct(r.p_now)}")
        else:
            lines.append("   Sin datos de viento")
        windows = closure_windows(r, "medio", 24)
        if windows:
            first, last, worst = windows[0]
            what = "probable suspensión" if worst == "alto" else "puede suspenderse"
            lines.append(f"   Próximas 24 h: {what} entre {fmt_local(first.t, '%H:%M')} y "
                         f"{fmt_local(last.t + timedelta(hours=1), '%H:%M')}")
        elif r.hours:
            lines.append("   Próximas 24 h: sin riesgo relevante de suspensión")
    if snap.is_stale():
        lines += ["", "⚠️ Datos desactualizados."]
    lines += ["", "La probabilidad de suspensión es una estimación por viento. Estado oficial:",
              config.OFFICIAL_URL]
    if config.SITE_URL:
        lines.append(f"Más info: {config.SITE_URL}")
    return "\n".join(lines)
