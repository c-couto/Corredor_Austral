// Estado oficial de TABSA y viento en Punta Delgada, leídos EN VIVO de los CSV que el
// proyecto ya guarda en GitHub (repo público). Solo baja el final de cada archivo.
// Si falla (sin señal, GitHub caído), devuelve null y la página usa un valor de ejemplo.

const BASE = "https://raw.githubusercontent.com/c-couto/Corredor_Austral/main/data/auto/";

function filaCsv(linea) {
  const out = [];
  let campo = "", comillas = false;
  for (let i = 0; i < linea.length; i++) {
    const c = linea[i];
    if (comillas) {
      if (c === '"' && linea[i + 1] === '"') { campo += '"'; i++; }
      else if (c === '"') comillas = false;
      else campo += c;
    } else if (c === '"') comillas = true;
    else if (c === ",") { out.push(campo); campo = ""; }
    else campo += c;
  }
  out.push(campo);
  return out;
}

async function ultimasFilas(archivo, bytes = 8000) {
  const url = BASE + archivo;
  const cabecera = await fetch(url, { headers: { Range: "bytes=0-511" }, cache: "no-store" });
  const columnas = filaCsv((await cabecera.text()).split("\n")[0].trim());
  const h = await fetch(url, { method: "HEAD", cache: "no-store" });
  const largo = Number(h.headers.get("content-length")) || 0;
  const opts = { cache: "no-store" };
  if (largo > bytes) opts.headers = { Range: `bytes=${largo - bytes}-` };
  const res = await fetch(url, opts);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  let lineas = (await res.text()).split("\n").filter((l) => l.trim());
  if (opts.headers && res.status === 206) lineas = lineas.slice(1); // la primera puede venir cortada
  else lineas = lineas.slice(1); // sin Range: la primera es el encabezado
  return lineas.map((l) => Object.fromEntries(filaCsv(l.trim()).map((v, i) => [columnas[i], v])));
}

/** { status, ts } del cruce, o null. */
export async function estadoTabsa(cruce = "primera_angostura") {
  try {
    const filas = (await ultimasFilas("tabsa_estado.csv")).filter((f) => f.crossing === cruce);
    const f = filas[filas.length - 1];
    return f && f.status ? { status: f.status.trim(), ts: Date.parse(f.ts_utc) } : null;
  } catch {
    return null;
  }
}

const puerto = (s) => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/\s+/g, " ").trim();

/**
 * Zarpes publicados por TABSA para un cruce con horario (p. ej. Punta Arenas – Porvenir).
 * Cada zarpe una sola vez, con el ÚLTIMO estado que publicó TABSA.
 * @returns {{ zarpes: {sale, llega, desde, estado, origen, destino}[], leido: number } | null}
 */
export async function zarpesTabsa(ruta, duracionMin, offsetH = -3) {
  try {
    const ini = puerto(ruta.inicio.nombre), fin = puerto(ruta.fin.nombre);
    const filas = await ultimasFilas("tabsa_programados.csv", 60000);
    const por = new Map();
    let leido = 0;
    for (const f of filas) {
      const o = puerto(f.origin), d = puerto(f.destination);
      if (!((o === ini && d === fin) || (o === fin && d === ini))) continue; // otras rutas de TABSA
      const m = /^(\d{4})-(\d\d)-(\d\d)$/.exec(f.date || "");
      const h = /^(\d{1,2}):(\d\d)$/.exec(f.departure || "");
      if (!m || !h) continue;
      const sale = Date.UTC(+m[1], +m[2] - 1, +m[3], +h[1], +h[2]) - offsetH * 3600000;
      por.set(`${f.date} ${f.departure} ${o}`, {
        sale, llega: sale + duracionMin * 60000, desde: o === ini ? "inicio" : "fin",
        estado: (f.status || "").trim(), origen: f.origin, destino: f.destination,
      });
      leido = Math.max(leido, Date.parse(f.ts_utc) || 0);
    }
    return { zarpes: [...por.values()].sort((a, b) => a.sale - b.sale), leido };
  } catch {
    return null;
  }
}

/** { desde_deg, kmh, ts } del último viento medido en un lugar (por defecto Punta Delgada), o null. */
export async function vientoPuntaDelgada(lugar = "punta_delgada") {
  try {
    const filas = (await ultimasFilas("weather_obs.csv", 12000)).filter((f) => f.place === lugar);
    const f = filas[filas.length - 1];
    if (!f || f.wind_dir_deg === "") return null;
    return { desde_deg: Number(f.wind_dir_deg), kmh: Number(f.wind_kmh), ts: Date.parse(f.ts_utc) };
  } catch {
    return null;
  }
}
