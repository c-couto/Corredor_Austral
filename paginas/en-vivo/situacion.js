// Qué está haciendo cada ferry, deducido de su posición, velocidad y rumbo.
// Sirve igual para la fuente simulada y para la real. Usa los datos opcionales si están:
//   curso (rumbo sobre el fondo), sale_utc, llega_utc.

const NUDO = 0.514444;
const EN_RAMPA_M = 250;   // a menos de esto de una rampa y quieto: está en la rampa
const MANIOBRA_M = 400;   // a menos de esto de una rampa y moviéndose: zarpando / atracando
const EMBARQUE_MIN = 15;  // si sale en menos de esto, está embarcando

function diferencia(a, b) {
  const d = Math.abs((((a - b) % 360) + 360) % 360);
  return d > 180 ? 360 - d : d;
}

export function horaLocal(ms, offsetH = -3) {
  const d = new Date(ms + offsetH * 3600000);
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
}

const enMin = (ms) => Math.max(1, Math.ceil(ms / 60000));
const diaLocal = (ms, offsetH = -3) => Math.floor((ms + offsetH * 3600000) / 86400000);

export function situacion(reg, ruta, ahoraMs, { suspendido = false } = {}) {
  const { d, desvio } = ruta.proyectar([reg.lon, reg.lat]);
  const v = reg.velocidad_nudos || 0;
  if (desvio > 1500) return { fase: "fuera", texto: "Fuera de la ruta del cruce", eta: null };

  const cercaInicio = d < EN_RAMPA_M, cercaFin = ruta.largo - d < EN_RAMPA_M;
  if (v < 1 && (cercaInicio || cercaFin)) {
    const lado = cercaInicio ? ruta.inicio.nombre : ruta.fin.nombre;
    if (suspendido) return { fase: "rampa", texto: `En rampa ${lado} · cruce suspendido`, eta: null };
    if (reg.suspendido) return { fase: "rampa", texto: `En rampa ${lado} · próximo zarpe suspendido`, eta: null };
    if (!reg.sale_utc) return { fase: "rampa", texto: `En rampa ${lado}`, eta: null };
    const sale = Date.parse(reg.sale_utc);
    const falta = sale - ahoraMs;
    if (falta <= EMBARQUE_MIN * 60000) return { fase: "rampa", texto: `En rampa ${lado} · embarcando`, eta: `sale en ~${enMin(falta)} min` };
    const otroDia = diaLocal(sale) !== diaLocal(ahoraMs);
    const texto = otroDia ? `En rampa ${lado} · sin más zarpes hoy` : `En rampa ${lado} · en espera`;
    return { fase: "rampa", texto, eta: `sale ${otroDia ? "mañana " : ""}${horaLocal(sale)}` };
  }
  if (v < 1) return { fase: "detenido", texto: "Detenido en el cruce", eta: null };

  // Hacia dónde va: por el curso (al dar marcha atrás la proa apunta al revés).
  const curso = reg.curso ?? reg.rumbo;
  const haciaFin = diferencia(curso, ruta.rumbo(d)) < 90;
  const destino = haciaFin ? ruta.fin.nombre : ruta.inicio.nombre;
  const origen = haciaFin ? ruta.inicio.nombre : ruta.fin.nombre;
  const restante = haciaFin ? ruta.largo - d : d;
  const recorrido = ruta.largo - restante;
  const min = reg.llega_utc
    ? enMin(Date.parse(reg.llega_utc) - ahoraMs)
    : enMin((restante / (Math.max(v, 3) * NUDO)) * 1000);
  const eta = `llega en ~${min} min`;
  if (recorrido < MANIOBRA_M) return { fase: "zarpando", texto: `Zarpando de ${origen}`, eta };
  if (restante < MANIOBRA_M) return { fase: "atracando", texto: `Atracando en ${destino}`, eta };
  return { fase: "cruzando", texto: `Cruzando hacia ${destino}`, eta };
}

const PUNTOS = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"];
export const cardinal = (g) => PUNTOS[Math.round((((g % 360) + 360) % 360) / 45) % 8];
