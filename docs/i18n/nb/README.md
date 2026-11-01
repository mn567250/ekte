# ekte — realitetssjekk for LLM-releer

> [🇬🇧 English](../../../README.md) · [🇨🇳 中文](../zh-CN/README.md) · [🇫🇷 Français](../fr/README.md) · [🇪🇸 Español](../es/README.md) · [🇵🇹 Português](../pt/README.md) · [🇮🇹 Italiano](../it/README.md) · [🇩🇪 Deutsch](../de/README.md) · **🇳🇴 Norsk**

[![CI](https://github.com/mn567250/ekte/actions/workflows/ci.yml/badge.svg)](https://github.com/mn567250/ekte/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](../../../LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](../../../pyproject.toml)

**ekte** er et verktøy som kjører lokalt og reviderer om et API-relé
(forhandler / proxy) faktisk leverer modellen det sier det leverer — eller i det
stille bytter den ut med en billigere, kutter kontekstvinduet ditt, forfalsker
strømming eller blåser opp tokenfaktureringen. Kort sagt: får du det du har betalt
for? Den snakker **OpenAI Chat Completions API**, **Anthropic Messages API** og
**OpenAI Responses API** (`/v1/responses`) — gjenkjent automatisk, eller tvunget
med `--api openai|anthropic|responses`.

Du peker den mot et reléendepunkt og modellen det sier det leverer; ekte kjører
et sett med black box-prober, sammenligner det den observerer med en medfølgende
kunnskapsbase med **130 modellprofiler fra 7 leverandører**, og gir en tydelig
konklusjon underbygd med bevis — på kommandolinjen, i et lokalt nettgrensesnitt
eller som JSON for et annet verktøy eller en LLM.

> ekte rapporterer **black box-bevis på avvik og risiko, ikke kryptografiske
> bevis på svindel.** Se [Ansvarlig bruk](guide/privacy.md#ansvarlig-bruk).

## Hvorfor

Markedet for relénøkler er fullt av tilbud om «GPT-4o til en tidel av prisen».
Mange er ærlige. Noen er det ikke — og de uærlige er vanskelige å avsløre med det
blotte øye:

- Du ber om `gpt-4o`; i det stille får du `gpt-4o-mini` eller en åpen modell.
- Reléet annonserer en kontekst på 1M tokens, men kutter stille ned til 32K.
- «Strømming» er hele svaret bufret og delt opp på nytt, uten noen gevinst i forsinkelse.
- De rapporterte `usage`-tokenene er blåst opp, så saldoen din brennes raskere enn den burde.
- En modell som skal støtte verktøykall / JSON-modus, gjør det i det stille ikke.

ekte gjør «dette føles feil» om til en reproduserbar rapport.

## Installasjon

Krever Python 3.11+ på Linux, macOS eller Windows.

```bash
pip install 'ekte[web]'          # eller: uv tool install 'ekte[web]'
```

Tillegget `web` legger til det lokale nettgrensesnittet; utelat det hvis du bare
vil bruke kommandolinjen. Fra kildekoden, med uv eller i Docker:
[Installasjon](guide/install.md).

## Kom i gang

```bash
export EKTE_API_KEY=sk-your-relay-key

# revider et relé mot modellen det sier det leverer
ekte check --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY \
  --model gpt-4o --suite standard

# den sterkeste kontrollen: sammenlign med en pålitelig referanse for samme modell
export OPENAI_API_KEY=sk-your-openai-key
ekte compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:EKTE_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o

# eller pek og klikk: det lokale nettgrensesnittet
ekte serve
```

Flere eksempler, konfigurasjonsfiler og bruk fra skript eller LLM-agenter:
[Kom i gang](guide/quickstart.md). Nettgrensesnittet: [Nettgrensesnitt](guide/web-ui.md).

## Hva den kontrollerer

ekte gir score i ti dimensjoner. De fire **kjernedimensjonene** — modellidentitet,
kontekstvindu, påståtte egenskaper og fakturering og forbruk — avslører mest
direkte en falsk vare. Navnene er de nettgrensesnittet og rapportene bruker.

| Dimensjon | ID | Hva den fanger |
|---|---|---|
| **Modellidentitet** | `model_identity` | Stille nedgradering eller bytte av modell |
| **Kontekstvindu** | `context_window` | Stille avkorting av kontekst og lost-in-the-middle |
| **Påståtte egenskaper** | `capability` | Verktøykall, JSON-modus, maks utdata eller syn som ikke innfris |
| **Protokollsamsvar** | `protocol` | Forespørselsparametere og svarattributter som droppes eller ignoreres |
| **Fakturering og forbruk** | `billing` | Oppblåst eller manglende tokenforbruk |
| **Tilkobling** | `connectivity` | Om endepunktet kan nås, og den annonserte modellisten |
| **Ekte strømming** | `streaming` | Forfalsket strømming (bufre og så dele opp) |
| **Pålitelighet ved samtidighet** | `reliability` | Feil og nedbremsing under samtidig last |
| **Transportsikkerhet** | `security` | Ukryptert HTTP, ekko av hemmeligheter, injiserte systemprompter, manipulering |
| **Ytelse** | `performance` | Hvor jevne forsinkelse, tid til første token og gjennomstrømning er |

Hvordan hver kontroll fungerer og hvordan konklusjonen nås:
[Metodikk](guide/methodology.md).

## Dokumentasjon

| Brukerveiledning | |
|---|---|
| [Installasjon](guide/install.md) | pip, uv, fra kildekoden, valgfrie tillegg |
| [Kom i gang](guide/quickstart.md) | De første revisjonene, konfigurasjonsfiler, bruk fra skript og LLM-agenter |
| [Nettgrensesnitt](guide/web-ui.md) | Sider, revisjoner i bakgrunnen, analyse, språk |
| [Testsett og sammenligningsmodus](guide/suites.md) | Testsett, egendefinert testsett, pålitelig referanse, LLM-dommer |
| [Ytelse](guide/performance.md) | Ytelsesdelen, proben og tidsavbrudd for forespørsler |
| [Overvåking](guide/monitoring.md) | Planlagte nye revisjoner, webhook-varsler, lagring av API-nøkler |
| [Revisjon av embedding, rerank, bilde og lyd](guide/other-endpoints.md) | Revisjon av endepunkter som ikke er chat |
| [Kunnskapsbase](guide/knowledge-base.md) | Modellprofiler og hvordan du legger til dine egne |
| [Rapporter](guide/reports.md) | Rapportformater og innhold |
| [Personvern og lokale data](guide/privacy.md) | Hva som blir på maskinen din; ansvarlig bruk |
| [GitHub Action](guide/github-action.md) | Stopp en CI-arbeidsflyt på en revisjon av et relé |
| [Docker](guide/docker.md) | Kjøre nettgrensesnittet i en container |
| [Metodikk](guide/methodology.md) | Hver kontroll, scoreskalaen og forbeholdene |
| [Fra zing](guide/migrating-from-zing.md) | Hva som endres for en eksisterende zing-installasjon |

| Referanse (på engelsk) | |
|---|---|
| [Kommandolinje](../../reference/cli.md) | Alle kommandoer og alternativer, og avslutningskodene |
| [Skjemaer for rapport og webhook](../../reference/schemas.md) | JSON-formatene og deres `schema_version` |
| [Stabilitet og kompatibilitet](../../reference/stability.md) | Hva semver beskytter, utfasing, støttede Python-versjoner og systemer |
| [Endringslogg](../../../CHANGELOG.md) | Hva som er endret i hver utgivelse |

Bidra: [Retningslinjer for bidrag](../../CONTRIBUTING.md) og
[Utviklerveiledning](../../dev/developer-guide.md) (på engelsk).
Sikkerhetsproblemer: [Sikkerhetspolicy](../../SECURITY.md).

## Lisens

[Apache-2.0](../../../LICENSE)
