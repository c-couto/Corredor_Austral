/* Corredor Austral · demo web
 *
 * Lee los CSV EN VIVO desde el repositorio público en GitHub (no se copian al sitio).
 * Para no descargar archivos enteros que crecen todos los días, pide solo el final de
 * cada CSV (HTTP Range); si el servidor no lo permite, descarga el archivo completo.
 *
 * Todo lo que viene de los datos se muestra como texto (textContent), nunca como HTML.
 */
(function () {
  "use strict";

  var RAW = "https://raw.githubusercontent.com/c-couto/Corredor_Austral/main/data/auto/";
  // Solo para probar en la PC: ?datos=http://localhost:8000/data/auto/ (únicamente desde localhost).
  var params = new URLSearchParams(location.search);
  var local = location.hostname === "localhost" || location.hostname === "127.0.0.1";
  var override = params.get("datos");
  if (local && override && /^http:\/\/(localhost|127\.0\.0\.1)(:\d+)?\//.test(override)) RAW = override;

  var OFFSET_H = -3;                 // Magallanes y Tierra del Fuego: UTC-3 todo el año
  var HOUR = 3600e3;
  var STALE_H = 2;                   // datos más viejos que esto: se avisa
  var LIMITS = { medio: 50, alto: 70 }; // umbrales PROVISORIOS de ráfaga (km/h)
  var PLACES = { punta_delgada: "Punta Delgada", bahia_azul: "Bahía Azul" };
  var CROSSINGS = { primera_angostura: "Primera Angostura", rio_verde: "Río Verde" };
  var DIAS = ["domingo", "lunes", "martes", "miércoles", "jueves", "viernes", "sábado"];
  var DIAS_C = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"];
  var MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
    "octubre", "noviembre", "diciembre"];
  var CARD = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"];

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function p2(n) { return ("0" + n).slice(-2); }
  function local_(ms) { return new Date(ms + OFFSET_H * HOUR); } // usar con getUTC*
  function hhmm(ms) { var t = local_(ms); return p2(t.getUTCHours()) + ":" + p2(t.getUTCMinutes()); }
  function num(v) { var n = parseFloat(v); return isFinite(n) ? n : null; }
  function ago(ms) {
    var m = Math.max(0, Math.round((Date.now() - ms) / 6e4));
    return m < 60 ? "hace " + m + " min" : "hace " + Math.floor(m / 60) + " h " + p2(m % 60) + " min";
  }

  /* ------------------------------------------------------------ reloj */
  function tick() {
    var t = local_(Date.now());
    $("clk").textContent = p2(t.getUTCHours()) + ":" + p2(t.getUTCMinutes()) + ":" + p2(t.getUTCSeconds());
    $("clk-date").textContent = DIAS[t.getUTCDay()] + " " + t.getUTCDate() + " de " + MESES[t.getUTCMonth()];
    setTimeout(tick, 1000 - (Date.now() % 1000));
  }
  tick();

  /* ------------------------------------------------------------ CSV */
  function parseLine(line) {
    var out = [], cur = "", q = false;
    for (var i = 0; i < line.length; i++) {
      var c = line[i];
      if (q) {
        if (c === '"' && line[i + 1] === '"') { cur += '"'; i++; }
        else if (c === '"') q = false;
        else cur += c;
      } else if (c === '"') q = true;
      else if (c === ",") { out.push(cur); cur = ""; }
      else cur += c;
    }
    out.push(cur);
    return out;
  }
  function toRows(header, lines) {
    var cols = parseLine(header), rows = [];
    lines.forEach(function (l) {
      if (!l) return;
      var v = parseLine(l), r = {};
      if (v.length !== cols.length) return; // línea cortada o rota: se ignora
      cols.forEach(function (c, i) { r[c] = v[i]; });
      rows.push(r);
    });
    return rows;
  }
  function fetchText(url, range) {
    var opts = { cache: "no-store" };
    if (range) opts.headers = { Range: range };
    return fetch(url, opts).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.text().then(function (t) { return { text: t, partial: r.status === 206 }; });
    });
  }
  // Últimos ~`bytes` del CSV, ya convertidos en filas.
  function fetchTail(name, bytes) {
    var url = RAW + name;
    return fetch(url, { method: "HEAD", cache: "no-store" }).then(function (h) {
      if (!h.ok) throw new Error("HTTP " + h.status);
      var size = parseInt(h.headers.get("Content-Length"), 10);
      if (!size || size <= bytes) return fetchText(url).then(function (r) { return r.text; });
      return Promise.all([fetchText(url, "bytes=0-1023"), fetchText(url, "bytes=" + (size - bytes) + "-")])
        .then(function (res) {
          if (!res[0].partial || !res[1].partial) return res[1].text; // sin Range: llegó completo
          var header = res[0].text.split("\n")[0];
          var body = res[1].text.split("\n").slice(1);             // la 1.ª línea viene cortada
          return header + "\n" + body.join("\n");
        });
    }).then(function (text) {
      var lines = text.replace(/\r/g, "").split("\n");
      return toRows(lines[0], lines.slice(1));
    });
  }

  /* ------------------------------------------------------------ niveles */
  function nivel(g) {
    if (g == null) return "nd";
    return g >= LIMITS.alto ? "alto" : g >= LIMITS.medio ? "medio" : "bajo";
  }
  var TEXTO = {
    bajo: "Viento normal para el cruce",
    medio: "Viento fuerte: puede haber suspensiones",
    alto: "Viento muy fuerte: suspensión probable",
    nd: "Sin datos de viento"
  };
  function estadoClase(s) { return !s ? "e-nd" : s.trim().toUpperCase() === "NORMAL" ? "e-ok" : "e-bad"; }

  /* ------------------------------------------------------------ avisos */
  var problemas = [];
  function aviso(msg) {
    if (problemas.indexOf(msg) !== -1) return;
    problemas.push(msg);
    var a = $("aviso");
    a.textContent = problemas.join(" ");
    a.hidden = false;
  }

  /* ------------------------------------------------------------ estado TABSA */
  function pintarEstado(rows) {
    var ul = $("cruces");
    ul.textContent = "";
    if (!rows.length) { ul.appendChild(el("li", "muted", "Todavía no hay lecturas de TABSA.")); return; }
    var last = rows[rows.length - 1].ts_utc, ms = Date.parse(last);
    $("estado-hora").textContent = "leído " + ago(ms) + " (" + hhmm(ms) + ")";
    rows.filter(function (r) { return r.ts_utc === last; }).forEach(function (r) {
      var li = el("li");
      li.appendChild(el("span", null, CROSSINGS[r.crossing] || r.crossing));
      li.appendChild(el("span", "estado " + estadoClase(r.status), r.status || "sin dato"));
      ul.appendChild(li);
    });
    if (Date.now() - ms > STALE_H * HOUR) aviso("El último estado de TABSA es de " + ago(ms) + ": puede no estar al día.");
  }

  function pintarZarpes(rows) {
    var tb = $("zarpes");
    tb.textContent = "";
    if (!rows.length) { tb.appendChild(fila(["Sin zarpes programados en la última lectura."], 3)); return; }
    var last = rows[rows.length - 1].ts_utc;
    var ruta = { "Punta Arenas": 1, "Porvenir": 1 };  // TABSA también publica otras rutas (Natales, Williams...)
    var proximos = rows.filter(function (r) { return r.ts_utc === last; }).filter(function (r) {
      if (!ruta[r.origin] || !ruta[r.destination]) return false;
      var dep = Date.parse(r.date + "T" + r.departure + ":00-03:00");
      return dep >= Date.now() - HOUR;
    });
    if (!proximos.length) { tb.appendChild(fila(["No hay más zarpes programados por ahora."], 3)); return; }
    proximos.slice(0, 6).forEach(function (r) {
      var tr = el("tr"), td = el("td");
      td.appendChild(el("b", null, r.departure));
      td.appendChild(el("br"));
      td.appendChild(el("span", "muted small", r.date.slice(8, 10) + "/" + r.date.slice(5, 7)));
      tr.appendChild(td);
      tr.appendChild(el("td", null, r.origin + " → " + r.destination));
      var te = el("td");
      te.appendChild(el("span", "estado " + estadoClase(r.status), r.status || "sin dato"));
      tr.appendChild(te);
      tb.appendChild(tr);
    });
  }
  function fila(textos, span) {
    var tr = el("tr"), td = el("td", "muted", textos[0]);
    td.colSpan = span;
    tr.appendChild(td);
    return tr;
  }

  /* ------------------------------------------------------------ viento */
  function pintarViento(rows) {
    var cont = $("lugares");
    cont.textContent = "";
    var ultimos = {};
    rows.forEach(function (r) { if (PLACES[r.place]) ultimos[r.place] = r; });
    var hora = null;
    Object.keys(PLACES).forEach(function (p) {
      var r = ultimos[p], g = r ? num(r.gust_kmh) : null, w = r ? num(r.wind_kmh) : null;
      var d = r ? num(r.wind_dir_deg) : null, n = nivel(g);
      if (r) hora = Math.max(hora || 0, Date.parse(r.ts_utc));
      var box = el("article", "lugar n-" + n);
      box.appendChild(el("h3", null, PLACES[p]));
      var dl = el("dl", "datos");
      dl.appendChild(dato("Ráfaga", g, "km/h"));
      dl.appendChild(dato("Viento", w, "km/h"));
      var dir = el("div");
      dir.appendChild(el("dt", null, "Desde"));
      var dd = el("dd");
      if (d != null) dd.appendChild(flecha(d));
      dd.appendChild(el("small", null, d == null ? "–" : CARD[Math.round(d / 45) % 8]));
      dir.appendChild(dd);
      dl.appendChild(dir);
      box.appendChild(dl);
      box.appendChild(el("p", "indicador i-" + n, TEXTO[n]));
      cont.appendChild(box);
    });
    $("viento-hora").textContent = hora ? ago(hora) + " (" + hhmm(hora) + ")" : "sin datos";
    if (hora && Date.now() - hora > STALE_H * HOUR) aviso("El último dato de viento es de " + ago(hora) + ".");
  }
  function dato(nombre, v, unidad) {
    var d = el("div");
    d.appendChild(el("dt", null, nombre));
    var dd = el("dd", null, v == null ? "–" : String(Math.round(v)));
    dd.appendChild(el("small", null, " " + unidad));
    d.appendChild(dd);
    return d;
  }
  function flecha(deg) { // apunta hacia donde VA el viento
    var NS = "http://www.w3.org/2000/svg", s = document.createElementNS(NS, "svg"), path = document.createElementNS(NS, "path");
    s.setAttribute("viewBox", "0 0 24 24");
    s.setAttribute("class", "flecha");
    s.setAttribute("aria-hidden", "true");
    s.style.transform = "rotate(" + ((deg + 180) % 360) + "deg)";
    path.setAttribute("d", "M12 3l5 9h-3.5v9h-3v-9H7z");
    s.appendChild(path);
    return s;
  }

  /* ------------------------------------------------------------ gráfico 72 h */
  function pintarGrafico(rows, estados) {
    var cont = $("chart");
    cont.textContent = "";
    var fin = Date.now(), ini = fin - 72 * HOUR;
    var series = { punta_delgada: [], bahia_azul: [] };
    rows.forEach(function (r) {
      var t = Date.parse(r.ts_utc), g = num(r.gust_kmh);
      if (series[r.place] && t >= ini && g != null) series[r.place].push([t, g]);
    });
    var todos = series.punta_delgada.concat(series.bahia_azul);
    if (!todos.length) { cont.appendChild(el("p", "muted small", "Todavía no hay datos de las últimas 72 horas.")); return; }

    var W = 360, H = 180, L = 30, R = 6, T = 10, B = 24, pw = W - L - R, ph = H - T - B;
    var top = Math.ceil(Math.max(100, Math.max.apply(null, todos.map(function (p) { return p[1]; })) * 1.1) / 20) * 20;
    function x(t) { return L + (t - ini) / (fin - ini) * pw; }
    function y(g) { return T + ph - Math.min(g, top) / top * ph; }
    var NS = "http://www.w3.org/2000/svg", svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    svg.setAttribute("role", "img");
    svg.setAttribute("aria-label", "Ráfagas en Punta Delgada y Bahía Azul durante las últimas 72 horas, en km/h");
    function add(tag, attrs, text) {
      var e = document.createElementNS(NS, tag);
      Object.keys(attrs).forEach(function (k) { e.setAttribute(k, attrs[k]); });
      if (text != null) e.textContent = text;
      svg.appendChild(e);
      return e;
    }
    // Zonas y umbrales provisorios.
    add("rect", { "class": "z-medio", x: L, y: y(LIMITS.alto), width: pw, height: y(LIMITS.medio) - y(LIMITS.alto) });
    add("rect", { "class": "z-alto", x: L, y: y(top), width: pw, height: y(LIMITS.alto) - y(top) });
    [["medio", LIMITS.medio], ["alto", LIMITS.alto]].forEach(function (u) {
      add("line", { "class": "umbral u-" + u[0], x1: L, x2: W - R, y1: y(u[1]), y2: y(u[1]) });
      add("text", { "class": "eje", x: L - 4, y: y(u[1]) + 3, "text-anchor": "end" }, String(u[1]));
    });
    add("text", { "class": "eje", x: L - 4, y: y(0) + 3, "text-anchor": "end" }, "0");
    add("text", { "class": "eje", x: L - 4, y: y(top) + 8, "text-anchor": "end" }, String(top));
    add("text", { "class": "eje", x: L + 3, y: T + 9 }, "km/h");
    // Períodos en que TABSA mostró Primera Angostura no normal.
    var desde = null;
    estados.filter(function (r) { return r.crossing === "primera_angostura"; }).forEach(function (r) {
      var t = Date.parse(r.ts_utc), mal = r.status.trim().toUpperCase() !== "NORMAL";
      if (mal && desde === null) desde = t;
      if (!mal && desde !== null) { banda(desde, t); desde = null; }
    });
    if (desde !== null) banda(desde, fin);
    function banda(a, b) {
      a = Math.max(a, ini); if (b <= a) return;
      add("rect", { "class": "susp", x: x(a), y: T, width: Math.max(2, x(b) - x(a)), height: ph });
    }
    // Marcas de tiempo: medianoche (día) y mediodía, hora local.
    for (var t = Math.ceil(ini / HOUR) * HOUR; t <= fin; t += HOUR) {
      var h = local_(t).getUTCHours();
      if (h !== 0 && h !== 12) continue;
      add("line", { "class": "grilla", x1: x(t), x2: x(t), y1: T, y2: T + ph });
      add("text", { "class": "eje" + (h === 0 ? " eje-dia" : ""), x: x(t), y: H - 8, "text-anchor": "middle" },
        h === 0 ? DIAS_C[local_(t).getUTCDay()] : "12 h");
    }
    // Series (se corta la línea si faltan más de 2 h de datos).
    [["punta_delgada", "s-pd"], ["bahia_azul", "s-ba"]].forEach(function (s) {
      var pts = series[s[0]].sort(function (a, b) { return a[0] - b[0]; }), d = "", prev = null;
      pts.forEach(function (p) {
        d += (prev === null || p[0] - prev > 2 * HOUR ? "M" : "L") + x(p[0]).toFixed(1) + " " + y(p[1]).toFixed(1);
        prev = p[0];
      });
      if (d) add("path", { "class": "serie " + s[1], d: d });
    });
    cont.appendChild(svg);
  }

  /* ------------------------------------------------------------ carga */
  var estadoP = fetchTail("tabsa_estado.csv", 40000);
  var zarpesP = fetchTail("tabsa_programados.csv", 30000);
  var climaP = fetchTail("weather_obs.csv", 260000); // ~72 h de 8 lugares

  estadoP.then(pintarEstado, function () {
    $("cruces").textContent = "";
    $("cruces").appendChild(el("li", "muted", "No pudimos cargar el estado de TABSA."));
    $("estado-hora").textContent = "sin conexión con los datos";
    aviso("No pudimos cargar algunos datos en este momento. Probá recargar en unos minutos.");
  });
  zarpesP.then(pintarZarpes, function () {
    $("zarpes").textContent = "";
    $("zarpes").appendChild(fila(["No pudimos cargar los zarpes."], 3));
  });
  climaP.then(pintarViento, function () {
    $("viento-hora").textContent = "sin conexión con los datos";
    aviso("No pudimos cargar algunos datos en este momento. Probá recargar en unos minutos.");
  });
  Promise.all([climaP, estadoP.catch(function () { return []; })]).then(function (r) {
    pintarGrafico(r[0], r[1]);
  }, function () {
    $("chart").textContent = "";
    $("chart").appendChild(el("p", "muted small", "No pudimos cargar el gráfico."));
  });
})();
