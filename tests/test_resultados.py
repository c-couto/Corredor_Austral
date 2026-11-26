"""Cómo nos fue: predicciones guardadas contra lo que hizo TABSA."""

from datetime import date, datetime, timedelta, timezone

from corredor import conditions, resultados, storage, web
from corredor.timeutil import format_ts, local_to_utc

from .helpers import TempDataDir
from .test_web_alerts import add_run

E = datetime(2026, 11, 20, 12, 5, tzinfo=timezone.utc)
NOW = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)


def estado(dt, status, crossing="primera_angostura"):
    storage.append_rows(storage.TABSA_STATE, [{"ts_utc": format_ts(dt), "crossing": crossing, "status": status}])


def pred(ruta, tipo, emitido, valido, a, prob, rafaga="", modelo="regla base"):
    storage.append_rows(storage.PREDICTIONS, [{
        "emitido_utc": format_ts(emitido), "ruta": ruta, "tipo": tipo, "valido_utc": format_ts(valido),
        "anticipacion_h": a, "prob": prob, "rafaga_kmh": rafaga, "modelo": modelo, "detalle": ""}])


def res(ruta, now=NOW, **kw):
    return next(r for r in resultados.calcular(now, **kw) if r.key == ruta)


class CruceConEstadoTest(TempDataDir):
    def setUp(self):
        super().setUp()
        e2 = E + timedelta(hours=1)
        for t, st in ((E, "NORMAL"), (E + timedelta(hours=3), "SUSPENDIDO"),   # 15:05 -> la hora de las 15:00
                      (e2, "NORMAL"), (e2 + timedelta(hours=3), "NORMAL")):     # 16:05 -> la hora de las 16:00
            estado(t, st)
        pred("primera_angostura", "hora", E, E.replace(minute=0) + timedelta(hours=3), "3", 0.8, 85)   # acierto
        pred("primera_angostura", "hora", e2, e2.replace(minute=0) + timedelta(hours=3), "3", 0.7, 75)  # falsa alarma

    def test_detecta_la_suspension_y_cuenta_la_falsa_alarma(self):
        c = res("primera_angostura").resumen[3]
        self.assertEqual((c.n, c.sus, c.detectadas, c.falsas, c.normales), (2, 1, 1, 1, 1))

    def test_se_compara_con_sigue_igual_y_con_la_regla_base(self):
        c = res("primera_angostura").resumen[3]
        self.assertAlmostEqual(c.brier, (0.2 ** 2 + 0.7 ** 2) / 2)        # nuestro
        self.assertAlmostEqual(c.brier_igual, (1 ** 2 + 0.0) / 2)         # "sigue igual" falló la suspensión
        self.assertTrue(c.nuestra_es_la_base)                              # modelo = regla base
        self.assertAlmostEqual(c.brier_base, c.brier)

    def test_con_pocos_casos_no_dice_mejor_ni_peor(self):
        self.assertIsNone(res("primera_angostura").resumen[3].mejor_que_igual)
        self.assertTrue(resultados.Resumen(n=9, sus=5, brier=0.1, brier_igual=0.2).mejor_que_igual)
        self.assertFalse(resultados.Resumen(n=9, sus=5, brier=0.3, brier_igual=0.2).mejor_que_igual)

    def test_por_dia_local(self):
        dias = res("primera_angostura").dias
        self.assertEqual([d.dia for d in dias], [date(2026, 11, 20)])
        self.assertEqual(dias[0].celdas[3].detectadas, 1)

    def test_lo_que_todavia_no_paso_no_cuenta(self):
        antes = datetime(2026, 11, 20, 15, 30, tzinfo=timezone.utc)  # después de la 1.ª hora, antes de la 2.ª
        self.assertEqual(res("primera_angostura", now=antes).resumen[3].n, 1)

    def test_filtrar_un_dia(self):
        self.assertEqual(res("primera_angostura", desde=date(2026, 11, 21), hasta=date(2026, 11, 21)).resumen, {})
        self.assertEqual(res("primera_angostura", desde=date(2026, 11, 20), hasta=date(2026, 11, 20)).resumen[3].n, 2)

    def test_modelo_aprendido_se_compara_con_la_regla_base_recalculada(self):
        # Una hora más, emitida con modelo aprendido: la regla base se recalcula con la ráfaga (85 km/h).
        e3 = E + timedelta(hours=4)
        estado(e3, "NORMAL"); estado(e3 + timedelta(hours=3), "NORMAL")
        pred("primera_angostura", "hora", e3, e3.replace(minute=0) + timedelta(hours=3), "3", 0.1, 85,
             modelo="aprendido 2026-11-20T00:00:00Z")
        c = res("primera_angostura").resumen[3]
        self.assertFalse(c.nuestra_es_la_base)
        self.assertEqual(c.n, 3)

class PorvenirTest(TempDataDir):
    def test_cada_zarpe_con_su_estado(self):
        salida = local_to_utc("2026-11-20", "09:00")
        previa = local_to_utc("2026-11-19", "09:00")
        emitido = salida - timedelta(hours=3, minutes=5)
        storage.append_rows(storage.TABSA_SAILINGS, [
            {"ts_utc": format_ts(previa), "date": "2026-11-19", "origin": "Punta Arenas", "destination": "Porvenir",
             "boarding": "", "departure": "09:00", "status": "NORMAL", "icon": ""},
            {"ts_utc": format_ts(salida), "date": "2026-11-20", "origin": "Punta Arenas", "destination": "Porvenir",
             "boarding": "", "departure": "09:00", "status": "CANCELADO", "icon": ""}])
        pred("punta_arenas_porvenir", "zarpe", emitido, salida, "3.08", 0.6)
        c = res("punta_arenas_porvenir").resumen[3]
        self.assertEqual((c.n, c.sus, c.detectadas, c.falsas), (1, 1, 1, 0))
        self.assertEqual(res("punta_arenas_porvenir").unidad, "zarpes")
        self.assertAlmostEqual(c.brier_igual, 1.0)   # el zarpe anterior era normal: "sigue igual" falló


class WebTest(TempDataDir):
    def test_seccion_con_errores_y_sin_datos_no_aparece(self):
        add_run(NOW - timedelta(minutes=5), {"punta_delgada": 30}, "NORMAL")
        html = web.render(conditions.snapshot(now=NOW, fetch_forecast=False), now=NOW)
        self.assertNotIn("Cómo nos fue", html)   # todavía no hay predicciones guardadas

        estado(E, "NORMAL"); estado(E + timedelta(hours=3), "SUSPENDIDO")
        estado(E + timedelta(hours=1), "NORMAL"); estado(E + timedelta(hours=4), "NORMAL")
        pred("primera_angostura", "hora", E, E.replace(minute=0) + timedelta(hours=3), "3", 0.8, 85)
        pred("primera_angostura", "hora", E + timedelta(hours=1), E.replace(minute=0) + timedelta(hours=4), "3", 0.7, 75)
        html = web.render(conditions.snapshot(now=NOW, fetch_forecast=False), now=NOW)
        sec = html.split("<h2>Cómo nos fue</h2>")[1].split("</section>")[0]
        self.assertIn("1 de 1", sec)                 # detectada
        self.assertIn("1 de 1</td>", sec)            # falsa alarma: 1 de 1 hora normal
        self.assertIn("Mostramos también los errores", sec)
        self.assertIn("Todavía no comparamos", sec)  # con 1 suspensión no se saca conclusión
        self.assertLessEqual(sec.count("pocos casos"), 1)  # solo en la introducción, no en cada fila
        self.assertIn("1 hora<", sec)                # singular
        self.assertIn("1/1 detectadas", sec)         # el día por día
        self.assertIn("Hoy este cruce usa la regla base", sec)


if __name__ == "__main__":
    import unittest
    unittest.main()
