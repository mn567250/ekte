# Condicionar a CI a uma auditoria de relay do ekte

> [🇬🇧 English](../../../guide/github-action.md) · [🇨🇳 中文](../../zh-CN/guide/github-action.md) · [🇫🇷 Français](../../fr/guide/github-action.md) · [🇪🇸 Español](../../es/guide/github-action.md) · **🇵🇹 Português** · [🇮🇹 Italiano](../../it/guide/github-action.md) · [🇩🇪 Deutsch](../../de/guide/github-action.md) · [🇳🇴 Norsk](../../nb/guide/github-action.md)

O `ekte` inclui uma **GitHub composite action** reutilizável, para que possa
fazer falhar uma build, bloquear um deploy ou executar uma verificação de saúde
agendada sempre que um relay se afaste do modelo que declara servir.

Por baixo, a action executa:

```
ekte check --base-url … --api-key env:… --model … --suite … \
           --fail-on-risk <level> --compact
```

Analisa o veredito JSON compacto, expõe `risk` / `score` / `rating` como saídas
do passo, escreve um resumo conciso no separador **Summary** da execução e deixa
que o próprio código de saída do `ekte` faça falhar o job (saída `1` quando o
limiar de risco é atingido, `2` num erro de configuração).

> A chave API é passada ao `ekte` através de uma variável de ambiente
> (`--api-key env:…`), pelo que nunca aparece numa linha de comandos e nunca é
> ecoada. Forneça-a sempre a partir de um segredo do repositório.

## Início rápido

```yaml
# .github/workflows/relay-audit.yml
name: Relay audit
on:
  schedule:
    - cron: "0 6 * * *"   # diariamente às 06:00 UTC
  workflow_dispatch:

permissions:
  contents: read

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - id: ekte
        uses: mn567250/ekte@v0.33.1   # fixe numa tag — ver «Fixar a versão» abaixo
        with:
          base-url: https://relay.example.com/v1
          api-key: ${{ secrets.RELAY_API_KEY }}
          model: gpt-4o
          fail-on-risk: high
      - run: echo "risk=${{ steps.ekte.outputs.risk }} score=${{ steps.ekte.outputs.score }}"
```

## Entradas

| Entrada             | Obrigatória | Por omissão   | Descrição |
| ------------------- | ----------- | ------------- | --------- |
| `base-url`          | sim         | —             | URL base do relay, p. ex. `https://relay.example.com/v1`. |
| `api-key`           | sim         | —             | Chave API do relay. Passe um segredo: `${{ secrets.RELAY_API_KEY }}`. Nunca é ecoada. |
| `model`             | sim         | —             | Id do modelo efetivamente enviado nos pedidos. |
| `claimed-model`     | não         | `""`          | Modelo que o relay declara servir, se for diferente de `model`. |
| `api`               | não         | `auto`        | Protocolo: `auto` \| `openai` \| `anthropic` \| `responses`. |
| `declared-provider` | não         | `""`          | Indicação do fornecedor para a consulta da base de conhecimento (`openai`, `anthropic`, `deepseek`, …). |
| `suite`             | não         | `standard`    | Suite de detetores: `smoke` \| `standard` \| `deep` \| `full`. |
| `fail-on-risk`      | não         | `high`        | Faz falhar o job quando o risco é `>=` este nível: `low` \| `medium` \| `high`. |
| `python-version`    | não         | `3.12`        | Versão de Python usada para instalar e executar o `ekte`. |
| `version`           | não         | `ekte`        | Especificação de instalação pip. Fixe-a para execuções reproduzíveis, p. ex. `ekte==0.33.1`. |

## Saídas

| Saída    | Descrição |
| -------- | --------- |
| `risk`   | Nível de risco: `clean` \| `low` \| `medium` \| `high` \| `inconclusive`. |
| `score`  | Pontuação global `0`–`100` (cadeia vazia se o `ekte` não conseguiu pontuar o relay). |
| `rating` | Classificação legível do veredito (pode estar vazia). |

## Condicionar um deploy à saúde do relay

Execute primeiro a auditoria; faça o deploy só quando ela passar. Como o passo de
auditoria faz falhar o job quando o limiar de risco é atingido, um job dependente
que dele precise (`needs:`) simplesmente não corre.

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
        uses: mn567250/ekte@v0.33.1
        with:
          base-url: https://relay.example.com/v1
          api-key: ${{ secrets.RELAY_API_KEY }}
          model: gpt-4o
          claimed-model: gpt-4o
          fail-on-risk: medium   # bloquear o deploy com risco médio ou pior
    outputs:
      risk: ${{ steps.ekte.outputs.risk }}
      score: ${{ steps.ekte.outputs.score }}

  deploy:
    needs: relay-health          # só corre se a auditoria tiver passado o limiar
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo "Relay is healthy (risk=${{ needs.relay-health.outputs.risk }}, \
            score=${{ needs.relay-health.outputs.score }}). Deploying…"
          # ./deploy.sh
```

## Fixar a versão

Fixe a action numa **tag de versão** (`mn567250/ekte@v0.33.1`) em vez de num ramo
que muda. Isto mantém as auditorias reproduzíveis e protege-o de alterações
inesperadas à action. Uma tag pode ser movida; para a proteção mais estrita da
cadeia de fornecimento, fixe o SHA completo do commit da versão, com a versão num
comentário (`mn567250/ekte@<full-commit-sha> # v0.33.1`), e deixe o Dependabot
mantê-lo atualizado. Para um comportamento da CLI totalmente reproduzível, fixe
também a entrada `version` numa versão exata, p. ex. `version: ekte==0.33.1`.

Um exemplo agendado pronto a copiar encontra-se em
[`.github/workflows/example-audit.yml`](../../../../.github/workflows/example-audit.yml).
