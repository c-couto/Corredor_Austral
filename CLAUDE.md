# Corredor Austral

## Qué es
Servicio para quienes cruzan el Estrecho de Magallanes (Primera Angostura, Río Verde
y Punta Arenas–Porvenir). TABSA publica el estado del cruce *en el momento*
(https://www.tabsa.cl/estado-cruces) y lo pisa con el siguiente. Nosotros lo guardamos
cada 30 minutos y construimos encima lo que TABSA no ofrece:

1. **Estado actual**: claro, rápido, pensado para el celular.
2. **Historial y estadísticas**: cuándo se suspendió, cuánto duró, qué meses/horas son peores.
3. **Avisos**: notificar cuando un cruce pasa de NORMAL a suspendido y cuando se reanuda.
4. **Pronóstico**: estimar si va a cruzar en las próximas horas (viento/marea + historial).

## Equipo
Sabemos algo de programación: entendemos el código si lo vemos, pero no escribimos mucho.
- Explicá en español y en términos simples qué hiciste y por qué.
- Preferí soluciones simples y gratuitas a las "elegantes".
- Antes de cambios grandes (borrar archivos, cambiar el formato de los datos, agregar
  servicios pagos o que pidan tarjeta), preguntá primero.
- Nunca pongas tokens ni claves en el código: usá GitHub Secrets / variables de entorno.

## Cómo funciona hoy
- `.github/workflows/collect.yml`: workflow `collect` que lee la página de TABSA y guarda los datos.
- Se dispara cada 30 min desde cron-job.org (vía `workflow_dispatch`); el `schedule` de
  GitHub (`7,37 * * * *`) queda de respaldo porque GitHub lo saltea seguido.
- El token que usa cron-job.org vence el 17/12/2026.
- **Dónde y en qué formato se guardan los datos** (revisado el 17/11/2026):
  - **Ojo:** el código actual **no lee TABSA**. `collector.py run` solo consulta clima
    y oleaje en Open-Meteo. Todavía no se guarda ningún estado de cruce.
  - Desde el 17/11/2026 los datos se guardan en **CSV**, uno por tabla, en `data/<tabla>.csv`
    (UTF-8, saltos de línea LF, primera fila con los nombres de las columnas, celda vacía si
    no hay dato). Siempre se **agregan filas al final**: nunca se borran ni se reescriben.
    Después de cada corrida el bot (`corredor-bot`) hace un commit "datos <fecha UTC>".
  - El workflow escribe `weather_obs.csv`, `marine_obs.csv` y `collector_errors.csv`. Los
    comandos manuales (`status` / `event` / `crossing`) escriben `status_obs.csv`,
    `events.csv` y `crossings.csv`. Como son archivos distintos, git no da conflictos.
  - `data/auto.db` (SQLite, formato viejo) queda **solo como respaldo**: ya no se escribe.
    Todas sus filas (69 de clima, 36 de oleaje y 15 errores) se pasaron a los CSV con
    `migrar_a_csv.py`, que se puede volver a correr sin duplicar. Se sacó la columna `id`,
    que era solo un contador interno de SQLite.
  - Clima y oleaje se piden en **una sola consulta** a Open-Meteo para todos los lugares,
    con un timeout de 15 s y hasta 3 reintentos (esperas de 5, 10 y 20 s). Si igual falla,
    queda anotado en `collector_errors.csv` y la corrida sigue.
  - Columnas (`ts_utc` siempre en UTC, formato `2026-11-17T20:07:52Z`):
    - `weather_obs`: una fila por lugar y corrida, para 7 lugares (rio_grande,
      ushuaia, san_sebastian, punta_delgada, bahia_azul, porvenir, punta_arenas).
      Guarda temp_c, wind_kmh, gust_kmh, wind_dir_deg, precip_mm,
      forecast_gust_max_24h_kmh y source.
    - `marine_obs`: oleaje en punta_delgada, bahia_azul y ushuaia. Guarda
      wave_height_m, wave_period_s, wave_dir_deg y source.
    - `status_obs`, `events`, `crossings`: carga manual (hoy vacías).
    - `collector_errors`: fallas de cada consulta (ts_utc, where_, error).
  - Todas las filas de una misma corrida comparten el mismo `ts_utc`.
  - Ejemplo de `weather_obs.csv`:
    ```
    ts_utc,place,temp_c,wind_kmh,gust_kmh,wind_dir_deg,precip_mm,forecast_gust_max_24h_kmh,source
    2026-11-17T20:29:16Z,bahia_azul,17.0,34.7,56.5,34.0,0.0,56.5,open-meteo
    ```
  - Ver los datos: `git pull` y después `python collector.py report`, o
    `python collector.py export datos.csv`.

## Reglas sobre los datos
- Los datos recolectados son el activo principal del proyecto: **nunca** borrar ni
  reescribir el historial existente. Si hay que cambiar el formato, migrar sin perder filas.
- Guardar siempre la hora en UTC y convertir a hora local solo al mostrar
  (Argentina UTC-3, Chile según temporada).
- Registrar los **cambios de estado** (de NORMAL a SUSPENDIDO y viceversa) con su hora,
  además de cada muestra, para poder medir duraciones.

## Arquitectura elegida (simple y gratis)
- **Recolección**: GitHub Actions (ya existe).
- **Datos**: archivos en el repo (CSV/JSON) mientras alcance; migrar a una base
  (p. ej. Supabase) solo si se vuelve necesario.
- **Web**: sitio estático que se arma a partir de los datos y se publica en GitHub Pages
  (o Cloudflare Pages). Mobile-first, en español, carga rápida con señal mala de ruta.
- **Avisos**: el mismo workflow detecta el cambio de estado y manda el mensaje.
  Primero Telegram (gratis y simple); después WhatsApp (Cloud API de Meta, requiere
  verificar la cuenta de negocio y tiene costo por conversación).
- **Pronóstico**: Open-Meteo (gratis, sin API key) para viento en Primera Angostura.
  Arrancar con reglas simples (umbrales de viento) y recién con varias semanas de
  historial pasar a un modelo.

## Hoja de ruta
- [ ] Fase 0 – Revisar el repo, documentar el formato de datos y completar este archivo.
- [ ] Fase 1 – Web: estado actual + historial básico, publicada en GitHub Pages.
- [ ] Fase 2 – Avisos por Telegram al cambiar el estado.
- [ ] Fase 3 – Estadísticas (duración de suspensiones, peores meses/horas).
- [ ] Fase 4 – Pronóstico con viento de Open-Meteo.
- [ ] Fase 5 – WhatsApp.
