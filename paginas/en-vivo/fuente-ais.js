// Fuente AIS REAL (preparada, TODAVÍA SIN CONECTAR).
//
// Más adelante un servidor propio recibirá los datos de aisstream.io (la clave NUNCA va
// en la web) y la página le pedirá los últimos reportes, con el mismo formato que la
// fuente simulada:
//   { mmsi, nombre, naviera, lat, lon, velocidad_nudos, rumbo, hora_utc }
//
// Los reportes AIS llegan cada varios segundos o minutos. Para que el barco no "salte",
// entre un reporte y otro se ESTIMA dónde está con su velocidad y rumbo, y cuando llega un
// reporte nuevo se corrige la posición de a poco (en ~2 s), sin teletransportarlo.

import { mover } from "./ruta.js";

const NUDO = 0.514444; // m/s

/** Dónde debería estar el barco en `ahoraMs`, avanzando desde su último reporte. */
export function estimarPosicion(reporte, ahoraMs, { maxSegundos = 180 } = {}) {
  const t = Date.parse(reporte.hora_utc);
  const seg = Math.min(Math.max((ahoraMs - t) / 1000, 0), maxSegundos); // no adivinar más de 3 min
  const v = reporte.velocidad_nudos;
  if (!v || v < 0.5 || reporte.rumbo == null || Number.isNaN(t)) return { ...reporte, estimada: false };
  const [lon, lat] = mover([reporte.lon, reporte.lat], reporte.rumbo, v * NUDO * seg);
  return { ...reporte, lon, lat, estimada: seg > 0 };
}

const suave = (f) => f * f * (3 - 2 * f);

export function crearFuenteAis({ correccionMs = 2000 } = {}) {
  const ultimos = new Map();   // mmsi -> último reporte
  const mostrados = new Map(); // mmsi -> última posición dibujada [lon, lat]
  const correcciones = new Map(); // mmsi -> { desde: [lon, lat], inicio: ms }

  return {
    simulada: false,
    /** Cargar reportes nuevos (por ejemplo, lo que devuelva el servidor propio). */
    agregarReportes(reportes, ahoraMs = Date.now()) {
      for (const r of reportes) {
        const previo = ultimos.get(r.mmsi);
        if (previo && Date.parse(previo.hora_utc) >= Date.parse(r.hora_utc)) continue;
        ultimos.set(r.mmsi, r);
        const visto = mostrados.get(r.mmsi);
        if (visto) correcciones.set(r.mmsi, { desde: visto, inicio: ahoraMs });
      }
    },
    leer(ahoraMs = Date.now()) {
      const out = [];
      for (const r of ultimos.values()) {
        const est = estimarPosicion(r, ahoraMs);
        const c = correcciones.get(r.mmsi);
        if (c) {
          const f = Math.min(1, (ahoraMs - c.inicio) / correccionMs);
          const k = suave(f);
          est.lon = c.desde[0] + (est.lon - c.desde[0]) * k;
          est.lat = c.desde[1] + (est.lat - c.desde[1]) * k;
          if (f >= 1) correcciones.delete(r.mmsi);
        }
        mostrados.set(r.mmsi, [est.lon, est.lat]);
        out.push(est);
      }
      return out;
    },
  };
}
