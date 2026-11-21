// El dibujo del mapa: MapLibre + teselas vectoriales de OpenFreeMap (gratis, sin clave,
// uso comercial permitido; datos © OpenStreetMap). No sabe de dónde vienen los ferris:
// recibe registros { mmsi, nombre, naviera, lat, lon, velocidad_nudos, rumbo }.

import { distancia, mover } from "./ruta.js";

/* global maplibregl */

export const NAVIERAS = {
  "TABSA": { color: "#F59E42", rgb: [245, 158, 66] },
  "Naviera Tierra del Fuego": { color: "#3CC6B8", rgb: [60, 198, 184] },
};
export const naviera = (n) => NAVIERAS[n] || NAVIERAS.TABSA;

// Estela y espuma se miden en PÍXELES de pantalla (y se pasan a metros según el zoom):
// así se ven igual de lejos o de cerca, y no quedan tapadas por el ícono del barco.
const ESTELA_PX = 170;      // largo de la estela detrás del barco
const PASO_PX = 3;          // cada cuántos píxeles se guarda un punto
const POPA_PX = 15;         // dónde empieza la "V" de espuma (detrás del centro del ícono)
const metrosPorPixel = (lat, zoom) => (78271.517 * Math.cos((lat * Math.PI) / 180)) / 2 ** zoom;
const APAGADO_MS = 1500;    // al llegar a la rampa, la estela se apaga en 1,5 s
const VACIO = { type: "FeatureCollection", features: [] };
const POLIGONO = ["match", ["geometry-type"], ["Polygon", "MultiPolygon"], true, false];
const OFM = "https://tiles.openfreemap.org";
const rgba = ([r, g, b], a) => `rgba(${r},${g},${b},${a})`;

// Colores del mapa (carta náutica nocturna)
const TIERRA = "#16222F";
const AGUA = "#0B2C4B";

function estilo() {
  return {
    version: 8,
    glyphs: `${OFM}/fonts/{fontstack}/{range}.pbf`,
    sources: { omt: { type: "vector", url: `${OFM}/planet` } },
    layers: [
      { id: "tierra", type: "background", paint: { "background-color": TIERRA } },
      { id: "vegetacion", type: "fill", source: "omt", "source-layer": "landcover",
        paint: { "fill-color": "#1A2836", "fill-opacity": 0.6 } },
      { id: "agua", type: "fill", source: "omt", "source-layer": "water", filter: POLIGONO,
        paint: { "fill-color": AGUA, "fill-antialias": false } },
      { id: "costa", type: "line", source: "omt", "source-layer": "water", filter: POLIGONO,
        paint: { "line-color": "rgba(130,185,230,0.30)", "line-width": ["interpolate", ["linear"], ["zoom"], 8, 0.6, 13, 1.4] } },
    ],
  };
}

// ------------------------------------------------------------------ oleaje animado
// Imagen animada (como el "punto que late" del ejemplo oficial de MapLibre) usada como
// fill-pattern del agua. Ondas sinusoidales con números de onda ENTEROS: el patrón empalma
// sin costuras. Se recalcula ~12 veces por segundo, no en cada cuadro.

function crearOlas() {
  const N = 128; // px del patrón (con pixelRatio 2 → 64 px en pantalla)
  const TABLA = 1024;
  const SIN = new Float32Array(TABLA);
  for (let i = 0; i < TABLA; i++) SIN[i] = Math.sin((i / TABLA) * 2 * Math.PI);
  const sen = (x) => SIN[((x % TABLA) + TABLA) % TABLA | 0];
  const P1 = new Float32Array(N * N);
  const P2 = new Float32Array(N * N);

  const img = {
    width: N, height: N, data: new Uint8ClampedArray(N * N * 4),
    t: 0, pendiente: true,
    /** Dirección HACIA donde van las olas (grados, 0 = norte). */
    direccion(haciaDeg) {
      const sx = Math.sin((haciaDeg * Math.PI) / 180), sy = -Math.cos((haciaDeg * Math.PI) / 180);
      let k1 = [Math.round(3 * sx), Math.round(3 * sy)];
      if (!k1[0] && !k1[1]) k1 = [3, 0];
      const k2 = [2 * k1[0] + Math.sign(-k1[1]), 2 * k1[1] + Math.sign(k1[0])];
      for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
        P1[y * N + x] = ((k1[0] * x + k1[1] * y) / N) * TABLA;
        P2[y * N + x] = ((k2[0] * x + k2[1] * y) / N) * TABLA;
      }
      this.pendiente = true;
    },
    avanzar(segundos) { this.t = segundos; this.pendiente = true; },
    render() {
      if (!this.pendiente) return false;
      this.pendiente = false;
      const d = this.data;
      const o1 = this.t * 0.22 * TABLA, o2 = this.t * 0.15 * TABLA;
      for (let i = 0, j = 0; i < N * N; i++, j += 4) {
        const v = sen(P1[i] - o1 + 60 * sen(P2[i] - o2));
        let c = (v - 0.55) / 0.45;
        c = c > 0 ? c * c * (3 - 2 * c) : 0;
        d[j] = 170; d[j + 1] = 212; d[j + 2] = 245; d[j + 3] = c * 15; // sutil: como mucho 6 % de opacidad
      }
      return true;
    },
  };
  img.direccion(60);
  return img;
}

// ------------------------------------------------------------------ ícono del ferry

function elementoFerry(reg, onClick) {
  const el = document.createElement("button");
  el.type = "button";
  el.className = "ferry";
  el.style.setProperty("--c", naviera(reg.naviera).color);
  el.setAttribute("aria-label", `Ferry ${reg.nombre}`);
  el.innerHTML =
    '<span class="anillo" aria-hidden="true"></span>' +
    '<svg viewBox="0 0 20 36" aria-hidden="true"><path d="M10 1C14.5 5 16 10 16 15v18a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V15c0-5 1.5-10 6-14z" ' +
    'fill="var(--c)" stroke="#0A1826" stroke-width="1.4"/><rect x="7" y="15" width="6" height="13" rx="1.5" fill="rgba(10,24,38,.35)"/></svg>';
  el.addEventListener("click", (e) => { e.stopPropagation(); onClick(reg.mmsi); });
  return el;
}

// ------------------------------------------------------------------ mapa

export function crearMapa(contenedor, ruta, { reducido = false, onSeleccion = () => {} } = {}) {
  const limites = new maplibregl.LngLatBounds(ruta.inicio.punto, ruta.inicio.punto);
  ruta.puntos.forEach((p) => limites.extend(p));
  // Aire alrededor del cruce: arriba los chips, abajo los botones y el crédito del mapa.
  const padding = { top: 90, bottom: 120, left: 80, right: 80 };

  const map = new maplibregl.Map({
    container: contenedor,
    style: estilo(),
    bounds: limites,
    fitBoundsOptions: { padding, maxZoom: 13 },
    minZoom: 6,
    maxZoom: 15,
    dragRotate: false,
    pitchWithRotate: false,
    attributionControl: false,
    fadeDuration: reducido ? 0 : 300,
  });
  map.touchZoomRotate.disableRotation();
  map.keyboard.disableRotation();
  map.addControl(new maplibregl.AttributionControl({ compact: false }), "bottom-left");

  const olas = crearOlas();
  const ferris = new Map(); // mmsi -> { marker, el, estela, apagando, rgb }
  let seleccionado = null;
  let listo = false;

  map.on("load", () => {
    map.addImage("olas", olas, { pixelRatio: 2 });
    map.addLayer({ id: "agua-olas", type: "fill", source: "omt", "source-layer": "water", filter: POLIGONO,
      paint: { "fill-pattern": "olas" } }, "costa");

    map.addSource("ruta", { type: "geojson", data: ruta.geojson() });
    map.addLayer({ id: "ruta", type: "line", source: "ruta", layout: { "line-cap": "round" },
      paint: { "line-color": "#A9BCCD", "line-opacity": 0.4, "line-width": 1.6, "line-dasharray": [1, 2.6] } });

    map.addSource("espuma", { type: "geojson", lineMetrics: true, data: VACIO });
    map.addLayer({ id: "espuma", type: "line", source: "espuma", layout: { "line-cap": "round" },
      paint: { "line-width": ["interpolate", ["linear"], ["zoom"], 10, 1, 14, 2.4], "line-blur": 0.6,
        "line-opacity": ["get", "o"],
        "line-gradient": ["interpolate", ["linear"], ["line-progress"], 0, "rgba(255,255,255,0.75)", 1, "rgba(255,255,255,0)"] } });

    map.addSource("rampas", { type: "geojson", data: { type: "FeatureCollection", features: [
      { type: "Feature", properties: { nombre: ruta.inicio.nombre, ancla: "bottom-right" }, geometry: { type: "Point", coordinates: ruta.inicio.punto } },
      { type: "Feature", properties: { nombre: ruta.fin.nombre, ancla: "top-left" }, geometry: { type: "Point", coordinates: ruta.fin.punto } },
    ] } });
    map.addLayer({ id: "rampas", type: "circle", source: "rampas",
      paint: { "circle-radius": 4, "circle-color": "#0A1826", "circle-stroke-color": "#EAF1F7", "circle-stroke-width": 1.6 } });
    map.addLayer({ id: "rampas-nombre", type: "symbol", source: "rampas",
      layout: { "text-field": ["get", "nombre"], "text-font": ["Noto Sans Bold"], "text-size": 12,
        "text-anchor": ["get", "ancla"], "text-offset": [0, 0], "text-radial-offset": 0.7, "text-allow-overlap": true },
      paint: { "text-color": "#EAF1F7", "text-halo-color": "#0A1826", "text-halo-width": 1.6 } });

    map.addSource("etiquetas", { type: "geojson", data: { type: "FeatureCollection", features: [
      { type: "Feature", properties: { t: "Primera Angostura", k: "agua" }, geometry: { type: "Point", coordinates: [-69.572, -52.479] } },
      { type: "Feature", properties: { t: "TIERRA DEL FUEGO", k: "tierra" }, geometry: { type: "Point", coordinates: [-69.556, -52.509] } },
    ] } });
    map.addLayer({ id: "etiquetas", type: "symbol", source: "etiquetas",
      layout: { "text-field": ["get", "t"], "text-font": ["match", ["get", "k"], "agua", ["literal", ["Noto Sans Italic"]], ["literal", ["Noto Sans Regular"]]],
        "text-size": ["match", ["get", "k"], "agua", 13, 11], "text-letter-spacing": ["match", ["get", "k"], "agua", 0.05, 0.3],
        "text-rotate": ["match", ["get", "k"], "agua", -40, -40], "text-allow-overlap": true },
      paint: { "text-color": ["match", ["get", "k"], "agua", "#7FB0D8", "#8296AA"], "text-halo-color": "rgba(10,24,38,0.6)", "text-halo-width": 1 } });

    listo = true;
  });

  function agregarFerry(reg) {
    const id = reg.mmsi;
    const { rgb } = naviera(reg.naviera);
    const el = elementoFerry(reg, onSeleccion);
    const marker = new maplibregl.Marker({ element: el, rotationAlignment: "map", pitchAlignment: "map" })
      .setLngLat([reg.lon, reg.lat]).setRotation(reg.rumbo || 0).addTo(map);
    map.addSource(`estela-${id}`, { type: "geojson", lineMetrics: true, data: VACIO });
    // Resplandor: más ancho y transparente, debajo de la estela.
    map.addLayer({ id: `estela-brillo-${id}`, type: "line", source: `estela-${id}`,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-width": ["interpolate", ["linear"], ["zoom"], 10, 6, 14, 14], "line-blur": 6,
        "line-gradient": ["interpolate", ["linear"], ["line-progress"], 0, rgba(rgb, 0), 1, rgba(rgb, 0.5)] } }, "espuma");
    map.addLayer({ id: `estela-${id}`, type: "line", source: `estela-${id}`,
      layout: { "line-cap": "round", "line-join": "round" },
      paint: { "line-width": ["interpolate", ["linear"], ["zoom"], 10, 2.2, 14, 4],
        "line-gradient": ["interpolate", ["linear"], ["line-progress"], 0, rgba(rgb, 0), 0.5, rgba(rgb, 0.55), 1, rgba(rgb, 1)] } }, "espuma");
    const f = { marker, el, estela: [], apagando: null, opacidad: 1 };
    ferris.set(id, f);
    return f;
  }

  function opacidadEstela(id, f, op) {
    if (f.opacidad === op) return;
    f.opacidad = op;
    map.setPaintProperty(`estela-${id}`, "line-opacity", op);
    map.setPaintProperty(`estela-brillo-${id}`, "line-opacity", op);
  }

  return {
    map,
    olas,
    get listo() { return listo; },

    /** Cada cuadro: solo mueve y gira los íconos (barato). */
    moverIconos(regs) {
      if (!listo) return;
      for (const r of regs) {
        const f = ferris.get(r.mmsi) || agregarFerry(r);
        f.marker.setLngLat([r.lon, r.lat]);
        f.marker.setRotation(r.rumbo || 0);
      }
    },

    /** ~12 veces por segundo: estelas, espuma y oleaje. */
    tick(regs, ahoraMs, segundos) {
      if (!listo) return;
      const espuma = [];
      const zoom = map.getZoom();
      for (const r of regs) {
        const mpp = metrosPorPixel(r.lat, zoom);
        const id = r.mmsi;
        const f = ferris.get(id) || agregarFerry(r);
        const p = [r.lon, r.lat];
        const v = r.velocidad_nudos || 0;
        if (v >= 1) {
          if (f.apagando !== null) { f.estela = []; f.apagando = null; }
          opacidadEstela(id, f, 1);
          const ult = f.estela[f.estela.length - 1];
          if (!ult || distancia(ult, p) > PASO_PX * mpp) f.estela.push(p);
          let largo = 0;
          for (let i = f.estela.length - 1; i > 0; i--) {
            largo += distancia(f.estela[i], f.estela[i - 1]);
            if (largo > ESTELA_PX * mpp) { f.estela = f.estela.slice(i - 1); break; }
          }
          // "V" de espuma detrás del barco
          const popa = mover(p, r.rumbo + 180, POPA_PX * mpp);
          const brazo = (16 + v * 1.6) * mpp;
          const o = Math.min(1, v / 8) * 0.9;
          for (const lado of [-1, 1]) {
            espuma.push({ type: "Feature", properties: { o },
              geometry: { type: "LineString", coordinates: [popa, mover(popa, r.rumbo + 180 + lado * 22, brazo)] } });
          }
        } else if (f.estela.length > 1) {
          if (f.apagando === null) f.apagando = ahoraMs;
          const op = Math.max(0, 1 - (ahoraMs - f.apagando) / APAGADO_MS);
          opacidadEstela(id, f, Math.round(op * 20) / 20);
          if (op === 0) f.estela = [];
        }
        const coords = f.estela.length ? [...f.estela, p] : [];
        map.getSource(`estela-${id}`).setData(coords.length > 1
          ? { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: coords } } : VACIO);
      }
      map.getSource("espuma").setData({ type: "FeatureCollection", features: espuma });
      if (segundos != null) { olas.avanzar(segundos); map.triggerRepaint(); }
    },

    seleccionar(mmsi) {
      seleccionado = mmsi;
      for (const [id, f] of ferris) f.el.classList.toggle("sel", id === mmsi);
      const f = ferris.get(mmsi);
      if (f && !map.getBounds().contains(f.marker.getLngLat())) {
        map.easeTo({ center: f.marker.getLngLat(), duration: reducido ? 0 : 600 });
      }
    },
    get seleccionado() { return seleccionado; },

    volverAlCruce() {
      map.fitBounds(limites, { padding, maxZoom: 13, duration: reducido ? 0 : 700 });
    },

    /** Viento: de dónde VIENE (grados). Las olas van hacia el lado contrario. */
    viento(desdeDeg) {
      olas.direccion((desdeDeg + 180) % 360);
      if (listo) map.triggerRepaint();
    },
  };
}
