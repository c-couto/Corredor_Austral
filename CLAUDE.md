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
  - **Ojo:** el código actual **no lee TABSA**. `python -m corredor run` solo consulta
    clima y oleaje en Open-Meteo. Todavía no se guarda ningún estado de cruce.
  - **CSV, uno por tabla.** El diccionario completo (columnas y unidades) está en
    la sección "Datos" del `README.md`. Siempre se **agregan filas al final**: nunca se borran ni se reescriben.
    - `data/auto/`: lo escribe solo el workflow (`weather_obs.csv`, `marine_obs.csv`,
      `collector_errors.csv`). Después de cada corrida el bot (`corredor-bot`) hace un
      commit "datos <fecha UTC>".
    - `data/manual/`: lo escriben solo los comandos `status` / `event` / `crossing`.
    - `data/legacy/auto.db`: el formato viejo (SQLite), solo como respaldo. Sus filas se
      pasaron a `data/auto/` con `scripts/migrar_a_csv.py`, que se puede volver a correr
      sin duplicar. Se sacó la columna `id` de SQLite.
  - Clima y oleaje se piden en **una sola consulta** a Open-Meteo para todos los lugares,
    con un timeout de 15 s y hasta 3 reintentos (esperas de 5, 10 y 20 s). Si igual falla,
    queda anotado en `collector_errors.csv` y la corrida sigue.
  - Ejemplo de `data/auto/weather_obs.csv`:
    ```
    ts_utc,place,temp_c,wind_kmh,gust_kmh,wind_dir_deg,precip_mm,forecast_gust_max_24h_kmh,source
    2026-11-17T20:29:16Z,bahia_azul,17.0,34.7,56.5,34.0,0.0,56.5,open-meteo
    ```
  - Ver los datos: `git pull` y después `python -m corredor report`, o
    `python -m corredor export datos.csv`.

## Estructura del código
- `corredor/` (paquete Python, solo biblioteca estándar, Python ≥ 3.10). Se corre con
  `python -m corredor <comando>` desde la raíz.
  - `config.py`: lugares, carpetas y parámetros de red.
  - `storage.py`: tablas (`Table`), y las funciones `append_rows` / `read_rows`.
  - `net.py`: `get_json` con timeout y reintentos.
  - `sources/`: un módulo por fuente externa (`open_meteo.py`; el lector de TABSA va acá).
  - `collect.py`: una recolección. `cli.py`: los comandos.
  - BETA: `conditions.py` calcula el riesgo por viento de cada cruce y es la única fuente
    para todos los canales. `web.py` genera `_site/index.html`, que no se guarda en el repo.
    `alerts.py` detecta cambios de nivel y avisa por `channels/telegram.py`, que toma el
    token de los Secrets. WhatsApp por ahora es solo un botón para compartir en la web.
- `tests/`: pruebas con `unittest` (`python -m unittest -v`). Corren en GitHub con el
  workflow `tests` cuando cambia el código. Nunca escriben en `data/`.
- **No renombrar `.github/workflows/collect.yml`**: cron-job.org lo dispara por ese nombre.

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
