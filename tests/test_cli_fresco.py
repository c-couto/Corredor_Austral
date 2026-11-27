"""python -m corredor web --fresco: la web con los datos más nuevos de GitHub, sin tocar data/."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from corredor import cli

GIT = shutil.which("git")


@unittest.skipUnless(GIT, "hace falta git")
class DatosDeGithubTest(unittest.TestCase):
    def git(self, repo, *args):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True,
                       capture_output=True)

    def test_copia_data_de_la_rama_sin_tocar_la_carpeta_local(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            self.git(repo, "init", "-q")
            (repo / "data" / "auto").mkdir(parents=True)
            archivo = repo / "data" / "auto" / "tabsa_estado.csv"
            archivo.write_text("ts_utc,crossing,status\n2026-11-27T20:05:00Z,rio_verde,NORMAL\n", encoding="utf-8")
            self.git(repo, "add", "-A")
            self.git(repo, "commit", "-q", "-m", "datos")
            # la copia local queda distinta (como la tuya): se le agrega una fila que NO está en el commit
            archivo.write_text(archivo.read_text(encoding="utf-8") + "LOCAL-NO-COMMITEADO\n", encoding="utf-8")

            tmp = cli.datos_de_github(ref="HEAD", repo=repo)
            try:
                copia = (tmp / "data" / "auto" / "tabsa_estado.csv").read_text(encoding="utf-8")
                self.assertIn("2026-11-27T20:05:00Z", copia)
                self.assertNotIn("LOCAL-NO-COMMITEADO", copia)                       # es lo que hay en GitHub
                self.assertIn("LOCAL-NO-COMMITEADO", archivo.read_text(encoding="utf-8"))  # y lo local ni se tocó
            finally:
                shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
