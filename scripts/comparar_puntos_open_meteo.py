"""Compara puntos de Open-Meteo: ¿caen en la misma celda del modelo y dan números distintos?

Solo lee (una consulta a Open-Meteo; no guarda nada en data/). Sirve para elegir un lugar nuevo
(por ejemplo, un punto de Primera Angostura que no caiga en la celda de Punta Delgada) o para revisar
si un punto (Río Verde) es representativo.

    python scripts/comparar_puntos_open_meteo.py
    python scripts/comparar_puntos_open_meteo.py "mi punto=-52.50,-69.52" "otro=-52.56,-69.45"

El primer punto es la referencia con la que se compara el resto. Open-Meteo usa uso NO comercial.
"""

from __future__ import annotations

import json
import statistics as st
import sys
import urllib.parse
import urllib.request

PUNTOS_POR_DEFECTO = {
    "punta_delgada (hoy en config)": (-52.43, -69.47),
    "bahia_azul (hoy en config)": (-52.50, -69.40),
    "rampa Punta Delgada (OSM)": (-52.4567, -69.5457),
    "rampa Bahía Azul (OSM)": (-52.4946, -69.5200),
    "canal, centro": (-52.476, -69.533),
    "un poco al sur": (-52.56, -69.45),
}


def leer_argumentos(args: list[str]) -> dict[str, tuple[float, float]]:
    if not args:
        return PUNTOS_POR_DEFECTO
    out = {}
    for a in args:
        nombre, coords = a.split("=")
        lat, lon = coords.split(",")
        out[nombre] = (float(lat), float(lon))
    return out


def main(args: list[str]) -> int:
    puntos = leer_argumentos(args)
    q = urllib.parse.urlencode({
        "latitude": ",".join(str(v[0]) for v in puntos.values()),
        "longitude": ",".join(str(v[1]) for v in puntos.values()),
        "hourly": "wind_gusts_10m", "past_days": 3, "forecast_days": 1, "timezone": "UTC"})
    datos = json.load(urllib.request.urlopen("https://api.open-meteo.com/v1/forecast?" + q, timeout=60))
    if isinstance(datos, dict):
        datos = [datos]
    series = {}
    for (nombre, _), d in zip(puntos.items(), datos):
        g = d["hourly"]["wind_gusts_10m"]
        series[nombre] = g
        validas = [x for x in g if x is not None]
        print(f"{nombre:32} celda ({d['latitude']:.3f},{d['longitude']:.3f})  ráfaga media {st.mean(validas):5.1f}  máx {max(validas):4.0f}")
    ref_nombre = next(iter(series))
    print(f"\nDiferencia con «{ref_nombre}» (96 h): promedio de |dif| en km/h y horas con ≥10 km/h de diferencia")
    for nombre, g in series.items():
        dif = [abs(a - b) for a, b in zip(series[ref_nombre], g) if a is not None and b is not None]
        print(f"  {nombre:32} {st.mean(dif):5.1f}   {sum(x >= 10 for x in dif)}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")
    raise SystemExit(main(sys.argv[1:]))
