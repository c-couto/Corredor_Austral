# Cambios de Corredor Austral

Una entrada por bloque de mejoras. Lo más nuevo arriba.

## Botón "Ver ferris en vivo" abierto como archivo (2026-11-25)
- Si la página principal se abre como archivo (file://) en vez de desde el sitio publicado, el botón
  llevaba a una pantalla que no puede cargar. Ahora, en ese caso, va directo a
  https://c-couto.github.io/Corredor_Austral/en-vivo/. En el sitio publicado no cambia nada.

## Río Verde: regla base en 85 km/h (2026-11-25)
- La regla base de Río Verde pasa de 70 a **85 km/h = 50 %** (`PRIOR_BY_ROUTE` en `config.py`).
  Motivo: el 24/11 operó normal con ráfagas de hasta 81 km/h y la regla de 70 daba 27 falsas alarmas.
  Es un piso (lo mínimo que se sabe que aguanta), no una medición: no hay temporales de Río Verde
  para calibrarlo. Primera Angostura y Porvenir siguen en 70.

## Bloque 1 — Modelo honesto (2026-11-25)
- **El modelo ya no se "aprueba" con los mismos datos con los que aprendió.** Para pasar de regla base
  a "aprendido" tiene que ganarle a la regla base en el 20 % más reciente de los datos, y esa prueba
  tiene que incluir al menos 2 temporales distintos (no 2 lecturas del mismo temporal).
  Antes, con pocos datos, se medía con los mismos datos y casi siempre parecía bueno.
- La web ya no dice "acierta el orden en el 98 % de los casos". Ahora dice, por ejemplo,
  "Regla base (hacen falta 8 temporales; hay 2)" o "Aprendido con 9 temporales; probado con datos
  nuevos: X % menos error que la regla base".
- La regla base ahora es **configurable por cruce** (`PRIOR_BY_ROUTE` en `config.py`). Los valores
  son los mismos de siempre (70 km/h = 50 %) para los tres cruces: no cambia ninguna predicción.
- Sin cambios en los CSV ni en `data/`.
