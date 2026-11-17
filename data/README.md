# Datos

Los datos son el activo principal del proyecto. Reglas:

- **Solo se agregan filas al final.** Nunca se borran ni se reescriben.
- **Horas en UTC** (`ts_utc`, formato `2026-11-17T20:29:16Z`). Se pasan a hora local recién al mostrarlas.
- CSV en UTF-8, separado por comas, saltos de línea LF y primera fila con los nombres de las columnas. Una celda vacía significa "sin dato".
- No abras y guardes estos archivos con Excel: puede cambiar el formato. Para analizarlos, abrí una copia o usá `python -m corredor export datos.csv`.

## Carpetas

| Carpeta | Quién escribe | Archivos |
|---|---|---|
| `auto/` | Solo el workflow `collect` (bot) | `weather_obs.csv`, `marine_obs.csv`, `collector_errors.csv` |
| `manual/` | Solo vos, con `python -m corredor status / event / crossing` | `status_obs.csv`, `events.csv`, `crossings.csv` (se crean con la primera carga) |
| `legacy/` | Nadie (respaldo) | `auto.db`: el formato viejo (SQLite), hasta el 17/11/2026. Todas sus filas ya están en `auto/` |

Como el bot y vos nunca escriben el mismo archivo, git no da conflictos.

## Columnas

### `auto/weather_obs.csv`: clima (Open-Meteo)
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

### `auto/marine_obs.csv`: oleaje (Open-Meteo Marine)
| Columna | Unidad | Descripción |
|---|---|---|
| `ts_utc`, `place` | | Como en clima. Lugares: `punta_delgada`, `bahia_azul`, `ushuaia` |
| `wave_height_m` | m | Altura de ola |
| `wave_period_s` | s | Período de ola |
| `wave_dir_deg` | grados | De dónde viene la ola |
| `source` | | `open-meteo-marine` |

### `auto/collector_errors.csv`: fallas del recolector
| Columna | Descripción |
|---|---|
| `ts_utc` | Cuándo falló |
| `where_` | Qué consulta (`weather`, `marine`; en datos viejos, `weather:<lugar>`) |
| `error` | Mensaje (máx. 500 caracteres) |

### `manual/status_obs.csv`: estados cargados a mano
`ts_utc`, `subject` (p. ej. `paso_san_sebastian`), `status` (p. ej. `abierto`), `note`, `source` (`manual`).

### `manual/events.csv`: eventos
`ts_utc`, `mode` (`tierra` / `mar` / `aire`), `place`, `kind` (p. ej. `suspendido`), `note`.

### `manual/crossings.csv`: demoras reales de cruce
`ts_utc`, `route` (p. ej. `punta_delgada_bahia_azul`), `delay_minutes`, `note`.
