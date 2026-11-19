"""Lector de TABSA, MET Norway y búsqueda del navegador."""

import io
import os
import unittest
from contextlib import redirect_stderr
from unittest import mock

from corredor import browser
from corredor.sources import met_norway, tabsa

from .helpers import tabsa_fixture_html


class TabsaParseTest(unittest.TestCase):
    def test_lee_la_pagina_real_guardada(self):
        page = tabsa.parse(tabsa_fixture_html())
        self.assertEqual([(c.key, c.name, c.status) for c in page.crossings],
                         [("primera_angostura", "Primera Angostura", "NORMAL"), ("rio_verde", "Rio Verde", "NORMAL")])
        self.assertEqual(page.crossings[0].icon, "EstadoCruceEnViaje")
        self.assertEqual(len(page.sailings), 6)
        first, last = page.sailings[0], page.sailings[-1]
        self.assertEqual((first.date, first.origin, first.destination, first.boarding, first.departure),
                         ("2026-11-17", "Punta Arenas", "Porvenir", "08:00", "09:00"))
        self.assertEqual((last.date, last.departure, last.origin), ("2026-11-18", "20:30", "Porvenir"))

    def test_estado_suspendido_en_mayusculas(self):
        html = tabsa_fixture_html().replace('<td class="align-left bold">NORMAL</td>',
                                            '<td class="align-left bold">Suspendido</td>', 1)
        self.assertEqual(tabsa.parse(html).crossings[0].status, "SUSPENDIDO")

    def test_si_falta_la_tabla_de_estado_falla_en_vez_de_inventar(self):
        with self.assertRaises(tabsa.TabsaFormatError):
            tabsa.parse("<html><body><div id='root'></div></body></html>")  # sin JavaScript renderizado

    def test_una_fila_rara_de_zarpes_no_tumba_la_lectura(self):
        with redirect_stderr(io.StringIO()):
            page = tabsa.parse(tabsa_fixture_html().replace("09:00", "a confirmar"))
        self.assertEqual([c.status for c in page.crossings], ["NORMAL", "NORMAL"])  # el estado se guarda
        self.assertEqual(len(page.sailings), 5)                                    # se saltea solo esa fila
        self.assertIn("a confirmar", page.skipped[0])

    def test_hora_con_fecha_entre_parentesis(self):
        # Caso real del 18/11/2026: Puerto Natales -> Puerto Edén, embarque "20:00 (18-11)".
        row = ('<tr><td>Puerto Natales</td><td>Puerto Edén</td><td>20:00 (18-11)</td><td>05:00</td>'
               '<td class="align-right"><img src="/static/media/EstadoCruceEnViaje.x.svg"></td>'
               '<td class="align-left bold">NORMAL</td></tr>')
        html = tabsa_fixture_html().replace("</tbody></table>", row + "</tbody></table>", 2)
        page = tabsa.parse(html)
        self.assertEqual(page.skipped, [])
        eden = [s for s in page.sailings if s.destination == "Puerto Edén"]
        self.assertTrue(eden)
        self.assertEqual((eden[0].boarding, eden[0].departure, eden[0].status), ("20:00 (18-11)", "05:00", "NORMAL"))

    def test_zarpe_con_fecha_propia_y_cambio_de_anio(self):
        self.assertEqual(tabsa._with_day("2026-11-19", None, None), "2026-11-19")
        self.assertEqual(tabsa._with_day("2026-11-19", "20", "11"), "2026-11-20")
        self.assertEqual(tabsa._with_day("2026-12-31", "1", "1"), "2027-01-01")
        self.assertEqual(tabsa._with_day("2027-01-01", "31", "12"), "2026-12-31")

    def test_slug(self):
        self.assertEqual(tabsa.slug("Río Verde"), "rio_verde")
        self.assertEqual(tabsa.slug(" Primera  Angostura "), "primera_angostura")


class MetNorwayTest(unittest.TestCase):
    def response(self, hours=30):
        return {"properties": {"timeseries": [
            {"time": f"2026-11-17T{h % 24:02d}:00:00Z",
             "data": {"instant": {"details": {"air_temperature": 9.5, "wind_speed": 10.0,
                                              "wind_speed_of_gust": 15.0 + h, "wind_from_direction": 250}},
                      "next_1_hours": {"details": {"precipitation_amount": 0.2}}}}
            for h in range(hours)]}}

    def test_convierte_a_kmh_y_arma_el_pronostico(self):
        w = met_norway.parse(self.response())
        self.assertEqual(w["wind_kmh"], 36.0)       # 10 m/s
        self.assertEqual(w["gust_kmh"], 54.0)       # 15 m/s
        self.assertEqual(w["temp_c"], 9.5)
        self.assertEqual(w["precip_mm"], 0.2)
        self.assertEqual(w["forecast_gust_max_24h_kmh"], round((15 + 23) * 3.6, 1))
        self.assertEqual(len(w["hourly"]), 30)
        self.assertEqual(w["hourly"][0], {"t": "2026-11-17T00:00:00Z", "wind": 36.0, "gust": 54.0, "dir": 250.0})

    def test_respuesta_vacia_es_error(self):
        with self.assertRaises(ValueError):
            met_norway.parse({"properties": {"timeseries": []}})


class BrowserTest(unittest.TestCase):
    def test_respeta_chrome_path(self):
        with mock.patch.dict(os.environ, {"CHROME_PATH": "/opt/mi-chrome"}):
            self.assertEqual(browser.find_browser(), "/opt/mi-chrome")

    def test_sin_navegador_da_un_error_claro(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch("shutil.which", return_value=None), \
                mock.patch("pathlib.Path.exists", return_value=False):
            with self.assertRaises(browser.BrowserNotFound):
                browser.find_browser()


if __name__ == "__main__":
    unittest.main()
