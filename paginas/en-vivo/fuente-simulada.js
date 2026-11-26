// Fuente SIMULADA (Primera Angostura): ferris de ejemplo con un HORARIO en hora local.
// Entrega lo mismo que entregará la fuente AIS real:
//   { mmsi, nombre, naviera, lat, lon, velocidad_nudos, rumbo, hora_utc }
// más datos opcionales: curso (rumbo sobre el fondo), sale_utc, llega_utc.
// El movimiento (atraque, marcha atrás, giro, cruce) está en movimiento.js.

import { crearMovimiento, registro } from "./movimiento.js";

// ------------------------------------------------------------------ horario (APROXIMADO)
// TABSA no publica un horario fijo para Primera Angostura. Estos valores salen de
// OpenStreetMap (vía 49793837: duration=00:20, opening_hours=08:00-24:00) y hay que
// confirmarlos con TABSA o calibrarlos con datos reales.
export const HORARIO = {
  utc_offset_h: -3,     // Magallanes y Tierra del Fuego: UTC-3 todo el año
  abre: "08:00",        // primer zarpe posible
  cierra: "24:00",      // el último cruce tiene que terminar antes de esta hora
  cruce_min: 20,        // duración del cruce
  rampa_min: 10,        // tiempo en rampa entre cruces (embarque)
  fuente: "OpenStreetMap vía 49793837 (duration 00:20, opening_hours 08:00-24:00); aproximado",
};

// Cada ferry: primer zarpe del día y desde qué orilla. Después alterna orillas cada
// (cruce + rampa) minutos. Elegidos para que nunca haya dos ferris en la misma rampa.
// Solo ferris REALES de TABSA en este cruce (Capitanía de Puerto de Punta Delgada, 2023:
// Pionero, Patagonia y Kawéskar). Los horarios de salida son de ejemplo.
// Cada ferry lleva su propio color (en el mapa y en la lista) para distinguirlos.
export const FERRIS_SIMULADOS = [
  { mmsi: 725001968, nombre: "Pionero", naviera: "TABSA", color: "#F59E42", rgb: [245, 158, 66], primera: "08:00", desde: "inicio", atraque_m: 0 },
  { mmsi: 725003001, nombre: "Kawéskar", naviera: "TABSA", color: "#3CC6B8", rgb: [60, 198, 184], primera: "08:00", desde: "fin", atraque_m: 0 },
];

const MIN = 60000;
const DIA = 24 * 60 * MIN;
const minutos = (hhmm) => { const [h, m] = hhmm.split(":").map(Number); return h * 60 + m; };

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

/** Reloj de la simulación: hora real, o adelantada / acelerada para la demo. */
export function crearReloj({ velocidad = 1, inicio = null } = {}) {
  let factor = velocidad;
  let baseReal = Date.now();
  let baseSim = inicio ?? baseReal;
  const ahora = (real = Date.now()) => baseSim + (real - baseReal) * factor;
  return {
    ahora,
    get velocidad() { return factor; },
    setVelocidad(v) {
      const real = Date.now();
      baseSim = ahora(real);
      baseReal = real;
      factor = v;
    },
  };
}

export function crearFuenteSimulada(ruta, { velocidad = 1, ferris = FERRIS_SIMULADOS, horario = HORARIO, inicio = null } = {}) {
  const reloj = crearReloj({ velocidad, inicio });
  const mov = crearMovimiento(ruta);
  let suspendido = false;

  function estado(f, t) {
    const { zarpes, inicioDia } = zarpesDelDia(f, t, horario);
    const primeroManana = zarpesDelDia(f, inicioDia + DIA + 1, horario).zarpes[0];
    if (!zarpes.length || t < zarpes[0].sale) {
      const z = zarpes[0] || primeroManana;
      return mov.enRampa(f, z.desde, suspendido ? {} : { sale: z.sale });
    }
    for (let i = 0; i < zarpes.length; i++) {
      const z = zarpes[i];
      if (t < z.llega) {
        // Suspendido: el ferry espera en la rampa de salida (no sale).
        if (suspendido) return mov.enRampa(f, z.desde);
        return { ...mov.navegando(f, z, t), llega: z.llega };
      }
      const siguiente = zarpes[i + 1];
      if (!siguiente || t < siguiente.sale) {
        const lado = z.desde === "inicio" ? "fin" : "inicio";
        const proxima = siguiente || primeroManana;
        return mov.enRampa(f, lado, suspendido ? {} : { sale: proxima.sale });
      }
    }
    return mov.enRampa(f, zarpes[zarpes.length - 1].desde);
  }

  return {
    simulada: true,
    horario,
    get velocidad() { return reloj.velocidad; },
    setVelocidad(v) { reloj.setVelocidad(v); },
    /** Con el cruce suspendido por TABSA, los ferris se quedan en rampa. */
    get suspendido() { return suspendido; },
    set suspendido(v) { suspendido = Boolean(v); },
    /** Hora simulada (ms) que corresponde a la hora real `real`. */
    ahora(real = Date.now()) { return reloj.ahora(real); },
    /** Posiciones de todos los ferris en la hora real `real`. */
    leer(real = Date.now()) {
      const t = reloj.ahora(real);
      return ferris.map((f) => registro(f, estado(f, t), t));
    },
  };
}
