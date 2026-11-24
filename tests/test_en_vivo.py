"""Pantalla "En vivo" (paginas/en-vivo/): datos del cruce y reglas que no se pueden romper.

La lógica de la pantalla es JavaScript; acá se controla lo que importa sin navegador:
la ruta viene de OpenStreetMap con la fuente anotada, se muestran los créditos
obligatorios, no hay claves y no se usan imágenes satelitales.
"""

import json
import re
import unittest
from pathlib import Path

CARPETA = Path(__file__).resolve().parent.parent / "paginas" / "en-vivo"


class DatosDelCruceTest(unittest.TestCase):
    def setUp(self):
        self.datos = json.loads((CARPETA / "datos" / "cruce-primera-angostura.json").read_text(encoding="utf-8"))

    def test_via_de_osm_con_sus_9_nodos_en_orden(self):
        nodos = self.datos["nodos"]
        self.assertEqual(self.datos["via"]["id"], 49793837)
        self.assertEqual(len(nodos), 9)
        self.assertEqual((nodos[0]["id"], nodos[0]["nombre"]), (632646620, "Punta Delgada"))
        self.assertEqual((nodos[-1]["id"], nodos[-1]["nombre"]), (632646610, "Bahía Azul"))
        for n in nodos:  # todo dentro de Primera Angostura
            self.assertTrue(-52.6 < n["lat"] < -52.4 and -69.7 < n["lon"] < -69.4, n)

    def test_fuente_y_licencia_anotadas(self):
        self.assertIn("openstreetmap.org/api/0.6/way/49793837", self.datos["url"])
        self.assertIn("ODbL", self.datos["licencia"])
        self.assertRegex(self.datos["descargado_utc"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")


class DatosPuntaArenasPorvenirTest(unittest.TestCase):
    def test_via_de_osm_entre_las_terminales_reales(self):
        d = json.loads((CARPETA / "datos" / "cruce-punta-arenas-porvenir.json").read_text(encoding="utf-8"))
        self.assertEqual(d["via"]["id"], 86335223)
        self.assertEqual(d["via"]["duracion"], "02:20")
        nodos = d["nodos"]
        self.assertEqual((nodos[0]["id"], nodos[0]["nombre"]), (639853443, "Porvenir"))        # Bahía Chilota
        self.assertEqual((nodos[-1]["id"], nodos[-1]["nombre"]), (461515635, "Punta Arenas"))  # Tres Puentes
        self.assertIn("ODbL", d["licencia"])

    def test_horario_real_lee_los_zarpes_de_tabsa(self):
        estado = (CARPETA / "estado.js").read_text(encoding="utf-8")
        self.assertIn("tabsa_programados.csv", estado)
        app = (CARPETA / "app.js").read_text(encoding="utf-8")
        self.assertIn("Horario real TABSA · posición estimada", app)  # se aclara qué es real y qué estimado


class DatosRioVerdeTest(unittest.TestCase):
    def setUp(self):
        self.ruta = json.loads((CARPETA / "datos" / "cruce-rio-verde.json").read_text(encoding="utf-8"))
        self.horario = json.loads((CARPETA / "datos" / "horario-rio-verde.json").read_text(encoding="utf-8"))

    def test_via_de_osm_entre_las_rampas_reales(self):
        self.assertEqual(self.ruta["via"]["id"], 164993132)
        nodos = self.ruta["nodos"]
        self.assertEqual((nodos[0]["id"], nodos[0]["nombre"]), (6294500944, "Isla Riesco"))
        self.assertEqual((nodos[-1]["id"], nodos[-1]["nombre"]), (1765874221, "Villa Ponsomby"))
        self.assertIn("ODbL", self.ruta["licencia"])
        self.assertIn("cinco minutos", self.ruta["via"]["duracion_fuente"])  # dato de TABSA

    def test_horario_con_fuente_y_temporadas_que_cubren_todo_el_anio(self):
        self.assertIn("rioverde.cl", self.horario["url"])
        self.assertIn("TABSA", self.horario["fuente"])
        nombres = [t["nombre"] for t in self.horario["temporadas"]]
        self.assertEqual(nombres, ["invierno", "verano"])
        inv, ver = self.horario["temporadas"]
        self.assertEqual((inv["desde"], inv["hasta"], ver["desde"], ver["hasta"]),
                         ("04-22", "09-30", "10-01", "04-21"))

    def test_cada_ida_tiene_su_vuelta_10_min_despues(self):
        # Así es el horario oficial: el ferry sale de Isla Riesco y vuelve desde Villa Ponsomby
        # 10 minutos después. Sirve para detectar un error al copiar una hora.
        def m(h):
            hh, mm = h.split(":")
            return int(hh) * 60 + int(mm)
        cantidades = {}
        for t in self.horario["temporadas"]:
            self.assertEqual(set(t["dias"]), {"lun_mie", "mar_jue_vie", "sab", "dom"})
            for dia, g in t["dias"].items():
                ida, vuelta = g["isla_riesco"], g["villa_ponsomby"]
                self.assertEqual(len(ida), len(vuelta), (t["nombre"], dia))
                self.assertEqual(ida, sorted(ida))
                for a, b in zip(ida, vuelta):
                    self.assertEqual(m(b) - m(a), 10 if not (t["nombre"] == "invierno" and dia == "lun_mie"
                                                            and a == "19:00") else 20, (t["nombre"], dia, a, b))
                cantidades[(t["nombre"], dia)] = len(ida)
        # Cantidad de cruces por sentido, contada en la imagen oficial.
        self.assertEqual(cantidades, {
            ("invierno", "lun_mie"): 9, ("invierno", "mar_jue_vie"): 6, ("invierno", "sab"): 7, ("invierno", "dom"): 5,
            ("verano", "lun_mie"): 9, ("verano", "mar_jue_vie"): 6, ("verano", "sab"): 7, ("verano", "dom"): 5,
        })

    def test_pantalla_usa_el_horario_y_el_estado_de_tabsa(self):
        app = (CARPETA / "app.js").read_text(encoding="utf-8")
        self.assertIn("datos/horario-rio-verde.json", app)
        self.assertIn('tabsa: "rio_verde"', app)
        self.assertIn("Horario oficial TABSA · posición estimada", app)
        self.assertIn('data-ruta="rv"', (CARPETA / "index.html").read_text(encoding="utf-8"))

    def test_porvenir_usa_la_duracion_de_tabsa(self):
        self.assertIn("duracion_min: 120", (CARPETA / "app.js").read_text(encoding="utf-8"))


class ReglasTest(unittest.TestCase):
    def archivos(self):
        return [p for p in CARPETA.rglob("*") if p.suffix in {".js", ".html", ".css", ".json"}]

    def test_sin_claves_ni_aisstream(self):
        for p in self.archivos():
            texto = p.read_text(encoding="utf-8")
            for prohibido in ("APIKey", "AISSTREAM_API_KEY", "stream.aisstream.io"):
                self.assertNotIn(prohibido, texto, f"{p.name} contiene {prohibido}")

    def test_creditos_de_openstreetmap(self):
        html = (CARPETA / "index.html").read_text(encoding="utf-8")
        self.assertIn("openstreetmap.org/copyright", html)
        self.assertIn("AttributionControl", (CARPETA / "mapa.js").read_text(encoding="utf-8"))

    def test_mapa_vectorial_sin_satelite_y_version_fija(self):
        todo = "".join(p.read_text(encoding="utf-8") for p in self.archivos())
        self.assertIn("tiles.openfreemap.org", todo)
        self.assertNotRegex(todo.lower(), r"satellite|arcgisonline|mapbox\.satellite|esri")
        self.assertRegex(todo, r"maplibre-gl@\d+\.\d+\.\d+/")  # versión exacta, no "latest"

    def test_avisa_que_es_simulacion_y_respeta_movimiento_reducido(self):
        html = (CARPETA / "index.html").read_text(encoding="utf-8")
        self.assertIn("Simulación · datos de ejemplo", html)
        self.assertIn("prefers-reduced-motion", (CARPETA / "estilos.css").read_text(encoding="utf-8"))
        self.assertIn("prefers-reduced-motion", (CARPETA / "app.js").read_text(encoding="utf-8"))

    def test_fuentes_con_el_mismo_formato(self):
        campos = ("mmsi", "nombre", "naviera", "lat", "lon", "velocidad_nudos", "rumbo", "hora_utc")
        # movimiento.js arma el registro común que usan la simulación y el horario real
        for archivo in ("movimiento.js", "fuente-ais.js"):
            texto = (CARPETA / archivo).read_text(encoding="utf-8")
            for c in campos:
                self.assertTrue(re.search(rf"\b{c}\b", texto), f"{archivo} no menciona {c}")


class AccesoDesdeLaWebTest(unittest.TestCase):
    def test_boton_en_la_pagina_principal(self):
        from datetime import datetime, timezone
        from corredor import conditions, web
        from .helpers import TempDataDir

        class Pagina(TempDataDir):
            def runTest(self):
                pass

        t = Pagina()
        t.setUp()
        try:
            now = datetime(2026, 11, 22, 15, 0, tzinfo=timezone.utc)
            html = web.render(conditions.snapshot(now=now, fetch_forecast=False), now=now)
        finally:
            t.doCleanups()
        self.assertIn('href="en-vivo/index.html"', html)
        self.assertIn("Ver ferris en vivo", html)
        self.assertIn("demo", html)  # se avisa que es una demo

    def test_pages_copia_la_pantalla(self):
        wf = (CARPETA.parent.parent / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
        self.assertIn("cp -r paginas/en-vivo _site/en-vivo", wf)


if __name__ == "__main__":
    unittest.main()
