# Cambios de Corredor Austral

Una entrada por bloque de mejoras. Lo más nuevo arriba.

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
