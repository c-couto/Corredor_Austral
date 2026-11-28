"""Camión desde Buenos Aires: ¿llega a tiempo para cruzar Primera Angostura?"""

import json
import re
import shutil
import subprocess
import unittest
from datetime import timedelta

from corredor import conditions, web

from .helpers import TempDataDir
from .test_web_alerts import NOW, add_forecast, add_run

NODE = shutil.which("node")


class SeccionCamionTest(TempDataDir):
    def pagina(self):
        add_run(NOW - timedelta(minutes=5), {"punta_delgada": 40, "bahia_azul": 40, "punta_arenas": 20}, "NORMAL")
        add_forecast(NOW, [40 + i for i in range(48)])
        return web.render(conditions.snapshot(now=NOW, fetch_forecast=False), now=NOW)

    def test_aparece_con_pronostico_y_aclara_el_supuesto(self):
        html = self.pagina()
        self.assertIn('id="camion"', html)
        self.assertIn("Camión desde Buenos Aires", html)
        self.assertIn("son un supuesto", html)
        datos = json.loads(re.search(r'id="camion-data">(.*?)</script>', html, re.S).group(1))
        self.assertEqual(len(datos["hours"]), 48)
        self.assertEqual(datos["horas"], 48)

    def test_sin_pronostico_no_se_muestra(self):
        add_run(NOW - timedelta(minutes=5), {"punta_delgada": 40}, "NORMAL")
        html = web.render(conditions.snapshot(now=NOW, fetch_forecast=False), now=NOW)
        self.assertNotIn('id="camion"', html)


@unittest.skipUnless(NODE, "hace falta node")
class LogicaCamionTest(unittest.TestCase):
    H = 3600e3

    def resultado(self, dep_h, viaje_h):
        # pronóstico: 48 h desde t=0, probabilidad 0,1 salvo 0,6 en la hora 30
        horas = [[int(i * self.H), 0.6 if i == 30 else 0.1] for i in range(48)]
        js = web.CAMION_JS_FN + f"""
        var d={{hours:{json.dumps(horas)}}};
        console.log(JSON.stringify(camionResultado(d,{dep_h}*3600e3,{viaje_h})));"""
        out = subprocess.run([NODE, "-e", js], capture_output=True, text=True, check=True).stdout
        return json.loads(out)

    def test_llega_dentro_del_pronostico(self):
        r = self.resultado(0, 20)
        self.assertEqual(r["tipo"], "pronostico")
        self.assertAlmostEqual(r["p"], 0.1)

    def test_toma_la_hora_de_llegada_y_avisa_la_peor_cercana(self):
        r = self.resultado(-18, 48)           # sale hace 18 h, 48 h de viaje -> llega en la hora 30
        self.assertEqual(r["tipo"], "pronostico")
        self.assertAlmostEqual(r["p"], 0.6)
        r = self.resultado(-17, 48)           # llega en la hora 31: la peor hora cercana (30) es 0,6
        self.assertAlmostEqual(r["p"], 0.1)
        self.assertAlmostEqual(r["peor"], 0.6)

    def test_mas_alla_del_pronostico_no_inventa_un_numero(self):
        r = self.resultado(0, 48 + 10)
        self.assertEqual(r["tipo"], "fuera")
        self.assertNotIn("p", r)
        self.assertEqual(r["desde"], r["arr"] - 47 * self.H)   # desde cuándo se podrá calcular

    def test_hora_pasada(self):
        self.assertEqual(self.resultado(-100, 10)["tipo"], "pasada")


if __name__ == "__main__":
    unittest.main()
