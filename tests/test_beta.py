"""Pruebas de la BETA: niveles de riesgo, avisos, Telegram y web."""

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from corredor import alerts, conditions, storage, web
from corredor.channels import telegram

from .helpers import TempDataDir, fake_urlopen

T0 = datetime(2026, 11, 17, 12, 0, tzinfo=timezone.utc)


def ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def add_run(dt, gusts, forecast=40.0):
    """Una corrida con la misma ráfaga en todos los puntos de `gusts` {lugar: ráfaga}."""
    storage.append_rows(storage.WEATHER, [
        {"ts_utc": ts(dt), "place": p, "wind_kmh": g / 2, "gust_kmh": g,
         "forecast_gust_max_24h_kmh": forecast, "source": "test"} for p, g in gusts.items()
    ])


class LevelTest(unittest.TestCase):
    def test_umbrales(self):
        self.assertEqual(conditions.level_for(None), None)
        self.assertEqual(conditions.level_for(49.9), "bajo")
        self.assertEqual(conditions.level_for(50), "medio")
        self.assertEqual(conditions.level_for(70), "alto")


class SnapshotTest(TempDataDir):
    def test_toma_la_mayor_rafaga_del_cruce_y_el_historial(self):
        add_run(T0, {"punta_delgada": 30, "bahia_azul": 20})
        add_run(T0 + timedelta(hours=1), {"punta_delgada": 55, "bahia_azul": 72})
        snap = conditions.snapshot()
        pa = snap.routes[0]
        self.assertEqual(pa.key, "primera_angostura")
        self.assertEqual(pa.gust_kmh, 72)
        self.assertEqual(pa.level, "alto")
        self.assertEqual([g for _, g in pa.history], [30, 72])
        self.assertIsNone(snap.routes[1].gust_kmh)  # Punta Arenas – Porvenir sin datos

    def test_sin_datos(self):
        snap = conditions.snapshot()
        self.assertIsNone(snap.latest)
        self.assertTrue(snap.is_stale())
        self.assertIn("NO es el estado oficial", conditions.summary_text(snap))

    def test_aviso_de_datos_viejos(self):
        add_run(T0, {"punta_delgada": 30})
        snap = conditions.snapshot()
        self.assertFalse(snap.is_stale(now=T0 + timedelta(hours=1)))
        self.assertTrue(snap.is_stale(now=T0 + timedelta(hours=3)))


class AlertsTest(TempDataDir):
    def test_detecta_cambio_de_nivel(self):
        add_run(T0, {"punta_delgada": 30, "punta_arenas": 20})
        add_run(T0 + timedelta(minutes=30), {"punta_delgada": 65, "punta_arenas": 21})
        changed = alerts.changes(now=T0 + timedelta(minutes=31))
        self.assertEqual(changed, [("Primera Angostura", "bajo", "medio")])

    def test_no_repite_un_aviso_viejo(self):
        add_run(T0, {"punta_delgada": 30})
        add_run(T0 + timedelta(minutes=30), {"punta_delgada": 65})
        # Una hora después (p. ej. falló la recolección siguiente): no se vuelve a avisar.
        self.assertEqual(alerts.changes(now=T0 + timedelta(minutes=90)), [])

    def test_sin_cambio_no_avisa(self):
        add_run(T0, {"punta_delgada": 30})
        add_run(T0 + timedelta(minutes=30), {"punta_delgada": 40})
        self.assertEqual(alerts.changes(now=T0 + timedelta(minutes=31)), [])


class TelegramTest(TempDataDir):
    def test_sin_configurar_no_envia(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(telegram.send("hola"))

    def test_envia_con_token_y_chat(self):
        env = {"TELEGRAM_BOT_TOKEN": "123:ABC", "TELEGRAM_CHAT_ID": "@canal"}
        with mock.patch.dict(os.environ, env, clear=True), fake_urlopen([{"ok": True}]) as m:
            self.assertTrue(telegram.send("hola"))
        req = m.call_args[0][0]
        self.assertEqual(req.get_method(), "POST")
        self.assertIn(b'"chat_id": "@canal"', req.data)

    def test_el_token_no_aparece_en_los_errores(self):
        env = {"TELEGRAM_BOT_TOKEN": "123:SECRETO", "TELEGRAM_CHAT_ID": "@canal"}
        with mock.patch.dict(os.environ, env, clear=True), \
                fake_urlopen([ValueError("fallo en https://api.telegram.org/bot123:SECRETO/x")] * 4):
            with self.assertRaises(RuntimeError) as ctx:
                telegram.send("hola")
        self.assertNotIn("SECRETO", str(ctx.exception))


class WebTest(TempDataDir):
    def test_genera_la_pagina(self):
        add_run(T0, {"punta_delgada": 30, "bahia_azul": 30, "punta_arenas": 20, "porvenir": 20})
        add_run(T0 + timedelta(minutes=30), {"punta_delgada": 75, "bahia_azul": 60,
                                             "punta_arenas": 20, "porvenir": 25})
        path = web.build_site(self.data_dir / "_site")
        html = path.read_text(encoding="utf-8")
        self.assertIn("Primera Angostura", html)
        self.assertIn("Riesgo alto", html)
        self.assertIn("No es el estado oficial", html)
        self.assertIn("https://wa.me/?text=", html)
        self.assertIn("<svg", html)  # gráfico del historial

    def test_pagina_sin_datos(self):
        html = web.render(conditions.snapshot())
        self.assertIn("Sin datos todavía", html)


if __name__ == "__main__":
    unittest.main()
