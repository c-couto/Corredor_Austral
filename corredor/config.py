"""Configuración: carpetas, lugares y parámetros de red.

Todo lo que se quiera ajustar sin tocar la lógica está acá.
"""

from __future__ import annotations

import os
from pathlib import Path

# Raíz del repositorio y carpeta de datos.
ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

# Red: cada consulta espera como máximo 15 s. Si falla, se reintenta hasta
# 3 veces, esperando cada vez un poco más (5 s, 10 s y 20 s).
HTTP_TIMEOUT_S = 15
RETRY_WAITS_S = (5, 10, 20)
USER_AGENT = "corredor-austral/0.3"

# Coordenadas APROXIMADAS (lat, lon). Verificalas en un mapa y ajustalas.
# Para clima, una diferencia de unos kilómetros no cambia mucho el resultado.
PLACES: dict[str, tuple[float, float]] = {
    "rio_grande": (-53.79, -67.71),
    "ushuaia": (-54.80, -68.30),
    "san_sebastian": (-53.30, -68.50),
    "punta_delgada": (-52.43, -69.47),
    "bahia_azul": (-52.50, -69.40),
    "porvenir": (-53.30, -70.37),
    "punta_arenas": (-53.16, -70.91),
}

# Puntos donde también se consulta oleaje (modelo marino; puede no cubrir bien el estrecho).
MARINE_PLACES: tuple[str, ...] = ("punta_delgada", "bahia_azul", "ushuaia")

# Nombres para mostrar.
PLACE_NAMES: dict[str, str] = {
    "rio_grande": "Río Grande",
    "ushuaia": "Ushuaia",
    "san_sebastian": "San Sebastián",
    "punta_delgada": "Punta Delgada",
    "bahia_azul": "Bahía Azul",
    "porvenir": "Porvenir",
    "punta_arenas": "Punta Arenas",
}

# ------------------------------------------------------------------ BETA web / avisos

# Cruces que se muestran, y qué puntos de clima miran.
ROUTES: dict[str, dict] = {
    "primera_angostura": {
        "name": "Primera Angostura",
        "detail": "Punta Delgada – Bahía Azul",
        "places": ("punta_delgada", "bahia_azul"),
    },
    "punta_arenas_porvenir": {
        "name": "Punta Arenas – Porvenir",
        "detail": "Estrecho, sector central",
        "places": ("punta_arenas", "porvenir"),
    },
}

# Umbrales PROVISORIOS de ráfaga (km/h) para el "riesgo de demora por viento".
# No están validados: hay que ajustarlos cuando tengamos el historial de TABSA.
# Se evalúan de arriba hacia abajo; si la ráfaga no llega a ninguno, el riesgo es "bajo".
GUST_LEVELS: tuple[tuple[float, str], ...] = ((70, "alto"), (50, "medio"))

# Magallanes (Chile) y Tierra del Fuego (Argentina) usan UTC-3 todo el año.
LOCAL_UTC_OFFSET_H = -3

# Si el último dato tiene más de estas horas, la web avisa que está desactualizada.
STALE_AFTER_H = 2

# Links opcionales (se configuran como variables del workflow; vacíos = no se muestran).
#   CORREDOR_SITE_URL      dirección pública de la web (va en los mensajes)
#   CORREDOR_TELEGRAM_URL  link al canal de Telegram (botón "Seguir en Telegram")
SITE_URL = os.environ.get("CORREDOR_SITE_URL", "").strip()
TELEGRAM_URL = os.environ.get("CORREDOR_TELEGRAM_URL", "").strip()
OFFICIAL_URL = "https://www.tabsa.cl/estado-cruces"
