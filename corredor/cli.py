"""Comandos de línea: python -m corredor <comando>.

  python -m corredor run                      # una recolección
  python -m corredor loop --every 30          # recolecta cada 30 minutos
  python -m corredor status paso_san_sebastian abierto --note "cadenas obligatorias"
  python -m corredor event mar suspendido --place punta_delgada --note "viento"
  python -m corredor crossing punta_delgada_bahia_azul 150 --note "cola de 20 camiones"
  python -m corredor report                   # últimos datos
  python -m corredor export datos.csv         # junta todo en un solo CSV
"""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

from . import __version__, config, storage
from .collect import collect_once


def cmd_run(args: argparse.Namespace) -> None:
    ok_w, ok_m = collect_once()
    print(f"{storage.now_utc()} clima: {ok_w}/{len(config.PLACES)} puntos"
          f" · oleaje: {ok_m}/{len(config.MARINE_PLACES)} puntos")


def cmd_loop(args: argparse.Namespace) -> None:
    every = max(5, args.every) * 60
    print(f"Recolectando cada {args.every} min. Ctrl+C para detener.")
    while True:
        try:
            cmd_run(args)
        except Exception as e:
            storage.log_error("loop", e)
        time.sleep(every)


def cmd_status(args: argparse.Namespace) -> None:
    storage.append_rows(storage.STATUS, [{"ts_utc": storage.now_utc(), "subject": args.subject,
                                          "status": args.status, "note": args.note, "source": "manual"}])
    print(f"Registrado: {args.subject} = {args.status}")


def cmd_event(args: argparse.Namespace) -> None:
    storage.append_rows(storage.EVENTS, [{"ts_utc": storage.now_utc(), "mode": args.mode,
                                          "place": args.place, "kind": args.kind, "note": args.note}])
    print(f"Evento registrado: {args.mode} / {args.kind}")


def cmd_crossing(args: argparse.Namespace) -> None:
    storage.append_rows(storage.CROSSINGS, [{"ts_utc": storage.now_utc(), "route": args.route,
                                             "delay_minutes": args.delay_minutes, "note": args.note}])
    print(f"Demora registrada: {args.route} = {args.delay_minutes} min")


def cmd_report(args: argparse.Namespace) -> None:
    print("== Últimas observaciones de clima ==")
    latest = {}
    for r in storage.read_rows(storage.WEATHER):  # el archivo está en orden de llegada: gana la última
        latest[r["place"]] = r
    for place in sorted(latest):
        r = latest[place]
        print(f"{place:15} {r['ts_utc']}  viento {r['wind_kmh']} km/h · ráfaga {r['gust_kmh']} km/h"
              f" · máx. ráfaga 24 h {r['forecast_gust_max_24h_kmh']} km/h")
    if not latest:
        print("(todavía no hay datos: corré `python -m corredor run`)")
    for table, title in ((storage.STATUS, "Estados manuales"), (storage.EVENTS, "Eventos"),
                         (storage.CROSSINGS, "Demoras reales")):
        print(f"== {title}: {len(storage.read_rows(table))} registros ==")
    print(f"== Errores del recolector: {len(storage.read_rows(storage.ERRORS))} ==")


def cmd_export(args: argparse.Namespace) -> None:
    out = Path(args.file)
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["tabla", "ts_utc", "dato1", "dato2", "dato3", "dato4"])
        for r in storage.read_rows(storage.WEATHER):
            w.writerow(["clima", r["ts_utc"], r["place"], r["wind_kmh"], r["gust_kmh"], r["forecast_gust_max_24h_kmh"]])
        for r in storage.read_rows(storage.MARINE):
            w.writerow(["oleaje", r["ts_utc"], r["place"], r["wave_height_m"], r["wave_period_s"], ""])
        for r in storage.read_rows(storage.STATUS):
            w.writerow(["estado", r["ts_utc"], r["subject"], r["status"], r["note"], ""])
        for r in storage.read_rows(storage.EVENTS):
            w.writerow(["evento", r["ts_utc"], r["mode"], r["place"], r["kind"], r["note"]])
        for r in storage.read_rows(storage.CROSSINGS):
            w.writerow(["demora", r["ts_utc"], r["route"], r["delay_minutes"], r["note"], ""])
    print(f"Exportado a {out}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m corredor", description="Corredor Austral - recolector de datos")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.fn(args)
    return 0
