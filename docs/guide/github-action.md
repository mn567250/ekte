# Gate CI on a ekte relay audit

> **🇬🇧 English** · [🇨🇳 中文](../i18n/zh-CN/guide/github-action.md) · [🇫🇷 Français](../i18n/fr/guide/github-action.md) · [🇪🇸 Español](../i18n/es/guide/github-action.md) · [🇵🇹 Português](../i18n/pt/guide/github-action.md) · [🇮🇹 Italiano](../i18n/it/guide/github-action.md) · [🇩🇪 Deutsch](../i18n/de/guide/github-action.md) · [🇳🇴 Norsk](../i18n/nb/guide/github-action.md)

`ekte` ships a reusable **GitHub composite action** so you can fail a build,
block a deploy, or run a scheduled health check whenever a relay drifts from the
model it claims to serve.

Under the hood the action runs:

```
ekte check --base-url … --api-key env:… --model … --suite … \
           --fail-on-risk <level> --compact
```

It parses the compact JSON verdict, exposes `risk` / `score` / `rating` as step
outputs, writes a concise summary to the run's **Summary** tab, and lets `ekte`'s
own exit code fail the job (exit `1` when the risk gate trips, `2` on a config
error).

> The API key is passed to `ekte` through an environment variable
> (`--api-key env:…`), so it never appears on a command line and is never echoed.
> Always supply it from a repository secret.

## Quick start

```yaml
# .github/workflows/relay-audit.yml
name: Relay audit
on:
  schedule:
    - cron: "0 6 * * *"   # daily at 06:00 UTC
  workflow_dispatch:

permissions:
  contents: read

jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - id: ekte
        uses: mn567250/ekte@v0.33.1   # pin to a tag — see "Pinning" below
        with:
          base-url: https://relay.example.com/v1
          api-key: ${{ secrets.RELAY_API_KEY }}
          model: gpt-4o
          fail-on-risk: high
      - run: echo "risk=${{ steps.ekte.outputs.risk }} score=${{ steps.ekte.outputs.score }}"
```

## Inputs

| Input               | Required | Default       | Description |
| ------------------- | -------- | ------------- | ----------- |
| `base-url`          | yes      | —             | Relay base URL, e.g. `https://relay.example.com/v1`. |
| `api-key`           | yes      | —             | Relay API key. Pass a secret: `${{ secrets.RELAY_API_KEY }}`. Never echoed. |
| `model`             | yes      | —             | Model id actually sent in requests. |
| `claimed-model`     | no       | `""`          | Model the relay claims to serve, if different from `model`. |
| `api`               | no       | `auto`        | Wire protocol: `auto` \| `openai` \| `anthropic` \| `responses`. |
| `declared-provider` | no       | `""`          | Provider hint for KB lookup (`openai`, `anthropic`, `deepseek`, …). |
| `suite`             | no       | `standard`    | Detector suite: `smoke` \| `standard` \| `deep` \| `full`. |
| `fail-on-risk`      | no       | `high`        | Fail the job when risk `>=` this level: `low` \| `medium` \| `high`. |
| `python-version`    | no       | `3.12`        | Python version used to install and run `ekte`. |
| `version`           | no       | `ekte`  | pip install spec. Pin for reproducible runs, e.g. `ekte==0.33.1`. |

## Outputs

| Output   | Description |
| -------- | ----------- |
| `risk`   | Risk level: `clean` \| `low` \| `medium` \| `high` \| `inconclusive`. |
| `score`  | Overall score `0`–`100` (empty string if `ekte` could not score the relay). |
| `rating` | Human-readable rating from the verdict (may be empty). |

## Gate a deploy on relay health

Run the audit first; only deploy when it passes. Because the audit step fails the
job when the risk gate trips, a dependent job that `needs:` it simply won't run.

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
          fail-on-risk: medium   # block the deploy on medium-or-worse risk
    outputs:
      risk: ${{ steps.ekte.outputs.risk }}
      score: ${{ steps.ekte.outputs.score }}

  deploy:
    needs: relay-health          # only runs if the audit passed the gate
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo "Relay is healthy (risk=${{ needs.relay-health.outputs.risk }}, \
            score=${{ needs.relay-health.outputs.score }}). Deploying…"
          # ./deploy.sh
```

## Pinning

Pin the action to a **release tag** (`mn567250/ekte@v0.33.1`) rather than a moving
branch. This keeps audits reproducible and protects you from unexpected changes
to the action. A tag can be moved; for the strictest supply-chain protection pin the
release's full commit SHA with the version in a comment
(`mn567250/ekte@<full-commit-sha> # v0.33.1`) and let Dependabot keep it current. For fully reproducible CLI behavior, also pin the `version` input
to an exact release, e.g. `version: ekte==0.33.1`.

A ready-to-copy scheduled example lives at
[`.github/workflows/example-audit.yml`](../../.github/workflows/example-audit.yml).
