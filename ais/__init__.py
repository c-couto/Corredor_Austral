"""Mapa en vivo (premium), etapa 1: medir la cobertura AIS de los ferris en el Estrecho.

Módulos:
  barcos.py     ferris conocidos (MMSI), zonas y terminales
  websocket.py  cliente WebSocket mínimo (solo biblioteca estándar)
  datos.py      CSV propios en data/ais/ (solo se agregan filas, hora en UTC)
  sondeo.py     escucha aisstream.io unos minutos y guarda las posiciones
  reporte.py    cobertura por barco, cruces detectados y mapa HTML

Separado a propósito de `corredor/`: no toca la recolección, el modelo ni sus datos.
"""
