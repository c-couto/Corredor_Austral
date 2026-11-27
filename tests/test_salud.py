"""Salud del sistema: informe, avisos al equipo (sin repetir) y cartel "Datos atrasados"."""

import os
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

from corredor import config, salud, storage

from .helpers import TempDataDir

AHORA = datetime(2026, 11, 27, 18, 0, tzinfo=timezone.utc)


def ts(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def corridas(desde, hasta, tabsa=True, clima=True):
    """Una corrida cada 30 min entre desde y hasta."""
    t = desde
    while t <= hasta:
        if tabsa:
            storage.append_rows(storage.TABSA_STATE, [{"ts_utc": ts(t), "crossing": "rio_verde", "status": "NORMAL", "icon": ""}])
        if clima:
            storage.append_rows(storage.WEATHER, [{"ts_utc": ts(t), "place": "punta_delgada", "gust_kmh": 30}])
        t += timedelta(minutes=30)


class SaludTest(TempDataDir):
    def setUp(self):
        super().setUp()
        p = mock.patch.object(config, "TOKEN_CRON_VENCE", date(2026, 12, 17))
        p.start()
        self.addCleanup(p.stop)

    def test_todo_bien(self):
        corridas(AHORA - timedelta(hours=24), AHORA - timedelta(minutes=5))
        s = salud.calcular(AHORA)
        self.assertEqual(s.problemas(), {})
        self.assertEqual(s.corridas_24h, 48)
        self.assertEqual(s.corridas_faltantes, 0)
        self.assertEqual(s.dias_token, 20)
        self.assertIn("PROBLEMAS: ninguno", salud.texto(s))

    def test_cuenta_corridas_que_faltan_y_errores(self):
        corridas(AHORA - timedelta(hours=12), AHORA - timedelta(minutes=5))
        storage.append_rows(storage.ERRORS, [
            {"ts_utc": ts(AHORA - timedelta(hours=1)), "where_": "weather", "error": "x"},
            {"ts_utc": ts(AHORA - timedelta(hours=30)), "where_": "weather", "error": "viejo"}])
        s = salud.calcular(AHORA)
        self.assertEqual(s.corridas_24h, 24)
        self.assertEqual(s.corridas_faltantes, 24)
        self.assertEqual(s.errores_24h, {"weather": 1})   # el de hace 30 h no cuenta

    def test_sin_tabsa_tres_corridas_seguidas(self):
        corridas(AHORA - timedelta(hours=6), AHORA - timedelta(minutes=125), tabsa=True)
        corridas(AHORA - timedelta(hours=6), AHORA - timedelta(minutes=5), tabsa=False)
        self.assertIn("tabsa", salud.calcular(AHORA).problemas())
        corridas(AHORA - timedelta(minutes=65), AHORA - timedelta(minutes=5), tabsa=True, clima=False)
        self.assertNotIn("tabsa", salud.calcular(AHORA).problemas())

    def test_clima_de_mas_de_90_minutos(self):
        corridas(AHORA - timedelta(hours=3), AHORA - timedelta(minutes=95), clima=True)
        corridas(AHORA - timedelta(hours=3), AHORA - timedelta(minutes=5), clima=False)
        p = salud.calcular(AHORA).problemas()
        self.assertIn("clima", p)
        self.assertNotIn("tabsa", p)

    def test_token_cerca_de_vencer(self):
        corridas(AHORA - timedelta(hours=2), AHORA - timedelta(minutes=5))
        with mock.patch.object(config, "TOKEN_CRON_VENCE", date(2026, 12, 4)):   # faltan 7 días
            self.assertIn("token", salud.calcular(AHORA).problemas())
        with mock.patch.object(config, "TOKEN_CRON_VENCE", date(2026, 12, 5)):   # faltan 8
            self.assertNotIn("token", salud.calcular(AHORA).problemas())

    def test_no_avisa_dos_veces_lo_mismo(self):
        corridas(AHORA - timedelta(hours=6), AHORA - timedelta(minutes=125))   # TABSA y clima se cortaron hace 2 h
        nuevos_ahora = salud.nuevos_problemas(AHORA)
        self.assertTrue(any("TABSA" in t for t in nuevos_ahora))
        # una hora después sigue roto: ya se avisó, no se repite
        self.assertEqual([t for t in salud.nuevos_problemas(AHORA + timedelta(hours=1)) if "TABSA" in t or "Clima" in t], [])

    def test_token_recuerda_una_vez_por_dia(self):
        corridas(AHORA - timedelta(hours=30), AHORA - timedelta(minutes=5))
        with mock.patch.object(config, "TOKEN_CRON_VENCE", date(2026, 12, 3)):
            self.assertEqual(salud.nuevos_problemas(datetime(2026, 11, 27, 0, 30, tzinfo=timezone.utc)) != [], True)
            self.assertEqual(salud.nuevos_problemas(AHORA), [])    # misma fecha que la revisión anterior

    def test_avisar_sin_chat_del_equipo_no_envia_ni_falla(self):
        corridas(AHORA - timedelta(hours=6), AHORA - timedelta(minutes=125))
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "t", "TELEGRAM_TEAM_CHAT_ID": ""}), \
                mock.patch("corredor.salud.datetime") as dt:
            dt.now.return_value = AHORA
            texto = salud.avisar(AHORA)
        self.assertIn("No enviado", texto)

    def test_avisar_manda_al_chat_del_equipo_y_no_al_de_usuarios(self):
        corridas(AHORA - timedelta(hours=6), AHORA - timedelta(minutes=125))
        env = {"TELEGRAM_BOT_TOKEN": "tok", "TELEGRAM_TEAM_CHAT_ID": "-999", "TELEGRAM_CHAT_ID": "@usuarios"}
        with mock.patch.dict(os.environ, env), mock.patch("corredor.net.post_json") as post:
            salud.avisar(AHORA)
        enviado = post.call_args[0][1]
        self.assertEqual(enviado["chat_id"], "-999")
        self.assertIn("TABSA", enviado["text"])

    def test_no_escribe_nada_en_data(self):
        corridas(AHORA - timedelta(hours=2), AHORA - timedelta(minutes=5))
        antes = {p: p.stat().st_size for p in self.data_dir.rglob("*") if p.is_file()}
        salud.texto(salud.calcular(AHORA))
        salud.nuevos_problemas(AHORA)
        self.assertEqual(antes, {p: p.stat().st_size for p in self.data_dir.rglob("*") if p.is_file()})


if __name__ == "__main__":
    unittest.main()
