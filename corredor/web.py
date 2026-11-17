"""Genera la web estática (un solo index.html, sin librerías externas).

Pensada para el celular y para señal mala en ruta: todo viene en un archivo
de pocos KB. Se regenera después de cada recolección.
"""

from __future__ import annotations

import urllib.parse
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from . import config
from .conditions import RouteStatus, Snapshot, fmt_local, level_for, snapshot, summary_text

LEVEL_LABEL = {"bajo": "Riesgo bajo", "medio": "Riesgo medio", "alto": "Riesgo alto", None: "Sin datos"}


def _n(value: float | None, unit: str = "") -> str:
    return "–" if value is None else f"{value:.0f}{unit}"


def _sparkline(st: RouteStatus) -> str:
    """Gráfico mínimo (SVG) de la ráfaga en las últimas 24 h, con las líneas de los umbrales."""
    if len(st.history) < 2:
        return '<p class="muted small">Todavía no hay historial suficiente para el gráfico.</p>'
    w, h, pad = 300, 70, 4
    t0, t1 = st.history[0][0].timestamp(), st.history[-1][0].timestamp()
    top = max([g for _, g in st.history] + [lim for lim, _ in config.GUST_LEVELS]) * 1.1

    def xy(t: float, g: float) -> tuple[float, float]:
        x = pad + (t - t0) / max(t1 - t0, 1) * (w - 2 * pad)
        y = h - pad - g / top * (h - 2 * pad)
        return round(x, 1), round(y, 1)

    pts = " ".join(f"{x},{y}" for x, y in (xy(t.timestamp(), g) for t, g in st.history))
    lines = "".join(
        f'<line x1="0" x2="{w}" y1="{xy(t0, lim)[1]}" y2="{xy(t0, lim)[1]}" class="th th-{name}"/>'
        for lim, name in config.GUST_LEVELS
    )
    return (
        f'<svg viewBox="0 0 {w} {h}" class="spark" role="img" '
        f'aria-label="Ráfagas de las últimas 24 horas">{lines}'
        f'<polyline points="{pts}" class="line"/></svg>'
        f'<p class="muted small">Ráfagas, últimas 24 h · líneas: umbrales de riesgo medio y alto</p>'
    )


def _route_card(st: RouteStatus) -> str:
    lvl = st.level or "nd"
    wave = (f'<div><dt>Oleaje</dt><dd>{st.wave_m:.1f} <small>m</small></dd></div>'
            if st.wave_m is not None else "")
    return f"""
<article class="card">
  <header>
    <div><h2>{escape(st.name)}</h2><p class="muted small">{escape(st.detail)}</p></div>
    <span class="badge b-{lvl}">{LEVEL_LABEL[st.level]}</span>
  </header>
  <dl class="stats">
    <div><dt>Ráfagas</dt><dd>{_n(st.gust_kmh)} <small>km/h</small></dd></div>
    <div><dt>Viento</dt><dd>{_n(st.wind_kmh)} <small>km/h</small></dd></div>
    {wave}
  </dl>
  <p class="forecast">Próximas 24 h: ráfagas de hasta <b>{_n(st.forecast_gust_kmh)} km/h</b>
    <span class="badge small b-{st.forecast_level or 'nd'}">{LEVEL_LABEL[st.forecast_level]}</span></p>
  {_sparkline(st)}
</article>"""


def _places_table(snap: Snapshot) -> str:
    rows = []
    for key, name in config.PLACE_NAMES.items():
        r = snap.places.get(key)
        if not r:
            continue
        gust = float(r["gust_kmh"]) if r["gust_kmh"] else None
        rows.append(
            f'<tr><td>{escape(name)}</td><td>{_n(gust)}</td><td>{_n(float(r["wind_kmh"]) if r["wind_kmh"] else None)}</td>'
            f'<td><span class="dot d-{level_for(gust) or "nd"}"></span></td></tr>'
        )
    return ("<table><thead><tr><th>Lugar</th><th>Ráfagas</th><th>Viento</th><th></th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table><p class='muted small'>km/h</p>")


def render(snap: Snapshot, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    updated = f"Actualizado {fmt_local(snap.latest)} (hora local, UTC-3)" if snap.latest else "Sin datos todavía"
    stale = ('<div class="alert">⚠️ Los datos tienen más de '
             f'{config.STALE_AFTER_H} h. Pueden no reflejar la situación actual.</div>') if snap.is_stale(now) else ""
    wa = "https://wa.me/?text=" + urllib.parse.quote(summary_text(snap))
    tg = (f'<a class="btn" href="{escape(config.TELEGRAM_URL)}" rel="noopener">Seguir en Telegram</a>'
          if config.TELEGRAM_URL else "")
    limits = " · ".join(f"{name}: desde {lim:.0f} km/h" for lim, name in sorted(config.GUST_LEVELS))
    cards = "".join(_route_card(r) for r in snap.routes)
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="900">
<title>Corredor Austral</title>
<meta name="description" content="Viento y riesgo de demora en los cruces del Estrecho de Magallanes (BETA)">
<style>
:root{{--bg:#f6f7f9;--card:#fff;--fg:#14181f;--muted:#5d6672;--line:#e3e6ea;--accent:#1f6feb;
--ok:#1a7f37;--ok-bg:#dafbe1;--mid:#9a6700;--mid-bg:#fff3c4;--hi:#c1121f;--hi-bg:#ffe0e0;--nd:#6e7781;--nd-bg:#eaeef2}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0d1117;--card:#161b22;--fg:#e6edf3;--muted:#9aa4af;--line:#30363d;
--accent:#58a6ff;--ok:#3fb950;--ok-bg:#0f2e1a;--mid:#d29922;--mid-bg:#33270a;--hi:#ff7b72;--hi-bg:#3d1416;--nd:#8b949e;--nd-bg:#21262d}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}}
main{{max-width:640px;margin:0 auto;padding:16px}}
h1{{font-size:1.4rem;margin:0}} h2{{font-size:1.1rem;margin:0}}
.top{{display:flex;justify-content:space-between;align-items:baseline;gap:8px;flex-wrap:wrap}}
.beta{{font-size:.75rem;font-weight:700;color:var(--accent);border:1px solid var(--accent);border-radius:99px;padding:1px 8px}}
.muted{{color:var(--muted)}} .small{{font-size:.8rem;margin:.25rem 0}}
.note{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;font-size:.9rem;margin:12px 0}}
.alert{{background:var(--mid-bg);color:var(--mid);border-radius:10px;padding:10px 12px;font-weight:600;margin:12px 0}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px;margin:12px 0}}
.card header{{display:flex;justify-content:space-between;align-items:flex-start;gap:8px}}
.badge{{border-radius:99px;padding:4px 10px;font-weight:700;font-size:.85rem;white-space:nowrap}}
.badge.small{{font-size:.72rem;padding:2px 8px}}
.b-bajo{{background:var(--ok-bg);color:var(--ok)}} .b-medio{{background:var(--mid-bg);color:var(--mid)}}
.b-alto{{background:var(--hi-bg);color:var(--hi)}} .b-nd{{background:var(--nd-bg);color:var(--nd)}}
.stats{{display:flex;gap:20px;margin:12px 0 4px}} .stats div{{min-width:0}}
dt{{font-size:.75rem;color:var(--muted);text-transform:uppercase;letter-spacing:.04em}}
dd{{margin:0;font-size:1.8rem;font-weight:700;font-variant-numeric:tabular-nums}} dd small{{font-size:.8rem;font-weight:500;color:var(--muted)}}
.forecast{{margin:6px 0 8px}}
.spark{{width:100%;height:70px;display:block}} .spark .line{{fill:none;stroke:var(--accent);stroke-width:2}}
.spark .th{{stroke-dasharray:4 4;stroke-width:1}} .th-medio{{stroke:var(--mid)}} .th-alto{{stroke:var(--hi)}}
.actions{{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}}
.btn{{display:inline-block;padding:10px 14px;border-radius:10px;background:var(--card);border:1px solid var(--line);
color:var(--fg);text-decoration:none;font-weight:600}} .btn.primary{{background:#25d366;border-color:#25d366;color:#08311a}}
table{{width:100%;border-collapse:collapse;background:var(--card);border-radius:12px;overflow:hidden}}
th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}}
th{{font-size:.75rem;color:var(--muted);text-transform:uppercase}}
.dot{{display:inline-block;width:10px;height:10px;border-radius:50%}}
.d-bajo{{background:var(--ok)}} .d-medio{{background:var(--mid)}} .d-alto{{background:var(--hi)}} .d-nd{{background:var(--nd)}}
footer{{margin:24px 0 8px;font-size:.8rem;color:var(--muted)}} a{{color:var(--accent)}}
</style>
</head>
<body>
<main>
  <div class="top"><h1>Corredor Austral</h1><span class="beta">BETA</span></div>
  <p class="muted small">{updated}</p>
  <div class="note">Riesgo de demora estimado <b>solo por viento</b>. <b>No es el estado oficial</b> del cruce:
    confirmalo en <a href="{config.OFFICIAL_URL}" rel="noopener">tabsa.cl/estado-cruces</a>.</div>
  {stale}
  {cards}
  <div class="actions">
    <a class="btn primary" href="{escape(wa)}" rel="noopener">Compartir por WhatsApp</a>
    {tg}
    <a class="btn" href="{config.OFFICIAL_URL}" rel="noopener">Estado oficial TABSA</a>
  </div>
  <h2>Otros puntos de la ruta</h2>
  {_places_table(snap)}
  <footer>
    <p>Umbrales provisorios de ráfaga — {limits}. Se van a ajustar con el historial real de suspensiones.</p>
    <p>Datos: <a href="https://open-meteo.com/" rel="noopener">Open-Meteo</a> (modelo, no estación). Se actualiza cada ~30 min.</p>
  </footer>
</main>
</body>
</html>
"""


def build_site(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "index.html"
    path.write_text(render(snapshot()), encoding="utf-8", newline="\n")
    return path
