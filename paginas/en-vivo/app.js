// Pantalla "En vivo" (premium). Junta: la fuente de datos (hoy simulada), el mapa,
// la lista de ferris y la franja con el estado oficial de TABSA.
//
// Parámetros de la URL:
//   ?premium=0      muestra la pantalla de invitación (solo visual, no hay pagos)
//   ?velocidad=20   simulación 20 veces más rápida (para la demo)
//   ?ferry=MMSI     abre con ese ferry seleccionado
//   ?hora=HH:MM     arranca la simulación a esa hora local de hoy (p. ej. para ver
//                   ferris cruzando de noche, cuando con el horario real están en rampa)

import { Ruta } from "./ruta.js";
import { crearFuenteSimulada, hoyALas } from "./fuente-simulada.js";
import { crearMapa, naviera } from "./mapa.js";
import { situacion, cardinal } from "./situacion.js";
import { estadoTabsa, vientoPuntaDelgada } from "./estado.js";

const $ = (s) => document.querySelector(s);
const params = new URLSearchParams(location.search);
const reducido = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

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

function actualizarLista(regs, ruta, ahoraSim, factor, seleccionado, alTocar, suspendido) {
  for (const r of regs) {
    const li = filas.get(r.mmsi) || crearFila(r, alTocar);
    const s = situacion(r, ruta, ahoraSim, { suspendido });
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
      li.querySelector(".d-senal").textContent = haceTexto((ahoraSim - Date.parse(r.hora_utc)) / factor);
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

  // Selector de cruce
  document.querySelectorAll(".selector button").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll(".selector button").forEach((x) => x.setAttribute("aria-selected", String(x === b)));
    const pronto = b.dataset.ruta !== "pa";
    $("#pronto").hidden = !pronto;
    document.body.classList.toggle("ruta-pronto", pronto);
  }));

  const datos = await (await fetch("datos/cruce-primera-angostura.json")).json();
  const ruta = new Ruta(datos);
  const hora = /^\d{1,2}:\d{2}$/.test(params.get("hora") || "") ? params.get("hora") : null;
  const fuente = crearFuenteSimulada(ruta, {
    velocidad: Number(params.get("velocidad")) || 1,
    inicio: hora ? hoyALas(hora) : null,
  });

  let seleccionado = null;
  const seleccionar = (mmsi) => {
    seleccionado = seleccionado === mmsi ? null : mmsi;
    mapa.seleccionar(seleccionado);
    refrescarLista();
  };
  const mapa = crearMapa($("#mapa"), ruta, { reducido, onSeleccion: seleccionar });
  $("#btn-centrar").addEventListener("click", () => mapa.volverAlCruce());

  const btnVel = $("#btn-vel");
  const pintarVel = () => {
    btnVel.textContent = fuente.velocidad > 1 ? `×${fuente.velocidad} · volver a ×1` : "Demo ×20";
    btnVel.setAttribute("aria-pressed", String(fuente.velocidad > 1));
  };
  btnVel.addEventListener("click", () => { fuente.setVelocidad(fuente.velocidad > 1 ? 1 : 20); pintarVel(); });
  pintarVel();

  let regs = fuente.leer();
  const refrescarLista = () =>
    actualizarLista(regs, ruta, fuente.ahora(), fuente.velocidad, seleccionado, seleccionar, fuente.suspendido);
  const inicial = Number(params.get("ferry")); // ?ferry=MMSI abre la pantalla con ese ferry seleccionado
  if (inicial) mapa.map.once("load", () => requestAnimationFrame(() => seleccionar(inicial)));

  const aplicarEstado = async () => {
    const { suspendido } = await cargarEstado();
    fuente.suspendido = suspendido;
  };
  aplicarEstado();
  setInterval(aplicarEstado, 5 * 60 * 1000);
  vientoPuntaDelgada().then((v) => { if (v && !Number.isNaN(v.desde_deg)) mapa.viento(v.desde_deg); });

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
