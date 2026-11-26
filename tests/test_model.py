"""Modelo de riesgo: regla base, aprendizaje y protecciones."""

import random
import unittest
from datetime import datetime, timedelta, timezone

from corredor import config, model, storage

from .helpers import TempDataDir

T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)


def synthetic(n, threshold=60.0, seed=1):
    """Datos simulados: se suspende (casi siempre) cuando la ráfaga pasa el umbral."""
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        g = rnd.uniform(15, 100)
        y = 1 if rnd.random() < model.sigmoid((g - threshold) / 4) else 0
        out.append((T0 + timedelta(minutes=30 * i), model.vector(g, g * 0.6, rnd.uniform(0, 360)), y))
    return out


class PriorTest(unittest.TestCase):
    def test_regla_base_coincide_con_los_niveles(self):
        self.assertEqual(model.level_for_prob(model.prior_probability(45)), "bajo")
        self.assertEqual(model.level_for_prob(model.prior_probability(55)), "medio")
        self.assertEqual(model.level_for_prob(model.prior_probability(75)), "alto")
        self.assertIsNone(model.prior_probability(None))

    def test_estado_normal_o_no(self):
        self.assertEqual(model.is_disrupted("NORMAL"), 0)
        self.assertEqual(model.is_disrupted(" normal "), 0)
        self.assertEqual(model.is_disrupted("SUSPENDIDO"), 1)


class TrainTest(unittest.TestCase):
    def test_pocos_datos_usa_la_regla_base(self):
        m = model.train(synthetic(30))
        self.assertEqual(m.kind, "prior")
        self.assertIn("hacen falta", m.reason)

    def test_sin_suspensiones_usa_la_regla_base(self):
        s = [(t, x, 0) for t, x, _ in synthetic(500)]
        self.assertEqual(model.train(s).kind, "prior")

    def test_aprende_el_umbral_real_y_supera_a_la_regla_base(self):
        m = model.train(synthetic(1500, threshold=60))
        self.assertEqual(m.kind, "trained")
        self.assertLess(m.metrics["brier_modelo"], m.metrics["brier_regla_base"])
        self.assertGreater(m.metrics["auc_modelo"], 0.9)
        self.assertLess(m.predict(45, 27, 270), 0.2)
        self.assertGreater(m.predict(75, 45, 270), 0.8)
        p60 = m.predict(60, 36, 270)
        self.assertTrue(0.3 < p60 < 0.7, p60)  # la regla base diría ~26 %


class TrainingDataTest(TempDataDir):
    def test_junta_viento_y_estado_de_la_misma_corrida(self):
        ts = ["2026-11-17T12:00:00Z", "2026-11-17T12:30:00Z"]
        storage.append_rows(storage.WEATHER, [
            {"ts_utc": ts[0], "place": "punta_delgada", "gust_kmh": 40, "wind_kmh": 25, "wind_dir_deg": 270},
            {"ts_utc": ts[0], "place": "bahia_azul", "gust_kmh": 45, "wind_kmh": 20, "wind_dir_deg": 270},
            {"ts_utc": ts[1], "place": "punta_delgada", "gust_kmh": 80, "wind_kmh": 50, "wind_dir_deg": 270},
        ])
        storage.append_rows(storage.TABSA_STATE, [
            {"ts_utc": ts[0], "crossing": "primera_angostura", "status": "NORMAL"},
            {"ts_utc": ts[1], "crossing": "primera_angostura", "status": "SUSPENDIDO"},
            {"ts_utc": "2026-11-17T13:00:00Z", "crossing": "primera_angostura", "status": "NORMAL"},  # sin clima
        ])
        s = model.samples_for("primera_angostura")
        self.assertEqual([(x[0], x[1], y) for _, x, y in s], [(45.0, 25.0, 0), (80.0, 50.0, 1)])

    def test_salidas_programadas_cerca_de_su_horario(self):
        ts = "2026-11-17T12:30:00Z"  # 09:30 local
        storage.append_rows(storage.WEATHER, [
            {"ts_utc": ts, "place": "punta_arenas", "gust_kmh": 70, "wind_kmh": 40, "wind_dir_deg": 250}])
        storage.append_rows(storage.TABSA_SAILINGS, [
            {"ts_utc": ts, "date": "2026-11-17", "departure": "09:00", "origin": "Punta Arenas",
             "destination": "Porvenir", "status": "SUSPENDIDO"},   # 30 min antes: cuenta
            {"ts_utc": ts, "date": "2026-11-17", "departure": "18:00", "origin": "Punta Arenas",
             "destination": "Porvenir", "status": "NORMAL"},       # lejos: no cuenta
        ])
        self.assertEqual([y for _, _, y in model.samples_for("punta_arenas_porvenir")], [1])

    def test_zarpes_de_otras_rutas_no_se_usan_para_entrenar(self):
        ts = "2026-11-19T08:30:00Z"  # 05:30 local
        storage.append_rows(storage.WEATHER, [
            {"ts_utc": ts, "place": "punta_arenas", "gust_kmh": 70, "wind_kmh": 40, "wind_dir_deg": 250}])
        storage.append_rows(storage.TABSA_SAILINGS, [
            {"ts_utc": ts, "date": "2026-11-19", "departure": "05:00", "origin": "Puerto Natales",
             "destination": "Puerto Edén", "status": "SUSPENDIDO"},      # otra ruta: no cuenta
            {"ts_utc": ts, "date": "2026-11-19", "departure": "06:00", "origin": "Punta Arenas",
             "destination": "Puerto Williams", "status": "SUSPENDIDO"},  # otra ruta: no cuenta
            {"ts_utc": ts, "date": "2026-11-19", "departure": "06:00", "origin": "Porvenir",
             "destination": "Punta Arenas", "status": "NORMAL"},         # este cruce: cuenta
        ])
        self.assertEqual([y for _, _, y in model.samples_for("punta_arenas_porvenir")], [0])

    def test_reconoce_el_cruce_aunque_cambie_la_escritura(self):
        self.assertTrue(model.is_route_sailing({"origin": "PUNTA  ARENAS", "destination": "Pórvenir"},
                                               "punta_arenas_porvenir"))
        self.assertFalse(model.is_route_sailing({"origin": "Porvenir", "destination": "Porvenir"},
                                                "punta_arenas_porvenir"))
        self.assertFalse(model.is_route_sailing({"origin": "Punta Arenas", "destination": "Porvenir"},
                                                "primera_angostura"))

    def test_guardar_y_cargar(self):
        models = model.train_all()
        self.assertTrue(model.model_path().exists())
        self.assertFalse(model.is_stale())
        loaded = model.load()
        self.assertEqual(set(loaded), set(config.ROUTES))
        self.assertEqual(loaded["primera_angostura"].kind, models["primera_angostura"].kind)

    def test_sin_modelo_guardado_usa_regla_base(self):
        self.assertTrue(model.is_stale())
        self.assertAlmostEqual(model.load()["rio_verde"].predict(85), 0.5)
        self.assertAlmostEqual(model.load()["primera_angostura"].predict(94), 0.5)
        self.assertEqual(model.load()["punta_arenas_porvenir"].predict(70), 0.5)


def tormentas(n_normal, bloques, seed=3):
    """Serie con temporales claros: bloques de 10 lecturas tranquilas y 3 con ráfagas de ~85 km/h."""
    rnd = random.Random(seed)
    out, i = [], 0
    for b in range(bloques):
        for y, base in [(0, 30)] * 10 + [(1, 85)] * 3:
            g = base + rnd.uniform(-8, 8)
            out.append((T0 + timedelta(minutes=30 * i), model.vector(g, g * 0.6, 270.0), y))
            i += 1
    return out


class ValidacionHonestaTest(unittest.TestCase):
    def test_sin_temporales_en_la_prueba_nunca_pasa_a_aprendido(self):
        # 20 temporales en lo viejo, pero lo más reciente (20 %) es todo tranquilo: no se puede probar.
        s = tormentas(0, 20)
        cut = int(len(s) * 0.8)
        s = s[:cut] + [(t, x, 0) for t, x, _ in s[cut:]]
        m = model.train(s, events=20)
        self.assertEqual(m.kind, "prior")
        self.assertIn("datos nuevos para probar", m.reason)

    def test_un_solo_temporal_en_la_prueba_no_alcanza(self):
        # Lo reciente tiene 1 temporal de varias lecturas: son 2 lecturas del mismo temporal, no 2 temporales.
        s = tormentas(0, 20)
        cut = int(len(s) * 0.8)
        reciente = [(t, x, 0) for t, x, _ in s[cut:]]
        for k in (10, 11, 12):  # un único temporal
            t, x, _ = reciente[k]
            reciente[k] = (t, model.vector(88, 52, 270.0), 1)
        m = model.train(s[:cut] + reciente, events=20)
        self.assertEqual(model.distinct_events(reciente), 1)
        self.assertEqual(m.kind, "prior")

    def test_con_dos_temporales_en_la_prueba_y_ganandole_a_la_regla_base_aprende(self):
        s = tormentas(0, 25)
        self.assertGreaterEqual(model.distinct_events(s[int(len(s) * 0.8):]), 2)
        m = model.train(s, events=25)
        self.assertEqual(m.kind, "trained")
        self.assertEqual(m.metrics["evaluado_en"], "datos nuevos (20 % más reciente)")
        self.assertGreaterEqual(m.metrics["temporales_prueba"], 2)
        self.assertLess(m.metrics["brier_modelo"], m.metrics["brier_regla_base"])

    def test_cuenta_temporales_distintos(self):
        y = [0, 1, 1, 1, 0, 0, 1, 0, 1, 1]
        s = [(T0 + timedelta(minutes=30 * i), model.vector(50, 30, None), v) for i, v in enumerate(y)]
        self.assertEqual(model.distinct_events(s), 3)
        self.assertEqual(model.distinct_events(s[1:4]), 0)  # arranca "adentro": puede venir de antes


class ReglaBasePorCruceTest(unittest.TestCase):
    def test_porvenir_sigue_con_la_regla_general(self):
        ruta = "punta_arenas_porvenir"
        self.assertEqual(config.PRIOR_BY_ROUTE[ruta], (config.PRIOR_CENTER_KMH, config.PRIOR_SCALE_KMH))
        self.assertAlmostEqual(model.RouteModel(route=ruta).predict(70), 0.5)
        self.assertAlmostEqual(model.RouteModel(route=ruta).predict(50), model.prior_probability(50))

    def test_primera_angostura_rojo_desde_94_y_amarillo_desde_79(self):
        pa = model.RouteModel(route="primera_angostura")
        self.assertAlmostEqual(pa.predict(94), 0.5)
        self.assertAlmostEqual(pa.predict(79), 0.2, places=2)
        self.assertLess(pa.predict(70), 0.2)    # a 70 es "normal" (TABSA operó con ráfagas de hasta 91)
        self.assertLess(pa.predict(78), 0.2)
        self.assertGreater(pa.predict(80), 0.2)

    def test_rio_verde_aguanta_mas_viento(self):
        rv = model.RouteModel(route="rio_verde")
        self.assertAlmostEqual(rv.predict(85), 0.5)
        self.assertLess(rv.predict(81), 0.5)    # operó normal con 81 km/h
        self.assertLess(rv.predict(60), 0.2)    # a 60 sigue siendo "normal" (antes ya daba 'medio')

    def test_cada_cruce_puede_tener_su_umbral(self):
        from unittest import mock
        with mock.patch.dict(config.PRIOR_BY_ROUTE, {"primera_angostura": (80.0, 14.4)}):
            self.assertAlmostEqual(model.RouteModel(route="primera_angostura").predict(80), 0.5)
            self.assertLess(model.RouteModel(route="primera_angostura").predict(70), 0.5)
            self.assertAlmostEqual(model.RouteModel(route="punta_arenas_porvenir").predict(70), 0.5)
        self.assertAlmostEqual(model.RouteModel(route="primera_angostura").predict(94), 0.5)


class EventosTest(TempDataDir):
    """Se cuenta por temporal y por zarpe, no por lectura de 30 min."""

    def estado(self, *pares):
        storage.append_rows(storage.TABSA_STATE, [
            {"ts_utc": ts, "crossing": "primera_angostura", "status": st} for ts, st in pares])

    def test_un_temporal_largo_cuenta_una_vez(self):
        # 3,5 h suspendido = 7 lecturas, pero es 1 temporal. Después, otro.
        horas = [f"2026-11-24T{h:02d}:{m:02d}:00Z" for h in range(14, 22) for m in (0, 30)]
        self.estado(*[(t, "NORMAL") for t in horas[:2]],
                    *[(t, "SUSPENDIDO") for t in horas[2:9]],
                    *[(t, "NORMAL") for t in horas[9:12]],
                    *[(t, "SUSPENDIDO") for t in horas[12:]])
        self.assertEqual(model.events_for("primera_angostura"), 2)

    def test_cada_zarpe_cancelado_una_vez_con_su_ultimo_estado(self):
        def z(ts, dep, st, origin="Punta Arenas", dest="Porvenir"):
            return {"ts_utc": ts, "date": "2026-11-24", "departure": dep, "origin": origin,
                    "destination": dest, "status": st}
        storage.append_rows(storage.TABSA_SAILINGS, [
            z("2026-11-24T10:00:00Z", "09:00", "CANCELADO"),
            z("2026-11-24T10:30:00Z", "09:00", "CANCELADO"),     # el mismo zarpe leído otra vez
            z("2026-11-24T10:00:00Z", "14:00", "CANCELADO"),
            z("2026-11-24T12:00:00Z", "14:00", "NORMAL"),        # después lo reprogramaron normal
            z("2026-11-24T10:00:00Z", "11:00", "CANCELADO", "Porvenir", "Punta Arenas"),
            z("2026-11-24T10:00:00Z", "06:00", "CANCELADO", "Punta Arenas", "Puerto Williams"),  # otra ruta
        ])
        self.assertEqual(model.events_for("punta_arenas_porvenir"), 2)

    def test_muchas_lecturas_de_pocos_temporales_no_alcanzan_para_aprender(self):
        s = synthetic(1500, threshold=60)
        self.assertEqual(model.train(s).kind, "trained")             # contando lecturas, aprendería
        m = model.train(s, events=2)                                  # pero son solo 2 temporales
        self.assertEqual(m.kind, "prior")
        self.assertEqual(m.n_events, 2)
        self.assertIn("2 y 1500", m.reason)
        self.assertEqual(model.train(s, events=8).kind, "trained")


if __name__ == "__main__":
    unittest.main()
