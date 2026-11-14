#!/usr/bin/env python3
"""
Corredor Austral - recolector de datos (v0.1)

Registra, en una base SQLite local, datos que más adelante servirán para
predecir demoras de abastecimiento hacia Tierra del Fuego:

  - Clima y viento (actual + pronóstico de ráfagas a 24 h) en puntos clave.
  - Oleaje (si la fuente tiene cobertura en ese punto).
  - Estados manuales (paso abierto/cerrado, ferry suspendido, etc.).
  - Demoras reales vividas (lo más valioso: son las "etiquetas" del futuro modelo).

Sin dependencias externas: solo la biblioteca estándar de Python 3.9+.

Datos: data/auto.db (lo escribe el recolector automático, p. ej. en la nube) y
data/manual.db (lo que cargás vos a mano). `report` y `export` leen las dos.

Uso:
  python collector.py run                      # una recolección
  python collector.py loop --every 30          # recolecta cada 30 minutos
  python collector.py status paso_san_sebastian abierto --note "cadenas obligatorias"
  python collector.py event ferry suspendido --place punta_delgada --note "viento"
  python collector.py crossing punta_delgada_bahia_azul 150 --note "cola de 20 camiones"
  python collector.py report                   # últimos datos
  python collector.py export datos.csv         # exporta todo a CSV

IMPORTANTE: revisá los términos de uso de cada fuente. La API gratuita de
Open-Meteo está pensada para uso NO comercial; si vas a vender un servicio
basado en estos datos, necesitás un plan comercial u otra fuente.
"""

import argparse
import csv
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Dos bases separadas para que la nube y vos no se pisen al usar git:
#   auto.db   -> la escribe SOLO el recolector automático (run / loop)
#   manual.db -> la escribís vos a mano (status / event / crossing)
DATA_DIR = Path(__file__).with_name("data")
AUTO_DB = DATA_DIR / "auto.db"
MANUAL_DB = DATA_DIR / "manual.db"
HTTP_TIMEOUT = 25

# Coordenadas APROXIMADAS (lat, lon). Verificalas en un mapa y ajustalas.
# Para clima, una diferencia de unos kilómetros no cambia mucho el resultado.
PLACES = {
    "rio_grande": (-53.79, -67.71),
    "ushuaia": (-54.80, -68.30),
    "san_sebastian": (-53.30, -68.50),
    "punta_delgada": (-52.43, -69.47),
    "bahia_azul": (-52.50, -69.40),
    "porvenir": (-53.30, -70.37),
    "punta_arenas": (-53.16, -70.91),
}

# Puntos donde también se consulta oleaje (modelo marino; puede no cubrir bien el estrecho).
MARINE_PLACES = ["punta_delgada", "bahia_azul", "ushuaia"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS weather_obs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    place TEXT NOT NULL,
    temp_c REAL,
    wind_kmh REAL,
    gust_kmh REAL,
    wind_dir_deg REAL,
    precip_mm REAL,
    forecast_gust_max_24h_kmh REAL,
    source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS marine_obs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    place TEXT NOT NULL,
    wave_height_m REAL,
    wave_period_s REAL,
    wave_dir_deg REAL,
    source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS status_obs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    subject TEXT NOT NULL,
    status TEXT NOT NULL,
    note TEXT,
    source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    mode TEXT NOT NULL,
    place TEXT,
    kind TEXT NOT NULL,
    note TEXT
);
CREATE TABLE IF NOT EXISTS crossings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    route TEXT NOT NULL,
    delay_minutes INTEGER NOT NULL,
    note TEXT
);
CREATE TABLE IF NOT EXISTS collector_errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    where_ TEXT NOT NULL,
    error TEXT NOT NULL
);
"""


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.executescript(SCHEMA)
    return conn


def existing_dbs():
    return [p for p in (AUTO_DB, MANUAL_DB) if p.exists()]


def log_error(conn, where, err):
    conn.execute(
        "INSERT INTO collector_errors (ts_utc, where_, error) VALUES (?,?,?)",
        (now_utc(), where, str(err)[:500]),
    )
    conn.commit()
    print(f"[error] {where}: {err}", file=sys.stderr)


def http_get_json(url, params):
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": "corredor-austral/0.1"})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _num(value):
    """Devuelve float o None (las APIs a veces devuelven null)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_weather(lat, lon):
    data = http_get_json(
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,wind_speed_10m,wind_gusts_10m,wind_direction_10m,precipitation",
            "hourly": "wind_gusts_10m",
            "forecast_hours": 24,
            "wind_speed_unit": "kmh",
            "timezone": "UTC",
        },
    )
    cur = data.get("current") or {}
    gusts = [g for g in (data.get("hourly") or {}).get("wind_gusts_10m", []) if g is not None]
    return {
        "temp_c": _num(cur.get("temperature_2m")),
        "wind_kmh": _num(cur.get("wind_speed_10m")),
        "gust_kmh": _num(cur.get("wind_gusts_10m")),
        "wind_dir_deg": _num(cur.get("wind_direction_10m")),
        "precip_mm": _num(cur.get("precipitation")),
        "forecast_gust_max_24h_kmh": max(gusts) if gusts else None,
    }


def fetch_marine(lat, lon):
    data = http_get_json(
        "https://marine-api.open-meteo.com/v1/marine",
        {
            "latitude": lat,
            "longitude": lon,
            "current": "wave_height,wave_period,wave_direction",
            "timezone": "UTC",
        },
    )
    cur = data.get("current") or {}
    return {
        "wave_height_m": _num(cur.get("wave_height")),
        "wave_period_s": _num(cur.get("wave_period")),
        "wave_dir_deg": _num(cur.get("wave_direction")),
    }


def collect_once(conn, weather_fn=fetch_weather, marine_fn=fetch_marine):
    ts = now_utc()
    ok_w = ok_m = 0
    for place, (lat, lon) in PLACES.items():
        try:
            w = weather_fn(lat, lon)
            conn.execute(
                "INSERT INTO weather_obs (ts_utc, place, temp_c, wind_kmh, gust_kmh, wind_dir_deg,"
                " precip_mm, forecast_gust_max_24h_kmh, source) VALUES (?,?,?,?,?,?,?,?,?)",
                (ts, place, w["temp_c"], w["wind_kmh"], w["gust_kmh"], w["wind_dir_deg"],
                 w["precip_mm"], w["forecast_gust_max_24h_kmh"], "open-meteo"),
            )
            ok_w += 1
        except Exception as e:  # una falla no debe frenar al resto
            log_error(conn, f"weather:{place}", e)
    for place in MARINE_PLACES:
        lat, lon = PLACES[place]
        try:
            m = marine_fn(lat, lon)
            conn.execute(
                "INSERT INTO marine_obs (ts_utc, place, wave_height_m, wave_period_s, wave_dir_deg, source)"
                " VALUES (?,?,?,?,?,?)",
                (ts, place, m["wave_height_m"], m["wave_period_s"], m["wave_dir_deg"], "open-meteo-marine"),
            )
            ok_m += 1
        except Exception as e:
            log_error(conn, f"marine:{place}", e)
    conn.commit()
    return ok_w, ok_m


def cmd_run(args):
    conn = connect(AUTO_DB)
    ok_w, ok_m = collect_once(conn)
    print(f"{now_utc()} clima: {ok_w}/{len(PLACES)} puntos · oleaje: {ok_m}/{len(MARINE_PLACES)} puntos")


def cmd_loop(args):
    conn = connect(AUTO_DB)
    every = max(5, args.every) * 60
    print(f"Recolectando cada {args.every} min. Ctrl+C para detener.")
    while True:
        try:
            ok_w, ok_m = collect_once(conn)
            print(f"{now_utc()} clima {ok_w}/{len(PLACES)} · oleaje {ok_m}/{len(MARINE_PLACES)}", flush=True)
        except Exception as e:
            log_error(conn, "loop", e)
        time.sleep(every)


def cmd_status(args):
    conn = connect(MANUAL_DB)
    conn.execute(
        "INSERT INTO status_obs (ts_utc, subject, status, note, source) VALUES (?,?,?,?,?)",
        (now_utc(), args.subject, args.status, args.note, "manual"),
    )
    conn.commit()
    print(f"Registrado: {args.subject} = {args.status}")


def cmd_event(args):
    conn = connect(MANUAL_DB)
    conn.execute(
        "INSERT INTO events (ts_utc, mode, place, kind, note) VALUES (?,?,?,?,?)",
        (now_utc(), args.mode, args.place, args.kind, args.note),
    )
    conn.commit()
    print(f"Evento registrado: {args.mode} / {args.kind}")


def cmd_crossing(args):
    conn = connect(MANUAL_DB)
    conn.execute(
        "INSERT INTO crossings (ts_utc, route, delay_minutes, note) VALUES (?,?,?,?)",
        (now_utc(), args.route, args.delay_minutes, args.note),
    )
    conn.commit()
    print(f"Demora registrada: {args.route} = {args.delay_minutes} min")


def cmd_report(args):
    conn = connect(AUTO_DB)
    print("== Últimas observaciones de clima ==")
    rows = conn.execute(
        "SELECT place, ts_utc, wind_kmh, gust_kmh, forecast_gust_max_24h_kmh FROM weather_obs"
        " WHERE id IN (SELECT MAX(id) FROM weather_obs GROUP BY place) ORDER BY place"
    ).fetchall()
    for place, ts, wind, gust, fg in rows:
        print(f"{place:15} {ts}  viento {wind} km/h · ráfaga {gust} km/h · máx. ráfaga 24 h {fg} km/h")
    if not rows:
        print("(todavía no hay datos: corré `python collector.py run`)")
    for table, title in (("status_obs", "Estados manuales"), ("events", "Eventos"), ("crossings", "Demoras reales")):
        n = 0
        for p in existing_dbs():
            c2 = connect(p)
            n += c2.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            c2.close()
        print(f"== {title}: {n} registros ==")
    n_err = conn.execute("SELECT COUNT(*) FROM collector_errors").fetchone()[0]
    print(f"== Errores del recolector: {n_err} ==")


def cmd_export(args):
    out = Path(args.file)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["tabla", "ts_utc", "dato1", "dato2", "dato3", "dato4"])
        for p in existing_dbs():
            conn = connect(p)
            for r in conn.execute("SELECT ts_utc, place, wind_kmh, gust_kmh, forecast_gust_max_24h_kmh FROM weather_obs"):
                w.writerow(["clima", *r])
            for r in conn.execute("SELECT ts_utc, place, wave_height_m, wave_period_s, '' FROM marine_obs"):
                w.writerow(["oleaje", *r])
            for r in conn.execute("SELECT ts_utc, subject, status, note, '' FROM status_obs"):
                w.writerow(["estado", *r])
            for r in conn.execute("SELECT ts_utc, mode, place, kind, note FROM events"):
                w.writerow(["evento", *r])
            for r in conn.execute("SELECT ts_utc, route, delay_minutes, note, '' FROM crossings"):
                w.writerow(["demora", *r])
            conn.close()
    print(f"Exportado a {out}")


def build_parser():
    p = argparse.ArgumentParser(description="Corredor Austral - recolector de datos")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("run", help="una recolección").set_defaults(fn=cmd_run)

    s = sub.add_parser("loop", help="recolectar de forma continua")
    s.add_argument("--every", type=int, default=30, help="minutos entre recolecciones (mínimo 5)")
    s.set_defaults(fn=cmd_loop)

    s = sub.add_parser("status", help="registrar un estado a mano")
    s.add_argument("subject", help="ej: paso_san_sebastian, ferry_primera_angostura")
    s.add_argument("status", help="ej: abierto, cerrado, suspendido, normal")
    s.add_argument("--note")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("event", help="registrar un evento (corte, paro, suspensión, vuelo cancelado...)")
    s.add_argument("mode", choices=["tierra", "mar", "aire"])
    s.add_argument("kind", help="ej: suspendido, corte, paro, cancelado, demora")
    s.add_argument("--place")
    s.add_argument("--note")
    s.set_defaults(fn=cmd_event)

    s = sub.add_parser("crossing", help="registrar una demora real de cruce")
    s.add_argument("route", help="ej: punta_delgada_bahia_azul")
    s.add_argument("delay_minutes", type=int)
    s.add_argument("--note")
    s.set_defaults(fn=cmd_crossing)

    sub.add_parser("report", help="ver últimos datos").set_defaults(fn=cmd_report)

    s = sub.add_parser("export", help="exportar todo a CSV")
    s.add_argument("file")
    s.set_defaults(fn=cmd_export)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
