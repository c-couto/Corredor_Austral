"""Modelo de riesgo: probabilidad de que un cruce NO esté normal, aprendida de nuestros datos.

Cómo aprende (todo con Python puro, sin costo):
  - Cada lectura de TABSA es un ejemplo: viento en ese momento -> estado real.
      * Primera Angostura y Río Verde: tabla "Estado del cruce".
      * Punta Arenas ↔ Porvenir: estado de cada salida programada, observado
        dentro de la hora anterior o posterior a su horario.
  - Variables: ráfaga, viento medio y dirección del viento (seno y coseno).
  - Regresión logística con regularización (evita "memorizar" pocos casos).

Protecciones:
  - Mientras no haya datos suficientes (config.MODEL_MIN_*), se usa una regla
    base: una curva sobre la ráfaga (config.PRIOR_*).
  - El modelo aprendido solo reemplaza a la regla base si predice MEJOR que ella
    en datos que no usó para aprender (los más recientes), medido con el puntaje
    de Brier (error cuadrático de la probabilidad; más bajo es mejor).

Se reentrena una vez por día dentro del workflow y se guarda en data/model/modelo.json.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config, storage
from .sources import num
from .timeutil import format_ts, local_to_utc, parse_ts

FEATURES = ("rafaga_kmh", "viento_kmh", "dir_seno", "dir_coseno")
SAILING_WINDOW = timedelta(hours=1)


# ------------------------------------------------------------------ utilidades

def sigmoid(z: float) -> float:
    if z >= 0:
        return 1 / (1 + math.exp(-z))
    e = math.exp(z)
    return e / (1 + e)


def level_for_prob(p: float | None) -> str | None:
    if p is None:
        return None
    for limit, name in config.RISK_LEVELS:
        if p >= limit:
            return name
    return "bajo"


def prior_probability(gust_kmh: float | None) -> float | None:
    if gust_kmh is None:
        return None
    return sigmoid((gust_kmh - config.PRIOR_CENTER_KMH) / config.PRIOR_SCALE_KMH)


def vector(gust: float, wind: float | None, dir_deg: float | None) -> list[float]:
    wind = wind if wind is not None else gust * 0.6
    if dir_deg is None:
        s = c = 0.0
    else:
        s, c = math.sin(math.radians(dir_deg)), math.cos(math.radians(dir_deg))
    return [gust, wind, s, c]


def is_disrupted(status: str) -> int:
    """1 si el estado NO es normal (suspendido, cerrado, demorado...), 0 si es normal."""
    return 0 if status.strip().upper() == "NORMAL" else 1


def model_path() -> Path:
    return config.DATA_DIR.joinpath(*config.MODEL_PATH_PARTS)


# ------------------------------------------------------------------ modelo

@dataclass
class RouteModel:
    kind: str = "prior"                 # "prior" (regla base) | "trained" (aprendido)
    weights: list[float] = field(default_factory=list)
    bias: float = 0.0
    means: list[float] = field(default_factory=list)
    stds: list[float] = field(default_factory=list)
    n_samples: int = 0
    n_positive: int = 0
    trained_utc: str = ""
    reason: str = ""                    # por qué se usa este modelo (se muestra en la web)
    metrics: dict = field(default_factory=dict)

    def predict(self, gust: float | None, wind: float | None = None, dir_deg: float | None = None) -> float | None:
        if gust is None:
            return None
        return self.predict_vector(vector(gust, wind, dir_deg))

    def predict_vector(self, x: list[float]) -> float:
        if self.kind != "trained":
            return prior_probability(x[0])
        z = self.bias + sum(w * (xi - m) / s for w, xi, m, s in zip(self.weights, x, self.means, self.stds))
        return sigmoid(z)


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Resuelve a·x = b (eliminación gaussiana con pivoteo; matrices chicas)."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[piv] = m[piv], m[col]
        if abs(m[col][col]) < 1e-12:
            raise ArithmeticError("sistema singular")
        for r in range(col + 1, n):
            f = m[r][col] / m[col][col]
            for c in range(col, n + 1):
                m[r][c] -= f * m[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][c] * x[c] for c in range(r + 1, n))) / m[r][r]
    return x


def _fit(xs: list[list[float]], ys: list[int], l2: float = 0.01, iters: int = 25):
    """Regresión logística regularizada por el método de Newton (converge en ~10 pasos)."""
    n, k = len(xs), len(xs[0])
    means = [sum(x[j] for x in xs) / n for j in range(k)]
    stds = [math.sqrt(sum((x[j] - means[j]) ** 2 for x in xs) / n) or 1.0 for j in range(k)]
    zs = [[1.0] + [(x[j] - means[j]) / stds[j] for j in range(k)] for x in xs]  # 1.0 = término fijo
    lam = max(1.0, l2 * n)  # regularización (no se aplica al término fijo)
    beta = [0.0] * (k + 1)
    for _ in range(iters):
        grad = [0.0] * (k + 1)
        hess = [[0.0] * (k + 1) for _ in range(k + 1)]
        for z, y in zip(zs, ys):
            p = sigmoid(sum(bj * zj for bj, zj in zip(beta, z)))
            wgt, err = p * (1 - p), p - y
            for i in range(k + 1):
                grad[i] += err * z[i]
                for j in range(i, k + 1):
                    hess[i][j] += wgt * z[i] * z[j]
        for i in range(k + 1):
            for j in range(i):
                hess[i][j] = hess[j][i]
            if i:
                grad[i] += lam * beta[i]
                hess[i][i] += lam
        step = _solve(hess, grad)
        beta = [bj - sj for bj, sj in zip(beta, step)]
        if max(abs(s) for s in step) < 1e-6:
            break
    return beta[1:], beta[0], means, stds


def brier(probs: list[float], ys: list[int]) -> float:
    return sum((p - y) ** 2 for p, y in zip(probs, ys)) / len(ys)


def auc(probs: list[float], ys: list[int]) -> float | None:
    """Probabilidad de que un caso suspendido tenga más riesgo que uno normal."""
    pos = [p for p, y in zip(probs, ys) if y]
    neg = [p for p, y in zip(probs, ys) if not y]
    if not pos or not neg:
        return None
    wins = sum(1.0 if p > q else 0.5 if p == q else 0.0 for p in pos for q in neg)
    return wins / (len(pos) * len(neg))


def train(samples: list[tuple[datetime, list[float], int]], now: datetime | None = None) -> RouteModel:
    """Entrena con [(hora, variables, 1 si no normal)] y decide si supera a la regla base."""
    now = now or datetime.now(timezone.utc)
    samples = sorted(samples, key=lambda s: s[0])
    n, pos = len(samples), sum(y for _, _, y in samples)
    base = dict(n_samples=n, n_positive=pos, trained_utc=format_ts(now))
    if n < config.MODEL_MIN_SAMPLES or pos < config.MODEL_MIN_POSITIVES or pos == n:
        return RouteModel(kind="prior", **base, reason=(
            f"Regla base: hacen falta al menos {config.MODEL_MIN_SAMPLES} muestras y "
            f"{config.MODEL_MIN_POSITIVES} suspensiones registradas (hay {n} y {pos})."))

    # Validación: aprende con el 80 % más viejo y se mide con el 20 % más reciente.
    cut = int(n * 0.8)
    train_s, test_s = samples[:cut], samples[cut:]
    test_ok = sum(y for _, _, y in test_s) >= 2 and sum(1 - y for _, _, y in test_s) >= 2 \
        and 0 < sum(y for _, _, y in train_s) < len(train_s)
    eval_s = test_s if test_ok else samples
    fit_s = train_s if test_ok else samples
    w, b, m, s = _fit([x for _, x, _ in fit_s], [y for _, _, y in fit_s])
    trial = RouteModel(kind="trained", weights=w, bias=b, means=m, stds=s)
    ys = [y for _, _, y in eval_s]
    p_model = [trial.predict_vector(x) for _, x, _ in eval_s]
    p_prior = [prior_probability(x[0]) for _, x, _ in eval_s]
    metrics = {
        "evaluado_en": "datos nuevos (20 % más reciente)" if test_ok else "los mismos datos (todavía no hay suficientes para separar)",
        "brier_modelo": round(brier(p_model, ys), 4),
        "brier_regla_base": round(brier(p_prior, ys), 4),
        "auc_modelo": None if auc(p_model, ys) is None else round(auc(p_model, ys), 3),
    }
    if metrics["brier_modelo"] > metrics["brier_regla_base"]:
        return RouteModel(kind="prior", **base, metrics=metrics,
                          reason="Regla base: el modelo aprendido todavía no predice mejor que ella.")

    w, b, m, s = _fit([x for _, x, _ in samples], [y for _, _, y in samples])  # final, con todo
    return RouteModel(kind="trained", weights=w, bias=b, means=m, stds=s, **base, metrics=metrics,
                      reason=f"Aprendido de {n} muestras con {pos} casos no normales.")


# ------------------------------------------------------------------ datos de entrenamiento

def _weather_runs() -> dict[str, dict[str, dict]]:
    runs: dict[str, dict[str, dict]] = {}
    for r in storage.read_rows(storage.WEATHER):
        runs.setdefault(r["ts_utc"], {})[r["place"]] = r
    return runs


def route_vector(by_place: dict[str, dict], places) -> list[float] | None:
    rows = [by_place[p] for p in places if p in by_place]
    gusts = [g for g in (num(r["gust_kmh"]) for r in rows) if g is not None]
    if not gusts:
        return None
    winds = [w for w in (num(r["wind_kmh"]) for r in rows) if w is not None]
    return vector(max(gusts), max(winds) if winds else None, num(rows[0]["wind_dir_deg"]))


def samples_for(route_key: str) -> list[tuple[datetime, list[float], int]]:
    route = config.ROUTES[route_key]
    runs = _weather_runs()
    out = []
    if route.get("tabsa"):
        for r in storage.read_rows(storage.TABSA_STATE):
            if r["crossing"] == route["tabsa"] and r["status"] and r["ts_utc"] in runs:
                x = route_vector(runs[r["ts_utc"]], route["places"])
                if x:
                    out.append((parse_ts(r["ts_utc"]), x, is_disrupted(r["status"])))
    if route.get("scheduled"):
        for r in storage.read_rows(storage.TABSA_SAILINGS):
            if not r["status"] or r["ts_utc"] not in runs:
                continue
            ts = parse_ts(r["ts_utc"])
            if abs(ts - local_to_utc(r["date"], r["departure"])) <= SAILING_WINDOW:
                x = route_vector(runs[r["ts_utc"]], route["places"])
                if x:
                    out.append((ts, x, is_disrupted(r["status"])))
    return out


# ------------------------------------------------------------------ guardar / cargar

def train_all(now: datetime | None = None) -> dict[str, RouteModel]:
    models = {key: train(samples_for(key), now) for key in config.ROUTES}
    path = model_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"version": 1, "trained_utc": format_ts(now or datetime.now(timezone.utc)),
               "features": FEATURES, "routes": {k: asdict(m) for k, m in models.items()}}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    return models


def load() -> dict[str, RouteModel]:
    models = {key: RouteModel(reason="Regla base: todavía no se entrenó el modelo.") for key in config.ROUTES}
    path = model_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            for key, m in data.get("routes", {}).items():
                if key in models:
                    models[key] = RouteModel(**m)
        except (ValueError, TypeError) as e:
            print(f"[aviso] modelo ilegible, se usa la regla base: {e}")
    return models


def is_stale(now: datetime | None = None) -> bool:
    """True si el modelo no se entrenó hoy (UTC)."""
    now = now or datetime.now(timezone.utc)
    path = model_path()
    if not path.exists():
        return True
    try:
        trained = parse_ts(json.loads(path.read_text(encoding="utf-8"))["trained_utc"])
    except (ValueError, KeyError):
        return True
    return trained.date() != now.date()
