# Quick start

> **🇬🇧 English** · [🇨🇳 中文](../i18n/zh-CN/guide/quickstart.md) · [🇫🇷 Français](../i18n/fr/guide/quickstart.md) · [🇪🇸 Español](../i18n/es/guide/quickstart.md) · [🇵🇹 Português](../i18n/pt/guide/quickstart.md) · [🇮🇹 Italiano](../i18n/it/guide/quickstart.md) · [🇩🇪 Deutsch](../i18n/de/guide/quickstart.md) · [🇳🇴 Norsk](../i18n/nb/guide/quickstart.md)

```bash
# 1) audit a relay against what it claims (model id + provider hint)
export EKTE_API_KEY=sk-your-relay-key
ekte check \
  --base-url https://relay.example.com/v1 \
  --api-key env:EKTE_API_KEY \
  --model gpt-4o \
  --suite standard

# 2) the strongest check: compare against a trusted baseline of the same model
export OPENAI_API_KEY=sk-your-openai-key
ekte compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:EKTE_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o \
  --suite deep

# 3) audit an Anthropic-native (Messages API) relay — the protocol is auto-detected
#    from the base_url/model, or forced with --api anthropic
ekte check --base-url https://relay.example.com/v1 --model claude-opus-4-8 \
  --api-key env:EKTE_API_KEY --api anthropic

# 4) confirm a suspected substitution: audit the relay's REAL model id against the
#    profile it's sold as (here: a Doubao model passed off as deepseek-v4-flash)
ekte check --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY \
  --model doubao-seed-2-0-lite --claimed-model deepseek-v4-flash

# 5) list the models an endpoint advertises
ekte models --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY

# 6) inspect the knowledge base
ekte kb            # every profile, with its source
ekte kb deepseek   # one provider

# 7) generate a config you can commit
ekte init          # writes ekte.yaml
ekte check -c ekte.yaml
```

API keys can be given literally, as `env:VAR` or as `file:/path`; reports only
ever contain a fingerprint of the key. A full config file is in
[`examples/ekte.yaml`](../../examples/ekte.yaml).

The file has a format version (`version: 1`; a file without one is format 1). Wrong types and invalid values are rejected with the file, line and key; unknown keys are ignored with a warning until ekte 1.0.0, which rejects them. `ekte config migrate` updates an older file. The schema is [`docs/schemas/config.schema.json`](../schemas/config.schema.json).

## As a tool for an LLM / agent

ekte is built to be driven by another program or model. Everything goes to stdout
as JSON, errors included, and the exit code is the gate.

```bash
# lean, agent-friendly verdict (~5x smaller than --json: no bulky evidence)
ekte check --base-url ... --model gpt-4o --compact | jq .verdict.risk

# full structured report when you need every finding's evidence
ekte check --base-url ... --model gpt-4o --json

# budget first: which detectors run + estimated API calls, WITHOUT making any
ekte check --base-url ... --model gpt-4o --suite deep --dry-run --json

# gate on the exit code (1 if risk >= medium, or the score is below --fail-under);
# config/usage errors exit 2, as JSON
ekte check --base-url ... --model gpt-4o --compact --fail-on-risk medium

# machine-readable discovery
ekte kb --json                      # the whole knowledge base
ekte models --base-url ... --json   # what an endpoint advertises
```

In `--json`/`--compact` mode a bad config prints `{"error": {...}}` (exit 2)
instead of a human message, so a pipeline can parse failures uniformly.
