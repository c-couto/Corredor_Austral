"""Una recolección completa: consulta las fuentes y guarda las filas en los CSV."""

from __future__ import annotations

from typing import Callable

from . import config, storage
from .sources import open_meteo


def collect_once(
    weather_fn: Callable = open_meteo.fetch_weather,
    marine_fn: Callable = open_meteo.fetch_marine,
) -> tuple[int, int]:
    """1 consulta de clima + 1 de oleaje. Si una falla, se anota y se sigue.

    Devuelve (lugares con clima, lugares con oleaje).
    """
    ts = storage.now_utc()  # todas las filas de esta corrida llevan la misma hora

    try:
        weather = weather_fn(config.PLACES)
    except Exception as e:
        storage.log_error("weather", e)
        weather = {}
    storage.append_rows(storage.WEATHER, (
        {"ts_utc": ts, "place": place, **w, "source": "open-meteo"} for place, w in weather.items()
    ))

    try:
        marine = marine_fn({p: config.PLACES[p] for p in config.MARINE_PLACES})
    except Exception as e:
        storage.log_error("marine", e)
        marine = {}
    storage.append_rows(storage.MARINE, (
        {"ts_utc": ts, "place": place, **m, "source": "open-meteo-marine"} for place, m in marine.items()
    ))

    return len(weather), len(marine)
