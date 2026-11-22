"""Mapa en vivo, etapa 1: WebSocket, lectura de mensajes AIS, sondeo, cobertura y cruces.

Todo con datos simulados en carpetas temporales: no se conecta a internet ni toca data/.
"""

import json
import math
import os
import socket
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

from ais import barcos, datos, reporte, sondeo
from ais import websocket as ws

from .helpers import TempDataDir

T0 = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)
PIONERO = 725001968
KEY = "CLAVE-SECRETA-123"


# ------------------------------------------------------------------ simulaciones

def _interp(a, b, f):
    return a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f


def ferry_ida_y_vuelta(ruta="primera_angostura", ciclos=6, paso_min=2, cruce_min=20, muelle_min=20):
    """Un ferry que espera en una orilla, cruza, espera en la otra y vuelve. Devuelve los puntos."""
    (_, la, oa), (_, lb, ob) = barcos.TERMINALES[ruta]
    A, B = (la, oa), (lb, ob)
    pts, t = [], T0
    tramos = []
    for _ in range(ciclos):
        tramos += [("quieto", A, A, muelle_min), ("cruza", A, B, cruce_min),
                   ("quieto", B, B, muelle_min), ("cruza", B, A, cruce_min)]
    tramos.append(("quieto", A, A, 10))
    for tipo, desde, hasta, dur in tramos:
        for k in range(0, dur, paso_min):
            lat, lon = _interp(desde, hasta, k / dur)
            pts.append(reporte.Punto(t, lat, lon, 0.0 if tipo == "quieto" else 9.5))
            t += timedelta(minutes=paso_min)
    return pts


def mensaje_posicion(mmsi, ts, lat, lon, tipo="PositionReport", sog=9.5, nombre="PIONERO"):
    return json.dumps({
        "MessageType": tipo,
        "MetaData": {"MMSI": mmsi, "ShipName": nombre + "   ", "latitude": lat, "longitude": lon,
                     "time_utc": ts.strftime("%Y-%m-%d %H:%M:%S") + ".123456789 +0000 UTC"},
        "Message": {tipo: {"UserID": mmsi, "Latitude": lat, "Longitude": lon, "Sog": sog, "Cog": 200.5,
                           "TrueHeading": 511, "NavigationalStatus": 0}},
    }).encode()


def mensaje_estatico(mmsi, nombre, ts=T0):
    return json.dumps({
        "MessageType": "ShipStaticData",
        "MetaData": {"MMSI": mmsi, "ShipName": nombre, "time_utc": ts.strftime("%Y-%m-%d %H:%M:%S") + " +0000 UTC"},
        "Message": {"ShipStaticData": {"UserID": mmsi, "Name": nombre, "Type": 60, "CallSign": "CA1234",
                                       "ImoNumber": 0, "Destination": "PORVENIR"}},
    }).encode()


class FakeClock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        self.t += 1
        return self.t


class FakeConn:
    """Conexión falsa: entrega los mensajes de la lista y después 'se acaba el tiempo'."""

    def __init__(self, mensajes, clock):
        self.mensajes, self.clock, self.enviados, self.cerrada = list(mensajes), clock, [], False

    def send_text(self, text):
        self.enviados.append(text)

    def recv(self):
        if self.mensajes:
            return self.mensajes.pop(0)
        self.clock.t += 10_000  # fin de la escucha
        raise socket.timeout()

    def close(self):
        self.cerrada = True


# ------------------------------------------------------------------ WebSocket

class FakeSock:
    def __init__(self, data, chunk=3):
        self.chunks = [data[i:i + chunk] for i in range(0, len(data), chunk)]
        self.sent = []

    def recv(self, n):
        return self.chunks.pop(0) if self.chunks else b""

    def sendall(self, b):
        self.sent.append(b)

    def close(self):
        pass


def server_frame(opcode, data, fin=True):
    n = len(data)
    head = bytes([(0x80 if fin else 0) | opcode])
    head += bytes([n]) if n < 126 else bytes([126]) + n.to_bytes(2, "big")
    return head + data


class WebSocketTest(unittest.TestCase):
    def test_frame_ida_y_vuelta(self):
        for size in (5, 300, 70_000):
            payload = bytes(range(256)) * (size // 256) + b"x" * (size % 256)
            frame = ws.encode_frame(ws.TEXT, payload, mask_key=b"\x01\x02\x03\x04")
            (fin, op, data), used = ws.parse_frame(frame + b"resto")
            self.assertEqual((fin, op, data, used), (True, ws.TEXT, payload, len(frame)))
            self.assertIsNone(ws.parse_frame(frame[:-1]))  # incompleto: esperar más

    def test_responde_ping_y_junta_fragmentos(self):
        data = (server_frame(ws.PING, b"hola") + server_frame(ws.TEXT, b'{"a":', fin=False)
                + server_frame(ws.CONT, b"1}") + server_frame(ws.CLOSE, b"\x03\xe8chau"))
        sock = FakeSock(data)
        conn = ws.WebSocket(sock)
        self.assertEqual(conn.recv(), b'{"a":1}')
        (_, op, payload), _ = ws.parse_frame(sock.sent[0])
        self.assertEqual((op, payload), (ws.PONG, b"hola"))
        with self.assertRaises(ws.Closed):
            conn.recv()

    def test_clave_de_aceptacion_rfc6455(self):
        self.assertEqual(ws.accept_key("dGhlIHNhbXBsZSBub25jZQ=="), "s3pPLMBiTxaQ9kYGzzhZRbK+xOo=")


# ------------------------------------------------------------------ mensajes

class MensajesTest(unittest.TestCase):
    def test_posicion(self):
        m = sondeo.parse_message(mensaje_posicion(PIONERO, T0, -52.48, -69.56))
        self.assertEqual(m["kind"], "pos")
        r = m["row"]
        self.assertEqual((r["ts_utc"], r["mmsi"], r["nombre"], r["zona"]),
                         ("2026-11-20T12:00:00Z", PIONERO, "PIONERO", "primera_angostura"))
        self.assertIsNone(r["rumbo_deg"])  # 511 = sin dato

    def test_posicion_invalida_y_basura(self):
        self.assertIsNone(sondeo.parse_message(mensaje_posicion(PIONERO, T0, 91, 181)))
        self.assertIsNone(sondeo.parse_message(b"no es json"))
        self.assertEqual(sondeo.parse_message(b'{"error": "Api Key Is Not Valid"}')["kind"], "error")

    def test_datos_fijos(self):
        r = sondeo.parse_message(mensaje_estatico(725009999, "KATAIK"))["row"]
        self.assertEqual((r["mmsi"], r["nombre"], r["tipo"]), (725009999, "KATAIK", 60))

    def test_suscripcion(self):
        s = sondeo.subscription(KEY)
        self.assertEqual(s["BoundingBoxes"], [[[-52.65, -69.85], [-52.35, -69.30]],
                                              [[-53.40, -70.95], [-53.05, -70.30]]])
        self.assertIn("PositionReport", s["FilterMessageTypes"])


# ------------------------------------------------------------------ sondeo

class SondeoTest(TempDataDir):
    def base(self):
        return datos.base_dir()

    def correr(self, mensajes, conexiones=None):
        clock = FakeClock()
        conns = []

        def connect(url, timeout):
            if conexiones:
                step = conexiones.pop(0)
                if isinstance(step, BaseException):
                    raise step
            c = FakeConn(mensajes, clock)
            conns.append(c)
            return c

        sleep = mock.Mock()
        stats = sondeo.run(1, KEY, self.base(), connect=connect, clock=clock, sleep=sleep, log=lambda s: None)
        return stats, conns, sleep

    def test_guarda_posiciones_sin_repetir_y_agrega_al_final(self):
        mensajes = [
            mensaje_posicion(PIONERO, T0, -52.48, -69.56),
            mensaje_posicion(PIONERO, T0 + timedelta(seconds=30), -52.481, -69.561),  # < 1 min: no se guarda
            mensaje_posicion(PIONERO, T0 + timedelta(seconds=65), -52.482, -69.562),
            mensaje_estatico(PIONERO, "PIONERO"),
            mensaje_estatico(PIONERO, "PIONERO"),  # repetido: se guarda una vez
            b"basura",
            mensaje_posicion(PIONERO, T0, 91, 181, tipo="StandardClassBPositionReport"),  # sin posición
        ]
        stats, conns, _ = self.correr(list(mensajes))
        self.assertEqual((stats["mensajes"], stats["posiciones"], stats["error"]), (7, 2, ""))
        sub = json.loads(conns[0].enviados[0])  # lo primero que se manda es la suscripción
        self.assertEqual(sub["APIKey"], KEY)
        self.assertTrue(conns[0].cerrada)

        archivo = self.base() / "posiciones" / "2026-11.csv"
        self.assertEqual(len(datos.read(archivo)), 2)
        self.assertEqual(len(datos.read(self.base() / "barcos.csv")), 1)
        self.assertEqual(len(datos.read(self.base() / "sesiones.csv")), 1)

        antes = archivo.read_bytes()
        self.correr(list(mensajes))  # segunda corrida: agrega, no reescribe
        despues = archivo.read_bytes()
        self.assertTrue(despues.startswith(antes))
        self.assertEqual(len(datos.read(archivo)), 4)
        self.assertEqual(despues.count(b"ts_utc"), 1)  # un solo encabezado
        self.assertNotIn(b"\r\n", despues)
        self.assertEqual(len(datos.read(self.base() / "sesiones.csv")), 2)

    def test_reconecta_si_se_corta_y_no_muestra_la_clave(self):
        stats, conns, sleep = self.correr([mensaje_posicion(PIONERO, T0, -52.48, -69.56)],
                                          conexiones=[OSError(f"fallo con {KEY}")])
        self.assertEqual(stats["posiciones"], 1)
        self.assertEqual(len(conns), 1)
        sleep.assert_called_once()
        self.assertNotIn(KEY, stats["error"])

    def test_clave_invalida_frena(self):
        stats, conns, _ = self.correr([b'{"error": "Api Key Is Not Valid"}'])
        self.assertTrue(stats["error"].startswith("aisstream rechazó"))
        self.assertEqual(len(conns), 1)  # no insiste

    def test_cuenta_los_tipos_de_mensaje(self):
        stats, _, _ = self.correr([mensaje_posicion(PIONERO, T0, -52.48, -69.56), b"basura",
                                   json.dumps({"MessageType": "AidsToNavigationReport"}).encode()])
        self.assertEqual(stats["tipos"], {"PositionReport": 1, "(no es JSON)": 1, "AidsToNavigationReport": 1})
        self.assertEqual(datos.read(self.base() / "sesiones.csv")[0].keys(), set(datos.SESIONES))  # mismas columnas

    def test_prueba_de_control_no_guarda_nada(self):
        clock = FakeClock()
        conns = []

        def connect(url, timeout):
            conns.append(FakeConn([mensaje_posicion(244000001, T0, 51.95, 4.10, nombre="RTM"),
                                   mensaje_posicion(244000002, T0, 51.96, 4.20, nombre="RTM2"),
                                   mensaje_posicion(725000001, T0, -33.02, -71.62, nombre="VALPO")], clock))
            return conns[-1]

        res = sondeo.control(KEY, 2, connect=connect, clock=clock, sleep=lambda s: None, log=lambda s: None)
        self.assertEqual(res["por_zona"], {"valparaiso": (1, 1), "rotterdam": (2, 2)})
        sub = json.loads(conns[0].enviados[0])
        self.assertEqual(len(sub["BoundingBoxes"]), 2)
        self.assertEqual(sub["BoundingBoxes"][1], [[51.85, 3.90], [52.05, 4.50]])
        self.assertFalse(self.data_dir.exists())  # nada en data/

    def test_sin_clave_no_se_conecta(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(ws, "connect") as c, \
                mock.patch("sys.stderr"):
            self.assertEqual(sondeo.main(["--minutos", "1"]), 2)
        c.assert_not_called()


# ------------------------------------------------------------------ cruces y cobertura

class CrucesTest(unittest.TestCase):
    def test_ferry_que_va_y_viene(self):
        cruces = reporte.detectar_cruces(ferry_ida_y_vuelta(), "primera_angostura")
        self.assertEqual(len(cruces), 12)
        self.assertEqual([c.desde for c in cruces[:2]], ["Punta Delgada", "Bahía Azul"])
        self.assertEqual(cruces[0].hacia, "Bahía Azul")
        for c in cruces:
            self.assertLess(c.llegada - c.salida, timedelta(minutes=25))

    def test_detecta_cruces_aunque_falten_datos_en_el_medio(self):
        pts = [p for p in ferry_ida_y_vuelta() if p.sog == 0.0]  # solo en los muelles
        self.assertEqual(len(reporte.detectar_cruces(pts, "primera_angostura")), 12)

    def test_punta_arenas_porvenir(self):
        pts = ferry_ida_y_vuelta("punta_arenas_porvenir", ciclos=2, paso_min=5, cruce_min=140, muelle_min=40)
        cruces = reporte.detectar_cruces(pts, "punta_arenas_porvenir")
        self.assertEqual(len(cruces), 4)
        self.assertTrue(cruces[0].desde.startswith("Punta Arenas"))
        self.assertEqual(reporte.detectar_cruces(pts, "primera_angostura"), [])  # otra ruta

    def test_buque_de_paso_no_cuenta_como_cruce(self):
        (_, la, oa), (_, lb, ob) = barcos.TERMINALES["primera_angostura"]
        mid = ((la + lb) / 2, (oa + ob) / 2)
        kx, ky = 111.32 * math.cos(math.radians(mid[0])), 110.57
        bx, by = (ob - oa) * kx, (lb - la) * ky          # línea del ferry, en km
        largo = math.hypot(bx, by)
        px, py = by / largo, -bx / largo                 # perpendicular (unitaria, km)
        pts = []
        for i, s in enumerate(range(-15, 16)):  # recorre el Estrecho perpendicular a la línea del ferry
            lat = mid[0] + s * py / ky
            lon = mid[1] + s * px / kx
            pts.append(reporte.Punto(T0 + timedelta(minutes=2 * i), lat, lon, 12.0))
        self.assertEqual(reporte.detectar_cruces(pts, "primera_angostura"), [])

    def test_muy_lento_no_es_un_cruce(self):
        pts = ferry_ida_y_vuelta(ciclos=1)
        lejos = [reporte.Punto(p.t + timedelta(hours=3 * i), p.lat, p.lon, p.sog) for i, p in enumerate(pts)]
        self.assertEqual(reporte.detectar_cruces(lejos, "primera_angostura"), [])


class CoberturaTest(unittest.TestCase):
    def test_horas_y_hueco_solo_cuentan_el_tiempo_escuchado(self):
        h = lambda hh, mm: T0.replace(hour=hh, minute=mm)  # noqa: E731
        sesiones = [(h(10, 0), h(10, 10)), (h(10, 30), h(10, 40)), (h(11, 0), h(11, 3)), (h(12, 0), h(12, 10))]
        horas = reporte.horas_escuchadas(sesiones)
        self.assertEqual(horas, {h(10, 0), h(12, 0)})  # 11 h: solo 3 min, no cuenta
        self.assertEqual(reporte.cobertura([h(10, 5)], horas), (1, 2))
        self.assertEqual(reporte.hueco_mas_largo([h(10, 5)], sesiones), timedelta(minutes=28))


class ReporteTest(TempDataDir):
    def test_reporte_completo_con_datos_simulados(self):
        base = datos.base_dir()
        pts = ferry_ida_y_vuelta()
        datos.append_sesion(base, {"inicio_utc": "2026-11-20T12:00:00Z", "fin_utc": "2026-11-20T20:00:00Z",
                                   "mensajes": 1, "posiciones": 1, "error": ""})
        datos.append_posiciones(base, [
            {"ts_utc": p.t.strftime("%Y-%m-%dT%H:%M:%SZ"), "mmsi": PIONERO, "lat": p.lat, "lon": p.lon,
             "sog_kn": p.sog} for p in pts])
        datos.append_posiciones(base, [{"ts_utc": "2026-11-20T13:00:00Z", "mmsi": 725009999,
                                        "nombre": "PATAGONIA</script><b>", "lat": -53.2, "lon": -70.6, "sog_kn": 0}])
        a = reporte.analizar(base)
        pionero = next(f for f in a["barcos"] if f["mmsi"] == PIONERO)
        self.assertEqual((len(pionero["cruces"]), pionero["horas"], pionero["pct"]), (12, 8, 100))
        txt = reporte.texto(a)
        self.assertIn("revisar y agregar a FERRIES", txt)       # PATAGONIA es candidato
        self.assertIn("Kawéskar (725003001): horas con dato 0/8", txt)  # conocido sin datos
        page = reporte.mapa_html(a)
        self.assertNotIn("</script><b>", page)
        self.assertIn("leaflet", page)

    def test_sin_datos(self):
        self.assertIn("Todavía no hay sesiones", reporte.texto(reporte.analizar(datos.base_dir())))


if __name__ == "__main__":
    unittest.main()
