"""Avisos: detecta cuándo cambia el riesgo de un cruce y lo comunica.

Compara la última corrida con la anterior. Solo avisa si la última corrida es
reciente (la acaba de hacer el workflow): así, si una recolección falla, no se
repite el aviso viejo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import config, storage
from .channels import telegram
from .conditions import LEVEL_EMOJI, group_runs, route_status_at, snapshot, summary_text

RECENT = timedelta(minutes=20)


def changes(now: datetime | None = None) -> list[tuple[str, str | None, str | None]]:
    """[(nombre del cruce, nivel anterior, nivel nuevo)] para los cruces que cambiaron."""
    now = now or datetime.now(timezone.utc)
    runs = group_runs(storage.read_rows(storage.WEATHER))
    marine = dict(group_runs(storage.read_rows(storage.MARINE)))
    out = []
    for key in config.ROUTES:
        new = route_status_at(key, runs, marine, -1)
        old = route_status_at(key, runs, marine, -2)
        if new.ts is None or old.ts is None or new.ts == old.ts or now - new.ts > RECENT:
            continue
        if new.level != old.level:
            out.append((new.name, old.level, new.level))
    return out


def change_message(changed: list[tuple[str, str | None, str | None]]) -> str:
    lines = ["Cambio de riesgo por viento:"]
    for name, old, new in changed:
        lines.append(f"{LEVEL_EMOJI[new]} {name}: {old or 's/d'} → {new or 's/d'}")
    return "\n".join(lines) + "\n\n" + summary_text(snapshot())


def notify(force: bool = False) -> str:
    """Envía el aviso si hubo cambios (o siempre, con force). Devuelve qué hizo."""
    changed = changes()
    if not changed and not force:
        return "Sin cambios de riesgo: no se envía nada."
    text = change_message(changed) if changed else summary_text(snapshot())
    sent = telegram.send(text)
    return ("Enviado por Telegram:\n" if sent else "No enviado (Telegram sin configurar). Mensaje:\n") + text
