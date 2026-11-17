import unittest
import urllib.error

from corredor import net

from .helpers import TempDataDir, fake_urlopen


def http_error(code):
    return urllib.error.HTTPError("https://x", code, "error", {}, None)


class GetJsonTest(TempDataDir):
    def test_anda_al_primer_intento(self):
        with fake_urlopen([{"ok": 1}]) as m:
            self.assertEqual(net.get_json("https://x", {}), {"ok": 1})
        self.assertEqual(m.call_count, 1)

    def test_falla_dos_veces_y_anda_a_la_tercera(self):
        with fake_urlopen([TimeoutError(), ConnectionResetError(), {"ok": 1}]) as m:
            self.assertEqual(net.get_json("https://x", {}), {"ok": 1})
        self.assertEqual(m.call_count, 3)

    def test_hasta_3_reintentos_y_despues_falla(self):
        with fake_urlopen([TimeoutError()] * 4) as m:
            with self.assertRaises(TimeoutError):
                net.get_json("https://x", {})
        self.assertEqual(m.call_count, 4)  # 1 intento + 3 reintentos

    def test_error_400_no_se_reintenta(self):
        with fake_urlopen([http_error(400)]) as m:
            with self.assertRaises(urllib.error.HTTPError):
                net.get_json("https://x", {})
        self.assertEqual(m.call_count, 1)

    def test_error_429_y_500_si_se_reintentan(self):
        with fake_urlopen([http_error(429), http_error(500), {"ok": 1}]) as m:
            self.assertEqual(net.get_json("https://x", {}), {"ok": 1})
        self.assertEqual(m.call_count, 3)


if __name__ == "__main__":
    unittest.main()
