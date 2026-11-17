"""Open-Meteo: clima y oleaje (gratis, sin API key, SOLO uso NO comercial).

Pide todos los lugares en UNA sola consulta (coordenadas separadas por coma).
Devuelve el mismo formato que met_norway.py (ver sources/__init__.py).
"""

from __future__ import annotations

from typing import Any, Mapping

from .. import net
from . import Places, num

NAME = "open-meteo"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"
FORECAST_HOURS = 48


def fetch_many(url: str, places: Places, params: Mapping[str, Any]) -> dict[str, dict]:
    """Una consulta para varios lugares. Devuelve {lugar: respuesta cruda}.

    Open-Meteo devuelve una lista con un resultado por lugar, en el mismo orden.
    """
    names = list(places)
    data = net.get_json(url, {
        "latitude": ",".join(str(places[p][0]) for p in names),
        "longitude": ",".join(str(places[p][1]) for p in names),
        **params,
    })
    if isinstance(data, dict):  # con un solo lugar devuelve un objeto, no una lista
        data = [data]
    if len(data) != len(names):
        raise ValueError(f"se pidieron {len(names)} lugares y llegaron {len(data)}")
    return dict(zip(names, data))


def fetch_weather(places: Places) -> dict[str, dict]:
    """Clima actual + pronóstico horario de 48 h, por lugar."""
    raw = fetch_many(FORECAST_URL, places, {
        "current": "temperature_2m,wind_speed_10m,wind_gusts_10m,wind_direction_10m,precipitation,weather_code,is_day",
        "hourly": "wind_speed_10m,wind_gusts_10m,wind_direction_10m",
        "forecast_hours": FORECAST_HOURS,
        "wind_speed_unit": "kmh",
        "timezone": "UTC",
    })
    out = {}
    for place, data in raw.items():
        cur = data.get("current") or {}
        h = data.get("hourly") or {}
        times = h.get("time") or []
        hourly = [
            {"t": f"{t}:00Z" if len(t) == 16 else t,
             "wind": num(_at(h, "wind_speed_10m", i)),
             "gust": num(_at(h, "wind_gusts_10m", i)),
             "dir": num(_at(h, "wind_direction_10m", i))}
            for i, t in enumerate(times)
        ]
        gusts_24h = [x["gust"] for x in hourly[:24] if x["gust"] is not None]
        if not times:  # respuesta sin horas: compatibilidad con la versión anterior
            gusts_24h = [g for g in map(num, h.get("wind_gusts_10m", [])) if g is not None]
        out[place] = {
            "temp_c": num(cur.get("temperature_2m")),
            "wind_kmh": num(cur.get("wind_speed_10m")),
            "gust_kmh": num(cur.get("wind_gusts_10m")),
            "wind_dir_deg": num(cur.get("wind_direction_10m")),
            "precip_mm": num(cur.get("precipitation")),
            "forecast_gust_max_24h_kmh": max(gusts_24h) if gusts_24h else None,
            "weather_code": num(cur.get("weather_code")),  # código WMO: despejado, lluvia, nieve...
            "is_day": num(cur.get("is_day")),
            "hourly": hourly,
        }
    return out


def _at(hourly: dict, key: str, i: int):
    values = hourly.get(key) or []
    return values[i] if i < len(values) else None


def fetch_marine(places: Places) -> dict[str, dict]:
    """Oleaje actual + pronóstico horario de 48 h de oleaje y nivel del mar (marea), por lugar.

    sea_level_height_msl: nivel del mar sobre el medio (marea + efecto del viento), en metros.
    La grilla marina es gruesa: sirve para la FASE de la marea (sube/baja), no su altura exacta.
    """
    raw = fetch_many(MARINE_URL, places, {
        "current": "wave_height,wave_period,wave_direction",
        "hourly": "wave_height,wave_period,wave_direction,sea_level_height_msl",
        "forecast_hours": FORECAST_HOURS,
        "timezone": "UTC",
    })
    out = {}
    for place, data in raw.items():
        cur = data.get("current") or {}
        h = data.get("hourly") or {}
        out[place] = {
            "wave_height_m": num(cur.get("wave_height")),
            "wave_period_s": num(cur.get("wave_period")),
            "wave_dir_deg": num(cur.get("wave_direction")),
            "hourly": [
                {"t": f"{t}:00Z" if len(t) == 16 else t,
                 "wave_height": num(_at(h, "wave_height", i)),
                 "wave_period": num(_at(h, "wave_period", i)),
                 "wave_dir": num(_at(h, "wave_direction", i)),
                 "sea_level": num(_at(h, "sea_level_height_msl", i))}
                for i, t in enumerate(h.get("time") or [])
            ],
        }
    return out
