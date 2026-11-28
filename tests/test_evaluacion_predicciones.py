"""La evaluación con anticipación usa lo que predijimos de verdad (predicciones/), para los 3 cruces."""

import unittest
from datetime import datetime, timedelta, timezone

from corredor import evaluacion, model, storage
from corredor.timeutil import format_ts, local_to_utc

from .helpers import TempDataDir
from .test_evaluacion import T0, corrida, pronostico

E = datetime(2026, 11, 26, 12, 5, tzinfo=timezone.utc)


def pred(ruta, tipo, emitido, valido, a, prob, rafaga=None):
    storage.append_rows(storage.PREDICTIONS, [{
        "emitido_utc": format_ts(emitido), "ruta": ruta, "tipo": tipo, "valido_utc": format_ts(valido),
        "anticipacion_h": a, "prob": prob, "rafaga_kmh": rafaga, "modelo": "regla base", "detalle": ""}])


def clima_y_estado(t, crossing, estado, rafaga=40):
    ts = format_ts(t)
    lugares = {"rio_verde": ["rio_verde"], "primera_angostura": ["punta_delgada", "bahia_azul"]}[crossing]
    storage.append_rows(storage.WEATHER, [{"ts_utc": ts, "place": p, "gust_kmh": rafaga, "wind_kmh": 20, "wind_dir_deg": 270}
                                          for p in lugares])
    storage.append_rows(storage.TABSA_STATE, [{"ts_utc": ts, "crossing": crossing, "status": estado}])


class UsaLoPredichoTest(TempDataDir):
    def test_rio_verde_ahora_se_mide_con_anticipacion(self):
        valido = E + timedelta(hours=3)
        clima_y_estado(valido, "rio_verde", "NORMAL")
        pred("rio_verde", "hora", E, valido.replace(minute=0) + timedelta(hours=0), "3", 0.8, 99)
        fila = evaluacion.evaluar(historial=[])["rio_verde"]["filas"][0]
        self.assertEqual(fila["p3"], 0.8)                       # el número guardado, no uno recalculado
        self.assertNotIn("p12", fila)
        m = evaluacion.evaluar(historial=[])["rio_verde"]["metricas"][3]
        self.assertEqual((m["n"], m["falsas_alarmas_50"]), (1, 1))

    def test_lo_guardado_manda_sobre_la_reconstruccion_en_primera_angostura(self):
        valido = T0 + timedelta(hours=3)
        pronostico(T0, [(valido, 98)])                         # la reconstrucción daría un % alto
        corrida(valido, 100, "NORMAL")
        pred("primera_angostura", "hora", T0, valido, "3", 0.12, 60)
        fila = evaluacion.evaluar(historial=[])["primera_angostura"]["filas"][0]
        self.assertEqual(fila["p3"], 0.12)

    def test_sin_predicciones_guardadas_sigue_reconstruyendo_primera_angostura(self):
        valido = T0 + timedelta(hours=3)
        pronostico(T0, [(valido, 98)])
        corrida(valido, 100, "NORMAL")
        fila = evaluacion.evaluar(historial=[])["primera_angostura"]["filas"][0]
        self.assertAlmostEqual(fila["p3"], model.prior_probability(98, "primera_angostura"))

    def test_zarpes_de_porvenir(self):
        salida = local_to_utc("2026-11-26", "09:00")
        emitido = salida - timedelta(hours=3, minutes=5)
        storage.append_rows(storage.TABSA_SAILINGS, [
            {"ts_utc": format_ts(salida), "date": "2026-11-26", "origin": "Punta Arenas", "destination": "Porvenir",
             "boarding": "", "departure": "09:00", "status": "CANCELADO", "icon": ""}])
        storage.append_rows(storage.WEATHER, [{"ts_utc": format_ts(salida), "place": "punta_arenas", "gust_kmh": 80,
                                               "wind_kmh": 40, "wind_dir_deg": 270}])
        pred("punta_arenas_porvenir", "zarpe", emitido, salida, "3.08", 0.64)
        m = evaluacion.evaluar(historial=[])["punta_arenas_porvenir"]["metricas"][3]
        self.assertEqual((m["n"], m["suspensiones"], m["detectadas_50"]), (1, 1, 1))

    def test_la_fecha_de_corte_deja_afuera_lo_anterior(self):
        clima_y_estado(E, "rio_verde", "NORMAL")
        clima_y_estado(E + timedelta(days=2), "rio_verde", "NORMAL")
        todo = evaluacion.evaluar(historial=[])["rio_verde"]["metricas"][0]["n"]
        desde = evaluacion.evaluar(E + timedelta(days=1), historial=[])["rio_verde"]["metricas"][0]["n"]
        self.assertEqual((todo, desde), (2, 1))

    def test_el_informe_ya_no_dice_que_solo_se_mide_primera_angostura(self):
        clima_y_estado(E, "rio_verde", "NORMAL")
        txt = evaluacion.texto(evaluacion.evaluar(historial=[]))
        self.assertNotIn("solo se puede medir Primera Angostura", txt)
        self.assertIn("predicciones/", txt)


if __name__ == "__main__":
    unittest.main()
