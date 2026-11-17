# Corredor Austral · el semáforo del Estrecho · v0.4

Estado oficial de los cruces del Estrecho de Magallanes (**Primera Angostura**, **Punta Arenas ↔ Porvenir** y **Río Verde**) + la **probabilidad de que se suspendan** en las próximas horas, aprendida de nuestro propio historial, y **la mejor hora para salir**.

TABSA publica el estado del momento y lo borra con el siguiente. Corredor Austral lo guarda cada 30 minutos junto con el viento, aprende con cuánto viento se suspende cada cruce y lo muestra en una web pensada para el celular, con avisos por Telegram y para compartir por WhatsApp.

No necesita instalar nada: solo Python 3.10 o superior y Chrome o Edge (para leer la página de TABSA). Costo: cero (ver [docs/MODELO_NEGOCIO.md](docs/MODELO_NEGOCIO.md)).

## Uso rápido

En la terminal de VS Code, desde la carpeta del proyecto:

```
git pull                           # trae los últimos datos del bot
python -m corredor web             # genera la web → abrí _site/index.html con doble clic
python -m corredor resumen         # el mensaje para Telegram / WhatsApp
```

Todos los comandos:

| Comando | Qué hace |
|---|---|
| `run` | Una recolección: clima + pronóstico horario + estado de TABSA |
| `tabsa` | Lee TABSA y lo muestra, sin guardar (para probar) |
| `suspensiones` | Suspensiones registradas: inicio, fin (UTC) y duración |
| `train` | Entrena el modelo de riesgo con los datos guardados (`--if-stale`: solo si no se entrenó hoy) |
| `web` | Genera la web en `_site/index.html` |
| `resumen` | Muestra el resumen que va a Telegram y WhatsApp |
| `notify` | Avisa por Telegram si algo cambió (`--force`: manda el resumen igual) |
| `report` / `export datos.csv` | Últimos datos / todo en un CSV |
| `status` / `event` / `crossing` | Carga manual (ver abajo) |

## Cómo funciona

1. **Recolección** (workflow `collect`, cada 30 min, gratis): clima de 8 puntos con pronóstico hora por hora, y el estado oficial de TABSA. La página de TABSA se arma con JavaScript, así que se abre con el Chrome que ya trae el servidor (sin ventana) y se leen las tablas visibles, igual que una persona. No se usan las APIs internas de TABSA.
2. **Cambios de estado:** cada vez que un cruce o una salida cambia (NORMAL → SUSPENDIDO y vuelta) queda registrado con su hora. Así se miden las duraciones.
3. **Modelo** (una vez por día, segundos): cada lectura de TABSA es un ejemplo "este viento → este estado". Una regresión logística aprende la **probabilidad de que el cruce no esté normal** según ráfaga, viento y dirección. Mientras no haya suficientes suspensiones registradas usa una **regla base** (50 km/h de ráfaga → 20 %, 70 km/h → 50 %), y el modelo aprendido solo la reemplaza si **predice mejor en datos que no vio**.
4. **Canales:** la web, Telegram y WhatsApp muestran lo mismo (sale de `corredor/conditions.py`).

**¿Qué significa el %?** Es la **probabilidad de que TABSA suspenda el cruce** (o un zarpe) por viento. No mide el peligro de cruzar: si el cruce opera, es seguro. Se muestra siempre junto al estado oficial y con una frase fácil:

| Frase | Probabilidad de suspensión |
|---|---|
| 🟢 Se espera cruce normal | menos de 20 % |
| 🟡 Atención: puede suspenderse | desde 20 % |
| 🔴 Probable suspensión | desde 50 % |

Si TABSA ya publicó una suspensión, eso manda: la frase pasa a "Suspendido según TABSA".

### La web
- **Encabezado:** bandera de Tierra del Fuego, reloj en vivo de la región (UTC-3) y clima actual de Primera Angostura, Punta Arenas, Porvenir, Río Grande y Ushuaia (temperatura, cielo y viento).
- **Por cruce:** estado oficial, frase fácil, probabilidad de suspensión, viento con su dirección y un **gráfico de ráfagas** (últimas 24 h medidas + próximas 48 h pronosticadas) sobre zonas de color que muestran desde cuánto viento sube la probabilidad. Marca "ahora" y los períodos en que TABSA tuvo el cruce suspendido. Debajo, **en qué horario podría suspenderse** ("Puede suspenderse jueves 13:00–19:00").
- **¿A qué hora salgo?:** elegís el origen (Río Gallegos, Punta Arenas, Río Grande, Ushuaia) y te muestra la probabilidad de suspensión a la hora en que llegarías a Primera Angostura y la mejor salida. Las horas de manejo están en `PLANNER_ORIGINS` (`corredor/config.py`).
- **Próximos zarpes Punta Arenas ↔ Porvenir:** estado TABSA + probabilidad de suspensión de cada zarpe.
- **Historial de suspensiones** con su duración y, con una semana de datos, un mapa de días y horas críticas.
- **Cómo calculamos la probabilidad:** si cada cruce usa el modelo aprendido o la regla base, y por qué.
- **Plan Flota y "Dónde esperar":** espacios comerciales (ver el modelo de negocio).

### Telegram y WhatsApp
- **Telegram:** el workflow avisa cuando TABSA cambia un estado (lo más valioso) y cuando cambia el nivel de riesgo. Se activa con los Secrets `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` (crear el bot con @BotFather y agregarlo como administrador del canal). Sin ellos no envía nada.
- **WhatsApp:** botón "Compartir por WhatsApp" en la web, sin costo. Los avisos automáticos por WhatsApp necesitan la API de Meta (paga): fase 5.

### Configuración (GitHub → Settings → Secrets and variables → Actions)
| Nombre | Tipo | Para qué |
|---|---|---|
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Secret | Avisos por Telegram |
| `CORREDOR_MET_CONTACT` | Variable | Un mail o la web del proyecto. Pasa el clima a **MET Norway** (permite uso comercial). **Obligatorio antes de cobrar** |
| `CORREDOR_SITE_URL`, `CORREDOR_TELEGRAM_URL` | Variable | Links en los mensajes y en la web, cuando estén publicados |
| `CORREDOR_CONTACT_URL` | Variable | Contacto comercial: activa los botones del Plan Flota y "Dónde esperar" |

## Estructura del proyecto

```
corredor/
├── cli.py                 comandos
├── config.py              lugares, cruces, umbrales, planificador: lo que se ajusta a mano
├── collect.py             una recolección (clima + TABSA) y registro de cambios de estado
├── browser.py             abre páginas con Chrome/Edge sin ventana
├── sources/
│   ├── tabsa.py           lee el estado oficial de TABSA
│   ├── open_meteo.py      clima y oleaje (solo uso no comercial)
│   └── met_norway.py      clima con uso comercial permitido
├── forecast.py            pronóstico horario del momento (en .cache/, fuera del repo)
├── model.py               modelo de riesgo que aprende de los datos
├── conditions.py          situación de cada cruce: única fuente para web y avisos
├── web.py                 la web (un solo HTML, sin librerías)
├── alerts.py              qué cambió y el aviso
├── channels/telegram.py   envío por Telegram
├── storage.py · net.py · timeutil.py
data/                      los datos (ver "Datos")
├── auto/                  lo escribe el bot
├── manual/                lo cargás vos
├── model/modelo.json      el modelo entrenado
└── legacy/auto.db         respaldo del formato viejo (SQLite)
tests/                     pruebas automáticas (python -m unittest -v)
scripts/                   migración única de SQLite a CSV
docs/                      GitHub Actions, guion de conversaciones, modelo de negocio
.github/workflows/
├── collect.yml            recolección cada 30 min (no renombrar: lo usa cron-job.org)
└── tests.yml              corre las pruebas cuando cambia el código
```

## Dejarlo corriendo

**Gratis y sin tu PC:** GitHub Actions, ver [docs/SETUP_GITHUB.md](docs/SETUP_GITHUB.md). **En tu PC:** `python -m corredor loop --every 30`.

## Cargar datos a mano

Lo que vivieron de verdad los choferes también sirve:

```
python -m corredor crossing punta_delgada_bahia_azul 150 --note "cola de 20 camiones"
python -m corredor status paso_san_sebastian abierto --note "cadenas obligatorias"
python -m corredor event mar suspendido --place punta_delgada --note "viento fuerte"
```

## Fuentes y condiciones de uso

- **TABSA** (`tabsa.cl/estado-cruces`): sitio público, su `robots.txt` permite el acceso. Se lee una vez cada 30 minutos, se cita siempre la fuente y se aclara que no somos canal oficial.
- **Open-Meteo:** gratis solo para uso **no comercial**.
- **MET Norway:** gratis con uso comercial (CC BY 4.0, citando "MET Norway"). Se activa con `CORREDOR_MET_CONTACT`. En ese modo no se usa Open-Meteo (tampoco el oleaje).

## Datos

Los datos son el activo principal del proyecto. Reglas:

- **Solo se agregan filas al final.** Nunca se borran ni se reescriben.
- **Horas en UTC** (`ts_utc`, formato `2026-11-17T20:29:16Z`). Se pasan a hora local (UTC-3) recién al mostrarlas.
- CSV en UTF-8, separado por comas, saltos de línea LF y primera fila con los nombres de las columnas. Una celda vacía significa "sin dato".
- Todas las filas de una corrida (clima y TABSA) llevan el mismo `ts_utc`: así se cruzan para entrenar el modelo.
- No abras y guardes estos archivos con Excel: puede cambiar el formato. Para analizarlos, abrí una copia o usá `python -m corredor export datos.csv`.

### Carpetas

| Carpeta | Quién escribe | Archivos |
|---|---|---|
| `data/auto/` | Solo el workflow `collect` (bot) | `weather_obs.csv`, `marine_obs.csv`, `tabsa_estado.csv`, `tabsa_programados.csv`, `tabsa_cambios.csv`, `pronosticos/AAAA-MM.csv`, `collector_errors.csv` |
| `data/manual/` | Solo vos, con `status / event / crossing` | `status_obs.csv`, `events.csv`, `crossings.csv` (se crean con la primera carga) |
| `data/model/` | El workflow, una vez por día | `modelo.json`: el modelo entrenado y sus métricas |
| `data/legacy/` | Nadie (respaldo) | `auto.db`: formato viejo (SQLite), hasta el 17/11/2026. Todas sus filas ya están en `data/auto/` |

### Columnas

#### `data/auto/tabsa_estado.csv`: estado oficial por cruce (una fila por cruce y corrida)
| Columna | Descripción |
|---|---|
| `ts_utc` | Hora de la lectura |
| `crossing` | `primera_angostura`, `rio_verde` (el nombre de TABSA en minúsculas y sin tildes) |
| `status` | Como lo publica TABSA, en mayúsculas: `NORMAL`, `SUSPENDIDO`, ... |
| `icon` | Nombre del ícono de estado de TABSA (p. ej. `EstadoCruceEnViaje`), respaldo del texto |

#### `data/auto/tabsa_programados.csv`: salidas programadas Punta Arenas ↔ Porvenir (una fila por salida y corrida)
`ts_utc`, `date` (AAAA-MM-DD, local), `origin`, `destination`, `boarding` y `departure` (HH:MM local: embarque y zarpe), `status`, `icon`.

#### `data/auto/tabsa_cambios.csv`: cambios de estado
| Columna | Descripción |
|---|---|
| `ts_utc` | Cuándo se detectó el cambio |
| `subject` | El cruce (`primera_angostura`) o la salida (`2026-11-18 08:00 Porvenir -> Punta Arenas`) |
| `previous` | Estado anterior (vacío la primera vez que se ve un cruce) |
| `current` | Estado nuevo |

#### `data/auto/pronosticos/AAAA-MM.csv`: el pronóstico tal como estaba en cada corrida
Un archivo por mes. En cada corrida se guardan las próximas 48 h de Punta Delgada y Bahía Azul (las dos orillas de Primera Angostura). Sirve para comparar después lo que se pronosticó con lo que pasó, sin usar datos del futuro.

| Columna | Unidad | Descripción |
|---|---|---|
| `issued_utc` | | Hora de la corrida (cuándo se tenía este pronóstico); igual al `ts_utc` del resto |
| `place` | | `punta_delgada` o `bahia_azul` |
| `valid_utc` | | Hora pronosticada |
| `lead_h` | h | Horas entre `issued_utc` y `valid_utc` (negativo = la hora en curso) |
| `wind_kmh`, `gust_kmh`, `wind_dir_deg` | km/h, grados | Viento, ráfaga y de dónde viene |
| `wave_height_m`, `wave_period_s`, `wave_dir_deg` | m, s, grados | Oleaje (Open-Meteo Marine) |
| `sea_level_m` | m | Nivel del mar (marea + viento). La grilla es gruesa: sirve para la fase de la marea, no para su altura exacta |
| `source` | | Fuentes usadas |

#### `data/auto/weather_obs.csv`: clima
Una fila por lugar y corrida.

| Columna | Unidad | Descripción |
|---|---|---|
| `ts_utc` | | Hora de la corrida |
| `place` | | `rio_grande`, `ushuaia`, `san_sebastian`, `punta_delgada`, `bahia_azul`, `porvenir`, `punta_arenas`, `rio_verde` (desde el 17/11/2026) |
| `temp_c` | °C | Temperatura a 2 m |
| `wind_kmh` | km/h | Viento medio a 10 m |
| `gust_kmh` | km/h | Ráfaga a 10 m |
| `wind_dir_deg` | grados | De dónde viene el viento (0 = norte, 90 = este) |
| `precip_mm` | mm | Precipitación |
| `forecast_gust_max_24h_kmh` | km/h | Ráfaga máxima pronosticada para las próximas 24 h |
| `source` | | `open-meteo` o `met-norway` |

#### `data/auto/marine_obs.csv`: oleaje (solo con Open-Meteo)
| Columna | Unidad | Descripción |
|---|---|---|
| `ts_utc`, `place` | | Como en clima. Lugares: `punta_delgada`, `bahia_azul`, `ushuaia` |
| `wave_height_m` | m | Altura de ola |
| `wave_period_s` | s | Período de ola |
| `wave_dir_deg` | grados | De dónde viene la ola |
| `source` | | `open-meteo-marine` |

#### `data/auto/collector_errors.csv`: fallas del recolector
| Columna | Descripción |
|---|---|
| `ts_utc` | Cuándo falló |
| `where_` | Qué fuente (`weather`, `marine`, `tabsa`, `forecast`; en datos viejos, `weather:<lugar>`) |
| `error` | Mensaje (máx. 500 caracteres) |

#### `data/manual/status_obs.csv`: estados cargados a mano
`ts_utc`, `subject` (p. ej. `paso_san_sebastian`), `status` (p. ej. `abierto`), `note`, `source` (`manual`).

#### `data/manual/events.csv`: eventos
`ts_utc`, `mode` (`tierra` / `mar` / `aire`), `place`, `kind` (p. ej. `suspendido`), `note`.

#### `data/manual/crossings.csv`: demoras reales de cruce
`ts_utc`, `route` (p. ej. `punta_delgada_bahia_azul`), `delay_minutes`, `note`.

## Pruebas

```
python -m unittest -v
```

Corren solas en GitHub cada vez que cambia el código (workflow `tests`). Usan carpetas temporales y no pueden salir a internet ni abrir el navegador: nunca tocan los datos reales.

## Plan de la semana

| Día | Qué hacer |
|---|---|
| 1 | Poner a correr el recolector. Armar la lista de 10 personas a contactar |
| 2 a 6 | Hacer las conversaciones con [docs/GUION_CONVERSACIONES.md](docs/GUION_CONVERSACIONES.md) y registrarlas |
| 7 | Revisar los datos recolectados y decidir con los criterios del guion |

Mientras tanto, seguí avanzando con AutoDocs para cuidar el ingreso del mes.
