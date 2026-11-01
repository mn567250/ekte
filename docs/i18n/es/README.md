# ekte — verificación de la realidad de los relays de LLM

> [🇬🇧 English](../../../README.md) · [🇨🇳 中文](../zh-CN/README.md) · [🇫🇷 Français](../fr/README.md) · **🇪🇸 Español** · [🇵🇹 Português](../pt/README.md) · [🇮🇹 Italiano](../it/README.md) · [🇩🇪 Deutsch](../de/README.md) · [🇳🇴 Norsk](../nb/README.md)

[![CI](https://github.com/mn567250/ekte/actions/workflows/ci.yml/badge.svg)](https://github.com/mn567250/ekte/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](../../../LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](../../../pyproject.toml)

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
> criptográfica de fraude.** Consulta [Uso responsable](guide/privacy.md#uso-responsable).

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

Requiere Python 3.11+ en Linux, macOS o Windows.

```bash
pip install 'ekte[web]'          # o: uv tool install 'ekte[web]'
```

El extra `web` añade la interfaz web local; omítelo si solo quieres la línea de
comandos. Desde el código fuente, con uv o en Docker: [Instalación](guide/install.md).

## Inicio rápido

```bash
export EKTE_API_KEY=sk-tu-clave-del-relay

# auditar un relay frente al modelo que dice servir
ekte check --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY \
  --model gpt-4o --suite standard

# la comprobación más fuerte: comparar con una referencia de confianza del mismo modelo
export OPENAI_API_KEY=sk-tu-clave-de-openai
ekte compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:EKTE_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o

# o con el ratón: la interfaz web local
ekte serve
```

Más ejemplos, archivos de configuración y uso desde scripts o agentes LLM:
[Inicio rápido](guide/quickstart.md). La interfaz web: [Interfaz web](guide/web-ui.md).

## Qué comprueba

ekte puntúa diez dimensiones. Las cuatro **dimensiones núcleo** — identidad del
modelo, ventana de contexto, capacidades declaradas y facturación y uso — revelan
más directamente un «gato por liebre». Los nombres son los de la interfaz
web y los informes.

| Dimensión | Id | Qué detecta |
|---|---|---|
| **Identidad del modelo** | `model_identity` | Degradación o sustitución silenciosa del modelo |
| **Ventana de contexto** | `context_window` | Recorte silencioso del contexto y «lost in the middle» |
| **Capacidades declaradas** | `capability` | Llamadas a herramientas, modo JSON, salida máxima o visión declarados pero no entregados |
| **Conformidad del protocolo** | `protocol` | Parámetros de petición y atributos de respuesta descartados o ignorados |
| **Facturación y uso** | `billing` | Uso de tokens inflado o ausente |
| **Conectividad** | `connectivity` | Accesibilidad del endpoint y la lista de modelos anunciada |
| **Autenticidad del streaming** | `streaming` | Streaming falso (búfer y luego troceo) |
| **Fiabilidad en concurrencia** | `reliability` | Fallos y ralentizaciones bajo carga concurrente |
| **Seguridad del transporte** | `security` | HTTP sin cifrar, eco de secretos, prompts de sistema inyectados, manipulación |
| **Rendimiento** | `performance` | Lo constantes que son la latencia, el tiempo hasta el primer token y el throughput |

Cómo funciona cada comprobación y cómo se llega al veredicto:
[Metodología](guide/methodology.md).

## Documentación

| Guía de usuario | |
|---|---|
| [Instalación](guide/install.md) | pip, uv, desde el código fuente, extras opcionales |
| [Inicio rápido](guide/quickstart.md) | Primeras auditorías, archivos de configuración, uso desde scripts y agentes LLM |
| [Interfaz web](guide/web-ui.md) | Páginas, auditorías en segundo plano, analíticas, idiomas |
| [Suites y modo de comparación](guide/suites.md) | Suites, suite personalizada, referencia de confianza, juez LLM |
| [Rendimiento](guide/performance.md) | La sección de rendimiento, la sonda y los timeouts de las peticiones |
| [Monitorización](guide/monitoring.md) | Reauditorías programadas, alertas por webhook, almacenamiento de claves API |
| [Auditorías de embeddings, rerank, imagen y audio](guide/other-endpoints.md) | Auditorías de endpoints que no son de chat |
| [Base de conocimiento](guide/knowledge-base.md) | Perfiles de modelos y cómo añadir los tuyos |
| [Informes](guide/reports.md) | Formatos y contenido de los informes |
| [Privacidad y datos locales](guide/privacy.md) | Qué se queda en tu máquina; uso responsable |
| [GitHub Action](guide/github-action.md) | Condicionar un workflow de CI a una auditoría del relay |
| [Docker](guide/docker.md) | Ejecutar la interfaz web en un contenedor |
| [Metodología](guide/methodology.md) | Cada comprobación, su escala de puntuación y sus salvedades |
| [Si vienes de zing](guide/migrating-from-zing.md) | Qué cambia para una instalación de zing existente |

| Referencia (en inglés) | |
|---|---|
| [Línea de comandos](../../reference/cli.md) | Todos los comandos y opciones, y los códigos de salida |
| [Esquemas del informe y del webhook](../../reference/schemas.md) | Los formatos JSON y su `schema_version` |
| [Estabilidad y compatibilidad](../../reference/stability.md) | Qué protege semver, obsolescencia, versiones de Python y sistemas compatibles |
| [Registro de cambios](../../../CHANGELOG.md) | Qué cambió en cada versión |

Contribuir: [Guía de contribución](../../CONTRIBUTING.md) y
[Guía para desarrolladores](../../dev/developer-guide.md) (en inglés).
Problemas de seguridad: [Política de seguridad](../../SECURITY.md).

## Licencia

[Apache-2.0](../../../LICENSE)
