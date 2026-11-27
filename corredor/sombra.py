"""Modelo EN SOMBRA: probar datos nuevos (marea y dirección del viento respecto del cruce) sin arriesgar nada.

Qué hace
  - Arma, para cada lectura de entrenamiento, los datos de siempre (ráfaga, viento, dirección) MÁS:
      * viento transversal y longitudinal al cruce: ráfaga × |sen| y × |cos| del ángulo entre de dónde
        viene el viento y el eje del cruce (el de los ferris en OpenStreetMap);
      * marea (solo Primera Angostura, el único lugar con nivel del mar guardado): nivel (m), cuánto
        sube o baja por hora (m/h) y su valor absoluto (la corriente es más fuerte a media marea).
  - Entrena con eso un modelo "sombra" y lo compara con la regla base y con el MISMO modelo sin los datos
    nuevos, en datos que no usó para aprender. Solo informa si mejora.

Qué NO hace
  - No se muestra en la web, no avisa por Telegram, no reemplaza ni cambia ninguna predicción.
  - No escribe nada en data/ (se calcula en memoria cada vez que se corre).
  - No se usa en la recolección ni en el entrenamiento diario.

Usa las mismas protecciones que el modelo real: nada hasta tener 8 suspensiones distintas y 60 muestras,
y la prueba con datos nuevos tiene que incluir al menos 2 temporales distintos.

    python -m corredor.sombra          # se imprime también al final de python -m corredor.evaluacion
"""

from __future__ import annotations

import bisect
import math
import sys
from datetime import datetime, timedelta

from . import config, model, storage
from .sources import num
from .timeutil import parse_ts

# Eje de cada cruce: (salida, llegada) = los extremos del camino de los ferris en OpenStreetMap
# (vías 49793837, 164993132 y 86335223; ver paginas/en-vivo/datos/). (lat, lon).
EJES: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {
    "primera_angostura": ((-52.4566991, -69.5457476), (-52.4945736, -69.5199923)),     # Punta Delgada → Bahía Azul
    "rio_verde": ((-52.654196, -71.4698616), (-52.6518224, -71.4638205)),               # Isla Riesco → Villa Ponsomby
    "punta_arenas_porvenir": ((-53.3046949, -70.4347761), (-53.1211734, -70.8667496)),  # Porvenir → Punta Arenas
}
# Lugar cuyo nivel del mar se usa como marea del cruce (solo está guardado en SNAPSHOT_PLACES).
LUGAR_MAREA: dict[str, str] = {"primera_angostura": "punta_delgada"}
TOLERANCIA_EMISION = timedelta(hours=2)   # el pronóstico de marea no puede ser más viejo que esto

FEATURES_VIENTO = ("rafaga_transversal", "rafaga_longitudinal")
FEATURES_MAREA = ("marea_nivel_m", "marea_tasa_m_h", "marea_tasa_abs")


def rumbo(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Rumbo (grados, 0 = norte) de a hacia b."""
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    y = math.sin(lo2 - lo1) * math.cos(la2)
    x = math.cos(la1) * math.sin(la2) - math.sin(la1) * math.cos(la2) * math.cos(lo2 - lo1)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def eje_grados(ruta: str) -> float:
    a, b = EJES[ruta]
    return rumbo(a, b)


def viento_respecto_del_eje(rafaga: float, dir_deg: float | None, eje: float) -> tuple[float, float]:
    """(transversal, longitudinal) en km/h: ráfaga × |sen| y × |cos| del ángulo viento–eje."""
    if dir_deg is None:
        return 0.0, 0.0
    ang = math.radians(dir_deg - eje)
    return rafaga * abs(math.sin(ang)), rafaga * abs(math.cos(ang))


class Mareas:
    """Nivel del mar (m) tal como lo pronosticaba la última corrida anterior a cada momento."""

    def __init__(self, rows: list[dict] | None = None):
        rows = storage.read_rows(storage.FORECAST_SNAPSHOTS) if rows is None else rows
        por_lugar: dict[str, dict[datetime, dict[datetime, float]]] = {}
        for r in rows:
            nivel = num(r.get("sea_level_m"))
            if nivel is None:
                continue
            por_lugar.setdefault(r["place"], {}).setdefault(parse_ts(r["issued_utc"]), {})[parse_ts(r["valid_utc"])] = nivel
        self.emisiones = {lugar: sorted(d) for lugar, d in por_lugar.items()}
        self.datos = por_lugar

    def en(self, lugar: str, t: datetime) -> tuple[float, float] | None:
        """(nivel en m, cambio por hora en m/h) en `t`, o None si no hay pronóstico de esa hora."""
        ems = self.emisiones.get(lugar)
        if not ems:
            return None
        i = bisect.bisect_right(ems, t) - 1
        if i < 0 or t - ems[i] > TOLERANCIA_EMISION:
            return None
        niveles = self.datos[lugar][ems[i]]
        h0 = t.replace(minute=0, second=0, microsecond=0)
        a, b = niveles.get(h0), niveles.get(h0 + timedelta(hours=1))
        if a is None or b is None:
            return None
        frac = (t - h0).total_seconds() / 3600
        return a + (b - a) * frac, b - a


def nombres_de_datos(ruta: str) -> tuple[str, ...]:
    extra = FEATURES_VIENTO + (FEATURES_MAREA if ruta in LUGAR_MAREA else ())
    return tuple(model.FEATURES) + extra


def extender(ruta: str, ts: datetime, x: list[float], mareas: Mareas | None) -> list[float] | None:
    """Vector de siempre (ráfaga, viento, sen, cos) + los datos nuevos. None si falta la marea."""
    sen, cos = x[2], x[3]
    dir_deg = None if (sen == 0 and cos == 0) else (math.degrees(math.atan2(sen, cos)) + 360) % 360
    trans, long_ = viento_respecto_del_eje(x[0], dir_deg, eje_grados(ruta))
    out = list(x) + [trans, long_]
    if ruta in LUGAR_MAREA:
        m = mareas.en(LUGAR_MAREA[ruta], ts) if mareas else None
        if m is None:
            return None
        out += [m[0], m[1], abs(m[1])]
    return out


def muestras(ruta: str, mareas: Mareas | None = None) -> list[tuple[datetime, list[float], int]]:
    """Las mismas lecturas del modelo real, con los datos nuevos agregados (se descartan las sin marea)."""
    mareas = mareas or (Mareas() if ruta in LUGAR_MAREA else None)
    out = []
    for ts, x, y in model.samples_for(ruta):
        e = extender(ruta, ts, x, mareas)
        if e is not None:
            out.append((ts, e, y))
    return out


# ------------------------------------------------------------------ comparación

def _entrenar(train: list, cols: int, ruta: str) -> model.RouteModel:
    w, b, m, s = model._fit([x[:cols] for _, x, _ in train], [y for _, _, y in train])
    return model.RouteModel(kind="trained", weights=w, bias=b, means=m, stds=s, route=ruta)


def comparar(ruta: str, mares: Mareas | None = None, eventos: int | None = None) -> dict:
    """Compara, en el 20 % más reciente: regla base · mismo modelo sin datos nuevos · modelo sombra."""
    datos = sorted(muestras(ruta, mares), key=lambda s: s[0])
    n = len(datos)
    ev = model.events_for(ruta) if eventos is None else eventos
    res = {"ruta": ruta, "muestras": n, "temporales": ev, "datos": nombres_de_datos(ruta)}
    if n < config.MODEL_MIN_SAMPLES or ev < config.MODEL_MIN_POSITIVES:
        res["veredicto"] = (f"todavía no se puede evaluar: hacen falta {config.MODEL_MIN_POSITIVES} "
                            f"suspensiones distintas y {config.MODEL_MIN_SAMPLES} muestras (hay {ev} y {n})")
        return res
    cut = int(n * 0.8)
    train, test = datos[:cut], datos[cut:]
    test_ev = model.distinct_events(test)
    if (test_ev < model.MIN_TEST_EVENTS or sum(1 - y for _, _, y in test) < 2
            or not 0 < sum(y for _, _, y in train) < len(train)):
        res["veredicto"] = (f"todavía no se puede evaluar: el 20 % más reciente necesita al menos "
                            f"{model.MIN_TEST_EVENTS} suspensiones distintas (tiene {test_ev})")
        return res
    ys = [y for _, _, y in test]
    base4 = _entrenar(train, len(model.FEATURES), ruta)
    sombra = _entrenar(train, len(datos[0][1]), ruta)
    b_regla = model.brier([model.prior_probability(x[0], ruta) for _, x, _ in test], ys)
    b_base4 = model.brier([base4.predict_vector(x[:len(model.FEATURES)]) for _, x, _ in test], ys)
    b_sombra = model.brier([sombra.predict_vector(x) for _, x, _ in test], ys)
    res.update(temporales_prueba=test_ev, brier_regla_base=b_regla, brier_mismo_modelo_sin_datos_nuevos=b_base4,
               brier_sombra=b_sombra)
    mejora = (1 - b_sombra / b_base4) * 100 if b_base4 else 0.0
    res["mejora_pct"] = mejora
    res["veredicto"] = (f"MEJORA {mejora:.0f} % el error frente al mismo modelo sin los datos nuevos"
                        if b_sombra < b_base4 else "no mejora: sigue igual o peor que el modelo sin los datos nuevos")
    return res


def exploracion(ruta: str, mares: Mareas | None = None) -> list[tuple[str, float, float, float]]:
    """Pista descriptiva (NO una conclusión): por dato, promedio con el cruce suspendido y con el cruce
    normal, y la diferencia en desvíos estándar. [(nombre, prom_suspendido, prom_normal, diferencia)]"""
    datos = muestras(ruta, mares)
    sus = [x for _, x, y in datos if y]
    nor = [x for _, x, y in datos if not y]
    if not sus or not nor:
        return []
    out = []
    for i, nombre in enumerate(nombres_de_datos(ruta)):
        if nombre in ("dir_seno", "dir_coseno"):
            continue
        todos = [x[i] for _, x, _ in datos]
        media = sum(todos) / len(todos)
        sd = math.sqrt(sum((v - media) ** 2 for v in todos) / len(todos)) or 1.0
        ms, mn = sum(x[i] for x in sus) / len(sus), sum(x[i] for x in nor) / len(nor)
        out.append((nombre, ms, mn, (ms - mn) / sd))
    return out


# ------------------------------------------------------------------ informe

def texto(rutas: list[str] | None = None) -> str:
    L = ["MODELO EN SOMBRA · solo informa; no se muestra ni cambia ninguna predicción", ""]
    mareas = Mareas()
    for ruta in rutas or list(config.ROUTES):
        c = comparar(ruta, mareas if ruta in LUGAR_MAREA else None)
        L.append(f"■ {config.ROUTES[ruta]['name']} · datos nuevos: "
                 f"{', '.join(c['datos'][len(model.FEATURES):])}  (eje {eje_grados(ruta):.0f}°)")
        L.append(f"  Muestras con todos los datos: {c['muestras']} · suspensiones distintas: {c['temporales']}")
        L.append(f"  Veredicto: {c['veredicto']}")
        if "brier_sombra" in c:
            L.append(f"  Error (Brier, menor es mejor) en datos nuevos: regla base {c['brier_regla_base']:.3f} · "
                     f"mismo modelo sin datos nuevos {c['brier_mismo_modelo_sin_datos_nuevos']:.3f} · "
                     f"sombra {c['brier_sombra']:.3f}")
        pistas = exploracion(ruta, mareas if ruta in LUGAR_MAREA else None)
        if pistas:
            L.append("  Pista (no es una conclusión): promedio con el cruce suspendido vs. normal "
                     "(diferencia en desvíos estándar)")
            for nombre, ms, mn, d in pistas:
                L.append(f"    {nombre:22} {ms:8.2f} vs {mn:8.2f}   ({d:+.2f})")
        L.append("")
    L.append("Con pocas suspensiones cualquier diferencia puede ser casualidad: no sacar conclusiones antes de tener 8.")
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    print(texto())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
