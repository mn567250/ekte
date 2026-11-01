# Inicio rápido

> [🇬🇧 English](../../../guide/quickstart.md) · [🇨🇳 中文](../../zh-CN/guide/quickstart.md) · [🇫🇷 Français](../../fr/guide/quickstart.md) · **🇪🇸 Español** · [🇵🇹 Português](../../pt/guide/quickstart.md) · [🇮🇹 Italiano](../../it/guide/quickstart.md) · [🇩🇪 Deutsch](../../de/guide/quickstart.md) · [🇳🇴 Norsk](../../nb/guide/quickstart.md)

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
configuración completo en [`examples/ekte.yaml`](../../../../examples/ekte.yaml).

El archivo tiene una versión de formato (`version: 1`; un archivo sin versión es el formato 1). Los tipos incorrectos y los valores no válidos se rechazan indicando archivo, línea y clave; las claves desconocidas se ignoran con una advertencia hasta ekte 1.0.0, que las rechaza. `ekte config migrate` actualiza un archivo antiguo. El esquema es [`docs/schemas/config.schema.json`](../../../schemas/config.schema.json).

## Como herramienta para un LLM / agente

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
