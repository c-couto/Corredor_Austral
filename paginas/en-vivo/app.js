// Pantalla "En vivo" (premium). Junta: la fuente de datos (hoy simulada), el mapa,
// la lista de ferris y la franja con el estado oficial de TABSA.
//
// Parámetros de la URL:
//   ?premium=0      muestra la pantalla de invitación (solo visual, no hay pagos)
//   ?velocidad=20   simulación 20 veces más rápida (para la demo)
//   ?ferry=MMSI     abre con ese ferry seleccionado
//   ?hora=HH:MM     arranca la simulación a esa hora local de hoy (p. ej. para ver
//                   ferris cruzando de noche, cuando con el horario real están en rampa)
//   ?cruce=pap      Punta Arenas – Porvenir (zarpes reales que publica TABSA)
//   ?cruce=rv       Río Verde – Isla Riesco (horario oficial fijo de TABSA + estado de TABSA)
//   sin ?cruce      Primera Angostura (simulación: TABSA no publica un horario)

import { Ruta } from "./ruta.js";
import { crearFuenteSimulada, hoyALas } from "./fuente-simulada.js";
import { crearFuenteHorario } from "./fuente-horario.js";
import { zarpesDelHorario, aplicarEstado } from "./horario-fijo.js";
import { crearMapa, naviera } from "./mapa.js";
import { situacion, cardinal, horaLocal } from "./situacion.js";
import { estadoTabsa, lecturasTabsa, vientoPuntaDelgada, zarpesTabsa } from "./estado.js";

const $ = (s) => document.querySelector(s);
const params = new URLSearchParams(location.search);
const reducido = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// Cada cruce: de dónde sale la ruta, qué fuente de datos usa y cómo se rotula.
const CRUCES = {
  pa: {
    datos: "datos/cruce-primera-angostura.json",
    chip: "Simulación · datos de ejemplo",
    viento: "punta_delgada",
  },
  pap: {
    datos: "datos/cruce-punta-arenas-porvenir.json",
    chip: "Horario real TABSA · posición estimada",
    viento: "punta_arenas",
    // TABSA (tabsa.cl, ruta Punta Arenas – Porvenir): "Duración del viaje: 2 horas aproximadamente".
    // Manda sobre los 02:20 que figuran en OpenStreetMap.
    duracion_min: 120,
    anclas: ["left", "top-left"],
    etiquetas: [
      { t: "Estrecho de Magallanes", k: "agua", c: [-70.74, -53.25], rot: -28 },
      { t: "TIERRA DEL FUEGO", k: "tierra", c: [-70.36, -53.385], rot: 0 },
    ],
    nota: "Horarios y estado de cada zarpe: los publicados por TABSA. La posición del ferry durante el cruce " +
      "es una estimación según ese horario (no hay señal AIS en la zona). Ante la duda, confirmá con TABSA.",
  },
  rv: {
    datos: "datos/cruce-rio-verde.json",
    horario: "datos/horario-rio-verde.json",  // horario oficial TABSA por temporada y día
    tabsa: "rio_verde",                       // estado oficial del cruce (tabsa_estado.csv)
    chip: "Horario oficial TABSA · posición estimada",
    viento: "rio_verde",
    duracion_min: 5,                          // TABSA: "aproximadamente cinco minutos"
    zoom: 16,
    barco: { mmsi: "tabsa-rv", nombre: "Bahía Azul", naviera: "TABSA", atraque_m: 0 },
    // Cruce de ~500 m en 5 min: marcha atrás y giro cortos; un solo ferry, no hace falta abrirse.
    maniobra: { retroceso_m: 35, retro_s: 30, giro_s: 45, lateral_m: 0 },
    anclas: ["top-right", "bottom-right"], // nombres fuera del lado donde queda el ferry atracado
    etiquetas: [
      { t: "Canal Fitz Roy", k: "agua", c: [-71.4652, -52.6548], rot: 60 },
      { t: "ISLA\nRIESCO", k: "tierra", c: [-71.4711, -52.6530], rot: 0 },
    ],
    nota: "Zarpes: el horario oficial de TABSA (temporada y día de la semana). Si TABSA informa el cruce " +
      "suspendido, el ferry no sale. La posición durante el cruce es una estimación (no hay señal AIS en la " +
      "zona). Ante la duda, confirmá con TABSA: (61) 272 8100.",
  },
};
const cruce = ["pap", "rv"].includes(params.get("cruce")) ? params.get("cruce") : "pa";
const conHorario = cruce !== "pa"; // pap y rv siguen zarpes reales; pa es simulado

/** Río Verde: zarpes del horario oficial (ayer, hoy y 2 días más) con el estado de TABSA de cada momento. */
async function zarpesHorarioFijo(cfg, ruta, horario, desdeMs) {
  const zarpes = zarpesDelHorario(horario, ruta, desdeMs, { dias: 3, duracionMin: cfg.duracion_min });
  const lecturas = await lecturasTabsa(cfg.tabsa);
  aplicarEstado(zarpes, lecturas);
  return { zarpes, leido: lecturas && lecturas.length ? lecturas[lecturas.length - 1].ts : null };
}
const minutosDe = (hhmm) => { const m = /^(\d{1,2}):(\d\d)$/.exec(hhmm || ""); return m ? +m[1] * 60 + +m[2] : null; };

function haceTexto(ms) {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `hace ${s} s`;
  const m = Math.round(s / 60);
  if (m < 60) return `hace ${m} min`;
  const h = Math.floor(m / 60);
  return `hace ${h} h ${String(m % 60).padStart(2, "0")} min`;
}

// ------------------------------------------------------------------ premium (solo visual)

function mostrarInvitacion(si) {
  document.body.classList.toggle("bloqueado", si);
  $("#invitacion").hidden = !si;
}

function aviso(texto) {
  const t = $("#aviso");
  t.textContent = texto;
  t.hidden = false;
  clearTimeout(aviso.timer);
  aviso.timer = setTimeout(() => { t.hidden = true; }, 3200);
}

// ------------------------------------------------------------------ franja de estado

async function cargarEstado() {
  const e = await estadoTabsa();
  const caja = $("#estado");
  const txt = $("#estado-txt");
  if (!e) {
    caja.dataset.tipo = "ok";
    txt.innerHTML = "";
    txt.append("Cruce habilitado · ", Object.assign(document.createElement("em"), { textContent: "dato de ejemplo" }));
    return { suspendido: false };
  }
  const normal = e.status.toUpperCase() === "NORMAL";
  const suspendido = /SUSP/i.test(e.status);
  caja.dataset.tipo = normal ? "ok" : suspendido ? "mal" : "medio";
  const titulo = normal ? "Cruce habilitado" : suspendido ? "Cruce suspendido" : `Cruce: ${e.status.toLowerCase()}`;
  txt.textContent = `${titulo} · Fuente: TABSA · ${haceTexto(Date.now() - e.ts)}`;
  // Si TABSA no informa NORMAL, los ferris simulados se quedan en rampa (no salen).
  return { suspendido: !normal };
}

/** Punta Arenas – Porvenir: la franja muestra el próximo zarpe oficial de TABSA. */
function pintarHorario(fuente) {
  const caja = $("#estado");
  const txt = $("#estado-txt");
  if (!fuente.zarpes.length) {
    caja.dataset.tipo = "medio";
    txt.textContent = fuente.leido === null ? "No se pudo leer el horario de TABSA. Revisá la conexión."
      : "Sin zarpes publicados por TABSA";
    return;
  }
  const t = fuente.ahora();
  const z = fuente.proximo(t);
  const leido = fuente.leido ? ` · ${haceTexto(Date.now() - fuente.leido)}` : "";
  if (!z) {
    caja.dataset.tipo = "medio";
    txt.textContent = `Sin más zarpes publicados · Fuente: TABSA${leido}`;
    return;
  }
  const normal = /^normal$/i.test(z.estado);
  caja.dataset.tipo = normal ? "ok" : /SUSP/i.test(z.estado) ? "mal" : "medio";
  const cuando = Math.floor((z.sale - 3 * 3600000) / 86400000) !== Math.floor((t - 3 * 3600000) / 86400000)
    ? `mañana ${horaLocal(z.sale)}` : horaLocal(z.sale);
  txt.textContent = normal
    ? `Próximo zarpe ${cuando} desde ${z.origen} · Fuente: TABSA${leido}`
    : `Zarpe de ${cuando} desde ${z.origen}: ${z.estado.toLowerCase()} · Fuente: TABSA${leido}`;
}

// ------------------------------------------------------------------ lista de ferris

const filas = new Map();

function crearFila(reg, alTocar) {
  const li = document.createElement("li");
  li.className = "fila";
  li.style.setProperty("--c", naviera(reg.naviera).color);
  li.innerHTML = `
    <button type="button" class="fila-boton" aria-expanded="false">
      <span class="marca-color" aria-hidden="true"></span>
      <span class="fila-texto"><b class="nombre"></b><span class="que"></span></span>
      <span class="eta"></span>
    </button>
    <dl class="detalle" hidden>
      <div><dt>Velocidad</dt><dd class="d-vel"></dd></div>
      <div><dt>Rumbo</dt><dd class="d-rumbo"></dd></div>
      <div><dt>Última señal</dt><dd class="d-senal"></dd></div>
    </dl>`;
  li.querySelector(".nombre").textContent = reg.nombre;
  li.querySelector(".fila-boton").addEventListener("click", () => alTocar(reg.mmsi));
  $("#lista").append(li);
  filas.set(reg.mmsi, li);
  return li;
}

function actualizarLista(regs, ruta, fuente, seleccionado, alTocar) {
  const ahoraSim = fuente.ahora();
  const factor = fuente.velocidad;
  for (const r of regs) {
    const li = filas.get(r.mmsi) || crearFila(r, alTocar);
    const s = situacion(r, ruta, ahoraSim, { suspendido: fuente.suspendido });
    li.querySelector(".que").textContent = `${r.naviera} · ${s.texto}`;
    li.querySelector(".eta").textContent = s.eta || "";
    li.dataset.fase = s.fase;
    const abierta = r.mmsi === seleccionado;
    li.classList.toggle("sel", abierta);
    li.querySelector(".fila-boton").setAttribute("aria-expanded", String(abierta));
    li.querySelector(".detalle").hidden = !abierta;
    if (abierta) {
      li.querySelector(".d-vel").textContent = `${r.velocidad_nudos.toFixed(1)} nudos`;
      li.querySelector(".d-rumbo").textContent = r.velocidad_nudos >= 1 ? `${Math.round(r.rumbo)}° ${cardinal(r.rumbo)}` : "—";
      if (fuente.tipo === "horario") {
        li.querySelector(".detalle div:last-child dt").textContent = "Posición";
        li.querySelector(".d-senal").textContent = "estimada (horario)";
      } else {
        li.querySelector(".d-senal").textContent = haceTexto((ahoraSim - Date.parse(r.hora_utc)) / factor);
      }
    }
  }
}

// ------------------------------------------------------------------ inicio

async function iniciar() {
  mostrarInvitacion(params.get("premium") === "0");
  $("#btn-activar").addEventListener("click", () => aviso("Demo: los pagos todavía no están activos."));
  $("#btn-ver-demo").addEventListener("click", () => {
    params.delete("premium");
    history.replaceState(null, "", `${location.pathname}${params.size ? `?${params}` : ""}`);
    mostrarInvitacion(false);
  });
  $("#btn-ver-invitacion").addEventListener("click", () => { $("#dlg-info").close(); mostrarInvitacion(true); });
  $("#btn-info").addEventListener("click", () => $("#dlg-info").showModal());
  $("#btn-cerrar-info").addEventListener("click", () => $("#dlg-info").close());

  // Selector de cruce: cada cruce es la misma página con ?cruce=...
  document.querySelectorAll(".selector button").forEach((b) => {
    b.setAttribute("aria-selected", String(b.dataset.ruta === cruce));
    b.addEventListener("click", () => {
      if (b.dataset.ruta === cruce) return;
      const p = new URLSearchParams(location.search);
      p.delete("ferry");
      if (b.dataset.ruta === "pa") p.delete("cruce"); else p.set("cruce", b.dataset.ruta);
      location.search = p.toString();
    });
  });

  const cfg = CRUCES[cruce];
  $("#chip-sim").textContent = cfg.chip;
  if (cfg.nota) $("#nota").textContent = cfg.nota;
  const datos = await (await fetch(cfg.datos)).json();
  const ruta = new Ruta(datos);
  const hora = /^\d{1,2}:\d{2}$/.test(params.get("hora") || "") ? params.get("hora") : null;
  const opciones = { velocidad: Number(params.get("velocidad")) || 1, inicio: hora ? hoyALas(hora) : null };
  let fuente;
  if (conHorario) {
    const duracion = cfg.duracion_min || minutosDe(datos.via?.duracion) || 140;
    const horario = cfg.horario ? await (await fetch(cfg.horario)).json() : null;
    // Hora de referencia para armar los días del horario fijo: la de la simulación (?hora=, ×20).
    const leer = (t) => (horario ? zarpesHorarioFijo(cfg, ruta, horario, t) : zarpesTabsa(ruta, duracion));
    const leidos = await leer(opciones.inicio ?? Date.now());
    fuente = crearFuenteHorario(ruta, leidos ? leidos.zarpes : [], {
      ...opciones, ...(cfg.barco ? { barco: cfg.barco } : {}), ...(cfg.maniobra ? { maniobra: cfg.maniobra } : {}),
    });
    fuente.leido = leidos?.leido || null;
    // Cada 5 min se vuelve a leer (TABSA puede suspender o agregar zarpes; a medianoche cambia el día).
    setInterval(async () => {
      const nuevos = await leer(fuente.ahora());
      if (nuevos) { fuente.zarpes.splice(0, fuente.zarpes.length, ...nuevos.zarpes); fuente.leido = nuevos.leido; }
    }, 5 * 60 * 1000);
  } else {
    fuente = crearFuenteSimulada(ruta, opciones);
  }

  let seleccionado = null;
  const seleccionar = (mmsi) => {
    seleccionado = seleccionado === mmsi ? null : mmsi;
    mapa.seleccionar(seleccionado);
    refrescarLista();
  };
  const mapa = crearMapa($("#mapa"), ruta, {
    reducido, onSeleccion: seleccionar,
    ...(cfg.etiquetas ? { etiquetas: cfg.etiquetas } : {}), ...(cfg.anclas ? { anclas: cfg.anclas } : {}),
    ...(cfg.zoom ? { zoomCruce: cfg.zoom } : {}),
  });
  $("#btn-centrar").addEventListener("click", () => mapa.volverAlCruce());

  const btnVel = $("#btn-vel");
  const pintarVel = () => {
    btnVel.textContent = fuente.velocidad > 1 ? `×${fuente.velocidad} · volver a ×1` : "Demo ×20";
    btnVel.setAttribute("aria-pressed", String(fuente.velocidad > 1));
  };
  btnVel.addEventListener("click", () => { fuente.setVelocidad(fuente.velocidad > 1 ? 1 : 20); pintarVel(); });
  pintarVel();

  let regs = fuente.leer();
  const refrescarLista = () => actualizarLista(regs, ruta, fuente, seleccionado, seleccionar);
  const pedido = params.get("ferry"); // ?ferry=MMSI abre la pantalla con ese ferry seleccionado
  const inicial = conHorario ? (pedido || null) : (Number(pedido) || null);
  if (inicial) mapa.map.once("load", () => requestAnimationFrame(() => seleccionar(inicial)));

  if (conHorario) {
    pintarHorario(fuente);
    setInterval(() => pintarHorario(fuente), 30 * 1000);
    if (!fuente.zarpes.length) $("#lista").innerHTML = "<li class='nota'>TABSA no tiene zarpes publicados para estos días.</li>";
  } else {
    const aplicarEstado = async () => {
      const { suspendido } = await cargarEstado();
      fuente.suspendido = suspendido;
    };
    aplicarEstado();
    setInterval(aplicarEstado, 5 * 60 * 1000);
  }
  vientoPuntaDelgada(cfg.viento).then((v) => { if (v && !Number.isNaN(v.desde_deg)) mapa.viento(v.desde_deg); });

  const inicio = performance.now();
  if (reducido) {
    // Sin animación continua: posiciones cada 2 s, sin oleaje en movimiento.
    const paso = () => {
      regs = fuente.leer();
      mapa.moverIconos(regs);
      mapa.tick(regs, Date.now(), null);
      refrescarLista();
    };
    mapa.map.on("load", paso);
    setInterval(paso, 2000);
    return;
  }

  let ultimoTick = 0, ultimaLista = 0;
  const cuadro = (t) => {
    regs = fuente.leer();
    mapa.moverIconos(regs);
    if (t - ultimoTick > 80) {        // ~12 por segundo: estelas, espuma y oleaje
      ultimoTick = t;
      mapa.tick(regs, Date.now(), (t - inicio) / 1000);
    }
    if (t - ultimaLista > 1000) {     // 1 por segundo: textos de la lista
      ultimaLista = t;
      refrescarLista();
    }
    requestAnimationFrame(cuadro);
  };
  requestAnimationFrame(cuadro);
}

iniciar().catch((e) => {
  console.error(e);
  const t = $("#estado-txt");
  if (t) t.textContent = "No se pudo cargar el mapa. Revisá la conexión.";
});
