"""Envío de mensajes por Telegram (gratis).

Necesita dos variables de entorno, que en GitHub se cargan como Secrets
(NUNCA en el código):
  TELEGRAM_BOT_TOKEN  el token que da @BotFather al crear el bot
  TELEGRAM_CHAT_ID    a dónde mandar: un canal (@nombre_del_canal) o un chat/grupo (número)

Si faltan, no se envía nada y no es un error: así el workflow anda igual
mientras Telegram no esté configurado.
"""

from __future__ import annotations

import os

from .. import net

API_URL = "https://api.telegram.org/bot{token}/sendMessage"


def is_configured() -> bool:
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID"))


def send(text: str) -> bool:
    """Envía `text`. Devuelve False si Telegram no está configurado."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not (token and chat_id):
        print("Telegram no configurado (faltan TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID): no se envía.")
        return False
    try:
        net.post_json(API_URL.format(token=token), {
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        })
    except Exception as e:
        # Que el token nunca aparezca en un mensaje de error (los errores se guardan en el repo).
        raise RuntimeError(f"Telegram: {str(e).replace(token, '***')}") from None
    return True
