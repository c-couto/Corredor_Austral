"""Escucha aisstream.io unos minutos y guarda las posiciones de los barcos en las zonas.

Uso (desde la raíz del repo):
    set AISSTREAM_API_KEY=...            (Windows)   /   export AISSTREAM_API_KEY=...
    python -m ais.sondeo --minutos 10

La clave se lee SOLO de la variable de entorno AISSTREAM_API_KEY (en GitHub: Secret).
Nunca se escribe en archivos ni se muestra en los mensajes de error.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import barcos, datos
from . import websocket as ws

URL = "wss://stream.aisstream.io/v0/stream"
TIPOS = ["PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport",
         "ShipStaticData", "StaticDataReport"]
MIN_INTERVALO_S = 60     # como mucho una posición guardada por barco por minuto
GUARDAR_CADA_S = 60      # se escribe al disco cada minuto (si el trabajo se corta, se pierde poco)
ESPERA_RECONEXION_S = 5
TS = "%Y-%m-%dT%H:%M:%SZ"


class ClaveInvalida(Exception):
    pass


def subscription(key: str, zonas: dict | None = None) -> dict:
    return {
        "APIKey": key,
        "BoundingBoxes": [[list(sw), list(ne)] for sw, ne in (zonas or barcos.ZONAS).values()],
        "FilterMessageTypes": TIPOS,
    }


def tipo_de(raw: bytes | str) -> str:
    """Tipo de mensaje de aisstream (para el diagnóstico de lo que llega)."""
    try:
        msg = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return "(no es JSON)"
    if not isinstance(msg, dict):
        return "(JSON raro)"
    return "error" if "error" in msg else str(msg.get("MessageType") or "(sin tipo)")


def _ts(meta_time: Any, fallback: datetime) -> str:
    """aisstream manda '2026-11-20 14:03:21.123456789 +0000 UTC' (siempre UTC)."""
    try:
        return datetime.strptime(str(meta_time)[:19], "%Y-%m-%d %H:%M:%S").strftime(TS)
    except ValueError:
        return fallback.strftime(TS)


def _num(v: Any, lo: float, hi: float) -> float | None:
    """Número válido dentro de [lo, hi]; AIS usa valores fuera de rango para 'sin dato'."""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return round(x, 5) if lo <= x <= hi else None


def parse_message(raw: bytes | str, now: datetime | None = None) -> dict | None:
    """Mensaje de aisstream -> {"kind": "pos"|"static"|"error", "row": {...}} o None."""
    now = now or datetime.now(timezone.utc)
    try:
        msg = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(msg, dict):
        return None
    if "error" in msg:
        return {"kind": "error", "error": str(msg["error"])}
    kind = msg.get("MessageType")
    meta = msg.get("MetaData") or {}
    body = (msg.get("Message") or {}).get(kind) or {}
    try:
        mmsi = int(meta.get("MMSI") or body.get("UserID"))
    except (TypeError, ValueError):
        return None
    ts = _ts(meta.get("time_utc"), now)
    name = str(meta.get("ShipName") or "").strip() or None
    if kind in ("PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport"):
        lat = _num(body.get("Latitude", meta.get("latitude")), -90, 90)
        lon = _num(body.get("Longitude", meta.get("longitude")), -180, 180)
        if lat is None or lon is None:
            return None
        return {"kind": "pos", "row": {
            "ts_utc": ts, "mmsi": mmsi, "nombre": name, "lat": lat, "lon": lon,
            "sog_kn": _num(body.get("Sog"), 0, 102.2),
            "cog_deg": _num(body.get("Cog"), 0, 359.9),
            "rumbo_deg": _num(body.get("TrueHeading"), 0, 359),
            "estado_nav": body.get("NavigationalStatus"),
            "tipo_msg": kind, "zona": barcos.zona_de(lat, lon),
        }}
    if kind == "ShipStaticData":
        return {"kind": "static", "row": {
            "ts_utc": ts, "mmsi": mmsi, "nombre": str(body.get("Name") or name or "").strip() or None,
            "tipo": body.get("Type"), "callsign": str(body.get("CallSign") or "").strip() or None,
            "imo": body.get("ImoNumber") or None, "destino": str(body.get("Destination") or "").strip() or None,
        }}
    if kind == "StaticDataReport":
        a, b = body.get("ReportA") or {}, body.get("ReportB") or {}
        return {"kind": "static", "row": {
            "ts_utc": ts, "mmsi": mmsi, "nombre": str(a.get("Name") or name or "").strip() or None,
            "tipo": b.get("ShipType"), "callsign": str(b.get("CallSign") or "").strip() or None,
            "imo": None, "destino": None,
        }}
    return None


def _safe(text: str, key: str) -> str:
    return text.replace(key, "***") if key else text


def run(minutes: float, key: str, base: Path, *, connect: Callable = ws.connect,
        clock: Callable[[], float] = time.time, sleep: Callable[[float], None] = time.sleep,
        log: Callable[[str], None] = print, zonas: dict | None = None) -> dict:
    """Escucha `minutes` minutos (reconectando si se corta) y guarda todo en `base`.

    `stats["tipos"]` cuenta qué tipos de mensaje llegaron (no se guarda en el CSV:
    sesiones.csv mantiene sus columnas; se muestra en el log de la corrida).
    """
    start = datetime.now(timezone.utc)
    deadline = clock() + minutes * 60
    stats: dict[str, Any] = {"mensajes": 0, "posiciones": 0, "error": "", "tipos": {}}
    pending_pos: list[dict] = []
    pending_static: list[dict] = []
    last_saved: dict[int, float] = {}
    static_seen: set[int] = set()
    last_flush = clock()

    def flush() -> None:
        nonlocal pending_pos, pending_static, last_flush
        stats["posiciones"] += datos.append_posiciones(base, pending_pos)
        datos.append_barcos(base, pending_static)
        pending_pos, pending_static, last_flush = [], [], clock()

    try:
        while clock() < deadline:
            conn = None
            try:
                conn = connect(URL, timeout=10)  # si no llega nada en 10 s, recv() avisa con timeout
                conn.send_text(json.dumps(subscription(key, zonas)))  # dentro de los 3 s de conectar
                while clock() < deadline:
                    if clock() - last_flush >= GUARDAR_CADA_S:
                        flush()
                    try:
                        raw = conn.recv()
                    except socket.timeout:
                        continue
                    stats["mensajes"] += 1
                    tipo = tipo_de(raw)
                    stats["tipos"][tipo] = stats["tipos"].get(tipo, 0) + 1
                    parsed = parse_message(raw)
                    if parsed is None:
                        continue
                    if parsed["kind"] == "error":
                        raise ClaveInvalida(parsed["error"])
                    row = parsed["row"]
                    if parsed["kind"] == "static":
                        if row["mmsi"] not in static_seen:
                            static_seen.add(row["mmsi"])
                            pending_static.append(row)
                        continue
                    t = datetime.strptime(row["ts_utc"], TS).timestamp()
                    if t - last_saved.get(row["mmsi"], float("-inf")) >= MIN_INTERVALO_S:
                        last_saved[row["mmsi"]] = t
                        pending_pos.append(row)
            except ClaveInvalida:
                raise
            except (OSError, ws.WebSocketError) as e:
                stats["error"] = _safe(f"{type(e).__name__}: {e}", key)[:300]
                log(f"Conexión cortada ({stats['error']}); reintento en {ESPERA_RECONEXION_S} s")
                if clock() + ESPERA_RECONEXION_S < deadline:
                    sleep(ESPERA_RECONEXION_S)
            finally:
                if conn is not None:
                    conn.close()
    except ClaveInvalida as e:
        stats["error"] = _safe(f"aisstream rechazó la suscripción: {e}", key)[:300]
        log(stats["error"])
    finally:
        flush()
        datos.append_sesion(base, {"inicio_utc": start.strftime(TS),
                                   "fin_utc": datetime.now(timezone.utc).strftime(TS), **stats})
    return stats


def _tipos_txt(tipos: dict) -> str:
    return ", ".join(f"{t} {n}" for t, n in sorted(tipos.items(), key=lambda kv: -kv[1])) or "ninguno"


def control(key: str, minutes: float = 2, **kwargs) -> dict:
    """Prueba de control: escucha en zonas con mucho tráfico y NO guarda nada en data/.

    Devuelve {"stats": ..., "por_zona": {zona: (posiciones, barcos distintos)}}.
    """
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        stats = run(minutes, key, base, zonas=barcos.ZONAS_CONTROL, **kwargs)
        por_zona = {}
        filas = datos.read_posiciones(base)
        for zona, ((s, w), (n, e)) in barcos.ZONAS_CONTROL.items():
            en = [r for r in filas if s <= float(r["lat"]) <= n and w <= float(r["lon"]) <= e]
            por_zona[zona] = (len(en), len({r["mmsi"] for r in en}))
    return {"stats": stats, "por_zona": por_zona}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m ais.sondeo", description=__doc__.splitlines()[0])
    p.add_argument("--minutos", type=float, default=None, help="cuánto escuchar (por defecto 10; 2 con --control)")
    p.add_argument("--datos", help="carpeta de datos (por defecto data/ais/)")
    p.add_argument("--control", action="store_true",
                   help="prueba de control en zonas con mucho tráfico (no guarda nada)")
    args = p.parse_args(argv)
    key = os.environ.get("AISSTREAM_API_KEY", "").strip()
    if not key:
        print("Falta la variable de entorno AISSTREAM_API_KEY (clave gratis de aisstream.io).", file=sys.stderr)
        return 2
    if args.control:
        res = control(key, args.minutos or 2)
        stats = res["stats"]
        print(f"PRUEBA DE CONTROL ({args.minutos or 2:g} min, no se guarda nada)")
        print(f"Mensajes recibidos: {stats['mensajes']} · tipos: {_tipos_txt(stats['tipos'])}")
        for zona, (n_pos, n_barcos) in res["por_zona"].items():
            print(f"  {zona}: {n_pos} posiciones de {n_barcos} barcos distintos")
        if stats["error"]:
            print(f"Último error: {stats['error']}")
        ok = any(n for n, _ in res["por_zona"].values())
        print("RESULTADO: la clave y el código reciben datos. Si el Estrecho no da nada, es falta de cobertura."
              if ok else "RESULTADO: no llegó ninguna posición ni en zonas con mucho tráfico: revisar clave/código.")
        return 0 if ok else 1
    base = datos.base_dir(args.datos)
    stats = run(args.minutos or 10, key, base)
    print(f"Mensajes recibidos: {stats['mensajes']} · posiciones guardadas: {stats['posiciones']}"
          f"{' · último error: ' + stats['error'] if stats['error'] else ''}")
    print(f"Tipos de mensaje: {_tipos_txt(stats['tipos'])}")
    return 1 if stats["error"].startswith("aisstream rechazó") else 0


if __name__ == "__main__":
    raise SystemExit(main())
