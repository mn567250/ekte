# Condicionar la CI a una auditoría de relay con ekte

> [🇬🇧 English](../../../guide/github-action.md) · [🇨🇳 中文](../../zh-CN/guide/github-action.md) · [🇫🇷 Français](../../fr/guide/github-action.md) · **🇪🇸 Español** · [🇵🇹 Português](../../pt/guide/github-action.md) · [🇮🇹 Italiano](../../it/guide/github-action.md) · [🇩🇪 Deutsch](../../de/guide/github-action.md) · [🇳🇴 Norsk](../../nb/guide/github-action.md)

`ekte` incluye una **acción compuesta de GitHub** reutilizable para que puedas
hacer fallar una compilación, bloquear un despliegue o ejecutar una comprobación
de salud programada cada vez que un relay se aparte del modelo que dice servir.

Por debajo, la acción ejecuta:

```
ekte check --base-url … --api-key env:… --model … --suite … \
           --fail-on-risk <level> --compact
```

Analiza el veredicto JSON compacto, expone `risk` / `score` / `rating` como
salidas del paso, escribe un resumen conciso en la pestaña **Summary** de la
ejecución y deja que el propio código de salida de `ekte` haga fallar el job
(salida `1` cuando salta la barrera de riesgo, `2` ante un error de
configuración).

> La clave API se pasa a `ekte` mediante una variable de entorno
> (`--api-key env:…`), así que nunca aparece en una línea de comandos ni se
> muestra. Proporciónala siempre desde un secreto del repositorio.

## Inicio rápido

```yaml
# .github/workflows/relay-audit.yml
name: Relay audit
on:
  schedule:
    - cron: "0 6 * * *"   # cada día a las 06:00 UTC
  workflow_dispatch:

permissions:
  contents: read

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - id: ekte
        uses: mn567250/ekte@v0.33.0   # fija una etiqueta — consulta «Fijar la versión» más abajo
        with:
          base-url: https://relay.example.com/v1
          api-key: ${{ secrets.RELAY_API_KEY }}
          model: gpt-4o
          fail-on-risk: high
      - run: echo "risk=${{ steps.ekte.outputs.risk }} score=${{ steps.ekte.outputs.score }}"
```

## Entradas

| Entrada             | Obligatoria | Por defecto | Descripción |
| ------------------- | ----------- | ----------- | ----------- |
| `base-url`          | sí          | —           | URL base del relay, p. ej. `https://relay.example.com/v1`. |
| `api-key`           | sí          | —           | Clave API del relay. Pasa un secreto: `${{ secrets.RELAY_API_KEY }}`. Nunca se muestra. |
| `model`             | sí          | —           | Id del modelo que se envía realmente en las peticiones. |
| `claimed-model`     | no          | `""`        | Modelo que el relay dice servir, si es distinto de `model`. |
| `api`               | no          | `auto`      | Protocolo: `auto` \| `openai` \| `anthropic` \| `responses`. |
| `declared-provider` | no          | `""`        | Pista de proveedor para buscar en la KB (`openai`, `anthropic`, `deepseek`, …). |
| `suite`             | no          | `standard`  | Suite de detectores: `smoke` \| `standard` \| `deep` \| `full`. |
| `fail-on-risk`      | no          | `high`      | Hace fallar el job cuando el riesgo es `>=` este nivel: `low` \| `medium` \| `high`. |
| `python-version`    | no          | `3.12`      | Versión de Python usada para instalar y ejecutar `ekte`. |
| `version`           | no          | `ekte`      | Especificación de pip install. Fíjala para ejecuciones reproducibles, p. ej. `ekte==0.33.0`. |

## Salidas

| Salida   | Descripción |
| -------- | ----------- |
| `risk`   | Nivel de riesgo: `clean` \| `low` \| `medium` \| `high` \| `inconclusive`. |
| `score`  | Puntuación global `0`–`100` (cadena vacía si `ekte` no pudo puntuar el relay). |
| `rating` | Valoración legible del veredicto (puede estar vacía). |

## Condicionar un despliegue a la salud del relay

Ejecuta primero la auditoría; despliega solo cuando la supere. Como el paso de
auditoría hace fallar el job cuando salta la barrera de riesgo, un job
dependiente que la declare en `needs:` simplemente no se ejecuta.

```yaml
name: Deploy
on:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  relay-health:
    runs-on: ubuntu-latest
    steps:
      - id: ekte
        uses: mn567250/ekte@v0.33.0
        with:
          base-url: https://relay.example.com/v1
          api-key: ${{ secrets.RELAY_API_KEY }}
          model: gpt-4o
          claimed-model: gpt-4o
          fail-on-risk: medium   # bloquea el despliegue con riesgo medio o peor
    outputs:
      risk: ${{ steps.ekte.outputs.risk }}
      score: ${{ steps.ekte.outputs.score }}

  deploy:
    needs: relay-health          # solo se ejecuta si la auditoría superó la barrera
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo "Relay is healthy (risk=${{ needs.relay-health.outputs.risk }}, \
            score=${{ needs.relay-health.outputs.score }}). Deploying…"
          # ./deploy.sh
```

## Fijar la versión

Fija la acción a una **etiqueta de versión** (`mn567250/ekte@v0.33.0`) en lugar de
a una rama que se mueve. Así las auditorías son reproducibles y te proteges de
cambios inesperados en la acción. Una etiqueta puede moverse; para la protección
más estricta de la cadena de suministro, fija el SHA completo del commit de la
versión con la versión en un comentario
(`mn567250/ekte@<full-commit-sha> # v0.33.0`) y deja que Dependabot lo mantenga al
día. Para un comportamiento de la CLI totalmente reproducible, fija también la
entrada `version` a una versión exacta, p. ej. `version: ekte==0.33.0`.

Tienes un ejemplo programado listo para copiar en
[`.github/workflows/example-audit.yml`](../../../../.github/workflows/example-audit.yml).
