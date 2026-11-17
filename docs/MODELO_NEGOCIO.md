# Modelo de negocio · Corredor Austral

## La idea en una línea

**"El semáforo del Estrecho"**: el estado oficial de los cruces + la probabilidad de que se suspendan en las próximas horas, aprendida de nuestro propio historial, y la mejor hora para salir. TABSA informa el estado del momento y lo borra; nosotros lo guardamos, aprendemos de él y anticipamos.

## Por qué es original

| Lo que hay hoy | Lo que agrega Corredor Austral |
|---|---|
| TABSA muestra el estado **del momento** | **Historial** de suspensiones con duración, y mapa de días y horas críticas |
| Pronósticos de viento genéricos | **Probabilidad de suspensión por cruce**, aprendida de suspensiones reales |
| Hay que entrar a mirar | **Avisos automáticos** por Telegram cuando cambia el estado |
| Nadie te dice cuándo salir | **"¿A qué hora salgo?"**: la mejor salida desde Río Gallegos, Punta Arenas, Río Grande o Ushuaia |

La ventaja que no se copia fácil es **el historial**: cada día que pasa, el modelo sabe más y un competidor que empiece después arranca de cero.

## Clientes y fuentes de ingreso

### 1. Plan Flota (la principal)
**Quién:** empresas de transporte y logística que abastecen Tierra del Fuego (alimentos, combustible, materiales), y empresas con choferes que cruzan seguido.
**Dolor:** un camión esperando horas en Primera Angostura es plata perdida (chofer, combustible, mercadería perecedera, entregas atrasadas).
**Qué reciben:**
- Avisos privados e inmediatos por Telegram cuando cambia el estado de su ruta.
- Planificador de salidas para sus choferes.
- Informe mensual: horas de suspensión, días y horas críticas, demoras estimadas.

**Precio orientativo:** USD 15–30 por mes y por empresa (en pesos o CLP según el país). Una sola espera evitada de un camión ya lo paga.

### 2. "Dónde esperar" (patrocinios locales)
**Quién:** hosterías, estaciones de servicio, restaurantes y almacenes en Punta Delgada, Cerro Sombrero, San Sebastián, Porvenir.
**Qué compran:** aparecer en la web **cuando el riesgo es alto o el cruce está suspendido**, que es justo cuando hay gente esperando cerca.
**Precio orientativo:** cuota mensual fija, baja (pensada para negocios chicos). Se carga en `SPONSORS` de `corredor/config.py`.

### 3. Informes (más adelante)
Municipios, aseguradoras, cámaras de comercio y turismo: estadísticas del corredor por temporada.

## Lo que queda gratis (y por qué)
La web, el canal público de Telegram y el botón de WhatsApp son **gratis para todos**. Son lo que trae audiencia y credibilidad. Las empresas pagan por lo que les ahorra plata.

## Costos: cero fijo
| Pieza | Costo |
|---|---|
| Recolección, modelo y avisos (GitHub Actions) | Gratis (~1.440 de 2.000 min/mes) |
| Web (Cloudflare Pages, cuando se publique) | Gratis, sin tarjeta |
| Telegram | Gratis |
| Clima (MET Norway) | Gratis, uso comercial permitido citando la fuente |
| Cobros (Mercado Pago) | Sin costo fijo: comisión solo sobre lo que se cobra |

## Plan de validación (antes de programar cobros)
1. **Semana 1–4:** dejar corriendo la recolección (el modelo necesita historial). Publicar la web y abrir el canal de Telegram.
2. **Semana 2–6:** contactar **10 empresas** de transporte que cruzan a Tierra del Fuego. Ofrecer a **5** un **mes de prueba gratis** del Plan Flota (avisos privados + planificador). Usar `docs/GUION_CONVERSACIONES.md`.
3. **Medir:** ¿abren los avisos? ¿cambiaron alguna salida por el planificador? ¿cuántas horas de espera evitaron?
4. **Decidir:** si 2 de 5 aceptan pagar al terminar la prueba, se activa el cobro. Si no, ajustar la oferta con lo que dijeron.

### Guion corto para la primera llamada
> "Armamos un sistema que guarda el estado de los cruces de TABSA y estima con horas de anticipación la probabilidad de que se suspenda Primera Angostura, con la mejor hora para salir desde Río Gallegos o Río Grande. ¿Cuántas veces por mes un camión de ustedes queda esperando en el cruce? ¿Cuánto les cuesta una espera de 5 horas? Te ofrezco un mes gratis de avisos para tus choferes, a cambio de tu opinión."

## Cómo cobrar (cuando se valide)
- **Mercado Pago → Suscripciones:** se crea un plan con link de pago, sin costo fijo. Cada empresa se suscribe con ese link.
- El acceso premium es un **grupo privado de Telegram por empresa** (o un chat del bot). Alta y baja manual al principio; automatizar recién con más de ~10 clientes.
- Facturación: según el país del cliente; consultar con un contador antes del primer cobro.

## Configuración para vender
En GitHub → Settings → Secrets and variables → Actions → **Variables**:
- `CORREDOR_CONTACT_URL`: contacto comercial (p. ej. `https://wa.me/54...` o un formulario). Activa los botones "Quiero probarlo gratis" y "Aparecé acá".
- `CORREDOR_MET_CONTACT`: un mail o la web del proyecto. **Obligatorio antes de cobrar**: pasa el clima a MET Norway (Open-Meteo gratis no permite uso comercial).
- `CORREDOR_SITE_URL` y `CORREDOR_TELEGRAM_URL`: cuando la web y el canal estén publicados.

## Riesgos y cómo cuidarlos
| Riesgo | Cuidado |
|---|---|
| Uso comercial del clima | Pasar a MET Norway (`CORREDOR_MET_CONTACT`) antes de cobrar |
| Datos de TABSA | Citar siempre la fuente con link, aclarar que no somos canal oficial, no usar sus APIs internas. Si el servicio crece, contarles el proyecto: pueden ser aliados |
| Que TABSA cambie su página | El lector falla de forma visible (`collector_errors.csv`) y no guarda datos dudosos; se ajusta el lector |
| Predicción equivocada | Se muestra como probabilidad, con el estado oficial al lado y la invitación a confirmar con TABSA. El modelo solo reemplaza a la regla base si demuestra predecir mejor |
| GitHub saltea corridas | cron-job.org como disparador principal (revisar que esté funcionando) |
