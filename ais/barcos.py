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

# Prueba de control: zonas con mucho tráfico para comprobar que la clave y el código reciben
# datos (si acá llegan posiciones y en el Estrecho no, el problema es la cobertura).
ZONAS_CONTROL: dict[str, tuple[tuple[float, float], tuple[float, float]]] = {
    "valparaiso": ((-33.10, -71.75), (-32.95, -71.55)),  # puerto chileno: ¿hay receptores en Chile?
    "rotterdam": ((51.85, 3.90), (52.05, 4.50)),         # uno de los puertos más vigilados del mundo
}

NOMBRES_ZONA = {"primera_angostura": "Primera Angostura", "punta_arenas_porvenir": "Punta Arenas ↔ Porvenir"}


# Terminales de cada cruce (lat, lon), tomadas de OpenStreetMap. El reporte igual muestra
# dónde se quedan quietos los ferris de verdad ("muelles observados") para verificarlas.
TERMINALES: dict[str, tuple[tuple[str, float, float], tuple[str, float, float]]] = {
    # Rampas reales de OpenStreetMap (vía 49793837, nodos 632646620 y 632646610).
    "primera_angostura": (("Punta Delgada", -52.4566991, -69.5457476), ("Bahía Azul", -52.4945736, -69.5199923)),
    # Terminales reales de OpenStreetMap (nodos 461515635 y 639853443).
    "punta_arenas_porvenir": (("Punta Arenas (Tres Puentes)", -53.1211734, -70.8667496),
                              ("Porvenir (Bahía Chilota)", -53.3046949, -70.4347761)),
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
