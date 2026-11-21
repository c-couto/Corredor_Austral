// Qué está haciendo cada ferry, deducido de su posición, velocidad y rumbo.
// Sirve igual para la fuente simulada y para la real (no usa nada propio de la simulación,
// salvo `sale_utc` si existe).

const NUDO = 0.514444;
const EN_RAMPA_M = 250;

function diferencia(a, b) {
  const d = Math.abs((((a - b) % 360) + 360) % 360);
  return d > 180 ? 360 - d : d;
}

export function situacion(reg, ruta, ahoraMs) {
  const { d, desvio } = ruta.proyectar([reg.lon, reg.lat]);
  const v = reg.velocidad_nudos || 0;
  if (desvio > 1500) return { fase: "fuera", texto: "Fuera de la ruta del cruce", eta: null };

  if (v < 1 && (d < EN_RAMPA_M || ruta.largo - d < EN_RAMPA_M)) {
    const lado = d < ruta.largo / 2 ? ruta.inicio.nombre : ruta.fin.nombre;
    let eta = null;
    if (reg.sale_utc) {
      const min = Math.max(1, Math.ceil((Date.parse(reg.sale_utc) - ahoraMs) / 60000));
      eta = `sale en ~${min} min`;
    }
    return { fase: "rampa", texto: `En rampa ${lado} · embarcando`, eta };
  }
  if (v < 1) return { fase: "detenido", texto: "Detenido en el cruce", eta: null };

  const haciaFin = diferencia(reg.rumbo, ruta.rumbo(d)) < 90;
  const destino = haciaFin ? ruta.fin.nombre : ruta.inicio.nombre;
  const restante = haciaFin ? ruta.largo - d : d;
  const min = Math.max(1, Math.ceil(restante / (Math.max(v, 3) * NUDO) / 60));
  return { fase: "cruzando", texto: `Cruzando hacia ${destino}`, eta: `llega en ~${min} min` };
}

const PUNTOS = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"];
export const cardinal = (g) => PUNTOS[Math.round((((g % 360) + 360) % 360) / 45) % 8];
