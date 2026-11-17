# Corredor Austral · recolector de datos v0.3

Registra clima, viento y oleaje en puntos clave del corredor hacia Tierra del Fuego, y te permite cargar a mano estados y demoras reales. Con el tiempo, esos datos son la base de un modelo para anticipar demoras.

No necesita instalar nada: solo Python 3.10 o superior.

## Estructura del proyecto

```
corredor/                  el código
├── cli.py                 comandos (run, report, status, ...)
├── config.py              lugares, carpetas y tiempos de espera: lo que se ajusta a mano
├── collect.py             una recolección completa
├── storage.py             lectura y escritura de los CSV
├── net.py                 consultas HTTP con reintentos
└── sources/
    └── open_meteo.py      fuente de clima y oleaje
data/                      los datos (ver la sección "Datos" más abajo)
├── auto/                  lo escribe el bot
├── manual/                lo cargás vos
└── legacy/auto.db         respaldo del formato viejo (SQLite)
tests/                     pruebas automáticas
scripts/migrar_a_csv.py    migración única de SQLite a CSV
docs/                      guías (GitHub Actions, guion de conversaciones)
.github/workflows/
├── collect.yml            recolección cada 30 min (no renombrar: lo usa cron-job.org)
└── tests.yml              corre las pruebas cuando cambia el código
```

## Puesta en marcha (VS Code)

1. Abrí esta carpeta en VS Code (`Archivo > Abrir carpeta`).
2. Abrí una terminal (`Terminal > Nueva terminal`).
3. Probá una recolección (los comandos se corren desde la carpeta raíz del proyecto):

```
python -m corredor run
python -m corredor report
```

Si ves datos de viento por cada punto, funciona. Si hay errores, mirá `python -m corredor report` (cuenta de errores) y revisá tu conexión.

## Dejarlo corriendo

**Gratis y sin tu PC:** seguí [docs/SETUP_GITHUB.md](docs/SETUP_GITHUB.md) (GitHub Actions con un repositorio privado).

**En tu PC**, cada 30 minutos, de forma continua:

```
python -m corredor loop --every 30
```

Para que no dependa de tu computadora, lo ideal es correrlo en un servidor chico (un VPS barato o una Raspberry Pi) con `cron`:

```
*/30 * * * * cd /ruta/a/corredor-austral && /usr/bin/python3 -m corredor run >> recolector.log 2>&1
```

## Cargar datos a mano (lo más valioso)

El clima solo no alcanza para predecir. Necesitás **qué pasó de verdad**. Cada vez que tengas un dato, cargalo:

```
python -m corredor crossing punta_delgada_bahia_azul 150 --note "cola de 20 camiones"
python -m corredor status paso_san_sebastian abierto --note "cadenas obligatorias"
python -m corredor event mar suspendido --place punta_delgada --note "viento fuerte"
python -m corredor event aire cancelado --place rio_grande --note "vuelo de carga cancelado"
```

Pedile a los choferes con los que hables que te cuenten sus demoras reales: cada una vale oro para el futuro modelo.

## Exportar y analizar

```
python -m corredor export datos.csv
```

Podés abrir el CSV en Excel o en Python (pandas) para empezar a buscar relaciones entre viento y demoras.

## BETA: web, Telegram y WhatsApp

Con los datos recolectados, la BETA estima el **riesgo de demora por viento** en cada cruce:

| Riesgo | Ráfaga actual (provisorio) |
|---|---|
| 🟢 bajo | menos de 50 km/h |
| 🟡 medio | desde 50 km/h |
| 🔴 alto | desde 70 km/h |

Para cada cruce toma la ráfaga más alta entre sus puntos: Primera Angostura usa Punta Delgada y Bahía Azul, y Punta Arenas – Porvenir usa esas dos ciudades. **No es el estado oficial de TABSA**, y así lo dicen todos los canales. Los umbrales están en `corredor/config.py` y se van a ajustar cuando tengamos el historial real de suspensiones.

```
python -m corredor web            # genera la web en _site/index.html (abrila con doble clic)
python -m corredor resumen        # muestra el mensaje que va a Telegram y WhatsApp
python -m corredor notify --force # manda ese mensaje por Telegram (si está configurado)
```

- **Web:** una sola página, pensada para el celular y señal mala. Muestra el riesgo actual, el pronóstico de 24 h, un gráfico de las últimas 24 h y los demás puntos de la ruta. Si los datos tienen más de 2 h, lo avisa.
- **Telegram:** el workflow `collect` manda un aviso cuando un cruce cambia de nivel, por ejemplo de bajo a medio. Para activarlo hay que cargar los Secrets `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` en GitHub. Sin ellos no envía nada.
- **WhatsApp:** botón "Compartir por WhatsApp" en la web, que arma el mensaje con el resumen. No tiene costo. Los avisos automáticos por WhatsApp necesitan la API de Meta, que es paga (fase 5).

## Qué falta (y cómo conseguirlo)

- **Fuentes de mar y aire:** hoy solo hay oleaje de modelo y carga manual. En las conversaciones preguntá qué datos de barcos y vuelos de carga usan o dónde los miran.
- **Estado oficial del paso y horarios del ferry:** no están automatizados. Revisá los términos de uso de cada sitio antes de hacer scraping, o buscá una fuente oficial con API. Mientras tanto, cargalo a mano con `status`.
- **Coordenadas:** son aproximadas. Verificalas en un mapa y ajustá `PLACES` en `corredor/config.py`.

## Aviso importante sobre las fuentes

La API gratuita de Open-Meteo es para **uso no comercial**. Si vas a vender un servicio basado en estos datos, vas a necesitar un plan comercial de ellos u otra fuente (por ejemplo, datos oficiales del Servicio Meteorológico Nacional). Revisá sus términos actuales antes de cobrar.

## Datos

Los datos son el activo principal del proyecto. Reglas:

- **Solo se agregan filas al final.** Nunca se borran ni se reescriben.
- **Horas en UTC** (`ts_utc`, formato `2026-11-17T20:29:16Z`). Se pasan a hora local recién al mostrarlas.
- CSV en UTF-8, separado por comas, saltos de línea LF y primera fila con los nombres de las columnas. Una celda vacía significa "sin dato".
- No abras y guardes estos archivos con Excel: puede cambiar el formato. Para analizarlos, abrí una copia o usá `python -m corredor export datos.csv`.

### Carpetas

| Carpeta | Quién escribe | Archivos |
|---|---|---|
| `data/auto/` | Solo el workflow `collect` (bot) | `weather_obs.csv`, `marine_obs.csv`, `collector_errors.csv` |
| `data/manual/` | Solo vos, con `python -m corredor status / event / crossing` | `status_obs.csv`, `events.csv`, `crossings.csv` (se crean con la primera carga) |
| `data/legacy/` | Nadie (respaldo) | `auto.db`: el formato viejo (SQLite), hasta el 17/11/2026. Todas sus filas ya están en `data/auto/` |

Como el bot y vos nunca escriben el mismo archivo, git no da conflictos.

### Columnas

#### `data/auto/weather_obs.csv`: clima (Open-Meteo)
Una fila por lugar y corrida. Todas las filas de una corrida tienen el mismo `ts_utc`.

| Columna | Unidad | Descripción |
|---|---|---|
| `ts_utc` | | Hora de la corrida |
| `place` | | `rio_grande`, `ushuaia`, `san_sebastian`, `punta_delgada`, `bahia_azul`, `porvenir`, `punta_arenas` |
| `temp_c` | °C | Temperatura a 2 m |
| `wind_kmh` | km/h | Viento medio a 10 m |
| `gust_kmh` | km/h | Ráfaga a 10 m |
| `wind_dir_deg` | grados | De dónde viene el viento (0 = norte, 90 = este) |
| `precip_mm` | mm | Precipitación |
| `forecast_gust_max_24h_kmh` | km/h | Ráfaga máxima pronosticada para las próximas 24 h |
| `source` | | `open-meteo` |

#### `data/auto/marine_obs.csv`: oleaje (Open-Meteo Marine)
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
| `where_` | Qué consulta (`weather`, `marine`; en datos viejos, `weather:<lugar>`) |
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

Corren solas en GitHub cada vez que cambia el código (workflow `tests`).

## Plan de la semana

| Día | Qué hacer |
|---|---|
| 1 | Poner a correr el recolector. Armar la lista de 10 personas a contactar |
| 2 a 6 | Hacer las conversaciones con [docs/GUION_CONVERSACIONES.md](docs/GUION_CONVERSACIONES.md) y registrarlas |
| 7 | Revisar los datos recolectados y decidir con los criterios del guion |

Mientras tanto, seguí avanzando con AutoDocs para cuidar el ingreso del mes.
