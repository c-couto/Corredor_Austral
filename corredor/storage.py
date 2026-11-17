"""Almacenamiento en CSV.

Cada tabla es un archivo `data/<carpeta>/<tabla>.csv`:
  - data/auto/    lo escribe SOLO el recolector automático (el workflow).
  - data/manual/  lo escribís SOLO vos (comandos status / event / crossing).
Como nunca escriben el mismo archivo, git no da conflictos.

Reglas: siempre se AGREGAN filas al final (nunca se borra ni se reescribe),
horas en UTC, UTF-8 y saltos de línea LF.
"""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from . import config


@dataclass(frozen=True)
class Table:
    name: str
    folder: str  # "auto" o "manual"
    columns: tuple[str, ...]

    @property
    def path(self) -> Path:
        return config.DATA_DIR / self.folder / f"{self.name}.csv"


WEATHER = Table("weather_obs", "auto", (
    "ts_utc", "place", "temp_c", "wind_kmh", "gust_kmh", "wind_dir_deg",
    "precip_mm", "forecast_gust_max_24h_kmh", "source",
))
MARINE = Table("marine_obs", "auto", (
    "ts_utc", "place", "wave_height_m", "wave_period_s", "wave_dir_deg", "source",
))
ERRORS = Table("collector_errors", "auto", ("ts_utc", "where_", "error"))
# TABSA: estado de cada cruce en cada corrida, cada salida programada, y los cambios de estado.
TABSA_STATE = Table("tabsa_estado", "auto", ("ts_utc", "crossing", "status", "icon"))
TABSA_SAILINGS = Table("tabsa_programados", "auto", (
    "ts_utc", "date", "origin", "destination", "boarding", "departure", "status", "icon",
))
TABSA_CHANGES = Table("tabsa_cambios", "auto", ("ts_utc", "subject", "previous", "current"))
STATUS = Table("status_obs", "manual", ("ts_utc", "subject", "status", "note", "source"))
EVENTS = Table("events", "manual", ("ts_utc", "mode", "place", "kind", "note"))
CROSSINGS = Table("crossings", "manual", ("ts_utc", "route", "delay_minutes", "note"))

TABLES: dict[str, Table] = {t.name: t for t in (
    WEATHER, MARINE, ERRORS, TABSA_STATE, TABSA_SAILINGS, TABSA_CHANGES, STATUS, EVENTS, CROSSINGS,
)}


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt(value: Any) -> str:
    """Cómo se escribe cada valor en el CSV: vacío si no hay dato."""
    return "" if value is None else str(value)


def _ends_without_newline(path: Path) -> bool:
    with path.open("rb") as f:
        f.seek(-1, 2)
        return f.read(1) != b"\n"


def append_rows(table: Table, rows: Iterable[Mapping[str, Any]]) -> int:
    """Agrega filas al final del CSV (crea el archivo con encabezado si no existe).

    Devuelve cuántas filas agregó.
    """
    rows = list(rows)
    if not rows:
        return 0
    path = table.path
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists() or path.stat().st_size == 0
    # Si alguien editó el archivo y quedó sin salto de línea al final, lo agregamos
    # para que la fila nueva no se pegue a la anterior.
    needs_newline = not is_new and _ends_without_newline(path)
    with path.open("a", newline="", encoding="utf-8") as f:
        if needs_newline:
            f.write("\n")
        writer = csv.writer(f, lineterminator="\n")
        if is_new:
            writer.writerow(table.columns)
        writer.writerows([fmt(r.get(c)) for c in table.columns] for r in rows)
    return len(rows)


def read_rows(table: Table) -> list[dict[str, str]]:
    """Devuelve las filas del CSV como diccionarios (lista vacía si no existe)."""
    path = table.path
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def log_error(where: str, err: BaseException) -> None:
    """Anota una falla en collector_errors.csv y la muestra por consola."""
    append_rows(ERRORS, [{"ts_utc": now_utc(), "where_": where, "error": str(err)[:500]}])
    print(f"[error] {where}: {err}", file=sys.stderr)
