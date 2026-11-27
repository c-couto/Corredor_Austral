"""Modelo en sombra: datos nuevos (marea y viento respecto del eje) que solo se evalúan, nunca se muestran."""

import random
import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from corredor import config, model, sombra

from .helpers import TempDataDir

T0 = datetime(2026, 11, 1, tzinfo=timezone.utc)
RAIZ = Path(__file__).resolve().parent.parent / "corredor"


def fila_marea(emitido, valido, nivel, lugar="punta_delgada"):
    return {"issued_utc": emitido.strftime("%Y-%m-%dT%H:%M:%SZ"), "place": lugar,
            "valid_utc": valido.strftime("%Y-%m-%dT%H:%M:%SZ"), "sea_level_m": str(nivel)}


class EjeYVientoTest(unittest.TestCase):
    def test_rumbo_de_los_puntos_cardinales(self):
        self.assertAlmostEqual(sombra.rumbo((0, 0), (1, 0)), 0, places=3)     # norte
        self.assertAlmostEqual(sombra.rumbo((0, 0), (0, 1)), 90, places=3)    # este
        self.assertAlmostEqual(sombra.rumbo((0, 0), (-1, 0)), 180, places=3)  # sur

    def test_ejes_de_los_tres_cruces(self):
        self.assertEqual(set(sombra.EJES), set(config.ROUTES))
        self.assertAlmostEqual(sombra.eje_grados("primera_angostura"), 158, delta=3)   # Punta Delgada → Bahía Azul (SSE)
        self.assertAlmostEqual(sombra.eje_grados("punta_arenas_porvenir"), 305, delta=3)  # Porvenir → Punta Arenas (NO)

    def test_viento_transversal_y_longitudinal(self):
        eje = 158.0
        self.assertEqual(sombra.viento_respecto_del_eje(80, None, eje), (0.0, 0.0))
        t, l = sombra.viento_respecto_del_eje(80, eje, eje)           # sopla a lo largo del cruce
        self.assertAlmostEqual(t, 0, places=6)
        self.assertAlmostEqual(l, 80, places=6)
        t, l = sombra.viento_respecto_del_eje(80, eje + 90, eje)      # sopla de costado
        self.assertAlmostEqual(t, 80, places=6)
        self.assertAlmostEqual(l, 0, places=6)
        # de un lado o del otro del cruce es lo mismo para el ferry
        self.assertEqual(sombra.viento_respecto_del_eje(80, eje + 30, eje), sombra.viento_respecto_del_eje(80, eje - 30, eje))


class MareasTest(unittest.TestCase):
    def setUp(self):
        e = datetime(2026, 11, 20, 12, 5, tzinfo=timezone.utc)
        h = lambda k: e.replace(minute=0) + timedelta(hours=k)
        self.e = e
        self.mareas = sombra.Mareas([fila_marea(e, h(k), n) for k, n in ((0, 1.0), (1, 3.0), (2, 2.0))])

    def test_nivel_y_cuanto_sube_por_hora(self):
        t = self.e.replace(minute=30)
        nivel, tasa = self.mareas.en("punta_delgada", t)
        self.assertAlmostEqual(nivel, 2.0)     # a medio camino entre 1,0 y 3,0
        self.assertAlmostEqual(tasa, 2.0)      # sube 2 m en esa hora

    def test_baja_tiene_tasa_negativa(self):
        nivel, tasa = self.mareas.en("punta_delgada", self.e.replace(hour=13, minute=0))
        self.assertAlmostEqual(tasa, -1.0)

    def test_sin_pronostico_viejo_ni_del_futuro(self):
        self.assertIsNone(self.mareas.en("punta_delgada", self.e - timedelta(minutes=10)))    # antes de la emisión
        self.assertIsNone(self.mareas.en("punta_delgada", self.e + timedelta(hours=5)))       # pronóstico muy viejo
        self.assertIsNone(self.mareas.en("bahia_azul", self.e))                               # lugar sin datos


class ExtenderTest(unittest.TestCase):
    def test_rio_verde_no_usa_marea(self):
        x = model.vector(80, 48, 270.0)
        e = sombra.extender("rio_verde", T0, x, None)
        self.assertEqual(len(e), 6)  # 4 de siempre + transversal + longitudinal
        self.assertEqual(len(sombra.nombres_de_datos("rio_verde")), 6)

    def test_primera_angostura_exige_la_marea(self):
        x = model.vector(80, 48, 270.0)
        self.assertIsNone(sombra.extender("primera_angostura", T0, x, sombra.Mareas([])))
        e = datetime(2026, 11, 20, 12, 5, tzinfo=timezone.utc)
        mareas = sombra.Mareas([fila_marea(e, e.replace(minute=0) + timedelta(hours=k), n)
                                for k, n in ((0, 0.0), (1, 2.0))])
        v = sombra.extender("primera_angostura", e, x, mareas)
        self.assertEqual(len(v), 9)
        self.assertEqual(len(sombra.nombres_de_datos("primera_angostura")), 9)
        self.assertGreater(v[-1], 0)  # |tasa|


def sinteticas(n=900, seed=5):
    """Cruce que se suspende por viento fuerte Y con la marea que baja (el dato nuevo ayuda de verdad)."""
    rnd = random.Random(seed)
    out = []
    for i in range(n):
        g = rnd.uniform(30, 95)
        tasa = rnd.uniform(-2, 2)
        z = (g - 70) / 6 + (-1.5 * tasa)
        y = 1 if rnd.random() < model.sigmoid(z) else 0
        x = model.vector(g, g * 0.6, 270.0) + [g * 0.9, g * 0.2, 0.0, tasa, abs(tasa)]
        out.append((T0 + timedelta(minutes=30 * i), x, y))
    return out


class CompararTest(unittest.TestCase):
    def test_con_pocas_suspensiones_no_evalua(self):
        with mock.patch.object(sombra, "muestras", return_value=sinteticas(200)):
            c = sombra.comparar("primera_angostura", eventos=2)
        self.assertIn("todavía no se puede evaluar", c["veredicto"])
        self.assertNotIn("brier_sombra", c)

    def test_si_los_datos_nuevos_ayudan_lo_dice(self):
        with mock.patch.object(sombra, "muestras", return_value=sinteticas()):
            c = sombra.comparar("primera_angostura", eventos=20)
        self.assertGreaterEqual(c["temporales_prueba"], 2)
        self.assertLess(c["brier_sombra"], c["brier_mismo_modelo_sin_datos_nuevos"])
        self.assertTrue(c["veredicto"].startswith("MEJORA"))

    def test_si_no_ayudan_dice_que_no_mejora(self):
        # La marea no tiene nada que ver con la suspensión: la sombra no le gana al modelo sin ella.
        rnd = random.Random(9)
        datos = []
        for t, x, _ in sinteticas():
            g = x[0]
            y = 1 if rnd.random() < model.sigmoid((g - 70) / 6) else 0
            datos.append((t, x, y))
        with mock.patch.object(sombra, "muestras", return_value=datos):
            c = sombra.comparar("primera_angostura", eventos=20)
        if c["brier_sombra"] >= c["brier_mismo_modelo_sin_datos_nuevos"]:
            self.assertTrue(c["veredicto"].startswith("no mejora"))
        else:
            self.assertLess(c["mejora_pct"], 5)   # una ganancia mínima es ruido, no una mejora real


class SoloInformaTest(TempDataDir):
    def test_el_informe_funciona_sin_datos_y_no_escribe_nada_en_data(self):
        antes = sorted(p.name for p in self.data_dir.rglob("*") if p.is_file())
        texto = sombra.texto()
        self.assertIn("MODELO EN SOMBRA", texto)
        self.assertIn("todavía no se puede evaluar", texto)
        self.assertEqual(antes, sorted(p.name for p in self.data_dir.rglob("*") if p.is_file()))

    def test_ninguna_parte_visible_ni_de_la_recoleccion_usa_la_sombra(self):
        # La sombra solo se lee desde corredor.evaluacion (informe) y desde sí misma.
        for archivo in ("web.py", "conditions.py", "collect.py", "alerts.py", "predicciones.py", "model.py",
                        "resultados.py", "forecast.py"):
            codigo = (RAIZ / archivo).read_text(encoding="utf-8")
            self.assertIsNone(re.search(r"\bsombra\b", codigo.replace("en sombra", "")), archivo)
        self.assertIn("sombra", (RAIZ / "evaluacion.py").read_text(encoding="utf-8"))
        self.assertFalse((self.data_dir / "model" / "modelo_sombra.json").exists())


if __name__ == "__main__":
    unittest.main()
