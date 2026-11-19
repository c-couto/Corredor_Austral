"""Situación por cruce, web, avisos y Telegram."""

import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from corredor import alerts, conditions, forecast, storage, web
from corredor.channels import telegram
from corredor.timeutil import format_ts

from .helpers import TempDataDir, fake_urlopen

NOW = datetime(2026, 11, 17, 15, 0, tzinfo=timezone.utc)  # 12:00 local


def add_run(dt, gusts, status_pa=None):
    ts = format_ts(dt)
    storage.append_rows(storage.WEATHER, [
        {"ts_utc": ts, "place": p, "wind_kmh": g / 2, "gust_kmh": g, "wind_dir_deg": 270,
         "forecast_gust_max_24h_kmh": g, "source": "test"} for p, g in gusts.items()])
    if status_pa:
        storage.append_rows(storage.TABSA_STATE, [{"ts_utc": ts, "crossing": "primera_angostura", "status": status_pa}])


def add_change(dt, subject, previous, current):
    storage.append_rows(storage.TABSA_CHANGES, [
        {"ts_utc": format_ts(dt), "subject": subject, "previous": previous, "current": current}])


def add_forecast(start, gusts):
    forecast.save(format_ts(start), "test", {"punta_delgada": {"hourly": [
        {"t": format_ts(start + timedelta(hours=i)), "wind": g / 2, "gust": g, "dir": 270} for i, g in enumerate(gusts)]}})


class SnapshotTest(TempDataDir):
    def test_estado_oficial_probabilidad_y_pronostico(self):
        add_run(NOW - timedelta(minutes=30), {"punta_delgada": 30, "bahia_azul": 20}, "NORMAL")
        add_run(NOW - timedelta(minutes=5), {"punta_delgada": 55, "bahia_azul": 72}, "SUSPENDIDO")
        add_forecast(NOW, [40] * 10 + [90] + [40] * 37)
        snap = conditions.snapshot(now=NOW, fetch_forecast=False)
        pa = snap.route("primera_angostura")
        self.assertEqual(pa.gust_kmh, 72)
        self.assertEqual(pa.level, "alto")              # 72 km/h con la regla base
        self.assertEqual((pa.official, pa.official_fresh), ("SUSPENDIDO", True))
        self.assertEqual(len(pa.hours), 48)
        self.assertEqual(pa.peak().gust, 90)
        self.assertEqual([g for _, g in pa.history], [30, 72])
        self.assertEqual(snap.episodes[0].status, "SUSPENDIDO")
        self.assertIsNone(snap.episodes[0].end)          # sigue suspendido

    def test_episodio_con_duracion(self):
        add_run(NOW - timedelta(hours=3), {"punta_delgada": 80}, "SUSPENDIDO")
        add_run(NOW - timedelta(hours=1), {"punta_delgada": 40}, "NORMAL")
        ep = conditions.snapshot(now=NOW, fetch_forecast=False).episodes[0]
        self.assertEqual(ep.duration(NOW), timedelta(hours=2))
        self.assertEqual(conditions.fmt_duration(ep.duration(NOW)), "2 h 00 min")

    def test_sin_datos(self):
        snap = conditions.snapshot(now=NOW, fetch_forecast=False)
        self.assertIsNone(snap.latest)
        self.assertTrue(snap.is_stale())
        self.assertIn("La probabilidad de suspensión es una estimación", conditions.summary_text(snap))

    def test_proximos_zarpes_solo_de_punta_arenas_porvenir(self):
        ts = format_ts(NOW - timedelta(minutes=5))
        storage.append_rows(storage.TABSA_SAILINGS, [
            {"ts_utc": ts, "date": "2026-11-17", "departure": "18:00", "origin": o, "destination": d, "status": "NORMAL"}
            for o, d in (("Puerto Natales", "Puerto Edén"), ("Punta Arenas", "Puerto Williams"),
                         ("Punta Arenas", "Porvenir"))])
        snap = conditions.snapshot(now=NOW, fetch_forecast=False)
        self.assertEqual([(s.origin, s.destination) for s in snap.sailings], [("Punta Arenas", "Porvenir")])

    def test_dato_oficial_viejo_no_se_muestra_como_actual(self):
        add_run(NOW - timedelta(hours=5), {"punta_delgada": 30}, "SUSPENDIDO")
        snap = conditions.snapshot(now=NOW, fetch_forecast=False)
        self.assertEqual(snap.official_for(snap.route("primera_angostura")), (None, "TABSA: sin dato reciente"))


class AlertsTest(TempDataDir):
    def test_aviso_oficial_de_suspension(self):
        add_run(NOW - timedelta(minutes=5), {"punta_delgada": 80}, "SUSPENDIDO")
        add_change(NOW - timedelta(minutes=35), "primera_angostura", "", "NORMAL")  # primera vez: no se avisa
        add_change(NOW - timedelta(minutes=5), "primera_angostura", "NORMAL", "SUSPENDIDO")
        changed = alerts.official_changes(now=NOW)
        self.assertEqual([(c["subject"], c["current"]) for c in changed], [("primera_angostura", "SUSPENDIDO")])
        with mock.patch.object(conditions.forecast, "load", return_value=None):
            text = alerts.change_message(changed, [])
        self.assertIn("Primera Angostura: NORMAL → SUSPENDIDO", text)

    def test_no_repite_un_aviso_viejo(self):
        add_change(NOW - timedelta(hours=2), "primera_angostura", "NORMAL", "SUSPENDIDO")
        self.assertEqual(alerts.official_changes(now=NOW), [])

    def test_cambio_de_riesgo_por_viento(self):
        add_run(NOW - timedelta(minutes=35), {"punta_delgada": 30})
        add_run(NOW - timedelta(minutes=5), {"punta_delgada": 75})
        self.assertIn(("Primera Angostura", "bajo", "alto"), alerts.risk_changes(now=NOW))

    def test_sin_cambios_no_envia(self):
        add_run(NOW - timedelta(minutes=35), {"punta_delgada": 30})
        add_run(NOW - timedelta(minutes=5), {"punta_delgada": 32})
        self.assertEqual(alerts.risk_changes(now=NOW), [])


class EasyReadingTest(TempDataDir):
    def test_ventanas_de_posible_suspension(self):
        add_run(NOW - timedelta(minutes=5), {"punta_delgada": 30})
        add_forecast(NOW, [30] * 5 + [60, 75, 80, 55] + [30] * 39)
        st = conditions.snapshot(now=NOW, fetch_forecast=False).route("primera_angostura")
        wins = conditions.closure_windows(st, "medio", 48)
        self.assertEqual(len(wins), 1)
        first, last, worst = wins[0]
        self.assertEqual((first.t, last.t, worst), (NOW + timedelta(hours=5), NOW + timedelta(hours=8), "alto"))
        self.assertIn("probable suspensión entre", conditions.summary_text(conditions.snapshot(now=NOW, fetch_forecast=False)))

    def test_veredicto_prioriza_el_estado_oficial(self):
        add_run(NOW - timedelta(minutes=5), {"punta_delgada": 20}, "SUSPENDIDO")
        snap = conditions.snapshot(now=NOW, fetch_forecast=False)
        self.assertEqual(conditions.verdict(snap, snap.route("primera_angostura")),
                         ("alto", "Suspendido según TABSA (suspendido)"))

    def test_veredicto_por_viento(self):
        add_run(NOW - timedelta(minutes=5), {"punta_delgada": 30}, "NORMAL")
        snap = conditions.snapshot(now=NOW, fetch_forecast=False)
        self.assertEqual(conditions.verdict(snap, snap.route("primera_angostura")), ("bajo", "Se espera cruce normal"))

    def test_umbrales_de_rafaga_de_la_regla_base(self):
        m = conditions.model.RouteModel()
        self.assertAlmostEqual(conditions.gust_threshold(m, 0.2), 50, delta=0.1)
        self.assertAlmostEqual(conditions.gust_threshold(m, 0.5), 70, delta=0.1)

    def test_describe_el_clima(self):
        self.assertEqual(conditions.describe_weather({"weather_code": 61, "is_day": 1}), ("🌧️", "Lluvia"))
        self.assertEqual(conditions.describe_weather({"weather_code": 0, "is_day": 0}), ("🌙", "Despejado"))
        self.assertEqual(conditions.describe_weather({"symbol": "lightsnow"}), ("🌨️", "Nieve"))
        self.assertEqual(conditions.describe_weather({"weather_code": 3, "gust_kmh": 80})[1], "Nublado, muy ventoso")
        self.assertEqual(conditions.describe_weather(None)[1], "Sin datos")


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
    def page(self):
        return web.render(conditions.snapshot(now=NOW, fetch_forecast=False), now=NOW)

    def test_pagina_completa(self):
        add_run(NOW - timedelta(minutes=35), {"punta_delgada": 30, "bahia_azul": 30, "punta_arenas": 20})
        add_run(NOW - timedelta(minutes=5), {"punta_delgada": 75, "bahia_azul": 60, "punta_arenas": 25}, "NORMAL")
        add_forecast(NOW, [40 + i for i in range(48)])
        html = self.page()
        for text in ("Primera Angostura", "TABSA: NORMAL", "¿A qué hora salgo?", 'id="plan-data"',
                     "Cómo calculamos la probabilidad", "regla base", "Plan Flota", "https://wa.me/?text=",
                     'class="chart"', "Construyendo el historial", "Bandera de Tierra del Fuego",
                     'id="clk"', "probabilidad de que TABSA suspenda", "Probable suspensión"):
            self.assertIn(text, html)
        self.assertNotIn("Los datos tienen más de", html)

    def test_aviso_de_datos_viejos_y_sin_planificador(self):
        add_run(NOW - timedelta(hours=5), {"punta_delgada": 30})
        html = self.page()
        self.assertIn("Los datos tienen más de", html)
        self.assertNotIn("¿A qué hora salgo?", html)  # sin pronóstico no se muestra

    def test_pagina_sin_datos(self):
        self.assertIn("Sin datos todavía", self.page())

    def test_textos_externos_se_escapan(self):
        add_run(NOW - timedelta(minutes=5), {"punta_delgada": 30}, "<script>x</script>")
        html = self.page()
        self.assertNotIn("<script>x</script>", html)
        self.assertIn("&lt;script&gt;", html)


if __name__ == "__main__":
    unittest.main()
