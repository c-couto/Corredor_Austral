"""Comandos de línea: python -m corredor <comando>.

  python -m corredor run                      # una recolección
  python -m corredor loop --every 30          # recolecta cada 30 minutos
  python -m corredor status paso_san_sebastian abierto --note "cadenas obligatorias"
  python -m corredor event mar suspendido --place punta_delgada --note "viento"
  python -m corredor crossing punta_delgada_bahia_azul 150 --note "cola de 20 camiones"
  python -m corredor report                   # últimos datos
  python -m corredor export datos.csv         # junta todo en un solo CSV

TABSA, modelo, web y avisos:
  python -m corredor tabsa                    # lee el estado de TABSA y lo muestra (no guarda)
  python -m corredor train                    # entrena el modelo de riesgo con los datos
  python -m corredor web                      # genera la web en _site/index.html
  python -m corredor resumen                  # el mensaje que va a Telegram / WhatsApp
  python -m corredor notify                   # avisa por Telegram si cambió algo
  python -m corredor notify --force           # manda el resumen igual (para probar)
  python -m corredor salud                    # salud del sistema (TABSA, clima, errores, token)
"""

from __future__ import annotations

import argparse
import csv
import time
from pathlib import Path

from . import __version__, config, storage
from .collect import collect_once


def cmd_run(args: argparse.Namespace) -> None:
    r = collect_once()
    marine = f" · oleaje: {r.marine}/{len(config.MARINE_PLACES)} puntos" if config.WEATHER_SOURCE == "open_meteo" else ""
    print(f"{storage.now_utc()} clima ({config.WEATHER_SOURCE}): {r.weather}/{len(config.PLACES)} puntos{marine}"
          f" · TABSA: {r.tabsa_crossings} cruces, {r.tabsa_sailings} salidas, {r.tabsa_changes} cambios"
          f" · pronóstico: {r.forecast_rows} filas")


def cmd_tabsa(args: argparse.Namespace) -> None:
    from .sources import tabsa
    page = tabsa.fetch()
    for c in page.crossings:
        print(f"{c.name:20} {c.status}")
    for s in page.sailings:
        print(f"{s.date} {s.departure}  {s.origin} -> {s.destination:15} {s.status}")


def cmd_suspensiones(args: argparse.Namespace) -> None:
    from .conditions import fmt_duration, snapshot
    from .timeutil import fmt_local, format_ts
    snap = snapshot(fetch_forecast=False)
    if not snap.episodes:
        print("Todavía no hay suspensiones registradas.")
        return
    print(f"{'cruce':20} {'estado':12} {'inicio (UTC)':22} {'fin (UTC)':22} duración")
    for e in reversed(snap.episodes):
        end = format_ts(e.end) if e.end else "en curso"
        print(f"{e.name:20} {e.status:12} {format_ts(e.start):22} {end:22} {fmt_duration(e.duration(snap.now))}"
              f"   (local {fmt_local(e.start)})")


def cmd_train(args: argparse.Namespace) -> None:
    from . import model
    if args.if_stale and not model.is_stale():
        print("El modelo ya se entrenó hoy: no se reentrena.")
        return
    for key, m in model.train_all().items():
        print(f"{config.ROUTES[key]['name']:25} {m.kind:8} {m.reason}")
        if m.metrics:
            print(f"{'':25} {m.metrics}")


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


def datos_de_github(ref: str = "origin/main", repo: Path | None = None) -> Path:
    """Baja lo último de GitHub (`git fetch`) y deja una copia de data/ en una carpeta temporal.

    No toca tu carpeta data/ ni tu rama: el recolector sube datos nuevos cada 30 min y tu copia local
    se va quedando vieja (una web armada con ella dice "datos de hace 23 h" aunque el servicio ande bien).
    Devuelve la carpeta temporal que contiene data/.
    """
    import subprocess
    import tarfile
    import tempfile
    repo = repo or config.ROOT
    if "/" in ref:
        remote, branch = ref.split("/", 1)
        subprocess.run(["git", "fetch", "--quiet", remote, branch], cwd=repo, check=True, timeout=180)
    tmp = Path(tempfile.mkdtemp(prefix="corredor-datos-"))
    proc = subprocess.Popen(["git", "archive", ref, "data"], cwd=repo, stdout=subprocess.PIPE)
    with tarfile.open(fileobj=proc.stdout, mode="r|") as tar:
        if hasattr(tarfile, "data_filter"):
            tar.extractall(tmp, filter="data")
        else:  # Python viejo: el contenido viene de nuestro propio repositorio
            tar.extractall(tmp)
    if proc.wait() != 0:
        raise RuntimeError(f"git archive {ref} falló")
    return tmp


def _aviso_si_datos_viejos() -> None:
    rows = storage.read_rows(storage.TABSA_STATE)
    if not rows:
        return
    from datetime import datetime, timezone
    from .timeutil import parse_ts
    edad = datetime.now(timezone.utc) - parse_ts(rows[-1]["ts_utc"])
    if edad.total_seconds() > config.STALE_AFTER_H * 3600:
        horas = edad.total_seconds() / 3600
        print(f"\nAVISO: los datos de esta web son de hace {horas:.0f} h (tu carpeta data/ está desactualizada;\n"
              f"  el servicio no está caído). Para verla con lo último de GitHub:  python -m corredor web --fresco")


def cmd_web(args: argparse.Namespace) -> None:
    from .web import build_site
    if args.fresco:
        try:
            carpeta = datos_de_github()
            config.DATA_DIR = carpeta / "data"
            print(f"Usando los datos más nuevos de GitHub (copia temporal en {carpeta}).")
        except Exception as e:  # sin internet / sin git: se avisa y se usa lo local
            print(f"AVISO: no pude bajar los datos de GitHub ({e}); uso los de tu carpeta.")
    path = build_site(Path(args.out))
    print(f"Web generada: {path.resolve()}")
    _aviso_si_datos_viejos()


def cmd_resumen(args: argparse.Namespace) -> None:
    from .conditions import snapshot, summary_text
    print(summary_text(snapshot()))


def cmd_notify(args: argparse.Namespace) -> None:
    from .alerts import notify
    print(notify(force=args.force))


def cmd_salud(args: argparse.Namespace) -> None:
    from . import salud
    print(salud.texto(salud.calcular()))
    if args.avisar:
        print("\n" + salud.avisar())


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

    sub.add_parser("tabsa", help="leer el estado de TABSA y mostrarlo (no guarda)").set_defaults(fn=cmd_tabsa)
    sub.add_parser("suspensiones", help="suspensiones registradas: inicio, fin y duración").set_defaults(
        fn=cmd_suspensiones)

    s = sub.add_parser("train", help="entrenar el modelo de riesgo con los datos")
    s.add_argument("--if-stale", action="store_true", help="solo si no se entrenó hoy")
    s.set_defaults(fn=cmd_train)

    s = sub.add_parser("web", help="BETA: generar la web estática")
    s.add_argument("--out", default=str(config.ROOT / "_site"), help="carpeta de salida (por defecto _site/)")
    s.add_argument("--fresco", action="store_true",
                   help="usar los datos más nuevos de GitHub (git fetch; no cambia tu carpeta data/)")
    s.set_defaults(fn=cmd_web)

    sub.add_parser("resumen", help="BETA: ver el resumen para Telegram / WhatsApp").set_defaults(fn=cmd_resumen)

    s = sub.add_parser("notify", help="BETA: avisar por Telegram si cambió el riesgo")
    s.add_argument("--force", action="store_true", help="enviar el resumen aunque no haya cambios")
    s.set_defaults(fn=cmd_notify)

    s = sub.add_parser("salud", help="¿está recolectando bien? (solo lee; no cambia nada)")
    s.add_argument("--avisar", action="store_true",
                   help="avisar al equipo por Telegram (TELEGRAM_TEAM_CHAT_ID) lo que se puso mal desde la revisión anterior")
    s.set_defaults(fn=cmd_salud)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    args.fn(args)
    return 0
