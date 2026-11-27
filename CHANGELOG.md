# Cambios de Corredor Austral

Una entrada por bloque de mejoras. Lo más nuevo arriba.


## Bloque 5 · Web más firme (contraste y un solo número por dato)
- **Arreglo urgente de un error del Bloque 4**: el cartel "Datos atrasados" usaba una variable con el mismo
  nombre que una función del planificador y lo rompía ("¿A qué hora salgo?" no respondía). Corregido.
- **Un solo número por dato**: el encabezado (viento y ráfagas de Primera Angostura) ahora usa la MISMA
  medición guardada que la tarjeta (antes el encabezado leía el clima "en vivo" de la API y daba 34/54 contra
  32/51). Las tarjetas aclaran "Medido hace X min" y que el gráfico mezcla lo medido con el pronóstico.
- **Contraste AA (4,5:1)**, mismo diseño: se midió con Chrome cada texto de la página. Se corrigieron el texto
  blanco sobre el botón activo celeste del planificador (1,9:1 → oscuro), el degradado del encabezado (más
  oscuro en la esquina clara) y los textos del encabezado con transparencia (reloj, "Datos de hace…", lugares).
- Pruebas nuevas (178 en total).

## Bloque 4 · Salud del sistema
- **`python -m corredor salud`**: última lectura de TABSA, edad del clima, errores de las últimas 24 h,
  corridas que faltaron y días que quedan del token de cron-job.org (vence el 17/12/2026). Solo lee.
- **Aviso al equipo** (`python -m corredor salud --avisar`, workflow nuevo `salud.yml`, cada hora): por
  Telegram a un chat aparte (Secret `TELEGRAM_TEAM_CHAT_ID`; sin él no envía y no falla) si hay 3 corridas
  seguidas sin TABSA, el clima tiene más de 90 min, o faltan 7 días o menos para el token (recuerda 1 vez
  por día). No repite el mismo aviso cada hora. No toca `collect.yml` ni cambia ningún dato.
- **Web**: cartel "Datos atrasados" si el dato más viejo (clima o TABSA) pasa de 90 min; también se
  activa en el navegador si la página queda abierta. Reemplaza al cartel anterior (2 h, solo clima).
- Pruebas nuevas: `tests/test_salud.py` (176 en total).

## Bloque 3 — Modelo en sombra (2026-11-27)
- Módulo nuevo `corredor/sombra.py`: prueba **datos candidatos** sin arriesgar nada. Suma a los de siempre
  el viento **transversal y longitudinal al cruce** (ráfaga × |sen| y × |cos| del ángulo con el eje de los
  ferris en OpenStreetMap) y, solo en Primera Angostura, la **marea** (nivel, cuánto sube o baja por hora y
  su valor absoluto, a partir del nivel del mar que ya se guarda en `pronosticos/`).
- Se evalúa dentro de `python -m corredor.evaluacion` (y solo: `python -m corredor.sombra`). Compara, en el
  20 % más reciente: regla base · el mismo modelo sin los datos nuevos · el modelo sombra, y dice si
  mejora. Usa las mismas protecciones que el modelo real (8 suspensiones distintas, prueba con al menos 2
  temporales). Hoy dice "todavía no se puede evaluar" en los tres cruces.
- **No se muestra en la web, no avisa, no cambia ninguna predicción y no escribe nada en `data/`**
  (una prueba lo verifica). No toca la recolección ni el reentrenamiento diario.
- Pista, no conclusión: con 2 temporales, en Primera Angostura la marea no se ve distinta entre
  suspendido y normal (la corriente a media marea no resulta mayor); lo que separa es el viento, casi todo
  de costado al cruce (eje 158°). Se vuelve a mirar al tener 8 temporales.
- Script nuevo `scripts/comparar_puntos_open_meteo.py` (solo lee): compara celdas y números de Open-Meteo.
  Hallazgo para el punto nuevo de Bahía Azul: `punta_delgada` y `bahia_azul` de `config.py` caen en la
  **misma celda** (-52,478 / -69,424); las rampas reales de los ferris caen en otras, con ráfagas distintas
  (hasta 98 km/h en la rampa de Bahía Azul contra 92 en la celda actual). **No se agregó ningún lugar a
  `config.py`**: queda propuesto, a la espera de OK.

## CLAUDE.md renovado (2026-11-27)
- Se instala el `CLAUDE.md` nuevo del equipo (forma de trabajo de un cambio por rama, cómo funciona el
  modelo hoy, lecciones del 24 al 26/11, hoja de ruta con el vencimiento del token de cron-job.org).
- Únicos agregados míos, para que coincida con lo que ya está en `main`: Río Verde en **95** (no 85),
  el comando `web --fresco`, `resultados.py` en la estructura y 153 pruebas. Sin cambios de código.

## Río Verde: regla base en 95 km/h (2026-11-27)
- La regla base de Río Verde pasa de 85 a **95 km/h = 50 %** (amarillo desde 75), `PRIOR_BY_ROUTE`.
  Motivo: el 26/11 operó normal en horario de servicio con ráfagas de hasta 88 km/h y la regla de 85
  daba 20 falsas alarmas rojas en 379 lecturas normales (con 95 siguen 7).
- Sigue siendo un piso y no una medición (solo hubo 1 suspensión, con 55 km/h). Con 95 todavía hay
  ráfagas de hasta 104 km/h con el cruce normal, así que conviene revisar si Open-Meteo exagera el
  viento en ese punto (Bloque 3) antes de seguir moviendo el umbral.

## Web con datos frescos: `python -m corredor web --fresco` (2026-11-27)
- Hallado el 27/11: una web armada en tu computadora decía "datos de hace 23 h 52 min" aunque el servicio
  andaba bien (52 recolecciones en las últimas 24 h; la web publicada estaba al día). Pasaba porque tu
  carpeta `data/` se queda vieja: el recolector sube datos nuevos a GitHub cada 30 min y no se bajan solos.
- `--fresco` hace `git fetch` y arma la web con los datos más nuevos de GitHub, **sin tocar tu carpeta
  `data/` ni tu rama**. Sin `--fresco`, si los datos locales tienen más de 2 h, el comando lo avisa y
  dice cómo arreglarlo. La web publicada (c-couto.github.io/Corredor_Austral/) no cambia.

## En vivo: el ferry espera en la rampa correcta (2026-11-26)
- Hallado un día de viento: con todos los zarpes de hoy cancelados, el ferry de Punta Arenas–Porvenir
  figuraba en Punta Arenas "esperando" un zarpe de mañana que sale de Porvenir. Ahora, en reposo, el
  ferry está en la rampa desde donde sale el próximo zarpe. Prueba nueva (usa Node.js si está instalado).

## En vivo abierto como archivo: va solo a la versión publicada (2026-11-26)
- Si la pantalla En vivo se abre como archivo (`file://`), ahora **redirige sola** a
  https://c-couto.github.io/Corredor_Austral/en-vivo/ en vez de quedarse en el cartel de aviso
  (el cartel queda solo si no hay internet). Para ver el sitio desde el celular, abrir ese link.

## Botón "Ver ferris en vivo" abierto como archivo (2026-11-25)
- Si la página principal se abre como archivo (file://) en vez de desde el sitio publicado, el botón
  llevaba a una pantalla que no puede cargar. Ahora, en ese caso, va directo a
  https://c-couto.github.io/Corredor_Austral/en-vivo/. En el sitio publicado no cambia nada.

## Río Verde: regla base en 85 km/h (2026-11-25)
- La regla base de Río Verde pasa de 70 a **85 km/h = 50 %** (`PRIOR_BY_ROUTE` en `config.py`).
  Motivo: el 24/11 operó normal con ráfagas de hasta 81 km/h y la regla de 70 daba 27 falsas alarmas.
  Es un piso (lo mínimo que se sabe que aguanta), no una medición: no hay temporales de Río Verde
  para calibrarlo. Primera Angostura y Porvenir siguen en 70.

## Primera Angostura: regla base en 94 / 79 km/h (2026-11-26)
- La regla base de Primera Angostura pasa de 70 a **rojo desde 94 km/h y amarillo desde 79**
  (`PRIOR_BY_ROUTE` en `config.py`): lo que había aprendido el modelo con los datos reales.
  Con 70 daba 32 falsas alarmas rojas en 282 lecturas normales; con 94/79, 0 (y 13 amarillas).
- **Provisional**: sale de solo 2 temporales (los dos del 24/11). El 24/11 las suspensiones fueron con
  ráfagas de 91–92 km/h, así que salen en amarillo y no en rojo. Se revisa al tener 8 temporales.
- Porvenir (70) y Río Verde (85) no cambian.

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
