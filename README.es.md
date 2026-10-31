# ekte — verificación de la realidad de los relays de LLM

> [🇬🇧 English](README.md) · [🇨🇳 中文](README.zh-CN.md) · [🇫🇷 Français](README.fr.md) · **🇪🇸 Español** · [🇵🇹 Português](README.pt.md) · [🇮🇹 Italiano](README.it.md) · [🇩🇪 Deutsch](README.de.md) · [🇳🇴 Norsk](README.nb.md)

[![CI](https://github.com/mn567250/ekte/actions/workflows/ci.yml/badge.svg)](https://github.com/mn567250/ekte/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

**ekte** es una herramienta local-first que audita si un relay de API
(revendedor / proxy) sirve realmente el modelo que declara — o si lo sustituye en
silencio por uno más barato, recorta tu ventana de contexto, simula el streaming
o infla la facturación de tokens. En resumen: ¿recibes lo que pagas? Habla la
**API OpenAI Chat Completions**, la **API Anthropic Messages** y la **API OpenAI
Responses** (`/v1/responses`) — con detección automática, o forzada con
`--api openai|anthropic|responses`.

Le indicas el endpoint de un relay y el modelo que dice servir; ekte ejecuta una
batería de sondas de caja negra, compara el comportamiento observado con una
base de conocimiento integrada de **98 perfiles de modelos de 7 proveedores** y
da un veredicto claro y respaldado por evidencia — en la línea de comandos, en
una interfaz web local o en JSON para otra herramienta o LLM.

> ekte aporta **evidencia de caja negra de desviaciones y riesgos, no una prueba
> criptográfica de fraude.** Consulta [Uso responsable](#uso-responsable).

Este README es para quienes **usan** ekte. Cómo se construye, se prueba y se
publica ekte está en la [Guía para desarrolladores](DEVELOPER_GUIDE.es.md); cómo
funciona y se puntúa cada comprobación, en la [Metodología](docs/METHODOLOGY.es.md).

---

## Contenido

- [Por qué](#por-qué)
- [Instalación](#instalación)
- [Inicio rápido](#inicio-rápido)
- [Interfaz web (`ekte serve`)](#interfaz-web-ekte-serve)
- [Qué comprueba](#qué-comprueba)
- [Cómo se llega al veredicto](#cómo-se-llega-al-veredicto)
- [Suites](#suites)
- [Rendimiento](#rendimiento)
- [Modo comparación y juez LLM](#modo-comparación-y-juez-llm)
- [Monitorización](#monitorización)
- [Auditorías de embeddings, rerank, imagen y audio](#auditorías-de-embeddings-rerank-imagen-y-audio)
- [Uso en CI (GitHub Action)](#uso-en-ci-github-action)
- [Base de conocimiento](#base-de-conocimiento)
- [Informes](#informes)
- [Privacidad y datos locales](#privacidad-y-datos-locales)
- [Uso responsable](#uso-responsable)
- [Más documentación](#más-documentación)
- [Si vienes de zing](#si-vienes-de-zing)
- [Licencia](#licencia)

## Por qué

El mercado de claves de relay está lleno de ofertas de «GPT-4o a una décima parte
del precio». Muchas son honestas. Otras no — y las deshonestas son difíciles de
detectar a simple vista:

- Pides `gpt-4o`; en silencio te sirven `gpt-4o-mini` o un modelo abierto.
- El relay anuncia un contexto de 1M de tokens pero lo recorta en silencio a 32K.
- El «streaming» es la respuesta completa almacenada en búfer y vuelta a trocear, sin ganancia de latencia.
- Los tokens de `usage` reportados están inflados, así que tu saldo se agota más rápido de lo debido.
- Un modelo que debería admitir llamadas a herramientas / modo JSON en silencio no lo hace.

ekte convierte «aquí algo no cuadra» en un informe reproducible.

## Instalación

Requiere Python 3.11+. Funciona en Linux, macOS y Windows (la imagen de Docker es Linux); en Windows los modos de solo propietario del directorio de datos no tienen efecto, véase [Sistemas operativos compatibles](docs/STABILITY.md#os). Cualquiera de las opciones siguientes proporciona el comando `ekte`.

### Con pip

```bash
# desde PyPI
pip install ekte

# o desde el código fuente
git clone https://github.com/mn567250/ekte
cd ekte
pip install -e .
```

### Con [uv](https://docs.astral.sh/uv/)

```bash
# desde PyPI, como herramienta independiente en tu PATH
uv tool install ekte

# o ejecutarlo una vez sin instalarlo
uvx --from ekte ekte --help

# o desde el código fuente, en un entorno virtual local del proyecto
git clone https://github.com/mn567250/ekte
cd ekte
uv venv
uv pip install -e .
source .venv/bin/activate       # Windows: .venv\Scripts\activate
```

También puedes instalarlo directamente desde el repositorio Git sin clonarlo:
`uv tool install git+https://github.com/mn567250/ekte`.

### Extras opcionales

- `web` — la interfaz web local (`ekte serve`).

```bash
pip install 'ekte[web]'      # pip, desde PyPI
pip install -e '.[web]'            # pip, desde el código fuente
uv tool install 'ekte[web]'  # uv, desde PyPI
uv pip install -e '.[web]'         # uv, desde el código fuente
```

El extra `tokenizers` ya no es necesario: está vacío y solo se
conserva para que los comandos de instalación antiguos sigan funcionando. ekte
cuenta los tokens con una heurística integrada y no descarga nada en tiempo de
ejecución (ningún archivo de tokenizer), así que también funciona en entornos
restringidos o sin conexión que solo alcanzan los relays que auditas.

Los informes PDF (`--format pdf` y la descarga en PDF de la interfaz web) no
necesitan ningún extra: se componen con
[ReportLab](https://www.reportlab.com/opensource/), una dependencia en Python puro
que no requiere bibliotecas del sistema en Linux, macOS ni Windows.

### Con Docker (solo la interfaz web)

Desde una copia del código fuente:

```bash
docker build -t ekte .
docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data ekte
# abre http://localhost:8000
```

Publica siempre el puerto en `127.0.0.1`, como arriba. Detalles y variables de
entorno: [Guía para desarrolladores → Docker](DEVELOPER_GUIDE.es.md#docker) y
[docs/DOCKER.md](docs/DOCKER.md).

## Inicio rápido

```bash
# 1) auditar un relay frente a lo que declara (id del modelo + pista de proveedor)
export EKTE_API_KEY=sk-tu-clave-del-relay
ekte check \
  --base-url https://relay.example.com/v1 \
  --api-key env:EKTE_API_KEY \
  --model gpt-4o \
  --suite standard

# 2) la comprobación más fuerte: comparar con una referencia de confianza del mismo modelo
export OPENAI_API_KEY=sk-tu-clave-de-openai
ekte compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:EKTE_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o \
  --suite deep

# 3) auditar un relay nativo de Anthropic (API Messages) — el protocolo se detecta
#    automáticamente a partir de base_url/model, o se fuerza con --api anthropic
ekte check --base-url https://relay.example.com/v1 --model claude-opus-4-8 \
  --api-key env:EKTE_API_KEY --api anthropic

# 4) confirmar una sustitución sospechada: auditar el id REAL del modelo del relay frente
#    al perfil con el que se vende (aquí: un modelo Doubao vendido como deepseek-v4-flash)
ekte check --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY \
  --model doubao-seed-2-0-lite --claimed-model deepseek-v4-flash

# 5) listar los modelos que anuncia un endpoint
ekte models --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY

# 6) consultar la base de conocimiento
ekte kb            # todos los perfiles, con su origen
ekte kb deepseek   # un proveedor

# 7) generar una configuración que puedes versionar
ekte init          # escribe ekte.yaml
ekte check -c ekte.yaml
```

Las claves de API pueden darse en claro, como `env:VAR` o como `file:/ruta`; los
informes solo contienen una huella de la clave. Tienes un archivo de
configuración completo en [`examples/ekte.yaml`](examples/ekte.yaml).

El archivo tiene una versión de formato (`version: 1`; un archivo sin versión es el formato 1). Los tipos incorrectos y los valores no válidos se rechazan indicando archivo, línea y clave; las claves desconocidas se ignoran con una advertencia hasta ekte 1.0.0, que las rechaza. `ekte config migrate` actualiza un archivo antiguo. El esquema es [`docs/schemas/config.schema.json`](docs/schemas/config.schema.json).

### Como herramienta para un LLM / agente

ekte está pensado para que lo controle otro programa o modelo. Todo sale por
stdout en JSON, errores incluidos, y el código de salida hace de barrera.

```bash
# veredicto ligero, apto para agentes (~5x más pequeño que --json: sin la evidencia voluminosa)
ekte check --base-url ... --model gpt-4o --compact | jq .verdict.risk

# informe estructurado completo cuando necesitas la evidencia de cada hallazgo
ekte check --base-url ... --model gpt-4o --json

# primero el presupuesto: qué detectores se ejecutan + llamadas a la API estimadas, SIN hacer ninguna
ekte check --base-url ... --model gpt-4o --suite deep --dry-run --json

# barrera por código de salida (1 si el riesgo >= medium, o la puntuación queda bajo --fail-under);
# los errores de configuración/uso salen con 2, en JSON
ekte check --base-url ... --model gpt-4o --compact --fail-on-risk medium

# descubrimiento legible por máquina
ekte kb --json                      # toda la base de conocimiento
ekte models --base-url ... --json   # lo que anuncia un endpoint
```

En modo `--json`/`--compact`, una configuración errónea imprime `{"error": {...}}`
(código de salida 2) en lugar de un mensaje para personas, para que un pipeline
pueda procesar los fallos de forma uniforme.

## Interfaz web (`ekte serve`)

¿Prefieres hacer clic? Una interfaz web local envuelve el mismo motor — sin
línea de comandos.

```bash
pip install 'ekte[web]'     # o: uv tool install 'ekte[web]'
ekte serve                        # abre http://localhost:8000
```

El formulario te guía por la configuración:

1. Elige el **Relay / proveedor**: un proveedor de la base de conocimiento o un
   relay que guardaste. Se rellena su URL base (las demás URL conocidas del
   proveedor se ofrecen como sugerencias). Para cualquier otro relay elige
   **Otro (introducir la URL)** e introduce la **URL del intermediario**.
2. Añade la **Clave de API** si el relay la necesita.
3. ekte lista por sí mismo los modelos del relay (al elegir un relay y cada vez
   que cambian la URL o la clave; **Actualizar modelos** vuelve a preguntar).
   Elige el **Modelo solicitado**. Un relay sin lista de modelos pasa a escribir
   el id (**Introducir a mano**).
4. Opcionalmente, elige el **Modelo declarado** entre los modelos de la base de
   conocimiento: el modelo que el relay dice servir. Si el modelo solicitado está
   en la base de conocimiento, aparece preseleccionado; cámbialo solo si el
   relay vende el modelo con otro nombre. De él se deriva el perfil de
   proveedor con el que ekte audita.

Un relay que aún no está en la lista se puede conservar con **Guardar en la
base** con el nombre que le des; la próxima vez estará a una selección. La
referencia de confianza (**Comparar con una referencia de confianza**) y las
auditorías de embeddings y rerank se configuran igual.

Después, **Iniciar auditoría** y
sigue las comprobaciones **en vivo**: cada comprobación muestra su puntuación y
cuánto tardó, y una comprobación con hallazgos se despliega para mostrar la
evidencia. El resultado es un informe de veredicto que puedes compartir: nota,
**Comprobaciones por dimensión** con sus escalas de puntuación, hallazgos en
lenguaje claro, la sección de rendimiento y un **Registro de ejecución** de cada
detector.

Todo se ejecuta en tu máquina: una clave escrita en el navegador solo llega a tu
servidor ekte local y al relay que auditas, nunca a terceros. Consulta
[Privacidad y datos locales](#privacidad-y-datos-locales).

### Páginas

La interfaz web se sirve en la raíz de la dirección que abre `ekte serve`, con la página de auditoría en `/`. Las direcciones usadas hasta ahora (`/v2/…`, p. ej. `/v2/history`) y las de la antigua interfaz clásica (`/tools`, `/console`) redirigen de forma permanente a la página correspondiente y conservan la cadena de consulta; estas redirecciones están obsoletas y se eliminan en 1.0.0.

| Página | Dirección | Para qué sirve |
|---|---|---|
| **Auditoría** | `/` | Auditar un relay (opcionalmente frente a una referencia) y leer el informe; las auditorías de embeddings y rerank también empiezan aquí, con el selector de tipo de endpoint |
| **Monitores** | `/watches` | Reauditorías programadas con alertas por webhook |
| **Historial** | `/history` | Cada auditoría ejecutada en esta máquina, agrupada por relay + modelo declarado, con tendencias |
| **Analítica** | `/analytics` | Relays y modelos comparados en el tiempo: indicadores, gráficos con tablas de datos, clasificaciones |
| **Conocimiento** | `/kb` | La base de conocimiento en tres pestañas — modelos, proveedores, relays: explorar, activar/desactivar, añadir lo tuyo |

Además, en las páginas: filtros y tendencias configurables (puntuación, nota,
latencia p50, tokens/s) en el **Historial**; **Programar como monitor** y **Repetir auditoría** en cada
ejecución del Historial; **Descargar informe** en todos los formatos; y un selector
de tema (Automático / Claro / Oscuro). Cada página
salvo Accesibilidad tiene un aviso justo bajo su introducción, coloreado según
su importancia (información, éxito, advertencia, crítico): p. ej. la última
auditoría terminada en **Auditoría**, la clave maestra en **Monitores**, las
ejecuciones aún en proceso en **Historial** y **Analítica**, las entradas
omitidas en **Conocimiento**.

**Auditorías en segundo plano.** Una auditoría iniciada en la
página **Auditoría** sigue en marcha cuando cambias de página o cierras la
pestaña; **Continuar en segundo plano** la envía allí a propósito. El
**Historial** muestra cada auditoría en cola y en marcha (y cada monitor en
ejecución) con su progreso; **Ver en directo** vuelve a abrir la vista en vivo,
que se pone al día con todo lo ocurrido. Las auditorías del mismo relay se
ejecutan una tras otra, para no distorsionar sus resultados de latencia o
fiabilidad (todas las direcciones loopback cuentan como un solo host, así que
los modelos servidos desde tu propia máquina también esperan); las de relays
distintos se ejecutan en paralelo, como máximo cuatro a la vez
(`EKTE_MAX_PARALLEL_AUDITS`). Los monitores esperan a su relay del mismo modo.

**Analítica.** `/analytics` convierte el historial local
en comparaciones: indicadores del periodo elegido (ejecuciones, puntuación
mediana, proporción de riesgo alto, tasa de éxito, TTFT, velocidad de salida,
ratios de facturación) con el cambio frente al periodo anterior de igual
duración; un gráfico de cualquier métrica por relay, modelo o relay × modelo,
por hora, día o semana (línea mediana con la banda p25–p75, hasta cuatro
series, cada gráfico también como tabla de datos); y una clasificación de los
relays de un modelo o de los modelos de un relay. Los relays se agrupan por su
entrada de la base de conocimiento (relays guardados y proveedores), así que
renombrar un relay reagrupa su historial. Los intervalos con menos de 3
ejecuciones se dibujan atenuados: una sola auditoría puede ser un valor
atípico; un monitor da mediciones regulares. Las ejecuciones antiguas muestran
lo que midieron: la página indica en cuántas ejecuciones se basa un valor. Por
defecto compara una suite y un modo de sondeo (los más frecuentes), para no
mezclar ejecuciones distintas; filtros y vista se guardan en la URL, así que
una vista se puede marcar o compartir. Nada sale del equipo.

Otros paneles responden preguntas más concretas: **horas punta** (un mapa de
calor día de la semana × hora del TTFT, la latencia y la velocidad de decodificación (mediana y colas p95 /
p5), la variación entre tokens, los tiempos de red y del relay o la tasa de éxito o de
error en tu zona horaria: ¿un relay se vuelve más lento o falla más en las horas
de más carga? Por día de la semana o, con 90 días de ejecuciones, en un ciclo
de 4 semanas y, con 180 días, por semana del mes), **errores y fiabilidad** (llamadas fallidas por causa: límite
de peticiones (HTTP 429), errores del servidor (5xx), tiempos agotados, errores
de red; a lo largo del tiempo y por relay o modelo, a partir de los registros
de peticiones guardados, indicando cuántas auditorías los tienen),
**integridad del modelo** (resultados de las comprobaciones de identidad,
ventana de contexto y capacidades por relay × modelo, la proporción de
auditorías cuyo modelo devuelto difiere y la proporción medida de la ventana
de contexto declarada), **facturación y tokens** (ratios de facturación a lo
largo del tiempo frente a la línea del 100 %: por encima, el relay informa más
tokens de los que contó ekte; además de las proporciones de tokens de
razonamiento y de entrada en caché) y **sobrecarga del relay** (el tiempo de
procesamiento que informa el relay junto al tiempo de ida y vuelta de red).

**Pestañas y enlaces para compartir (Analítica).** Los paneles están en cinco
pestañas — **Resumen** (indicadores, clasificación), **Tendencias**
(comparación en el tiempo, horas punta), **Fiabilidad** (errores, sobrecarga
del relay), **Integridad del modelo** y **Facturación** — bajo la cabecera de
la página y un panel de filtros común; solo se carga la pestaña que está
viendo. La URL guarda la pestaña, los filtros y cada opción de los gráficos
(`#tab=reliability&range=30&relay=…&eb=dow_hour`), y **Copiar el enlace a esta
vista** la copia (o la muestra en un campo para copiarla si el navegador no lo
permite): el enlace abre exactamente esa vista. El panel de filtros es el mismo
en **Historial**, **Monitores** y **Analítica**: cerrado, indica cuántos filtros están activos
y los nombra en una línea (p. ej. «Últimos 30 días · standard · Streaming ·
Example Relay»), así una vista compartida dice lo que muestra.

### Idiomas

Un menú de idioma en la cabecera de cada página cambia la interfaz entre
**🇬🇧 inglés** (por defecto), **🇨🇳 chino** (la interfaz original),
**🇫🇷 francés**, **🇪🇸 español**, **🇵🇹 portugués**, **🇮🇹 italiano**,
**🇩🇪 alemán** y **🇳🇴 noruego** (bokmål); la elección se recuerda por navegador.

Los informes descargados desde la interfaz (**Descargar informe**: JSON,
Markdown, HTML o PDF) siguen el idioma elegido: las claves JSON, los valores
enumerados (`risk_level`, `status`, `severity`, …), los ids y la evidencia quedan
exactamente como en el informe de la CLI (el JSON sigue siendo un informe de ekte
válido), mientras que los valores legibles (titular y resumen del veredicto,
títulos y resúmenes de los hallazgos, recomendaciones, nombres de detectores,
notas) se traducen, y el nombre del archivo lleva el idioma
(`ekte-report.es.json`, `ekte-report.es.pdf`). Los encabezados de sección de los
archivos Markdown/HTML/PDF están en inglés. Los informes de la CLI con
`--format json|md|html|pdf` siguen en inglés.

**Los prompts enviados al endpoint auditado no siguen el idioma de la
interfaz.** Todo texto que ekte envía a una API de LLM está en inglés, para que el
mismo relay reciba el mismo veredicto sea quien sea quien lea el informe (las
comprobaciones de respuestas y las estimaciones de tokens están calibradas con
esos textos exactos). Las únicas excepciones son las huellas de la base de
conocimiento cuyo idioma *es* la medida — por ejemplo, las sondas de fluidez en
chino, de tokenizer y de autoidentificación de los modelos chinos. Cada informe
registra los idiomas de sonda realmente usados (`prompt_languages`, p. ej.
`["en", "zh"]`).
Cada informe también registra cómo se habló con el endpoint: el protocolo
(`target.api`: `openai`, `anthropic` o `responses`), si `--api auto` lo detectó
(`target.api_auto`) y el modo de petición de la sonda de rendimiento
(`stream_mode`: `stream`, `non_stream` o `both` para la suite completa). La página
de historial de la interfaz web puede filtrar por los tres.
`started_at` registra cuándo empezó la auditoría (UTC); el `start_ms` de cada
registro de petición cuenta desde ese momento.

## Qué comprueba

ekte puntúa diez dimensiones. Las cuatro **dimensiones núcleo** — identidad del
modelo, ventana de contexto, capacidades declaradas y facturación y uso — revelan
más directamente un «gato por liebre». Los nombres son los de la interfaz
web y los informes.

| Dimensión | Id | Peso | Qué detecta |
|---|---|---|---|
| **Identidad del modelo** | `model_identity` | 21 | Degradación o sustitución silenciosa del modelo — autoidentificación, fecha de corte del conocimiento, huellas de tokenizer, el campo `model` devuelto; opcionalmente un juez LLM |
| **Ventana de contexto** | `context_window` | 19 | Recorte silencioso del contexto (declara 1M, la recuperación falla en 32K) y «lost in the middle» por capas baratas de RAG/resumen, mediante aguja en un pajar y búsqueda binaria |
| **Capacidades declaradas** | `capability` | 13 | Llamadas a herramientas / modo JSON / esquema JSON / salida máxima declarados pero no entregados (o *sobre*entregados, señal de un sustituto); **visión** — un modelo que declara entrada de imagen debe leer una imagen generada de respuesta conocida |
| **Conformidad del protocolo** | `protocol` | 8 | Conformidad en el cable: multiturno, secuencias de parada, esquema de error; cada parámetro de petición aceptado (y respetado cuando es visible), cada atributo de respuesta presente; caché de respuestas que ignora temperature/seed |
| **Facturación y uso** | `billing` | 8 | Inflado de tokens/uso y contabilidad de uso ausente o no verificable, mediante una estimación heurística independiente de tokens |
| **Conectividad** | `connectivity` | 7 | Accesibilidad del endpoint y la lista `/v1/models` anunciada |
| **Autenticidad del streaming** | `streaming` | 6 | Streaming falso (búfer y luego troceo), a partir del número de fragmentos y su separación temporal |
| **Fiabilidad en concurrencia** | `reliability` | 6 | Tasa de éxito y latencia bajo carga concurrente (la limitación HTTP 429 se cuenta aparte) |
| **Seguridad del transporte** | `security` | 6 | HTTPS, higiene de cabeceras, eco de secretos; un prompt de sistema inyectado oculto; manipulación en tránsito de respuestas y llamadas a herramientas (canarios de respuesta conocida); caché de prefijo de prompt (tiempos) |
| **Rendimiento** | `performance` | 6 | Lo *constantes* que son la latencia, el tiempo hasta el primer token y el throughput, la tasa de fallos y la ralentización bajo carga; la velocidad solo frente a una referencia (ver [Rendimiento](#rendimiento)) |

La [Metodología](docs/METHODOLOGY.es.md) describe cada sonda, el truco de relay al
que responde, su escala de puntuación y sus salvedades sobre falsos positivos.

## Cómo se llega al veredicto

En resumen (los detalles están en la [Metodología](docs/METHODOLOGY.es.md#cómo-puntúa-ekte)):

- Cada detector publica su **escala de puntuación** — cada resultado posible de
  cada comprobación con sus puntos —, y la interfaz web la muestra en **Escala de
  puntuación**.
- La **puntuación de una dimensión** es la media con igual peso de las
  puntuaciones de sus detectores. Un hallazgo ALTO/CRÍTICO impone **Fallo** y un
  hallazgo MEDIO eleva **Correcto** a **Advertencia**, sea cual sea la
  puntuación. Los informes lo explican por dimensión en **Dimension details**; en
  la interfaz web, cada fila de **Comprobaciones por dimensión** se despliega con
  los mismos detalles.
- La **puntuación de salud global** es la media ponderada de las dimensiones
  ejecutadas (pesos arriba), con nota A (≥ 90), B (≥ 80), C (≥ 70), D (≥ 60) o F.
- El **veredicto de riesgo** depende de la gravedad de los hallazgos, no de la
  puntuación:

| Riesgo | Etiqueta en la interfaz | Cuándo |
|---|---|---|
| `inconclusive` | Señal insuficiente | Nada utilizable que juzgar: identidad del modelo, ventana de contexto y capacidades declaradas se ejecutaron sin resultado utilizable (relay inaccesible, modelo fuera de la base de conocimiento), o ninguna dimensión salvo la conectividad lo dio |
| `high` | Gato por liebre | Un hallazgo CRÍTICO, un hallazgo ALTO/CRÍTICO en una dimensión núcleo, o dos o más hallazgos ALTOS |
| `medium` | Desviaciones detectadas | Exactamente un hallazgo ALTO fuera de las dimensiones núcleo, o un hallazgo MEDIO en una dimensión núcleo |
| `low` | Mayormente fiable | Cualquier otro hallazgo MEDIO |
| `clean` | Coherente (probablemente auténtico) | Ninguno de los anteriores |

Los hallazgos de la dimensión de conectividad nunca elevan el riesgo: un relay
caído o limitado no pudo evaluarse, y eso no prueba que responda otro modelo. La
**confianza** del veredicto (baja / media / alta) crece con el número de
dimensiones núcleo que dieron resultado, con una referencia y con el juez LLM.

Los avisos de transporte —HTTP sin cifrar (`security.tls`) y fallos o colas lentas
bajo carga (`reliability.*`)— bajan la puntuación de su dimensión, pero tampoco
elevan el riesgo de sustitución; el resumen los lista como avisos. La manipulación
de respuestas y una clave API devuelta sí lo elevan. HTTP sin cifrar hacia esta
máquina o una red privada es solo un aviso de gravedad baja, porque la clave nunca
sale de ella. Un perfil de la base de conocimiento emparejado solo de forma
aproximada (fuzzy) limita la confianza a baja, y un detector sin ninguna respuesta
utilizable es no concluyente, nunca un aprobado.

## Suites

| Suite | Detectores | Coste |
|---|---|---|
| `smoke` | connectivity, security | muy bajo |
| `standard` | + protocol, protocol_request, protocol_response, model_identity, capability, streaming, billing, reliability | bajo–medio |
| `deep` | + context_window, determinism, vision, injected_prompt, integrity, prompt_cache, performance, quality_judge (con `--judge`) | más alto (las sondas de contexto largo y de tiempos cuestan tokens) |
| `full` | los detectores de `deep`, con el rendimiento medido con y sin streaming | el más alto |
| `custom` | solo las dimensiones que elijas, con la profundidad de `deep` | según la selección |

La sonda de ventana de contexto está limitada por `--max-context-tokens` (200K
por defecto) para que auditar un modelo de 1M de tokens siga siendo asequible.
`--only` / `--skip` ejecutan o excluyen detectores sueltos por su id.
Una ventana mayor que el límite de `--max-context-tokens` se informa como *verificada hasta el límite*, nunca como truncada.

### Suite personalizada

Ejecuta solo las dimensiones que te interesan, lo que ahorra tiempo y tokens. Se
ejecuta cada detector de cada dimensión elegida, como en `deep`:

```bash
ekte check --base-url ... --model gpt-4o -D protocol -D performance
ekte check --base-url ... --model gpt-4o --suite custom --dimension billing,streaming
```

`--dimension/-D` es repetible o separado por comas e implica `--suite custom`; en
un archivo de configuración usa `run.dimensions: [protocol, performance]`. Las
dimensiones son `connectivity`, `protocol`, `context_window`, `model_identity`,
`capability`, `streaming`, `billing`, `reliability`, `security` y `performance`.
En la interfaz web, el botón de suite `custom` abre la misma elección
(**Dimensiones a ejecutar**) en la página de auditoría, la consola y los
monitores.

La **puntuación global es la media ponderada solo de las dimensiones elegidas**;
las que dejas fuera aparecen como «no seleccionadas». El veredicto de riesgo
también se basa en las dimensiones elegidas: sin la identidad del modelo solo
las cubre a ellas, no qué modelo se sirve, y lo indica.

## Rendimiento

Cada informe incluye una sección **performance**: latencia, tiempo hasta el
primer token (TTFT), tokens/s de decodificación y de extremo a extremo, latencia
y jitter entre fragmentos, tasas de error/timeout/429, un desglose de red
(conexión TCP, TLS, un viaje de ida y vuelta `GET /models`, tiempo de servidor) y
arranque en frío, cada uno como count / min / mean / p50 / p75 / p90 / p95 / p99
/ max / stdev.

Cuando se ejecuta la sonda dedicada, puntúa la dimensión **Rendimiento**. La
puntuación mide la **constancia**, no la velocidad bruta, así que un endpoint
lento pero constante (un modelo local o autoalojado) no se penaliza por no ser un
centro de datos:

| Comprobación | Se puntúa según |
|---|---|
| constancia de latencia / TTFT | ratio de cola p90 ÷ p50 (≤ 1,3 constante 100 · ≤ 1,75 estable 85 · ≤ 2,5 variable 65 · por encima: errática 40); necesita ≥ 10 muestras |
| constancia del throughput | ratio de cola p50 ÷ p10 de tokens/s, mismos tramos |
| errores | peticiones de sonda fallidas: ≤ 2 % 100 · ≤ 10 % 80 · por encima: 50 (los 429 no cuentan) |
| estabilidad bajo carga | latencia p50 en ráfaga ÷ p50 secuencial: ≤ 1,5x 100 · ≤ 3x 80 · por encima: 55 |
| acierto de caché | prompts únicos respondidos desde una caché: 60 |
| referencia | tokens/s frente a la referencia de confianza o, si no, al rango publicado para el modelo en la base de conocimiento: en línea 100 · más lento: no computa (informativo, nunca un fallo) · ≥ 2x más rápido 60 (señal de un modelo más pequeño) · sin referencia: no computa |

Los hallazgos de rendimiento son como mucho de gravedad baja: mueven la
puntuación, nunca el veredicto de riesgo. Sin la sonda (`standard` sin
referencia, `smoke`), la dimensión no se ejecuta y sale de la puntuación global.

- **standard** reúne la sección a partir de las propias peticiones de la auditoría.
- **deep / full / custom** añaden una sonda dedicada: 100 peticiones no
  cacheables de 128 tokens de salida (un id de petición aleatorio abre cada
  prompt; no se envían parámetros de caché ni de razonamiento) más una ráfaga con
  `--concurrency`. Ajústala con `--performance-requests` (0 la desactiva) y
  `--performance-max-tokens`.
- La sonda usa streaming por defecto; `--performance-non-streaming` (o el
  selector **Streaming / Sin streaming** de la interfaz web) mide relays que no
  pueden hacer streaming. **full** mide ambos modos, intercalados, y los muestra
  lado a lado.
- **compare** ejecuta la sonda en ambos endpoints, alternando peticiones, y añade
  una tabla objetivo-vs-referencia (5 peticiones por lado en `standard`,
  demasiadas pocas para las comprobaciones de constancia) cuyas diferencias se
  marcan en verde ✓ cuando el objetivo es mejor y en rojo ✗ cuando es peor.

Los tokens se cuentan dos veces — a partir del `usage` del relay y localmente —,
así que el throughput se puede medir incluso sin `usage`. El conteo local es una
estimación con una heurística integrada (aproximadamente ±15-20 %; no se usa ni
se descarga ningún tokenizer), y la sección siempre lo indica. Un percentil solo
se muestra con suficientes muestras (p90 desde 10, p95 desde 20, p99 desde 100). El
informe JSON guarda los tiempos de cada petición (solo números, sin texto); el
informe HTML y la interfaz web los representan a lo largo de la línea temporal de
la auditoría.

Las auditorías que se ejecutan a la vez en `ekte serve` (varias pestañas del
navegador, monitores) no distorsionan los tiempos de las demás: la preparación
intensiva en CPU, como construir los largos prompts de ventana de contexto, se
ejecuta fuera del bucle de eventos del servidor.

**Tiempos de espera.** `timeout_sec` (`--timeout`, 60 s por defecto) es la base;
cada petición recibe más tiempo según el tamaño del prompt y el presupuesto de
salida, para que una sonda larga de ventana de contexto o un modelo autoalojado
lento no se corte al minuto. Los hosts locales y privados (`localhost`, `127.x`,
`192.168.x`, `host.docker.internal`, …) reciben al menos 300 s. `max_request_sec`
(`--max-request-time`, 900 s por defecto) es el tope absoluto de cada petición,
streams incluidos, así que ninguna petición puede quedarse colgada para siempre.
Una sonda de ventana de contexto que aun así agota el tiempo se informa como no
concluyente, no como truncamiento.

## Modo comparación y juez LLM

ekte tiene dos modos de detección:

- **Código puro (por defecto):** todos los detectores salvo `quality_judge`
  deciden con código determinista — huellas, barrido de contexto, aritmética de
  facturación, tiempos del streaming. No hace falta un segundo modelo; los
  resultados son reproducibles.
- **Híbrido código + LLM (`--judge`):** además pregunta a un modelo juez *de
  confianza* (configurado aparte, nunca el objetivo) si las respuestas del
  objetivo se parecen al modelo declarado — señales difusas como la calidad y la
  profundidad de razonamiento que el código solo no puede decidir. Es el detector
  `quality_judge`.

```bash
ekte check --base-url ... --model gpt-4o --suite deep --judge \
  --judge-base-url https://api.openai.com/v1 --judge-api-key env:OPENAI_API_KEY --judge-model gpt-4o-mini
```

El **modo comparación** (`ekte compare`, o **Comparar con una referencia de
confianza** en la interfaz web) ejecuta las mismas sondas, al mismo tiempo,
contra una referencia de confianza del modelo declarado. Es la vía de
confirmación más fuerte: respuestas de identidad, parámetros de petición
rechazados, canarios de manipulación y rendimiento se juzgan lado a lado, y solo
una referencia permite que la confianza del veredicto sea *alta*. Sin
`--judge-base-url`, el modo comparación usa la referencia como juez.

## Monitorización

Un relay puede servir el modelo real hoy y cambiarlo en silencio la semana que
viene. `ekte watch` vuelve a auditar según un calendario, guarda cada ejecución
en el historial y avisa a un webhook cuando el riesgo cruza un umbral o
**empeora** respecto a la ejecución anterior.

```bash
ekte watch --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY \
  --model gpt-4o --suite standard --interval 3600 \
  --alert-on medium --webhook "$FEISHU_WEBHOOK" \
  --alert-lang es                                     # o --once para cron
```

Las alertas se formatean para **Slack / Feishu / DingTalk / JSON genérico**,
detectados automáticamente a partir de la URL del webhook, y se redactan en el
idioma de las alertas — inglés por defecto; `--alert-lang en|zh|fr|es|pt|it|de|nb`.
La carga JSON genérica mantiene neutrales sus claves y valores de máquina
(`risk_level`, `score`, …), traduce los legibles (`text`, `headline`,
`key_findings`) e indica el `language`.

**En la interfaz web**, `ekte serve` ejecuta los mismos monitores en un
planificador en segundo plano dentro del proceso del servidor, guarda cada
ejecución en el **Historial** y envía las mismas alertas por webhook. Abre una ejecución en el **Historial** y elige **Programar
como monitor**. ekte copia la configuración de esa ejecución (relay, modelo,
modelo declarado, proveedor, suite, dimensiones personalizadas) en un monitor
en pausa de la página **Monitores**; allí fija su intervalo y su clave API (el
Historial nunca guarda claves) y actívalo. Intervalo, clave, **Umbral de
alerta**, webhooks e **Idioma de las alertas** se editan directamente en cada
monitor. Al pulsar el nombre de un monitor su tarjeta se pliega a nombre,
estado y última ejecución (**Contraer todo** / **Expandir todo** sobre la
lista; se recuerda por navegador), y el panel de filtros (búsqueda, estado,
último riesgo, tipo de endpoint, relay, suite) acota una lista larga como en
el **Historial**.

Cada monitor tiene su propio idioma de alertas (por defecto, el de la interfaz),
puede ejecutarse ahora, pausarse o eliminarse, y queda anclado al perfil de la
base de conocimiento con el que se creó hasta que lo vuelvas a anclar.

Los monitores a los que les toca ejecutarse lo hacen a la vez, cada uno como su
propia auditoría, pero nunca más de una auditoría a la vez por host de relay y
como máximo `EKTE_MAX_PARALLEL_AUDITS` en total; una ejecución espera a que haya
un hueco libre (una auditoría que lances a mano también puede quedar en cola
detrás de los monitores en curso). La hora de una ejecución es la de inicio de
su auditoría, tras cualquier espera. La comprobación de regresiones compara con
la ejecución guardada más reciente del mismo relay y modelo, por muchas otras
ejecuciones que se hayan guardado desde entonces. Los webhooks de alerta de una
ejecución se envían a la vez, así que uno lento o caído no retrasa a los demás.
Las claves se guardan cifradas en tu directorio de datos local y nunca se devuelven
al navegador.

**Almacenamiento de claves API.** Por defecto ekte **no guarda** las claves API
de los monitores: una clave que introduces permanece solo en la memoria de
`ekte serve` y nunca se escribe en el disco. Tras un reinicio, la página
**Monitores** indica qué monitores necesitan de nuevo su clave; esperan (sin
ejecución fallida ni alerta) hasta que la introduzcas. Los monitores sin clave y
las referencias `env:`/`file:` siguen funcionando. Para que las claves
sobrevivan a los reinicios, elige **Guardar cifradas en este equipo** en
**Almacenamiento de claves API** de la página **Monitores**: las claves se
guardan entonces en `watches.db`, cifradas con una clave maestra. Volver atrás
mueve las claves guardadas a la memoria y las borra de `watches.db`. El aviso de
la página muestra el modo activo, pide confirmación antes de cambiar e informa de
lo que se movió. Una instalación que ya guardaba claves cifradas, o que define `EKTE_SECRET_KEY`,
las sigue guardando hasta que cambies.

**Clave maestra.** Las claves API de los monitores se cifran con una clave
maestra que ekte nunca escribe en disco. La primera vez que guardas una clave
API, la página **Monitores** la crea y la muestra una sola vez: cópiala o
descárgala, guárdala en un gestor de contraseñas (tu navegador puede guardarla)
y pégala de nuevo para confirmar. Tras cada reinicio de `ekte serve` la página
vuelve a pedirla (el navegador puede rellenarla); hasta entonces, los monitores
que la necesitan esperan, mientras que los monitores sin clave o con claves
`env:`/`file:` siguen ejecutándose. La barra de estado de la página también
ofrece **Bloquear**, **Rotar** y **¿Olvidaste la clave?** (descarta las claves
API cifradas para que puedas volver a introducirlas). Para uso desatendido o en
Docker, pasa la clave como `EKTE_SECRET_KEY` (consulta
[docs/DOCKER.md](docs/DOCKER.md)); `ekte secret status | export | rotate` la
gestionan desde la línea de comandos.

## Auditorías de embeddings, rerank, imagen y audio

Estos endpoints devuelven vectores, clasificaciones, imágenes o audio en lugar de
chat, así que ekte los audita con sondas específicas en lugar de los prompts de
chat. Cada uno imprime un veredicto y admite `--json` y `--fail-on-risk`.

### Tipo de endpoint (superficie), monitores de embeddings y rerank

Cada auditoría, fila del historial y monitor tiene un **tipo de endpoint**
(`surface`): `chat` (por defecto), `embedding` o `rerank`. Es independiente de la
suite. Las auditorías de embeddings y rerank pasan por el mismo runner, la misma
puntuación (0–100, A–F), el historial, la analítica y los monitores que las de
chat; solo cambian los detectores. El historial y la analítica filtran por tipo de
endpoint, y la analítica muestra solo las métricas que aplican.

Para vigilar un endpoint de embeddings o rerank, audítelo en la página
**Auditoría** (elija **Embeddings** o **Reordenación** en el selector de tipo de
endpoint) y elija
**Monitorizar**, o **Programar como monitor** en su fila
del historial. El monitor repite la auditoría según su calendario, con la misma
fijación de la base de conocimiento, el mismo umbral de alerta y las mismas
alertas de regresión que un monitor de chat, y comprueba la **deriva** frente a
su ejecución anterior (los vectores de una sonda de embeddings, la clasificación y
las puntuaciones de una sonda de rerank). La dimensión declarada de un monitor de
embeddings se puede cambiar en su tarjeta (vacía o 0: de la base de
conocimiento). Las sondas de velocidad (embeddings: latencia, arranque en frío,
entradas/s, escalado por lotes; rerank: latencia, arranque en frío, documentos/s,
4 frente a 32 documentos) solo se ejecutan en las suites deep, full o custom, o en
standard con una referencia.

### Embeddings y rerank

```bash
# La dimensión de vector esperada se resuelve desde la base de conocimiento para el modelo declarado.
ekte embed --base-url https://relay.example.com/v1 \
           --model text-embedding-3-large --claimed-model text-embedding-3-large --fail-on-risk high

# O indicar directamente la dimensión esperada:
ekte embed --base-url ... --model my-embed --claimed-dimensions 1024 --json

# Rerank: una sonda integrada de respuesta conocida — un reranker auténtico debe poner
# primero el documento evidentemente relevante.
ekte rerank --base-url https://relay.example.com/v1 --model my-rerank

# Más a fondo: añade la sonda de velocidad de rerank; --no-save deja la ejecución fuera del historial.
ekte rerank --base-url ... --model my-rerank --suite deep --no-save
# Ver antes las comprobaciones y las llamadas estimadas, sin enviar ninguna petición:
ekte rerank --base-url ... --model my-rerank --dry-run
```

`rerank` comprueba la conectividad, la **sonda de respuesta conocida** (el
documento obviamente relevante debe quedar primero), el campo `model` devuelto,
el determinismo (la misma consulta dos veces da la misma clasificación y las
mismas puntuaciones) y la **deriva de la clasificación** frente a la ejecución
guardada anterior. `ekte embed` y `ekte rerank` aceptan `--suite`,
`--save/--no-save` (se guarda por defecto, para que la siguiente ejecución tenga
una referencia de deriva) y `--dry-run`.

`embed` comprueba la conectividad, la **coincidencia de dimensión** (longitud del
vector devuelto frente a la dimensión nativa del modelo declarado — la señal
principal de «gato por liebre»: un relay que declara `text-embedding-3-large` de
3072-d pero devuelve 1024-d sirve un sustituto), el determinismo (misma entrada →
coseno ≈ 1), la distinción (entradas sin relación → coseno claramente inferior a
1) y el campo `model` devuelto. Perfiles integrados: OpenAI
`text-embedding-3-small` (1536), `text-embedding-3-large` (3072),
`text-embedding-ada-002` (1536), Qwen `text-embedding-v3`/`-v4` (1024).

Ambos están también en la interfaz web: empiezan en la página **Auditoría** con
el selector de tipo de endpoint (**Embeddings**, **Reordenación**). La auditoría de rerank usa
siempre las sondas integradas, para que cada ejecución siga siendo comparable para
la deriva y la monitorización.

### Generación de imagen y audio (TTS)

Generación de imágenes (`POST /v1/images/generations`) y texto a voz
(`POST /v1/audio/speech`), decodificados solo con la biblioteca estándar de
Python — dimensiones de imagen a partir de los bytes de cabecera
(PNG/JPEG/GIF/WebP), duración WAV mediante `wave`.

```bash
# ¿Un relay que declara DALL·E 3 devuelve de verdad el 1792x1024 pedido? Una imagen
# reducida o de tamaño incorrecto (o fuera de los tamaños nativos del modelo declarado,
# según la base de conocimiento) es la señal principal de «gato por liebre».
ekte image --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model dall-e-3 --claimed-model dall-e-3 --size 1792x1024 --fail-on-risk high

# ¿Un relay que declara tts-1-hd devuelve audio real cuya duración crece con la entrada
# (no un marcador fijo, ni HTML/JSON disfrazado de audio)?
ekte audio --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model tts-1-hd --voice alloy --audio-format wav --save-to clip.wav
```

`image` comprueba la conectividad, un formato válido y decodificable, la
**coincidencia de tamaño** (ancho × alto decodificados frente a la petición y a
los tamaños nativos del modelo declarado — FAIL/HIGH si no coinciden), la
distinción (dos prompts → imágenes distintas, para descubrir un marcador fijo),
el número y el campo `model`. `audio` comprueba la conectividad, la validez del
contenedor/formato, que se respete el formato, una duración no trivial que crece
con la entrada, la distinción y el campo `model`. La base de conocimiento incluye
OpenAI DALL·E 2/3, gpt-image-1, tts-1/tts-1-hd/gpt-4o-mini-tts y perfiles de
imagen/TTS de Qwen.

## Uso en CI (GitHub Action)

Condiciona cualquier workflow a una auditoría de relay con la action compuesta
incluida. Ejecuta `ekte check --compact --fail-on-risk`, expone `risk` / `score` /
`rating` como salidas, escribe un resumen en la ejecución y hace fallar el job
cuando salta la barrera de riesgo.

```yaml
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - id: ekte
        uses: mn567250/ekte@vX.Y.Z       # fijar a una etiqueta de versión
        with:
          base-url: https://relay.example.com/v1
          api-key: ${{ secrets.RELAY_API_KEY }}   # secreto del llamante; nunca se muestra
          model: gpt-4o
          fail-on-risk: high
      - run: echo "risk=${{ steps.ekte.outputs.risk }} score=${{ steps.ekte.outputs.score }}"
```

La clave del relay se pasa por una variable de entorno (`--api-key env:…`), así
que nunca aparece en una línea de comandos. Consulta [docs/CI.md](docs/CI.md)
para todas las entradas y salidas y un ejemplo de barrera de despliegue.

## Base de conocimiento

ekte juzga un relay según el **perfil** del modelo que declara: ventana de
contexto nativa, salida máxima, fecha de corte del conocimiento, tokenizer,
capacidades, palabras clave de identidad y huellas de comportamiento. Los
perfiles integrados cubren OpenAI, Anthropic, Google Gemini, DeepSeek, Qwen, GLM
y Moonshot (`ekte kb` los lista). Hay tres capas; las posteriores prevalecen:

1. Perfiles **integrados**, un archivo YAML por proveedor en
   [`ekte/knowledge/data/`](ekte/knowledge/data).
2. **Un directorio con tus propios archivos YAML**: `--kb-dir ./my-profiles`
   (repetible) o `EKTE_KB_DIR`.
3. **Tus entradas** (`kb.db` en el directorio de datos), añadidas sin archivos
   YAML ni instalación editable:
   - en la página **Conocimiento** de la interfaz web (`/kb`), con una pestaña
     para **Modelos**, **Proveedores** y **Relays**. Cada pestaña lista el conjunto
     completo —incluidos, `EKTE_KB_DIR` y los tuyos (marcados **Tuyo**)— con un
     filtro, un interruptor por elemento y un formulario **Añadir …**: **Añadir un
     modelo** → **Copiar el prompt de investigación** en el asistente de IA que
     prefieras, subir o pegar el YAML con el que responde y después **Comprobar y
     guardar**; **Añadir un proveedor** acepta YAML de proveedor del mismo modo;
     **Añadir un relay** pide un nombre y una URL base. **¿Qué perfil usa un ID de
     modelo?** muestra cómo se resuelve un id; tus entradas se pueden exportar
     como YAML;
   - en la página **Auditoría** de la interfaz web:
     **Guardar en la base** conserva el nombre y la URL base de un relay (una
     entrada de proveedor sin modelos), que aparece en **Conocimiento → Relays**;
   - en la línea de comandos: `ekte kb-prompt <model>`, `ekte kb-import <file>`
     (añade `--check` para solo comprobarlo) y `ekte kb-export`.

Antes de guardar una entrada, ekte la comprueba: esquema y límites, expresiones
regulares peligrosas, cada prompt que enviaría e ids de modelo que se
resolverían a otro perfil. Un modelo tuyo con el id de uno integrado lo sustituye
(se indica que lo *oculta*), pero nunca cambia los ajustes propios de un
proveedor integrado; las huellas se fusionan por id. Desactivar un modelo,
proveedor o relay incluido en la página **Conocimiento** también se guarda en
`kb.db`: un id de modelo desactivado ya no se resuelve y un proveedor desactivado
se lleva sus modelos y URL base. `ekte check` y `ekte serve` usan exactamente los
mismos perfiles; `--no-user-kb` (o `EKTE_NO_USER_KB=1`) deja fuera tus entradas e
interruptores.

Un modelo con `identity_keywords` vacío no se guarda así: ekte completa sus
propias palabras de marca a partir de los nombres del proveedor y del modelo
(por ejemplo `glm` y `z.ai`) y muestra una
advertencia para que las revises, ya que sin ellas la comprobación de identidad
podría tomar a su propio fabricante por una marca rival. El prompt de
investigación se las pide expresamente al asistente de IA.

Cada informe registra el perfil contra el que auditó (`knowledge`: proveedor,
modelo, cómo se resolvió el id, su origen y una instantánea completa con su hash
de contenido), de modo que un informe sigue siendo verificable después de que
cambie la base de conocimiento.

## Informes

`ekte check` y `ekte compare` imprimen un veredicto y escriben el informe en
`reports/` (`--out-dir`) como JSON, Markdown, HTML y PDF (`--format all`, el valor
por defecto); `--format json|md|html|pdf` escribe un solo formato. `--json` y
`--compact` imprimen en stdout en su lugar.

```text
╭─ ✗ HIGH RISK — Strong evidence the relay does not deliver the claimed model… ─╮
│ Target : my-relay · model gpt-4o · provider openai                            │
│ Mode   : check · suite deep                                                   │
│ Score  : 53.5/100 (rating F) · confidence medium                             │
│                                                                               │
│ Overall health score 53.5/100. Findings: 3 high. …                            │
╰───────────────────────────────────────────────────────────────────────────────╯
  • Self-identifies as a rival brand (anthropic) under the claimed model id gpt-4o
  • Real context window ~8000 << declared 128000 (silent truncation suspected)
  • Reported prompt tokens far exceed independent estimate
```

Un informe contiene el veredicto (riesgo, confianza, puntuación, nota), los
hallazgos clave con recomendaciones, las puntuaciones por dimensión y los
**Dimension details**, los hallazgos de cada detector con su evidencia, la
sección de rendimiento, el perfil de la base de conocimiento usado y los idiomas
de sonda. El texto controlado por el relay se censura y se escapa antes de
escribirse.

## Privacidad y datos locales

- **Solo local.** `ekte serve` escucha solo en loopback (`127.0.0.1`, `::1`,
  `localhost`), responde solo a esos nombres de host y rechaza peticiones entre
  sitios; no tiene inicio de sesión porque nada fuera de tu máquina puede
  alcanzarlo. ekte solo contacta los endpoints que configuras (objetivo,
  referencia, juez, webhooks); no descarga nada en tiempo de ejecución, ni
  siquiera archivos de tokenizer.
- **Claves.** Los informes y el historial solo guardan una huella de una clave
  API. Las claves de los monitores se guardan cifradas en `watches.db`; la clave
  maestra que las descifra nunca se escribe en el directorio de datos (la
  guardas tú, consulta **Monitorización** más arriba), así que una copia del
  directorio no revela ninguna clave API. Aun así, solo tú tienes acceso al
  directorio.
- **Directorio de datos.** `~/.ekte` (o `EKTE_DATA_DIR`), creado con `0700` y
  archivos con `0600`: `history.db` (historial de auditorías), `watches.db`
  (monitores, con sus claves cifradas) y `kb.db` (tus entradas de la base de
  conocimiento). Borra el directorio para eliminarlo todo.
  `ekte data-dir` muestra dónde está; `--data-dir RUTA` elige otro para una
  ejecución, p. ej. `ekte serve --data-dir .` guarda las bases de datos en la
  carpeta actual. Son archivos SQLite normales que puedes abrir para tus
  propios análisis (mejor solo lectura mientras ekte se ejecuta). No hagas
  commit de `watches.db` si esa carpeta es un repositorio.
  `history_metrics` guarda una fila de valores medidos por ejecución y
  `history_requests` cada registro de petición (guardado ahí una sola vez, no
  dentro de cada informe).

## Uso responsable

ekte es una ayuda de auditoría de caja negra. **No puede probar**:

- que un proveedor guarde tus prompts o entrene con ellos,
- que siempre enrute a un único modelo exacto (los relays pueden enrutar de forma probabilística),
- un fraude de facturación más allá de lo que la estimación independiente de tokens puede sugerir.

Usa los informes para tu propia diligencia debida. **No acuses públicamente a un
proveedor** basándote en una sola ejecución sin revisar el tamaño de la muestra,
la configuración de costes y la legislación local. Ejecuta `ekte compare` contra
una referencia de confianza antes de sacar conclusiones firmes.

## Más documentación

| Documento | Para |
|---|---|
| [Metodología](docs/METHODOLOGY.es.md) | Cómo funciona cada comprobación, su escala de puntuación y sus salvedades |
| [Guía para desarrolladores](DEVELOPER_GUIDE.es.md) | Arquitectura, entorno de desarrollo, contribuciones, traducciones, Docker, versiones |
| [docs/CI.md](docs/CI.md) | La GitHub Action: entradas, salidas, ejemplos (en inglés) |
| [docs/DOCKER.md](docs/DOCKER.md) | Ejecutar la interfaz web en un contenedor (en inglés) |
| [Estabilidad y compatibilidad](docs/STABILITY.md) | Qué protege semver, obsolescencia, versiones de Python y sistemas compatibles, actualizaciones y downgrades (en inglés) |
| [CHANGELOG.md](CHANGELOG.md) | Qué cambió en cada versión (en inglés) |
| [SECURITY.md](SECURITY.md) | Informar de una vulnerabilidad (en inglés) |

## Si vienes de zing

ekte continúa [zing](https://github.com/cenbonew/zing) (su última versión fue la
0.11.0) con un nombre nuevo. Qué cambia en una instalación existente:

- **Paquete y comando.** `pip install ekte` (antes `zing-audit`), el comando
  `ekte` (antes `zing`), el paquete de Python `ekte`. Los extras conservan su
  nombre, p. ej. `pip install 'ekte[web]'`. Los dos paquetes no comparten
  comando ni módulo, así que `zing-audit` puede seguir instalado junto a ekte.
- **Variables de entorno.** `EKTE_*` sustituye a `ZING_*` (`EKTE_DATA_DIR`,
  `EKTE_SECRET_KEY`, `EKTE_HOST`, …). Una variable `ZING_*` antigua sigue
  funcionando mientras su nombre `EKTE_*` no esté definido; ekte la menciona una
  vez en stderr.
- **Directorio de datos.** En su primera ejecución, ekte copia `~/.zing` a
  `~/.ekte` (historial, monitores, base de conocimiento) si `~/.ekte` aún no
  existe, y desde entonces trabaja solo con `~/.ekte`. `~/.zing` queda tal cual,
  para zing si todavía se ejecuta; bórralo tú cuando ya no lo necesites. Un
  directorio indicado con `EKTE_DATA_DIR`, `ZING_DATA_DIR` o `--data-dir` se usa
  tal como está.
- **Interfaz web.** Se conservan el idioma, el tema y los filtros, y una clave
  maestra guardada en el gestor de contraseñas del navegador. La interfaz clásica
  de zing ya no existe: sus direcciones (`/tools`, `/console`) abren la página de auditoría (`/`).
- **Informes y sondeos.** Los informes, los webhooks y los nombres de archivo
  dicen `ekte` (p. ej. `"tool": "ekte"`, `ekte-report.json`), igual que los
  sondeos enviados a los relays. Los scripts que buscan `zing` en ellos deben
  actualizarse.
- **Calendario.** Toda la capa de compatibilidad (la lectura de `ZING_*`, la copia de `~/.zing`, el traspaso de ajustes del navegador, cookies y la clave maestra guardada, y las direcciones de la interfaz clásica) está obsoleta y se elimina en ekte **1.0.0** (1.0.0rc1 es la primera versión sin ella). Hasta entonces cada parte sigue funcionando y su aviso nombra esta versión; las antiguas direcciones de página `/v2/…` también redirigen hasta 1.0.0. ekte nunca borra un `~/.zing` antiguo, tampoco cuando se elimina la copia.

## Licencia

[Apache-2.0](LICENSE)
