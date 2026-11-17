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

    def test_guardar_y_cargar(self):
        models = model.train_all()
        self.assertTrue(model.model_path().exists())
        self.assertFalse(model.is_stale())
        loaded = model.load()
        self.assertEqual(set(loaded), set(config.ROUTES))
        self.assertEqual(loaded["primera_angostura"].kind, models["primera_angostura"].kind)

    def test_sin_modelo_guardado_usa_regla_base(self):
        self.assertTrue(model.is_stale())
        self.assertEqual(model.load()["rio_verde"].predict(70), 0.5)


if __name__ == "__main__":
    unittest.main()
