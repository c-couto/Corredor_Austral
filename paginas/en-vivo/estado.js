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

/** { desde_deg, kmh, ts } del viento en Punta Delgada, o null. */
export async function vientoPuntaDelgada() {
  try {
    const filas = (await ultimasFilas("weather_obs.csv", 12000)).filter((f) => f.place === "punta_delgada");
    const f = filas[filas.length - 1];
    if (!f || f.wind_dir_deg === "") return null;
    return { desde_deg: Number(f.wind_dir_deg), kmh: Number(f.wind_kmh), ts: Date.parse(f.ts_utc) };
  } catch {
    return null;
  }
}
