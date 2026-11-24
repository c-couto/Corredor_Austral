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
    monthly: bool = False  # True: un archivo por mes, data/<carpeta>/<tabla>/AAAA-MM.csv

    @property
    def path(self) -> Path:
        """Archivo de la tabla (para tablas mensuales: la carpeta que contiene los meses)."""
        if self.monthly:
            return config.DATA_DIR / self.folder / self.name
        return config.DATA_DIR / self.folder / f"{self.name}.csv"

    def month_path(self, month: str) -> Path:
        return self.path / f"{month}.csv"

    def files(self) -> list[Path]:
        if not self.monthly:
            return [self.path] if self.path.exists() else []
        return sorted(self.path.glob("*.csv")) if self.path.exists() else []


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
# Pronóstico TAL COMO ESTABA en cada corrida (48 h por lugar): permite comparar después lo que
# se pronosticó con lo que pasó, sin usar datos del futuro. Un archivo por mes (es la tabla más grande).
FORECAST_SNAPSHOTS = Table("pronosticos", "auto", (
    "issued_utc", "place", "valid_utc", "lead_h", "wind_kmh", "gust_kmh", "wind_dir_deg",
    "wave_height_m", "wave_period_s", "wave_dir_deg", "sea_level_m", "source",
), monthly=True)
STATUS = Table("status_obs", "manual", ("ts_utc", "subject", "status", "note", "source"))
EVENTS = Table("events", "manual", ("ts_utc", "mode", "place", "kind", "note"))
CROSSINGS = Table("crossings", "manual", ("ts_utc", "route", "delay_minutes", "note"))
# Lo que PREDIJIMOS en cada corrida (el mismo cálculo que muestra la web), para medir después
# "cómo nos fue" con anticipación en los 3 cruces. Un archivo por mes.
PREDICTIONS = Table("predicciones", "auto", (
    "emitido_utc", "ruta", "tipo", "valido_utc", "anticipacion_h", "prob", "rafaga_kmh",
    "modelo", "detalle",
), monthly=True)

TABLES: dict[str, Table] = {t.name: t for t in (
    WEATHER, MARINE, ERRORS, TABSA_STATE, TABSA_SAILINGS, TABSA_CHANGES, FORECAST_SNAPSHOTS,
    PREDICTIONS, STATUS, EVENTS, CROSSINGS,
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


def _append_to_file(path: Path, columns: tuple[str, ...], rows: list[Mapping[str, Any]]) -> None:
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
            writer.writerow(columns)
        writer.writerows([fmt(r.get(c)) for c in columns] for r in rows)


def append_rows(table: Table, rows: Iterable[Mapping[str, Any]]) -> int:
    """Agrega filas al final del CSV (crea el archivo con encabezado si no existe).

    En tablas mensuales, cada fila va al archivo del mes de su primera columna (hora UTC).
    Devuelve cuántas filas agregó.
    """
    rows = list(rows)
    if not rows:
        return 0
    if not table.monthly:
        _append_to_file(table.path, table.columns, rows)
        return len(rows)
    by_month: dict[str, list[Mapping[str, Any]]] = {}
    for r in rows:
        by_month.setdefault(str(r[table.columns[0]])[:7], []).append(r)
    for month, month_rows in by_month.items():
        _append_to_file(table.month_path(month), table.columns, month_rows)
    return len(rows)


def read_rows(table: Table) -> list[dict[str, str]]:
    """Devuelve las filas como diccionarios (lista vacía si no hay datos).

    En tablas mensuales junta todos los meses, en orden.
    """
    out: list[dict[str, str]] = []
    for path in table.files():
        with path.open(newline="", encoding="utf-8") as f:
            out.extend(csv.DictReader(f))
    return out


def log_error(where: str, err: BaseException) -> None:
    """Anota una falla en collector_errors.csv y la muestra por consola."""
    append_rows(ERRORS, [{"ts_utc": now_utc(), "where_": where, "error": str(err)[:500]}])
    print(f"[error] {where}: {err}", file=sys.stderr)
