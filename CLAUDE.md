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

## Cómo funciona hoy (v0.4, 17/11/2026)
- `.github/workflows/collect.yml`: workflow `collect`. En cada corrida (un solo trabajo, ~1 min):
  clima de 8 puntos + pronóstico horario, estado de TABSA, reentrenamiento diario del modelo,
  commit de `data/auto/` y `data/model/`, y aviso por Telegram si algo cambió.
- Se dispara cada 30 min desde cron-job.org (vía `workflow_dispatch`); el `schedule` de
  GitHub (`7,37 * * * *`) queda de respaldo porque GitHub lo saltea seguido.
  (Al 17/11 había muchas menos corridas que las esperadas: revisar cron-job.org.)
- El token que usa cron-job.org vence el 17/12/2026.
- Costo: ~1.440 de los 2.000 min/mes gratis. No agregar pasos que sumen minutos sin preguntar.
- **TABSA**: la página se arma con JavaScript. Se renderiza con el Chrome/Edge que ya está en
  la máquina (`corredor/browser.py`, `--headless --dump-dom`) y se leen las tablas visibles
  (`corredor/sources/tabsa.py`). **No usar las APIs internas de TABSA** (`api-gw.tabsa.cl`, etc.):
  piden autorización y su código está ofuscado a propósito.
  Verificado el 17/11/2026 observando el tráfico de la página: el estado sale de
  `api-gw.tabsa.cl/api/cruce/cruce/suspension` y `/cruce/20/fecha/...`, ambos con Authorization. Si la página cambia, el lector
  lanza `TabsaFormatError` y queda en `collector_errors.csv` (no guarda datos dudosos).
- **Datos**: CSV, uno por tabla. El diccionario completo está en la sección "Datos" del
  `README.md`. Siempre se **agregan filas al final**.
  - `data/auto/`: lo escribe solo el bot: `weather_obs`, `marine_obs`, `tabsa_estado`,
    `tabsa_programados`, `tabsa_cambios`, `collector_errors`.
  - `data/manual/`: lo escriben solo los comandos `status` / `event` / `crossing`.
  - `data/auto/pronosticos/AAAA-MM.csv`: el pronóstico de 48 h (viento, oleaje, marea) de
    Punta Delgada y Bahía Azul tal como estaba en cada corrida. Un archivo por mes (~12 KB por corrida).
  - `data/model/modelo.json`: el modelo entrenado (se reescribe una vez por día; no es historial).
  - `data/legacy/auto.db`: formato viejo (SQLite), solo respaldo.
  - `.cache/pronostico.json`: pronóstico horario del momento, **fuera del repo**.
- **Clima**: Open-Meteo (solo uso NO comercial) por defecto. Con la variable
  `CORREDOR_MET_CONTACT` pasa a MET Norway (uso comercial permitido) y deja de usar Open-Meteo.
  **Antes de cobrar por el servicio hay que activar MET Norway.**
- **Modelo** (`corredor/model.py`): regresión logística en Python puro sobre ráfaga, viento y
  dirección, con el estado de TABSA como etiqueta. Usa una regla base hasta tener
  `MODEL_MIN_SAMPLES` muestras y `MODEL_MIN_POSITIVES` suspensiones, y el modelo aprendido
  solo la reemplaza si tiene mejor puntaje de Brier en el 20 % más reciente de los datos.
- Ver los datos: `git pull` y después `python -m corredor web` / `resumen` / `report`.

## Estructura del código
- `corredor/` (paquete Python, solo biblioteca estándar, Python ≥ 3.10). Se corre con
  `python -m corredor <comando>` desde la raíz.
  - `config.py`: lugares, cruces (`ROUTES`), umbrales, planificador, links. Lo privado llega por
    variables de entorno.
  - `collect.py`: una recolección y el registro de cambios de estado de TABSA.
  - `sources/`: `tabsa.py`, `open_meteo.py`, `met_norway.py` (mismo formato de salida).
  - `browser.py`, `net.py` (reintentos), `storage.py` (CSV), `timeutil.py` (UTC ↔ local),
    `forecast.py` (caché del pronóstico).
  - `model.py`: modelo de riesgo. `conditions.py`: situación de cada cruce, **única fuente**
    para la web, Telegram y WhatsApp. `web.py`: la web (`_site/index.html`, fuera del repo).
    `alerts.py` + `channels/telegram.py`: avisos.
- `tests/`: `unittest` (`python -m unittest -v`), 54 pruebas. Usan carpetas temporales, no
  pueden salir a internet ni abrir el navegador. `tests/fixtures/` tiene un recorte real
  de la página de TABSA.
- `docs/MODELO_NEGOCIO.md`: cómo ganar plata (Plan Flota, patrocinios), validación y riesgos.
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
- [x] Fase 0 – Revisar el repo, documentar el formato de datos y completar este archivo.
- [ ] Fase 1 – Web: estado actual + historial básico (hecha en local; falta publicarla:
      Cloudflare Pages gratis, o GitHub Pages si el repo pasa a público).
- [x] Fase 2 – Avisos por Telegram al cambiar el estado (falta cargar los Secrets).
- [ ] Fase 3 – Estadísticas: duración de suspensiones y mapa día/hora hechos; peores meses
      cuando haya historial.
- [x] Fase 4 – Pronóstico: probabilidad por hora con modelo que aprende de los datos
      (con regla base mientras no haya suficientes suspensiones).
- [ ] Fase 5 – WhatsApp (hoy: botón para compartir; la API de Meta es paga).
- [ ] Negocio – Validar el Plan Flota con 5 empresas (ver `docs/MODELO_NEGOCIO.md`).
