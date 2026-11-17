import unittest

from corredor import storage

from .helpers import TempDataDir


class AppendRowsTest(TempDataDir):
    def test_crea_archivo_con_encabezado_y_agrega_al_final(self):
        storage.append_rows(storage.CROSSINGS, [{"ts_utc": "t1", "route": "r", "delay_minutes": 90}])
        storage.append_rows(storage.CROSSINGS, [{"ts_utc": "t2", "route": "r", "delay_minutes": 30, "note": "x"}])
        text = storage.CROSSINGS.path.read_text(encoding="utf-8")
        self.assertEqual(text, "ts_utc,route,delay_minutes,note\nt1,r,90,\nt2,r,30,x\n")

    def test_va_a_la_carpeta_correcta(self):
        storage.append_rows(storage.WEATHER, [{"ts_utc": "t"}])
        storage.append_rows(storage.STATUS, [{"ts_utc": "t"}])
        self.assertTrue((self.data_dir / "auto" / "weather_obs.csv").exists())
        self.assertTrue((self.data_dir / "manual" / "status_obs.csv").exists())

    def test_sin_filas_no_crea_nada(self):
        self.assertEqual(storage.append_rows(storage.EVENTS, []), 0)
        self.assertFalse(storage.EVENTS.path.exists())

    def test_repara_archivo_sin_salto_de_linea_final(self):
        path = storage.EVENTS.path
        path.parent.mkdir(parents=True)
        path.write_text("ts_utc,mode,place,kind,note\nt1,mar,,suspendido,", encoding="utf-8")
        storage.append_rows(storage.EVENTS, [{"ts_utc": "t2", "mode": "aire", "kind": "cancelado"}])
        rows = storage.read_rows(storage.EVENTS)
        self.assertEqual([r["ts_utc"] for r in rows], ["t1", "t2"])

    def test_texto_con_comas_y_comillas(self):
        note = 'viento "fuerte", cola larga'
        storage.append_rows(storage.STATUS, [{"ts_utc": "t", "subject": "s", "status": "x", "note": note}])
        self.assertEqual(storage.read_rows(storage.STATUS)[0]["note"], note)

    def test_leer_tabla_inexistente(self):
        self.assertEqual(storage.read_rows(storage.MARINE), [])


if __name__ == "__main__":
    unittest.main()
