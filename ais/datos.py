"""CSV del mapa en vivo, separados de los datos del modelo.

  data/ais/posiciones/AAAA-MM.csv  una fila por posición (como mucho 1 por barco por minuto)
  data/ais/barcos.csv              datos fijos que manda cada barco (nombre, tipo, señal)
  data/ais/sesiones.csv            cuándo estuvimos escuchando (sin esto no se puede medir la cobertura)

Mismas reglas que el resto del proyecto: solo se AGREGAN filas al final, hora en UTC,
UTF-8 y saltos de línea LF.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable, Mapping

from corredor import config

POSICIONES = ("ts_utc", "mmsi", "nombre", "lat", "lon", "sog_kn", "cog_deg", "rumbo_deg",
              "estado_nav", "tipo_msg", "zona")
BARCOS = ("ts_utc", "mmsi", "nombre", "tipo", "callsign", "imo", "destino")
SESIONES = ("inicio_utc", "fin_utc", "mensajes", "posiciones", "error")


def base_dir(override: str | Path | None = None) -> Path:
    return Path(override) if override else config.DATA_DIR / "ais"


def _fmt(v: Any) -> str:
    return "" if v is None else str(v)


def append(path: Path, columns: tuple[str, ...], rows: Iterable[Mapping[str, Any]]) -> int:
    rows = list(rows)
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists() or path.stat().st_size == 0
    needs_newline = False
    if not is_new:
        with path.open("rb") as f:
            f.seek(-1, 2)
            needs_newline = f.read(1) != b"\n"
    with path.open("a", newline="", encoding="utf-8") as f:
        if needs_newline:
            f.write("\n")
        w = csv.writer(f, lineterminator="\n")
        if is_new:
            w.writerow(columns)
        w.writerows([_fmt(r.get(c)) for c in columns] for r in rows)
    return len(rows)


def append_posiciones(base: Path, rows: Iterable[Mapping[str, Any]]) -> int:
    by_month: dict[str, list] = {}
    for r in rows:
        by_month.setdefault(r["ts_utc"][:7], []).append(r)
    return sum(append(base / "posiciones" / f"{m}.csv", POSICIONES, rs) for m, rs in sorted(by_month.items()))


def append_barcos(base: Path, rows) -> int:
    return append(base / "barcos.csv", BARCOS, rows)


def append_sesion(base: Path, row) -> int:
    return append(base / "sesiones.csv", SESIONES, [row])


def read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_posiciones(base: Path) -> list[dict[str, str]]:
    folder = base / "posiciones"
    out: list[dict[str, str]] = []
    for p in sorted(folder.glob("*.csv")) if folder.exists() else []:
        out.extend(read(p))
    return out
