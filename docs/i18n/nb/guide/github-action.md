# Stopp CI på en ekte-revisjon av et relé

> [🇬🇧 English](../../../guide/github-action.md) · [🇨🇳 中文](../../zh-CN/guide/github-action.md) · [🇫🇷 Français](../../fr/guide/github-action.md) · [🇪🇸 Español](../../es/guide/github-action.md) · [🇵🇹 Português](../../pt/guide/github-action.md) · [🇮🇹 Italiano](../../it/guide/github-action.md) · [🇩🇪 Deutsch](../../de/guide/github-action.md) · **🇳🇴 Norsk**

`ekte` leveres med en gjenbrukbar **GitHub composite action**, så du kan la et
bygg feile, blokkere en utrulling eller kjøre en planlagt helsesjekk hver gang et
relé avviker fra modellen det sier det leverer.

Under panseret kjører handlingen:

```
ekte check --base-url … --api-key env:… --model … --suite … \
           --fail-on-risk <level> --compact
```

Den tolker den kompakte JSON-konklusjonen, gjør `risk` / `score` / `rating`
tilgjengelige som utdata fra steget, skriver et kort sammendrag til kjøringens
**Summary**-fane og lar `ekte`s egen avslutningskode stoppe jobben (avslutning
`1` når risikoterskelen utløses, `2` ved en konfigurasjonsfeil).

> API-nøkkelen sendes til `ekte` gjennom en miljøvariabel
> (`--api-key env:…`), så den vises aldri på en kommandolinje og gjengis aldri.
> Oppgi den alltid fra en repository-hemmelighet (secret).

## Kom i gang

```yaml
# .github/workflows/relay-audit.yml
name: Relay audit
on:
  schedule:
    - cron: "0 6 * * *"   # daglig kl. 06:00 UTC
  workflow_dispatch:

permissions:
  contents: read

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - id: ekte
        uses: mn567250/ekte@v0.33.1   # fest til en tag — se «Festing» nedenfor
        with:
          base-url: https://relay.example.com/v1
          api-key: ${{ secrets.RELAY_API_KEY }}
          model: gpt-4o
          fail-on-risk: high
      - run: echo "risk=${{ steps.ekte.outputs.risk }} score=${{ steps.ekte.outputs.score }}"
```

## Inndata

| Inndata             | Påkrevd  | Standard      | Beskrivelse |
| ------------------- | -------- | ------------- | ----------- |
| `base-url`          | ja       | —             | Reléets basis-URL, f.eks. `https://relay.example.com/v1`. |
| `api-key`           | ja       | —             | Reléets API-nøkkel. Send en hemmelighet: `${{ secrets.RELAY_API_KEY }}`. Gjengis aldri. |
| `model`             | ja       | —             | Modell-ID-en som faktisk sendes i forespørslene. |
| `claimed-model`     | nei      | `""`          | Modellen reléet sier det leverer, hvis den er en annen enn `model`. |
| `api`               | nei      | `auto`        | Protokoll: `auto` \| `openai` \| `anthropic` \| `responses`. |
| `declared-provider` | nei      | `""`          | Leverandørhint for oppslag i kunnskapsbasen (`openai`, `anthropic`, `deepseek`, …). |
| `suite`             | nei      | `standard`    | Testsett: `smoke` \| `standard` \| `deep` \| `full`. |
| `fail-on-risk`      | nei      | `high`        | La jobben feile når risikoen er `>=` dette nivået: `low` \| `medium` \| `high`. |
| `python-version`    | nei      | `3.12`        | Python-versjonen som brukes til å installere og kjøre `ekte`. |
| `version`           | nei      | `ekte`  | pip-installasjonsspesifikasjon. Fest den for reproduserbare kjøringer, f.eks. `ekte==0.33.1`. |

## Utdata

| Utdata   | Beskrivelse |
| -------- | ----------- |
| `risk`   | Risikonivå: `clean` \| `low` \| `medium` \| `high` \| `inconclusive`. |
| `score`  | Samlet score `0`–`100` (tom streng hvis `ekte` ikke kunne gi reléet score). |
| `rating` | Lesbar karakter fra konklusjonen (kan være tom). |

## Gjør en utrulling avhengig av reléets helse

Kjør revisjonen først; rull bare ut når den består. Siden revisjonssteget lar
jobben feile når risikoterskelen utløses, kjører en avhengig jobb som `needs:`
den, rett og slett ikke.

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
          fail-on-risk: medium   # blokker utrullingen ved middels risiko eller verre
    outputs:
      risk: ${{ steps.ekte.outputs.risk }}
      score: ${{ steps.ekte.outputs.score }}

  deploy:
    needs: relay-health          # kjører bare hvis revisjonen besto terskelen
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo "Relay is healthy (risk=${{ needs.relay-health.outputs.risk }}, \
            score=${{ needs.relay-health.outputs.score }}). Deploying…"
          # ./deploy.sh
```

## Festing

Fest handlingen til en **utgivelsestag** (`mn567250/ekte@v0.33.1`) i stedet for
en gren som flytter seg. Det holder revisjonene reproduserbare og beskytter deg
mot uventede endringer i handlingen. En tag kan flyttes; for den strengeste
beskyttelsen av forsyningskjeden fester du utgivelsens fullstendige commit-SHA
med versjonen i en kommentar (`mn567250/ekte@<full-commit-sha> # v0.33.1`) og lar
Dependabot holde den oppdatert. For fullt reproduserbar oppførsel i CLI-et fester
du også inndataene `version` til en eksakt utgivelse, f.eks.
`version: ekte==0.33.1`.

Et planlagt eksempel klart til å kopieres ligger i
[`.github/workflows/example-audit.yml`](../../../../.github/workflows/example-audit.yml).
