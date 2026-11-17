"""Configuración: carpetas, lugares y parámetros de red.

Todo lo que se quiera ajustar sin tocar la lógica está acá.
"""

from __future__ import annotations

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
