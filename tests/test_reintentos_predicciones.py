"""Reintentos del clima (1 min entre intentos), TABSA antes que el clima y predicciones guardadas."""

import urllib.error
from unittest import mock

from corredor import conditions, config, storage
from corredor.collect import collect_once
from corredor.timeutil import parse_ts

from .helpers import TempDataDir, fake_urlopen, open_meteo_response
from .test_collect import N_MARINE, N_WEATHER, tabsa_ok

TIMEOUT = OSError("<urlopen error _ssl.c:1063: The handshake operation timed out>")


class ReintentosDelClimaTest(TempDataDir):
    def test_falla_dos_veces_y_anda_al_tercer_intento(self):
        with fake_urlopen([TIMEOUT, TIMEOUT, open_meteo_response(N_WEATHER, hours=48),
                           open_meteo_response(N_MARINE)]) as m:
            r = collect_once(tabsa_fn=tabsa_ok)
        self.assertEqual(m.call_count, 4)          # 3 de clima + 1 de oleaje
        self.assertEqual(r.weather, N_WEATHER)
        self.assertEqual(storage.read_rows(storage.ERRORS), [])

    def test_si_fallan_los_tres_queda_el_error_y_tabsa_se_guarda(self):
        with fake_urlopen([TIMEOUT, TIMEOUT, TIMEOUT, open_meteo_response(N_MARINE)]):
            r = collect_once(tabsa_fn=tabsa_ok)
        self.assertEqual((r.weather, r.tabsa_crossings, r.marine), (0, 2, N_MARINE))
        errores = storage.read_rows(storage.ERRORS)
        self.assertEqual([e["where_"] for e in errores], ["weather"])
        self.assertIn("handshake operation timed out", errores[0]["error"])
        self.assertEqual(len(storage.read_rows(storage.TABSA_STATE)), 2)
        self.assertEqual(storage.read_rows(storage.PREDICTIONS), [])  # sin clima nuevo no se predice

    def test_usa_las_esperas_largas_solo_para_el_clima(self):
        with mock.patch.object(config, "WEATHER_RETRY_WAITS_S", (61, 62)), \
                mock.patch.object(config, "RETRY_WAITS_S", (1, 2, 3)), \
                mock.patch("corredor.net.time.sleep") as dormir, \
                fake_urlopen([TIMEOUT, TIMEOUT, open_meteo_response(N_WEATHER, hours=48),
                              TIMEOUT, open_meteo_response(N_MARINE)]):
            collect_once(tabsa_fn=tabsa_ok)
        self.assertEqual([c.args[0] for c in dormir.call_args_list], [61, 62, 1])  # clima: 61, 62 · oleaje: 1

    def test_un_404_no_se_reintenta(self):
        e404 = urllib.error.HTTPError("https://api.open-meteo.com", 404, "Not Found", None, None)
        with fake_urlopen([e404, open_meteo_response(N_MARINE)]) as m:
            collect_once(tabsa_fn=tabsa_ok)
        self.assertEqual(m.call_count, 2)  # 1 de clima (sin reintentos) + 1 de oleaje

    def test_tabsa_se_lee_antes_que_el_clima(self):
        orden = []

        def tabsa_fn():
            orden.append("tabsa")
            return tabsa_ok()

        def clima(places):
            orden.append("clima")
            return {}

        collect_once(weather_fn=clima, marine_fn=None, tabsa_fn=tabsa_fn, source_name="test")
        self.assertEqual(orden, ["tabsa", "clima"])


class PrediccionesGuardadasTest(TempDataDir):
    def test_guarda_lo_mismo_que_muestra_la_web(self):
        # El pronóstico de prueba empieza el 17/11 00:00 UTC: la corrida simulada es a esa hora.
        with mock.patch.object(storage, "now_utc", return_value="2026-11-17T00:05:00Z"), \
                fake_urlopen([open_meteo_response(N_WEATHER, hours=48, gust=80), open_meteo_response(N_MARINE)]):
            collect_once(tabsa_fn=tabsa_ok)
        filas = storage.read_rows(storage.PREDICTIONS)
        self.assertTrue(filas)
        ts = filas[0]["emitido_utc"]
        self.assertTrue(all(f["emitido_utc"] == ts for f in filas))      # una sola corrida
        self.assertEqual({f["ruta"] for f in filas}, set(config.ROUTES))   # los 3 cruces
        snap = conditions.snapshot(now=parse_ts(ts), fetch_forecast=False)
        for st in snap.routes:
            ahora = next(f for f in filas if f["ruta"] == st.key and f["tipo"] == "ahora")
            self.assertAlmostEqual(float(ahora["prob"]), st.p_now, places=4)  # = medidor de la web
            self.assertEqual(ahora["modelo"], "regla base")
        horas = sorted({int(float(f["anticipacion_h"])) for f in filas if f["tipo"] == "hora"})
        self.assertTrue(set(horas) <= {1, 2, 3, 4, 5, 6, 9, 12, 18, 24, 36})
        self.assertIn(1, horas)

    def test_se_agrega_al_final_un_archivo_por_mes(self):
        for _ in range(2):
            with fake_urlopen([open_meteo_response(N_WEATHER, hours=48), open_meteo_response(N_MARINE)]):
                collect_once(tabsa_fn=tabsa_ok)
        archivos = storage.PREDICTIONS.files()
        self.assertEqual(len(archivos), 1)
        texto = archivos[0].read_text(encoding="utf-8")
        self.assertEqual(texto.count("emitido_utc"), 1)  # un solo encabezado

    def test_si_falla_el_calculo_no_rompe_la_corrida(self):
        with mock.patch("corredor.predicciones.filas", side_effect=ValueError("boom")), \
                fake_urlopen([open_meteo_response(N_WEATHER, hours=48), open_meteo_response(N_MARINE)]):
            r = collect_once(tabsa_fn=tabsa_ok)
        self.assertEqual((r.weather, r.tabsa_crossings), (N_WEATHER, 2))
        self.assertIn("predicciones", [e["where_"] for e in storage.read_rows(storage.ERRORS)])
