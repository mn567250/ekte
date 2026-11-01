# CI an eine ekte-Relay-Prüfung koppeln

> [🇬🇧 English](../../../guide/github-action.md) · [🇨🇳 中文](../../zh-CN/guide/github-action.md) · [🇫🇷 Français](../../fr/guide/github-action.md) · [🇪🇸 Español](../../es/guide/github-action.md) · [🇵🇹 Português](../../pt/guide/github-action.md) · [🇮🇹 Italiano](../../it/guide/github-action.md) · **🇩🇪 Deutsch** · [🇳🇴 Norsk](../../nb/guide/github-action.md)

`ekte` bringt eine wiederverwendbare **GitHub Composite Action** mit, mit der Sie
einen Build scheitern lassen, ein Deployment blockieren oder einen geplanten
Gesundheitscheck ausführen können, sobald ein Relay von dem Modell abweicht, das
es angeblich liefert.

Intern führt die Action Folgendes aus:

```
ekte check --base-url … --api-key env:… --model … --suite … \
           --fail-on-risk <level> --compact
```

Sie wertet das kompakte JSON-Urteil aus, stellt `risk` / `score` / `rating` als
Step-Outputs bereit, schreibt eine knappe Zusammenfassung in den Tab **Summary**
des Laufs und lässt den Job über den eigenen Exit-Code von `ekte` scheitern
(Exit `1`, wenn die Risikoschranke auslöst, `2` bei einem Konfigurationsfehler).

> Der API-Schlüssel wird `ekte` über eine Umgebungsvariable übergeben
> (`--api-key env:…`), erscheint also nie auf einer Kommandozeile und wird nie
> ausgegeben. Liefern Sie ihn immer aus einem Repository-Secret.

## Schnellstart

```yaml
# .github/workflows/relay-audit.yml
name: Relay audit
on:
  schedule:
    - cron: "0 6 * * *"   # täglich um 06:00 UTC
  workflow_dispatch:

permissions:
  contents: read

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - id: ekte
        uses: mn567250/ekte@vX.Y.Z   # an einen Tag binden — siehe „Versionen festlegen“ unten
        with:
          base-url: https://relay.example.com/v1
          api-key: ${{ secrets.RELAY_API_KEY }}
          model: gpt-4o
          fail-on-risk: high
      - run: echo "risk=${{ steps.ekte.outputs.risk }} score=${{ steps.ekte.outputs.score }}"
```

## Eingaben

| Eingabe             | Pflicht  | Standard      | Beschreibung |
| ------------------- | -------- | ------------- | ----------- |
| `base-url`          | ja       | —             | Basis-URL des Relays, z. B. `https://relay.example.com/v1`. |
| `api-key`           | ja       | —             | API-Schlüssel des Relays. Übergeben Sie ein Secret: `${{ secrets.RELAY_API_KEY }}`. Wird nie ausgegeben. |
| `model`             | ja       | —             | Modell-ID, die tatsächlich in den Anfragen gesendet wird. |
| `claimed-model`     | nein     | `""`          | Modell, das das Relay angeblich liefert, falls es von `model` abweicht. |
| `api`               | nein     | `auto`        | Protokoll: `auto` \| `openai` \| `anthropic` \| `responses`. |
| `declared-provider` | nein     | `""`          | Anbieterhinweis für die Suche in der Wissensbasis (`openai`, `anthropic`, `deepseek`, …). |
| `suite`             | nein     | `standard`    | Test-Suite: `smoke` \| `standard` \| `deep` \| `full`. |
| `fail-on-risk`      | nein     | `high`        | Lässt den Job scheitern, wenn das Risiko `>=` dieser Stufe ist: `low` \| `medium` \| `high`. |
| `python-version`    | nein     | `3.12`        | Python-Version, mit der `ekte` installiert und ausgeführt wird. |
| `version`           | nein     | `ekte`  | pip-Installationsangabe. Für reproduzierbare Läufe festlegen, z. B. `ekte==X.Y.Z`. |

## Ausgaben

| Ausgabe  | Beschreibung |
| -------- | ----------- |
| `risk`   | Risikostufe: `clean` \| `low` \| `medium` \| `high` \| `inconclusive`. |
| `score`  | Gesamtbewertung `0`–`100` (leere Zeichenkette, wenn `ekte` das Relay nicht bewerten konnte). |
| `rating` | Für Menschen lesbare Einstufung aus dem Urteil (kann leer sein). |

## Ein Deployment an die Gesundheit des Relays koppeln

Führen Sie zuerst die Prüfung aus und deployen Sie nur, wenn sie besteht. Weil der
Prüfschritt den Job scheitern lässt, sobald die Risikoschranke auslöst, läuft ein
abhängiger Job, der ihn per `needs:` voraussetzt, einfach nicht.

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
        uses: mn567250/ekte@vX.Y.Z
        with:
          base-url: https://relay.example.com/v1
          api-key: ${{ secrets.RELAY_API_KEY }}
          model: gpt-4o
          claimed-model: gpt-4o
          fail-on-risk: medium   # das Deployment ab mittlerem Risiko blockieren
    outputs:
      risk: ${{ steps.ekte.outputs.risk }}
      score: ${{ steps.ekte.outputs.score }}

  deploy:
    needs: relay-health          # läuft nur, wenn die Prüfung die Schranke bestanden hat
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo "Relay is healthy (risk=${{ needs.relay-health.outputs.risk }}, \
            score=${{ needs.relay-health.outputs.score }}). Deploying…"
          # ./deploy.sh
```

## Versionen festlegen

Binden Sie die Action an einen **Release-Tag** (`mn567250/ekte@vX.Y.Z`) statt an
einen beweglichen Branch. So bleiben Prüfungen reproduzierbar, und Sie sind vor
unerwarteten Änderungen an der Action geschützt. Ein Tag lässt sich verschieben;
für den strengsten Schutz der Lieferkette binden Sie die Action an den vollständigen
Commit-SHA des Releases, mit der Version in einem Kommentar
(`mn567250/ekte@<full-commit-sha> # vX.Y.Z`), und lassen Dependabot ihn aktuell
halten. Für vollständig reproduzierbares CLI-Verhalten legen Sie zusätzlich die
Eingabe `version` auf ein genaues Release fest, z. B. `version: ekte==X.Y.Z`.

Ein kopierfertiges geplantes Beispiel liegt unter
[`.github/workflows/example-audit.yml`](../../../../.github/workflows/example-audit.yml).
