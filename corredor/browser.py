"""Renderiza páginas que se arman con JavaScript usando Chrome/Edge "headless".

No instala nada: usa el navegador que ya está en la máquina (los servidores de
GitHub Actions traen Google Chrome; en Windows sirve Chrome o Edge).
Se puede forzar uno con la variable de entorno CHROME_PATH.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_CANDIDATES_PATH = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge")
_CANDIDATES_WIN = (
    r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
    r"%LocalAppData%\Google\Chrome\Application\chrome.exe",
    r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
    r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe",
)
_CANDIDATES_MAC = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
)


class BrowserNotFound(RuntimeError):
    pass


def find_browser() -> str:
    """Ruta del navegador a usar, o BrowserNotFound."""
    env = os.environ.get("CHROME_PATH", "").strip()
    if env:
        return env
    for name in _CANDIDATES_PATH:
        found = shutil.which(name)
        if found:
            return found
    for raw in _CANDIDATES_WIN if sys.platform == "win32" else _CANDIDATES_MAC:
        path = Path(os.path.expandvars(raw))
        if path.exists():
            return str(path)
    raise BrowserNotFound("no se encontró Chrome/Chromium/Edge (se puede indicar con CHROME_PATH)")


def render_dom(url: str, wait_ms: int = 15000, timeout_s: int = 90) -> str:
    """Abre `url`, deja correr el JavaScript hasta `wait_ms` y devuelve el HTML resultante."""
    with tempfile.TemporaryDirectory(prefix="corredor-chrome-") as profile:
        cmd = [
            find_browser(),
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "--mute-audio",
            f"--user-data-dir={profile}",
            f"--virtual-time-budget={wait_ms}",
            "--dump-dom",
            url,
        ]
        if os.environ.get("CI"):  # servidores de GitHub: máquina descartable
            cmd.insert(1, "--no-sandbox")
        result = subprocess.run(cmd, capture_output=True, timeout=timeout_s)
    html = result.stdout.decode("utf-8", errors="replace")
    if result.returncode != 0 or "<html" not in html.lower():
        err = result.stderr.decode("utf-8", errors="replace").strip().splitlines()[-1:] or [""]
        raise RuntimeError(f"el navegador terminó con código {result.returncode}: {err[0][:200]}")
    return html
