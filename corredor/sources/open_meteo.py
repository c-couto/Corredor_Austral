"""Open-Meteo: clima y oleaje (gratis, sin API key, solo uso NO comercial).

Pide todos los lugares en UNA sola consulta (coordenadas separadas por coma).
"""

from __future__ import annotations

from typing import Any, Mapping

from .. import net

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
MARINE_URL = "https://marine-api.open-meteo.com/v1/marine"

Places = Mapping[str, "tuple[float, float]"]


def _num(value: Any) -> float | None:
    """Devuelve float o None (la API a veces devuelve null)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


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


def fetch_weather(places: Places) -> dict[str, dict[str, float | None]]:
    """Clima actual + ráfaga máxima pronosticada en las próximas 24 h, por lugar."""
    raw = fetch_many(FORECAST_URL, places, {
        "current": "temperature_2m,wind_speed_10m,wind_gusts_10m,wind_direction_10m,precipitation",
        "hourly": "wind_gusts_10m",
        "forecast_hours": 24,
        "wind_speed_unit": "kmh",
        "timezone": "UTC",
    })
    out = {}
    for place, data in raw.items():
        cur = data.get("current") or {}
        gusts = [g for g in map(_num, (data.get("hourly") or {}).get("wind_gusts_10m", [])) if g is not None]
        out[place] = {
            "temp_c": _num(cur.get("temperature_2m")),
            "wind_kmh": _num(cur.get("wind_speed_10m")),
            "gust_kmh": _num(cur.get("wind_gusts_10m")),
            "wind_dir_deg": _num(cur.get("wind_direction_10m")),
            "precip_mm": _num(cur.get("precipitation")),
            "forecast_gust_max_24h_kmh": max(gusts) if gusts else None,
        }
    return out


def fetch_marine(places: Places) -> dict[str, dict[str, float | None]]:
    """Oleaje actual por lugar."""
    raw = fetch_many(MARINE_URL, places, {
        "current": "wave_height,wave_period,wave_direction",
        "timezone": "UTC",
    })
    out = {}
    for place, data in raw.items():
        cur = data.get("current") or {}
        out[place] = {
            "wave_height_m": _num(cur.get("wave_height")),
            "wave_period_s": _num(cur.get("wave_period")),
            "wave_dir_deg": _num(cur.get("wave_direction")),
        }
    return out
