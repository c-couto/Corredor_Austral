"""MET Norway (api.met.no, el servicio detrás de yr.no): clima con cobertura mundial.

Gratis y con uso comercial permitido (licencia CC BY 4.0: hay que citar
"Datos: MET Norway"). Condiciones de uso: identificarse con un User-Agent que
incluya un contacto (CORREDOR_MET_CONTACT), coordenadas con hasta 4 decimales
y no más de 20 consultas por segundo. Una consulta por lugar.

Devuelve el mismo formato que open_meteo.fetch_weather.
"""

from __future__ import annotations

from .. import net
from . import Places, num

NAME = "met-norway"
URL = "https://api.met.no/weatherapi/locationforecast/2.0/complete"
MS_TO_KMH = 3.6
FORECAST_HOURS = 96


def _kmh(value) -> float | None:
    v = num(value)
    return None if v is None else round(v * MS_TO_KMH, 1)


def parse(data: dict) -> dict:
    """Respuesta de api.met.no para un lugar -> clima actual + pronóstico horario."""
    series = ((data.get("properties") or {}).get("timeseries")) or []
    if not series:
        raise ValueError("MET Norway: respuesta sin pronóstico")
    hourly = []
    for step in series[:FORECAST_HOURS]:
        inst = ((step.get("data") or {}).get("instant") or {}).get("details") or {}
        hourly.append({
            "t": step.get("time"),
            "wind": _kmh(inst.get("wind_speed")),
            "gust": _kmh(inst.get("wind_speed_of_gust")),
            "dir": num(inst.get("wind_from_direction")),
        })
    first = series[0].get("data") or {}
    now = (first.get("instant") or {}).get("details") or {}
    next_1h = first.get("next_1_hours") or {}
    precip = (next_1h.get("details") or {}).get("precipitation_amount")
    gusts_24h = [h["gust"] for h in hourly[:24] if h["gust"] is not None]
    return {
        "temp_c": num(now.get("air_temperature")),
        "wind_kmh": _kmh(now.get("wind_speed")),
        "gust_kmh": _kmh(now.get("wind_speed_of_gust")),
        "wind_dir_deg": num(now.get("wind_from_direction")),
        "precip_mm": num(precip),
        "forecast_gust_max_24h_kmh": max(gusts_24h) if gusts_24h else None,
        "symbol": (next_1h.get("summary") or {}).get("symbol_code"),  # p. ej. "rain", "clearsky_day"
        "hourly": hourly,
    }


def fetch_weather(places: Places) -> dict[str, dict]:
    out = {}
    for place, (lat, lon) in places.items():
        out[place] = parse(net.get_json(URL, {"lat": round(lat, 4), "lon": round(lon, 4)}))
    return out
