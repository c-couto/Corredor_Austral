#!/usr/bin/env python3
"""
Migración única: copia las filas de data/legacy/auto.db (SQLite, formato viejo)
a los CSV de data/auto/ (formato nuevo). No modifica auto.db.

Se puede correr varias veces sin duplicar: solo agrega las filas de auto.db que
todavía no están en el CSV, y al final verifica que estén todas.

Uso (desde la raíz del repo):  python scripts/migrar_a_csv.py
"""

import sqlite3
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # para importar `corredor`

from corredor import config, storage  # noqa: E402

LEGACY_DB = config.DATA_DIR / "legacy" / "auto.db"
TABLES = [storage.WEATHER, storage.MARINE, storage.ERRORS]


def as_csv_row(row):
    """Una fila tal como queda escrita en el CSV (todo texto)."""
    return tuple(storage.fmt(v) for v in row)


def csv_rows(table):
    return Counter(tuple(r[c] for c in table.columns) for r in storage.read_rows(table))


def main():
    if not LEGACY_DB.exists():
        sys.exit(f"No existe {LEGACY_DB}")
    conn = sqlite3.connect(f"file:{LEGACY_DB}?mode=ro", uri=True)  # solo lectura
    all_ok = True
    for table in TABLES:
        db_rows = conn.execute(f"SELECT {', '.join(table.columns)} FROM {table.name} ORDER BY id").fetchall()

        # Filas que ya están en el CSV (contando repetidas, por las dudas).
        already = csv_rows(table)
        to_add = []
        for row in db_rows:
            key = as_csv_row(row)
            if already[key] > 0:
                already[key] -= 1
            else:
                to_add.append(dict(zip(table.columns, row)))
        storage.append_rows(table, to_add)

        # Verificación: cada fila de la base tiene que estar en el CSV.
        missing = Counter(as_csv_row(r) for r in db_rows) - csv_rows(table)
        status = "OK" if not missing else f"FALTAN {sum(missing.values())}"
        all_ok = all_ok and not missing
        print(f"{table.name:17} base: {len(db_rows):4}  agregadas ahora: {len(to_add):4}  "
              f"total en CSV: {len(storage.read_rows(table)):4}  -> {status}")
    conn.close()
    if not all_ok:
        sys.exit("La migración NO está completa.")
    print("Migración verificada: todas las filas de auto.db están en los CSV.")


if __name__ == "__main__":
    main()
