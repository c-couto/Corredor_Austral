"""Pronóstico horario del momento (96 h = 4 días por lugar; en data/ se guardan 48 h).

Es una "foto" que se reemplaza en cada corrida, así que NO se guarda en el repo
(vive en .cache/). Lo usan la web y el planificador. Si falta o es viejo, se
vuelve a pedir a la fuente de clima.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from . import config
from .timeutil import format_ts, parse_ts

MAX_AGE = timedelta(hours=3)
SNAPSHOT_HOURS = 48   # lo que se guarda en data/auto/pronosticos/ (el pronóstico en memoria llega a 96 h)
CURRENT_FIELDS = ("temp_c", "wind_kmh", "gust_kmh", "wind_dir_deg", "precip_mm",
                  "weather_code", "is_day", "symbol")


def _path():
    return config.CACHE_DIR / "pronostico.json"


def snapshot_rows(issued_utc: str, source: str, weather: dict[str, dict],
                  marine: dict[str, dict] | None = None) -> list[dict]:
    """Filas de data/auto/pronosticos/: el pronóstico de 48 h tal como estaba al emitirse.

    Una fila por lugar (config.SNAPSHOT_PLACES) y hora pronosticada, con viento y, si hay,
    oleaje y nivel del mar. lead_h = horas entre la corrida y la hora pronosticada.
    """
    issued = parse_ts(issued_utc)
    rows = []
    for place in config.SNAPSHOT_PLACES:
        wind = {h["t"]: h for h in (weather.get(place) or {}).get("hourly") or []}
        sea = {h["t"]: h for h in ((marine or {}).get(place) or {}).get("hourly") or []}
        for t in sorted(set(wind) | set(sea)):
            if (parse_ts(t) - issued).total_seconds() > SNAPSHOT_HOURS * 3600:
                continue  # el formato y el tamaño de lo guardado no cambian
            w, m = wind.get(t, {}), sea.get(t, {})
            rows.append({
                "issued_utc": issued_utc, "place": place, "valid_utc": t,
                "lead_h": round((parse_ts(t) - issued).total_seconds() / 3600, 2),
                "wind_kmh": w.get("wind"), "gust_kmh": w.get("gust"), "wind_dir_deg": w.get("dir"),
                "wave_height_m": m.get("wave_height"), "wave_period_s": m.get("wave_period"),
                "wave_dir_deg": m.get("wave_dir"), "sea_level_m": m.get("sea_level"),
                "source": source + ("+open-meteo-marine" if m else ""),
            })
    return rows


def save(ts_utc: str, source: str, weather: dict[str, dict]) -> None:
    payload = {
        "generated_utc": ts_utc,
        "source": source,
        "places": {place: w.get("hourly") or [] for place, w in weather.items()},
        # Clima del momento por lugar (para la web: temperatura, viento y estado del cielo).
        "current": {place: {k: w.get(k) for k in CURRENT_FIELDS} for place, w in weather.items()},
    }
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def load(now: datetime | None = None, refresh: bool = True) -> dict | None:
    """Pronóstico guardado si es reciente; si no (y refresh), lo pide de nuevo."""
    now = now or datetime.now(timezone.utc)
    path = _path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            usable = any(data.get("places", {}).values()) and "current" in data  # vacío o formato viejo: no
            if usable and now - parse_ts(data["generated_utc"]) <= MAX_AGE:
                return data
        except (ValueError, KeyError):
            pass
    if not refresh:
        return None
    from .sources import weather_source
    name, fetch_weather, _ = weather_source()
    try:
        weather = fetch_weather(config.PLACES)
    except Exception as e:
        print(f"[aviso] no se pudo obtener el pronóstico: {e}")
        return None
    save(format_ts(now), name, weather)
    return json.loads(path.read_text(encoding="utf-8"))
