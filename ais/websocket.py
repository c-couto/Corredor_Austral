"""Cliente WebSocket mínimo (RFC 6455) con la biblioteca estándar.

Python no trae WebSocket y no queremos instalar librerías (el proyecto usa solo la
biblioteca estándar). Esto alcanza para aisstream: conectar por TLS, mandar un texto
(la suscripción) y recibir mensajes. Responde los "ping" del servidor.
"""

from __future__ import annotations

import base64
import hashlib
import os
import socket
import ssl
import struct
from urllib.parse import urlsplit

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_FRAME = 4 * 1024 * 1024  # 4 MB: un mensaje AIS pesa < 2 KB

TEXT, BINARY, CLOSE, PING, PONG, CONT = 0x1, 0x2, 0x8, 0x9, 0xA, 0x0


class WebSocketError(Exception):
    pass


class Closed(WebSocketError):
    """El servidor cerró la conexión."""


def encode_frame(opcode: int, payload: bytes, mask_key: bytes | None = None) -> bytes:
    """Arma un frame del cliente (los del cliente van siempre enmascarados)."""
    key = mask_key if mask_key is not None else os.urandom(4)
    n = len(payload)
    head = bytes([0x80 | opcode])
    if n < 126:
        head += bytes([0x80 | n])
    elif n < 65536:
        head += bytes([0x80 | 126]) + struct.pack("!H", n)
    else:
        head += bytes([0x80 | 127]) + struct.pack("!Q", n)
    return head + key + bytes(b ^ key[i % 4] for i, b in enumerate(payload))


def parse_frame(buf: bytes) -> tuple[tuple[bool, int, bytes], int] | None:
    """Lee un frame del principio de `buf`. Devuelve ((fin, opcode, datos), bytes usados)
    o None si todavía no llegó completo."""
    if len(buf) < 2:
        return None
    b1, b2 = buf[0], buf[1]
    n, pos = b2 & 0x7F, 2
    if n == 126:
        if len(buf) < 4:
            return None
        n, pos = struct.unpack("!H", buf[2:4])[0], 4
    elif n == 127:
        if len(buf) < 10:
            return None
        n, pos = struct.unpack("!Q", buf[2:10])[0], 10
    if n > MAX_FRAME:
        raise WebSocketError(f"frame demasiado grande ({n} bytes)")
    key = None
    if b2 & 0x80:
        if len(buf) < pos + 4:
            return None
        key, pos = buf[pos:pos + 4], pos + 4
    if len(buf) < pos + n:
        return None
    data = buf[pos:pos + n]
    if key:
        data = bytes(b ^ key[i % 4] for i, b in enumerate(data))
    return (bool(b1 & 0x80), b1 & 0x0F, data), pos + n


class WebSocket:
    def __init__(self, sock, leftover: bytes = b""):
        self.sock = sock
        self._buf = leftover
        self._parts: list[bytes] = []

    def send_text(self, text: str) -> None:
        self.sock.sendall(encode_frame(TEXT, text.encode("utf-8")))

    def recv(self) -> bytes:
        """Próximo mensaje (texto o binario) como bytes. Si no llega nada dentro del
        timeout del socket lanza socket.timeout (lo leído a medias queda guardado)."""
        while True:
            parsed = parse_frame(self._buf)
            if parsed is None:
                chunk = self.sock.recv(65536)
                if not chunk:
                    raise Closed("el servidor cortó la conexión")
                self._buf += chunk
                continue
            (fin, opcode, data), used = parsed
            self._buf = self._buf[used:]
            if opcode == PING:
                self.sock.sendall(encode_frame(PONG, data))
            elif opcode == PONG:
                pass
            elif opcode == CLOSE:
                try:
                    self.sock.sendall(encode_frame(CLOSE, data[:2]))
                except OSError:
                    pass
                reason = data[2:].decode("utf-8", "replace")
                raise Closed(f"el servidor cerró la conexión{': ' + reason if reason else ''}")
            elif opcode in (TEXT, BINARY, CONT):
                self._parts.append(data)
                if fin:
                    msg, self._parts = b"".join(self._parts), []
                    return msg
            else:
                raise WebSocketError(f"opcode desconocido {opcode}")

    def close(self) -> None:
        try:
            self.sock.sendall(encode_frame(CLOSE, struct.pack("!H", 1000)))
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass


def accept_key(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()


def connect(url: str, timeout: float = 15.0) -> WebSocket:
    parts = urlsplit(url)
    secure = parts.scheme == "wss"
    host = parts.hostname or ""
    port = parts.port or (443 if secure else 80)
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    raw = socket.create_connection((host, port), timeout=timeout)
    sock = ssl.create_default_context().wrap_socket(raw, server_hostname=host) if secure else raw
    try:
        key = base64.b64encode(os.urandom(16)).decode()
        sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}\r\nUpgrade: websocket\r\n"
                      f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                      f"Sec-WebSocket-Version: 13\r\nUser-Agent: corredor-austral-ais\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk or len(buf) > 16384:
                raise WebSocketError("respuesta inválida al conectar")
            buf += chunk
        head, leftover = buf.split(b"\r\n\r\n", 1)
        lines = head.decode("latin-1").split("\r\n")
        if " 101 " not in lines[0] + " ":
            raise WebSocketError(f"el servidor no aceptó el WebSocket: {lines[0]}")
        headers = {k.strip().lower(): v.strip() for k, _, v in (ln.partition(":") for ln in lines[1:])}
        if headers.get("sec-websocket-accept") != accept_key(key):
            raise WebSocketError("respuesta de WebSocket inválida (accept)")
        return WebSocket(sock, leftover)
    except BaseException:
        sock.close()
        raise
