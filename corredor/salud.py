"""Salud del sistema: ¿está recolectando bien? Solo lee los datos, no escribe nada en data/.

    python -m corredor salud            # el informe
    python -m corredor salud --avisar   # además avisa al EQUIPO por Telegram si algo se puso mal

El aviso va a un chat aparte del de los usuarios (Secret TELEGRAM_TEAM_CHAT_ID). Para no mandar
el mismo aviso cada hora, solo se avisa lo que se puso mal DESDE la revisión anterior (se calcula
la misma salud una hora atrás con los datos que ya hay; no hace falta guardar nada).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from . import config, net, storage
from .channels import telegram
from .timeutil import fmt_local, parse_ts

SLOT_MIN = 30
CORRIDAS_POR_DIA = 24 * 60 // SLOT_MIN


@dataclass
class Salud:
    ahora: datetime
    tabsa_ultima: datetime | None
    clima_ultimo: datetime | None
    errores_24h: dict[str, int]
    corridas_24h: int
    dias_token: int

    @property
    def tabsa_edad_min(self) -> int | None:
        return None if self.tabsa_ultima is None else int((self.ahora - self.tabsa_ultima).total_seconds() // 60)

    @property
    def clima_edad_min(self) -> int | None:
        return None if self.clima_ultimo is None else int((self.ahora - self.clima_ultimo).total_seconds() // 60)

    @property
    def corridas_faltantes(self) -> int:
        return max(0, CORRIDAS_POR_DIA - self.corridas_24h)

    def problemas(self) -> dict[str, str]:
        """{clave: texto} de lo que está mal ahora. Las claves permiten comparar con la revisión anterior."""
        out = {}
        limite = config.TABSA_SIN_LECTURA_MIN
        if self.tabsa_edad_min is None or self.tabsa_edad_min > limite:
            out["tabsa"] = ("TABSA: no hay ninguna lectura" if self.tabsa_edad_min is None else
                            f"TABSA: {config.CORRIDAS_SIN_TABSA_AVISO} corridas seguidas sin lectura "
                            f"(última hace {_dur(self.tabsa_edad_min)})")
        if self.clima_edad_min is None or self.clima_edad_min > config.CLIMA_ATRASADO_MIN:
            out["clima"] = ("Clima: no hay datos" if self.clima_edad_min is None else
                            f"Clima: el último dato es de hace {_dur(self.clima_edad_min)}")
        if self.dias_token <= config.TOKEN_AVISO_DIAS:
            out["token"] = (f"El token de cron-job.org vence en {self.dias_token} días "
                            f"({config.TOKEN_CRON_VENCE.strftime('%d/%m/%Y')}): renovarlo"
                            if self.dias_token >= 0 else
                            "El token de cron-job.org YA VENCIÓ: renovarlo ya")
        return out


def _dur(minutos: int) -> str:
    return f"{minutos} min" if minutos < 120 else f"{minutos / 60:.1f} h"


def calcular(ahora: datetime | None = None) -> Salud:
    """Salud con los datos que hay hasta `ahora` (lo posterior se ignora)."""
    ahora = ahora or datetime.now(timezone.utc)

    def hasta_ahora(filas):
        return [r for r in filas if parse_ts(r["ts_utc"]) <= ahora]

    estado = hasta_ahora(storage.read_rows(storage.TABSA_STATE))
    clima = hasta_ahora(storage.read_rows(storage.WEATHER))
    errores = hasta_ahora(storage.read_rows(storage.ERRORS))
    desde = ahora - timedelta(hours=24)
    # una "corrida" = media hora con al menos una lectura de TABSA
    franjas = {(t.date(), t.hour, t.minute // SLOT_MIN)
               for t in (parse_ts(r["ts_utc"]) for r in estado) if t >= desde}
    cuenta: dict[str, int] = {}
    for r in errores:
        if parse_ts(r["ts_utc"]) > desde:
            donde = r["where_"].split(":")[0]
            cuenta[donde] = cuenta.get(donde, 0) + 1
    return Salud(
        ahora=ahora,
        tabsa_ultima=max((parse_ts(r["ts_utc"]) for r in estado), default=None),
        clima_ultimo=max((parse_ts(r["ts_utc"]) for r in clima), default=None),
        errores_24h=cuenta, corridas_24h=min(len(franjas), CORRIDAS_POR_DIA),
        dias_token=(config.TOKEN_CRON_VENCE - ahora.date()).days)


def texto(s: Salud) -> str:
    def cuando(t):
        return "nunca" if t is None else f"{fmt_local(t)} (UTC-3)"

    def edad(m):
        return "—" if m is None else f"hace {_dur(m)}"
    lineas = [
        f"SALUD DEL SISTEMA  ({fmt_local(s.ahora)} UTC-3)",
        f"  Última lectura de TABSA : {cuando(s.tabsa_ultima)}  {edad(s.tabsa_edad_min)}",
        f"  Último dato de clima    : {cuando(s.clima_ultimo)}  {edad(s.clima_edad_min)}",
        f"  Corridas en 24 h        : {s.corridas_24h} de {CORRIDAS_POR_DIA} esperadas"
        f"  ({s.corridas_faltantes} sin lectura)",
    ]
    if s.errores_24h:
        lineas.append("  Errores en 24 h         : " + ", ".join(f"{k} {v}" for k, v in sorted(s.errores_24h.items())))
    else:
        lineas.append("  Errores en 24 h         : ninguno")
    lineas.append(f"  Token de cron-job.org   : vence el {config.TOKEN_CRON_VENCE.strftime('%d/%m/%Y')} "
                  f"(faltan {s.dias_token} días)")
    p = s.problemas()
    lineas.append("")
    lineas.append("PROBLEMAS: " + ("; ".join(p.values()) if p else "ninguno"))
    return "\n".join(lineas)


def nuevos_problemas(ahora: datetime | None = None) -> list[str]:
    """Lo que está mal ahora y no estaba mal en la revisión anterior (una hora atrás).

    El token es la excepción: recuerda una vez por día mientras falten pocos días.
    """
    ahora = ahora or datetime.now(timezone.utc)
    hoy, antes = calcular(ahora), calcular(ahora - timedelta(hours=1))
    p_hoy, p_antes = hoy.problemas(), antes.problemas()
    out = [t for k, t in p_hoy.items() if k != "token" and k not in p_antes]
    if "token" in p_hoy and (antes.ahora.date() != hoy.ahora.date() or "token" not in p_antes):
        out.append(p_hoy["token"])
    return out


def avisar(ahora: datetime | None = None) -> str:
    """Avisa al equipo por Telegram (chat aparte). Devuelve qué hizo."""
    nuevos = nuevos_problemas(ahora)
    if not nuevos:
        return "Sin problemas nuevos: no se avisa."
    mensaje = "🛠️ Corredor Austral · salud del sistema\n" + "\n".join(f"• {t}" for t in nuevos)
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_TEAM_CHAT_ID", "").strip()
    if not (token and chat):
        return "No enviado (faltan TELEGRAM_BOT_TOKEN / TELEGRAM_TEAM_CHAT_ID). Mensaje:\n" + mensaje
    try:
        net.post_json(telegram.API_URL.format(token=token),
                      {"chat_id": chat, "text": mensaje, "disable_web_page_preview": True})
    except Exception as e:
        raise RuntimeError(f"Telegram (equipo): {str(e).replace(token, '***')}") from None
    return "Enviado al equipo por Telegram:\n" + mensaje
