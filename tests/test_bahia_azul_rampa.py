"""Punto nuevo de Bahía Azul (rampa real): se recolecta, pero ninguna predicción lo usa todavía."""

import unittest
from datetime import timedelta

from corredor import conditions, config

from .helpers import TempDataDir
from .test_web_alerts import NOW, add_run

NUEVO = "bahia_azul_rampa"


class RampaBahiaAzulTest(TempDataDir):
    def test_se_recolecta_en_otra_celda_que_los_puntos_viejos(self):
        self.assertIn(NUEVO, config.PLACES)
        self.assertIn(NUEVO, config.PLACE_NAMES)
        # sigue estando el punto viejo (no se borra nada)
        self.assertIn("bahia_azul", config.PLACES)
        lat, lon = config.PLACES[NUEVO]
        self.assertAlmostEqual(lat, -52.4946, places=3)
        self.assertAlmostEqual(lon, -69.5200, places=3)
        self.assertNotEqual(config.PLACES[NUEVO], config.PLACES["bahia_azul"])

    def test_ningun_cruce_ni_guardado_de_pronosticos_lo_usa(self):
        for cfg in config.ROUTES.values():
            self.assertNotIn(NUEVO, cfg["places"])
        self.assertNotIn(NUEVO, config.SNAPSHOT_PLACES)    # el formato y tamaño de pronosticos/ no cambian
        self.assertNotIn(NUEVO, config.MARINE_PLACES)
        self.assertNotIn(NUEVO, config.PLANNER_ORIGINS)

    def test_con_o_sin_el_dato_nuevo_las_predicciones_son_iguales(self):
        add_run(NOW - timedelta(minutes=5), {"punta_delgada": 60, "bahia_azul": 60, "punta_arenas": 40}, "NORMAL")
        antes = {r.key: (r.gust_kmh, r.p_now) for r in conditions.snapshot(now=NOW, fetch_forecast=False).routes}
        add_run(NOW - timedelta(minutes=5), {NUEVO: 130})        # un viento enorme en el punto nuevo
        despues = {r.key: (r.gust_kmh, r.p_now) for r in conditions.snapshot(now=NOW, fetch_forecast=False).routes}
        self.assertEqual(antes, despues)


if __name__ == "__main__":
    unittest.main()
