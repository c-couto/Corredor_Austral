"""Una recolección completa: consulta las fuentes y guarda las filas en los CSV.

Cada fuente es independiente: si una falla, se anota en collector_errors.csv
y las demás se guardan igual.
"""

from __future__ import annotations

from typing import Callable, NamedTuple

from . import config, forecast, storage
from .sources import tabsa, weather_source


class CollectResult(NamedTuple):
    weather: int          # lugares con clima
    marine: int           # lugares con oleaje
    tabsa_crossings: int  # cruces con estado oficial
    tabsa_sailings: int   # salidas programadas leídas
    tabsa_changes: int    # cambios de estado detectados
    forecast_rows: int = 0  # filas de pronóstico guardadas (data/auto/pronosticos/)


def sailing_subject(row: dict) -> str:
    return f"{row['date']} {row['departure']} {row['origin']} -> {row['destination']}"


def _last_status(table: storage.Table, key) -> dict[str, str]:
    last: dict[str, str] = {}
    for r in storage.read_rows(table):  # en orden de llegada: queda el último
        last[key(r)] = r["status"]
    return last


def save_tabsa(ts: str, page: tabsa.TabsaPage) -> int:
    """Guarda la muestra de TABSA y los cambios de estado. Devuelve cuántos cambios hubo."""
    prev_cross = _last_status(storage.TABSA_STATE, lambda r: r["crossing"])
    prev_sail = _last_status(storage.TABSA_SAILINGS, sailing_subject)

    storage.append_rows(storage.TABSA_STATE, (
        {"ts_utc": ts, "crossing": c.key, "status": c.status, "icon": c.icon} for c in page.crossings
    ))
    storage.append_rows(storage.TABSA_SAILINGS, (
        {"ts_utc": ts, "date": s.date, "origin": s.origin, "destination": s.destination,
         "boarding": s.boarding, "departure": s.departure, "status": s.status, "icon": s.icon}
        for s in page.sailings
    ))

    changes = []
    for c in page.crossings:
        before = prev_cross.get(c.key)
        if before != c.status:  # también la primera vez que se ve el cruce (previous vacío)
            changes.append({"ts_utc": ts, "subject": c.key, "previous": before or "", "current": c.status})
    for s in page.sailings:
        before = prev_sail.get(s.subject)
        if before is not None and before != s.status:  # salidas nuevas no son un "cambio"
            changes.append({"ts_utc": ts, "subject": s.subject, "previous": before, "current": s.status})
    return storage.append_rows(storage.TABSA_CHANGES, changes)


def collect_once(
    weather_fn: Callable | None = None,
    marine_fn: Callable | None = None,
    tabsa_fn: Callable | None = None,
    source_name: str | None = None,
) -> CollectResult:
    """Clima (+ pronóstico horario), oleaje y estado oficial de TABSA."""
    ts = storage.now_utc()  # todas las filas de esta corrida llevan la misma hora
    default_name, default_weather, default_marine = weather_source()
    if weather_fn is None:
        weather_fn, marine_fn, source_name = default_weather, default_marine, default_name
    source_name = source_name or default_name
    tabsa_fn = tabsa_fn or tabsa.fetch

    try:
        weather = weather_fn(config.PLACES)
    except Exception as e:
        storage.log_error("weather", e)
        weather = {}
    storage.append_rows(storage.WEATHER, (
        {"ts_utc": ts, "place": place, **w, "source": source_name} for place, w in weather.items()
    ))
    if weather:
        try:
            forecast.save(ts, source_name, weather)
        except OSError as e:
            storage.log_error("forecast", e)

    marine = {}
    if marine_fn is not None:
        try:
            marine = marine_fn({p: config.PLACES[p] for p in config.MARINE_PLACES})
        except Exception as e:
            storage.log_error("marine", e)
        storage.append_rows(storage.MARINE, (
            {"ts_utc": ts, "place": place, **m, "source": "open-meteo-marine"} for place, m in marine.items()
        ))

    # Pronóstico de 48 h tal como está AHORA (para evaluar y entrenar sin usar datos del futuro).
    snapshot = 0
    if weather or marine:
        try:
            snapshot = storage.append_rows(storage.FORECAST_SNAPSHOTS,
                                           forecast.snapshot_rows(ts, source_name, weather, marine))
        except Exception as e:
            storage.log_error("pronosticos", e)

    crossings = sailings = changes = 0
    try:
        page = tabsa_fn()
        changes = save_tabsa(ts, page)
        crossings, sailings = len(page.crossings), len(page.sailings)
    except Exception as e:
        storage.log_error("tabsa", e)

    return CollectResult(len(weather), len(marine), crossings, sailings, changes, snapshot)
