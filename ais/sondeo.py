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


def subscription(key: str) -> dict:
    return {
        "APIKey": key,
        "BoundingBoxes": [[list(sw), list(ne)] for sw, ne in barcos.ZONAS.values()],
        "FilterMessageTypes": TIPOS,
    }


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
        log: Callable[[str], None] = print) -> dict:
    """Escucha `minutes` minutos (reconectando si se corta) y guarda todo en `base`."""
    start = datetime.now(timezone.utc)
    deadline = clock() + minutes * 60
    stats = {"mensajes": 0, "posiciones": 0, "error": ""}
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
                conn.send_text(json.dumps(subscription(key)))  # dentro de los 3 s de conectar
                while clock() < deadline:
                    if clock() - last_flush >= GUARDAR_CADA_S:
                        flush()
                    try:
                        raw = conn.recv()
                    except socket.timeout:
                        continue
                    stats["mensajes"] += 1
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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m ais.sondeo", description=__doc__.splitlines()[0])
    p.add_argument("--minutos", type=float, default=10, help="cuánto escuchar (por defecto 10)")
    p.add_argument("--datos", help="carpeta de datos (por defecto data/ais/)")
    args = p.parse_args(argv)
    key = os.environ.get("AISSTREAM_API_KEY", "").strip()
    if not key:
        print("Falta la variable de entorno AISSTREAM_API_KEY (clave gratis de aisstream.io).", file=sys.stderr)
        return 2
    base = datos.base_dir(args.datos)
    stats = run(args.minutos, key, base)
    print(f"Mensajes recibidos: {stats['mensajes']} · posiciones guardadas: {stats['posiciones']}"
          f"{' · último error: ' + stats['error'] if stats['error'] else ''}")
    return 1 if stats["error"].startswith("aisstream rechazó") else 0


if __name__ == "__main__":
    raise SystemExit(main())
