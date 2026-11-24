"""Genera la web estática: un solo index.html, sin librerías externas.

"El semáforo del Estrecho":
  - Encabezado: bandera de Tierra del Fuego, reloj en vivo de la región (UTC-3) y clima actual.
  - Por cruce: estado oficial, veredicto en palabras ("Se espera cruce normal"...), probabilidad
    de suspensión, gráfico de ráfagas (24 h medidas + 48 h pronosticadas) sobre zonas de color,
    y en qué horario podría suspenderse.
  - Planificador "¿A qué hora salgo?", próximas salidas a Porvenir, historial, cómo se calcula,
    y espacios comerciales (Plan Flota, "Dónde esperar").

Pensada para el celular y para señal mala en ruta: un archivo de pocos KB.
"""

from __future__ import annotations

import json
import math
import urllib.parse
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

from . import __version__, config, model
from .conditions import (RouteStatus, Snapshot, closure_windows, describe_weather, fmt_duration,
                         gust_threshold, is_normal, pct, snapshot, summary_text, verdict)
from .timeutil import fmt_local, format_ts, to_local

WEEKDAYS = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")
WEEKDAYS_LONG = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MONTHS = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
          "octubre", "noviembre", "diciembre")
CARDINALS = ("N", "NE", "E", "SE", "S", "SO", "O", "NO")
STRIP_PLACES = ("punta_arenas", "porvenir", "rio_grande", "ushuaia")  # clima en el encabezado


def _n(value: float | None, unit: str = "") -> str:
    return "–" if value is None else f"{value:.0f}{unit}"


def _cardinal(deg: float | None) -> str:
    return "" if deg is None else CARDINALS[round(deg / 45) % 8]


def _lvl(p: float | None) -> str:
    return model.level_for_prob(p) or "nd"


def _day_label(dt: datetime, now: datetime) -> str:
    d, today = to_local(dt).date(), to_local(now).date()
    if d == today:
        return "hoy"
    if d == today + timedelta(days=1):
        return "mañana"
    return WEEKDAYS_LONG[d.weekday()]


# ------------------------------------------------------------------ bandera

def _star(cx: float, cy: float, r: float) -> str:
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.4
        pts.append(f"{cx + rr * math.cos(a):.0f},{cy + rr * math.sin(a):.0f}")
    return f'<polygon points="{" ".join(pts)}"/>'


# Bandera de la Provincia de Tierra del Fuego (dibujo simplificado en SVG: liviano y nítido).
FLAG_TDF = (
    '<svg class="flag" viewBox="0 0 960 640" role="img" aria-label="Bandera de Tierra del Fuego">'
    '<rect width="960" height="640" fill="#fff"/>'
    '<path fill="#1e85de" d="M190 0H960V640L890 450 540 352 562 265 428 285Z"/>'
    '<path fill="#fd9a2f" d="M0 0 188 90 397 298 285 372H523L845 517 960 640H0Z"/>'
    '<g fill="#fff">' + "".join(_star(*s) for s in (
        (680, 68, 34), (838, 86, 34), (642, 212, 34), (826, 191, 18), (845, 393, 34))) + "</g></svg>"
)


# ------------------------------------------------------------------ encabezado

def _hero(snap: Snapshot) -> str:
    local = to_local(snap.now)
    date = f"{WEEKDAYS_LONG[local.weekday()]} {local.day} de {MONTHS[local.month - 1]}"
    pd = snap.current_weather.get("punta_delgada")
    icon, text = describe_weather(pd)
    main = ""
    if pd:
        main = f"""<div class="wx-main">
      <span class="wx-ico" aria-hidden="true">{icon}</span>
      <div><b>{_n(pd.get("temp_c"))}°</b><span>{escape(text)}</span>
      <small>Primera Angostura · viento {_n(pd.get("wind_kmh"))} km/h {_cardinal(pd.get("wind_dir_deg"))}
      · ráfagas {_n(pd.get("gust_kmh"))}</small></div></div>"""
    chips = []
    for key in STRIP_PLACES:
        w = snap.current_weather.get(key)
        if not w:
            continue
        ico, txt = describe_weather(w)
        chips.append(f'<li title="{escape(txt)}"><span>{escape(config.PLACE_NAMES[key])}</span>'
                     f'<b>{ico} {_n(w.get("temp_c"))}°</b><small>viento {_n(w.get("wind_kmh"))} km/h</small></li>')
    ago = (f'Datos de hace <span data-ago="{format_ts(snap.latest)}">'
           f'{max(0, round((snap.now - snap.latest).total_seconds() / 60))} min</span> · se actualizan cada 30 min'
           if snap.latest else "Sin datos todavía")
    return f"""
<header class="hero"><div class="in">
  <div class="brand">{FLAG_TDF}<div><h1>Corredor Austral <span class="beta">BETA</span></h1>
    <p class="tag">El semáforo del Estrecho de Magallanes</p></div></div>
  <div class="now">
    <div class="clock"><b><span id="clk">{local:%H:%M}</span><small id="clk-s">{local:%S}</small></b>
      <span class="date" id="clk-date">{date}</span><small>Tierra del Fuego y Magallanes · UTC-3</small></div>
    {main}
  </div>
  {f'<ul class="wx-strip">{"".join(chips)}</ul>' if chips else ""}
  <p class="upd">{ago}</p>
</div></header>"""


# ------------------------------------------------------------------ cruce

def _gauge(st: RouteStatus) -> str:
    p = st.p_now
    deg = 0 if p is None else round(p * 360)
    return (f'<div class="gauge g-{_lvl(p)}" style="--deg:{deg}deg" role="img" '
            f'aria-label="Probabilidad de suspensión {pct(p)}">'
            f'<div class="gauge-in"><b>{"–" if p is None else round(p * 100)}<small>%</small></b>'
            f'<span>prob. de<br>suspensión</span></div></div>')


def _official(snap: Snapshot, st: RouteStatus) -> str:
    status, text = snap.official_for(st)
    if config.ROUTES[st.key].get("scheduled") and status:
        nxt = snap.next_sailing()
        text = f"TABSA · próx. zarpe {nxt.departure}: {status}" if nxt else text
    cls = "nd" if status is None else ("ok" if is_normal(status) else "bad")
    return f'<span class="off off-{cls}"><i></i>{escape(text)}</span>'


def _wind(st: RouteStatus) -> str:
    arrow = ""
    if st.wind_dir_deg is not None:  # la flecha apunta hacia donde VA el viento
        arrow = (f'<svg class="arrow" viewBox="0 0 24 24" style="transform:rotate({(st.wind_dir_deg + 180) % 360:.0f}deg)" '
                 f'aria-hidden="true"><path d="M12 3l5 9h-3.5v9h-3v-9H7z"/></svg>')
    wave = (f'<div><dt>Oleaje</dt><dd>{st.wave_m:.1f}<small> m</small></dd></div>' if st.wave_m is not None else "")
    return f"""<dl class="stats">
      <div><dt>Ráfagas</dt><dd>{_n(st.gust_kmh)}<small> km/h</small></dd></div>
      <div><dt>Viento</dt><dd>{_n(st.wind_kmh)}<small> km/h</small></dd></div>
      <div><dt>Desde</dt><dd>{arrow}<small>{_cardinal(st.wind_dir_deg)}</small></dd></div>
      {wave}</dl>"""


def _chart(snap: Snapshot, st: RouteStatus) -> str:
    """Barras de ráfagas por hora: últimas 24 h (medidas) + próximas 48 h (pronóstico),
    sobre zonas de color según la probabilidad de suspensión que implica cada ráfaga."""
    now = snap.now
    start, span = now - timedelta(hours=24), timedelta(hours=72)
    past: dict[datetime, float] = {}
    for dt, g in st.history:
        hour = dt.replace(minute=0, second=0, microsecond=0)
        if hour >= start:
            past[hour] = max(past.get(hour, 0.0), g)
    future = [h for h in st.hours if h.t >= now.replace(minute=0, second=0, microsecond=0) and h.t < start + span]
    if not past and not future:
        return '<p class="muted small">Todavía no hay datos para el gráfico.</p>'

    limits = sorted(config.RISK_LEVELS)  # [(0.2, "medio"), (0.5, "alto")]
    thr = [gust_threshold(st.model, p, st.wind_dir_deg) for p, _ in limits]
    gusts = list(past.values()) + [h.gust for h in future if h.gust is not None]
    top = max([100.0, max(gusts) * 1.15] + [t * 1.25 for t in thr if t])
    top = math.ceil(top / 20) * 20

    W, H, L, R, T, B = 360, 180, 30, 6, 18, 34
    pw, ph = W - L - R, H - T - B
    slot = pw / 72

    def x(t: datetime) -> float:
        return L + (t - start).total_seconds() / span.total_seconds() * pw

    def y(g: float) -> float:
        return T + ph - min(g, top) / top * ph

    parts = []
    # Zonas de fondo: normal / puede suspenderse / probable suspensión.
    edges = [0.0] + [t if t else top for t in thr] + [top]
    for (lo, hi), name in zip(zip(edges, edges[1:]), ("bajo", "medio", "alto")):
        if hi > lo:
            parts.append(f'<rect class="z z-{name}" x="{L}" y="{y(hi):.1f}" width="{pw}" height="{y(lo) - y(hi):.1f}"/>')
    for t, (_, name) in zip(thr, limits):
        if t and t < top:
            parts.append(f'<line class="thl t-{name}" x1="{L}" x2="{W - R}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
                         f'<text class="ax ax-{name}" x="{L - 4}" y="{y(t) + 3:.1f}" text-anchor="end">{t:.0f}</text>')
    parts.append(f'<text class="ax" x="{L - 4}" y="{y(0) + 3:.1f}" text-anchor="end">0</text>'
                 f'<text class="ax" x="{L - 4}" y="{y(top) + 3:.1f}" text-anchor="end">{top:.0f}</text>')
    # Períodos en que TABSA tuvo el cruce suspendido.
    for e in snap.episodes:
        if e.name != st.name:
            continue
        s, f = max(e.start, start), min(e.end or now, start + span)
        if f > s:
            parts.append(f'<rect class="susp" x="{x(s):.1f}" y="{T}" width="{max(2, x(f) - x(s)):.1f}" height="{ph}"/>'
                         f'<text class="ax susp-t" x="{x(s) + 2:.1f}" y="{T + 9}">TABSA: suspendido</text>')
    # Barras: medidas (sólidas) y pronóstico (más claras).
    bw = slot * 0.72
    for hour, g in sorted(past.items()):
        p = st.model.predict(g, g * 0.6, st.wind_dir_deg)
        parts.append(f'<rect class="bar l-{_lvl(p)}" x="{x(hour) + (slot - bw) / 2:.1f}" y="{y(g):.1f}" '
                     f'width="{bw:.1f}" height="{y(0) - y(g):.1f}" rx="1">'
                     f'<title>{fmt_local(hour, "%d/%m %H:%M")} · medido {g:.0f} km/h</title></rect>')
    for h in future:
        if h.gust is None:
            continue
        parts.append(f'<rect class="bar fc l-{_lvl(h.p)}" x="{x(h.t) + (slot - bw) / 2:.1f}" y="{y(h.gust):.1f}" '
                     f'width="{bw:.1f}" height="{y(0) - y(h.gust):.1f}" rx="1">'
                     f'<title>{fmt_local(h.t, "%d/%m %H:%M")} · pronóstico {h.gust:.0f} km/h · '
                     f'prob. de suspensión {pct(h.p)}</title></rect>')
    # Eje de tiempo (hora local). Solo cambia lo que se ESCRIBE debajo del gráfico, no los datos:
    #   fila 1: hora cada 6 h (6 h, 12 h, 18 h); a medianoche, una línea que separa los días.
    #   fila 2: el día con su fecha ("Mié 25"), centrado en la parte visible de ese día.
    t0, t1 = to_local(start), to_local(start + span)
    t = t0.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    while t < t1:
        if t.hour % 6 == 0:
            if t.hour == 0:
                parts.append(f'<line class="daysep" x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{T}" y2="{H - 4}"/>')
            else:
                parts.append(f'<line class="tick" x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{T + ph}" y2="{T + ph + 4}"/>'
                             f'<text class="ax" x="{x(t):.1f}" y="{T + ph + 13}" '
                             f'text-anchor="middle">{t.hour} h</text>')
        t += timedelta(hours=1)
    day = t0.replace(hour=0, minute=0, second=0, microsecond=0)
    while day < t1:
        a, b = max(day, t0), min(day + timedelta(days=1), t1)
        if b - a >= timedelta(hours=6):  # un pedacito de día no lleva nombre (no entra)
            parts.append(f'<text class="ax ax-day" x="{(x(a) + x(b)) / 2:.1f}" y="{H - 4}" '
                         f'text-anchor="middle">{WEEKDAYS[day.weekday()]} {day.day}</text>')
        day += timedelta(days=1)
    parts.append(f'<line class="nowl" x1="{x(now):.1f}" x2="{x(now):.1f}" y1="{T - 6}" y2="{T + ph}"/>'
                 f'<text class="ax now-t" x="{x(now):.1f}" y="{T - 8}" text-anchor="middle">ahora</text>')
    parts.append(f'<text class="ax" x="{L + 2}" y="{T - 8}">km/h</text>')
    label = (f"Ráfagas de {st.name}: últimas 24 horas medidas y próximas 48 horas pronosticadas, "
             f"en kilómetros por hora")
    return f"""<figure class="chartbox">
    <svg class="chart" viewBox="0 0 {W} {H}" role="img" aria-label="{escape(label)}">{"".join(parts)}</svg>
    <figcaption class="legend">
      <span><i class="lg lg-past"></i>Medido</span><span><i class="lg lg-fc"></i>Pronóstico (más claro)</span>
      <span><i class="lg lg-bajo"></i>Zona normal</span><span><i class="lg lg-medio"></i>Puede suspenderse</span>
      <span><i class="lg lg-alto"></i>Probable suspensión</span>
    </figcaption></figure>"""


def _windows(snap: Snapshot, st: RouteStatus) -> str:
    if not st.hours:
        return ""
    wins = closure_windows(st, "medio", 48)
    if not wins:
        return '<p class="win win-ok">✓ Próximas 48 h: sin riesgo relevante de suspensión por viento.</p>'
    items = []
    for first, last, worst in wins[:3]:
        end = last.t + timedelta(hours=1)
        what = "Probable suspensión" if worst == "alto" else "Puede suspenderse"
        items.append(f'<li class="w-{worst}"><b>{what}</b> {_day_label(first.t, snap.now)} '
                     f'{fmt_local(first.t, "%H:%M")}–{fmt_local(end, "%H:%M")}</li>')
    return f'<ul class="wins" aria-label="Horarios con posible suspensión">{"".join(items)}</ul>'


def _route_card(snap: Snapshot, st: RouteStatus) -> str:
    lvl, phrase = verdict(snap, st)
    return f"""
<article class="card route lvl-{lvl}">
  <header>
    <div><h2>{escape(st.name)}</h2><p class="muted small">{escape(st.detail)}</p>{_official(snap, st)}</div>
    {_gauge(st)}
  </header>
  <p class="verdict v-{lvl}"><i></i>{escape(phrase)}</p>
  {_wind(st)}
  {_chart(snap, st)}
  {_windows(snap, st)}
</article>"""


# ------------------------------------------------------------------ secciones

def _planner(snap: Snapshot) -> str:
    st = snap.route(config.PLANNER_ROUTE)
    if not st or not st.hours:
        return ""
    data = {
        "hours": [[int(h.t.timestamp() * 1000), round(h.p, 3)] for h in st.hours],
        "origins": [[name, hours] for name, hours in config.PLANNER_ORIGINS],
        "offset": config.LOCAL_UTC_OFFSET_H,
        "levels": [[lim, name] for lim, name in config.RISK_LEVELS],
    }
    buttons = "".join(f'<button type="button" data-i="{i}">{escape(n)}</button>'
                      for i, (n, _) in enumerate(config.PLANNER_ORIGINS))
    return f"""
<section class="card" id="planificador">
  <h2>¿A qué hora salgo?</h2>
  <p class="muted small">Elegí desde dónde salís: te mostramos la probabilidad de que {escape(st.name)}
  esté suspendido a la hora en que llegarías.</p>
  <div class="seg" role="group" aria-label="Origen">{buttons}</div>
  <p id="plan-best" class="best"></p>
  <ol id="plan-grid" class="plan"></ol>
  <noscript><p class="small">Activá JavaScript para usar el planificador.</p></noscript>
  <script type="application/json" id="plan-data">{json.dumps(data)}</script>
</section>"""


def _sailings(snap: Snapshot) -> str:
    if not snap.sailings:
        return ""
    rows = []
    for s in snap.sailings[:8]:
        ok = is_normal(s.status)
        rows.append(
            f'<tr><td><b>{escape(s.departure)}</b><br><span class="muted small">{escape(s.date[8:10])}/{escape(s.date[5:7])}</span></td>'
            f'<td>{escape(s.origin)} → {escape(s.destination)}</td>'
            f'<td><span class="off off-{"ok" if ok else "bad"}"><i></i>{escape(s.status)}</span></td>'
            f'<td><span class="pill b-{_lvl(s.p)}">{pct(s.p)}</span></td></tr>')
    return f"""
<section class="card">
  <h2>Próximos zarpes Punta Arenas ↔ Porvenir</h2>
  <table><thead><tr><th>Zarpe</th><th>Sentido</th><th>TABSA</th><th>Prob. susp.</th></tr></thead>
  <tbody>{"".join(rows)}</tbody></table>
  <p class="muted small">Estado oficial según TABSA. "Prob. susp.": nuestra estimación de que ese zarpe se
  suspenda por viento.</p>
</section>"""


def _history(snap: Snapshot) -> str:
    items = []
    for e in snap.episodes[:8]:
        end = f"→ {fmt_local(e.end)}" if e.end else '<b class="live">en curso</b>'
        items.append(f'<li><span class="off off-bad"><i></i>{escape(e.status)}</span> <b>{escape(e.name)}</b> · '
                     f'{fmt_local(e.start)} {end} · <b>{fmt_duration(e.duration(snap.now))}</b></li>')
    episodes = (f'<ul class="episodes">{"".join(items)}</ul>' if items
                else '<p class="muted small">Sin suspensiones registradas desde que empezamos a medir.</p>')
    if snap.tabsa_days >= 7:
        head = "".join(f"<th>{h:02d}</th>" if h % 3 == 0 else "<th></th>" for h in range(24))
        body = []
        for d, name in enumerate(WEEKDAYS):
            cells = []
            for h in range(24):
                n, bad = snap.heat.get((d, h), [0, 0])
                share = bad / n if n else None
                alpha = 0.06 if share is None else 0.12 + 0.88 * share
                cells.append(f'<td style="--a:{alpha:.2f}" title="{name} {h:02d} h · '
                             f'{"sin datos" if share is None else f"{round(share * 100)} % suspendido ({n} lecturas)"}"></td>')
            body.append(f"<tr><th>{name}</th>{''.join(cells)}</tr>")
        heat = (f'<h3>¿Cuándo se suspende? Primera Angostura</h3><div class="heatwrap"><table class="heat">'
                f'<thead><tr><th></th>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'
                f'<p class="muted small">Más oscuro = más veces suspendido en ese día y hora (hora local).</p>')
    else:
        heat = (f'<div class="progress"><span style="width:{min(100, round(snap.tabsa_days / 7 * 100))}%"></span></div>'
                f'<p class="muted small">Construyendo el historial que TABSA no guarda: {snap.tabsa_days} de 7 días '
                f'({snap.tabsa_samples} lecturas). Con una semana aparece el mapa de días y horas.</p>')
    return f"""
<section class="card">
  <h2>Historial de suspensiones</h2>
  {episodes}
  {heat}
</section>"""


def _method(snap: Snapshot) -> str:
    rows = []
    for st in snap.routes:
        m = st.model
        tag = ('<span class="pill b-bajo">aprendido</span>' if m.kind == "trained"
               else '<span class="pill b-nd">regla base</span>')
        extra = ""
        if m.metrics.get("auc_modelo") is not None:
            extra = f' · acierta el orden en el {round(m.metrics["auc_modelo"] * 100)} % de los casos'
        rows.append(f"<li><b>{escape(st.name)}</b> {tag}<br><span class='muted small'>{escape(m.reason)}{extra}</span></li>")
    return f"""
<section class="card">
  <h2>Cómo calculamos la probabilidad</h2>
  <p class="small">Cada media hora guardamos el viento y el estado oficial de TABSA. Con ese historial, un modelo
  aprende <b>con cuánto viento se suspende cada cruce</b> y estima la probabilidad para las próximas horas.
  Se reentrena todos los días y solo reemplaza a la regla base si demuestra predecir mejor.</p>
  <ul class="method">{"".join(rows)}</ul>
  <p class="muted small">Normal: menos de 20 % · Puede suspenderse: desde 20 % · Probable suspensión: desde 50 %.</p>
  <p class="small"><b>Predicciones experimentales:</b> el modelo todavía tiene pocas semanas de datos y puede
  equivocarse. No reemplaza al estado oficial de TABSA.</p>
</section>"""


def _business(snap: Snapshot) -> str:
    high = any(verdict(snap, r)[0] == "alto" for r in snap.routes)
    contact = escape(config.CONTACT_URL)
    sponsors = "".join(
        f'<li><a href="{escape(s.get("url", "#"))}" rel="noopener sponsored"><b>{escape(s["name"])}</b></a>'
        f' · {escape(s.get("place", ""))}<br><span class="muted small">{escape(s.get("text", ""))}</span></li>'
        for s in config.SPONSORS)
    wait = ""
    if sponsors or contact:
        cta = (f'<p class="small">¿Tenés un negocio cerca de un cruce? <a href="{contact}" rel="noopener">Aparecé acá</a>.</p>'
               if contact else "")
        wait = (f'<section class="card{" glow" if high else ""}"><h2>Dónde esperar</h2>'
                f'{"<p class=small>El cruce puede demorarse: lugares cerca para esperar.</p>" if high else ""}'
                f'{f"<ul class=sponsors>{sponsors}</ul>" if sponsors else ""}{cta}</section>')
    flota_cta = (f'<a class="btn primary" href="{contact}" rel="noopener">Quiero probarlo gratis</a>' if contact
                 else '<p class="muted small">Próximamente.</p>')
    return f"""{wait}
<section class="card flota">
  <h2>Plan Flota <span class="beta">empresas</span></h2>
  <p class="small">Para transportistas que cruzan a Tierra del Fuego: menos camiones esperando en el cruce.</p>
  <ul class="checks">
    <li>Aviso inmediato por Telegram cuando cambia el estado de tu ruta</li>
    <li>Planificador de salidas para tus choferes</li>
    <li>Informe mensual de demoras y horas perdidas</li>
  </ul>
  {flota_cta}
</section>"""


# ------------------------------------------------------------------ página

CSS = """
:root{--bg:#eef3f7;--card:#fff;--fg:#0f1d2b;--muted:#5b6b7b;--line:#dbe3ea;--brand:#0b4f79;--brand2:#14a3b8;
--ok:#14915a;--ok-bg:#d9f6e7;--mid:#c27400;--mid-bg:#ffefcf;--hi:#d62839;--hi-bg:#ffe1e3;--nd:#7b8794;--nd-bg:#e8edf2;
--shadow:0 1px 2px rgba(15,29,43,.06),0 8px 24px rgba(15,29,43,.06)}
:root{color-scheme:dark;--bg:#07121c;--card:#0f1e2b;--fg:#e7eef5;--muted:#93a4b5;--line:#1f3344;
--brand:#5cc8ff;--brand2:#2fd0c6;--ok:#3ddc97;--ok-bg:#0d2c21;--mid:#f5b13d;--mid-bg:#33260b;--hi:#ff6b78;--hi-bg:#3a1418;
--nd:#8a99a8;--nd-bg:#1a2a38;--shadow:none}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;overflow-x:hidden;background:var(--bg);color:var(--fg);font:16px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:720px;margin:0 auto;padding:0 16px 24px}
.hero{background:radial-gradient(120% 140% at 100% 0,#14a3b8 0,#0e7490 40%,#0b3d63 100%);color:#fff;padding:18px 16px 60px;position:relative;overflow:hidden}
.hero:after{content:"";position:absolute;inset:auto -10% -30px -10%;height:90px;background:repeating-radial-gradient(ellipse at 50% 0,rgba(255,255,255,.07) 0 6px,transparent 6px 18px);pointer-events:none}
.hero .in{max-width:720px;margin:0 auto;position:relative;z-index:1}
.brand{display:flex;align-items:center;gap:12px}
.flag{width:54px;height:36px;border-radius:4px;box-shadow:0 2px 8px rgba(0,0,0,.25);flex:none}
h1{font-size:1.4rem;margin:0;letter-spacing:-.01em;line-height:1.15}h2{font-size:1.1rem;margin:0}h3{font-size:.95rem;margin:16px 0 6px}
.tag{margin:2px 0 0;opacity:.85;font-size:.82rem}
.beta{font-size:.62rem;font-weight:800;letter-spacing:.06em;text-transform:uppercase;border:1px solid currentColor;border-radius:99px;padding:1px 7px;vertical-align:middle;opacity:.9}
.now{display:flex;gap:16px;align-items:center;justify-content:space-between;margin-top:16px;flex-wrap:wrap}
.clock b{display:block;font-size:2.6rem;line-height:1;font-weight:750;font-variant-numeric:tabular-nums;letter-spacing:-.02em}
.clock b small{font-size:1rem;font-weight:600;opacity:.7;margin-left:3px}
.clock .date{display:block;font-size:.9rem;margin-top:6px}.clock .date::first-letter{text-transform:uppercase}.clock>small{font-size:.7rem;opacity:.75}
.wx-main{display:flex;gap:10px;align-items:center;background:rgba(255,255,255,.12);border:1px solid rgba(255,255,255,.18);border-radius:14px;padding:8px 12px;backdrop-filter:blur(4px)}
.wx-ico{font-size:2.2rem;line-height:1}.wx-main b{font-size:1.6rem;line-height:1}.wx-main span{display:block;font-size:.85rem;font-weight:600}
.wx-main small{display:block;font-size:.7rem;opacity:.85;max-width:220px}
.wx-strip{list-style:none;padding:0;margin:14px 0 0;display:grid;grid-template-columns:repeat(auto-fit,minmax(78px,1fr));gap:6px}
.wx-strip li{background:rgba(255,255,255,.1);border-radius:10px;padding:6px 8px;font-size:.72rem;line-height:1.25}
.wx-strip span{display:block;opacity:.85}.wx-strip b{display:block;font-size:.95rem}.wx-strip small{opacity:.8}
.upd{margin:10px 0 0;font-size:.72rem;opacity:.8}
.wrap{margin-top:-44px;position:relative;z-index:2}
.muted{color:var(--muted)}.small{font-size:.82rem;margin:.3rem 0}
.alert{background:var(--mid-bg);color:var(--mid);border-radius:12px;padding:10px 12px;font-weight:600;margin:12px 0}
.info{display:flex;gap:10px;background:var(--card);border:1px solid var(--line);border-left:4px solid var(--brand);border-radius:12px;padding:10px 12px;font-size:.84rem;margin:12px 0;box-shadow:var(--shadow)}
.info b{color:var(--brand)}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px;margin:12px 0;box-shadow:var(--shadow)}
.card.glow{border-color:var(--mid);box-shadow:0 0 0 3px var(--mid-bg)}
.route{border-top:4px solid var(--nd)}.lvl-bajo{border-top-color:var(--ok)}.lvl-medio{border-top-color:var(--mid)}.lvl-alto{border-top-color:var(--hi)}
.route header{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.route header>div{min-width:0}
.off{display:inline-flex;align-items:center;gap:6px;font-weight:700;font-size:.76rem;margin-top:6px;border-radius:99px;padding:3px 10px}
.off i{width:8px;height:8px;border-radius:50%;background:currentColor;flex:none}
.off-ok{background:var(--ok-bg);color:var(--ok)}.off-bad{background:var(--hi-bg);color:var(--hi)}.off-nd{background:var(--nd-bg);color:var(--nd)}
.off-bad i,.v-alto i{animation:pulse 1.4s infinite}@keyframes pulse{50%{opacity:.25}}
@media (prefers-reduced-motion:reduce){.off-bad i,.v-alto i{animation:none}}
.verdict{display:flex;align-items:center;gap:8px;font-weight:750;font-size:1.05rem;margin:12px 0 0}
.verdict i{width:12px;height:12px;border-radius:50%;background:var(--nd);flex:none}
.v-bajo{color:var(--ok)}.v-bajo i{background:var(--ok)}.v-medio{color:var(--mid)}.v-medio i{background:var(--mid)}.v-alto{color:var(--hi)}.v-alto i{background:var(--hi)}
.gauge{--c:var(--nd);width:86px;height:86px;flex:none;border-radius:50%;background:conic-gradient(var(--c) var(--deg),var(--nd-bg) 0);display:grid;place-items:center}
.g-bajo{--c:var(--ok)}.g-medio{--c:var(--mid)}.g-alto{--c:var(--hi)}
.gauge-in{width:68px;height:68px;border-radius:50%;background:var(--card);display:grid;place-items:center;align-content:center;line-height:1;text-align:center}
.gauge-in b{font-size:1.4rem;font-variant-numeric:tabular-nums}.gauge-in small{font-size:.7rem}
.gauge-in span{font-size:.52rem;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;line-height:1.15;margin-top:2px}
.stats{display:flex;gap:18px;margin:12px 0 6px;flex-wrap:wrap}.stats div{min-width:0}
dt{font-size:.68rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
dd{margin:0;font-size:1.45rem;font-weight:750;font-variant-numeric:tabular-nums;display:flex;align-items:center;gap:4px}dd small{font-size:.75rem;font-weight:500;color:var(--muted)}
.arrow{width:24px;height:24px;fill:var(--brand)}
.chartbox{margin:8px 0 0}.chart{width:100%;height:auto;display:block;overflow:visible}
.z{opacity:.11}.z-bajo{fill:var(--ok);opacity:.07}.z-medio{fill:var(--mid)}.z-alto{fill:var(--hi)}
.thl{stroke-width:1;stroke-dasharray:3 3}.t-medio{stroke:var(--mid)}.t-alto{stroke:var(--hi)}
.bar.l-bajo{fill:var(--ok)}.bar.l-medio{fill:var(--mid)}.bar.l-alto{fill:var(--hi)}.bar.l-nd{fill:var(--nd)}.bar.fc{opacity:.45}
.susp{fill:var(--hi);opacity:.14}.susp-t{fill:var(--hi);font-weight:700}
.ax{font-size:10px;fill:var(--muted)}.ax-day{font-weight:700;fill:var(--fg)}.ax-medio{fill:var(--mid);font-weight:700}.ax-alto{fill:var(--hi);font-weight:700}
.tick{stroke:var(--line)}.daysep{stroke:var(--muted);stroke-width:.8;stroke-dasharray:2 3;opacity:.6}.nowl{stroke:var(--fg);stroke-width:1.2;stroke-dasharray:3 2;opacity:.7}.now-t{fill:var(--fg);font-weight:700}
.legend{display:flex;flex-wrap:wrap;gap:4px 12px;font-size:.7rem;color:var(--muted);margin-top:4px}
.legend span{display:inline-flex;align-items:center;gap:5px}
.lg{width:10px;height:10px;border-radius:2px;display:inline-block}.lg-past{background:var(--ok)}.lg-fc{background:var(--ok);opacity:.45}
.lg-bajo{background:var(--ok);opacity:.35}.lg-medio{background:var(--mid);opacity:.45}.lg-alto{background:var(--hi);opacity:.45}
.win{font-size:.85rem;margin:10px 0 0;font-weight:600}.win-ok{color:var(--ok)}
.wins{list-style:none;padding:0;margin:10px 0 0;display:grid;gap:6px}
.wins li{border-radius:10px;padding:7px 10px;font-size:.86rem}.wins .w-medio{background:var(--mid-bg);color:var(--mid)}.wins .w-alto{background:var(--hi-bg);color:var(--hi)}
.seg{display:flex;gap:6px;flex-wrap:wrap;margin:10px 0}
.seg button{font:inherit;font-size:.85rem;font-weight:600;padding:8px 12px;border-radius:99px;border:1px solid var(--line);background:var(--bg);color:var(--fg);cursor:pointer}
.seg button[aria-pressed=true]{background:var(--brand);border-color:var(--brand);color:#fff}
.best{font-weight:600;margin:6px 0 10px}
.plan{list-style:none;padding:0;margin:0;display:grid;grid-template-columns:repeat(auto-fill,minmax(64px,1fr));gap:6px}
.plan li{border-radius:10px;padding:6px 4px;text-align:center;font-size:.78rem;line-height:1.2;font-variant-numeric:tabular-nums}
.plan li b{display:block;font-size:.95rem}.plan li.top{outline:2px solid var(--brand);outline-offset:1px}
table{width:100%;border-collapse:collapse}th,td{text-align:left;padding:8px 6px;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums;vertical-align:middle}
th{font-size:.68rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.pill{display:inline-block;border-radius:99px;padding:2px 9px;font-weight:700;font-size:.78rem}
.b-bajo{background:var(--ok-bg);color:var(--ok)}.b-medio{background:var(--mid-bg);color:var(--mid)}.b-alto{background:var(--hi-bg);color:var(--hi)}.b-nd{background:var(--nd-bg);color:var(--nd)}
.episodes,.method,.sponsors{list-style:none;padding:0;margin:8px 0}.episodes li,.method li,.sponsors li{padding:8px 0;border-bottom:1px solid var(--line);font-size:.88rem}
.live{color:var(--hi)}
.heatwrap{overflow-x:auto}.heat{border-collapse:separate;border-spacing:2px;min-width:420px}
.heat th{font-size:.6rem;padding:0 2px;border:0;text-transform:none}.heat td{height:16px;padding:0;border:0;border-radius:3px;background:color-mix(in srgb,var(--hi) calc(var(--a)*100%),var(--nd-bg))}
.progress{height:8px;background:var(--nd-bg);border-radius:99px;overflow:hidden;margin:12px 0 4px}.progress span{display:block;height:100%;background:linear-gradient(90deg,var(--brand),var(--brand2))}
.flota{background:linear-gradient(160deg,var(--card),var(--bg))}
.checks{padding-left:0;list-style:none;margin:10px 0}.checks li{padding:3px 0 3px 24px;position:relative;font-size:.9rem}
.checks li:before{content:"✓";position:absolute;left:4px;color:var(--ok);font-weight:800}
.actions{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}
.btn{display:inline-block;padding:10px 14px;border-radius:12px;background:var(--card);border:1px solid var(--line);color:var(--fg);text-decoration:none;font-weight:650}
.btn.primary{background:var(--brand);border-color:var(--brand);color:#fff}.btn.wa{background:#25d366;border-color:#25d366;color:#06301a}
footer{margin:24px 0 8px;font-size:.78rem;color:var(--muted)}a{color:var(--brand)}
.proto{background:#ffd23f;color:#3a2a00;text-align:center;font-size:.8rem;line-height:1.35;padding:7px 16px}
"""

JS = """
(function(){var OFF=%(offset)d*3600e3,D=['domingo','lunes','martes','miércoles','jueves','viernes','sábado'],
M=['enero','febrero','marzo','abril','mayo','junio','julio','agosto','septiembre','octubre','noviembre','diciembre'];
function p2(n){return('0'+n).slice(-2)}
var c=document.getElementById('clk'),cs=document.getElementById('clk-s'),cd=document.getElementById('clk-date');
function tick(){var t=new Date(Date.now()+OFF);c.textContent=p2(t.getUTCHours())+':'+p2(t.getUTCMinutes());cs.textContent=p2(t.getUTCSeconds());
cd.textContent=D[t.getUTCDay()]+' '+t.getUTCDate()+' de '+M[t.getUTCMonth()];
document.querySelectorAll('[data-ago]').forEach(function(e){var m=Math.max(0,Math.round((Date.now()-Date.parse(e.dataset.ago))/6e4));
e.textContent=m<60?m+' min':Math.floor(m/60)+' h '+p2(m%%60)+' min'});setTimeout(tick,1000-Date.now()%%1000)}
if(c)tick();
var el=document.getElementById('plan-data');if(!el)return;var d=JSON.parse(el.textContent);
var H=3600e3,btns=document.querySelectorAll('#planificador .seg button'),grid=document.getElementById('plan-grid'),best=document.getElementById('plan-best');
function lvl(p){for(var i=0;i<d.levels.length;i++)if(p>=d.levels[i][0])return d.levels[i][1];return'bajo'}
function hhmm(ms){var t=new Date(ms+d.offset*H);return p2(t.getUTCHours())+':'+p2(t.getUTCMinutes())}
function at(ms){var b=null,bd=1/0;d.hours.forEach(function(h){var x=Math.abs(h[0]-ms);if(x<bd){bd=x;b=h}});return bd<=H?b[1]:null}
function show(i){btns.forEach(function(b,j){b.setAttribute('aria-pressed',j===i)});var drive=d.origins[i][1]*H;
var start=Math.ceil(Date.now()/H)*H,opts=[];for(var k=0;k<24;k++){var dep=start+k*H,p=at(dep+drive);if(p!==null)opts.push([dep,p])}
if(!opts.length){best.textContent='Sin pronóstico para ese horario.';grid.innerHTML='';return}
var top=opts.reduce(function(a,b){return b[1]<a[1]-0.02?b:a});
best.innerHTML='Mejor salida desde '+d.origins[i][0]+': <b>'+hhmm(top[0])+'</b> · llegás ~'+hhmm(top[0]+drive)+' · prob. de suspensión '+Math.round(top[1]*100)+' %%';
grid.innerHTML=opts.map(function(o){return'<li class="b-'+lvl(o[1])+(o===top?' top':'')+'" title="Llegada ~'+hhmm(o[0]+drive)+'"><b>'+hhmm(o[0])+'</b>'+Math.round(o[1]*100)+' %%</li>'}).join('')}
btns.forEach(function(b,i){b.addEventListener('click',function(){show(i)})});show(0)})();
"""


# Acceso a la pantalla "Ferris en vivo" (paginas/en-vivo/, se publica en en-vivo/).
# Mini animación: una barcaza zarpa, cruza, gira y vuelve entre las dos rampas.
ENVIVO = """<a class="envivo" href="en-vivo/index.html">
  <span class="ev-mapa" aria-hidden="true">
    <span class="ev-linea"></span><span class="ev-rampa a"></span><span class="ev-rampa b"></span>
    <svg class="ev-barco" viewBox="0 0 26 66"><path d="M5.5 1.5h15l-1.2 8h-12.6z" fill="#9AA7B4"/>
      <path d="M3.2 8.5h19.6a2 2 0 0 1 2 2v49a4 4 0 0 1-4 4H5.2a4 4 0 0 1-4-4v-49a2 2 0 0 1 2-2z" fill="#F59E42" stroke="#0A1826"/>
      <rect x="3.6" y="10.4" width="18.8" height="33" rx="1" fill="#AEB9C4"/>
      <rect x="5" y="12" width="6.4" height="14" rx=".9" fill="#E9EEF3"/><rect x="14.6" y="12.6" width="6" height="8" rx="1.6" fill="#C8453F"/>
      <rect x="14.6" y="22.6" width="6" height="8" rx="1.6" fill="#3F7FC4"/>
      <rect x="4.6" y="45" width="16.8" height="13.6" rx="1.8" fill="#F3F6F9"/><rect x="6.6" y="45.6" width="12.8" height="1.5" fill="#1E2C3A"/></svg>
  </span>
  <span class="ev-txt"><span class="ev-vivo"><i></i>EN VIVO · demo</span>
    <b>Ver ferris en vivo</b>
    <small>Primera Angostura en el mapa: zarpe, giro, cruce y atraque.</small></span>
  <span class="ev-flecha" aria-hidden="true">→</span>
</a>"""

ENVIVO_CSS = """
.envivo{display:flex;align-items:center;gap:14px;margin:12px 0;padding:12px 14px;border-radius:16px;text-decoration:none;color:#EAF1F7;
background:radial-gradient(120% 160% at 0 0,#123a5e 0,#0B2C4B 45%,#0A1826 100%);border:1px solid rgba(245,158,66,.45);
box-shadow:0 0 0 1px rgba(245,158,66,.08),0 10px 30px rgba(245,158,66,.12)}
.envivo:hover{border-color:#F59E42}
.ev-mapa{position:relative;flex:none;width:118px;height:62px;border-radius:12px;overflow:hidden;
background:repeating-linear-gradient(115deg,rgba(170,212,245,.07) 0 2px,transparent 2px 11px),#0B2C4B;border:1px solid rgba(169,188,205,.18)}
.ev-linea{position:absolute;left:12px;right:12px;top:50%;border-top:1.5px dashed rgba(169,188,205,.45)}
.ev-rampa{position:absolute;top:50%;width:7px;height:7px;margin-top:-3.5px;border-radius:50%;background:#0A1826;border:1.5px solid #EAF1F7}
.ev-rampa.a{left:6px}.ev-rampa.b{right:6px}
.ev-barco{position:absolute;top:50%;width:11px;height:28px;margin-top:-14px;left:10px;filter:drop-shadow(0 1px 2px rgba(0,0,0,.6));
animation:ev-cruce 12s ease-in-out infinite}
@keyframes ev-cruce{0%,10%{left:10px;transform:rotate(90deg)}44%,52%{left:calc(100% - 21px);transform:rotate(90deg)}
58%{left:calc(100% - 21px);transform:rotate(270deg)}92%,96%{left:10px;transform:rotate(270deg)}100%{left:10px;transform:rotate(450deg)}}
.ev-txt{display:grid;gap:1px;min-width:0;flex:1}
.ev-txt b{font-size:1.05rem}.ev-txt small{font-size:.76rem;color:#A9BCCD}
.ev-vivo{display:inline-flex;align-items:center;gap:6px;font-size:.64rem;font-weight:800;letter-spacing:.1em;color:#FFC27A}
.ev-vivo i{width:7px;height:7px;border-radius:50%;background:#FF4D5E;box-shadow:0 0 0 0 rgba(255,77,94,.6);animation:ev-late 1.6s infinite}
@keyframes ev-late{70%{box-shadow:0 0 0 6px rgba(255,77,94,0)}100%{box-shadow:0 0 0 0 rgba(255,77,94,0)}}
.ev-flecha{font-size:1.3rem;color:#F59E42;flex:none}
@media (prefers-reduced-motion:reduce){.ev-barco,.ev-vivo i{animation:none}}
"""


def render(snap: Snapshot, now: datetime | None = None) -> str:
    now = now or snap.now
    stale = (f'<div class="alert">⚠️ Los datos tienen más de {config.STALE_AFTER_H} h. '
             'Pueden no reflejar la situación actual.</div>') if snap.is_stale(now) else ""
    wa = "https://wa.me/?text=" + urllib.parse.quote(summary_text(snap))
    tg = (f'<a class="btn" href="{escape(config.TELEGRAM_URL)}" rel="noopener">Avisos por Telegram</a>'
          if config.TELEGRAM_URL else "")
    weather_credit = ('<a href="https://www.met.no/" rel="noopener">MET Norway</a> (CC BY 4.0)'
                      if (snap.forecast_source or config.WEATHER_SOURCE).startswith("met")
                      else '<a href="https://open-meteo.com/" rel="noopener">Open-Meteo</a>')
    cards = "".join(_route_card(snap, r) for r in snap.routes)
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="900">
<title>Corredor Austral</title>
<meta name="description" content="¿Cruza o no cruza? Estado oficial y probabilidad de suspensión de los cruces del Estrecho de Magallanes: Primera Angostura, Punta Arenas–Porvenir y Río Verde.">
<meta name="theme-color" content="#07121c">
<meta name="color-scheme" content="dark">
<meta property="og:title" content="Corredor Austral · el semáforo del Estrecho">
<meta property="og:description" content="Estado oficial, probabilidad de suspensión por viento y la mejor hora para salir.">
<style>{CSS}{ENVIVO_CSS}</style>
</head>
<body>
<div class="proto" role="note"><b>Prototipo – versión preliminar.</b> Las predicciones son experimentales:
  confirmá siempre con TABSA antes de viajar.</div>
{_hero(snap)}
<main>
<div class="wrap">
  {stale}
  {ENVIVO}
  <div class="info"><span aria-hidden="true">ℹ️</span><div>El <b>%</b> es la <b>probabilidad de que TABSA suspenda el
  cruce</b> por viento. No mide el peligro de cruzar: si el cruce opera, es seguro.</div></div>
  {cards}
</div>
  <p class="muted small">El estado oficial lo publica <a href="{config.OFFICIAL_URL}" rel="noopener">TABSA</a>; la
  probabilidad es nuestra estimación. Ante la duda, confirmá con TABSA.</p>
  {_planner(snap)}
  {_sailings(snap)}
  {_history(snap)}
  {_method(snap)}
  {_business(snap)}
  <div class="actions">
    <a class="btn wa" href="{escape(wa)}" rel="noopener">Compartir por WhatsApp</a>
    {tg}
    <a class="btn" href="{config.OFFICIAL_URL}" rel="noopener">Estado oficial TABSA</a>
  </div>
  <footer>
    <p>Fuentes: estado de cruces de <a href="{config.OFFICIAL_URL}" rel="noopener">TABSA</a> (sitio público) ·
    clima {weather_credit}. Corredor Austral no es un canal oficial de TABSA ni del Gobierno de Tierra del Fuego.</p>
    <p>v{__version__} · generado {fmt_local(now)}</p>
  </footer>
</main>
<script>{JS % {"offset": config.LOCAL_UTC_OFFSET_H}}</script>
</body>
</html>
"""


def build_site(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "index.html"
    path.write_text(render(snapshot()), encoding="utf-8", newline="\n")
    return path
