"""Genera la web estática: un solo index.html, sin librerías externas.

"El semáforo del Estrecho": estado oficial + probabilidad de suspensión por cruce,
pronóstico hora por hora, planificador "¿A qué hora salgo?", próximas salidas a
Porvenir, historial y espacios comerciales (Plan Flota, "Dónde esperar").

Pensada para el celular y para señal mala en ruta: un archivo de pocos KB.
"""

from __future__ import annotations

import json
import urllib.parse
from datetime import datetime
from html import escape
from pathlib import Path

from . import __version__, config, model
from .conditions import (RouteStatus, Snapshot, fmt_duration, is_normal, pct, snapshot,
                         summary_text)
from .timeutil import fmt_local, to_local

LEVEL_LABEL = {"bajo": "Riesgo bajo", "medio": "Riesgo medio", "alto": "Riesgo alto", None: "Sin datos"}
WEEKDAYS = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")
CARDINALS = ("N", "NE", "E", "SE", "S", "SO", "O", "NO")


def _n(value: float | None, unit: str = "") -> str:
    return "–" if value is None else f"{value:.0f}{unit}"


def _cardinal(deg: float | None) -> str:
    return "" if deg is None else CARDINALS[round(deg / 45) % 8]


def _lvl(p: float | None) -> str:
    return model.level_for_prob(p) or "nd"


# ------------------------------------------------------------------ piezas

def _gauge(st: RouteStatus) -> str:
    p = st.p_now
    deg = 0 if p is None else round(p * 360)
    return (f'<div class="gauge g-{_lvl(p)}" style="--deg:{deg}deg" role="img" '
            f'aria-label="Probabilidad de suspensión {pct(p)}">'
            f'<div class="gauge-in"><b>{"–" if p is None else round(p * 100)}<small>%</small></b>'
            f'<span>riesgo</span></div></div>')


def _official(snap: Snapshot, st: RouteStatus) -> str:
    status, text = snap.official_for(st)
    if config.ROUTES[st.key].get("scheduled") and status:
        nxt = snap.next_sailing()
        text = f"Próx. {nxt.departure}: {status}" if nxt else text
    cls = "nd" if status is None else ("ok" if is_normal(status) else "bad")
    return f'<span class="off off-{cls}"><i></i>{escape(text)}</span>'


def _timeline(st: RouteStatus) -> str:
    if not st.hours:
        return '<p class="muted small">Pronóstico horario no disponible.</p>'
    bars = []
    for i, h in enumerate(st.hours[:48]):
        local = to_local(h.t)
        tick = f'<em>{local:%H}h</em>' if local.hour % 6 == 0 else ""
        day = ' class="day"' if local.hour == 0 and i else ""
        bars.append(
            f'<li{day} title="{WEEKDAYS[local.weekday()]} {local:%H:%M} · ráfagas {_n(h.gust)} km/h · {pct(h.p)}">'
            f'<span class="bar b-{_lvl(h.p)}" style="height:{max(12, round(h.p ** 0.6 * 100))}%"></span>{tick}</li>')
    pk = st.peak()
    peak = (f'<p class="small">Pico próximas 24 h: <b>{pct(pk.p)}</b> a las {fmt_local(pk.t, "%H:%M")}'
            f' · ráfagas {_n(pk.gust)} km/h</p>') if pk else ""
    return f'<ol class="timeline" aria-label="Riesgo hora por hora, próximas 48 h">{"".join(bars)}</ol>{peak}'


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


def _route_card(snap: Snapshot, st: RouteStatus) -> str:
    return f"""
<article class="card route lvl-{_lvl(st.p_now)}">
  <header>
    <div><h2>{escape(st.name)}</h2><p class="muted small">{escape(st.detail)}</p>{_official(snap, st)}</div>
    {_gauge(st)}
  </header>
  {_wind(st)}
  {_timeline(st)}
</article>"""


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
  <p class="muted small">Elegí desde dónde salís: calculamos el riesgo en {escape(st.name)} a la hora en que llegarías.</p>
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
  <h2>Próximas salidas Punta Arenas ↔ Porvenir</h2>
  <table><thead><tr><th>Zarpe</th><th>Sentido</th><th>TABSA</th><th>Riesgo</th></tr></thead>
  <tbody>{"".join(rows)}</tbody></table>
  <p class="muted small">Estado según TABSA. Riesgo: estimación por viento a la hora de zarpe.</p>
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
                             f'{"sin datos" if share is None else f"{round(share * 100)} % no normal ({n} lecturas)"}"></td>')
            body.append(f"<tr><th>{name}</th>{''.join(cells)}</tr>")
        heat = (f'<h3>¿Cuándo se suspende? Primera Angostura</h3><div class="heatwrap"><table class="heat">'
                f'<thead><tr><th></th>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'
                f'<p class="muted small">Más oscuro = más lecturas no normales en ese día y hora (hora local).</p>')
    else:
        heat = (f'<div class="progress"><span style="width:{min(100, round(snap.tabsa_days / 7 * 100))}%"></span></div>'
                f'<p class="muted small">Construyendo el historial que TABSA no guarda: {snap.tabsa_days} de 7 días '
                f'({snap.tabsa_samples} lecturas). Con una semana aparece el mapa de días y horas.</p>')
    return f"""
<section class="card">
  <h2>Historial</h2>
  {episodes}
  {heat}
</section>"""


def _method(snap: Snapshot) -> str:
    rows = []
    for st in snap.routes:
        m = st.model
        tag = '<span class="pill b-bajo">aprendido</span>' if m.kind == "trained" else '<span class="pill b-nd">regla base</span>'
        extra = ""
        if m.metrics.get("auc_modelo") is not None:
            extra = f' · acierta el orden en el {round(m.metrics["auc_modelo"] * 100)} % de los casos'
        rows.append(f"<li><b>{escape(st.name)}</b> {tag}<br><span class='muted small'>{escape(m.reason)}{extra}</span></li>")
    limits = " · ".join(f"{name}: desde {round(lim * 100)} %" for lim, name in sorted(config.RISK_LEVELS))
    return f"""
<section class="card">
  <h2>Cómo calculamos el riesgo</h2>
  <p class="small">Cada media hora guardamos el viento y el estado oficial de TABSA. Con ese historial, un modelo
  aprende <b>con cuánto viento se suspende cada cruce</b> y estima la probabilidad para las próximas horas.
  Se reentrena todos los días y solo reemplaza a la regla base si demuestra predecir mejor.</p>
  <ul class="method">{"".join(rows)}</ul>
  <p class="muted small">Niveles: bajo · {limits}.</p>
</section>"""


def _business(snap: Snapshot) -> str:
    high = any(model.level_for_prob(r.p_now) == "alto" or (r.official_fresh and is_normal(r.official) is False)
               for r in snap.routes)
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
--ok:#14915a;--ok-bg:#d9f6e7;--mid:#b86e00;--mid-bg:#ffefcf;--hi:#d62839;--hi-bg:#ffe1e3;--nd:#7b8794;--nd-bg:#e8edf2;
--shadow:0 1px 2px rgba(15,29,43,.06),0 8px 24px rgba(15,29,43,.06)}
@media (prefers-color-scheme:dark){:root{--bg:#07121c;--card:#0f1e2b;--fg:#e7eef5;--muted:#93a4b5;--line:#1f3344;
--brand:#5cc8ff;--brand2:#2fd0c6;--ok:#3ddc97;--ok-bg:#0d2c21;--mid:#f5b13d;--mid-bg:#33260b;--hi:#ff6b78;--hi-bg:#3a1418;
--nd:#8a99a8;--nd-bg:#1a2a38;--shadow:none}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;overflow-x:hidden;background:var(--bg);color:var(--fg);font:16px/1.45 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:720px;margin:0 auto;padding:0 16px 24px}
.hero{background:linear-gradient(135deg,#0b4f79,#0e7490 60%,#14a3b8);color:#fff;padding:20px 16px 56px}
.hero .in{max-width:720px;margin:0 auto}
.brand{display:flex;align-items:center;gap:10px}.brand svg{width:34px;height:34px}
h1{font-size:1.45rem;margin:0;letter-spacing:-.01em}h2{font-size:1.08rem;margin:0}h3{font-size:.95rem;margin:16px 0 6px}
.beta{font-size:.68rem;font-weight:800;letter-spacing:.06em;text-transform:uppercase;border:1px solid currentColor;border-radius:99px;padding:1px 7px;vertical-align:middle;opacity:.9}
.hero p{margin:6px 0 0;opacity:.9;font-size:.85rem}
.wrap{margin-top:-40px}
.muted{color:var(--muted)}.small{font-size:.82rem;margin:.3rem 0}
.alert{background:var(--mid-bg);color:var(--mid);border-radius:12px;padding:10px 12px;font-weight:600;margin:12px 0}
.card{background:var(--card);border:1px solid var(--line);border-radius:16px;padding:16px;margin:12px 0;box-shadow:var(--shadow)}
.card.glow{border-color:var(--mid);box-shadow:0 0 0 3px var(--mid-bg)}
.route{border-top:4px solid var(--nd)}.lvl-bajo{border-top-color:var(--ok)}.lvl-medio{border-top-color:var(--mid)}.lvl-alto{border-top-color:var(--hi)}
.route header{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.route header>div{min-width:0}
.off{display:inline-flex;align-items:center;gap:6px;font-weight:700;font-size:.8rem;margin-top:6px;border-radius:99px;padding:3px 10px}
.off i{width:9px;height:9px;border-radius:50%;background:currentColor}
.off-ok{background:var(--ok-bg);color:var(--ok)}.off-bad{background:var(--hi-bg);color:var(--hi)}.off-nd{background:var(--nd-bg);color:var(--nd)}
.off-bad i{animation:pulse 1.4s infinite}@keyframes pulse{50%{opacity:.25}}
@media (prefers-reduced-motion:reduce){.off-bad i{animation:none}}
.gauge{--c:var(--nd);width:84px;height:84px;flex:none;border-radius:50%;background:conic-gradient(var(--c) var(--deg),var(--nd-bg) 0);display:grid;place-items:center}
.g-bajo{--c:var(--ok)}.g-medio{--c:var(--mid)}.g-alto{--c:var(--hi)}
.gauge-in{width:66px;height:66px;border-radius:50%;background:var(--card);display:grid;place-items:center;align-content:center;line-height:1}
.gauge-in b{font-size:1.45rem;font-variant-numeric:tabular-nums}.gauge-in small{font-size:.7rem}.gauge-in span{font-size:.62rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.stats{display:flex;gap:18px;margin:14px 0 8px;flex-wrap:wrap}.stats div{min-width:0}
dt{font-size:.68rem;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
dd{margin:0;font-size:1.5rem;font-weight:750;font-variant-numeric:tabular-nums;display:flex;align-items:center;gap:4px}dd small{font-size:.75rem;font-weight:500;color:var(--muted)}
.arrow{width:24px;height:24px;fill:var(--brand)}
.timeline{list-style:none;margin:10px 0 2px;padding:0 0 16px;display:grid;grid-template-columns:repeat(48,minmax(0,1fr));gap:1px;height:64px;align-items:end;position:relative}
.timeline li{height:48px;display:flex;align-items:flex-end;position:relative}.timeline li.day{border-left:1px dashed var(--line)}
.timeline em{position:absolute;bottom:-16px;left:0;font-size:.62rem;font-style:normal;color:var(--muted)}
.bar{display:block;width:100%;min-height:4px;border-radius:2px 2px 1px 1px;background:var(--nd)}
.b-bajo{background:var(--ok-bg);color:var(--ok)}.b-medio{background:var(--mid-bg);color:var(--mid)}.b-alto{background:var(--hi-bg);color:var(--hi)}.b-nd{background:var(--nd-bg);color:var(--nd)}
.bar.b-bajo{background:var(--ok)}.bar.b-medio{background:var(--mid)}.bar.b-alto{background:var(--hi)}.bar.b-nd{background:var(--nd)}
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
"""

JS = """
(function(){var el=document.getElementById('plan-data');if(!el)return;var d=JSON.parse(el.textContent);
var H=3600e3,btns=document.querySelectorAll('#planificador .seg button'),grid=document.getElementById('plan-grid'),best=document.getElementById('plan-best');
function lvl(p){for(var i=0;i<d.levels.length;i++)if(p>=d.levels[i][0])return d.levels[i][1];return'bajo'}
function hhmm(ms){var t=new Date(ms+d.offset*H);return('0'+t.getUTCHours()).slice(-2)+':'+('0'+t.getUTCMinutes()).slice(-2)}
function at(ms){var b=null,bd=1/0;d.hours.forEach(function(h){var x=Math.abs(h[0]-ms);if(x<bd){bd=x;b=h}});return bd<=H?b[1]:null}
function show(i){btns.forEach(function(b,j){b.setAttribute('aria-pressed',j===i)});var drive=d.origins[i][1]*H;
var start=Math.ceil(Date.now()/H)*H,opts=[];for(var k=0;k<24;k++){var dep=start+k*H,p=at(dep+drive);if(p!==null)opts.push([dep,p])}
if(!opts.length){best.textContent='Sin pronóstico para ese horario.';grid.innerHTML='';return}
var top=opts.reduce(function(a,b){return b[1]<a[1]-0.02?b:a});
best.innerHTML='Mejor salida desde '+d.origins[i][0]+': <b>'+hhmm(top[0])+'</b> (llegás ~'+hhmm(top[0]+drive)+', riesgo '+Math.round(top[1]*100)+' %)';
grid.innerHTML=opts.map(function(o){return'<li class="b-'+lvl(o[1])+(o===top?' top':'')+'" title="Llegada ~'+hhmm(o[0]+drive)+'"><b>'+hhmm(o[0])+'</b>'+Math.round(o[1]*100)+' %</li>'}).join('')}
btns.forEach(function(b,i){b.addEventListener('click',function(){show(i)})});show(0)})();
"""

LOGO = ('<svg viewBox="0 0 40 40" aria-hidden="true"><circle cx="20" cy="20" r="19" fill="#fff" fill-opacity=".15"/>'
        '<path d="M6 24c4 0 4-3 8-3s4 3 8 3 4-3 8-3 4 3 4 3" fill="none" stroke="#fff" stroke-width="2.4" stroke-linecap="round"/>'
        '<path d="M6 30c4 0 4-3 8-3s4 3 8 3 4-3 8-3 4 3 4 3" fill="none" stroke="#fff" stroke-opacity=".6" stroke-width="2.4" stroke-linecap="round"/>'
        '<path d="M14 18l6-9 6 9z" fill="#fff"/></svg>')


def render(snap: Snapshot, now: datetime | None = None) -> str:
    now = now or snap.now
    updated = f"Actualizado {fmt_local(snap.latest)} · hora local (UTC-3)" if snap.latest else "Sin datos todavía"
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
<meta name="description" content="Estado y riesgo de los cruces del Estrecho de Magallanes: Primera Angostura, Punta Arenas–Porvenir y Río Verde.">
<meta name="theme-color" content="#0b4f79">
<meta property="og:title" content="Corredor Austral · el semáforo del Estrecho">
<meta property="og:description" content="¿Cruza o no cruza? Estado oficial, riesgo por viento y la mejor hora para salir.">
<style>{CSS}</style>
</head>
<body>
<header class="hero"><div class="in">
  <div class="brand">{LOGO}<h1>Corredor Austral <span class="beta">BETA</span></h1></div>
  <p>El semáforo del Estrecho de Magallanes · {updated}</p>
</div></header>
<main>
<div class="wrap">
  {stale}
  {cards}
</div>
  <p class="muted small">El estado oficial lo publica <a href="{config.OFFICIAL_URL}" rel="noopener">TABSA</a>; el riesgo es
  nuestra estimación. Ante la duda, confirmá con TABSA.</p>
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
    clima {weather_credit}. Corredor Austral no es un canal oficial de TABSA.</p>
    <p>v{__version__} · generado {fmt_local(now)}</p>
  </footer>
</main>
<script>{JS}</script>
</body>
</html>
"""


def build_site(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "index.html"
    path.write_text(render(snapshot()), encoding="utf-8", newline="\n")
    return path
