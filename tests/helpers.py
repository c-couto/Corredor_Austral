"""Utilidades para las pruebas: carpeta de datos temporal y respuestas HTTP falsas."""

import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from corredor import config


class TempDataDir(unittest.TestCase):
    """Cada prueba escribe en una carpeta temporal, nunca en data/ de verdad."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data_dir = Path(tmp.name)
        patcher = mock.patch.object(config, "DATA_DIR", self.data_dir)
        patcher.start()
        self.addCleanup(patcher.stop)
        # Sin esperas entre reintentos para que las pruebas sean rápidas.
        patcher = mock.patch.object(config, "RETRY_WAITS_S", (0, 0, 0))
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


def open_meteo_response(n_places):
    """Respuesta de Open-Meteo con n lugares (sirve para clima y oleaje)."""
    item = {
        "current": {"temperature_2m": 10, "wind_speed_10m": 20, "wind_gusts_10m": 30,
                    "wind_direction_10m": 90, "precipitation": 0,
                    "wave_height": 1.5, "wave_period": 4, "wave_direction": 200},
        "hourly": {"wind_gusts_10m": [30, 45, None]},
    }
    return item if n_places == 1 else [item] * n_places
