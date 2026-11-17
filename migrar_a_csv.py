#!/usr/bin/env python3
"""
Migración única: copia las filas de data/auto.db (SQLite, formato viejo) a los CSV
de data/ (formato nuevo). No modifica auto.db.

Se puede correr varias veces sin duplicar: solo agrega las filas de auto.db que
todavía no están en el CSV. Sirve si el bot llegó a guardar alguna corrida más en
auto.db antes de que se subiera el workflow nuevo.

Uso:  python migrar_a_csv.py
"""

import sqlite3
import sys
from collections import Counter

import collector

AUTO_DB = collector.DATA_DIR / "auto.db"
TABLES = ["weather_obs", "marine_obs", "collector_errors"]


def as_csv_row(row):
    """Una fila tal como queda escrita en el CSV (todo texto)."""
    return tuple(collector.fmt(v) for v in row)


def main():
    if not AUTO_DB.exists():
        sys.exit(f"No existe {AUTO_DB}")
    conn = sqlite3.connect(f"file:{AUTO_DB}?mode=ro", uri=True)  # solo lectura
    all_ok = True
    for table in TABLES:
        columns = collector.TABLES[table]
        db_rows = conn.execute(f"SELECT {', '.join(columns)} FROM {table} ORDER BY id").fetchall()

        # Filas que ya están en el CSV (contando repetidas, por las dudas).
        already = Counter(tuple(r[c] for c in columns) for r in collector.read_rows(table))
        to_add = []
        for row in db_rows:
            key = as_csv_row(row)
            if already[key] > 0:
                already[key] -= 1
            else:
                to_add.append(dict(zip(columns, row)))
        collector.append_rows(table, to_add)

        # Verificación: cada fila de la base tiene que estar en el CSV.
        in_csv = Counter(tuple(r[c] for c in columns) for r in collector.read_rows(table))
        missing = Counter(as_csv_row(r) for r in db_rows) - in_csv
        n_csv = len(collector.read_rows(table))
        status = "OK" if not missing else f"FALTAN {sum(missing.values())}"
        all_ok = all_ok and not missing
        print(f"{table:17} base: {len(db_rows):4}  agregadas ahora: {len(to_add):4}  "
              f"total en CSV: {n_csv:4}  -> {status}")
    conn.close()
    if not all_ok:
        sys.exit("La migración NO está completa.")
    print("Migración verificada: todas las filas de auto.db están en los CSV.")


if __name__ == "__main__":
    main()
