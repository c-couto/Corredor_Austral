"""Cómo nos fue: compara lo que PREDIJIMOS con lo que hizo TABSA.

Uso (desde la raíz del repo):
    python -m corredor.evaluacion              # todo el historial
    python -m corredor.evaluacion --dias 7     # últimos 7 días
    python -m corredor.evaluacion --csv .cache/evaluacion.csv   # detalle fila por fila

Solo LEE datos: no escribe en data/ ni toca el modelo.

Para que la medición sea honesta:
  - Se usa el modelo que estaba vigente EN ESE MOMENTO (versiones de data/model/modelo.json
    en el historial de git), no el de hoy.
  - "Con anticipación" usa el pronóstico TAL COMO ESTABA entonces (data/auto/pronosticos/),
    nunca datos del futuro.
  - "En el momento" (0 h) usa el viento medido en esa misma corrida.

Métricas (para cada anticipación):
  Brier          error cuadrático medio de la probabilidad (0 = perfecto). Se compara con
                 "siempre decir la frecuencia promedio" (referencia): si no le ganamos, el
                 modelo no aporta.
  Detectadas     suspensiones reales a las que les dimos ≥ 50 % (y ≥ 20 %).
  Falsas alarmas momentos NORMALES a los que les dimos ≥ 50 %.
"""

from __future__ import annotations

import argparse
import bisect
import csv
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config, model, storage
from .sources import num
from .timeutil import fmt_local, local_to_utc, parse_ts

ANTICIPACIONES_H = (0, 3, 12, 24)
TOLERANCIA_CLIMA = timedelta(minutes=35)   # clima medido más cercano a la observación
TOLERANCIA_EMISION = timedelta(hours=1)    # el pronóstico usado no puede ser más viejo que esto


@dataclass
class Observacion:
    ruta: str
    t: datetime           # cuándo (UTC)
    estado: str
    y: int                # 1 = suspendido / no normal
    ts_corrida: str       # corrida en la que se vio


# ------------------------------------------------------------------ modelos vigentes

def _modelos_desde_json(texto: str) -> dict[str, model.RouteModel]:
    data = json.loads(texto)
    out = {}
    for key, m in data.get("routes", {}).items():
        try:
            out[key] = model.RouteModel(**{**m, "route": key})
        except TypeError:
            continue
    return out


def historial_modelos() -> list[tuple[datetime, dict[str, model.RouteModel]]]:
    """Versiones de modelo.json en git: [(fecha de entrenamiento, modelos)], de la más vieja a la más nueva.
    Si no hay git (o los datos no son los del repo), devuelve []."""
    ruta = Path(*config.MODEL_PATH_PARTS)
    if config.DATA_DIR.resolve() != (config.ROOT / "data").resolve():
        return []
    rel = (Path("data") / ruta).as_posix()
    try:
        log = subprocess.run(["git", "log", "--format=%H", "--", rel], cwd=config.ROOT,
                             capture_output=True, text=True, timeout=30, check=True).stdout.split()
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for h in log:
        try:
            texto = subprocess.run(["git", "show", f"{h}:{rel}"], cwd=config.ROOT, capture_output=True,
                                   text=True, timeout=30, check=True, encoding="utf-8").stdout
            data = json.loads(texto)
            out.append((parse_ts(data["trained_utc"]), _modelos_desde_json(texto)))
        except (OSError, subprocess.SubprocessError, ValueError, KeyError):
            continue
    return sorted(out, key=lambda x: x[0])


def modelo_vigente(ruta: str, t: datetime, historial) -> model.RouteModel:
    """El modelo que estaba en uso en `t` (si todavía no había ninguno: la regla base)."""
    vigente = None
    for fecha, modelos in historial:
        if fecha <= t and ruta in modelos:
            vigente = modelos[ruta]
    return vigente or model.RouteModel(reason="regla base", route=ruta)


# ------------------------------------------------------------------ datos

def observaciones(ruta: str) -> list[Observacion]:
    cfg = config.ROUTES[ruta]
    out = []
    if cfg.get("tabsa"):
        for r in storage.read_rows(storage.TABSA_STATE):
            if r["crossing"] == cfg["tabsa"] and r["status"]:
                out.append(Observacion(ruta, parse_ts(r["ts_utc"]), r["status"], model.is_disrupted(r["status"]), r["ts_utc"]))
    if cfg.get("scheduled"):
        # Cada zarpe se cuenta UNA vez: la lectura más cercana a su hora de salida (±1 h).
        mejores: dict[tuple, tuple[timedelta, Observacion]] = {}
        for r in storage.read_rows(storage.TABSA_SAILINGS):
            if not r["status"] or not model.is_route_sailing(r, ruta):
                continue
            try:
                sale = local_to_utc(r["date"], r["departure"])
            except ValueError:
                continue
            visto = parse_ts(r["ts_utc"])
            dist = abs(visto - sale)
            if dist > model.SAILING_WINDOW:
                continue
            clave = (r["date"], r["departure"], r["origin"])
            if clave not in mejores or dist < mejores[clave][0]:
                mejores[clave] = (dist, Observacion(ruta, sale, r["status"], model.is_disrupted(r["status"]), r["ts_utc"]))
        out.extend(o for _, o in mejores.values())
    return sorted(out, key=lambda o: o.t)


class Clima:
    """Clima medido por corrida, para buscar el más cercano a un momento."""

    def __init__(self):
        corridas: dict[str, dict[str, dict]] = {}
        for r in storage.read_rows(storage.WEATHER):
            corridas.setdefault(r["ts_utc"], {})[r["place"]] = r
        self.ts = sorted(corridas)
        self.tiempos = [parse_ts(t) for t in self.ts]
        self.corridas = corridas

    def cerca(self, t: datetime, lugares) -> list[float] | None:
        i = bisect.bisect_left(self.tiempos, t)
        candidatos = [j for j in (i - 1, i) if 0 <= j < len(self.tiempos)]
        candidatos.sort(key=lambda j: abs(self.tiempos[j] - t))
        for j in candidatos:
            if abs(self.tiempos[j] - t) <= TOLERANCIA_CLIMA:
                x = model.route_vector(self.corridas[self.ts[j]], lugares)
                if x:
                    return x
        return None


class Pronosticos:
    """Pronósticos guardados (tal como estaban en cada corrida)."""

    def __init__(self):
        self.por_emision: dict[datetime, dict[str, dict[datetime, dict]]] = {}
        for r in storage.read_rows(storage.FORECAST_SNAPSHOTS):
            if not r.get("gust_kmh"):
                continue
            e = parse_ts(r["issued_utc"])
            self.por_emision.setdefault(e, {}).setdefault(r["place"], {})[parse_ts(r["valid_utc"])] = r
        self.emisiones = sorted(self.por_emision)

    def para(self, t: datetime, anticipacion_h: float, lugares) -> tuple[datetime, list[float]] | None:
        """Lo que decía el pronóstico emitido `anticipacion_h` horas antes de `t`, para la hora de `t`."""
        limite = t - timedelta(hours=anticipacion_h)
        i = bisect.bisect_right(self.emisiones, limite) - 1
        if i < 0 or limite - self.emisiones[i] > TOLERANCIA_EMISION:
            return None
        emision = self.emisiones[i]
        hora = t.replace(minute=0, second=0, microsecond=0) + (timedelta(hours=1) if t.minute >= 30 else timedelta(0))
        filas = {}
        for lugar in lugares:
            fila = self.por_emision[emision].get(lugar, {}).get(hora)
            if fila:
                filas[lugar] = {"gust_kmh": fila["gust_kmh"], "wind_kmh": fila["wind_kmh"], "wind_dir_deg": fila["wind_dir_deg"]}
        x = model.route_vector(filas, [lg for lg in lugares if lg in filas])
        return (emision, x) if x else None


# ------------------------------------------------------------------ evaluación

def evaluar(desde: datetime | None = None, historial=None) -> dict:
    historial = historial_modelos() if historial is None else historial
    clima, pron = Clima(), Pronosticos()
    resultado = {}
    for ruta in config.ROUTES:
        lugares = config.ROUTES[ruta]["places"]
        obs = [o for o in observaciones(ruta) if not desde or o.t >= desde]
        filas = []
        for o in obs:
            fila = {"ruta": ruta, "t": o.t, "estado": o.estado, "y": o.y}
            x = clima.cerca(o.t, lugares)
            if x:
                fila["p0"] = modelo_vigente(ruta, o.t, historial).predict_vector(x)
                fila["rafaga0"] = x[0]
            for a in ANTICIPACIONES_H[1:]:
                r = pron.para(o.t, a, lugares)
                if r:
                    emision, xa = r
                    fila[f"p{a}"] = modelo_vigente(ruta, emision, historial).predict_vector(xa)
                    fila[f"rafaga{a}"] = xa[0]
            filas.append(fila)
        resultado[ruta] = {"filas": filas, "metricas": {a: metricas(filas, f"p{a}") for a in ANTICIPACIONES_H},
                           "episodios": episodios(filas)}
    return resultado


def metricas(filas: list[dict], col: str) -> dict:
    pares = [(f[col], f["y"]) for f in filas if f.get(col) is not None]
    n = len(pares)
    pos = sum(y for _, y in pares)
    if not n:
        return {"n": 0}
    base = pos / n
    brier = sum((p - y) ** 2 for p, y in pares) / n
    brier_ref = sum((base - y) ** 2 for _, y in pares) / n
    sus = [p for p, y in pares if y]
    nor = [p for p, y in pares if not y]
    return {
        "n": n, "suspensiones": pos, "brier": brier, "brier_referencia": brier_ref,
        "detectadas_50": sum(p >= 0.5 for p in sus), "detectadas_20": sum(p >= 0.2 for p in sus),
        "falsas_alarmas_50": sum(p >= 0.5 for p in nor), "normales": len(nor),
        "prob_media_suspendido": sum(sus) / len(sus) if sus else None,
        "prob_media_normal": sum(nor) / len(nor) if nor else None,
    }


def episodios(filas: list[dict]) -> list[dict]:
    """Suspensiones seguidas = un episodio. Para cada uno: qué probabilidad dábamos al empezar."""
    out, actual = [], None
    for f in filas:
        if f["y"] and actual is None:
            actual = {"inicio": f["t"], "fin": f["t"], "estado": f["estado"],
                      **{f"p{a}": f.get(f"p{a}") for a in ANTICIPACIONES_H}, "rafaga0": f.get("rafaga0")}
        elif f["y"]:
            actual["fin"] = f["t"]
            if actual["p0"] is None and f.get("p0") is not None:
                actual["p0"], actual["rafaga0"] = f["p0"], f.get("rafaga0")
        elif actual is not None:
            actual["normal_desde"] = f["t"]
            out.append(actual)
            actual = None
    if actual is not None:
        out.append(actual)
    return out


# ------------------------------------------------------------------ informe

def _pct(p) -> str:
    return "—" if p is None else f"{round(p * 100)} %"


def texto(res: dict) -> str:
    nombres = {k: v["name"] for k, v in config.ROUTES.items()}
    L = ["CÓMO NOS FUE · predicción vs. lo que hizo TABSA", ""]
    for ruta, r in res.items():
        m0 = r["metricas"][0]
        L.append(f"■ {nombres[ruta]}")
        if not m0.get("n"):
            L += ["  Sin observaciones con clima todavía.", ""]
            continue
        L.append(f"  Observaciones: {m0['n']} · suspensiones: {m0['suspensiones']}")
        L.append("  Anticipación   n     Brier (ref.)       Detectadas ≥50% / ≥20%   Falsas alarmas ≥50%")
        for a in ANTICIPACIONES_H:
            m = r["metricas"][a]
            if not m.get("n"):
                L.append(f"  {a:>3} h         sin datos")
                continue
            det = (f"{m['detectadas_50']}/{m['suspensiones']} · {m['detectadas_20']}/{m['suspensiones']}"
                   if m["suspensiones"] else "— (no hubo)")
            ref = f"({m['brier_referencia']:.3f})" if m["suspensiones"] else "(no aplica)"
            L.append(f"  {a:>3} h       {m['n']:>4}   {m['brier']:.3f} {ref:<13}  "
                     f"{det:<24} {m['falsas_alarmas_50']}/{m['normales']}")
        if r["episodios"]:
            L.append("  Suspensiones y la probabilidad que dábamos:")
            for e in r["episodios"]:
                fin = e.get("normal_desde")
                dur = f"{fmt_local(e['inicio'])} → {fmt_local(fin) if fin else 'sigue'}"
                probs = " · ".join(f"{a} h antes: {_pct(e.get(f'p{a}'))}" if a else f"en el momento: {_pct(e.get('p0'))}"
                                   for a in ANTICIPACIONES_H)
                raf = f" (ráfaga medida {e['rafaga0']:.0f} km/h)" if e.get("rafaga0") is not None else ""
                L.append(f"   - {dur} {e['estado']}{raf}: {probs}")
        else:
            L.append("  No hubo suspensiones en el período: todavía no se puede medir si las anticipamos.")
        L.append("")
    L.append("Brier: 0 es perfecto; tiene que ser MENOR que la referencia (decir siempre el promedio).")
    L.append("Sin suspensiones la referencia no aplica (decir siempre 0 % sería 'perfecto').")
    L.append("Con anticipación solo se puede medir Primera Angostura (es el único cruce con pronóstico guardado).")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m corredor.evaluacion", description=__doc__.splitlines()[0])
    p.add_argument("--dias", type=float, help="solo los últimos N días")
    p.add_argument("--csv", help="guardar el detalle fila por fila en este archivo (p. ej. .cache/evaluacion.csv)")
    args = p.parse_args(argv)
    desde = datetime.now(timezone.utc) - timedelta(days=args.dias) if args.dias else None
    res = evaluar(desde)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    print(texto(res))
    if args.csv:
        cols = ["ruta", "t", "estado", "y"] + [f"{c}{a}" for a in ANTICIPACIONES_H for c in ("p", "rafaga")]
        path = Path(args.csv)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh, lineterminator="\n")
            w.writerow(cols)
            for r in res.values():
                for f in r["filas"]:
                    w.writerow([f["t"].strftime("%Y-%m-%dT%H:%M:%SZ") if c == "t" else
                                (round(f[c], 4) if isinstance(f.get(c), float) else f.get(c, "")) for c in cols])
        print(f"\nDetalle: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
