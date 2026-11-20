"""Reporte de cobertura AIS: ¿alcanzan los datos para un mapa en vivo?

Uso (desde la raíz del repo):
    python -m ais.reporte                       # todo lo juntado
    python -m ais.reporte --desde 2026-11-20    # desde una fecha (UTC)

Por barco mide: % de horas con dato (sobre las horas en que ESTUVIMOS escuchando),
hueco más largo sin dato (contando solo el tiempo escuchado) y cruces detectados.
Genera un mapa HTML (por defecto .cache/ais_mapa.html, fuera del repo).
"""

from __future__ import annotations

import argparse
import html
import json
import math
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from corredor import config
from corredor.timeutil import fmt_local, parse_ts

from . import barcos, datos

MIN_ESCUCHA_HORA_S = 300  # una hora cuenta si escuchamos al menos 5 min en ella
CORTE_TRAZO = timedelta(minutes=30)  # en el mapa, se corta la línea si pasa más de esto sin dato


@dataclass
class Punto:
    t: datetime
    lat: float
    lon: float
    sog: float | None


@dataclass
class Cruce:
    ruta: str
    salida: datetime   # última vez visto en la orilla de salida
    llegada: datetime  # primera vez visto en la otra orilla
    desde: str
    hacia: str


# ------------------------------------------------------------------ geometría

def proyectar(lat: float, lon: float, ruta: str) -> tuple[float, float]:
    """(fracción del camino entre terminales [0 = salida, 1 = llegada], distancia a la línea en km)."""
    (_, la, oa), (_, lb, ob) = barcos.TERMINALES[ruta]
    kx = 111.32 * math.cos(math.radians(la))
    ky = 110.57
    bx, by = (ob - oa) * kx, (lb - la) * ky
    x, y = (lon - oa) * kx, (lat - la) * ky
    largo2 = bx * bx + by * by
    return (x * bx + y * by) / largo2, abs(x * by - y * bx) / math.sqrt(largo2)


def detectar_cruces(puntos: list[Punto], ruta: str) -> list[Cruce]:
    """Cruce = el barco pasa de un extremo de la línea entre terminales al otro.

    Funciona aunque falten posiciones en el medio (cobertura irregular): alcanza con
    verlo en una orilla y después en la otra dentro de MAX_DURACION_CRUCE_H.
    """
    (na, *_), (nb, *_) = barcos.TERMINALES[ruta]
    nombres = {"A": na, "B": nb}
    max_dur = timedelta(hours=barcos.MAX_DURACION_CRUCE_H[ruta])
    out: list[Cruce] = []
    lado, lado_t = None, None
    for p in sorted(puntos, key=lambda p: p.t):
        f, desvio = proyectar(p.lat, p.lon, ruta)
        if desvio > barcos.MAX_DESVIO_KM[ruta] or not -0.5 <= f <= 1.5:
            continue  # lejos de la ruta (otro tramo del Estrecho)
        s = "A" if f <= barcos.EXTREMO else "B" if f >= 1 - barcos.EXTREMO else None
        if s is None:
            continue
        if lado is not None and s != lado and p.t - lado_t <= max_dur:
            out.append(Cruce(ruta, lado_t, p.t, nombres[lado], nombres[s]))
        lado, lado_t = s, p.t
    return out


# ------------------------------------------------------------------ cobertura

def _solapa(a: datetime, b: datetime, sesiones: list[tuple[datetime, datetime]]) -> float:
    return sum(max(0.0, (min(e, b) - max(s, a)).total_seconds()) for s, e in sesiones)


def horas_escuchadas(sesiones: list[tuple[datetime, datetime]]) -> set[datetime]:
    seg: dict[datetime, float] = {}
    for s, e in sesiones:
        h = s.replace(minute=0, second=0, microsecond=0)
        while h < e:
            seg[h] = seg.get(h, 0.0) + _solapa(h, h + timedelta(hours=1), [(s, e)])
            h += timedelta(hours=1)
    return {h for h, v in seg.items() if v >= MIN_ESCUCHA_HORA_S}


def cobertura(tiempos: list[datetime], horas: set[datetime]) -> tuple[int, int]:
    con_dato = {t.replace(minute=0, second=0, microsecond=0) for t in tiempos} & horas
    return len(con_dato), len(horas)


def hueco_mas_largo(tiempos: list[datetime], sesiones: list[tuple[datetime, datetime]]) -> timedelta:
    """Mayor tiempo ESCUCHANDO sin recibir nada del barco (las horas sin escuchar no cuentan)."""
    if not sesiones:
        return timedelta(0)
    marcas = [min(s for s, _ in sesiones), *sorted(tiempos), max(e for _, e in sesiones)]
    return timedelta(seconds=max(_solapa(a, b, sesiones) for a, b in zip(marcas, marcas[1:])))


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode()
    return " ".join(t.upper().split())


def muelles_observados(puntos_por_barco: dict[int, list[Punto]], ruta: str, top: int = 4):
    """Dónde se quedan quietos los barcos (velocidad < 0,5 nudos) dentro de la zona: sirve
    para corregir las coordenadas de las terminales con datos reales."""
    conteo: dict[tuple[float, float], int] = {}
    for pts in puntos_por_barco.values():
        for p in pts:
            if p.sog is not None and p.sog < 0.5 and barcos.zona_de(p.lat, p.lon) == ruta:
                k = (round(p.lat, 2), round(p.lon, 2))
                conteo[k] = conteo.get(k, 0) + 1
    return sorted(conteo.items(), key=lambda kv: -kv[1])[:top]


def fmt_dur(d: timedelta) -> str:
    m = round(d.total_seconds() / 60)
    return f"{m} min" if m < 60 else f"{m // 60} h {m % 60:02d} min"


# ------------------------------------------------------------------ armado

def analizar(base: Path, desde: datetime | None = None) -> dict:
    sesiones = []
    for r in datos.read(base / "sesiones.csv"):
        try:
            s, e = parse_ts(r["inicio_utc"]), parse_ts(r["fin_utc"])
        except (KeyError, ValueError):
            continue
        if desde and e < desde:
            continue
        sesiones.append((max(s, desde) if desde else s, e))
    nombres: dict[int, str] = {}
    for r in datos.read(base / "barcos.csv"):
        if r.get("nombre"):
            nombres[int(r["mmsi"])] = r["nombre"]
    puntos: dict[int, list[Punto]] = {}
    for r in datos.read_posiciones(base):
        try:
            t = parse_ts(r["ts_utc"])
            mmsi = int(r["mmsi"])
            p = Punto(t, float(r["lat"]), float(r["lon"]), float(r["sog_kn"]) if r.get("sog_kn") else None)
        except (KeyError, ValueError):
            continue
        if desde and t < desde:
            continue
        puntos.setdefault(mmsi, []).append(p)
        if r.get("nombre") and mmsi not in nombres:
            nombres[mmsi] = r["nombre"]
    for pts in puntos.values():
        pts.sort(key=lambda p: p.t)

    horas = horas_escuchadas(sesiones)
    buscados = {_norm(n) for n in barcos.NOMBRES_BUSCADOS}

    def nombre(mmsi: int) -> str:
        return barcos.FERRIES.get(mmsi) or nombres.get(mmsi) or "(sin nombre)"

    filas = []
    for mmsi in sorted(set(barcos.FERRIES) | set(puntos)):
        pts = puntos.get(mmsi, [])
        cruces = [c for ruta in barcos.TERMINALES for c in detectar_cruces(pts, ruta)]
        conocido = mmsi in barcos.FERRIES
        candidato = not conocido and any(b in _norm(nombres.get(mmsi, "")) for b in buscados)
        if not (conocido or candidato or cruces):
            continue
        con, total = cobertura([p.t for p in pts], horas)
        filas.append({
            "mmsi": mmsi, "nombre": nombre(mmsi), "conocido": conocido, "candidato": candidato,
            "posiciones": len(pts), "horas_con_dato": con, "horas": total,
            "pct": round(100 * con / total) if total else None,
            "hueco": hueco_mas_largo([p.t for p in pts], sesiones) if pts else None,
            "cruces": sorted(cruces, key=lambda c: c.salida),
            "ultimo": pts[-1].t if pts else None,
        })

    zonas = {}
    for ruta in barcos.ZONAS:
        tiempos = [p.t for pts in puntos.values() for p in pts if barcos.zona_de(p.lat, p.lon) == ruta]
        con, total = cobertura(tiempos, horas)
        zonas[ruta] = {"horas_con_dato": con, "horas": total,
                       "pct": round(100 * con / total) if total else None,
                       "muelles": muelles_observados(puntos, ruta)}

    return {
        "sesiones": sesiones, "horas": len(horas),
        "escuchado": timedelta(seconds=sum((e - s).total_seconds() for s, e in sesiones)),
        "zonas": zonas, "barcos": filas, "puntos": puntos, "nombres": {m: nombre(m) for m in puntos},
        "otros": len([m for m in puntos if m not in {f["mmsi"] for f in filas}]),
    }


def texto(a: dict, mapa: Path | None = None) -> str:
    L = []
    if not a["sesiones"]:
        return "Todavía no hay sesiones de escucha (correr: python -m ais.sondeo)."
    ini, fin = min(s for s, _ in a["sesiones"]), max(e for _, e in a["sesiones"])
    L.append(f"Cobertura AIS · del {fmt_local(ini)} al {fmt_local(fin)} (hora local)")
    L.append(f"Escuchamos {fmt_dur(a['escuchado'])} en {len(a['sesiones'])} sesiones · "
             f"horas con al menos 5 min de escucha: {a['horas']}")
    L.append("")
    L.append("Por zona (horas con al menos un mensaje de algún barco):")
    for ruta, z in a["zonas"].items():
        pct = f"{z['pct']} %" if z["pct"] is not None else "-"
        L.append(f"  {barcos.NOMBRES_ZONA[ruta]}: {z['horas_con_dato']}/{z['horas']} ({pct})")
    L.append("")
    L.append("Por barco:")
    for f in a["barcos"]:
        marca = "" if f["conocido"] else "  ← ¿ferry? revisar y agregar a FERRIES" if f["candidato"] else "  ← cruza, no está en la lista"
        pct = f"{f['pct']} %" if f["pct"] is not None else "-"
        hueco = fmt_dur(f["hueco"]) if f["hueco"] is not None else "-"
        L.append(f"  {f['nombre']} ({f['mmsi']}): horas con dato {f['horas_con_dato']}/{f['horas']} ({pct}) · "
                 f"hueco más largo {hueco} · posiciones {f['posiciones']} · cruces {len(f['cruces'])}{marca}")
    L.append(f"  Otros barcos vistos en las zonas: {a['otros']}")
    L.append("")
    L.append("Muelles observados (barco quieto; para corregir las terminales en ais/barcos.py):")
    for ruta, z in a["zonas"].items():
        txt = ", ".join(f"{lat:.2f},{lon:.2f} ({n})" for (lat, lon), n in z["muelles"]) or "sin datos"
        L.append(f"  {barcos.NOMBRES_ZONA[ruta]}: {txt}")
    if mapa:
        L.append("")
        L.append(f"Mapa: {mapa}")
    return "\n".join(L)


LEAFLET = "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4"


def mapa_html(a: dict) -> str:
    colores = ["#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4", "#46f0f0", "#f032e6", "#9a6324"]
    destacados = {f["mmsi"] for f in a["barcos"]}
    barcos_js = []
    for i, (mmsi, pts) in enumerate(sorted(a["puntos"].items(), key=lambda kv: (kv[0] not in destacados, kv[0]))):
        trazos, actual = [], []
        for p in pts:
            if actual and p.t - actual[-1][2] > CORTE_TRAZO:
                trazos.append(actual)
                actual = []
            actual.append((p.lat, p.lon, p.t))
        if actual:
            trazos.append(actual)
        barcos_js.append({
            "nombre": f"{a['nombres'][mmsi]} ({mmsi})", "destacado": mmsi in destacados,
            "color": colores[i % len(colores)] if mmsi in destacados else "#888",
            "trazos": [[[la, lo] for la, lo, _ in tr] for tr in trazos],
            "ultimo": [pts[-1].lat, pts[-1].lon], "hora": fmt_local(pts[-1].t),
        })
    payload = {
        "barcos": barcos_js,
        "zonas": [[list(sw), list(ne)] for sw, ne in barcos.ZONAS.values()],
        "terminales": [[n, la, lo] for par in barcos.TERMINALES.values() for n, la, lo in par],
    }
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    filas = "".join(
        f"<tr><td>{html.escape(f['nombre'])}</td><td>{f['mmsi']}</td>"
        f"<td>{f['pct'] if f['pct'] is not None else '-'} %</td>"
        f"<td>{fmt_dur(f['hueco']) if f['hueco'] is not None else '-'}</td><td>{len(f['cruces'])}</td></tr>"
        for f in a["barcos"])
    resumen = html.escape(texto(a))
    return f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cobertura AIS</title>
<link rel="stylesheet" href="{LEAFLET}/leaflet.min.css">
<style>
body{{margin:0;font:14px/1.4 system-ui,sans-serif;background:#07121c;color:#e7eef5}}
#map{{height:65vh}}main{{padding:12px 16px;max-width:900px}}table{{border-collapse:collapse;width:100%}}
td,th{{padding:4px 6px;border-bottom:1px solid #1f3344;text-align:left}}pre{{white-space:pre-wrap;font-size:12px;color:#93a4b5}}
</style></head><body>
<div id="map"></div>
<main><h1>Cobertura AIS · etapa 1</h1>
<table><tr><th>Barco</th><th>MMSI</th><th>Horas con dato</th><th>Hueco más largo</th><th>Cruces</th></tr>{filas}</table>
<pre>{resumen}</pre>
<p>Mapa © colaboradores de OpenStreetMap · datos AIS de aisstream.io</p></main>
<script id="datos" type="application/json">{data}</script>
<script src="{LEAFLET}/leaflet.min.js"></script>
<script>
(function(){{var d=JSON.parse(document.getElementById('datos').textContent);
function txt(s){{var e=document.createElement('span');e.textContent=s;return e}}
var m=L.map('map').setView([-52.9,-70.1],8);
L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:15,attribution:'© OpenStreetMap'}}).addTo(m);
d.zonas.forEach(function(z){{L.rectangle(z,{{color:'#5cc8ff',weight:1,fill:false,dashArray:'4'}}).addTo(m)}});
d.terminales.forEach(function(t){{L.circleMarker([t[1],t[2]],{{radius:5,color:'#ffd23f'}}).bindTooltip(txt(t[0])).addTo(m)}});
d.barcos.forEach(function(b){{b.trazos.forEach(function(tr){{L.polyline(tr,{{color:b.color,weight:b.destacado?3:1,opacity:b.destacado?.9:.4}}).bindTooltip(txt(b.nombre)).addTo(m)}});
L.circleMarker(b.ultimo,{{radius:b.destacado?6:3,color:b.color}}).bindTooltip(txt(b.nombre+' · último dato '+b.hora)).addTo(m)}});
}})();
</script></body></html>
"""


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m ais.reporte", description=__doc__.splitlines()[0])
    p.add_argument("--datos", help="carpeta de datos (por defecto data/ais/)")
    p.add_argument("--desde", help="fecha UTC AAAA-MM-DD desde la que medir")
    p.add_argument("--salida", default=str(config.CACHE_DIR / "ais_mapa.html"), help="archivo del mapa HTML")
    args = p.parse_args(argv)
    desde = datetime.strptime(args.desde, "%Y-%m-%d").replace(tzinfo=timezone.utc) if args.desde else None
    a = analizar(datos.base_dir(args.datos), desde)
    salida = Path(args.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.write_text(mapa_html(a), encoding="utf-8", newline="\n")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")  # la consola de Windows no tiene todos los caracteres
    print(texto(a, salida))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
