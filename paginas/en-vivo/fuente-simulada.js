// Fuente SIMULADA: ferris de ejemplo que van y vienen por el cruce de Primera Angostura.
// Entrega lo mismo que entregará la fuente AIS real:
//   { mmsi, nombre, naviera, lat, lon, velocidad_nudos, rumbo, hora_utc }
// (+ `sale_utc`, que solo la simulación conoce: la hora de salida de la rampa).

import { rumbo as rumboEntre, mover } from "./ruta.js";

const NUDO = 0.514444; // m/s
const MIN = 60000;

// Ciclo de 60 min: 20 cruzando, 10 en rampa, 20 volviendo, 10 en rampa.
const CICLO = [
  { tipo: "cruza", desde: "inicio", min: 20 },
  { tipo: "rampa", en: "fin", min: 10 },
  { tipo: "cruza", desde: "fin", min: 20 },
  { tipo: "rampa", en: "inicio", min: 10 },
];
const CICLO_MIN = CICLO.reduce((s, f) => s + f.min, 0);

export const FERRIS_SIMULADOS = [
  { mmsi: 725001968, nombre: "Pionero", naviera: "TABSA", desfase_min: 0 },
  { mmsi: 725003001, nombre: "Kawéskar", naviera: "TABSA", desfase_min: 30 },
  // MMSI de ejemplo: el real del Kataik todavía no lo conocemos.
  { mmsi: 999000001, nombre: "Kataik", naviera: "Naviera Tierra del Fuego", desfase_min: 47 },
];

const ACEL = 0.1; // 10 % del cruce acelerando y 10 % frenando

function avance(u) {
  // Recorrido (0..1) con aceleración y frenado suaves; devuelve [posición, velocidad relativa].
  const vmax = 1 / (1 - ACEL);
  if (u < ACEL) return [(vmax * u * u) / (2 * ACEL), (vmax * u) / ACEL];
  if (u > 1 - ACEL) return [1 - (vmax * (1 - u) ** 2) / (2 * ACEL), (vmax * (1 - u)) / ACEL];
  return [vmax * (u - ACEL / 2), vmax];
}

function posicionEnCruce(ruta, u, haciaFin) {
  // Posición sobre la ruta, corrida hacia estribor (derecha) en el medio del cruce
  // para que dos ferris en sentido contrario no se pisen.
  const [s] = avance(u);
  const d = (haciaFin ? s : 1 - s) * ruta.largo;
  const base = ruta.punto(d);
  const sentido = haciaFin ? ruta.rumbo(d) : (ruta.rumbo(d) + 180) % 360;
  // El corrimiento depende de la distancia recorrida (no del tiempo): así no gira de costado al arrancar.
  return mover(base, sentido + 90, 45 * Math.sin(Math.PI * s));
}

export function crearFuenteSimulada(ruta, { velocidad = 1, ferris = FERRIS_SIMULADOS } = {}) {
  let factor = velocidad;
  let baseReal = Date.now();
  let baseSim = baseReal;

  const ahoraSim = (real) => baseSim + (real - baseReal) * factor;

  function estado(f, sim) {
    const minCiclo = (((sim / MIN + f.desfase_min) % CICLO_MIN) + CICLO_MIN) % CICLO_MIN;
    let t = minCiclo;
    let i = 0;
    while (t >= CICLO[i].min) { t -= CICLO[i].min; i++; }
    const fase = CICLO[i];
    const u = t / fase.min;
    const finFase = sim + (fase.min - t) * MIN;
    if (fase.tipo === "rampa") {
      const llegoHaciaFin = fase.en === "fin";
      const punto = fase.en === "fin" ? ruta.fin.punto : ruta.inicio.punto;
      const rumbo = llegoHaciaFin ? ruta.rumbo(ruta.largo) : (ruta.rumbo(0) + 180) % 360;
      return { punto, rumbo, nudos: 0, sale_utc: new Date(finFase).toISOString() };
    }
    const haciaFin = fase.desde === "inicio";
    const punto = posicionEnCruce(ruta, u, haciaFin);
    const delante = posicionEnCruce(ruta, Math.min(u + 0.004, 1), haciaFin);
    const atras = posicionEnCruce(ruta, Math.max(u - 0.004, 0), haciaFin);
    const rumbo = rumboEntre(atras, delante);
    const [, vrel] = avance(u);
    const mps = (vrel * ruta.largo) / (fase.min * 60);
    return { punto, rumbo, nudos: mps / NUDO };
  }

  return {
    simulada: true,
    get velocidad() { return factor; },
    setVelocidad(v) {
      const real = Date.now();
      baseSim = ahoraSim(real);
      baseReal = real;
      factor = v;
    },
    /** Hora simulada (ms) que corresponde a la hora real `real`. */
    ahora(real = Date.now()) { return ahoraSim(real); },
    /** Posiciones de todos los ferris en la hora real `real`. */
    leer(real = Date.now()) {
      const sim = ahoraSim(real);
      const ultimoReporte = Math.floor(sim / 10000) * 10000; // "reportan" cada 10 s
      return ferris.map((f) => {
        const e = estado(f, sim);
        return {
          mmsi: f.mmsi,
          nombre: f.nombre,
          naviera: f.naviera,
          lat: e.punto[1],
          lon: e.punto[0],
          velocidad_nudos: Math.round(e.nudos * 10) / 10,
          rumbo: Math.round(e.rumbo * 10) / 10,
          hora_utc: new Date(ultimoReporte).toISOString(),
          ...(e.sale_utc ? { sale_utc: e.sale_utc } : {}),
        };
      });
    },
  };
}
