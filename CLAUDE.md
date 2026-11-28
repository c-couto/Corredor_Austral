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
- Forma de trabajo: **un cambio por rama**, chico, con pruebas nuevas, todas las pruebas
  pasando, una entrada en `CHANGELOG.md` y el OK del equipo antes del merge.
- También revisamos el repo desde Claude en claude.ai (solo lectura): ahí se analiza y se
  preparan los pedidos; los cambios se hacen acá, en una rama.

## ⚠️ Negocio: antes de cobrar
- **Open-Meteo es solo para uso NO comercial.** Antes de cobrar (Premium o Plan Flota) hay
  que pasar a **MET Norway** (variable `CORREDOR_MET_CONTACT`) y **revisar que el modelo,
  entrenado con datos de Open-Meteo, siga funcionando con la fuente nueva**.
- **Mapas**: OpenFreeMap + MapLibre (gratis, uso comercial permitido, crédito obligatorio a
  OpenStreetMap). Nada de imágenes satelitales que prohíban el uso comercial.
- Nunca copiar datos de sitios de terceros (MarineTraffic, VesselFinder…): sus condiciones
  lo prohíben. Con los servicios gratuitos no hay cobertura AIS en la zona; las opciones son
  satélite (pago) o una antena propia (plan B).

## Cómo funciona hoy (v0.4.0, actualizado 27/11/2026)
- **Recolección** (`.github/workflows/collect.yml`, un trabajo de ~1 min, límite 6 min):
  estado de TABSA, clima de 8 puntos + pronóstico horario, oleaje, reentrenamiento diario del
  modelo (00:01 UTC), commit de `data/auto/` y `data/model/`, y aviso por Telegram.
  - La dispara **cron-job.org a los :05 y :35** (vía `workflow_dispatch`). El `schedule` de
    GitHub (`20,50 * * * *`) es solo respaldo: GitHub lo saltea o lo atrasa seguido; está a
    mitad de camino para no duplicar la lectura de cron-job.org.
  - El token que usa cron-job.org vence el **17/12/2026**. **Renovarlo antes**: si vence, se
    corta la recolección y se pierde historial que no se puede recuperar.
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
  dirección), con el estado de TABSA como etiqueta.
  - Las suspensiones se cuentan por **evento**: un temporal = 1 (aunque dure 7 lecturas) y cada
    zarpe cancelado = 1 (`model.events_for`).
  - Usa la **regla base** hasta tener `MODEL_MIN_POSITIVES`=8 suspensiones distintas y
    `MODEL_MIN_SAMPLES`=60 muestras. El aprendido solo la reemplaza si le gana (Brier) en el
    **20 % más reciente**, que no usó para aprender, y esa prueba tiene que incluir **al menos 2
    temporales distintos**. **Nunca** se aprueba con los mismos datos con los que aprendió.
  - **Regla base por cruce** (`PRIOR_BY_ROUTE` en `config.py`; ráfaga en km/h = 50 %):
    - Primera Angostura: **94** (rojo) / amarillo desde **79**. **PROVISIONAL**: sale de solo 2
      temporales (24/11). Se revisa al tener 8.
    - Punta Arenas–Porvenir: **70**.
    - Río Verde: **95** (amarillo desde 75; antes 85). Es un piso (operó normal con 88 km/h en
      horario de servicio el 26/11), no una medición.
  - Al 27/11 los 3 cruces usan la regla base (temporales/zarpes: PA 2, Porvenir 6, Río Verde 1).
  - Se reentrena todos los días a las 00:01 UTC (21:01 hora local).
- **Evaluación** (`python -m corredor.evaluacion`): compara lo que predijimos con lo que hizo
  TABSA, en el momento y con 3/12/24 h de anticipación. Solo lee datos. Con anticipación usa `predicciones/` (lo que se predijo de verdad, los 3 cruces, desde el 24/11); `--desde AAAA-MM-DD` mide solo con la regla vigente.
- **Web — "Cómo nos fue"** (Bloque 2): predicciones con 3/12/24 h contra lo que hizo TABSA, por
  cruce y por día, con errores incluidos.
- **Web** publicada en **GitHub Pages**: https://c-couto.github.io/Corredor_Austral/
  (`.github/workflows/pages.yml`: se regenera al terminar cada `collect`; no hace commits).
  Lleva el cartel "Prototipo – versión preliminar". `netlify.toml` + `web/` son una demo vieja
  para Netlify, **no conectada**.
  - `python -m corredor web` arma la web con los datos de tu carpeta `data/`, que se queda vieja
    (el recolector sube datos a GitHub y no se bajan solos). Para verla con lo último:
    `python -m corredor web --fresco` (no toca tu `data/` ni tu rama).
- **Pantalla "En vivo"** (`paginas/en-vivo/`, en el sitio: `en-vivo/`), marcada **demo**. Es la
  futura función **PREMIUM**.
  - Primera Angostura: solo **ferris reales de TABSA**, cada uno con su color (Pionero naranja,
    Kawéskar turquesa). La posición y los tiempos son **estimados** y así se marcan (no hay AIS).
  - Punta Arenas–Porvenir y Río Verde: siguen los **horarios y zarpes publicados por TABSA**; la
    posición en el cruce es estimada.
  - Si se abre como archivo (`file://`), redirige a la versión publicada.
  - Regla: **nunca mostrar ferris cruzando si TABSA dice suspendido o cancelado** (la pantalla lo
    respeta; **verificar** el minimapa de la página principal).
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
  Un zarpe de Porvenir puede pasar NORMAL → SUSPENDIDO → CANCELADO (pasó el 26/11): cuenta
  como **una** suspensión.
- `data/auto/` lo escribe solo el bot; `data/manual/` solo los comandos `status`/`event`/`crossing`.
- `data/auto/pronosticos/AAAA-MM.csv`: pronóstico de 48 h tal como estaba en cada corrida
  (solo Punta Delgada y Bahía Azul; se guardan 48 h aunque el pronóstico en memoria llega a 96 h, que usa la sección del camión). `data/model/modelo.json`: el modelo (se reescribe a diario).
- `data/auto/predicciones/AAAA-MM.csv`: lo que **predijimos** en cada corrida para los 3 cruces
  (ahora, +1…+36 h y cada zarpe de Porvenir), con el mismo cálculo que la web (`corredor/predicciones.py`).

## Estructura del código
- `corredor/` (solo biblioteca estándar, Python ≥ 3.10): `python -m corredor <comando>`.
  `config.py` (lugares, cruces, umbrales), `collect.py`, `sources/`, `net.py`, `storage.py`,
  `timeutil.py`, `forecast.py`, `model.py`, `evaluacion.py`, `resultados.py` ("Cómo nos fue"),
  `conditions.py` (**única fuente** para web, Telegram y WhatsApp), `web.py`, `alerts.py` +
  `channels/telegram.py`.
- `ais/`: sondeo y reporte de cobertura AIS. `paginas/en-vivo/`: pantalla En vivo (JS, sin build).
- `tests/`: `python -m unittest -v` (153 al 27/11). **Todas tienen que pasar.** No salen a
  internet ni abren el navegador ni tocan los datos reales.
- `CHANGELOG.md`: una entrada por cambio, lo más nuevo arriba.
- `docs/MODELO_NEGOCIO.md`: Plan Flota, patrocinios, validación y riesgos.

## Lecciones (24 al 26/11/2026)

**Temporales registrados hasta el 27/11:**
- Río Verde: lunes 23/11, 11:01 → 12:01 (ráfaga de 55 km/h: no fue por viento fuerte).
- Primera Angostura: martes 24/11, 12:31 → 16:01 (91 km/h) y 19:05 → 21:05 (83 km/h).
- Porvenir, martes 24/11: cancelados los zarpes de 09:00, 15:00 y 18:00.
- Porvenir, jueves 26/11: cancelados los zarpes de 09:00 (antes pasó por SUSPENDIDO), 15:00 y
  18:00. El sistema daba 64 % en el momento.
- Jueves 26/11: Primera Angostura y Río Verde **no** se suspendieron, aunque el pronóstico daba
  ráfagas de 90–100 km/h en Río Verde.

**Del 26/11 y de la evaluación del 27/11:**
- **Río Verde**, aun con la regla en 85, dio 20 falsas alarmas rojas y predice peor que "decir
  siempre el promedio" (Brier 0,051 contra 0,005). Puede que Open-Meteo exagere el viento ahí o
  que el punto elegido no sea representativo: revisarlo antes de bajar o subir el umbral.
  (El 27/11 se subió a 95; siguen 7 falsas alarmas rojas, con ráfagas de hasta 104 km/h y el
  cruce normal: eso apunta más a revisar el punto de Open-Meteo que al umbral.)
- **Primera Angostura con 94/79**: 0 falsas alarmas rojas, pero ninguna de las 11 lecturas
  suspendidas llegó a rojo (≥50 %). Solo se detectan en amarillo (9 de 11 lecturas ≥20 %). Es el
  costo de haberla ajustado con 2 temporales: **no ajustar más a mano**; esperar a 8 y que decida
  la evaluación.

**Del 24/11 (primer temporal):**
- Primera Angostura se suspendió de **12:31 a 16:01** (hora local) y cerró y reabrió con casi
  el mismo viento (ráfagas de ~90 km/h). Coincidió con la **bajante fuerte de la marea**: es una
  pista para probar la marea como dato del modelo, **no una conclusión**.
- **Río Verde aguanta más viento** que la regla de 70 (normal con ráfagas de 75–81 km/h) →
  regla base por cruce (hecho).
- **Bahía Azul y Punta Delgada caen en la misma celda de Open-Meteo**: Bahía Azul no aporta
  nada. Hay que elegir otro punto (pendiente, Bloque 3).
- Un modelo que se evaluó con los mismos datos con los que aprendió pasó a "aprendido" con 2
  temporales y mostraba "98 % de acierto" → corregido (Bloque 1).
- **No ajustar umbrales a mano por uno o dos días.**

## Hoja de ruta
Hecho:
- [x] Recolección cada 30 min (TABSA, clima, oleaje, pronósticos) y registro de cambios.
- [x] Web publicada en GitHub Pages (estado, gráfico, planificador, historial, mapa día/hora).
- [x] Avisos por Telegram al cambiar el estado (verificar que estén cargados los Secrets).
- [x] Modelo con regla base + evaluación (`corredor.evaluacion`).
- [x] Pantalla En vivo (demo) y medición de cobertura AIS (AIS apagado: sin cobertura).
- [x] Guardar las predicciones emitidas en cada corrida (3 cruces), desde el 24/11.
- [x] Contar suspensiones por temporal y por zarpe, no por lectura.
- [x] Bloque 1: modelo honesto (prueba con datos nuevos y 2 temporales) y regla base por cruce.
- [x] Bloque 2: sección "Cómo nos fue".
- [x] Ventanas con día de fin ("hoy 18:00 → mañana 21:00").

Prioridades, en orden:
1. **Renovar el token de cron-job.org antes del 17/12/2026.**
2. ~~`corredor.evaluacion` con `predicciones/`~~ (hecho).
3. Bloque 3, modelo en sombra: marea y dirección del viento respecto del eje de cada cruce
   (se evalúa pero no se muestra) + un punto nuevo para Bahía Azul, en otra celda de
   Open-Meteo, sin borrar el viejo. Revisar también por qué Río Verde da tantas falsas
   alarmas.
4. Bloque 4, salud del sistema: comando `salud`, aviso al equipo por Telegram (chat aparte)
   si fallan TABSA o el clima o si se acerca el vencimiento del token, y cartel "Datos
   atrasados" en la web.
5. Bloque 5, web profesional: contraste AA, un solo número por dato (encabezado contra
   tarjeta), % principal de Porvenir = próximo zarpe, minimapa que respete a TABSA, versión
   0.5.0 en el pie, prueba en celular y con 3G lenta.
6. Reconstruir las suspensiones de años anteriores (prensa, redes de TABSA y de la Capitanía
   de Puerto de Punta Delgada): es lo único que acorta la espera para entrenar.
7. Pasar a MET Norway antes de cobrar.

Después: WhatsApp (la API de Meta es paga) y validar el Plan Flota con 5 empresas.
