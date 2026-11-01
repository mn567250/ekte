# Suites y modo de comparación

> [🇬🇧 English](../../../guide/suites.md) · [🇨🇳 中文](../../zh-CN/guide/suites.md) · [🇫🇷 Français](../../fr/guide/suites.md) · **🇪🇸 Español** · [🇵🇹 Português](../../pt/guide/suites.md) · [🇮🇹 Italiano](../../it/guide/suites.md) · [🇩🇪 Deutsch](../../de/guide/suites.md) · [🇳🇴 Norsk](../../nb/guide/suites.md)

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

## Suite personalizada

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
(**Dimensiones a ejecutar**) en la página de auditoría y los
monitores.

La **puntuación global es la media ponderada solo de las dimensiones elegidas**;
las que dejas fuera aparecen como «no seleccionadas». El veredicto de riesgo
también se basa en las dimensiones elegidas: sin la identidad del modelo solo
las cubre a ellas, no qué modelo se sirve, y lo indica.

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
