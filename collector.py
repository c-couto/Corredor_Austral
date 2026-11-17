#!/usr/bin/env python3
"""
Corredor Austral - recolector de datos (v0.2)

Guarda, en archivos CSV dentro de data/, datos que más adelante servirán para
predecir demoras en el cruce:

  - Clima y viento (actual + pronóstico de ráfagas a 24 h) en puntos clave.
  - Oleaje (si la fuente tiene cobertura en ese punto).
  - Estados manuales (paso abierto/cerrado, ferry suspendido, etc.).
  - Demoras reales vividas (lo más valioso: son las "etiquetas" del futuro modelo).

Sin dependencias externas: solo la biblioteca estándar de Python 3.9+.

Datos: un CSV por tabla en data/. Siempre se AGREGAN filas al final, nunca se
borran ni se reescriben. Todas las horas están en UTC.
  - Los escribe el recolector automático (run / loop):
      weather_obs.csv, marine_obs.csv, collector_errors.csv
  - Los escribís vos a mano (status / event / crossing):
      status_obs.csv, events.csv, crossings.csv
Como la nube y vos escriben archivos distintos, git no da conflictos.

Uso:
  python collector.py run                      # una recolección
  python collector.py loop --every 30          # recolecta cada 30 minutos
  python collector.py status paso_san_sebastian abierto --note "cadenas obligatorias"
  python collector.py event mar suspendido --place punta_delgada --note "viento"
  python collector.py crossing punta_delgada_bahia_azul 150 --note "cola de 20 camiones"
  python collector.py report                   # últimos datos
  python collector.py export datos.csv         # junta todo en un solo CSV

IMPORTANTE: revisá los términos de uso de cada fuente. La API gratuita de
Open-Meteo está pensada para uso NO comercial; si vas a vender un servicio
basado en estos datos, necesitás un plan comercial u otra fuente.
"""

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(__file__).with_name("data")

# Cada consulta espera como máximo 15 s. Si falla, se reintenta hasta 3 veces,
# esperando cada vez un poco más (5 s, 10 s y 20 s).
HTTP_TIMEOUT = 15
RETRY_WAITS = (5, 10, 20)

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

# Columnas de cada CSV (data/<tabla>.csv), en orden.
TABLES = {
    "weather_obs": ["ts_utc", "place", "temp_c", "wind_kmh", "gust_kmh", "wind_dir_deg",
                    "precip_mm", "forecast_gust_max_24h_kmh", "source"],
    "marine_obs": ["ts_utc", "place", "wave_height_m", "wave_period_s", "wave_dir_deg", "source"],
    "collector_errors": ["ts_utc", "where_", "error"],
    "status_obs": ["ts_utc", "subject", "status", "note", "source"],
    "events": ["ts_utc", "mode", "place", "kind", "note"],
    "crossings": ["ts_utc", "route", "delay_minutes", "note"],
}


# ---------------------------------------------------------------- archivos CSV

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def csv_path(table):
    return DATA_DIR / f"{table}.csv"


def fmt(value):
    """Cómo se escribe cada valor en el CSV: vacío si no hay dato."""
    if value is None:
        return ""
    return str(value)


def append_rows(table, rows):
    """Agrega filas (diccionarios) al final del CSV de la tabla. Nunca borra nada."""
    if not rows:
        return
    columns = TABLES[table]
    path = csv_path(table)
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists() or path.stat().st_size == 0
    # Si alguien editó el archivo y quedó sin salto de línea al final, lo agregamos
    # para que la fila nueva no se pegue a la anterior.
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
        for r in rows:
            w.writerow([fmt(r.get(c)) for c in columns])


def read_rows(table):
    """Devuelve las filas del CSV como diccionarios (lista vacía si no existe)."""
    path = csv_path(table)
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def log_error(where, err):
    append_rows("collector_errors", [{"ts_utc": now_utc(), "where_": where, "error": str(err)[:500]}])
    print(f"[error] {where}: {err}", file=sys.stderr)


# ------------------------------------------------------------ consultas a la API

def http_get_json(url, params):
    """GET con timeout de 15 s y hasta 3 reintentos con espera creciente."""
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": "corredor-austral/0.2"})
    last_error = None
    for attempt in range(len(RETRY_WAITS) + 1):
        if attempt > 0:
            wait = RETRY_WAITS[attempt - 1]
            print(f"  reintento {attempt}/{len(RETRY_WAITS)} en {wait} s ({last_error})", file=sys.stderr)
            time.sleep(wait)
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # Un error 4xx (pedido mal armado) no se arregla reintentando,
            # salvo el 429 (demasiadas consultas).
            if 400 <= e.code < 500 and e.code != 429:
                raise
            last_error = e
        except Exception as e:  # timeout, conexión cortada, respuesta rota...
            last_error = e
    raise last_error


def fetch_many(url, places, params):
    """Pide varios lugares en UNA sola consulta (coordenadas separadas por coma).

    Open-Meteo devuelve una lista con un resultado por lugar, en el mismo orden.
    Devuelve {lugar: resultado}.
    """
    data = http_get_json(
        url,
        {
            "latitude": ",".join(str(PLACES[p][0]) for p in places),
            "longitude": ",".join(str(PLACES[p][1]) for p in places),
            **params,
        },
    )
    if isinstance(data, dict):  # con un solo lugar devuelve un objeto, no una lista
        data = [data]
    if len(data) != len(places):
        raise ValueError(f"se pidieron {len(places)} lugares y llegaron {len(data)}")
    return dict(zip(places, data))


def _num(value):
    """Devuelve float o None (las APIs a veces devuelven null)."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_weather_all(places):
    raw = fetch_many(
        "https://api.open-meteo.com/v1/forecast",
        places,
        {
            "current": "temperature_2m,wind_speed_10m,wind_gusts_10m,wind_direction_10m,precipitation",
            "hourly": "wind_gusts_10m",
            "forecast_hours": 24,
            "wind_speed_unit": "kmh",
            "timezone": "UTC",
        },
    )
    out = {}
    for place, data in raw.items():
        cur = data.get("current") or {}
        gusts = [_num(g) for g in (data.get("hourly") or {}).get("wind_gusts_10m", []) if _num(g) is not None]
        out[place] = {
            "temp_c": _num(cur.get("temperature_2m")),
            "wind_kmh": _num(cur.get("wind_speed_10m")),
            "gust_kmh": _num(cur.get("wind_gusts_10m")),
            "wind_dir_deg": _num(cur.get("wind_direction_10m")),
            "precip_mm": _num(cur.get("precipitation")),
            "forecast_gust_max_24h_kmh": max(gusts) if gusts else None,
        }
    return out


def fetch_marine_all(places):
    raw = fetch_many(
        "https://marine-api.open-meteo.com/v1/marine",
        places,
        {"current": "wave_height,wave_period,wave_direction", "timezone": "UTC"},
    )
    out = {}
    for place, data in raw.items():
        cur = data.get("current") or {}
        out[place] = {
            "wave_height_m": _num(cur.get("wave_height")),
            "wave_period_s": _num(cur.get("wave_period")),
            "wave_dir_deg": _num(cur.get("wave_direction")),
        }
    return out


def collect_once(weather_fn=fetch_weather_all, marine_fn=fetch_marine_all):
    """Una recolección: 1 consulta de clima + 1 de oleaje. Si una falla, se anota y se sigue."""
    ts = now_utc()  # todas las filas de esta corrida llevan la misma hora

    try:
        weather = weather_fn(list(PLACES))
    except Exception as e:
        log_error("weather", e)
        weather = {}
    append_rows("weather_obs", [
        {"ts_utc": ts, "place": place, **w, "source": "open-meteo"} for place, w in weather.items()
    ])

    try:
        marine = marine_fn(list(MARINE_PLACES))
    except Exception as e:
        log_error("marine", e)
        marine = {}
    append_rows("marine_obs", [
        {"ts_utc": ts, "place": place, **m, "source": "open-meteo-marine"} for place, m in marine.items()
    ])

    return len(weather), len(marine)


# -------------------------------------------------------------------- comandos

def cmd_run(args):
    ok_w, ok_m = collect_once()
    print(f"{now_utc()} clima: {ok_w}/{len(PLACES)} puntos · oleaje: {ok_m}/{len(MARINE_PLACES)} puntos")


def cmd_loop(args):
    every = max(5, args.every) * 60
    print(f"Recolectando cada {args.every} min. Ctrl+C para detener.")
    while True:
        try:
            ok_w, ok_m = collect_once()
            print(f"{now_utc()} clima {ok_w}/{len(PLACES)} · oleaje {ok_m}/{len(MARINE_PLACES)}", flush=True)
        except Exception as e:
            log_error("loop", e)
        time.sleep(every)


def cmd_status(args):
    append_rows("status_obs", [{"ts_utc": now_utc(), "subject": args.subject, "status": args.status,
                                "note": args.note, "source": "manual"}])
    print(f"Registrado: {args.subject} = {args.status}")


def cmd_event(args):
    append_rows("events", [{"ts_utc": now_utc(), "mode": args.mode, "place": args.place,
                            "kind": args.kind, "note": args.note}])
    print(f"Evento registrado: {args.mode} / {args.kind}")


def cmd_crossing(args):
    append_rows("crossings", [{"ts_utc": now_utc(), "route": args.route,
                               "delay_minutes": args.delay_minutes, "note": args.note}])
    print(f"Demora registrada: {args.route} = {args.delay_minutes} min")


def cmd_report(args):
    print("== Últimas observaciones de clima ==")
    latest = {}
    for r in read_rows("weather_obs"):  # el archivo está en orden de llegada: gana la última
        latest[r["place"]] = r
    for place in sorted(latest):
        r = latest[place]
        print(f"{place:15} {r['ts_utc']}  viento {r['wind_kmh']} km/h · ráfaga {r['gust_kmh']} km/h"
              f" · máx. ráfaga 24 h {r['forecast_gust_max_24h_kmh']} km/h")
    if not latest:
        print("(todavía no hay datos: corré `python collector.py run`)")
    for table, title in (("status_obs", "Estados manuales"), ("events", "Eventos"), ("crossings", "Demoras reales")):
        print(f"== {title}: {len(read_rows(table))} registros ==")
    print(f"== Errores del recolector: {len(read_rows('collector_errors'))} ==")


def cmd_export(args):
    out = Path(args.file)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["tabla", "ts_utc", "dato1", "dato2", "dato3", "dato4"])
        for r in read_rows("weather_obs"):
            w.writerow(["clima", r["ts_utc"], r["place"], r["wind_kmh"], r["gust_kmh"], r["forecast_gust_max_24h_kmh"]])
        for r in read_rows("marine_obs"):
            w.writerow(["oleaje", r["ts_utc"], r["place"], r["wave_height_m"], r["wave_period_s"], ""])
        for r in read_rows("status_obs"):
            w.writerow(["estado", r["ts_utc"], r["subject"], r["status"], r["note"], ""])
        for r in read_rows("events"):
            w.writerow(["evento", r["ts_utc"], r["mode"], r["place"], r["kind"], r["note"]])
        for r in read_rows("crossings"):
            w.writerow(["demora", r["ts_utc"], r["route"], r["delay_minutes"], r["note"], ""])
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

    s = sub.add_parser("export", help="juntar todo en un solo CSV")
    s.add_argument("file")
    s.set_defaults(fn=cmd_export)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
