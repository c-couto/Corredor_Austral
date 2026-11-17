# Recolector gratis en la nube (GitHub Actions)

Una tarea de GitHub corre `collector.py run` cada 30 minutos y guarda los datos en archivos CSV dentro de `data/`, en de un repositorio **privado**. Tu PC no hace falta.

Antes de empezar, revisá en tu cuenta cuántos minutos gratis de Actions tenés por mes en repositorios privados: este plan usa aproximadamente 1 minuto por ejecución (unas 1.440 por mes). Si no alcanza, cambiá el cron a una vez por hora (está explicado en el archivo del workflow).

## Cómo funciona con tus datos manuales

- La nube escribe **solo** `data/weather_obs.csv`, `data/marine_obs.csv` y `data/collector_errors.csv`.
- Vos escribís **solo** `data/status_obs.csv`, `data/events.csv` y `data/crossings.csv` (con los comandos `status`, `event` y `crossing`).
- Así nunca editan el mismo archivo y git no da conflictos.
- `report` y `export` leen todos juntos.

## Paso a paso (Windows, PowerShell)

### 1. Pasá tus primeros datos a la carpeta nueva

Reemplazá los archivos del proyecto por los de este paquete (`collector.py`, `README.md`, etc.) y después:

```
mkdir data
copy corredor.db data\auto.db
```

Tu primera recolección queda como punto de partida.

### 2. Apagá la tarea programada de tu PC (si la creaste)

Si no, tu PC y la nube escribirían en el mismo archivo y se pisarían:

```
schtasks /delete /tn "CorredorAustral" /f
```

No vuelvas a correr `python collector.py run` en tu PC una vez que la nube esté andando. Para ver datos, usá `report` o `export`.

### 3. Creá el repositorio privado

1. Entrá a github.com e iniciá sesión (creá la cuenta si no tenés).
2. **New repository**, nombre `corredor-austral`, marcá **Private**, sin README ni .gitignore.
3. Copiá la URL que te muestra.

### 4. Subí el proyecto

En PowerShell, dentro de la carpeta del proyecto (necesitás tener Git instalado):

```
git init
git branch -M main
git add .
git commit -m "inicio"
git remote add origin URL_DE_TU_REPO
git push -u origin main
```

Verificá con `git status` que `data/auto.db` haya quedado incluido. Con un repositorio privado, nadie más ve tu código ni tus datos.

### 5. Activá y probá

1. En GitHub, pestaña **Actions**. Si te lo pide, habilitá los workflows.
2. Abrí el workflow **collect** y tocá **Run workflow** para una corrida de prueba.
3. Esperá 1 minuto. Tiene que quedar con una tilde verde y aparecer un commit nuevo "datos ...".

Si falla al guardar (error de permisos al hacer push): en **Settings > Actions > General > Workflow permissions** elegí **Read and write permissions** y volvé a correrlo.

### 6. Usarlo en el día a día

Antes de mirar o cargar datos, traé lo último de la nube:

```
git pull
python collector.py report
```

Para cargar una demora real:

```
python collector.py crossing punta_delgada_bahia_azul 90 --note "cola de 20 camiones"
git add data/crossings.csv
git commit -m "demora"
git pull --rebase
git push
```

## Cosas para tener en cuenta

- **A veces se atrasa.** Las ejecuciones programadas de GitHub pueden demorarse varios minutos o saltearse alguna en momentos de mucha carga. Para empezar sirve, pero no es exacto como un servidor propio.
- **Uso comercial.** La fuente de clima (Open-Meteo gratuita) es para uso no comercial. Si más adelante cobrás un servicio con estos datos, hace falta un plan comercial u otra fuente.
- **Límites y condiciones de GitHub.** Cambian con el tiempo: revisalos de vez en cuando. Si tu repositorio es público, las tareas programadas pueden pausarse tras un período sin actividad, así que mantené el repositorio privado y activo.
- **El día que quieras algo más sólido**, el mismo script corre en un servidor propio con `cron`, tal como indica el README.
