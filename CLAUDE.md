# Corredor Austral

## Qué es
Servicio para quienes cruzan el Estrecho de Magallanes (Primera Angostura, Río Verde
y Punta Arenas–Porvenir). TABSA publica el estado del cruce *en el momento*
(https://www.tabsa.cl/estado-cruces) y lo pisa con el siguiente. Nosotros lo guardamos
cada 30 minutos y construimos encima lo que TABSA no ofrece:

1. **Estado actual**: claro, rápido, pensado para el celular.
2. **Historial y estadísticas**: cuándo se suspendió, cuánto duró, qué días/horas son peores.
3. **Avisos**: notificar cuando un cruce pasa de NORMAL a suspendido y cuando se reanuda.
4. **Pronóstico**: probabilidad de suspensión en las próximas horas. **Lo más importante es
   que sea preciso.**

## Equipo
Sabemos algo de programación: entendemos el código si lo vemos, pero no escribimos mucho.
- Explicá en español y en términos simples qué hiciste y por qué.
- Preferí soluciones simples y gratuitas a las "elegantes".
- Antes de cambios grandes (borrar archivos, cambiar el formato de los datos, agregar
  servicios pagos o que pidan tarjeta), preguntá primero.
- Nunca pongas tokens ni claves en el código: usá GitHub Secrets / variables de entorno.
- Si una tarea es "solo diagnóstico", no cambies nada: leé, calculá y reportá.

## ⚠️ Negocio: antes de cobrar
- **Open-Meteo es solo para uso NO comercial.** Antes de cobrar (Premium o Plan Flota) hay
  que pasar a **MET Norway** (variable `CORREDOR_MET_CONTACT`) y **revisar que el modelo,
  entrenado con datos de Open-Meteo, siga funcionando con la fuente nueva**.
- **Mapas**: OpenFreeMap + MapLibre (gratis, uso comercial permitido, crédito obligatorio a
  OpenStreetMap). Nada de imágenes satelitales que prohíban el uso comercial.
- Nunca copiar datos de sitios de terceros (MarineTraffic, VesselFinder…): sus condiciones
  lo prohíben. Con los servicios gratuitos no hay cobertura AIS en la zona; las opciones son
  satélite (pago) o una antena propia (plan B).

## Cómo funciona hoy (v0.4.0, 24/11/2026)
- **Recolección** (`.github/workflows/collect.yml`, un trabajo de ~1 min, límite 6 min):
  estado de TABSA, clima de 8 puntos + pronóstico horario, oleaje, reentrenamiento diario del
  modelo (00:01 UTC), commit de `data/auto/` y `data/model/`, y aviso por Telegram.
  - La dispara **cron-job.org a los :05 y :35** (vía `workflow_dispatch`). El `schedule` de
    GitHub (`20,50 * * * *`) es solo respaldo: GitHub lo saltea o lo atrasa seguido; está a
    mitad de camino para no duplicar la lectura de cron-job.org.
  - El token que usa cron-job.org vence el **17/12/2026**.
  - **No renombrar `collect.yml`**: cron-job.org lo dispara por ese nombre.
- **Repo PÚBLICO**: los minutos de Actions no gastan cupo. **Si vuelve a privado, apagar
  `ais.yml` y revisar el consumo** (el cupo gratis es de 2.000 min/mes).
- **TABSA**: la página se arma con JavaScript. Se renderiza con el Chrome/Edge de la máquina
  (`corredor/browser.py`) y se leen las tablas visibles (`corredor/sources/tabsa.py`).
  **No usar las APIs internas de TABSA** (`api-gw.tabsa.cl`): piden autorización y su código
  está ofuscado a propósito. Si la página cambia, el lector lanza `TabsaFormatError` y queda
  en `collector_errors.csv`. Los zarpes de otras rutas (Puerto Williams, Natales) se guardan
  pero se filtran fuera de Punta Arenas–Porvenir (`model.is_route_sailing`).
- **Clima**: Open-Meteo por defecto. Los errores son **timeouts al conectar con Open-Meteo**
  (el "handshake" no termina en 15 s), casi siempre a los :02/:32 (congestión de las horas en
  punto y y media). El clima de Open-Meteo se intenta 3 veces con 1 min entre intentos
  (`WEATHER_RETRY_WAITS_S`); lo demás usa `RETRY_WAITS_S` (5, 10 y 20 s). **TABSA se lee
  primero**, así que si el clima falla o tarda, la corrida sigue y TABSA ya quedó guardado.
- **Modelo** (`corredor/model.py`): regresión logística en Python puro (ráfaga, viento,
  dirección), con el estado de TABSA como etiqueta. Usa la **regla base** (equivale a un umbral
  de 70 km/h de ráfaga) hasta tener `MODEL_MIN_SAMPLES`=60 muestras y `MODEL_MIN_POSITIVES`=8
  suspensiones; el aprendido solo la reemplaza si tiene mejor Brier en el 20 % más reciente.
  Al 24/11 los 3 cruces usan la regla base.
- **Evaluación** (`python -m corredor.evaluacion`): compara lo que predijimos con lo que hizo
  TABSA, en el momento y con 3/12/24 h de anticipación, con el modelo vigente en cada momento.
  Solo lee datos.
- **Web** publicada en **GitHub Pages**: https://c-couto.github.io/Corredor_Austral/
  (`.github/workflows/pages.yml`: se regenera al terminar cada `collect`; no hace commits).
  Lleva el cartel "Prototipo – versión preliminar". `netlify.toml` + `web/` son una demo vieja
  para Netlify, **no conectada**.
- **Pantalla "En vivo"** (`paginas/en-vivo/`, en el sitio: `en-vivo/`), marcada **demo**. Es la
  futura función **PREMIUM**.
  - Primera Angostura: ferris **simulados** con un horario aproximado (OSM: cruce de 20 min,
    servicio 08:00–24:00).
  - Punta Arenas–Porvenir: sigue los **zarpes reales publicados por TABSA**; la posición en el
    cruce es estimada.
  - Regla: **nunca mostrar ferris cruzando si TABSA dice suspendido o cancelado** (la pantalla ya
    lo respeta; el minimapa de la página principal todavía no).
- **AIS** (`ais/`, `.github/workflows/ais.yml`): escuchaba aisstream.io 10 min a los :15 y :45
  y guardaba en la **rama `datos-ais`, nunca en `main`**. Al 24/11: 127 sesiones (~21 h de
  escucha en 64 h distintas) y **0 posiciones** → aisstream no cubre la zona.
  **Apagado el 24/11/2026**: `ais.yml` quedó solo con `workflow_dispatch` (se puede correr a
  mano) y se desactivó su trabajo en cron-job.org. El código y los datos quedan. Plan B: antena
  AIS propia en Punta Delgada / Bahía Azul (~100 USD). Clave en el Secret `AISSTREAM_API_KEY`.

## Datos
CSV, uno por tabla; diccionario completo en la sección "Datos" del `README.md`.
- **Nunca** borrar ni reescribir el historial: solo se **agregan filas al final**. Si hay que
  cambiar el formato, migrar sin perder filas.
- Hora siempre en **UTC**; a hora local (UTC-3 todo el año en Magallanes y Tierra del Fuego)
  solo al mostrar.
- Registrar los **cambios de estado** con su hora (`tabsa_cambios.csv`), además de cada muestra.
- `data/auto/` lo escribe solo el bot; `data/manual/` solo los comandos `status`/`event`/`crossing`.
- `data/auto/pronosticos/AAAA-MM.csv`: pronóstico de 48 h tal como estaba en cada corrida
  (solo Punta Delgada y Bahía Azul). `data/model/modelo.json`: el modelo (se reescribe a diario).
- `data/auto/predicciones/AAAA-MM.csv`: lo que **predijimos** en cada corrida para los 3 cruces
  (ahora, +1…+36 h y cada zarpe de Porvenir), con el mismo cálculo que la web (`corredor/predicciones.py`).

## Estructura del código
- `corredor/` (solo biblioteca estándar, Python ≥ 3.10): `python -m corredor <comando>`.
  `config.py` (lugares, cruces, umbrales), `collect.py`, `sources/`, `net.py`, `storage.py`,
  `timeutil.py`, `forecast.py`, `model.py`, `evaluacion.py`, `conditions.py` (**única fuente**
  para web, Telegram y WhatsApp), `web.py`, `alerts.py` + `channels/telegram.py`.
- `ais/`: sondeo y reporte de cobertura AIS. `paginas/en-vivo/`: pantalla En vivo (JS, sin build).
- `tests/`: `python -m unittest -v`. **Todas tienen que pasar.** No salen a internet ni abren el
  navegador ni tocan los datos reales.
- `docs/MODELO_NEGOCIO.md`: Plan Flota, patrocinios, validación y riesgos.

## Lecciones del 24/11/2026 (primer temporal registrado)
- Primera Angostura se suspendió de **12:31 a 16:01** (hora local) y cerró y reabrió con casi
  el mismo viento (ráfagas de ~90 km/h). Coincidió con la **bajante fuerte de la marea**: es una
  pista para probar la marea como dato del modelo, **no una conclusión**.
- **Río Verde aguanta más viento** que la regla base (normal con ráfagas de 75–81 km/h): la regla
  base no debería ser la misma para los 3 cruces.
- **Bahía Azul y Punta Delgada caen en la misma celda de Open-Meteo**: Bahía Azul no aporta
  nada. Hay que elegir otro punto.
- Contar suspensiones por **evento**, no por lectura de 30 min, y **cada zarpe cancelado una sola
  vez**, antes de que el modelo pase a "aprendido" (hoy una suspensión de 3,5 h suma 7 lecturas).
- Falta **guardar la predicción emitida** en cada corrida para los 3 cruces: sin eso no se puede
  medir "cómo nos fue" con anticipación (salvo Primera Angostura) ni publicarlo.
- La regla base (umbral de 70 km/h) dio **muchas falsas alarmas** ese día.
- **No ajustar umbrales a mano por un solo día.**

## Hoja de ruta
Hecho:
- [x] Recolección cada 30 min (TABSA, clima, oleaje, pronósticos) y registro de cambios.
- [x] Web publicada en GitHub Pages (estado, gráfico, planificador, historial, mapa día/hora).
- [x] Avisos por Telegram al cambiar el estado (verificar que estén cargados los Secrets).
- [x] Modelo con regla base + evaluación (`corredor.evaluacion`).
- [x] Pantalla En vivo (demo) y medición de cobertura AIS.

Prioridades, en orden:
1. [x] Guardar las predicciones emitidas en cada corrida (3 cruces) — desde el 24/11/2026.
2. Contar eventos y zarpes en lugar de lecturas.
3. Reconstruir las suspensiones de años anteriores (prensa, redes de TABSA y de la Capitanía
   de Puerto de Punta Delgada): es lo único que acorta la espera para entrenar.
4. Probar la marea y la dirección del viento respecto del eje del estrecho como datos del
   modelo, cuando haya varios temporales.
5. Textos de la web: ventanas "16:00–16:00" sin día de fin, "ahora" contra pronóstico,
   minimapa que respete a TABSA.
6. Pasar a MET Norway antes de cobrar.

Después: WhatsApp (la API de Meta es paga) y validar el Plan Flota con 5 empresas.
