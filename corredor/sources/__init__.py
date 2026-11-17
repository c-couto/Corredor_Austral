"""Fuentes de datos externas. Cada módulo consulta una fuente y devuelve diccionarios simples.

Formato común del clima (open_meteo.fetch_weather y met_norway.fetch_weather):
    {lugar: {"temp_c", "wind_kmh", "gust_kmh", "wind_dir_deg", "precip_mm",
             "forecast_gust_max_24h_kmh",
             "hourly": [{"t": "2026-11-17T21:00Z...", "wind", "gust", "dir"}, ...]}}
Viento siempre en km/h, horas en UTC.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping

Places = Mapping[str, "tuple[float, float]"]


def num(value: Any) -> float | None:
    """Devuelve float o None (las APIs a veces devuelven null)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def weather_source() -> tuple[str, Callable, Callable | None]:
    """(nombre, función de clima, función de oleaje o None) según config.WEATHER_SOURCE."""
    from .. import config
    if config.WEATHER_SOURCE == "met_norway":
        from . import met_norway
        # Uso comercial: no se usa Open-Meteo para nada (tampoco el oleaje).
        return met_norway.NAME, met_norway.fetch_weather, None
    from . import open_meteo
    return open_meteo.NAME, open_meteo.fetch_weather, open_meteo.fetch_marine
