"""Pronóstico de 4 días: el viento se pide a 96 h, pero lo que se guarda en data/ sigue en 48 h."""

import json
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone
from unittest import mock

from corredor import config, conditions, forecast, storage, web
from corredor.sources import open_meteo

from .helpers import TempDataDir, fake_urlopen, open_meteo_response
from .test_web_alerts import NOW, add_run


class PedidoTest(TempDataDir):
    def pedidos(self, fn, n_places, hours):
        urls = []

        def falso(req, timeout):
            urls.append(getattr(req, "full_url", req))
            import io
            return io.BytesIO(json.dumps(open_meteo_response(n_places, hours=hours)).encode())

        with mock.patch("urllib.request.urlopen", side_effect=falso):
            fn()
        return [urllib.parse.parse_qs(urllib.parse.urlparse(u).query) for u in urls]

    def test_el_viento_se_pide_a_96_horas_y_el_oleaje_a_48(self):
        q = self.pedidos(lambda: open_meteo.fetch_weather(config.PLACES), len(config.PLACES), 96)
        self.assertEqual(q[0]["forecast_hours"], ["96"])
        q = self.pedidos(lambda: open_meteo.fetch_marine({p: config.PLACES[p] for p in config.MARINE_PLACES}), len(config.MARINE_PLACES), 48)
        self.assertEqual(q[0]["forecast_hours"], ["48"])


class GuardadoTest(unittest.TestCase):
    def test_lo_que_se_guarda_en_data_sigue_siendo_48_horas(self):
        emitido = datetime(2026, 11, 28, 12, 5, tzinfo=timezone.utc)
        base = emitido.replace(minute=0)
        horas = [{"t": (base + timedelta(hours=i + 1)).strftime("%Y-%m-%dT%H:%M:%SZ"), "wind": 20, "gust": 40 + i, "dir": 270}
                 for i in range(96)]
        filas = forecast.snapshot_rows(emitido.strftime("%Y-%m-%dT%H:%M:%SZ"), "test", {p: {"hourly": horas} for p in config.SNAPSHOT_PLACES})
        por_lugar = {p: [f for f in filas if f["place"] == p] for p in config.SNAPSHOT_PLACES}
        for p, fs in por_lugar.items():
            self.assertEqual(len(fs), 48, p)
            self.assertLessEqual(max(float(f["lead_h"]) for f in fs), 48.0)


class WebTest(TempDataDir):
    def pagina(self, horas):
        add_run(NOW - timedelta(minutes=5), {"punta_delgada": 40, "bahia_azul": 40, "punta_arenas": 20}, "NORMAL")
        forecast.save(forecast.format_ts(NOW), "test", {"punta_delgada": {"hourly": [
            {"t": forecast.format_ts(NOW + timedelta(hours=i)), "wind": 20, "gust": 40, "dir": 270} for i in range(horas)]}})
        snap = conditions.snapshot(now=NOW, fetch_forecast=False)
        return snap, web.render(snap, now=NOW)

    def test_el_pronostico_llega_a_96_horas_pero_el_planificador_sigue_con_48(self):
        snap, html = self.pagina(96)
        self.assertEqual(len(snap.route("primera_angostura").hours), 96)
        import re
        plan = json.loads(re.search(r'id="plan-data">(.*?)</script>', html, re.S).group(1))
        cam = json.loads(re.search(r'id="camion-data">(.*?)</script>', html, re.S).group(1))
        self.assertEqual(len(plan["hours"]), 48)
        self.assertEqual(len(cam["hours"]), 96)

    def test_aviso_de_pronostico_lejano_y_nuevo_horizonte_en_el_camion(self):
        _, html = self.pagina(96)
        self.assertIn("a más de 2 días: menos preciso", html)
        self.assertIn("Más allá de 4 días", html)


if __name__ == "__main__":
    unittest.main()
