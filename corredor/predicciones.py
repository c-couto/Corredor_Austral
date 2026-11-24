"""Predicciones EMITIDAS en cada corrida (lo que mostraba la web en ese momento).

Se guardan en data/auto/predicciones/AAAA-MM.csv para poder medir después, sin trampas,
qué probabilidad dábamos con anticipación antes de cada suspensión o cancelación.

Usa exactamente el mismo cálculo que la web (conditions.snapshot), así lo guardado coincide
con lo que vio la gente. Por corrida y por cruce:
  tipo "ahora"  probabilidad con el viento medido en esta corrida (la del medidor de la tarjeta)
  tipo "hora"   pronóstico para algunas horas (1–6, 9, 12, 18, 24 y 36 h): 11 filas por cruce
  tipo "zarpe"  Punta Arenas–Porvenir: probabilidad para la hora de cada próximo zarpe
"""

from __future__ import annotations

from . import conditions
from .timeutil import format_ts, parse_ts

ANTICIPACIONES_H = (1, 2, 3, 4, 5, 6, 9, 12, 18, 24, 36)  # el pronóstico cubre hasta +47 h


def _r(x, n=4):
    return None if x is None else round(x, n)


def _modelo(m) -> str:
    return f"aprendido {m.trained_utc}" if m.kind == "trained" else "regla base"


def filas(ts_utc: str, snap: conditions.Snapshot | None = None) -> list[dict]:
    """Filas a guardar para la corrida `ts_utc` (usa el pronóstico ya guardado; no sale a internet)."""
    emitido = parse_ts(ts_utc)
    snap = snap or conditions.snapshot(now=emitido, fetch_forecast=False)
    out: list[dict] = []
    for st in snap.routes:
        modelo = _modelo(st.model)
        if st.p_now is not None:
            out.append({"emitido_utc": ts_utc, "ruta": st.key, "tipo": "ahora", "valido_utc": ts_utc,
                        "anticipacion_h": 0, "prob": _r(st.p_now), "rafaga_kmh": _r(st.gust_kmh, 1),
                        "modelo": modelo, "detalle": ""})
        base = emitido.replace(minute=0, second=0, microsecond=0)
        for h in st.hours:
            lead = round((h.t - base).total_seconds() / 3600)
            if lead in ANTICIPACIONES_H:
                out.append({"emitido_utc": ts_utc, "ruta": st.key, "tipo": "hora", "valido_utc": format_ts(h.t),
                            "anticipacion_h": lead, "prob": _r(h.p), "rafaga_kmh": _r(h.gust, 1),
                            "modelo": modelo, "detalle": ""})
    pap = snap.route("punta_arenas_porvenir")
    for s in snap.sailings:
        if s.p is None:
            continue
        out.append({"emitido_utc": ts_utc, "ruta": "punta_arenas_porvenir", "tipo": "zarpe",
                    "valido_utc": format_ts(s.departure_utc),
                    "anticipacion_h": round((s.departure_utc - emitido).total_seconds() / 3600, 2),
                    "prob": _r(s.p), "rafaga_kmh": None, "modelo": _modelo(pap.model) if pap else "",
                    "detalle": f"{s.date} {s.departure} {s.origin} -> {s.destination}"})
    return out
