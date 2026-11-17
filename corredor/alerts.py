"""Avisos: qué cambió en la última corrida y cómo comunicarlo.

Dos tipos de aviso:
  1. Oficial (lo más valioso): TABSA cambió el estado de un cruce o de una salida
     programada (sale de tabsa_cambios.csv).
  2. Anticipo: el riesgo estimado por viento cambió de nivel (bajo/medio/alto).

Solo se avisa lo que detectó la corrida recién hecha (últimos 20 minutos): así,
si una recolección falla, no se repite un aviso viejo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import config, model, storage
from .channels import telegram
from .conditions import LEVEL_EMOJI, OFFICIAL_EMOJI, group_runs, is_normal, route_probability_at, snapshot, summary_text
from .timeutil import parse_ts

RECENT = timedelta(minutes=20)


def official_changes(now: datetime | None = None) -> list[dict]:
    """Cambios de estado de TABSA detectados en la última lectura (si es reciente)."""
    now = now or datetime.now(timezone.utc)
    rows = storage.read_rows(storage.TABSA_CHANGES)
    if not rows:
        return []
    last_ts = rows[-1]["ts_utc"]
    if now - parse_ts(last_ts) > RECENT:
        return []
    return [r for r in rows if r["ts_utc"] == last_ts and r["previous"]]  # sin "primera vez que se ve"


def risk_changes(now: datetime | None = None) -> list[tuple[str, str | None, str | None]]:
    """[(cruce, nivel anterior, nivel nuevo)] entre las dos últimas corridas de clima."""
    now = now or datetime.now(timezone.utc)
    runs = group_runs(storage.read_rows(storage.WEATHER))
    models = model.load()
    out = []
    for key, cfg in config.ROUTES.items():
        r_runs = [(ts, bp) for ts, bp in runs if any(p in bp for p in cfg["places"])]
        if len(r_runs) < 2 or now - parse_ts(r_runs[-1][0]) > RECENT:
            continue
        new = model.level_for_prob(route_probability_at(key, r_runs[-1][1], models[key]))
        old = model.level_for_prob(route_probability_at(key, r_runs[-2][1], models[key]))
        if new != old:
            out.append((cfg["name"], old, new))
    return out


def _subject_name(subject: str) -> str:
    for cfg in config.ROUTES.values():
        if cfg.get("tabsa") == subject:
            return cfg["name"]
    return f"Salida {subject}"  # salidas programadas: "AAAA-MM-DD HH:MM Origen -> Destino"


def change_message(official: list[dict], risk: list[tuple[str, str | None, str | None]]) -> str:
    lines = []
    if official:
        lines.append("📢 Cambio de estado oficial (TABSA):")
        for r in official:
            lines.append(f"{OFFICIAL_EMOJI[is_normal(r['current'])]} {_subject_name(r['subject'])}: "
                         f"{r['previous']} → {r['current']}")
    if risk:
        if lines:
            lines.append("")
        lines.append("🌬️ Cambio de riesgo por viento (estimado):")
        for name, old, new in risk:
            lines.append(f"{LEVEL_EMOJI[new]} {name}: {old or 's/d'} → {new or 's/d'}")
    return "\n".join(lines) + "\n\n" + summary_text(snapshot())


def notify(force: bool = False) -> str:
    """Envía el aviso si hubo cambios (o siempre, con force). Devuelve qué hizo."""
    official, risk = official_changes(), risk_changes()
    if not (official or risk) and not force:
        return "Sin cambios: no se envía nada."
    text = change_message(official, risk) if (official or risk) else summary_text(snapshot())
    sent = telegram.send(text)
    return ("Enviado por Telegram:\n" if sent else "No enviado (Telegram sin configurar). Mensaje:\n") + text
