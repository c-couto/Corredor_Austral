// Horario FIJO oficial (Río Verde – Isla Riesco): TABSA no publica estos zarpes en su página
// de estado, pero sí un horario por temporada y día de la semana (datos/horario-rio-verde.json).
// Con ese horario se arman los zarpes de cada día, y el ESTADO de cada zarpe sale del estado
// oficial de TABSA del cruce (leído cada 30 min por nuestro recolector): si en la hora del zarpe
// TABSA informaba el cruce suspendido, el ferry no sale.

const MIN = 60000;
const DIA = 24 * 60 * MIN;
const GRUPO = ["dom", "lun_mie", "mar_jue_vie", "lun_mie", "mar_jue_vie", "mar_jue_vie", "sab"]; // getUTCDay()

const minutos = (hhmm) => { const [h, m] = hhmm.split(":").map(Number); return h * 60 + m; };
const clave = (s) => (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z]+/g, "_").replace(/^_|_$/g, "");

/** Temporada vigente para un día "MM-DD" (las temporadas pueden cruzar el año: 10-01 → 04-21). */
export function temporada(horario, mmdd) {
  return horario.temporadas.find((t) => (t.desde <= t.hasta
    ? mmdd >= t.desde && mmdd <= t.hasta
    : mmdd >= t.desde || mmdd <= t.hasta)) || null;
}

/**
 * Zarpes del horario para `dias` días locales a partir del día de `desdeMs` (ms UTC).
 * @returns {{sale, llega, desde: "inicio"|"fin", estado, origen, destino}[]} ordenados por `sale`.
 */
export function zarpesDelHorario(horario, ruta, desdeMs, { dias = 3, duracionMin = 5, antes = 1 } = {}) {
  const off = horario.utc_offset_h * 60 * MIN;
  const lado = { [clave(ruta.inicio.nombre)]: "inicio", [clave(ruta.fin.nombre)]: "fin" };
  const nombre = { inicio: ruta.inicio.nombre, fin: ruta.fin.nombre };
  const hoy = Math.floor((desdeMs + off) / DIA) * DIA - off; // 00:00 local, en ms UTC
  const out = [];
  for (let k = -antes; k < dias; k++) {
    const inicioDia = hoy + k * DIA;
    const d = new Date(inicioDia + off);
    const mmdd = `${String(d.getUTCMonth() + 1).padStart(2, "0")}-${String(d.getUTCDate()).padStart(2, "0")}`;
    const t = temporada(horario, mmdd);
    const grupo = t && t.dias[GRUPO[d.getUTCDay()]];
    if (!grupo) continue;
    for (const [orilla, horas] of Object.entries(grupo)) {
      const desde = lado[clave(orilla)];
      if (!desde) throw new Error(`orilla desconocida en el horario: ${orilla}`);
      for (const h of horas) {
        const sale = inicioDia + minutos(h) * MIN;
        out.push({ sale, llega: sale + duracionMin * MIN, desde, estado: "NORMAL",
          origen: nombre[desde], destino: nombre[desde === "inicio" ? "fin" : "inicio"] });
      }
    }
  }
  return out.sort((a, b) => a.sale - b.sale);
}

/**
 * Pone a cada zarpe el estado que informaba TABSA a la hora de salir (la última lectura anterior
 * al zarpe; para los zarpes futuros, la última lectura disponible).
 * @param lecturas [{ ts, status }] del cruce, en orden. Sin lecturas, no cambia nada.
 */
export function aplicarEstado(zarpes, lecturas) {
  if (!lecturas || !lecturas.length) return zarpes;
  for (const z of zarpes) {
    let st = null;
    for (const l of lecturas) { if (l.ts <= z.sale) st = l.status; else break; }
    if (st === null) continue; // antes de lo que tenemos leído: queda como en el horario
    z.estado = /^normal$/i.test(st.trim()) ? "NORMAL" : st.trim().toUpperCase();
  }
  return zarpes;
}
