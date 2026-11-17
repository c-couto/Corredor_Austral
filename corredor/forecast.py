"""Pronóstico horario del momento (48 h por lugar).

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


def _path():
    return config.CACHE_DIR / "pronostico.json"


def save(ts_utc: str, source: str, weather: dict[str, dict]) -> None:
    payload = {
        "generated_utc": ts_utc,
        "source": source,
        "places": {place: w.get("hourly") or [] for place, w in weather.items()},
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
            if now - parse_ts(data["generated_utc"]) <= MAX_AGE:
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
