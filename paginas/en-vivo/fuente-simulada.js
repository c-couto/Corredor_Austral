// Fuente SIMULADA: ferris de ejemplo que cruzan Primera Angostura con un HORARIO en hora local.
// Entrega lo mismo que entregará la fuente AIS real:
//   { mmsi, nombre, naviera, lat, lon, velocidad_nudos, rumbo, hora_utc }
// más datos opcionales que AIS también tiene o que solo conoce la simulación:
//   curso      rumbo sobre el fondo (al dar marcha atrás es distinto de la proa)
//   sale_utc   próxima salida de la rampa · llega_utc  llegada prevista
//
// Cómo se mueve una barcaza de rampa (como las del cruce):
//   llega con la PROA a la rampa (baja la rampa) → embarca → al zarpar RETROCEDE,
//   GIRA 180° y recién ahí navega hacia la otra orilla.

import { rumbo as rumboEntre, mover } from "./ruta.js";

// ------------------------------------------------------------------ horario (APROXIMADO)
// TABSA no publica un horario fijo para Primera Angostura. Estos valores salen de
// OpenStreetMap (vía 49793837: duration=00:20, opening_hours=08:00-24:00) y hay que
// confirmarlos con TABSA o calibrarlos con los datos AIS reales.
export const HORARIO = {
  utc_offset_h: -3,     // Magallanes y Tierra del Fuego: UTC-3 todo el año
  abre: "08:00",        // primer zarpe posible
  cierra: "24:00",      // el último cruce tiene que terminar antes de esta hora
  cruce_min: 20,        // duración del cruce
  rampa_min: 10,        // tiempo en rampa entre cruces (embarque)
  fuente: "OpenStreetMap vía 49793837 (duration 00:20, opening_hours 08:00-24:00); aproximado",
};

// Cada ferry: primer zarpe del día y desde qué orilla. Después alterna orillas cada
// (cruce + rampa) minutos. Elegidos para que nunca haya dos ferris en la misma rampa
// y para que cada uno termine el día en la orilla donde arranca el siguiente.
export const FERRIS_SIMULADOS = [
  { mmsi: 725001968, nombre: "Pionero", naviera: "TABSA", primera: "08:00", desde: "inicio", atraque_m: 0 },
  { mmsi: 725003001, nombre: "Kawéskar", naviera: "TABSA", primera: "08:00", desde: "fin", atraque_m: 0 },
  // MMSI de ejemplo: el real del Kataik todavía no lo conocemos.
  // Otra naviera: usa su propio muelle, a 400 m de la rampa de TABSA (posición de ejemplo),
  // y entra a las rampas cuando los de TABSA no están maniobrando.
  { mmsi: 999000001, nombre: "Kataik", naviera: "Naviera Tierra del Fuego", primera: "08:45", desde: "inicio", atraque_m: 400 },
];

const NUDO = 0.514444; // m/s
const MIN = 60000;
const DIA = 24 * 60 * MIN;
const RETROCESO_M = 55;   // cuánto se aleja de la rampa marcha atrás antes de girar
const T_RETRO = 0.05;     // 1 min de 20: marcha atrás
const T_GIRO = 0.05;      // 1 min de 20: giro de 180°
const ACEL = 0.12;        // fracción del tramo navegando que usa para acelerar / frenar
const minutos = (hhmm) => { const [h, m] = hhmm.split(":").map(Number); return h * 60 + m; };
const suave = (x) => x * x * (3 - 2 * x);

function avance(u) {
  // Recorrido 0..1 con aceleración y frenado suaves; devuelve [posición, velocidad relativa].
  const vmax = 1 / (1 - ACEL);
  if (u < ACEL) return [(vmax * u * u) / (2 * ACEL), (vmax * u) / ACEL];
  if (u > 1 - ACEL) return [1 - (vmax * (1 - u) ** 2) / (2 * ACEL), (vmax * (1 - u)) / ACEL];
  return [vmax * (u - ACEL / 2), vmax];
}

/** Zarpes de un ferry en el día local que contiene `t` (ms UTC). */
export function zarpesDelDia(f, t, horario = HORARIO) {
  const off = horario.utc_offset_h * 60 * MIN;
  const inicioDia = Math.floor((t + off) / DIA) * DIA - off; // 00:00 local, en ms UTC
  const paso = (horario.cruce_min + horario.rampa_min) * MIN;
  const cierre = inicioDia + minutos(horario.cierra) * MIN;
  const out = [];
  let lado = f.desde;
  for (let dep = inicioDia + minutos(f.primera) * MIN; dep + horario.cruce_min * MIN <= cierre; dep += paso) {
    out.push({ sale: dep, llega: dep + horario.cruce_min * MIN, desde: lado });
    lado = lado === "inicio" ? "fin" : "inicio";
  }
  return { inicioDia, zarpes: out, ladoNoche: lado };
}

/** Hora simulada (ms UTC) para "hoy a las HH:MM" en hora local. */
export function hoyALas(hhmm, horario = HORARIO, ahora = Date.now()) {
  const off = horario.utc_offset_h * 60 * MIN;
  const inicioDia = Math.floor((ahora + off) / DIA) * DIA - off;
  return inicioDia + minutos(hhmm) * MIN;
}

export function crearFuenteSimulada(ruta, { velocidad = 1, ferris = FERRIS_SIMULADOS, horario = HORARIO, inicio = null } = {}) {
  let factor = velocidad;
  let baseReal = Date.now();
  let baseSim = inicio ?? baseReal; // `inicio`: arrancar la simulación en otra hora (demo)
  let suspendido = false;
  const ahoraSim = (real) => baseSim + (real - baseReal) * factor;
  const L = ruta.largo;

  // Rumbo de la ruta en sentido inicio → fin, y "a la derecha" de esa dirección.
  const puntoRuta = (d, lateral) => mover(ruta.punto(d), ruta.rumbo(d) + 90, lateral);
  const proaEnRampa = (lado) => (lado === "fin" ? ruta.rumbo(L) : (ruta.rumbo(0) + 180) % 360);

  function enRampa(f, lado, extra) {
    const d = lado === "fin" ? L : 0;
    return { punto: puntoRuta(d, f.atraque_m), rumbo: proaEnRampa(lado), nudos: 0, ...extra };
  }

  function navegando(f, z, t) {
    const haciaFin = z.desde === "inicio";
    const u = (t - z.sale) / (z.llega - z.sale);
    const aD = (dO) => (haciaFin ? dO : L - dO);                     // distancia desde el origen → desde "inicio"
    const sentido = (dO) => (haciaFin ? ruta.rumbo(aD(dO)) : (ruta.rumbo(aD(dO)) + 180) % 360);
    const lateral = (s) => f.atraque_m + (haciaFin ? 1 : -1) * 70 * Math.sin(Math.PI * s); // por estribor
    const durS = (z.llega - z.sale) / 1000;
    const proaRampa = (sentido(0) + 180) % 360; // llegó con la proa hacia esta rampa

    if (u < T_RETRO) { // marcha atrás: se aleja de la rampa con la proa todavía hacia ella
      const k = u / T_RETRO;
      const dO = RETROCESO_M * suave(k);
      const v = (RETROCESO_M * 6 * k * (1 - k)) / (T_RETRO * durS);
      return { punto: puntoRuta(aD(dO), lateral(0)), rumbo: proaRampa, curso: sentido(dO), nudos: v / NUDO, fase: "zarpando" };
    }
    if (u < T_RETRO + T_GIRO) { // giro de 180° por estribor
      const k = suave((u - T_RETRO) / T_GIRO);
      return { punto: puntoRuta(aD(RETROCESO_M), lateral(0)), rumbo: (proaRampa + 180 * k) % 360,
        curso: sentido(RETROCESO_M), nudos: 1.2, fase: "zarpando" };
    }
    const w = (u - T_RETRO - T_GIRO) / (1 - T_RETRO - T_GIRO);
    const pos = (ww) => {
      const [s] = avance(Math.min(Math.max(ww, 0), 1));
      return puntoRuta(aD(RETROCESO_M + s * (L - RETROCESO_M)), lateral(s));
    };
    const [, vrel] = avance(w);
    const v = (vrel * (L - RETROCESO_M)) / ((1 - T_RETRO - T_GIRO) * durS);
    const rumbo = rumboEntre(pos(w - 0.004), pos(w + 0.004));
    return { punto: pos(w), rumbo, curso: rumbo, nudos: v / NUDO };
  }

  function estado(f, t) {
    const { zarpes, inicioDia } = zarpesDelDia(f, t, horario);
    const primeroManana = zarpesDelDia(f, inicioDia + DIA + 1, horario).zarpes[0];
    if (!zarpes.length || t < zarpes[0].sale) {
      const z = zarpes[0] || primeroManana;
      return enRampa(f, z.desde, suspendido ? {} : { sale: z.sale });
    }
    for (let i = 0; i < zarpes.length; i++) {
      const z = zarpes[i];
      if (t < z.llega) {
        // Suspendido: el ferry espera en la rampa de salida (no sale).
        if (suspendido) return enRampa(f, z.desde, {});
        return { ...navegando(f, z, t), llega: z.llega };
      }
      const siguiente = zarpes[i + 1];
      if (!siguiente || t < siguiente.sale) {
        const lado = z.desde === "inicio" ? "fin" : "inicio";
        const proxima = siguiente || primeroManana;
        return enRampa(f, lado, suspendido ? {} : { sale: proxima.sale });
      }
    }
    return enRampa(f, zarpes[zarpes.length - 1].desde, {});
  }

  return {
    simulada: true,
    horario,
    get velocidad() { return factor; },
    setVelocidad(v) {
      const real = Date.now();
      baseSim = ahoraSim(real);
      baseReal = real;
      factor = v;
    },
    /** Con el cruce suspendido por TABSA, los ferris se quedan en rampa. */
    get suspendido() { return suspendido; },
    set suspendido(v) { suspendido = Boolean(v); },
    /** Hora simulada (ms) que corresponde a la hora real `real`. */
    ahora(real = Date.now()) { return ahoraSim(real); },
    /** Posiciones de todos los ferris en la hora real `real`. */
    leer(real = Date.now()) {
      const t = ahoraSim(real);
      const ultimoReporte = Math.floor(t / 10000) * 10000; // "reportan" cada 10 s
      return ferris.map((f) => {
        const e = estado(f, t);
        const r = {
          mmsi: f.mmsi,
          nombre: f.nombre,
          naviera: f.naviera,
          lat: e.punto[1],
          lon: e.punto[0],
          velocidad_nudos: Math.round(e.nudos * 10) / 10,
          rumbo: Math.round(e.rumbo * 10) / 10,
          hora_utc: new Date(ultimoReporte).toISOString(),
        };
        if (e.curso != null) r.curso = Math.round(e.curso * 10) / 10;
        if (e.sale) r.sale_utc = new Date(e.sale).toISOString();
        if (e.llega) r.llega_utc = new Date(e.llega).toISOString();
        return r;
      });
    },
  };
}
