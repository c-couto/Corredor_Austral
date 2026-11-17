"""Horas: todo se guarda en UTC y se pasa a hora local (UTC-3) solo para mostrar."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import config

TS_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def local_tz() -> timezone:
    return timezone(timedelta(hours=config.LOCAL_UTC_OFFSET_H))


def parse_ts(value: str) -> datetime:
    """'2026-11-17T20:29:16Z' -> datetime en UTC (compatible con Python 3.10)."""
    return datetime.strptime(value, TS_FORMAT).replace(tzinfo=timezone.utc)


def format_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime(TS_FORMAT)


def to_local(dt: datetime) -> datetime:
    return dt.astimezone(local_tz())


def fmt_local(dt: datetime, fmt: str = "%d/%m %H:%M") -> str:
    return to_local(dt).strftime(fmt)


def local_to_utc(date_iso: str, hhmm: str) -> datetime:
    """Fecha 'AAAA-MM-DD' + hora 'HH:MM' en hora local -> datetime en UTC."""
    naive = datetime.strptime(f"{date_iso} {hhmm}", "%Y-%m-%d %H:%M")
    return naive.replace(tzinfo=local_tz()).astimezone(timezone.utc)
