// Fuente HORARIO REAL (Punta Arenas – Porvenir): el ferry sigue los zarpes que publica TABSA
// (los guarda nuestro recolector cada 30 min en data/auto/tabsa_programados.csv).
// Real: hora de cada zarpe, origen/destino y su estado (si TABSA lo suspende, no sale).
// Estimado: la posición durante el cruce (duración según OpenStreetMap) y el barco
// (TABSA no publica cuál hace cada viaje).

import { crearMovimiento, registro } from "./movimiento.js";
import { crearReloj } from "./fuente-simulada.js";

export const FERRY_TABSA = { mmsi: "tabsa-pap", nombre: "Ferry TABSA", naviera: "TABSA", atraque_m: 0 };

const normal = (z) => /^normal$/i.test((z.estado || "").trim());
const otro = (lado) => (lado === "inicio" ? "fin" : "inicio");

/**
 * @param zarpes [{ sale, llega, desde: "inicio" | "fin", estado }] en ms UTC, ordenados por `sale`.
 */
export function crearFuenteHorario(ruta, zarpes, { velocidad = 1, inicio = null, barco = FERRY_TABSA } = {}) {
  const reloj = crearReloj({ velocidad, inicio });
  const mov = crearMovimiento(ruta);

  function estado(t) {
    if (!zarpes.length) return null;
    let lado = zarpes[0].desde;
    for (const z of zarpes) {
      if (z.sale > t) break;
      if (!normal(z)) continue;                 // zarpe suspendido: el ferry no se movió
      if (t < z.llega) return { ...mov.navegando(barco, z, t), llega: z.llega };
      lado = otro(z.desde);                     // ya llegó a la otra orilla
    }
    const proximo = zarpes.find((z) => z.sale > t);
    if (!proximo) return mov.enRampa(barco, lado);
    if (!normal(proximo)) return mov.enRampa(barco, lado, { suspendido: true });
    return mov.enRampa(barco, lado, { sale: proximo.sale });
  }

  return {
    simulada: false,
    tipo: "horario",
    zarpes,
    get velocidad() { return reloj.velocidad; },
    setVelocidad(v) { reloj.setVelocidad(v); },
    suspendido: false,
    ahora(real = Date.now()) { return reloj.ahora(real); },
    leer(real = Date.now()) {
      const t = reloj.ahora(real);
      const e = estado(t);
      return e ? [registro(barco, e, t)] : [];
    },
    /** Próximo zarpe después de `t` (para la franja de estado). */
    proximo(t) { return zarpes.find((z) => z.sale > t) || null; },
  };
}
