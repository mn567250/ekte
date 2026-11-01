# Suites and compare mode

> **🇬🇧 English** · [🇨🇳 中文](../i18n/zh-CN/guide/suites.md) · [🇫🇷 Français](../i18n/fr/guide/suites.md) · [🇪🇸 Español](../i18n/es/guide/suites.md) · [🇵🇹 Português](../i18n/pt/guide/suites.md) · [🇮🇹 Italiano](../i18n/it/guide/suites.md) · [🇩🇪 Deutsch](../i18n/de/guide/suites.md) · [🇳🇴 Norsk](../i18n/nb/guide/suites.md)

| Suite | Detectors | Cost |
|---|---|---|
| `smoke` | connectivity, security | very low |
| `standard` | + protocol, protocol_request, protocol_response, model_identity, capability, streaming, billing, reliability | low–medium |
| `deep` | + context_window, determinism, vision, injected_prompt, integrity, prompt_cache, performance, quality_judge (with `--judge`) | higher (long-context and timing probes cost tokens) |
| `full` | the detectors of `deep`, with performance measured both streaming and non-streaming | highest |
| `custom` | only the dimensions you pick, at `deep` depth | depends on the selection |

The context-window probe is bounded by `--max-context-tokens` (default 200K) so
auditing a 1M-token model stays affordable; a window larger than the cap is
reported as *verified up to the cap*, never as truncated. `--only` / `--skip` run or leave out
single detectors by id.

## Custom suite

Run just the dimensions you care about, which saves time and tokens. Every
detector of each selected dimension runs, as on `deep`:

```bash
ekte check --base-url ... --model gpt-4o -D protocol -D performance
ekte check --base-url ... --model gpt-4o --suite custom --dimension billing,streaming
```

`--dimension/-D` is repeatable or comma-separated and implies `--suite custom`;
in a config file use `run.dimensions: [protocol, performance]`. The dimensions
are `connectivity`, `protocol`, `context_window`, `model_identity`, `capability`,
`streaming`, `billing`, `reliability`, `security` and `performance`. In the web
UI, the `custom` suite button opens the same choice (**Dimensions to run**) on
the audit page and the monitors.

The **overall score is the weighted mean of the selected dimensions only**;
dimensions you left out are reported as "not selected". The risk verdict is
judged on the selected dimensions too: without model identity it covers only
them, not which model is served, and says so.

## Compare mode and the LLM judge

ekte has two detection modes:

- **Pure code (default):** every detector except `quality_judge` decides by
  deterministic code — fingerprints, the context sweep, billing arithmetic,
  streaming timing. No second model is needed; results are reproducible.
- **Code + LLM hybrid (`--judge`):** additionally asks a *trusted* judge model
  (configured separately, never the target) whether the target's answers read
  like the claimed model — fuzzy signals such as quality and reasoning depth that
  pure code can't decide. This is the `quality_judge` detector.

```bash
ekte check --base-url ... --model gpt-4o --suite deep --judge \
  --judge-base-url https://api.openai.com/v1 --judge-api-key env:OPENAI_API_KEY --judge-model gpt-4o-mini
```

**Compare mode** (`ekte compare`, or **Compare against a trusted baseline** in
the web UI) runs the same probes against a trusted baseline of the claimed model
at the same time. It is the strongest confirmation path: identity answers,
rejected request parameters, tampering canaries and performance are all judged
side by side, and only a baseline lets the verdict's confidence reach *high*.
Without `--judge-base-url`, compare mode uses the baseline as the judge.
