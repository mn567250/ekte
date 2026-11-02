# Conditionner la CI à un audit de relais ekte

> [🇬🇧 English](../../../guide/github-action.md) · [🇨🇳 中文](../../zh-CN/guide/github-action.md) · **🇫🇷 Français** · [🇪🇸 Español](../../es/guide/github-action.md) · [🇵🇹 Português](../../pt/guide/github-action.md) · [🇮🇹 Italiano](../../it/guide/github-action.md) · [🇩🇪 Deutsch](../../de/guide/github-action.md) · [🇳🇴 Norsk](../../nb/guide/github-action.md)

`ekte` fournit une **action composite GitHub** réutilisable pour faire échouer
un build, bloquer un déploiement ou lancer un contrôle de santé planifié dès
qu'un relais s'écarte du modèle qu'il prétend servir.

En coulisses, l'action exécute :

```
ekte check --base-url … --api-key env:… --model … --suite … \
           --fail-on-risk <level> --compact
```

Elle analyse le verdict JSON compact, expose `risk` / `score` / `rating` comme
sorties de l'étape, écrit un résumé concis dans l'onglet **Summary** de
l'exécution, et laisse le propre code de sortie d'`ekte` faire échouer le job
(sortie `1` quand le seuil de risque est franchi, `2` sur une erreur de
configuration).

> La clé API est transmise à `ekte` par une variable d'environnement
> (`--api-key env:…`), elle n'apparaît donc jamais sur une ligne de commande et
> n'est jamais affichée. Fournissez-la toujours depuis un secret du dépôt.

## Démarrage rapide

```yaml
# .github/workflows/relay-audit.yml
name: Relay audit
on:
  schedule:
    - cron: "0 6 * * *"   # tous les jours à 06:00 UTC
  workflow_dispatch:

permissions:
  contents: read

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - id: ekte
        uses: mn567250/ekte@v0.33.1   # épinglez sur un tag — voir « Épinglage » plus bas
        with:
          base-url: https://relay.example.com/v1
          api-key: ${{ secrets.RELAY_API_KEY }}
          model: gpt-4o
          fail-on-risk: high
      - run: echo "risk=${{ steps.ekte.outputs.risk }} score=${{ steps.ekte.outputs.score }}"
```

## Entrées

| Entrée              | Requise  | Défaut        | Description |
| ------------------- | -------- | ------------- | ----------- |
| `base-url`          | oui      | —             | URL de base du relais, p. ex. `https://relay.example.com/v1`. |
| `api-key`           | oui      | —             | Clé API du relais. Passez un secret : `${{ secrets.RELAY_API_KEY }}`. Jamais affichée. |
| `model`             | oui      | —             | Id du modèle réellement envoyé dans les requêtes. |
| `claimed-model`     | non      | `""`          | Modèle que le relais prétend servir, s'il diffère de `model`. |
| `api`               | non      | `auto`        | Protocole : `auto` \| `openai` \| `anthropic` \| `responses`. |
| `declared-provider` | non      | `""`          | Indice de fournisseur pour la recherche dans la base de connaissances (`openai`, `anthropic`, `deepseek`, …). |
| `suite`             | non      | `standard`    | Suite de détecteurs : `smoke` \| `standard` \| `deep` \| `full`. |
| `fail-on-risk`      | non      | `high`        | Fait échouer le job quand le risque est `>=` ce niveau : `low` \| `medium` \| `high`. |
| `python-version`    | non      | `3.12`        | Version de Python utilisée pour installer et exécuter `ekte`. |
| `version`           | non      | `ekte`  | Spécification pip install. Épinglez-la pour des exécutions reproductibles, p. ex. `ekte==0.33.1`. |

## Sorties

| Sortie   | Description |
| -------- | ----------- |
| `risk`   | Niveau de risque : `clean` \| `low` \| `medium` \| `high` \| `inconclusive`. |
| `score`  | Score global `0`–`100` (chaîne vide si `ekte` n'a pas pu noter le relais). |
| `rating` | Appréciation lisible tirée du verdict (peut être vide). |

## Conditionner un déploiement à la santé du relais

Lancez d'abord l'audit ; ne déployez que s'il réussit. Comme l'étape d'audit fait
échouer le job quand le seuil de risque est franchi, un job dépendant qui la
référence par `needs:` ne s'exécute tout simplement pas.

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
          fail-on-risk: medium   # bloquer le déploiement dès un risque moyen ou pire
    outputs:
      risk: ${{ steps.ekte.outputs.risk }}
      score: ${{ steps.ekte.outputs.score }}

  deploy:
    needs: relay-health          # ne s'exécute que si l'audit a passé le seuil
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo "Relay is healthy (risk=${{ needs.relay-health.outputs.risk }}, \
            score=${{ needs.relay-health.outputs.score }}). Deploying…"
          # ./deploy.sh
```

## Épinglage

Épinglez l'action sur un **tag de version** (`mn567250/ekte@v0.33.1`) plutôt que
sur une branche mouvante. Les audits restent ainsi reproductibles et vous êtes
protégé des changements inattendus de l'action. Un tag peut être déplacé ; pour
la protection la plus stricte de la chaîne d'approvisionnement, épinglez le SHA
complet du commit de la version avec la version en commentaire
(`mn567250/ekte@<full-commit-sha> # v0.33.1`) et laissez Dependabot le tenir à
jour. Pour un comportement de la CLI entièrement reproductible, épinglez aussi
l'entrée `version` sur une version exacte, p. ex. `version: ekte==0.33.1`.

Un exemple planifié prêt à copier se trouve dans
[`.github/workflows/example-audit.yml`](../../../../.github/workflows/example-audit.yml).
