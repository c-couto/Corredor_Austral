import unittest

from corredor import config, storage
from corredor.collect import collect_once

from .helpers import TempDataDir, fake_urlopen, open_meteo_response

N_WEATHER = len(config.PLACES)
N_MARINE = len(config.MARINE_PLACES)


class CollectOnceTest(TempDataDir):
    def test_corrida_normal(self):
        with fake_urlopen([open_meteo_response(N_WEATHER), open_meteo_response(N_MARINE)]) as m:
            self.assertEqual(collect_once(), (N_WEATHER, N_MARINE))
        self.assertEqual(m.call_count, 2)  # una consulta de clima y una de oleaje

        weather = storage.read_rows(storage.WEATHER)
        self.assertEqual([r["place"] for r in weather], list(config.PLACES))
        self.assertEqual(len({r["ts_utc"] for r in weather}), 1)  # misma hora para toda la corrida
        self.assertEqual(weather[0]["gust_kmh"], "30.0")
        self.assertEqual(weather[0]["forecast_gust_max_24h_kmh"], "45.0")
        self.assertEqual([r["place"] for r in storage.read_rows(storage.MARINE)], list(config.MARINE_PLACES))
        self.assertEqual(storage.read_rows(storage.ERRORS), [])

    def test_si_falla_el_clima_anota_el_error_y_sigue_con_el_oleaje(self):
        with fake_urlopen([TimeoutError("sin respuesta")] * 4 + [open_meteo_response(N_MARINE)]):
            self.assertEqual(collect_once(), (0, N_MARINE))
        self.assertEqual(storage.read_rows(storage.WEATHER), [])
        self.assertEqual(len(storage.read_rows(storage.MARINE)), N_MARINE)
        errors = storage.read_rows(storage.ERRORS)
        self.assertEqual([(e["where_"], e["error"]) for e in errors], [("weather", "sin respuesta")])

    def test_si_llegan_menos_lugares_no_guarda_filas_mezcladas(self):
        with fake_urlopen([open_meteo_response(N_WEATHER - 2), open_meteo_response(N_MARINE)]):
            self.assertEqual(collect_once(), (0, N_MARINE))
        self.assertIn("llegaron", storage.read_rows(storage.ERRORS)[0]["error"])


if __name__ == "__main__":
    unittest.main()
