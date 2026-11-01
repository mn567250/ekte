# ekte — verificação da realidade dos relays de LLM

> [🇬🇧 English](../../../README.md) · [🇨🇳 中文](../zh-CN/README.md) · [🇫🇷 Français](../fr/README.md) · [🇪🇸 Español](../es/README.md) · **🇵🇹 Português** · [🇮🇹 Italiano](../it/README.md) · [🇩🇪 Deutsch](../de/README.md) · [🇳🇴 Norsk](../nb/README.md)

[![CI](https://github.com/mn567250/ekte/actions/workflows/ci.yml/badge.svg)](https://github.com/mn567250/ekte/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](../../../LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](../../../pyproject.toml)

O **ekte** é uma ferramenta local-first que audita se um relay de API
(revendedor / proxy) serve realmente o modelo que declara — ou se o substitui
discretamente por um mais barato, trunca a sua janela de contexto, simula o
streaming ou inflaciona a faturação de tokens. Em suma: recebe aquilo por que
paga? Fala a **API OpenAI Chat Completions**, a **API Anthropic Messages** e a
**API OpenAI Responses** (`/v1/responses`) — com deteção automática, ou forçada
com `--api openai|anthropic|responses`.

Indica-lhe o endpoint de um relay e o modelo que ele diz servir; o ekte executa
uma bateria de sondas de caixa-preta, compara o comportamento observado com uma
base de conhecimento integrada de **130 perfis de modelos de 7 fornecedores** e
dá um veredito claro, apoiado em evidências — na linha de comandos, numa
interface web local ou em JSON para outra ferramenta ou LLM.

> O ekte fornece **evidências de caixa-preta de desvios e riscos, não uma prova
> criptográfica de fraude.** Consulte [Utilização responsável](guide/privacy.md#utilização-responsável).

## Porquê

O mercado de chaves de relay está cheio de ofertas de «GPT-4o a um décimo do
preço». Muitas são honestas. Outras não — e as desonestas são difíceis de
detetar a olho nu:

- Pede `gpt-4o`; discretamente, servem-lhe `gpt-4o-mini` ou um modelo aberto.
- O relay anuncia um contexto de 1M de tokens mas trunca discretamente para 32K.
- O «streaming» é a resposta completa em buffer, voltada a partir em pedaços, sem ganho de latência.
- Os tokens de `usage` reportados estão inflacionados, pelo que o seu saldo se esgota mais depressa do que devia.
- Um modelo que devia suportar chamadas de ferramentas / modo JSON discretamente não o faz.

O ekte transforma «há aqui algo que não bate certo» num relatório reproduzível.

## Instalação

Requer Python 3.11+ em Linux, macOS ou Windows.

```bash
pip install 'ekte[web]'          # ou: uv tool install 'ekte[web]'
```

O extra `web` acrescenta a interface web local; omita-o se só quiser a linha de
comandos. A partir do código-fonte, com uv ou em Docker: [Instalação](guide/install.md).

## Início rápido

```bash
export EKTE_API_KEY=sk-your-relay-key

# auditar um relay face ao modelo que declara servir
ekte check --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY \
  --model gpt-4o --suite standard

# a verificação mais forte: comparar com uma referência de confiança do mesmo modelo
export OPENAI_API_KEY=sk-your-openai-key
ekte compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:EKTE_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o

# ou apontar e clicar: a interface web local
ekte serve
```

Mais exemplos, ficheiros de configuração e utilização a partir de scripts ou de
agentes LLM: [Início rápido](guide/quickstart.md). A interface web:
[Interface web](guide/web-ui.md).

## O que é verificado

O ekte pontua dez dimensões. As quatro **dimensões núcleo** — identidade do
modelo, janela de contexto, capacidades declaradas e faturação e utilização —
revelam mais diretamente um «gato por lebre». Os nomes são os da interface web e
dos relatórios.

| Dimensão | Id | O que deteta |
|---|---|---|
| **Identidade do modelo** | `model_identity` | Despromoção ou substituição silenciosa do modelo |
| **Janela de contexto** | `context_window` | Truncagem silenciosa do contexto e «lost in the middle» |
| **Capacidades declaradas** | `capability` | Chamadas de ferramentas, modo JSON, saída máxima ou visão declarados mas não entregues |
| **Conformidade do protocolo** | `protocol` | Parâmetros do pedido e atributos da resposta descartados ou ignorados |
| **Faturação e utilização** | `billing` | Utilização de tokens inflacionada ou ausente |
| **Conectividade** | `connectivity` | Acessibilidade do endpoint e a lista de modelos anunciada |
| **Autenticidade do streaming** | `streaming` | Streaming falso (buffer e depois partição) |
| **Fiabilidade em concorrência** | `reliability` | Falhas e abrandamentos sob carga concorrente |
| **Segurança do transporte** | `security` | HTTP simples, eco de segredos, prompts de sistema injetados, adulteração |
| **Desempenho** | `performance` | Quão constantes são a latência, o tempo até ao primeiro token e o débito |

Como funciona cada verificação e como se chega ao veredito:
[Metodologia](guide/methodology.md).

## Documentação

| Guia do utilizador | |
|---|---|
| [Instalação](guide/install.md) | pip, uv, a partir do código-fonte, extras opcionais |
| [Início rápido](guide/quickstart.md) | Primeiras auditorias, ficheiros de configuração, utilização por scripts e agentes LLM |
| [Interface web](guide/web-ui.md) | Páginas, auditorias em segundo plano, análises, idiomas |
| [Suites e modo de comparação](guide/suites.md) | Suites, suite personalizada, referência de confiança, juiz LLM |
| [Desempenho](guide/performance.md) | A secção de desempenho, a sonda e os timeouts dos pedidos |
| [Monitorização](guide/monitoring.md) | Reauditorias agendadas, alertas por webhook, armazenamento das chaves API |
| [Auditorias de embeddings, rerank, imagem e áudio](guide/other-endpoints.md) | Auditorias de endpoints que não são de chat |
| [Base de conhecimento](guide/knowledge-base.md) | Perfis de modelos e como acrescentar os seus |
| [Relatórios](guide/reports.md) | Formatos e conteúdo dos relatórios |
| [Privacidade e dados locais](guide/privacy.md) | O que fica na sua máquina; utilização responsável |
| [GitHub Action](guide/github-action.md) | Condicionar um workflow de CI a uma auditoria de relay |
| [Docker](guide/docker.md) | Executar a interface web num contentor |
| [Metodologia](guide/methodology.md) | Cada verificação, a sua escala de pontuação e as suas ressalvas |
| [Se vem do zing](guide/migrating-from-zing.md) | O que muda para uma instalação zing existente |

| Referência (em inglês) | |
|---|---|
| [Linha de comandos](../../reference/cli.md) | Todos os comandos e opções, e os códigos de saída |
| [Esquemas do relatório e do webhook](../../reference/schemas.md) | Os formatos JSON e a sua `schema_version` |
| [Estabilidade e compatibilidade](../../reference/stability.md) | O que o semver protege, descontinuação, versões de Python e sistemas suportados |
| [Registo de alterações](../../../CHANGELOG.md) | O que mudou em cada versão |

Contribuir: [Guia de contribuição](../../CONTRIBUTING.md) e
[Guia do programador](../../dev/developer-guide.md) (em inglês).
Problemas de segurança: [Política de segurança](../../SECURITY.md).

## Licença

[Apache-2.0](../../../LICENSE)
