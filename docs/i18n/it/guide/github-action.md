# Bloccare la CI con una verifica di relay ekte

> [🇬🇧 English](../../../guide/github-action.md) · [🇨🇳 中文](../../zh-CN/guide/github-action.md) · [🇫🇷 Français](../../fr/guide/github-action.md) · [🇪🇸 Español](../../es/guide/github-action.md) · [🇵🇹 Português](../../pt/guide/github-action.md) · **🇮🇹 Italiano** · [🇩🇪 Deutsch](../../de/guide/github-action.md) · [🇳🇴 Norsk](../../nb/guide/github-action.md)

`ekte` include una **GitHub composite action** riutilizzabile, così puoi far
fallire una build, bloccare un deploy o eseguire un controllo di salute
pianificato ogni volta che un relay si discosta dal modello che dichiara di
servire.

Dietro le quinte l'action esegue:

```
ekte check --base-url … --api-key env:… --model … --suite … \
           --fail-on-risk <level> --compact
```

Analizza il verdetto JSON compatto, espone `risk` / `score` / `rating` come
output dello step, scrive un riepilogo conciso nella scheda **Summary** dell'esecuzione
e lascia che sia il codice di uscita di `ekte` a far fallire il job (uscita `1`
quando scatta la barriera sul rischio, `2` per un errore di configurazione).

> La chiave API viene passata a `ekte` tramite una variabile d'ambiente
> (`--api-key env:…`), quindi non compare mai su una riga di comando e non viene
> mai stampata. Forniscila sempre da un secret del repository.

## Avvio rapido

```yaml
# .github/workflows/relay-audit.yml
name: Relay audit
on:
  schedule:
    - cron: "0 6 * * *"   # ogni giorno alle 06:00 UTC
  workflow_dispatch:

permissions:
  contents: read

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - id: ekte
        uses: mn567250/ekte@v0.33.0   # fissa un tag — vedi "Fissare la versione" sotto
        with:
          base-url: https://relay.example.com/v1
          api-key: ${{ secrets.RELAY_API_KEY }}
          model: gpt-4o
          fail-on-risk: high
      - run: echo "risk=${{ steps.ekte.outputs.risk }} score=${{ steps.ekte.outputs.score }}"
```

## Input

| Input               | Obbligatorio | Predefinito   | Descrizione |
| ------------------- | ------------ | ------------- | ----------- |
| `base-url`          | sì           | —             | URL di base del relay, ad es. `https://relay.example.com/v1`. |
| `api-key`           | sì           | —             | Chiave API del relay. Passa un secret: `${{ secrets.RELAY_API_KEY }}`. Mai stampata. |
| `model`             | sì           | —             | Id del modello effettivamente inviato nelle richieste. |
| `claimed-model`     | no           | `""`          | Modello che il relay dichiara di servire, se diverso da `model`. |
| `api`               | no           | `auto`        | Protocollo: `auto` \| `openai` \| `anthropic` \| `responses`. |
| `declared-provider` | no           | `""`          | Indizio sul fornitore per la ricerca nella base di conoscenza (`openai`, `anthropic`, `deepseek`, …). |
| `suite`             | no           | `standard`    | Suite di rilevatori: `smoke` \| `standard` \| `deep` \| `full`. |
| `fail-on-risk`      | no           | `high`        | Fa fallire il job quando il rischio è `>=` questo livello: `low` \| `medium` \| `high`. |
| `python-version`    | no           | `3.12`        | Versione di Python usata per installare ed eseguire `ekte`. |
| `version`           | no           | `ekte`        | Specifica di installazione pip. Fissala per esecuzioni riproducibili, ad es. `ekte==0.33.0`. |

## Output

| Output   | Descrizione |
| -------- | ----------- |
| `risk`   | Livello di rischio: `clean` \| `low` \| `medium` \| `high` \| `inconclusive`. |
| `score`  | Punteggio complessivo `0`–`100` (stringa vuota se `ekte` non ha potuto valutare il relay). |
| `rating` | Valutazione leggibile tratta dal verdetto (può essere vuota). |

## Subordinare un deploy alla salute del relay

Esegui prima la verifica; fai il deploy solo se passa. Poiché lo step di verifica
fa fallire il job quando scatta la barriera sul rischio, un job dipendente che lo
richiede con `needs:` semplicemente non viene eseguito.

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
          fail-on-risk: medium   # blocca il deploy con rischio medium o peggiore
    outputs:
      risk: ${{ steps.ekte.outputs.risk }}
      score: ${{ steps.ekte.outputs.score }}

  deploy:
    needs: relay-health          # viene eseguito solo se la verifica ha superato la barriera
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo "Relay is healthy (risk=${{ needs.relay-health.outputs.risk }}, \
            score=${{ needs.relay-health.outputs.score }}). Deploying…"
          # ./deploy.sh
```

## Fissare la versione

Fissa l'action a un **tag di rilascio** (`mn567250/ekte@v0.33.0`) invece che a un
branch mobile. Così le verifiche restano riproducibili e sei protetto da
modifiche inattese all'action. Un tag può essere spostato; per la protezione più
rigorosa della catena di fornitura fissa lo SHA completo del commit del rilascio,
con la versione in un commento (`mn567250/ekte@<full-commit-sha> # v0.33.0`), e
lascia che Dependabot lo tenga aggiornato. Per un comportamento della CLI del
tutto riproducibile, fissa anche l'input `version` a un rilascio esatto, ad es.
`version: ekte==0.33.0`.

Un esempio pianificato pronto da copiare si trova in
[`.github/workflows/example-audit.yml`](../../../../.github/workflows/example-audit.yml).
