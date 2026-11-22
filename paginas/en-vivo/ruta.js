// Geometría del cruce: suaviza la línea de OpenStreetMap y permite medir sobre ella.
// Todas las distancias en metros. Coordenadas como [lon, lat] (orden de MapLibre/GeoJSON).

const R = 6371008.8;
const rad = (g) => (g * Math.PI) / 180;
const deg = (r) => (r * 180) / Math.PI;

export function distancia(a, b) {
  // Equirectangular: más que suficiente para unos pocos kilómetros.
  const x = rad(b[0] - a[0]) * Math.cos(rad((a[1] + b[1]) / 2));
  const y = rad(b[1] - a[1]);
  return Math.hypot(x, y) * R;
}

export function rumbo(a, b) {
  // Rumbo de a hacia b en grados (0 = norte, 90 = este).
  const x = rad(b[0] - a[0]) * Math.cos(rad((a[1] + b[1]) / 2));
  const y = rad(b[1] - a[1]);
  return (deg(Math.atan2(x, y)) + 360) % 360;
}

export function mover(p, rumboDeg, metros) {
  // Punto a `metros` de p en la dirección `rumboDeg`.
  const d = metros / R;
  const lat = p[1] + deg(d * Math.cos(rad(rumboDeg)));
  const lon = p[0] + deg((d * Math.sin(rad(rumboDeg))) / Math.cos(rad(p[1])));
  return [lon, lat];
}

export function chaikin(puntos, vueltas = 3) {
  // Suaviza una línea cortando las esquinas; conserva los dos extremos (las rampas).
  let p = puntos;
  for (let v = 0; v < vueltas; v++) {
    const out = [p[0]];
    for (let i = 0; i < p.length - 1; i++) {
      const [a, b] = [p[i], p[i + 1]];
      out.push([0.75 * a[0] + 0.25 * b[0], 0.75 * a[1] + 0.25 * b[1]]);
      out.push([0.25 * a[0] + 0.75 * b[0], 0.25 * a[1] + 0.75 * b[1]]);
    }
    out.push(p[p.length - 1]);
    p = out;
  }
  return p;
}

export class Ruta {
  /** @param {{nodos: {lat:number, lon:number, nombre?:string}[]}} datos  (archivo de OSM) */
  constructor(datos) {
    const crudos = datos.nodos.map((n) => [n.lon, n.lat]);
    this.inicio = { nombre: datos.nodos[0].nombre, punto: crudos[0] };
    this.fin = { nombre: datos.nodos[datos.nodos.length - 1].nombre, punto: crudos[crudos.length - 1] };
    this.puntos = chaikin(crudos);
    this.acum = [0];
    for (let i = 1; i < this.puntos.length; i++) {
      this.acum.push(this.acum[i - 1] + distancia(this.puntos[i - 1], this.puntos[i]));
    }
    this.largo = this.acum[this.acum.length - 1];
  }

  _tramo(d) {
    d = Math.min(Math.max(d, 0), this.largo);
    let lo = 0, hi = this.acum.length - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (this.acum[mid] <= d) lo = mid; else hi = mid;
    }
    return [lo, d];
  }

  /** Punto a `d` metros desde Punta Delgada. */
  punto(d) {
    const [i, dd] = this._tramo(d);
    const a = this.puntos[i], b = this.puntos[i + 1];
    const t = (dd - this.acum[i]) / (this.acum[i + 1] - this.acum[i] || 1);
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
  }

  /** Rumbo de la ruta (sentido Punta Delgada → Bahía Azul) a `d` metros. */
  rumbo(d) {
    const [i] = this._tramo(d);
    return rumbo(this.puntos[i], this.puntos[i + 1]);
  }

  /** Proyecta un punto sobre la ruta: { d: metros desde el inicio, desvio: metros a la línea }. */
  proyectar(p) {
    let mejor = { d: 0, desvio: Infinity };
    for (let i = 0; i < this.puntos.length - 1; i++) {
      const a = this.puntos[i], b = this.puntos[i + 1];
      const k = Math.cos(rad(a[1]));
      const ax = 0, ay = 0, bx = (b[0] - a[0]) * k, by = b[1] - a[1];
      const px = (p[0] - a[0]) * k, py = p[1] - a[1];
      const l2 = bx * bx + by * by || 1e-12;
      const t = Math.min(1, Math.max(0, ((px - ax) * bx + (py - ay) * by) / l2));
      const q = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
      const desvio = distancia(p, q);
      if (desvio < mejor.desvio) mejor = { d: this.acum[i] + t * (this.acum[i + 1] - this.acum[i]), desvio };
    }
    return mejor;
  }

  geojson() {
    return { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: this.puntos } };
  }
}
