// Comprobación (la corre tests/test_en_vivo.py si hay Node): el ferry en reposo está en la rampa
// desde donde sale el próximo zarpe, aunque haya zarpes cancelados en el medio.
import fs from "node:fs";
import { pathToFileURL } from "node:url";
const R = process.argv[2];
const { Ruta } = await import(pathToFileURL(R + "/ruta.js"));
const { crearFuenteHorario } = await import(pathToFileURL(R + "/fuente-horario.js"));
const { situacion } = await import(pathToFileURL(R + "/situacion.js"));
const ruta = new Ruta(JSON.parse(fs.readFileSync(R + "/datos/cruce-punta-arenas-porvenir.json", "utf8")));
const H = 3600000, t0 = Date.UTC(2026, 10, 26, 12, 0);
const zarpes = [
  { sale: t0 + 1 * H, llega: t0 + 3 * H, desde: "inicio", estado: "CANCELADO" },   // hoy, cancelado
  { sale: t0 + 20 * H, llega: t0 + 22 * H, desde: "fin", estado: "NORMAL" },        // mañana, desde la otra orilla
];
const fuente = crearFuenteHorario(ruta, zarpes);
const t = t0 + 5 * H;
const [reg] = fuente.leer(t);
const s = situacion(reg, ruta, t);
const { d } = ruta.proyectar([reg.lon, reg.lat]);
const enFin = ruta.largo - d < 300;
console.log(JSON.stringify({ enFin, texto: s.texto }));
process.exit(enFin && s.texto.includes(ruta.fin.nombre) ? 0 : 1);
