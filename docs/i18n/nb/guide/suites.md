# Testsett og sammenligningsmodus

> [🇬🇧 English](../../../guide/suites.md) · [🇨🇳 中文](../../zh-CN/guide/suites.md) · [🇫🇷 Français](../../fr/guide/suites.md) · [🇪🇸 Español](../../es/guide/suites.md) · [🇵🇹 Português](../../pt/guide/suites.md) · [🇮🇹 Italiano](../../it/guide/suites.md) · [🇩🇪 Deutsch](../../de/guide/suites.md) · **🇳🇴 Norsk**

| Testsett | Detektorer | Kostnad |
|---|---|---|
| `smoke` | connectivity, security | svært lav |
| `standard` | + protocol, protocol_request, protocol_response, model_identity, capability, streaming, billing, reliability | lav–middels |
| `deep` | + context_window, determinism, vision, injected_prompt, integrity, prompt_cache, performance, quality_judge (med `--judge`) | høyere (prober for lang kontekst og tidsmåling koster tokens) |
| `full` | detektorene i `deep`, med ytelsen målt både med og uten strømming | høyest |
| `custom` | bare dimensjonene du velger, med dybden `deep` | avhenger av utvalget |

Kontekstvindu-proben begrenses av `--max-context-tokens` (standard 200K), så det
holder seg rimelig å revidere en modell med 1M tokens; et vindu større enn taket
rapporteres som *verifisert opp til taket*, aldri som avkortet. `--only` /
`--skip` kjører eller utelater enkeltdetektorer etter ID.

## Egendefinert testsett

Kjør bare dimensjonene du bryr deg om; det sparer tid og tokens. Hver detektor i
hver valgte dimensjon kjøres, som på `deep`:

```bash
ekte check --base-url ... --model gpt-4o -D protocol -D performance
ekte check --base-url ... --model gpt-4o --suite custom --dimension billing,streaming
```

`--dimension/-D` kan gjentas eller kommasepareres og innebærer
`--suite custom`; i en konfigurasjonsfil bruker du
`run.dimensions: [protocol, performance]`. Dimensjonene er `connectivity`,
`protocol`, `context_window`, `model_identity`, `capability`, `streaming`,
`billing`, `reliability`, `security` og `performance`. I nettgrensesnittet åpner
knappen for testsettet `custom` det samme valget (**Dimensjoner som skal
kjøres**) på revisjonssiden og på overvåkingene.

Den **samlede scoren er det vektede gjennomsnittet av bare de valgte
dimensjonene**; dimensjoner du utelot, rapporteres som «ikke valgt».
Risikokonklusjonen vurderes også på de valgte dimensjonene: uten
modellidentitet dekker den bare dem, ikke hvilken modell som leveres, og sier det.

## Sammenligningsmodus og LLM-dommeren

ekte har to deteksjonsmoduser:

- **Ren kode (standard):** alle detektorer unntatt `quality_judge` avgjør med
  deterministisk kode — fingeravtrykk, kontekstsveipet, faktureringsregning,
  tidsmåling av strømming. Ingen ekstra modell trengs; resultatene er
  reproduserbare.
- **Hybrid av kode og LLM (`--judge`):** spør i tillegg en *pålitelig*
  dommermodell (satt opp separat, aldri målet) om målets svar leses som den
  oppgitte modellen — uklare signaler som kvalitet og resonneringsdybde som ren
  kode ikke kan avgjøre. Dette er detektoren `quality_judge`.

```bash
ekte check --base-url ... --model gpt-4o --suite deep --judge \
  --judge-base-url https://api.openai.com/v1 --judge-api-key env:OPENAI_API_KEY --judge-model gpt-4o-mini
```

**Sammenligningsmodus** (`ekte compare`, eller **Sammenlign med en pålitelig
referanse** i nettgrensesnittet) kjører de samme probene mot en pålitelig
referanse for den oppgitte modellen samtidig. Det er den sterkeste veien til
bekreftelse: identitetssvar, avviste forespørselsparametere, kanarier for
manipulering og ytelse vurderes side om side, og bare en referanse lar
konklusjonens sikkerhet nå *høy*. Uten `--judge-base-url` bruker
sammenligningsmodus referansen som dommer.
