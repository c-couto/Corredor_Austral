"""Configuración: carpetas, lugares, fuentes, modelo y web.

Todo lo que se quiera ajustar sin tocar la lógica está acá. Lo que es privado
(tokens, contactos) llega por variables de entorno / GitHub Secrets.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

from . import __version__

# ---------------------------------------------------------------- carpetas

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CACHE_DIR = ROOT / ".cache"  # pronóstico horario del momento (no se guarda en el repo)
MODEL_PATH_PARTS = ("model", "modelo.json")  # dentro de DATA_DIR

# ---------------------------------------------------------------- red

# Cada consulta espera como máximo 15 s. Si falla, se reintenta hasta 3 veces,
# esperando cada vez un poco más (5 s, 10 s y 20 s).
HTTP_TIMEOUT_S = 15
RETRY_WAITS_S = (5, 10, 20)
# Clima de Open-Meteo: cuando falla es casi siempre porque el servidor está saturado (el
# "handshake" no termina en 15 s). Sirve más esperar un minuto que insistir rápido.
# 3 intentos en total, 60 s entre cada uno (peor caso ~2 min 45 s; el trabajo tiene 6 min
# y TABSA se lee ANTES del clima, así que nunca se pierde por esto).
WEATHER_RETRY_WAITS_S = (60, 60)

# ---------------------------------------------------------------- lugares

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
    "rio_verde": (-52.65, -71.48),  # cruce del canal Fitz Roy: verificar en el mapa
}

# Puntos donde también se consulta oleaje (modelo marino; puede no cubrir bien el estrecho).
MARINE_PLACES: tuple[str, ...] = ("punta_delgada", "bahia_azul", "ushuaia")

# Puntos cuyo pronóstico de 48 h se guarda COMPLETO en cada corrida (data/auto/pronosticos/):
# las dos orillas de Primera Angostura, el cruce que queremos predecir mejor que nadie.
SNAPSHOT_PLACES: tuple[str, ...] = ("punta_delgada", "bahia_azul")

PLACE_NAMES: dict[str, str] = {
    "rio_grande": "Río Grande",
    "ushuaia": "Ushuaia",
    "san_sebastian": "San Sebastián",
    "punta_delgada": "Punta Delgada",
    "bahia_azul": "Bahía Azul",
    "porvenir": "Porvenir",
    "punta_arenas": "Punta Arenas",
    "rio_verde": "Río Verde",
}

# Magallanes (Chile) y Tierra del Fuego (Argentina) usan UTC-3 todo el año.
LOCAL_UTC_OFFSET_H = -3

# ---------------------------------------------------------------- fuentes

TABSA_URL = "https://www.tabsa.cl/estado-cruces"
OFFICIAL_URL = TABSA_URL

# Clima: Open-Meteo (gratis, SOLO uso NO comercial) o MET Norway (gratis, permite uso
# comercial citando la fuente, pero exige identificarse con un contacto).
# Para pasar a MET Norway alcanza con definir CORREDOR_MET_CONTACT (un mail o la web
# del proyecto). En ese modo NO se usa Open-Meteo para nada (tampoco el oleaje).
MET_CONTACT = os.environ.get("CORREDOR_MET_CONTACT", "").strip()
WEATHER_SOURCE = "met_norway" if MET_CONTACT else "open_meteo"
USER_AGENT = f"corredor-austral/{__version__}" + (f" {MET_CONTACT}" if MET_CONTACT else "")

# ---------------------------------------------------------------- cruces

# Qué se muestra por cruce, qué puntos de clima mira y cómo se llama en TABSA.
#   tabsa:     clave del cruce en la tabla "Estado del cruce" de TABSA (None si no está)
#   scheduled: True si el cruce funciona con horarios (tabla "Cruces programados")
ROUTES: dict[str, dict] = {
    "primera_angostura": {
        "name": "Primera Angostura",
        "detail": "Punta Delgada ↔ Bahía Azul",
        "places": ("punta_delgada", "bahia_azul"),
        "tabsa": "primera_angostura",
    },
    "punta_arenas_porvenir": {
        "name": "Punta Arenas ↔ Porvenir",
        "detail": "Cruces con horario",
        "places": ("punta_arenas", "porvenir"),
        "tabsa": None,
        "scheduled": True,
    },
    "rio_verde": {
        "name": "Río Verde",
        "detail": "Canal Fitz Roy · Isla Riesco",
        "places": ("rio_verde",),
        "tabsa": "rio_verde",
    },
}

# Planificador "¿A qué hora salgo?": horas de manejo APROXIMADAS hasta Primera Angostura
# (incluyen el paso fronterizo cuando corresponde). Ajustalas con la experiencia de los choferes.
PLANNER_ROUTE = "primera_angostura"
PLANNER_ORIGINS: tuple[tuple[str, float], ...] = (
    ("Río Gallegos", 2.0),
    ("Punta Arenas", 2.5),
    ("Río Grande", 4.0),
    ("Ushuaia", 7.0),
)

# ---------------------------------------------------------------- riesgo y modelo

# Probabilidad de que el cruce NO esté normal -> nivel que se muestra.
RISK_LEVELS: tuple[tuple[float, str], ...] = ((0.5, "alto"), (0.2, "medio"))

# Regla base (mientras no haya suficientes suspensiones para aprender): curva logística
# sobre la ráfaga. Con estos valores: 50 km/h -> 20 % (medio), 70 km/h -> 50 % (alto).
PRIOR_CENTER_KMH = 70.0
PRIOR_SCALE_KMH = 14.4

# Regla base POR CRUCE: (ráfaga en que da 50 %, escala). Hoy los 3 valen lo mismo que la regla
# general; está separado para poder ajustar cada cruce con datos (ver corredor.evaluacion).
# No cambiar a mano por un solo día de viento.
PRIOR_BY_ROUTE: dict[str, tuple[float, float]] = {
    # Primera Angostura: lo que había aprendido el modelo con los datos reales del 24/11 (rojo desde
    # 94 km/h, amarillo desde 79). PROVISIONAL: sale de solo 2 temporales; se revisa al tener 8.
    # Con 70 daba 32 falsas alarmas rojas en 282 lecturas normales; con 94/79, 0.
    "primera_angostura": (94.0, 10.8),
    "punta_arenas_porvenir": (PRIOR_CENTER_KMH, PRIOR_SCALE_KMH),
    # Río Verde operó normal con ráfagas de hasta 88 km/h en horario de servicio (26/11) y TABSA solo lo
    # suspendió una vez, con 55 km/h. 95 es un piso, no una medición: revisar también si Open-Meteo
    # exagera el viento en ese punto.
    "rio_verde": (95.0, PRIOR_SCALE_KMH),
}

# El modelo aprendido reemplaza a la regla base solo si hay datos suficientes y
# además predice mejor que ella en datos que no vio.
MODEL_MIN_SAMPLES = 60
MODEL_MIN_POSITIVES = 8

# ---------------------------------------------------------------- web y avisos

# Si el último dato tiene más de estas horas, se avisa que está desactualizado.
STALE_AFTER_H = 2

# Salud del sistema (corredor/salud.py y cartel "Datos atrasados" de la web).
CLIMA_ATRASADO_MIN = 90        # clima más viejo que esto = problema / cartel en la web
TABSA_SIN_LECTURA_MIN = 100    # ~3 corridas seguidas (cada 30 min) sin leer TABSA
CORRIDAS_SIN_TABSA_AVISO = 3
TOKEN_AVISO_DIAS = 7           # avisar al equipo desde 7 días antes
TOKEN_CRON_VENCE = date(2026, 12, 17)   # vence el token que usa cron-job.org: RENOVARLO antes

# Links opcionales (variables del workflow; vacíos = no se muestran).
#   CORREDOR_SITE_URL      dirección pública de la web (va en los mensajes)
#   CORREDOR_TELEGRAM_URL  link al canal de Telegram (botón "Seguir en Telegram")
#   CORREDOR_CONTACT_URL   contacto comercial: Plan Flota y anunciantes (mailto:, wa.me/..., formulario)
SITE_URL = os.environ.get("CORREDOR_SITE_URL", "").strip()
TELEGRAM_URL = os.environ.get("CORREDOR_TELEGRAM_URL", "").strip()
CONTACT_URL = os.environ.get("CORREDOR_CONTACT_URL", "").strip()

# "Dónde esperar": negocios que pagan por aparecer cuando el riesgo es alto.
# Ejemplo: {"name": "Hostería X", "place": "Punta Delgada", "text": "Café y wifi", "url": "https://..."}
SPONSORS: list[dict[str, str]] = []
