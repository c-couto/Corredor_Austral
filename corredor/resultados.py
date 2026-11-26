"""Cómo nos fue: lo que PREDIJIMOS (data/auto/predicciones/) contra lo que hizo TABSA.

Para cada cruce y para cada anticipación (3, 12 y 24 horas) se toma la predicción que ya
estaba guardada ANTES de la hora, se la compara con el estado oficial de TABSA en esa hora, y se
calcula cuántas suspensiones detectamos, cuántas falsas alarmas dimos y qué error tuvimos frente a
dos comparaciones simples:

  - "Sigue igual" (persistencia): decir que el cruce va a estar como estaba cuando hicimos la
    predicción. Si no le ganamos a esto, el modelo no aporta.
  - Regla base: la curva sobre la ráfaga que se usa mientras no hay datos para aprender.
    Mientras el modelo usa la regla base, la nuestra ES la regla base (se marca como igual).

Solo LEE datos: no escribe nada en data/. No usa datos del futuro: cada predicción es la guardada
en su momento.

    python -m corredor.resultados                    # todo el período
    python -m corredor.resultados --dia 2026-11-26   # un día completo (hora local)
"""

from __future__ import annotations

import argparse
import bisect
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from . import config, evaluacion, model, storage
from .timeutil import parse_ts, to_local

ANTICIPACIONES_H = (3, 12, 24)
ALARMA = 0.5                          # "Probable suspensión" en la web
TOL_OBS = timedelta(minutes=20)       # una lectura de TABSA cuenta para la hora si está a menos de esto
TOL_ZARPE_H = 0.75                    # un zarpe usa la predicción emitida a esta cercanía de la anticipación pedida
MIN_SUSPENSIONES = 3                  # con menos casos no se saca conclusión


@dataclass
class Celda:
    """Resultado de un grupo de predicciones (todo el período, o un día)."""
    n: int = 0              # predicciones comparadas
    sus: int = 0            # de esas, cuántas veces TABSA tenía el cruce suspendido / cancelado
    detectadas: int = 0     # suspensiones a las que dimos ≥ 50 %
    falsas: int = 0         # momentos normales a los que dimos ≥ 50 %

    def sumar(self, p: float, y: int) -> None:
        self.n += 1
        self.sus += y
        if p >= ALARMA:
            if y:
                self.detectadas += 1
            else:
                self.falsas += 1

    @property
    def normales(self) -> int:
        return self.n - self.sus


@dataclass
class Resumen(Celda):
    # Error (Brier: 0 es perfecto) sobre las predicciones donde existen las tres comparaciones.
    n_comp: int = 0
    brier: float | None = None
    brier_igual: float | None = None      # "sigue igual"
    brier_base: float | None = None       # regla base
    nuestra_es_la_base: bool = True       # en todo el período usamos la regla base

    @property
    def mejor_que_igual(self) -> bool | None:
        if self.brier is None or self.brier_igual is None or self.sus < MIN_SUSPENSIONES:
            return None
        return self.brier < self.brier_igual


@dataclass
class Dia:
    dia: date
    celdas: dict[int, Celda] = field(default_factory=dict)   # anticipación -> Celda

    @property
    def sus(self) -> int:
        return max((c.sus for c in self.celdas.values()), default=0)


@dataclass
class RutaResultados:
    key: str
    name: str
    unidad: str                                   # "horas" (cruces con estado) o "zarpes"
    resumen: dict[int, Resumen] = field(default_factory=dict)
    dias: list[Dia] = field(default_factory=list)  # del más viejo al más nuevo


# ------------------------------------------------------------------ armado de las parejas

@dataclass
class Par:
    ruta: str
    valido: datetime
    a: int
    p: float
    y: int
    p_igual: float | None
    p_base: float | None
    modelo_base: bool


def _prior(ruta: str, rafaga: float | None) -> float | None:
    return model.prior_probability(rafaga, ruta)


def _filas_por_valido(rows: list[dict], ruta: str, tipo: str):
    """Para cada (hora de validez, anticipación pedida) deja UNA predicción: la emitida a la
    anticipación más parecida (hay una cada 30 min, así que sobra una de las dos)."""
    mejores: dict[tuple[datetime, int], tuple[float, dict, datetime, datetime]] = {}
    for r in rows:
        if r["ruta"] != ruta or r["tipo"] != tipo or not r["prob"]:
            continue
        emitido, valido = parse_ts(r["emitido_utc"]), parse_ts(r["valido_utc"])
        lead = (valido - emitido).total_seconds() / 3600
        for a in ANTICIPACIONES_H:
            if tipo == "hora":
                if r["anticipacion_h"] != str(a):          # la anticipación "de etiqueta" que guardó el sistema
                    continue
            elif abs(lead - a) > TOL_ZARPE_H:
                continue
            dist = abs(lead - a)
            clave = (valido, a)
            if clave not in mejores or dist < mejores[clave][0]:
                mejores[clave] = (dist, r, emitido, valido)
    return mejores


def _nearest(obs: list, t: datetime):
    """Observación (t, y) más cercana a `t` y a menos de TOL_OBS, o None. `obs` va ordenada por t."""
    i = bisect.bisect_left([o.t for o in obs], t)
    cands = obs[max(0, i - 1):i + 1]
    best = min(cands, key=lambda o: abs(o.t - t), default=None)
    return best if best is not None and abs(best.t - t) <= TOL_OBS else None


def parejas(now: datetime, pred_rows: list[dict] | None = None) -> list[Par]:
    rows = storage.read_rows(storage.PREDICTIONS) if pred_rows is None else pred_rows
    out: list[Par] = []
    for ruta, cfg in config.ROUTES.items():
        obs = evaluacion.observaciones(ruta)
        if not obs:
            continue
        if cfg.get("scheduled"):
            por_t = defaultdict(list)
            for o in obs:
                por_t[o.t].append(o)
            for (valido, a), (_, r, emitido, _v) in _filas_por_valido(rows, ruta, "zarpe").items():
                if valido > now or valido not in por_t:
                    continue
                o = por_t[valido][0]
                previos = [x for x in obs if x.t <= emitido and emitido - x.t <= timedelta(hours=24)]
                p_igual = float(previos[-1].y) if previos else None
                out.append(_par(ruta, valido, a, r, o.y, p_igual, rafaga=None))
        else:
            for (valido, a), (_, r, emitido, _v) in _filas_por_valido(rows, ruta, "hora").items():
                if valido > now:
                    continue
                o = _nearest(obs, valido)
                if o is None:
                    continue
                antes = _nearest(obs, emitido)
                p_igual = float(antes.y) if antes else None
                rafaga = float(r["rafaga_kmh"]) if r["rafaga_kmh"] else None
                out.append(_par(ruta, valido, a, r, o.y, p_igual, rafaga))
    return out


def _par(ruta, valido, a, r, y, p_igual, rafaga) -> Par:
    base_regla = r["modelo"] == "regla base"
    p = float(r["prob"])
    # Con la regla base vigente, la nuestra ES la regla base; si el modelo era aprendido, se recalcula.
    p_base = p if base_regla else _prior(ruta, rafaga)
    return Par(ruta, valido, a, p, int(y), p_igual, p_base, base_regla)


# ------------------------------------------------------------------ resultados

def calcular(now: datetime | None = None, pred_rows: list[dict] | None = None,
             desde: date | None = None, hasta: date | None = None) -> list[RutaResultados]:
    """Resultados por cruce. `desde` / `hasta`: días LOCALES (incluidos) a considerar."""
    now = now or datetime.now(timezone.utc)
    todas = parejas(now, pred_rows)
    resultado = []
    for ruta, cfg in config.ROUTES.items():
        mias = [p for p in todas if p.ruta == ruta
                and (desde is None or to_local(p.valido).date() >= desde)
                and (hasta is None or to_local(p.valido).date() <= hasta)]
        rr = RutaResultados(ruta, cfg["name"], "zarpes" if cfg.get("scheduled") else "horas")
        if not mias:
            resultado.append(rr)
            continue
        for a in ANTICIPACIONES_H:
            ps = [p for p in mias if p.a == a]
            res = Resumen()
            for p in ps:
                res.sumar(p.p, p.y)
            comp = [p for p in ps if p.p_igual is not None and p.p_base is not None]
            res.n_comp = len(comp)
            if comp:
                res.brier = sum((p.p - p.y) ** 2 for p in comp) / len(comp)
                res.brier_igual = sum((p.p_igual - p.y) ** 2 for p in comp) / len(comp)
                res.brier_base = sum((p.p_base - p.y) ** 2 for p in comp) / len(comp)
            res.nuestra_es_la_base = all(p.modelo_base for p in ps)
            rr.resumen[a] = res
        por_dia: dict[date, Dia] = {}
        for p in mias:
            d = to_local(p.valido).date()
            dia = por_dia.setdefault(d, Dia(d))
            dia.celdas.setdefault(p.a, Celda()).sumar(p.p, p.y)
        rr.dias = [por_dia[d] for d in sorted(por_dia)]
        resultado.append(rr)
    return resultado


# ------------------------------------------------------------------ informe de texto

def _pct(x) -> str:
    return "—" if x is None else f"{x:.3f}"


def texto(res: list[RutaResultados]) -> str:
    L = ["CÓMO NOS FUE · lo que predijimos vs. lo que hizo TABSA", ""]
    for r in res:
        L.append(f"■ {r.name} (unidad: {r.unidad})")
        if not r.resumen:
            L += ["  Todavía no hay predicciones comparables.", ""]
            continue
        L.append("  Antic.  n    susp.  detectadas  falsas alarmas   error nuestro / sigue igual / regla base")
        for a, s in r.resumen.items():
            L.append(f"  {a:>3} h  {s.n:>4} {s.sus:>5}  {s.detectadas:>4}/{s.sus:<5}  {s.falsas:>4}/{s.normales:<9}"
                     f"  {_pct(s.brier)} / {_pct(s.brier_igual)} / {_pct(s.brier_base)}  (n={s.n_comp})")
        L.append("  Por día:")
        for d in r.dias:
            celdas = " · ".join(f"{a} h: {c.detectadas}/{c.sus} det., {c.falsas} falsas"
                                for a, c in sorted(d.celdas.items()))
            L.append(f"   {d.dia.strftime('%d/%m')}  {celdas}")
        L.append("")
    L.append("Error (Brier): 0 es perfecto; menor es mejor. 'Sigue igual' = decir que el cruce va a estar como estaba.")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m corredor.resultados", description=__doc__.splitlines()[0])
    p.add_argument("--dia", help="solo este día completo, en hora local (AAAA-MM-DD)")
    args = p.parse_args(argv)
    dia = date.fromisoformat(args.dia) if args.dia else None
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    print(texto(calcular(desde=dia, hasta=dia)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
