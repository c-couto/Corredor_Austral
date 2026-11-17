# Corredor Austral · recolector de datos v0.3

Registra clima, viento y oleaje en puntos clave del corredor hacia Tierra del Fuego, y te permite cargar a mano estados y demoras reales. Con el tiempo, esos datos son la base de un modelo para anticipar demoras.

No necesita instalar nada: solo Python 3.9 o superior.

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
data/                      los datos (ver data/README.md)
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

## Qué falta (y cómo conseguirlo)

- **Fuentes de mar y aire:** hoy solo hay oleaje de modelo y carga manual. En las conversaciones preguntá qué datos de barcos y vuelos de carga usan o dónde los miran.
- **Estado oficial del paso y horarios del ferry:** no están automatizados. Revisá los términos de uso de cada sitio antes de hacer scraping, o buscá una fuente oficial con API. Mientras tanto, cargalo a mano con `status`.
- **Coordenadas:** son aproximadas. Verificalas en un mapa y ajustá `PLACES` en `corredor/config.py`.

## Aviso importante sobre las fuentes

La API gratuita de Open-Meteo es para **uso no comercial**. Si vas a vender un servicio basado en estos datos, vas a necesitar un plan comercial de ellos u otra fuente (por ejemplo, datos oficiales del Servicio Meteorológico Nacional). Revisá sus términos actuales antes de cobrar.

## Estructura de los datos (CSV)

Cada tabla es un archivo CSV: lo del bot está en `data/auto/` y lo que cargás vos en `data/manual/`. Siempre se agregan filas al final, y las horas están en UTC. El detalle de cada columna, con sus unidades, está en [data/README.md](data/README.md).

Si abrís un CSV en Excel, no lo guardes encima: Excel puede cambiar el formato.

| Tabla | Contenido |
|---|---|
| `weather_obs` | Viento, ráfagas, temperatura, lluvia y pronóstico de ráfaga máxima a 24 h |
| `marine_obs` | Altura y período de olas |
| `status_obs` | Estados cargados a mano |
| `events` | Cortes, paros, suspensiones, cancelaciones (tierra, mar, aire) |
| `crossings` | Demoras reales de cruce, en minutos |
| `collector_errors` | Fallas del recolector |

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
