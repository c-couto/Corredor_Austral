import json
import unittest

from corredor import config, forecast, storage
from corredor.collect import collect_once
from corredor.sources import tabsa

from .helpers import TempDataDir, fake_urlopen, open_meteo_response, tabsa_fixture_html

N_WEATHER = len(config.PLACES)
N_MARINE = len(config.MARINE_PLACES)


def tabsa_ok():
    return tabsa.parse(tabsa_fixture_html())


def tabsa_with(status_pa="NORMAL", sailing_status="NORMAL"):
    html = tabsa_fixture_html()
    html = html.replace("Primera Angostura</td>", "Primera Angostura</td>", 1)
    page = tabsa.parse(html)
    page.crossings[0] = tabsa.CrossingState("primera_angostura", "Primera Angostura", status_pa, "x")
    page.sailings[0] = tabsa.Sailing(**{**page.sailings[0].__dict__, "status": sailing_status})
    return lambda: page


def tabsa_broken():
    raise tabsa.TabsaFormatError("no se encontró la tabla")


class CollectOnceTest(TempDataDir):
    def test_corrida_normal(self):
        with fake_urlopen([open_meteo_response(N_WEATHER, hours=48), open_meteo_response(N_MARINE)]) as m:
            r = collect_once(tabsa_fn=tabsa_ok)
        self.assertEqual((r.weather, r.marine, r.tabsa_crossings, r.tabsa_sailings), (N_WEATHER, N_MARINE, 2, 6))
        self.assertEqual(m.call_count, 2)  # una consulta de clima y una de oleaje

        weather = storage.read_rows(storage.WEATHER)
        self.assertEqual([r["place"] for r in weather], list(config.PLACES))
        self.assertEqual(len({r["ts_utc"] for r in weather}), 1)  # misma hora para toda la corrida
        self.assertEqual(weather[0]["gust_kmh"], "30.0")
        self.assertEqual(weather[0]["forecast_gust_max_24h_kmh"], "53.0")  # máx. de las primeras 24 h
        self.assertEqual([r["place"] for r in storage.read_rows(storage.MARINE)], list(config.MARINE_PLACES))
        self.assertEqual(storage.read_rows(storage.ERRORS), [])
        # Todas las fuentes comparten la hora de la corrida (así se cruzan para el modelo).
        self.assertEqual(storage.read_rows(storage.TABSA_STATE)[0]["ts_utc"], weather[0]["ts_utc"])

    def test_guarda_el_pronostico_horario_fuera_del_repo(self):
        with fake_urlopen([open_meteo_response(N_WEATHER, hours=48), open_meteo_response(N_MARINE)]):
            collect_once(tabsa_fn=tabsa_ok)
        data = json.loads((self.cache_dir / "pronostico.json").read_text(encoding="utf-8"))
        self.assertEqual(len(data["places"]["punta_delgada"]), 48)
        self.assertEqual(data["places"]["punta_delgada"][0], {"t": "2026-11-17T00:00:00Z", "wind": 20.0,
                                                              "gust": 30.0, "dir": 270.0})
        self.assertFalse((self.data_dir / "auto" / "pronostico.json").exists())

    def test_si_falla_el_clima_anota_el_error_y_sigue(self):
        with fake_urlopen([TimeoutError("sin respuesta")] * 4 + [open_meteo_response(N_MARINE)]):
            r = collect_once(tabsa_fn=tabsa_ok)
        self.assertEqual((r.weather, r.marine, r.tabsa_crossings), (0, N_MARINE, 2))
        self.assertEqual(storage.read_rows(storage.WEATHER), [])
        errors = storage.read_rows(storage.ERRORS)
        self.assertEqual([(e["where_"], e["error"]) for e in errors], [("weather", "sin respuesta")])

    def test_si_falla_tabsa_se_guarda_el_clima_igual(self):
        with fake_urlopen([open_meteo_response(N_WEATHER), open_meteo_response(N_MARINE)]):
            r = collect_once(tabsa_fn=tabsa_broken)
        self.assertEqual((r.weather, r.tabsa_crossings), (N_WEATHER, 0))
        self.assertEqual(storage.read_rows(storage.TABSA_STATE), [])
        self.assertEqual(storage.read_rows(storage.ERRORS)[0]["where_"], "tabsa")

    def test_si_llegan_menos_lugares_no_guarda_filas_mezcladas(self):
        with fake_urlopen([open_meteo_response(N_WEATHER - 2), open_meteo_response(N_MARINE)]):
            r = collect_once(tabsa_fn=tabsa_ok)
        self.assertEqual(r.weather, 0)
        self.assertIn("llegaron", storage.read_rows(storage.ERRORS)[0]["error"])

    def test_con_met_norway_no_se_usa_open_meteo(self):
        def met(places):
            return {p: {"gust_kmh": 40.0, "hourly": []} for p in places}
        r = collect_once(weather_fn=met, marine_fn=None, tabsa_fn=tabsa_ok, source_name="met-norway")
        self.assertEqual((r.weather, r.marine), (N_WEATHER, 0))
        self.assertEqual({row["source"] for row in storage.read_rows(storage.WEATHER)}, {"met-norway"})
        self.assertEqual(storage.read_rows(storage.MARINE), [])


class TabsaChangesTest(TempDataDir):
    def run_once(self, fn):
        with fake_urlopen([open_meteo_response(N_WEATHER), open_meteo_response(N_MARINE)]):
            return collect_once(tabsa_fn=fn)

    def test_primera_lectura_registra_el_estado_inicial(self):
        self.run_once(tabsa_ok)
        changes = storage.read_rows(storage.TABSA_CHANGES)
        self.assertEqual([(c["subject"], c["previous"], c["current"]) for c in changes],
                         [("primera_angostura", "", "NORMAL"), ("rio_verde", "", "NORMAL")])

    def test_sin_cambios_no_agrega_nada(self):
        self.run_once(tabsa_ok)
        r = self.run_once(tabsa_ok)
        self.assertEqual(r.tabsa_changes, 0)
        self.assertEqual(len(storage.read_rows(storage.TABSA_STATE)), 4)  # pero sí guarda cada muestra

    def test_detecta_suspension_y_reanudacion(self):
        self.run_once(tabsa_ok)
        self.run_once(tabsa_with(status_pa="SUSPENDIDO"))
        self.run_once(tabsa_ok)
        changes = [(c["subject"], c["previous"], c["current"]) for c in storage.read_rows(storage.TABSA_CHANGES)][2:]
        self.assertEqual(changes, [("primera_angostura", "NORMAL", "SUSPENDIDO"),
                                   ("primera_angostura", "SUSPENDIDO", "NORMAL")])

    def test_detecta_cambio_de_una_salida_programada(self):
        self.run_once(tabsa_ok)
        self.run_once(tabsa_with(sailing_status="SUSPENDIDO"))
        last = storage.read_rows(storage.TABSA_CHANGES)[-1]
        self.assertEqual((last["subject"], last["previous"], last["current"]),
                         ("2026-11-17 09:00 Punta Arenas -> Porvenir", "NORMAL", "SUSPENDIDO"))


class ForecastCacheTest(TempDataDir):
    def test_pronostico_viejo_no_se_usa_sin_refrescar(self):
        forecast.save("2026-01-01T00:00:00Z", "open-meteo", {"x": {"hourly": []}})
        self.assertIsNone(forecast.load(refresh=False))


if __name__ == "__main__":
    unittest.main()
