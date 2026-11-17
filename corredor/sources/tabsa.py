"""TABSA: estado oficial de los cruces (https://www.tabsa.cl/estado-cruces).

La página se arma con JavaScript, así que primero se renderiza con Chrome/Edge
headless (ver browser.py) y después se leen las tablas visibles, igual que las
ve una persona. No se usan las APIs internas de TABSA.

Si la estructura de la página cambia, `parse` lanza TabsaFormatError en lugar
de devolver datos dudosos: la falla queda en collector_errors.csv.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import PurePosixPath

from .. import browser, config

DATE_RE = re.compile(r"(\d{2})-(\d{2})-(\d{4})")
TIME_RE = re.compile(r"^\d{1,2}:\d{2}$")


class TabsaFormatError(ValueError):
    """La página no tiene la forma esperada (¿TABSA la cambió?)."""


@dataclass(frozen=True)
class CrossingState:
    key: str      # p. ej. "primera_angostura"
    name: str     # como lo escribe TABSA, p. ej. "Primera Angostura"
    status: str   # en mayúsculas, p. ej. "NORMAL"
    icon: str     # nombre del ícono, p. ej. "EstadoCruceEnViaje"


@dataclass(frozen=True)
class Sailing:
    date: str          # AAAA-MM-DD (hora local)
    origin: str
    destination: str
    boarding: str      # HH:MM local
    departure: str     # HH:MM local
    status: str
    icon: str

    @property
    def subject(self) -> str:
        """Identificador estable de la salida, para seguir sus cambios de estado."""
        return f"{self.date} {self.departure} {self.origin} -> {self.destination}"


@dataclass
class TabsaPage:
    crossings: list[CrossingState] = field(default_factory=list)
    sailings: list[Sailing] = field(default_factory=list)


def slug(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _icon_name(src: str) -> str:
    # "/static/media/EstadoCruceEnViaje.af49....svg" -> "EstadoCruceEnViaje"
    return PurePosixPath(src).name.split(".")[0] if src else ""


class _TableCollector(HTMLParser):
    """Recorre el HTML en orden y junta: subtítulos con fecha y tablas (filas de celdas)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, object]] = []  # ("date", "AAAA-MM-DD") | ("table", filas)
        self._in_subtitle = False
        self._subtitle_text: list[str] = []
        self._table: list[list[tuple[str, str]]] | None = None
        self._row: list[tuple[str, str]] | None = None
        self._cell_text: list[str] | None = None
        self._cell_icon = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if tag == "p" and "subtitle-cruces-s" in classes:
            self._in_subtitle, self._subtitle_text = True, []
        elif tag == "table" and "table-cruces-s" in classes:
            self._table = []
        elif self._table is not None and tag == "tr":
            self._row = []
        elif self._row is not None and tag in ("td", "th"):
            self._cell_text, self._cell_icon = [], ""
        elif self._cell_text is not None and tag == "img":
            self._cell_icon = _icon_name(a.get("src") or "")

    def handle_endtag(self, tag):
        if tag == "p" and self._in_subtitle:
            self._in_subtitle = False
            m = DATE_RE.search(" ".join(self._subtitle_text))
            if m:
                d, mth, y = m.groups()
                self.blocks.append(("date", f"{y}-{mth}-{d}"))
        elif tag in ("td", "th") and self._cell_text is not None and self._row is not None:
            self._row.append((" ".join(" ".join(self._cell_text).split()), self._cell_icon))
            self._cell_text = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.blocks.append(("table", self._table))
            self._table = None

    def handle_data(self, data):
        if self._in_subtitle:
            self._subtitle_text.append(data)
        if self._cell_text is not None:
            self._cell_text.append(data)


def _texts(row: list[tuple[str, str]]) -> list[str]:
    return [t for t, _ in row if t]


def _icon(row: list[tuple[str, str]]) -> str:
    return next((i for _, i in row if i), "")


def parse(html: str) -> TabsaPage:
    collector = _TableCollector()
    collector.feed(html)
    page = TabsaPage()
    current_date: str | None = None
    for kind, value in collector.blocks:
        if kind == "date":
            current_date = value
            continue
        rows = value
        if not rows:
            continue
        header = [t.lower() for t in _texts(rows[0])]
        body = [r for r in rows[1:] if _texts(r)]
        if header and header[0] == "lugar":
            for r in body:
                texts = _texts(r)
                if len(texts) < 2:
                    raise TabsaFormatError(f"fila de estado inesperada: {texts}")
                page.crossings.append(CrossingState(slug(texts[0]), texts[0], texts[-1].upper(), _icon(r)))
        elif header and header[0] == "origen":
            if current_date is None:
                raise TabsaFormatError("tabla de cruces programados sin fecha")
            for r in body:
                texts = _texts(r)
                if len(texts) < 5 or not (TIME_RE.match(texts[2]) and TIME_RE.match(texts[3])):
                    raise TabsaFormatError(f"fila de cruce programado inesperada: {texts}")
                page.sailings.append(Sailing(current_date, texts[0], texts[1], texts[2], texts[3],
                                             texts[4].upper(), _icon(r)))
    if not any(c.key == "primera_angostura" for c in page.crossings):
        raise TabsaFormatError("no se encontró la tabla de estado con Primera Angostura")
    return page


def fetch() -> TabsaPage:
    """Abre la página de TABSA y devuelve los estados que muestra."""
    return parse(browser.render_dom(config.TABSA_URL))
