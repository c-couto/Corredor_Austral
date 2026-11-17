"""Consultas HTTP con timeout y reintentos (solo biblioteca estándar)."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Mapping

from . import config


def get_json(url: str, params: Mapping[str, Any]) -> Any:
    """GET que devuelve JSON. Timeout de 15 s y hasta 3 reintentos con espera creciente."""
    full = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full, headers={"User-Agent": config.USER_AGENT})
    waits = config.RETRY_WAITS_S
    last_error: BaseException | None = None
    for attempt in range(len(waits) + 1):
        if attempt > 0:
            wait = waits[attempt - 1]
            print(f"  reintento {attempt}/{len(waits)} en {wait} s ({last_error})", file=sys.stderr)
            time.sleep(wait)
        try:
            with urllib.request.urlopen(req, timeout=config.HTTP_TIMEOUT_S) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # Un 4xx (pedido mal armado) no se arregla reintentando, salvo el 429
            # (demasiadas consultas).
            if 400 <= e.code < 500 and e.code != 429:
                raise
            last_error = e
        except Exception as e:  # timeout, conexión cortada, respuesta rota...
            last_error = e
    assert last_error is not None
    raise last_error
