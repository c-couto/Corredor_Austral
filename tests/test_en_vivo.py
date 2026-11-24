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
        for archivo in ("fuente-simulada.js", "fuente-ais.js"):
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
