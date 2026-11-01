# ekte — LLM relay reality check

> **🇬🇧 English** · [🇨🇳 中文](docs/i18n/zh-CN/README.md) · [🇫🇷 Français](docs/i18n/fr/README.md) · [🇪🇸 Español](docs/i18n/es/README.md) · [🇵🇹 Português](docs/i18n/pt/README.md) · [🇮🇹 Italiano](docs/i18n/it/README.md) · [🇩🇪 Deutsch](docs/i18n/de/README.md) · [🇳🇴 Norsk](docs/i18n/nb/README.md)

[![CI](https://github.com/mn567250/ekte/actions/workflows/ci.yml/badge.svg)](https://github.com/mn567250/ekte/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

**ekte** is a local-first tool that audits whether an API relay (reseller /
proxy) actually serves the model it claims to — or quietly substitutes a cheaper
one, truncates your context window, fakes streaming, or inflates token billing.
In short: do you get what you paid for? It speaks the **OpenAI Chat Completions
API**, the **Anthropic Messages API** and the **OpenAI Responses API**
(`/v1/responses`) — auto-detected, or forced with `--api openai|anthropic|responses`.

You point it at a relay endpoint and the model it claims to serve; ekte runs a
battery of black-box probes, compares what it observes with a bundled knowledge
base of **98 model profiles from 7 providers**, and gives a clear, evidence-backed
verdict — on the command line, in a local web UI, or as JSON for another tool or
LLM.

> ekte reports **black-box evidence of divergence and risk, not cryptographic
> proof of fraud.** See [Responsible use](docs/guide/privacy.md#responsible-use).

## Why

The relay-key market is full of "GPT-4o for 1/10th the price" offers. Many are
honest. Some are not — and the dishonest ones are hard to catch by eye:

- You ask for `gpt-4o`; you're quietly served `gpt-4o-mini` or an open model.
- The relay advertises a 1M-token context but silently truncates to 32K.
- "Streaming" is the full response buffered and re-chunked, with no latency win.
- Reported `usage` tokens are inflated, so your balance burns faster than it should.
- A model that should support tool calling / JSON mode quietly doesn't.

ekte turns "this feels off" into a reproducible report.

## Install

Requires Python 3.11+ on Linux, macOS or Windows.

```bash
pip install 'ekte[web]'          # or: uv tool install 'ekte[web]'
```

The `web` extra adds the local web UI; leave it out for the command line only.
From source, with uv or in Docker: [Install](docs/guide/install.md).

## Quick start

```bash
export EKTE_API_KEY=sk-your-relay-key

# audit a relay against the model it claims to serve
ekte check --base-url https://relay.example.com/v1 --api-key env:EKTE_API_KEY \
  --model gpt-4o --suite standard

# the strongest check: compare against a trusted baseline of the same model
export OPENAI_API_KEY=sk-your-openai-key
ekte compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:EKTE_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o

# or point and click: the local web UI
ekte serve
```

More examples, config files and use from scripts or LLM agents:
[Quick start](docs/guide/quickstart.md). The web UI: [Web UI](docs/guide/web-ui.md).

## What it checks

ekte scores ten dimensions. The four **core dimensions** — model identity,
context window, capability claims and billing & usage — most directly reveal a
bait-and-switch. The names are the ones the web UI and reports use.

| Dimension | Id | What it catches |
|---|---|---|
| **Model identity** | `model_identity` | Silent model downgrade or substitution |
| **Context window** | `context_window` | Silent context truncation and lost-in-the-middle |
| **Capability claims** | `capability` | Tool calling, JSON mode, max output or vision that isn't delivered |
| **Protocol compliance** | `protocol` | Request parameters and response attributes that are dropped or ignored |
| **Billing & usage** | `billing` | Inflated or missing token usage |
| **Connectivity** | `connectivity` | Endpoint reachability and the advertised model list |
| **Streaming authenticity** | `streaming` | Fake streaming (buffer-then-chunk) |
| **Concurrency reliability** | `reliability` | Failures and slowdowns under concurrent load |
| **Transport security** | `security` | Plain HTTP, secret echo, injected system prompts, tampering |
| **Performance** | `performance` | How consistent latency, time to first token and throughput are |

How every check works and how the verdict is reached:
[Methodology](docs/guide/methodology.md).

## Documentation

| User guide | |
|---|---|
| [Install](docs/guide/install.md) | pip, uv, from source, optional extras |
| [Quick start](docs/guide/quickstart.md) | First audits, config files, use by scripts and LLM agents |
| [Web UI](docs/guide/web-ui.md) | Pages, background audits, analytics, languages |
| [Suites and compare mode](docs/guide/suites.md) | Suites, custom suite, trusted baseline, LLM judge |
| [Performance](docs/guide/performance.md) | The performance section, the probe and request timeouts |
| [Monitoring](docs/guide/monitoring.md) | Scheduled re-audits, webhook alerts, API key storage |
| [Embedding, rerank, image and audio](docs/guide/other-endpoints.md) | Audits of endpoints that are not chat |
| [Knowledge base](docs/guide/knowledge-base.md) | Model profiles and adding your own |
| [Reports](docs/guide/reports.md) | Report formats and contents |
| [Privacy and local data](docs/guide/privacy.md) | What stays on your machine; responsible use |
| [GitHub Action](docs/guide/github-action.md) | Gate a CI workflow on a relay audit |
| [Docker](docs/guide/docker.md) | Run the web UI in a container |
| [Methodology](docs/guide/methodology.md) | Every check, its scoring scale and its caveats |
| [Coming from zing](docs/guide/migrating-from-zing.md) | What changes for an existing zing install |

| Reference (English) | |
|---|---|
| [Command line](docs/reference/cli.md) | Every command and option, and the exit codes |
| [Report and webhook schemas](docs/reference/schemas.md) | The JSON formats and their `schema_version` |
| [Stability and compatibility](docs/reference/stability.md) | What semver protects, deprecation, supported Python and systems |
| [Changelog](CHANGELOG.md) | What changed in each release |

Contributing: [Contributing guide](docs/CONTRIBUTING.md) and
[Developer guide](docs/dev/developer-guide.md) (English).
Security issues: [Security policy](docs/SECURITY.md).

## License

[Apache-2.0](LICENSE)
