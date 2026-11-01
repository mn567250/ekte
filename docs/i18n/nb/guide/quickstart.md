# Kom i gang

> [🇬🇧 English](../../../guide/quickstart.md) · [🇨🇳 中文](../../zh-CN/guide/quickstart.md) · [🇫🇷 Français](../../fr/guide/quickstart.md) · [🇪🇸 Español](../../es/guide/quickstart.md) · [🇵🇹 Português](../../pt/guide/quickstart.md) · [🇮🇹 Italiano](../../it/guide/quickstart.md) · [🇩🇪 Deutsch](../../de/guide/quickstart.md) · **🇳🇴 Norsk**

```bash
# 1) revider et relé mot det det påstår (modell-ID + leverandørhint)
export EKTE_API_KEY=sk-your-relay-key
ekte check \
  --base-url https://relay.example.com/v1 \
  --api-key env:EKTE_API_KEY \
  --model gpt-4o \
  --suite standard

# 2) den sterkeste kontrollen: sammenlign med en pålitelig referanse for samme modell
export OPENAI_API_KEY=sk-your-openai-key
ekte compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:EKTE_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o \
  --suite deep

# 3) revider et Anthropic-relé (Messages API) — protokollen gjenkjennes automatisk
#    fra base_url/modellen, eller tvinges med --api anthropic
ekte check --base-url https://relay.example.com/v1 --model claude-opus-4-8 \
  --api-key env:EKTE_API_KEY --api anthropic

# 4) bekreft et mistenkt bytte: revider reléets EKTE modell-ID mot profilen den
#    selges som (her: en Doubao-modell som utgis for å være deepseek-v4-flash)
ekte check --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY \
  --model doubao-seed-2-0-lite --claimed-model deepseek-v4-flash

# 5) vis modellene et endepunkt annonserer
ekte models --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY

# 6) se i kunnskapsbasen
ekte kb            # alle profiler, med kilde
ekte kb deepseek   # én leverandør

# 7) lag en konfigurasjon du kan legge inn i versjonskontroll
ekte init          # skriver ekte.yaml
ekte check -c ekte.yaml
```

API-nøkler kan oppgis direkte, som `env:VAR` eller som `file:/sti`; rapporter
inneholder bare et fingeravtrykk av nøkkelen. En fullstendig konfigurasjonsfil
ligger i [`examples/ekte.yaml`](../../../../examples/ekte.yaml).

Filen har en formatversjon (`version: 1`; en fil uten versjon er format 1). Feil typer og ugyldige verdier avvises med fil, linje og nøkkel; ukjente nøkler ignoreres med en advarsel frem til ekte 1.0.0, som avviser dem. `ekte config migrate` oppdaterer en eldre fil. Skjemaet er [`docs/schemas/config.schema.json`](../../../schemas/config.schema.json).

## Som verktøy for en LLM / agent

ekte er laget for å styres av et annet program eller en annen modell. Alt går til
stdout som JSON, også feil, og avslutningskoden er porten.

```bash
# slank, agentvennlig konklusjon (~5x mindre enn --json: uten de store bevisene)
ekte check --base-url ... --model gpt-4o --compact | jq .verdict.risk

# full strukturert rapport når du trenger bevisene for hvert funn
ekte check --base-url ... --model gpt-4o --json

# budsjett først: hvilke detektorer som kjører + anslått antall API-kall, UTEN å gjøre noen
ekte check --base-url ... --model gpt-4o --suite deep --dry-run --json

# port på avslutningskoden (1 hvis risiko >= medium, eller scoren er under --fail-under);
# konfigurasjons-/bruksfeil avslutter med 2, som JSON
ekte check --base-url ... --model gpt-4o --compact --fail-on-risk medium

# maskinlesbar oppdagelse
ekte kb --json                      # hele kunnskapsbasen
ekte models --base-url ... --json   # hva et endepunkt annonserer
```

I modusene `--json`/`--compact` skriver en dårlig konfigurasjon ut
`{"error": {...}}` (avslutningskode 2) i stedet for en melding for mennesker, så en
pipeline kan tolke feil på samme måte.
