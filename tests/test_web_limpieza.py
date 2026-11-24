"""Web más clara: sin repetir "suspendido", gráfico sin textos encimados, tortas con datos reales."""

from datetime import timedelta

from corredor import conditions, storage, web
from corredor.timeutil import format_ts

from .helpers import TempDataDir
from .test_web_alerts import NOW, add_forecast, add_run


def add_sailing(read_dt, date, departure, origin, destination, status):
    storage.append_rows(storage.TABSA_SAILINGS, [{
        "ts_utc": format_ts(read_dt), "date": date, "origin": origin, "destination": destination,
        "boarding": "", "departure": departure, "status": status, "icon": ""}])


class TarjetaSuspendidaTest(TempDataDir):
    def setUp(self):
        super().setUp()
        add_run(NOW - timedelta(hours=3), {"punta_delgada": 40}, "NORMAL")
        add_run(NOW - timedelta(minutes=95), {"punta_delgada": 90}, "SUSPENDIDO")   # 10:25 local
        add_run(NOW - timedelta(minutes=5), {"punta_delgada": 90}, "SUSPENDIDO")
        add_forecast(NOW, [90] * 6 + [40] * 42)
        self.snap = conditions.snapshot(now=NOW, fetch_forecast=False)
        self.html = web.render(self.snap, now=NOW)

    def test_una_sola_linea_con_desde_cuando(self):
        self.assertIn("TABSA: suspendido desde las 10:25", self.html)
        self.assertNotIn("Suspendido según TABSA (suspendido)", self.html)
        card = self.html.split("Primera Angostura</h2>")[1].split("</article>")[0]
        self.assertNotIn("prob. de<br>suspensión", card)  # sin el % cuando ya está suspendido
        self.assertNotIn('class="off off-bad"', card)      # ni el cartelito repetido

    def test_grafico_sin_textos_encimados(self):
        self.assertNotIn("susp-t", self.html)
        self.assertIn('class="susp"', self.html)
        self.assertIn("Suspendido (TABSA)", self.html)  # se explica en la leyenda

    def test_historial_sin_repetir_la_palabra(self):
        hist = self.html.split("<h2>Historial</h2>")[1].split("</section>")[0]
        self.assertNotIn("SUSPENDIDO", hist)
        self.assertIn("sigue", hist)


class OperacionTest(TempDataDir):
    def test_tiempo_habilitado_desde_las_lecturas_de_tabsa(self):
        # 4 h de lecturas, 1 h suspendido -> 75 % habilitado, 1 suspensión.
        add_run(NOW - timedelta(hours=4), {"punta_delgada": 30}, "NORMAL")
        add_run(NOW - timedelta(hours=2), {"punta_delgada": 90}, "SUSPENDIDO")
        add_run(NOW - timedelta(hours=1), {"punta_delgada": 40}, "NORMAL")
        add_run(NOW, {"punta_delgada": 40}, "NORMAL")
        op = next(o for o in conditions.snapshot(now=NOW, fetch_forecast=False).operation
                  if o.key == "primera_angostura")
        self.assertAlmostEqual(op.ok_share, 0.75)
        self.assertEqual((op.events, op.down), (1, timedelta(hours=1)))

    def test_zarpes_cada_uno_una_vez_con_su_ultimo_estado(self):
        add_run(NOW, {"punta_delgada": 30}, "NORMAL")
        # 09:00 local leído 2 veces (primero NORMAL, después CANCELADO); 11:00 normal; 18:00 todavía no salió.
        add_sailing(NOW - timedelta(hours=8), "2026-11-17", "09:00", "Punta Arenas", "Porvenir", "NORMAL")
        add_sailing(NOW - timedelta(hours=7), "2026-11-17", "09:00", "Punta Arenas", "Porvenir", "CANCELADO")
        add_sailing(NOW - timedelta(hours=7), "2026-11-17", "11:00", "Porvenir", "Punta Arenas", "NORMAL")
        add_sailing(NOW - timedelta(hours=7), "2026-11-17", "18:00", "Punta Arenas", "Porvenir", "NORMAL")
        snap = conditions.snapshot(now=NOW, fetch_forecast=False)
        op = next(o for o in snap.operation if o.key == "punta_arenas_porvenir")
        self.assertEqual((op.total, op.events), (2, 1))
        self.assertIn("1 de 2 · 1 cancelado", web.render(snap, now=NOW))


class VentanasTest(TempDataDir):
    def test_ventana_que_termina_otro_dia_dice_el_dia(self):
        add_run(NOW - timedelta(minutes=5), {"punta_delgada": 30}, "NORMAL")
        add_forecast(NOW, [30] * 6 + [90] * 20 + [30] * 22)  # 18:00 hoy -> 14:00 mañana (local)
        html = web.render(conditions.snapshot(now=NOW, fetch_forecast=False), now=NOW)
        self.assertIn("hoy 18:00 → mañana 14:00", html)


if __name__ == "__main__":
    import unittest
    unittest.main()
