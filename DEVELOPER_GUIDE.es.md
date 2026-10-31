# ekte — Guía para desarrolladores

> [🇬🇧 English](DEVELOPER_GUIDE.md) · [🇨🇳 中文](DEVELOPER_GUIDE.zh-CN.md) · [🇫🇷 Français](DEVELOPER_GUIDE.fr.md) · **🇪🇸 Español** · [🇵🇹 Português](DEVELOPER_GUIDE.pt.md) · [🇮🇹 Italiano](DEVELOPER_GUIDE.it.md) · [🇩🇪 Deutsch](DEVELOPER_GUIDE.de.md) · [🇳🇴 Norsk](DEVELOPER_GUIDE.nb.md)

Esta guía es para quienes modifican ekte: cómo está construido, cómo preparar un
entorno de desarrollo, cómo contribuir y cómo se empaqueta, se ejecuta en Docker
y se publica. Qué hace ekte y cómo usarlo está en el [README](README.es.md); cómo
funciona y se puntúa cada comprobación, en la [Metodología](docs/METHODOLOGY.es.md).

---

## Contenido

- [Principios](#principios)
- [Entorno de desarrollo](#entorno-de-desarrollo)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Arquitectura](#arquitectura)
  - [Flujo de una auditoría](#flujo-de-una-auditoría)
  - [Clientes](#clientes)
  - [Detectores y escalas de puntuación](#detectores-y-escalas-de-puntuación)
  - [Puntuación y veredicto](#puntuación-y-veredicto)
  - [Base de conocimiento](#base-de-conocimiento)
  - [Biblioteca de prompts](#biblioteca-de-prompts)
  - [Informes](#informes)
  - [Superficies](#superficies)
  - [Auditores independientes](#auditores-independientes)
  - [Servidor web](#servidor-web)
  - [Frontend web](#frontend-web)
  - [Datos locales](#datos-locales)
- [Contribuir](#contribuir)
  - [Pull requests](#pull-requests)
  - [Añadir un detector](#añadir-un-detector)
  - [Editar la base de conocimiento](#editar-la-base-de-conocimiento)
  - [Cambiar los prompts de las sondas](#cambiar-los-prompts-de-las-sondas)
  - [Traducciones](#traducciones)
  - [Documentación](#documentación)
- [Pruebas](#pruebas)
- [Docker](#docker)
- [Integración continua](#integración-continua)
- [Publicación de versiones](#publicación-de-versiones)
- [Seguridad](#seguridad)
- [Licencia](#licencia)

## Principios

ekte es una ayuda de auditoría de caja negra: la corrección y **no acusar en
falso a relays honestos** importan más que atrapar cada truco posible. Ten presente
ese listón en cualquier cambio.

- **Evidencia, no acusaciones.** Los hallazgos informan de *desviación y riesgo*,
  nunca de «fraude». Mejor *no concluyente* que una suposición. Una nueva vía de
  gravedad ALTA necesita evidencia sólida y reproducible, y debe ser difícil de
  disparar con un endpoint honesto.
- **Sin red en las pruebas.** Las pruebas de los detectores se ejecutan contra el
  servidor simulado en proceso de `tests/conftest.py` (httpx `MockTransport`),
  nunca contra una API real.
- **Los secretos no salen.** Las claves de API se reducen a una huella y nunca se
  guardan en los informes. Toda nueva vía de salida debe pasar el texto
  controlado por el relay por `ekte.utils.redact` y escaparlo para su formato.
- **Las mismas sondas para todos.** Los textos de las sondas están en inglés y
  son fijos, sea cual sea el idioma de la interfaz, para que el mismo relay
  reciba el mismo veredicto (ver [Biblioteca de prompts](#biblioteca-de-prompts)).
- **Solo local.** ekte solo contacta los endpoints que configura el usuario, y la
  interfaz web solo escucha en loopback (ver [Servidor web](#servidor-web)).

## Entorno de desarrollo

Requiere Python 3.11+. Linux, macOS y Windows se prueban en la CI; las pruebas que solo tienen sentido en POSIX se omiten en Windows con un motivo explícito (`skipif(sys.platform == "win32", reason=...)`). Usa `pathlib`, pasa `encoding="utf-8"` en la E/S de texto y nunca escribas `/tmp` fijo. Node.js es opcional: las pruebas del JavaScript del
navegador se ejecutan con `node` y se omiten sin él.

```bash
git clone https://github.com/mn567250/ekte
cd ekte
pip install -e '.[dev,web]'   # editable, con herramientas de dev e interfaz web
pytest                        # suite de pruebas
ruff check ekte tests         # lint
mypy ekte                     # comprobación de tipos
```

Con uv: `uv venv && uv pip install -e '.[dev,web]'`. No hace falta
ninguna biblioteca del sistema, tampoco para los informes PDF.

Ejecuta desde el código fuente con `ekte …` o `python -m ekte …`. `ekte serve`
sirve la interfaz web directamente desde `ekte/web/static/`, así que recargar el
navegador recoge los cambios del frontend; no hay paso de build.

## Estructura del repositorio

```text
ekte/
  cli.py               CLI Typer: check, compare, models, kb*, serve, watch, embed, rerank, image, audio
  config.py            configuración YAML, referencias a secretos (env:/file:), AuditOptions
  runner.py            run_audit(): lo conecta todo y ejecuta los detectores
  context.py           AuditContext que recibe cada detector
  models.py            contratos de datos pydantic: TargetConfig, Finding, DetectorResult, AuditReport, …
  scoring.py           puntuaciones de dimensión, pesos, puntuación global, veredicto de riesgo, confianza
  clients/             clientes HTTP: compatible con OpenAI, Anthropic Messages, OpenAI Responses
  detectors/           un archivo por detector, más base.py (registro), scale.py, helpers.py
  judge/               el juez LLM de confianza que usa quality_judge
  knowledge/           esquema, cargador, almacén del usuario (kb.db), importación, prompt de investigación, instantáneas
    data/              perfiles de proveedores integrados (*.yaml)
  prompts/en.json      todo texto que ekte envía a una API de LLM
  perf/                registro por petición y la sección de rendimiento del informe
  report/              renderizadores JSON / Markdown / HTML / PDF y escritura
  embed_audit.py       auditor independiente de embeddings y rerank
  media_audit.py       auditor independiente de imagen y audio (TTS)
  notify.py            alertas por webhook (Slack / Feishu / DingTalk / JSON genérico)
  datadir.py           el directorio de datos local y sus archivos SQLite
  legacy.py            los ajustes ZING_* y la copia de ~/.zing de antes del cambio de nombre
  secretbox.py         cifrado de los secretos guardados; la clave maestra en memoria
  i18n/                traducciones compartidas por la interfaz web y las alertas
    locales/           <code>.json por idioma, fragments/<feature>/<code>.json
  utils/               censura, análisis SSE, estadística, estimación de tokens
  web/
    server.py          app FastAPI: páginas, API JSON, flujo SSE de auditoría, planificador de monitores
    jobs.py            trabajos de auditoría en segundo plano y el bloqueo por relay
    security.py        escucha en loopback, lista de hosts permitidos, controles de Origin/JSON, cabeceras
    history.py         almacén del historial de auditorías (history.db)
    analytics_store.py sus tablas de análisis: métricas por ejecución, registros de peticiones
    analytics.py       consultas de análisis: KPI, series temporales, clasificaciones
    watches.py         almacén de los monitores (watches.db)
    masterkey.py       estados y acciones de la clave maestra (servidor y `ekte secret`)
    static/            scripts que comparten todas las páginas (lang.js, i18n.js, icons.js, …)
    static/v2/         páginas, estilos y scripts de la interfaz web
tests/                 suite pytest; conftest.py contiene el relay simulado
docs/                  METHODOLOGY (8 idiomas), CI.md, DOCKER.md, PUBLISHING.md
examples/ekte.yaml     archivo de configuración comentado
action.yml             la action compuesta de GitHub
Dockerfile             imagen de la interfaz web
```

## Arquitectura

### Flujo de una auditoría

`ekte check`, `ekte compare`, `ekte watch`, el flujo de auditoría de la interfaz
web y su planificador de monitores terminan todos en la misma función,
`ekte.runner.run_audit()`:

1. **Configuración.** `ekte/config.py` combina la configuración YAML con las
   opciones de línea de comandos en `TargetConfig` (objetivo, referencia y juez
   opcionales) y `AuditOptions` (suite, dimensiones, tamaño de las sondas,
   salida). Aquí se resuelven las claves de API dadas como `env:VAR` o
   `file:/ruta`.
   El formato se define en `ekte/configfile.py` (una tabla de claves, tipos y valores por defecto) y se publica como esquema JSON [`docs/schemas/config.schema.json`](docs/schemas/config.schema.json), que se regenera con `uv run python -m ekte.configfile` (una prueba falla si está desactualizado). `ekte/config.py` carga el archivo a través de él, así que todos los comandos lo validan. Un cambio de formato requiere un nuevo `CURRENT_VERSION`, los cambios de nombre en `RENAMES_FROM` (que usa `ekte config migrate`) y una entrada en el changelog; una clave obsoleta va a `DEPRECATED` con su sustituta. Véase la [política de estabilidad](docs/STABILITY.md#surface-config).
2. **Base de conocimiento.** `load_knowledge_base()` carga los perfiles
   integrados, `--kb-dir`/`EKTE_KB_DIR` y el `kb.db` del usuario, y resuelve el
   modelo **declarado** (por defecto, el solicitado) a un perfil. Un monitor pasa
   en su lugar su instantánea anclada.
3. **Clientes.** `make_client()` crea un cliente para el objetivo (y la
   referencia) en el protocolo elegido o detectado automáticamente. Un
   `RequestRecorder` envuelve cada llamada para la sección de rendimiento.
4. **Detectores.** `select_detectors()` elige los detectores registrados para la
   suite (o las dimensiones personalizadas) y descarta los que necesitan un juez
   o una referencia ausentes. Se ejecutan **de forma secuencial**, a propósito:
   las peticiones concurrentes dispararían límites de tasa y distorsionarían las
   mediciones de tiempo (las sondas de fiabilidad y rendimiento gestionan su
   propia concurrencia acotada). `run_detector()` cronometra cada uno y convierte
   un fallo interno en un resultado con estado **Error**, de modo que una
   respuesta anómala del relay nunca interrumpe la auditoría.
5. **Puntuación.** `scoring.build_dimensions()` y `build_verdict()` convierten
   los resultados de los detectores en puntuaciones de dimensión, puntuación
   global y nota, veredicto de riesgo y su confianza.
6. **Informe.** Todo acaba en un `AuditReport` (`ekte/models.py`) con el objetivo
   censurado, la instantánea del perfil de la base de conocimiento, la sección de
   rendimiento y los idiomas de las sondas. La CLI lo renderiza y lo escribe; la
   interfaz web lo transmite.

`run_audit()` acepta un callback `on_event`; el servidor web convierte sus
eventos (detector iniciado/terminado con hallazgos compactos, tiempos por
petición agrupados) en Server-Sent Events para la vista en vivo.

### Clientes

`ekte/clients/` tiene un cliente por protocolo — `openai_compatible.py` (Chat
Completions), `anthropic.py` (Messages) y `responses.py` (Responses) — con la
misma interfaz, construidos sobre la mecánica HTTP común de `base.py`.
`make_client()` en `clients/__init__.py` elige uno según `--api` o lo detecta a
partir de la URL base y el modelo. Los detectores solo hablan con esta interfaz
(`RequestSpec` de entrada, `CompletionOutcome` de salida), así que son
independientes del protocolo.

Los clientes también adaptan las solicitudes a lo que el modelo acepta
(`base.py`): el runner rellena `unsupported_params` desde el perfil, los
parámetros de muestreo que figuran allí se omiten y, en Chat Completions, un
`max_tokens` listado envía el límite como `max_completion_tokens`. Un 4xx que
nombra uno de esos parámetros lo añade al conjunto y repite la solicitud una vez
adaptada (el intento rechazado se registra con la fase `param_retry`). Una sonda
que juzga el rechazo sin alterar establece `RequestSpec.exact_params`.

### Detectores y escalas de puntuación

Un detector es un archivo autocontenido en `ekte/detectors/`: una subclase de
`Detector` (`base.py`) con un `id`, un `name`, una `dimension`, la primera suite
en la que se ejecuta (`min_suite`), un `cost_hint` aproximado para `--dry-run` y
`async def run(self, ctx) -> DetectorResult`. `@register` lo añade al registro;
`ekte/detectors/__init__.py` importa cada módulo para que el registro esté
completo.

Cada detector publica su **escala de puntuación** (`SCALE`, construida con
`scale.py`): cada resultado posible de cada comprobación con sus puntos, estado y
gravedad. Los hallazgos se crean a partir de la escala
(`SCALE.finding(check, outcome, …)`), así que informe y comportamiento no pueden
divergir. `Scale` puntúa con la media de sus comprobaciones; `DeductionScale`
parte de 100 y resta o limita. La interfaz web muestra la escala en **Escala de
puntuación**; la [Metodología](docs/METHODOLOGY.es.md) reproduce cada escala.
`connectivity.py` es el ejemplo canónico y más corto.

Los detectores comparten un mismo bucle de eventos con todas las demás
auditorías de `ekte serve`, así que el trabajo intensivo en CPU no debe
ejecutarse en él: un bucle bloqueado retrasa las peticiones de las demás
auditorías e infla las latencias que registran. `helpers.build_filler()`
construye el texto de relleno en tiempo lineal y memoriza los últimos pocos
tamaños, y los detectores de ventana de contexto y de caché de prompts lo llaman
(así como a `build_haystack()`) mediante `asyncio.to_thread`. Los conteos de
tokens vienen de `ekte/utils/tokenize.py`, una heurística con la biblioteca
estándar: ekte no importa ninguna biblioteca de tokenizer y no descarga nada en
tiempo de ejecución, así que funciona en entornos restringidos. El argumento `tokenizer`
de `estimate_tokens()` se acepta pero no cambia el conteo, y los campos del
informe `tokens_exact` / `exact_tokenizer` se conservan por compatibilidad y
siempre valen false.

### Puntuación y veredicto

`ekte/scoring.py` contiene `DIMENSION_WEIGHTS` y las reglas del veredicto: la
puntuación de una dimensión es la media con igual peso de sus detectores, la
puntuación global la media ponderada de las dimensiones ejecutadas, y el nivel de
riesgo sigue la escala de gravedad descrita en
[Metodología → Cómo puntúa ekte](docs/METHODOLOGY.es.md#cómo-puntúa-ekte). Cada
dimensión registra cómo se calculó en `DimensionScore.breakdown`, que alimenta
los **Dimension details** de los informes y las filas desplegables de
**Comprobaciones por dimensión** de la interfaz web.

### Base de conocimiento

`ekte/knowledge/` define el esquema de los perfiles (`schema.py`:
`ProviderProfile`, `ModelProfile`, `FingerprintProbe`), carga y fusiona las
capas (`loader.py`: YAML integrado → `EKTE_KB_DIR`/`--kb-dir` → el `kb.db` del
usuario), guarda las entradas del usuario (`store.py`), comprueba e importa YAML
(`importer.py`), construye el prompt de investigación para asistentes externos
(`research.py`) y toma una instantánea del perfil que usó una ejecución
(`snapshot.py`). Los ids de modelo se resuelven de forma exacta, mediante
alias o por nombre normalizado, acotados por el proveedor declarado. La
alternativa aproximada toma el nombre de la KB más largo que contiene el id
declarado (un id de snapshot o decorado), salvo que el resto del id nombre otro
nivel o variante (`-mini`, `-lite`, `-image`, …); un id truncado solo se
resuelve cuando el nombre de un único modelo empieza por él, así que un id
ambiguo como `gpt-4` no obtiene perfil en lugar de un nivel adivinado. Cada
informe registra cómo se resolvió el id.

`load_knowledge_base()` guarda en caché los resultados fusionados y devuelve por
defecto una copia profunda, así que quien la llama puede modificar lo que
recibe. Quienes solo la leen (las listas y el catálogo de la interfaz web,
resolver un modelo) pasan `copy=False` y obtienen la instancia compartida en
caché, que no deben modificar.

Los relays también son endpoints: `relays.py` convierte los `base_url_hints`
de un proveedor en URL base utilizables (`GET /api/kb` → `base_urls`) y guarda un
relay desde la interfaz web como entrada de proveedor en `kb.db` (`origin =
relay`: un `display_name` y una URL base, sin modelos; sin cambios de esquema).

### Biblioteca de prompts

Todo texto que ekte envía a una API de LLM — sondas de chat, el prompt del juez,
esquemas de herramientas, entradas de embeddings / rerank / imagen / audio — está
en `ekte/prompts/en.json` y se lee con `ekte.prompts.text()` / `get()`.
`{{name}}` marca un valor que se rellena en tiempo de ejecución. El idioma de las
sondas está fijado en inglés (`PROBE_LANG`), independientemente del idioma de la
interfaz, porque las comprobaciones de respuestas y las estimaciones de tokens
están calibradas con esos textos exactos. Las sondas cuyo idioma *es* la medida
(p. ej. fluidez en chino, tokenizer o autoidentificación de modelos chinos) viven
con sus respuestas esperadas en la base de conocimiento y declaran `prompt_lang`
y un motivo `language_bound`. El runner registra los idiomas usados en
`prompt_languages`.

### Informes

`ekte/report/render.py` renderiza un `AuditReport` como JSON, JSON compacto para
agentes, Markdown y HTML; `dimensions.py` y `performance.py` renderizan los
**Dimension details** y la sección de rendimiento; `pdf.py` compone el PDF con
ReportLab a partir de los mismos datos y funciones (Python puro; solo las fuentes
estándar de PDF, con la fuente CID STSong-Light para el chino, así que no se
incrusta nada; sin cargar nunca recursos externos), y la CLI y la interfaz web
lo comparten;
`writer.py` escribe los archivos. Todo texto controlado por el relay se censura y
se escapa (HTML / Markdown) antes de la salida. `POST /api/report/export` de la
interfaz web reutiliza estos renderizadores para la fila **Descargar informe**,
con los textos legibles traducidos al idioma de la interfaz.

### Superficies

La **superficie** es el tipo de endpoint auditado: `chat` (por defecto),
`embedding` o `rerank` (`ekte.config.SURFACES`; más adelante imagen, TTS). Es un
segundo eje junto a la suite, que llevan `AuditOptions.surface`,
`AuditReport.surface` y una columna `surface` anulable en `history.db` y
`watches.db` (`NULL` y un campo JSON ausente significan `chat`; sin migración).

- Los detectores declaran `surface: ClassVar[str]`; `select_detectors` filtra por
  ella antes del nivel de suite. Los detectores de embeddings y rerank reutilizan
  las dimensiones existentes.
- Los pesos de puntuación y los conjuntos de dimensiones de perfil / núcleo /
  infraestructura son por superficie (`scoring.SURFACE_WEIGHTS`); chat conserva
  sus valores.
- El grabador marca las llamadas de embeddings con `op="embed"` y las de rerank con
  `op="rerank"` (`ekte.config.SURFACE_OPS`); las funciones de `perf/summary.py`
  aceptan un parámetro `op` (por defecto `complete`).
- `embed_audit.run_embedding_audit()` y `run_rerank_audit()` (usadas por
  `ekte embed` / `ekte rerank` y `/api/embed` / `/api/rerank`) ejecutan el runner
  con `surface="embedding"` o `"rerank"`, pasan la ejecución guardada anterior de
  la misma superficie como `previous_report` (deriva) y guardan el informe salvo
  que se indique lo contrario (`--no-save`).
- Detectores de rerank: `rerank.connectivity`, `rerank.known_answer`
  (CAPABILITY), `rerank.identity` y `rerank.drift` (MODEL_IDENTITY),
  `rerank.determinism` (RELIABILITY) y `performance.rerank`. Pesos:
  MODEL_IDENTITY 30, CAPABILITY 30, PERFORMANCE 20, RELIABILITY 10,
  CONNECTIVITY 10.
- Monitores: la `surface` y `embedding_dimensions` (0 = de la base de
  conocimiento) de un monitor alimentan `AuditOptions` en `_run_one_watch_inner`;
  un monitor de embeddings o rerank lee su referencia de deriva con
  `history.latest_for(..., surface=...)` antes de la auditoría y compara las
  alertas solo con ejecuciones de la misma superficie. La superficie se fija al
  crearlo (`POST /api/watches`, `/api/watches/from-history/{id}`, que también
  acepta `embedding_dimensions`) y `PATCH` no la cambia; `PATCH` cambia
  `embedding_dimensions` de un monitor de embeddings (la tarjeta de Monitores v2
  lo edita en línea).

### Auditores independientes

Imagen/audio (`media_audit.py`) aún no son superficies, así que tienen sus propios
auditores pequeños con su propio veredicto en lugar del pipeline de detectores.
Comparten los ajustes HTTP de los clientes, la base de conocimiento (dimensiones
nativas, tamaños de imagen, voces) y la biblioteca de prompts. Toda la
decodificación (cabeceras de imagen, WAV) usa solo la biblioteca estándar.

### Servidor web

`ekte/web/server.py` es una app FastAPI creada por `create_app()`:

- **Páginas.** La interfaz web (`/v2/`, `/v2/history`, `/v2/watches`,
  `/v2/analytics`, `/v2/kb`, `/v2/accessibility`) es HTML estático. No hay página
  de Herramientas: las auditorías de embeddings y rerank empiezan en la página de
  auditoría con el selector de tipo de endpoint (`/v2/?surface=embedding|rerank`),
  y `/v2/tools` sirve una pequeña página que redirige allí los enlaces antiguos
  (`#rerank` elige rerank, `?rerun=` se transmite). Las direcciones de la
  interfaz clásica eliminada (`/`, `/history`, `/watches`, `/tools`, `/console`)
  redirigen (308) a sus páginas v2, con la cadena de consulta.
- **API.** `/api/jobs…` ejecuta las auditorías (ver abajo); `/api/models` lista
  los modelos de un relay; `/api/report/export` renderiza un informe;
  `/api/history…`, `/api/watches…`, `/api/kb…` y `/api/analytics…` dan servicio
  a las demás páginas. `/api/audit/stream` (una auditoría transmitida por SSE),
  `/api/embed` y `/api/rerank` (una auditoría síncrona de embeddings / rerank)
  ya no los usa la interfaz web; su futuro se sigue en las issues #3 y #4.
- **Relays.** `POST /api/kb/relays` guarda un relay `{name, base_url}` (400 si la
  entrada no es válida, 409 si el nombre o la URL ya se conocen).
- **Análisis.** `GET /api/analytics/options` (relays, modelos, suites, modos de
  stream, API y el intervalo de fechas del historial), `/api/analytics/summary`
  (KPI de `from`–`to` frente al intervalo anterior de la misma duración),
  `/api/analytics/series` (`metric` por `group=relay|model|relay_model`, hasta
  4 `keys`, en intervalos `bucket=hour|day|week|dow_hour` de la zona horaria
  del usuario, `tz` o `tz_offset`; `dow_hour` acepta además `block` (horas por fila) y
  `fold=week|4weeks|month_week`, que vuelve a `week` hasta que las ejecuciones
  abarcan 90 o 180 días) y `/api/analytics/leaderboard` (`model=` para
  sus relays, o `relay=` para sus modelos). Todos aceptan los filtros `from`,
  `to`, `suite`, `stream_mode`, `api`, `source=all|manual|monitor`, `relay` y
  `model`. `ekte/web/analytics.py` lo calcula todo en Python a partir de
  `history.analytics_runs()`: los identificadores de métrica salen de una lista
  fija, los relays se agrupan por su entrada de la base de conocimiento en el
  momento de la consulta, un valor que una ejecución no midió se omite (cada
  valor lleva su `n` y su `coverage`) y los intervalos con menos de `MIN_RUNS`
  (3) ejecuciones se marcan con `low_n`. Un parámetro no válido responde 400;
  las respuestas llevan `Cache-Control: no-store`.
- **Paneles de analítica.** `/api/analytics/breakdown` (hasta 8 `metrics` por
  `group=relay|model|relay_model|all` en el periodo), `/api/analytics/errors`
  (las llamadas de completado al destino por clase de resultado
  `success|client_4xx|rate_limited|server_5xx|timeout|network|other`, por
  `group=relay|model` y por `bucket`, contadas en SQL por
  `history.analytics_request_classes()` sin cargar las filas de peticiones; la
  hora de una llamada es el inicio de su auditoría más su desfase, al minuto;
  `covered` = auditorías con registros de peticiones) y
  `/api/analytics/integrity` (recuentos de superadas / avisos / fallos de los
  detectores de identidad, capacidades, visión, streaming, protocolo,
  integridad, prompt inyectado y conectividad por relay × modelo, la proporción
  de modelos discrepantes y la mediana de ventana de contexto medida /
  declarada). `/api/analytics/series` también acepta `group=all`. Mismos
  filtros y errores que arriba.
- **Auditorías en segundo plano.** `jobs.py` ejecuta cada auditoría como un
  trabajo del servidor. `POST /api/jobs` pone uno en cola, `GET /api/jobs` lista
  los trabajos en cola, en marcha y recién terminados (y los monitores en
  ejecución) con su progreso, `GET /api/jobs/{id}/events` reproduce el registro
  de eventos y luego lo sigue en vivo por SSE, y `POST /api/jobs/{id}/cancel` lo
  detiene. La interfaz web los usa, así que una auditoría sobrevive a la
  página; `/api/audit/stream` envuelve el mismo trabajo y lo
  cancela al cerrarse el flujo. Un bloqueo por relay deja que una sola auditoría
  (o ejecución de monitor) use un relay a la vez, por nombre de host y con todas
  las direcciones loopback como un host; como mucho
  `EKTE_MAX_PARALLEL_AUDITS` (4 por defecto) a la vez, en orden de llegada.
- **Planificador de monitores.** El lifespan de la app lanza un bucle en segundo
  plano que inicia cada monitor pendiente como su propia tarea, así que los
  monitores de relays distintos auditan a la vez; el bloqueo por relay se sigue
  aplicando, de modo que los monitores pueden ocupar los huecos de
  `EKTE_MAX_PARALLEL_AUDITS` y una auditoría manual puede quedar en cola detrás
  de ellos. El `last_run_ts` de una ejecución es el momento en que empieza su
  auditoría (tras esperar a su relay). Cada ejecución se guarda en el historial;
  la comprobación de regresiones la compara con la ejecución guardada más
  reciente del mismo objetivo y modelo (`history.latest_for()`, una sola
  búsqueda indexada) y envía las alertas por webhook (`ekte/notify.py`) en
  paralelo al cruzar un umbral o ante una regresión. `POST /api/watches/{id}/run`
  responde 409 cuando el planificador acaba de iniciar ese monitor; un
  restablecimiento de la clave maestra cancela las ejecuciones programadas que
  aún no han empezado, y el apagado cancela las que están en curso.
- **Compresión y caché.** `caching.py` comprime con gzip las respuestas de 1 KiB
  o más (salvo los Server-Sent Events) para los clientes que lo aceptan
  (`gzip;q=0` lo rechaza). Las páginas y `/locales.js` se comprimen una sola vez,
  al generarse, y se sirven precomprimidos con `Content-Encoding: gzip`,
  `Vary: Accept-Encoding` y un ETag aparte que termina en `-gz`; las páginas se
  sirven mediante `html_page(page, request.scope)` para que tomen esa ruta y
  respondan 304 a las peticiones condicionales. Las URL de scripts y hojas de
  estilo locales en las páginas llevan un `?v=<content hash>` y se guardan en
  caché como inmutables.
- **Seguridad.** `security.py` resuelve la dirección de escucha (solo loopback,
  salvo en un contenedor detectado con `EKTE_CONTAINER=1`) e instala
  `LocalOnlyMiddleware`: una lista de hosts permitidos contra el DNS rebinding,
  controles de `Origin` y `Sec-Fetch-Site` contra CSRF, cuerpos de petición solo
  JSON y cabeceras anti-iframe / no-sniff / no-referrer. La interfaz no tiene
  inicio de sesión por diseño.

### Frontend web

El frontend es HTML, CSS y JavaScript de navegador sencillos, sin módulos ni paso
de build. Las páginas están en `ekte/web/static/v2/` y comparten una cabecera (`nav.js`), el renderizador de
informes (`report.js`), el selector de tema (`theme.js`) y los estilos
(`tokens.css`, `ekte.css`, `fields.css`, `report.css`, `perf.css`). Los scripts compartidos se
sirven desde la raíz: `lang.js` (cambio de idioma), `locales.js` (datos de
traducción), `i18n.js` (traducción de hallazgos), `icons.js` (con el logotipo de
ekte), `secretfield.js` y `perf.js` (gráficos de rendimiento).

Cada página v2 salvo Accesibilidad tiene un **aviso de página** justo bajo su
hero (`<div class="znote" id="note">`, dibujado por `v2/notice.js`, con estilo
`.znote` en `ekte.css`): `EkteNotice.show(el, {level, title, detail, items,
actions})`; el nivel `info`, `success`, `warning` o `critical` fija el tinte, el
borde y el icono (critical es `role="alert"`, los demás `role="status"`; mostrar
el mismo aviso otra vez no cambia nada). La página elige el mensaje más
importante y lista los demás en `items`. Auditoría: servidor inalcanzable /
auditorías en curso / la ejecución guardada más reciente / se ejecuta
localmente; Historial: historial ilegible / ejecuciones de monitores en pausa
(clave maestra bloqueada) o ejecuciones antiguas aún en proceso / número de
ejecuciones; Analítica: datos ilegibles / ejecuciones aún no incluidas en los
gráficos o con hora de inicio estimada / en qué se basa; Conocimiento: error de
carga / entradas omitidas o ignoradas / elementos desactivados / completa.
Monitores conserva su barra de clave maestra (`masterkey.js`), con el mismo
aspecto y lugar. Las cifras del historial completo vienen de
`GET /api/history/status` (`history.status()`: número de ejecuciones, la más
antigua y la más reciente, filas que el backfill de analítica aún no procesó,
ejecuciones con hora de inicio estimada).

La página v2 **Auditoría** configura los relays con
`v2/relaycfg.js`: selección de relay/proveedor → URL base → los modelos del relay
(`/api/models`, al cambiar, en caché por URL/clave/protocolo) → modelo declarado
de la base de conocimiento (`/api/kb/resolve` lo preselecciona) → proveedor
derivado, además de **Guardar en la base** (`POST /api/kb/relays`). Sus funciones
auxiliares puras se prueban con node.

La página v2 **Analítica** (`v2/analytics.html`) solo lee `/api/analytics/*`
(`options` también lista los pares relay × modelo, `relay_models`, para el
selector de series). Tiene una `<section class="card panel">` por panel bajo una
única barra de filtros, así que se pueden añadir paneles; filtros y vista van en
el fragmento de la URL (`#range=30&metric=score&…`) y en `localStorage`. Los
gráficos salen de `v2/charts.js` (`EkteCharts.timeChart`: SVG en línea dibujado
a mano con línea mediana, banda p25–p75, huecos para intervalos vacíos,
marcadores atenuados para intervalos `low_n`, líneas de anotación y tooltip al
pasar el puntero; `fmt` / `fmtDelta` formatean valores según la unidad) y de
`v2/charts.css` (cuatro colores de serie validados por tema, distinguibles
también por la forma del marcador). Cada gráfico existe también como tabla de
datos.

Cada panel es autónomo: un registro `PANELS` en el script de la página indica
el id de su sección, `load()` (obtener con los filtros y la vista actuales y
dibujar) y `render()` (redibujar con los datos cargados, p. ej. al cambiar de
idioma), así que los paneles pueden reorganizarse sin tocarse entre sí.
`EkteCharts.heatmap` dibuja la cuadrícula día de la semana × hora (escala
secuencial de un tono en cinco pasos por tema, celdas rayadas para `low_n`,
celdas vacías solo con contorno), `EkteCharts.stackBars` las barras de errores
apiladas, y `timeChart` acepta una línea `ref` (ratio de facturación del
100 %). `EkteCharts.donut` (un anillo de partes de un todo con una cifra HTML
en el centro) y `EkteCharts.meter` (una barra fina de partes) dibujan la
tarjeta de cobertura del informe de accesibilidad; sus colores `k-*` (quién
decide un paso: azul la batería de pruebas, violeta una persona) vienen de
`tokens.css`. `v2/chartmotion.js` (`EkteMotion.enter`) dibuja un anillo en el
sentido de las agujas del reloj y hace crecer las barras desde la izquierda,
como en los demás gráficos, solo cuando llegan datos nuevos y nunca con
movimiento reducido ni con la animación desactivada en la cabecera.

La cabecera de la página y el panel de filtros están sobre cinco pestañas
internas (`v2/tabs.js`, como en Conocimiento): cada
entrada de `PANELS` indica su `tab`, y solo se cargan los paneles de la pestaña
visible; un cambio de filtro recarga esa pestaña y marca las demás como
obsoletas (`activate()` las carga al mostrarlas). Aquí `tabs.js` recibe
`writeHash: false`, porque la página escribe ella misma toda la vista en el
fragmento — `#tab=trends&range=30&suite=…&metric=…` (`stateQuery()`), que
**Copiar el enlace a esta vista** copia (un campo de solo lectura seleccionado
si falta la API del portapapeles o la rechaza); un fragmento sin `tab` abre el
Resumen, y un enlace pegado (`hashchange`) vuelve a leer la vista. El panel de
filtros plegable es `v2/filterpanel.js` + `v2/filterpanel.css`, compartido con
el Historial, Monitores y Conocimiento: `EkteFilterPanel.create(section, {label, title, storeKey, open,
onReset})` devuelve `render({body, foot, count, summary})`,
`sync({count, summary})`, `setOpen()` y `focusStart()`; la página tiene sus
filtros y campos, el panel el botón con la insignia de filtros activos, el
resumen de una línea que se muestra plegado, el estado abierto recordado y
**Restablecer filtros**.

**Convención de traducción.** El texto chino escrito en el HTML es el original y
no se toca; cada elemento lleva su texto inglés en `data-en` (y
`data-en-placeholder`, `data-en-title`, `data-en-aria-label`). El texto inglés es
la clave de búsqueda para todos los demás idiomas. Los scripts usan `T(zh, en)`
para el texto dinámico y `EKTE_LANG.server(text)` para el texto que viene del
backend (nombres de detectores, recomendaciones, frases del veredicto).

### Datos locales

`ekte/datadir.py` gestiona `$EKTE_DATA_DIR` (por defecto `~/.ekte`), creado con
`0700`, con archivos SQLite `0600`: `history.db` (`web/history.py`),
`watches.db` (`web/watches.py`, que guarda cifradas las claves API de los
monitores) y `kb.db` (`knowledge/store.py`). Cada llamada abre una conexión de
corta duración, así que los almacenes son seguros en el pool de hilos de
FastAPI. La opción global `--data-dir` (también en `ekte serve`) solo fija
`EKTE_DATA_DIR` con la ruta absoluta, y `ekte data-dir` muestra el directorio
resuelto. Un directorio que ya existe conserva sus permisos; solo el `~/.ekte`
por defecto se restringe a `0700`. Las filas del historial están indexadas por
objetivo y modelo (`idx_history_target`), índice que usa `history.latest_for()`
para encontrar la ejecución anterior de un monitor.

Desde la versión 2 del esquema (`PRAGMA user_version`), `history.db` también
contiene las tablas de análisis, definidas en `web/analytics_store.py`:
`history_metrics` (una fila de métricas extraídas por ejecución: hora de inicio,
tasas, percentiles de latencia/TTFT/decodificación, ratios de facturación,
número de hallazgos y más; NULL donde la ejecución no midió un valor),
`history_dimensions` (puntuaciones de dimensiones y detectores) y
`history_requests` (los registros de peticiones de la ejecución, objetivo y
baseline, en el orden de la lista). Los `performance.requests` de un informe se
guardan solo ahí: `save()` los saca de `report_json` (`requests_split` marca la
fila) y `get()` / `latest_for()` los vuelven a poner, de modo que un informe se
lee idéntico a como se guardó; lo que las columnas no pueden reproducir con
exactitud va a la columna JSON `extra`. `extract_metrics()` es pura y está
versionada (`EXTRACT_VERSION`). Tras la migración, un backfill por lotes (una
transacción corta por lote, idempotente) mueve los registros de las filas
antiguas, extrae sus métricas y vuelve a extraer las filas escritas con una
`EXTRACT_VERSION` anterior; `history.backfill_analytics()` lo ejecuta de nuevo
cuando hace falta. La hora de inicio de una ejecución es el `started_at` del
informe; los informes anteriores a ese campo reciben `generated_at` menos el
intervalo de sus registros de peticiones (`started_at_estimated` = 1).

Dónde se guardan las claves API de los monitores lo decide el usuario
(`watches.get_key_storage()`, una fila de `secret_meta`): `memory`, el valor por
defecto, no guarda ninguna — la columna `api_key` solo tiene la marca `mem:` y la
clave vive en `watches._memory_keys` hasta que el proceso termina (tras un
reinicio la fila queda `key_missing`, que el planificador trata como una clave
bloqueada: la ejecución espera, sin alerta); `encrypted` las guarda como se
describe abajo. Sin fila, un almacén que ya tiene claves cifradas o un valor de
comprobación, o con `EKTE_SECRET_KEY` / un `secret.key` antiguo, empieza en
`encrypted`; la elección se registra al arrancar. `Vault.set_storage()`
(`POST /api/secret/storage`) cambia y mueve las claves en una transacción
(`keys_to_memory()` borra las cifradas y el valor de comprobación y limpia el
archivo; `keys_to_store()` sella las que hay en memoria). Una petición puede
pasar `key_storage: "memory"` para que su clave no entre en la base de datos sea
cual sea el ajuste; nada puede forzar el almacenamiento.

Las claves API guardadas las cifra `ekte/secretbox.py` (Fernet, guardadas como
`enc:v1:…`; las referencias `env:`/`file:` se quedan tal cual). La clave maestra
nunca se guarda: `web/masterkey.py` (`Vault`, compartido por el servidor y
`ekte secret`) la mantiene en la memoria del servidor en cuanto llega de
`EKTE_SECRET_KEY`, de un `secret.key` antiguo o del usuario en la página
Monitores, y `watches.db` solo conserva un valor de comprobación (`secret_meta`)
que rechaza una clave incorrecta. Una clave nueva vuelve a cifrar cada clave
guardada y reescribe el valor de comprobación en una sola transacción. La clave
vive en la memoria de un proceso, así que ejecuta un servidor por directorio de
datos.

`ekte/legacy.py` mantiene en marcha las instalaciones de antes del cambio de
nombre: cada ajuste `EKTE_*` se lee con `legacy.getenv`, que recurre al nombre
antiguo `ZING_*` (avisado una vez en stderr), y `datadir.data_dir()` copia
`~/.zing` a `~/.ekte` una sola vez cuando solo existe el directorio antiguo (los
archivos SQLite mediante la API de copia de seguridad, en un directorio temporal
hermano que luego se renombra). `~/.zing` nunca se modifica ni se borra.
`lang.js` copia del mismo modo los ajustes `zing.*` del navegador a `ekte.*`, y
el servidor sigue leyendo las cookies `zing_lang` / `zing_ui` mientras no
existan las `ekte_*`.

## Contribuir

### Pull requests

- Mantén en verde `pytest`, `ruff check ekte tests` y `mypy ekte` (la CI ejecuta
  los tres con Python 3.11–3.14).
- Describe el truco de relay o el falso positivo que aborda el cambio.
- Actualiza `CHANGELOG.md` en `[Unreleased]`.
- Actualiza la documentación afectada — README, esta guía, la Metodología — en
  **todos los idiomas** (ver [Documentación](#documentación)).

Al contribuir aceptas que tus contribuciones se licencien bajo la licencia
[Apache-2.0](LICENSE) del proyecto.

### Añadir un detector

1. Crea `ekte/detectors/<name>.py` e impórtalo en `ekte/detectors/__init__.py`.
2. Define su `SCALE` (`Scale` o `DeductionScale` de `scale.py`) con cada
   resultado de cada comprobación, y crea los hallazgos solo a través de ella.
3. Hereda de `Detector`; define `id`, `name`, `dimension`, `min_suite` y
   `cost_hint`; pon `requires_judge = True` o `requires_baseline = True` si
   necesita un juez o una referencia, o redefine `applies()` para otras
   condiciones. Decora la clase con `@register`.
4. Implementa `async def run(self, ctx) -> DetectorResult` partiendo de
   `self.new_result(scoring=SCALE.scoring())`. Envía las peticiones a través de
   `ctx.client` y toma cada prompt de `ekte/prompts/en.json`.
5. Añade pruebas de comportamiento para el camino señalado y para el limpio, con
   el relay simulado de `tests/conftest.py`.
6. Traduce los nuevos títulos y resúmenes de hallazgos (ver
   [Traducciones](#traducciones)) y documenta el detector y su escala en cada
   archivo de [Metodología](docs/METHODOLOGY.es.md).

### Editar la base de conocimiento

Los perfiles están en `ekte/knowledge/data/<provider>.yaml`, un archivo por
proveedor. Cada modelo lleva su ventana de contexto nativa, salida máxima, fecha
de corte del conocimiento, tokenizer, modalidades, capacidades, parámetros no
admitidos, palabras clave de identidad y huellas (ver
`ekte/knowledge/schema.py`). Cuando cambies un campo numérico, **cita una fuente
autorizada** (la ficha oficial del modelo, precios o documentación del
proveedor) en la pull request: un valor erróneo provoca falsos positivos contra
relays honestos. `ekte kb-import --check <archivo>` ejecuta las mismas
comprobaciones que la importación del usuario (esquema, límites, expresiones
regulares peligrosas, prompts, colisiones de ids).

Las `fingerprints` a nivel de proveedor se ejecutan en cada modelo del
proveedor. Una sonda cuya expectativa solo vale para algunos modelos (una fecha
de corte, una prueba de conocimiento del nivel Pro, una trampa de razonamiento)
va en las `fingerprints` de esos modelos; si no, la respuesta veraz de otro
modelo cuenta como divergencia.

Rellena siempre `identity_keywords` con las palabras del fabricante y de la
familia con que el modelo se nombra a sí mismo. La comprobación de identidad
también cuenta la clave del proveedor, el nombre visible y el id del modelo como
marca auténtica, ampliados con los demás nombres del fabricante en
`VENDOR_BRANDS` (`ekte/knowledge/identity.py`, que es también la lista de marcas
rivales del detector); la importación completa las palabras clave vacías a
partir de esos nombres con una advertencia. Las palabras de marca de un
fabricante nuevo se añaden allí como un grupo.

### Cambiar los prompts de las sondas

Los textos de las sondas son datos de calibración. Cambiar uno en
`ekte/prompts/en.json` puede alterar las comprobaciones de respuestas, las
estimaciones de tokens y, por tanto, los veredictos; ajusta el detector y sus
pruebas en consecuencia y menciona el cambio en el CHANGELOG. Nunca hagas que una
sonda siga el idioma de la interfaz.

### Traducciones

La interfaz y las alertas por webhook comparten un único conjunto de traducciones
en `ekte/i18n/locales/<code>.json`:

- `meta` — código, el nombre del idioma en su propia lengua para el menú, idioma
  `html`, configuración regional de fechas y orden en el menú;
- `strings` — texto inglés → traducción (`en.json` es la aplicación identidad y
  la lista de referencia de textos traducibles);
- `findings` — id del hallazgo → `[título, plantilla de resumen]` (`zh.json`
  contiene el catálogo chino original).

Las funcionalidades pueden incluir sus textos como fragmentos,
`ekte/i18n/locales/fragments/<feature>/<code>.json` con `{"strings": {…}}`, que se
fusionan en el idioma al cargarse. `/locales.js` envía solo el idioma elegido
(`?lang=<code>` o la cookie `ekte_lang` que fija `lang.js`; sin ninguno, todos
los idiomas), generado y comprimido con gzip una vez por variante y revalidado
por `ETag`; al cambiar de idioma se carga el nuevo bajo demanda.

- **Nuevo texto de interfaz:** escribe el chino en el HTML y el inglés en
  `data-en` (o usa `T(zh, en)`), luego añade la clave inglesa a `en.json` o a un
  fragmento y su traducción en cada uno de los demás idiomas.
- **Nuevo idioma:** añade `ekte/i18n/locales/<code>.json` (copia `de.json`) y un
  archivo por fragmento; el menú, las páginas, las alertas y `--alert-lang` lo
  recogen.
- `tests/test_web_locales.py` falla hasta que cada texto de la interfaz y cada
  hallazgo esté traducido con sus marcadores de posición y su marcado intactos.

**Terminología.** Cada término tiene una sola traducción por idioma. Reutiliza la
terminología que ya usa la interfaz (nombres de páginas, nombres de las
dimensiones, etiquetas de riesgo, rótulos de botones) en los textos nuevos y en
la documentación.

### Documentación

La documentación existe en ocho idiomas — inglés, chino (`zh-CN`), francés,
español, portugués, italiano, alemán y noruego (bokmål, `nb`):

| Archivo | Público |
|---|---|
| `README.md`, `README.<lang>.md` | Usuarios: qué hace ekte, instalación, uso de la CLI y la interfaz web |
| `DEVELOPER_GUIDE.md`, `DEVELOPER_GUIDE.<lang>.md` | Contribuidores: arquitectura, entorno, contribuciones, Docker, versiones |
| `docs/METHODOLOGY.md`, `docs/METHODOLOGY.<lang>.md` | Todos: cada comprobación, su escala de puntuación y sus salvedades |
| `docs/CI.md`, `docs/DOCKER.md`, `docs/PUBLISHING.md` | Páginas de referencia (en inglés) |

Los archivos en inglés son la referencia. Cuando cambies uno, cambia los demás en
la misma pull request y usa en cada idioma la terminología de la interfaz (busca
el término en `ekte/i18n/locales/`). Los archivos METHODOLOGY reproducen las
escalas de puntuación con la redacción que la interfaz muestra en **Escala de
puntuación**.

## Pruebas

```bash
pytest                       # todo
pytest tests/test_billing.py # un módulo
pytest -k streaming          # por palabra clave
pytest -n auto               # en paralelo, un worker por CPU (pytest-xdist)
```

- `tests/conftest.py` ofrece `MockServer`, un endpoint compatible con OpenAI
  sobre `httpx.MockTransport` con ajustes para cada desviación que busca ekte
  (modelo servido, autoidentificación, recorte de contexto, streaming falso,
  uso ausente o inflado, llamadas a herramientas, modo JSON, …). Cada ajuste
  tiene por defecto el valor de un relay honesto.
- Los clientes de Anthropic y Responses tienen sus propias pruebas
  (`test_anthropic.py`, `test_responses.py`); el servidor web se prueba con el
  cliente de pruebas de FastAPI (`test_web*.py`), incluidas las protecciones de
  uso local (`test_web_security.py`).
- Los scripts del navegador (`lang.js`, `v2/relaycfg.js`, `perf.js`,
  `secretfield.js`, `v2/report.js`, las traducciones) se evalúan con `node` en
  `test_web_*_js.py` y `test_web_locales.py`; se omiten sin Node.js.
- Ninguna prueba puede acceder a la red.
- `test_cli_startup.py` mantiene rápido el arranque de la CLI: importar
  `ekte.cli` no debe cargar los clientes HTTP, el runner, el cargador de la base
  de conocimiento, los renderizadores de informes (ReportLab) ni el servidor
  web. Impórtalos dentro del comando que los necesite.
- `test_filler_perf.py` fija el texto de relleno byte a byte y falla cuando la
  sonda de ventana de contexto bloquea el bucle de eventos.
- `tests/a11y/` comprueba la interfaz web (v2) frente a BITV 2.0 / EN 301 549 /
  WCAG 2.1 AA en un navegador real (Playwright + axe-core), en cada idioma de la
  interfaz y en ambos temas: `pip install -e '.[web,a11y]' && playwright install
  chromium`, y luego `pytest -m a11y`. Sin Playwright, el directorio se omite. Qué
  está automatizado y qué sigue necesitando una revisión BITV manual se describe
  en [docs/ACCESSIBILITY.md](docs/ACCESSIBILITY.md).
- `EKTE_A11Y_PAGES=history,kb` ejecuta solo las pruebas a11y de esas páginas
  (y las comprobaciones que abarcan todas las páginas); `python -m
  tests.a11y.affected --base origin/main --head HEAD` muestra las páginas a las
  que afecta un cambio. Ambos usan una sola correspondencia,
  `tests/a11y/pages.py`: una página nueva se añade a su `PAGES` y `RULES`
  ([tests/a11y/README.md](tests/a11y/README.md)).

## Docker

El `Dockerfile` construye una imagen de la interfaz web (Python 3.12 slim con el
extra `web`; los informes PDF no necesitan paquetes del sistema). Se ejecuta con
un usuario sin privilegios y el directorio de datos en `/data`.

```bash
docker build -t ekte .
docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data ekte
# abre http://localhost:8000
```

**Publica siempre en `127.0.0.1`.** Un simple `-p 8000:8000` publica la interfaz
— y cada clave API escrita en ella o guardada en un monitor — en tu red. Dentro
del contenedor, el servidor debe escuchar en todas las interfaces; eso solo se
permite si `EKTE_CONTAINER=1` está definido (la imagen lo define) *y* se detecta
un entorno de contenedor.

| Variable | Por defecto | Función |
|---|---|---|
| `EKTE_CONTAINER` | sin definir (`1` en la imagen) | Permite escuchar fuera de loopback dentro de un contenedor detectado |
| `EKTE_HOST` | `127.0.0.1` (`0.0.0.0` en la imagen) | Dirección de escucha; `--host` prevalece |
| `EKTE_PORT` | `8000` | Puerto; `--port` prevalece |
| `EKTE_DATA_DIR` | `~/.ekte` (`/data` en la imagen) | Historial, monitores (con sus claves cifradas) y tus entradas de la base de conocimiento; monta aquí un volumen. `--data-dir` tiene prioridad |
| `EKTE_SECRET_KEY` | sin definir | Clave maestra de las claves API guardadas de los monitores (una clave, o `file:/run/secrets/…` / `env:VAR`); sin definir, la página Monitores la pide tras cada arranque. Nunca se guarda en `EKTE_DATA_DIR` |
| `EKTE_KB_DIR` | sin definir | Directorio YAML adicional de la base de conocimiento, p. ej. `-v ./profiles:/kb:ro -e EKTE_KB_DIR=/kb` |
| `EKTE_NO_USER_KB` | sin definir | `1` ignora tus propias entradas de la base de conocimiento (`kb.db`) |
| `EKTE_ALLOWED_HOSTS` | sin definir | Nombres de host adicionales a los que responde la interfaz, separados por comas |

[docs/DOCKER.md](docs/DOCKER.md) es la referencia completa (en inglés), incluido
lo que protege la interfaz.

## Integración continua

| Workflow | Se ejecuta con | Hace |
|---|---|---|
| `.github/workflows/ci.yml` | push y pull request a `main` (y a las ramas de integración `a11y/integration`, `perf/integration`); cada noche y manual (solo accesibilidad) | `ruff`, `mypy` y `pytest` con Python 3.11–3.14 y los extras `dev` y `web`; construye la wheel y la sdist y comprueba que la wheel se instala y carga la base de conocimiento; ejecuta la suite de accesibilidad (informativa, nunca hace fallar la ejecución) y sube sus hallazgos: todas las páginas en los push y las ejecuciones nocturnas y manuales (con el informe de conformidad BITV), en las pull requests solo las páginas afectadas por el cambio (ninguna si solo cambia documentación) — salvo en las pull requests a `perf/integration`, donde se omite la lenta suite de navegador (se ejecuta en los push de esa rama y en su pull request a `main`) |
| `.github/workflows/release.yml` | una etiqueta `v*` | construye, ejecuta `twine check` y publica en PyPI (Trusted Publishing) |
| `.github/workflows/example-audit.yml` | programación diaria, manual | ejemplo de auditoría programada de un relay con la action |

La action compuesta es `action.yml`, documentada en [docs/CI.md](docs/CI.md).

### Archivos de terceros en la distribución

La distribución de código fuente contiene las pruebas, pero ningún archivo de terceros incluido. `tests/a11y/vendor/axe.min.js` (axe-core, MPL-2.0) está solo en el repositorio git; se excluye del sdist (`exclude` en `[tool.hatch.build.targets.sdist]` de `pyproject.toml`) y nunca formó parte del wheel.

- Las pruebas que necesitan un archivo excluido se omiten con un motivo claro cuando falta; ejecute la suite de accesibilidad desde un checkout de git.
- `NOTICE` enumera cada archivo de terceros e indica si se distribuye. Añada un archivo nuevo a la lista `exclude` y a `NOTICE`, o, si debe distribuirse, indique en `NOTICE` que se distribuye.
- `scripts/check_dist_contents.py` construye el wheel y el sdist (`uv build`) y falla si hay un archivo excluido, o uno que `NOTICE` indica como no distribuido. El workflow `.github/workflows/dist.yml` lo ejecuta en un job aparte.

## Publicación de versiones

Una versión es una etiqueta de versión; todo lo demás está automatizado y
comprobado. La lista de comprobación está en
[docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md); la configuración única de
PyPI y el procedimiento manual, en [docs/PUBLISHING.md](docs/PUBLISHING.md).

### Publicar una versión

1. Recorrer la [lista de comprobación](docs/RELEASE_CHECKLIST.md): versión y
   changelog, versiones de Python y sistemas admitidos, actualidad de la base de
   conocimiento, fixture de actualización, revisión de accesibilidad si cambia la
   UI, documentación en todos los idiomas, avisos de seguridad.
2. Fijar `version` en `pyproject.toml` y renombrar `[Unreleased]` en `CHANGELOG.md`
   a `[X.Y.Z] - AAAA-MM-DD`. Comprobar en local con
   `python scripts/release_check.py version vX.Y.Z` y `... notes vX.Y.Z`.
3. Fusionar, etiquetar el commit y subir la etiqueta:
   `git tag -a vX.Y.Z -m "ekte vX.Y.Z"`, `git push origin vX.Y.Z`.
4. `release.yml` verifica primero, con `scripts/release_check.py`, que la etiqueta
   coincide con la versión del paquete, que `CHANGELOG.md` tiene una sección para
   ella y que la CI está en verde para el commit etiquetado (espera si aún se está
   ejecutando). Si falla una comprobación, el workflow se detiene y no se publica
   nada. Después compila, publica en PyPI mediante Trusted Publishing con
   atestaciones de procedencia y crea la GitHub Release con la sección del
   changelog como notas.

### Release candidates

Etiquetar `vX.Y.ZrcN` (con `version = "X.Y.ZrcN"` en `pyproject.toml`). PyPI la trata
como prerrelease PEP 440: `pip install ekte` la ignora y `pip install --pre ekte` la
encuentra; GitHub marca la release como «Pre-release». En el changelog sirve la
sección `[X.Y.ZrcN]`, `[X.Y.Z]` o `[Unreleased]`.

### Si una publicación falla a medias

PyPI nunca acepta dos veces el mismo archivo y una versión no se puede reutilizar;
decide según hasta dónde llegó la ejecución (Actions, «Release to PyPI»):

- **Falló una comprobación (job verify).** No se publicó nada. Corregir la causa
  (versión, changelog, CI), borrar la etiqueta en local y en origin
  (`git push origin :refs/tags/vX.Y.Z`) y etiquetar de nuevo el commit corregido.
- **Falló la compilación o la subida antes de que PyPI tuviera archivos.** Volver a
  ejecutar los jobs fallidos; no se consumió ninguna versión. Si hay que cambiar el
  propio commit etiquetado, borrar la etiqueta y crearla otra vez.
- **PyPI tiene parte de los archivos** (ver <https://pypi.org/project/ekte/#files>).
  Volver a ejecutar los jobs fallidos: la subida omite los archivos existentes. Si
  los archivos difieren de lo que se quiere publicar, no reintentar: hacer «yank» de
  la versión en PyPI y publicar la siguiente (`X.Y.Z+1` o `rcN+1`).
- **PyPI está completo pero falló la GitHub Release.** Volver a ejecutar el job
  `GitHub Release`; crea o actualiza la release de forma idempotente. O a mano:
  `gh release create vX.Y.Z --notes-file <(python scripts/release_check.py notes vX.Y.Z)`.
- **Ya hay una versión defectuosa publicada.** Hacer «yank» en PyPI (solo se instala
  con versión exacta), corregir hacia delante con una versión nueva y anotarlo en su
  changelog.

## Seguridad

Informa de las vulnerabilidades en privado, como se describe en
[SECURITY.md](SECURITY.md). Entran en el alcance sobre todo: una clave o un
secreto que llegue a un informe, texto controlado por el relay que inyecte
marcado en un informe o en la interfaz, tráfico hacia algo distinto de los
endpoints configurados y cualquier forma de eludir las protecciones de uso local
de la interfaz web.

## Licencia

[Apache-2.0](LICENSE)
