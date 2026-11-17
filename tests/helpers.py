"""Utilidades para las pruebas: carpetas temporales, sin red y respuestas HTTP falsas."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from corredor import config

FIXTURES = Path(__file__).parent / "fixtures"


def _no_network(*args, **kwargs):
    raise AssertionError("las pruebas no pueden salir a internet (usá fake_urlopen)")


def _no_browser(*args, **kwargs):
    raise AssertionError("las pruebas no pueden abrir el navegador (pasá tabsa_fn)")


class TempDataDir(unittest.TestCase):
    """Cada prueba escribe en carpetas temporales, nunca en data/ ni .cache/ de verdad,
    y no puede usar la red ni el navegador salvo que lo simule explícitamente."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name) / "data"
        self.cache_dir = Path(tmp.name) / "cache"
        for patcher in (
            mock.patch.object(config, "DATA_DIR", self.data_dir),
            mock.patch.object(config, "CACHE_DIR", self.cache_dir),
            mock.patch.object(config, "RETRY_WAITS_S", (0, 0, 0)),  # reintentos sin espera
            mock.patch.object(config, "WEATHER_SOURCE", "open_meteo"),
            mock.patch("urllib.request.urlopen", side_effect=_no_network),
            mock.patch("corredor.browser.render_dom", side_effect=_no_browser),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)


def fake_urlopen(responses):
    """Reemplazo de urlopen: cada llamada devuelve (o lanza) el siguiente elemento."""
    responses = list(responses)

    def _urlopen(req, timeout):
        step = responses.pop(0)
        if isinstance(step, BaseException):
            raise step
        return io.BytesIO(json.dumps(step).encode())

    return mock.patch("urllib.request.urlopen", side_effect=_urlopen)


def open_meteo_response(n_places, hours=0, gust=30):
    """Respuesta de Open-Meteo con n lugares (sirve para clima y oleaje)."""
    item = {
        "current": {"temperature_2m": 10, "wind_speed_10m": 20, "wind_gusts_10m": gust,
                    "wind_direction_10m": 90, "precipitation": 0,
                    "wave_height": 1.5, "wave_period": 4, "wave_direction": 200},
        "hourly": {"wind_gusts_10m": [30, 45, None]},
    }
    if hours:
        item["hourly"] = {
            "time": [f"2026-11-{17 + h // 24:02d}T{h % 24:02d}:00" for h in range(hours)],
            "wind_speed_10m": [20] * hours,
            "wind_gusts_10m": [30 + h for h in range(hours)],
            "wind_direction_10m": [270] * hours,
            "wave_height": [1.0] * hours,
            "wave_period": [4.0] * hours,
            "wave_direction": [200] * hours,
            "sea_level_height_msl": [round(-2 + h * 0.5, 2) for h in range(hours)],
        }
    return item if n_places == 1 else [item] * n_places


def tabsa_fixture_html() -> str:
    return (FIXTURES / "tabsa_estado_cruces.html").read_text(encoding="utf-8")
