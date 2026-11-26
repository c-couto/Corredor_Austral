"""Evaluación: compara lo predicho con lo que hizo TABSA, sin mirar el futuro."""

from datetime import datetime, timedelta, timezone

from corredor import evaluacion, model, storage
from corredor.timeutil import format_ts

from .helpers import TempDataDir

T0 = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def corrida(t, rafaga, estado):
    ts = format_ts(t)
    storage.append_rows(storage.WEATHER, [
        {"ts_utc": ts, "place": p, "gust_kmh": rafaga, "wind_kmh": rafaga * 0.6, "wind_dir_deg": 270}
        for p in ("punta_delgada", "bahia_azul")])
    storage.append_rows(storage.TABSA_STATE, [{"ts_utc": ts, "crossing": "primera_angostura", "status": estado}])


def pronostico(emitido, horas_rafaga):
    storage.append_rows(storage.FORECAST_SNAPSHOTS, [
        {"issued_utc": format_ts(emitido), "place": p, "valid_utc": format_ts(v), "lead_h": 0,
         "gust_kmh": g, "wind_kmh": g * 0.6, "wind_dir_deg": 270}
        for v, g in horas_rafaga for p in ("punta_delgada", "bahia_azul")])


class EvaluacionTest(TempDataDir):
    def test_mide_la_probabilidad_que_dabamos_antes_de_la_suspension(self):
        # 3 h antes el pronóstico ya anunciaba 98 km/h para las 15:00 (la regla base de este cruce marca rojo desde 94)
        pronostico(T0, [(T0 + timedelta(hours=3), 98)])
        corrida(T0 + timedelta(hours=2, minutes=30), 40, "NORMAL")
        corrida(T0 + timedelta(hours=3), 100, "SUSPENDIDO")
        corrida(T0 + timedelta(hours=3, minutes=30), 105, "SUSPENDIDO")
        corrida(T0 + timedelta(hours=4), 45, "NORMAL")
        res = evaluacion.evaluar(historial=[])["primera_angostura"]
        self.assertEqual(len(res["episodios"]), 1)
        ep = res["episodios"][0]
        self.assertAlmostEqual(ep["p0"], model.prior_probability(100, "primera_angostura"))
        self.assertAlmostEqual(ep["p3"], model.prior_probability(98, "primera_angostura"))   # lo que decía el pronóstico 3 h antes
        self.assertIsNone(ep["p24"])                                     # no había pronóstico de 24 h antes
        m0 = res["metricas"][0]
        self.assertEqual((m0["n"], m0["suspensiones"], m0["detectadas_50"], m0["falsas_alarmas_50"]), (4, 2, 2, 0))
        self.assertLess(m0["brier"], m0["brier_referencia"])  # la regla base le gana a "decir el promedio"
        pct = round(model.prior_probability(98, "primera_angostura") * 100)
        self.assertIn(f"3 h antes: {pct} %", evaluacion.texto({"primera_angostura": res}))  # regla base con 98 km/h

    def test_no_usa_pronosticos_del_futuro_ni_demasiado_viejos(self):
        corrida(T0, 30, "NORMAL")
        pronostico(T0 + timedelta(minutes=10), [(T0, 90)])          # emitido DESPUÉS: no vale
        pronostico(T0 - timedelta(hours=8), [(T0, 90)])             # demasiado viejo para "3 h antes"
        fila = evaluacion.evaluar(historial=[])["primera_angostura"]["filas"][0]
        self.assertNotIn("p3", fila)

    def test_usa_el_modelo_vigente_en_ese_momento(self):
        entrenado = model.RouteModel(kind="trained", weights=[0, 0, 0, 0], bias=2.0,
                                     means=[0, 0, 0, 0], stds=[1, 1, 1, 1])
        hist = [(T0 + timedelta(days=1), {"primera_angostura": entrenado})]   # entrenado DESPUÉS
        self.assertEqual(evaluacion.modelo_vigente("primera_angostura", T0, hist).kind, "prior")
        self.assertEqual(evaluacion.modelo_vigente("primera_angostura", T0 + timedelta(days=2), hist).kind, "trained")

    def test_sin_suspensiones_lo_dice(self):
        corrida(T0, 30, "NORMAL")
        txt = evaluacion.texto(evaluacion.evaluar(historial=[]))
        self.assertIn("no aplica", txt)
        self.assertIn("todavía no se puede medir", txt)

    def test_no_escribe_en_data(self):
        corrida(T0, 30, "NORMAL")
        antes = sorted(p.relative_to(self.data_dir) for p in self.data_dir.rglob("*"))
        evaluacion.evaluar(historial=[])
        self.assertEqual(sorted(p.relative_to(self.data_dir) for p in self.data_dir.rglob("*")), antes)
