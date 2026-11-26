// Cómo se mueve una barcaza de rampa entre dos orillas (lo usan la simulación y el horario real).
//   llega con la PROA a la rampa → embarca → al zarpar RETROCEDE, GIRA 180° y navega.
// No sabe de horarios: recibe un zarpe { sale, llega, desde: "inicio" | "fin" } en ms UTC.

import { rumbo as rumboEntre, mover } from "./ruta.js";

export const NUDO = 0.514444; // m/s
const RETROCESO_DEF_M = 55;   // cuánto se aleja de la rampa marcha atrás antes de girar
const RETRO_DEF_S = 60;       // 1 min de marcha atrás
const GIRO_DEF_S = 60;        // 1 min de giro de 180°
const ACEL = 0.12;            // fracción del tramo navegando que usa para acelerar / frenar
const LATERAL_DEF_M = 70;     // al cruzarse, cada uno se corre a su estribor

const suave = (x) => x * x * (3 - 2 * x);

function avance(u) {
  // Recorrido 0..1 con aceleración y frenado suaves; devuelve [posición, velocidad relativa].
  const vmax = 1 / (1 - ACEL);
  if (u < ACEL) return [(vmax * u * u) / (2 * ACEL), (vmax * u) / ACEL];
  if (u > 1 - ACEL) return [1 - (vmax * (1 - u) ** 2) / (2 * ACEL), (vmax * (1 - u)) / ACEL];
  return [vmax * (u - ACEL / 2), vmax];
}

/**
 * @param maniobra  valores propios del cruce (por defecto los de Primera Angostura):
 *   { retroceso_m, retro_s, giro_s, lateral_m }. En un cruce corto (Río Verde, ~5 min)
 *   la marcha atrás y el giro tienen que ser más cortos para que entren en el viaje.
 */
export function crearMovimiento(ruta, maniobra = {}) {
  const L = ruta.largo;
  const RETROCESO_M = maniobra.retroceso_m ?? RETROCESO_DEF_M;
  const RETRO_S = maniobra.retro_s ?? RETRO_DEF_S;
  const GIRO_S = maniobra.giro_s ?? GIRO_DEF_S;
  const CRUCE_LATERAL_M = maniobra.lateral_m ?? LATERAL_DEF_M;
  // "A la derecha" de la dirección inicio → fin; atraque_m corre el muelle a lo largo de la costa.
  const puntoRuta = (d, lateral) => mover(ruta.punto(d), ruta.rumbo(d) + 90, lateral);
  const proaEnRampa = (lado) => (lado === "fin" ? ruta.rumbo(L) : (ruta.rumbo(0) + 180) % 360);

  /** Barco atracado en una rampa, con la proa hacia ella. */
  function enRampa(barco, lado, extra = {}) {
    const d = lado === "fin" ? L : 0;
    return { punto: puntoRuta(d, barco.atraque_m || 0), rumbo: proaEnRampa(lado), nudos: 0, ...extra };
  }

  /** Barco navegando en el zarpe `z` en el momento `t` (sale ≤ t < llega). */
  function navegando(barco, z, t) {
    const haciaFin = z.desde === "inicio";
    const durS = (z.llega - z.sale) / 1000;
    const seg = (t - z.sale) / 1000;
    const aD = (dO) => (haciaFin ? dO : L - dO);                     // distancia desde el origen → desde "inicio"
    const sentido = (dO) => (haciaFin ? ruta.rumbo(aD(dO)) : (ruta.rumbo(aD(dO)) + 180) % 360);
    const atraque = barco.atraque_m || 0;
    const lateral = (s) => atraque + (haciaFin ? 1 : -1) * CRUCE_LATERAL_M * Math.sin(Math.PI * s);
    const proaRampa = (sentido(0) + 180) % 360; // llegó con la proa hacia esta rampa

    if (seg < RETRO_S) { // marcha atrás: se aleja de la rampa con la proa todavía hacia ella
      const k = seg / RETRO_S;
      const dO = RETROCESO_M * suave(k);
      const v = (RETROCESO_M * 6 * k * (1 - k)) / RETRO_S;
      return { punto: puntoRuta(aD(dO), lateral(0)), rumbo: proaRampa, curso: sentido(dO), nudos: v / NUDO };
    }
    if (seg < RETRO_S + GIRO_S) { // giro de 180° por estribor
      const k = suave((seg - RETRO_S) / GIRO_S);
      return { punto: puntoRuta(aD(RETROCESO_M), lateral(0)), rumbo: (proaRampa + 180 * k) % 360,
        curso: sentido(RETROCESO_M), nudos: 1.2 };
    }
    const tramoS = durS - RETRO_S - GIRO_S;
    const w = (seg - RETRO_S - GIRO_S) / tramoS;
    const pos = (ww) => {
      const [s] = avance(Math.min(Math.max(ww, 0), 1));
      return puntoRuta(aD(RETROCESO_M + s * (L - RETROCESO_M)), lateral(s));
    };
    const [, vrel] = avance(w);
    const v = (vrel * (L - RETROCESO_M)) / tramoS;
    const paso = Math.min(0.004, 20 / tramoS); // ~20 s antes y después, para el rumbo
    const rumbo = rumboEntre(pos(w - paso), pos(w + paso));
    return { punto: pos(w), rumbo, curso: rumbo, nudos: v / NUDO };
  }

  return { enRampa, navegando };
}

/** Pasa un estado interno al formato común { mmsi, nombre, naviera, lat, lon, velocidad_nudos, rumbo, hora_utc, ... }. */
export function registro(barco, e, t) {
  const r = {
    mmsi: barco.mmsi,
    nombre: barco.nombre,
    naviera: barco.naviera,
    ...(barco.color ? { color: barco.color, rgb: barco.rgb } : {}), // color propio del ferry
    lat: e.punto[1],
    lon: e.punto[0],
    velocidad_nudos: Math.round(e.nudos * 10) / 10,
    rumbo: Math.round(e.rumbo * 10) / 10,
    hora_utc: new Date(Math.floor(t / 10000) * 10000).toISOString(), // "reportan" cada 10 s
  };
  if (e.curso != null) r.curso = Math.round(e.curso * 10) / 10;
  if (e.sale) r.sale_utc = new Date(e.sale).toISOString();
  if (e.llega) r.llega_utc = new Date(e.llega).toISOString();
  if (e.suspendido) r.suspendido = true;
  if (e.estado_zarpe) r.estado_zarpe = e.estado_zarpe; // la palabra de TABSA: SUSPENDIDO, CANCELADO...
  return r;
}
