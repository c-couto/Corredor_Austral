"""Ferris, zonas y terminales para el mapa en vivo.

Para agregar un ferry: sumá su MMSI a FERRIES. El reporte lista los barcos que
transmiten con alguno de los NOMBRES_BUSCADOS y todavía no están en la lista.
"""

from __future__ import annotations

# MMSI -> nombre (confirmados).
FERRIES: dict[int, str] = {
    725001968: "Pionero",
    725003001: "Kawéskar",
    725000877: "Fueguino",
}

# Ferris de la zona cuyo MMSI todavía no conocemos (se buscan por nombre en los datos).
NOMBRES_BUSCADOS = (
    "PATAGONIA", "KENOS", "CRUX AUSTRALIS", "PATHAGON",  # TABSA
    "KATAIK", "TANU",                                     # Naviera Tierra del Fuego
    "PIONERO", "KAWESKAR", "FUEGUINO",                    # ya conocidos (por si cambian de MMSI)
)

# Rectángulos de suscripción: ((lat_sur, lon_oeste), (lat_norte, lon_este)).
ZONAS: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {
    "primera_angostura": ((-52.65, -69.85), (-52.35, -69.30)),
    "punta_arenas_porvenir": ((-53.40, -70.95), (-53.05, -70.30)),
}

NOMBRES_ZONA = {"primera_angostura": "Primera Angostura", "punta_arenas_porvenir": "Punta Arenas ↔ Porvenir"}


# Terminales de cada cruce (lat, lon). APROXIMADAS: el reporte muestra dónde se quedan
# quietos los ferris de verdad ("muelles observados") para corregirlas con datos.
TERMINALES: dict[str, tuple[tuple[str, float, float], tuple[str, float, float]]] = {
    "primera_angostura": (("Punta Delgada", -52.455, -69.540), ("Bahía Azul", -52.505, -69.580)),
    "punta_arenas_porvenir": (("Punta Arenas (Tres Puentes)", -53.129, -70.873),
                              ("Porvenir (Bahía Chilota)", -53.299, -70.370)),
}

# Un cruce es pasar de un extremo (< 20 % del camino) al otro (> 80 %) en menos de este tiempo.
EXTREMO = 0.2
MAX_DURACION_CRUCE_H = {"primera_angostura": 1.5, "punta_arenas_porvenir": 4.0}
# Distancia máxima a la línea entre terminales: deja afuera a los buques que pasan por el Estrecho.
MAX_DESVIO_KM = {"primera_angostura": 4.0, "punta_arenas_porvenir": 12.0}


def zona_de(lat: float, lon: float) -> str | None:
    for key, ((s, w), (n, e)) in ZONAS.items():
        if s <= lat <= n and w <= lon <= e:
            return key
    return None
