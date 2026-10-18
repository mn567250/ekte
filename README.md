# zing — LLM relay reality check

> **🇬🇧 English** · [🇨🇳 中文](README.zh-CN.md) · [🇫🇷 Français](README.fr.md) · [🇪🇸 Español](README.es.md) · [🇵🇹 Português](README.pt.md) · [🇮🇹 Italiano](README.it.md) · [🇩🇪 Deutsch](README.de.md)

[![CI](https://github.com/cenbonew/zing/actions/workflows/ci.yml/badge.svg)](https://github.com/cenbonew/zing/actions/workflows/ci.yml)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

**zing** is a local-first tool that audits whether an API relay (reseller /
proxy) actually serves the model it claims to — or quietly substitutes a cheaper
one, truncates your context window, fakes streaming, or inflates token billing.
In short: do you get what you paid for? It speaks the **OpenAI Chat Completions
API**, the **Anthropic Messages API** and the **OpenAI Responses API**
(`/v1/responses`) — auto-detected, or forced with `--api openai|anthropic|responses`.

You point it at a relay endpoint and the model it claims to serve; zing runs a
battery of black-box probes, compares what it observes with a bundled knowledge
base of **98 model profiles from 7 providers**, and gives a clear, evidence-backed
verdict — on the command line, in a local web UI, or as JSON for another tool or
LLM.

> zing reports **black-box evidence of divergence and risk, not cryptographic
> proof of fraud.** See [Responsible use](#responsible-use).

This README is for people who **use** zing. How zing is built, tested and
released is in the [Developer guide](DEVELOPER_GUIDE.md); how every check works
and is scored is in the [Methodology](docs/METHODOLOGY.md).

---

## Contents

- [Why](#why)
- [Install](#install)
- [Quick start](#quick-start)
- [Web UI (`zing serve`)](#web-ui-zing-serve)
- [What it checks](#what-it-checks)
- [How the verdict is reached](#how-the-verdict-is-reached)
- [Suites](#suites)
- [Performance](#performance)
- [Compare mode and the LLM judge](#compare-mode-and-the-llm-judge)
- [Monitoring](#monitoring)
- [Embedding, rerank, image and audio audits](#embedding-rerank-image-and-audio-audits)
- [Use in CI (GitHub Action)](#use-in-ci-github-action)
- [Knowledge base](#knowledge-base)
- [Reports](#reports)
- [Privacy and local data](#privacy-and-local-data)
- [Responsible use](#responsible-use)
- [Further documentation](#further-documentation)
- [License](#license)

## Why

The relay-key market is full of "GPT-4o for 1/10th the price" offers. Many are
honest. Some are not — and the dishonest ones are hard to catch by eye:

- You ask for `gpt-4o`; you're quietly served `gpt-4o-mini` or an open model.
- The relay advertises a 1M-token context but silently truncates to 32K.
- "Streaming" is the full response buffered and re-chunked, with no latency win.
- Reported `usage` tokens are inflated, so your balance burns faster than it should.
- A model that should support tool calling / JSON mode quietly doesn't.

zing turns "this feels off" into a reproducible report.

## Install

Requires Python 3.10+. Every option below provides the `zing` command.

### With pip

```bash
# from PyPI
pip install zing-audit

# or from source
git clone https://github.com/cenbonew/zing
cd zing
pip install -e .
```

### With [uv](https://docs.astral.sh/uv/)

```bash
# from PyPI, as a standalone tool on your PATH
uv tool install zing-audit

# or run it once without installing
uvx --from zing-audit zing --help

# or from source, into a project-local virtual environment
git clone https://github.com/cenbonew/zing
cd zing
uv venv
uv pip install -e .
source .venv/bin/activate       # Windows: .venv\Scripts\activate
```

You can also install straight from the Git repository without cloning:
`uv tool install git+https://github.com/cenbonew/zing`.

### Optional extras

- `web` — the local web UI (`zing serve`).

```bash
pip install 'zing-audit[web]'      # pip, from PyPI
pip install -e '.[web]'            # pip, from source
uv tool install 'zing-audit[web]'  # uv, from PyPI
uv pip install -e '.[web]'         # uv, from source
```

The `tokenizers` extra is no longer needed: since 0.19.0 it is empty and kept
only so older install commands still work. zing counts tokens with a built-in
heuristic and downloads nothing at runtime (no tokenizer files), so it also
runs in restricted or offline environments that only reach the relays you
audit.

PDF reports (`--format pdf`, and the PDF download in the web UI) need no extra: they
are typeset with [ReportLab](https://www.reportlab.com/opensource/), a pure Python
dependency that needs no system libraries on Linux, macOS or Windows.

### With Docker (web UI only)

From a source checkout:

```bash
docker build -t zing .
docker run --rm -p 127.0.0.1:8000:8000 -v zing-data:/data zing
# open http://localhost:8000
```

Always publish the port to `127.0.0.1` as shown. Details and environment
variables: [Developer guide → Docker](DEVELOPER_GUIDE.md#docker) and
[docs/DOCKER.md](docs/DOCKER.md).

## Quick start

```bash
# 1) audit a relay against what it claims (model id + provider hint)
export ZING_API_KEY=sk-your-relay-key
zing check \
  --base-url https://relay.example.com/v1 \
  --api-key env:ZING_API_KEY \
  --model gpt-4o \
  --suite standard

# 2) the strongest check: compare against a trusted baseline of the same model
export OPENAI_API_KEY=sk-your-openai-key
zing compare \
  --target-base-url https://relay.example.com/v1 --target-api-key env:ZING_API_KEY --target-model gpt-4o \
  --baseline-base-url https://api.openai.com/v1 --baseline-api-key env:OPENAI_API_KEY --baseline-model gpt-4o \
  --suite deep

# 3) audit an Anthropic-native (Messages API) relay — the protocol is auto-detected
#    from the base_url/model, or forced with --api anthropic
zing check --base-url https://relay.example.com/v1 --model claude-opus-4-8 \
  --api-key env:ZING_API_KEY --api anthropic

# 4) confirm a suspected substitution: audit the relay's REAL model id against the
#    profile it's sold as (here: a Doubao model passed off as deepseek-v4-flash)
zing check --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY \
  --model doubao-seed-2-0-lite --claimed-model deepseek-v4-flash

# 5) list the models an endpoint advertises
zing models --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY

# 6) inspect the knowledge base
zing kb            # every profile, with its source
zing kb deepseek   # one provider

# 7) generate a config you can commit
zing init          # writes zing.yaml
zing check -c zing.yaml
```

API keys can be given literally, as `env:VAR` or as `file:/path`; reports only
ever contain a fingerprint of the key. A full config file is in
[`examples/zing.yaml`](examples/zing.yaml).

### As a tool for an LLM / agent

zing is built to be driven by another program or model. Everything goes to stdout
as JSON, errors included, and the exit code is the gate.

```bash
# lean, agent-friendly verdict (~5x smaller than --json: no bulky evidence)
zing check --base-url ... --model gpt-4o --compact | jq .verdict.risk

# full structured report when you need every finding's evidence
zing check --base-url ... --model gpt-4o --json

# budget first: which detectors run + estimated API calls, WITHOUT making any
zing check --base-url ... --model gpt-4o --suite deep --dry-run --json

# gate on the exit code (1 if risk >= medium, or the score is below --fail-under);
# config/usage errors exit 2, as JSON
zing check --base-url ... --model gpt-4o --compact --fail-on-risk medium

# machine-readable discovery
zing kb --json                      # the whole knowledge base
zing models --base-url ... --json   # what an endpoint advertises
```

In `--json`/`--compact` mode a bad config prints `{"error": {...}}` (exit 2)
instead of a human message, so a pipeline can parse failures uniformly.

## Web UI (`zing serve`)

Prefer point-and-click? A local web UI wraps the same engine — no CLI needed.

```bash
pip install 'zing-audit[web]'     # or: uv tool install 'zing-audit[web]'
zing serve                        # opens http://localhost:8000
```

In the new UI the form guides you through the configuration:

1. Choose the **Relay / provider**: a provider of the knowledge base or a relay
   you saved. Its base URL is filled in (other known URLs of the provider are
   offered as suggestions). For any other relay choose **Other** and enter the
   **Relay URL**.
2. Add the **API key** if the relay needs one.
3. zing lists the relay's models on its own (when you pick a relay and whenever
   the URL or key changes; **Refresh models** asks again). Pick the **Model to
   request**. A relay without a model list falls back to typing the id
   (**Enter manually**).
4. Optionally pick the **Claimed model** from the knowledge base's models: the
   model the relay says it serves. When the requested model is in the knowledge
   base it is preselected; change it only if the relay sells the model under
   another name. The provider profile zing audits against follows from it.

A relay that is not in the list yet can be kept with **Save to knowledge base**
under a name you give it; next time it is one pick away. The trusted baseline
(**Compare against a trusted baseline**) and the **Tools** page are configured
the same way. The classic UI keeps the plain fields with **Fetch models**.

Then **Start audit** and watch the checks run **live**: every check shows its
score and how long it took, and a check with findings expands to show the
evidence. The result is a shareable verdict report: grade, the per-dimension
checks with their scoring scales, plain-language findings and the performance
section (in the new UI also an **Execution log** of every detector).

Everything runs on your machine: a key typed in the browser reaches only your
local zing server and the relay you audit, never a third party. See
[Privacy and local data](#privacy-and-local-data).

### Pages

The web UI comes in two versions that share the same server and data. The
**classic UI** opens at `/`; its **Try the new UI** link switches to the **new
UI** under `/v2/`, and the new UI's **Classic UI** link switches back. The
choice is remembered per browser.

| Page | Classic UI | New UI | What it is for |
|---|---|---|---|
| **Audit** | `/` | `/v2/` | Audit a relay (optionally against a baseline) and read the report |
| **Console** | `/console` | — | The same audit as a compact, log-style console |
| **Tools** | `/tools` | `/v2/tools` | Embedding and rerank audits |
| **History** | `/history` | `/v2/history` | Every audit run on this machine, grouped by relay + claimed model, with trends |
| **Analytics** | — | `/v2/analytics` | Relays and models compared over time: KPIs, charts with data tables, leaderboards |
| **Monitors** | `/watches` | `/v2/watches` | Scheduled re-audits with webhook alerts |
| **Knowledge** | — | `/v2/kb` | The knowledge base in three tabs — models, providers, relays: browse, switch on/off, add your own |

The new UI adds: filters and configurable trends (score, grade, latency p50,
tokens/s) on **History**; **Schedule as monitor** and **Re-run audit** on every History run; **Download
report** in every format; a theme switch (Auto theme / Light / Dark); and the
**Knowledge** page.

**Background audits (new UI).** An audit started on the **Audit** page keeps
running when you switch pages or close the tab; **Continue in background** sends
it there on purpose. **History** lists every queued and running audit (and every
running monitor) with its progress; **Watch live** reopens the live view, which
catches up on everything that already happened. Audits of the same relay run one
after another, so they never skew each other's latency or reliability results
(all loopback addresses count as one host, so models served from your own
machine queue too); audits of different relays run in parallel, at most four at
once (`ZING_MAX_PARALLEL_AUDITS`). Monitors wait for their relay the same way.

**Analytics (new UI).** `/v2/analytics` turns the local history into
comparisons: KPI tiles for the chosen period (runs, median score, high-risk
share, success rate, TTFT, decode speed, billing ratios) with the change
against the period of the same length before; a chart of any metric per relay,
model or relay × model by hour, day or week (median line with the p25–p75 band,
up to four series, every chart also as a data table); and a leaderboard of the
relays for a model, or the models for a relay. Relays are grouped by their
knowledge-base entry (saved relays and providers), so renaming a relay
regroups its history. Buckets with fewer than 3 runs are drawn faded — a single
audit can be an outlier; a monitor gives regular measurements. Older runs show
what they measured: the page says how many runs a value is based on. By default
it compares one suite and probe mode (the most common ones), so unlike runs are
not mixed; the filters and view are kept in the URL, so a view can be
bookmarked or shared. Nothing leaves the machine.

Further panels answer narrower questions: **peak hours** (a weekday × hour
heatmap of TTFT, latency, success or error rate in your time zone — does a
relay slow down or fail more at busy times?), **errors and reliability** (failed
calls by cause — rate limits (HTTP 429), server errors (5xx), timeouts, network
errors — over time and per relay or model, from the stored request records,
with how many runs have them), **model integrity** (identity, context-window and
capability check results per relay × model, the share of runs whose echoed
model differs and the measured share of the declared context window),
**billing and tokens** (billing ratios over time against the 100% line — above
it the relay reports more tokens than zing counted — plus reasoning and cached
input shares) and **relay overhead** (the processing time a relay reports next
to the network round trip to it).

**Tabs and share links (Analytics).** The panels sit in five tabs —
**Overview** (KPIs, leaderboard), **Trends** (comparison over time, peak
hours), **Reliability** (errors, relay overhead), **Model integrity** and
**Billing** — under the page header and one filter panel shared by all of
them; only the tab you look at loads. The URL keeps the tab, the filters and
every chart option (`#tab=reliability&range=30&relay=…&eb=dow_hour`), and
**Copy link to this view** copies it (or shows it in a field to copy where the
browser does not allow that): opening the link shows exactly that view. The
filter panel is the same on **History** and **Analytics**: closed, it shows how
many filters are active and names them in one line (e.g. "Last 30 days ·
standard · Streaming · Example Relay"), so a shared view says what it shows.

### Languages

A language dropdown in the header of every page switches the UI between
**🇬🇧 English** (default), **🇨🇳 Chinese** (the original UI), **🇫🇷 French**,
**🇪🇸 Spanish**, **🇵🇹 Portuguese**, **🇮🇹 Italian** and **🇩🇪 German**; the choice
is remembered per browser.

Reports downloaded from the UI (**Download report**: JSON, Markdown, HTML or PDF)
follow the selected language: the JSON keys, enum values (`risk_level`,
`status`, `severity`, …), ids and evidence stay exactly as in the CLI's report
(the JSON is still a valid zing report), while the human-readable values
(verdict headline and summary, finding titles and summaries, recommendations,
detector names, notes) are translated, and the file name carries the language
(`zing-report.de.json`, `zing-report.de.pdf`). The section headings of the
Markdown/HTML/PDF files are English. The CLI's own `--format json|md|html|pdf`
reports stay English.

**Prompts sent to the audited endpoint do not follow the UI language.** Every
text zing sends to an LLM API is English, so the same relay gets the same
verdict whoever reads the report (answer checks and token estimates are
calibrated to these exact texts). The only exceptions are knowledge-base
fingerprints whose language *is* the measurement — for example the Chinese
fluency, tokenizer and self-identification probes of China-native models. Each
report records the probe languages it actually used (`prompt_languages`, e.g.
`["en", "zh"]`).

Each report also records how the endpoint was spoken to: the wire protocol
(`target.api`: `openai`, `anthropic` or `responses`), whether `--api auto`
detected it (`target.api_auto`), and the performance probe's request mode
(`stream_mode`: `stream`, `non_stream` or `both` for the full suite). The web
UI's history page can filter on all three. `started_at` records when the audit
started (UTC); the `start_ms` of every request record counts from it.

## What it checks

zing scores ten dimensions. The four **core dimensions** — model identity,
context window, capability claims and billing & usage — most directly reveal a
bait-and-switch. The names are the ones the web UI and reports use.

| Dimension | Id | Weight | What it catches |
|---|---|---|---|
| **Model identity** | `model_identity` | 21 | Silent model downgrade or substitution — self-identification, knowledge cutoff, tokenizer fingerprints, the echoed `model` field; optionally an LLM judge |
| **Context window** | `context_window` | 19 | Silent context truncation (claims 1M, recall fails at 32K) and lost-in-the-middle from cheap RAG/summarization shims, via needle-in-a-haystack and binary search |
| **Capability claims** | `capability` | 13 | Tool calling / JSON mode / JSON schema / max-output claims that aren't delivered (or are *over*-delivered, hinting at a substitute); **vision** — a model claiming image input must read a generated known-answer image |
| **Protocol compliance** | `protocol` | 8 | Wire conformance: multi-turn, stop sequences, error schema; every request parameter accepted (and honored where visible), every response attribute present; response caching that ignores temperature/seed |
| **Billing & usage** | `billing` | 8 | Token/usage inflation and missing or unverifiable usage accounting, via an independent heuristic token estimate |
| **Connectivity** | `connectivity` | 7 | Endpoint reachability and the advertised `/v1/models` list |
| **Streaming authenticity** | `streaming` | 6 | Fake streaming (buffer-then-chunk), from chunk count and inter-chunk timing |
| **Concurrency reliability** | `reliability` | 6 | Success rate and latency under concurrent load (HTTP 429 throttling counted separately) |
| **Transport security** | `security` | 6 | HTTPS, header hygiene, secret echo; a hidden injected system prompt; in-flight tampering of answers and tool calls (known-answer canaries); prompt-prefix caching (timing) |
| **Performance** | `performance` | 6 | How *consistent* latency, time to first token and throughput are, the failure rate and the slowdown under load; speed only against a reference (see [Performance](#performance)) |

The [Methodology](docs/METHODOLOGY.md) describes every probe, which relay trick
it maps to, its scoring scale and its false-positive caveats.

## How the verdict is reached

In short (the [Methodology](docs/METHODOLOGY.md#how-zing-scores) has the details):

- Every detector publishes its **scoring scale** — each possible outcome of each
  check with its points — and the web UI shows it under **Scoring scale**.
- A **dimension score** is the equal-weight mean of its detectors' scores. A
  HIGH/CRITICAL finding forces **Fail** and a MEDIUM finding lifts **Pass** to
  **Warning**, whatever the score. Reports explain this per dimension under
  **Dimension details**; in the web UI each row of **Per-dimension checks**
  expands into the same details.
- The **overall health score** is the weighted mean of the dimensions that ran
  (weights above), rated A (≥ 90), B (≥ 80), C (≥ 70), D (≥ 60) or F.
- The **risk verdict** is driven by finding severity, not by the score:

| Risk | Label in the UI | When |
|---|---|---|
| `inconclusive` | Insufficient signal | Nothing usable to judge by: none of model identity, context window and capability claims produced a usable result when they ran (relay unreachable, model not in the knowledge base), or no dimension but connectivity did |
| `high` | Bait-and-switch | A CRITICAL finding, a HIGH/CRITICAL finding in a core dimension, or two or more HIGH findings |
| `medium` | Deviations found | Exactly one HIGH finding outside the core dimensions, or a MEDIUM finding in a core dimension |
| `low` | Mostly trustworthy | Any other MEDIUM finding |
| `clean` | Consistent (likely genuine) | None of the above |

Findings of the connectivity dimension never raise the risk: a relay that is down
or throttled could not be assessed, which is not evidence of a different model.
Transport advisories — plain HTTP (`security.tls`) and failures or slow tails
under load (`reliability.*`) — lower their dimension's score but do not raise the
substitution risk either; the summary lists them as advisories. Integrity
tampering and an echoed API key still do. Plain HTTP to this machine or a private
network is only a low-severity warning, since the key never leaves it.
The headline names the dimensions that set the risk: it speaks of the claimed
model only when model identity is among them (a truncated context window reads
"does not deliver what it advertises: Context window"), and a verdict without a
model-identity result says that model identity was not verified.
The verdict's **confidence** (low / medium / high) grows with the number of core
dimensions that produced a result, a baseline and the LLM judge; a model id that
only matched a knowledge-base profile fuzzily caps it at low. A detector that got
no usable answer (e.g. every model-identity probe failed) is inconclusive and
counts as no signal, never as a pass.

## Suites

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

### Custom suite

Run just the dimensions you care about, which saves time and tokens. Every
detector of each selected dimension runs, as on `deep`:

```bash
zing check --base-url ... --model gpt-4o -D protocol -D performance
zing check --base-url ... --model gpt-4o --suite custom --dimension billing,streaming
```

`--dimension/-D` is repeatable or comma-separated and implies `--suite custom`;
in a config file use `run.dimensions: [protocol, performance]`. The dimensions
are `connectivity`, `protocol`, `context_window`, `model_identity`, `capability`,
`streaming`, `billing`, `reliability`, `security` and `performance`. In the web
UI, the `custom` suite button opens the same choice (**Dimensions to run**) on
the audit page, the console and the monitors.

The **overall score is the weighted mean of the selected dimensions only**;
dimensions you left out are reported as "not selected". The risk verdict is
judged on the selected dimensions too: without model identity it covers only
them, not which model is served, and says so.

## Performance

Every report carries a **performance** section: latency, time to first token
(TTFT), decode and end-to-end tokens/s, inter-chunk latency and jitter,
error/timeout/429 rates, a network breakdown (TCP connect, TLS, a `GET /models`
round trip, server time) and cold start, each as count / min / mean / p50 / p75 /
p90 / p95 / p99 / max / stdev.

When the dedicated probe runs, it scores the **Performance** dimension. The score
is about **consistency**, not raw speed, so a slow but steady endpoint (a local
or self-hosted model) is not marked down for not being a data centre:

| Check | Scored on |
|---|---|
| latency / TTFT consistency | tail ratio p90 ÷ p50 (≤ 1.3 steady 100 · ≤ 1.75 stable 85 · ≤ 2.5 variable 65 · above: erratic 40); needs ≥ 10 samples |
| throughput consistency | tail ratio p50 ÷ p10 of tokens/s, same bands |
| errors | failed probe requests: ≤ 2% 100 · ≤ 10% 80 · above: 50 (429s not counted) |
| load stability | burst p50 latency ÷ sequential p50: ≤ 1.5x 100 · ≤ 3x 80 · above: 55 |
| cache hit | unique prompts answered from a cache: 60 |
| reference | tokens/s against the trusted baseline, or else the knowledge base's published range for the model: in line 100 · slower: not counted (informational, never a failure) · ≥ 2x faster 60 (hints at a smaller model) · no reference: not counted |

Performance findings are at most low severity: they move the score, never the
risk verdict. Without the probe (`standard` without a baseline, `smoke`), the
dimension does not run and drops out of the overall score.

- **standard** collects the section from the audit's own requests.
- **deep / full / custom** add a dedicated probe: 100 uncacheable requests of 128
  output tokens (a random request id opens every prompt; no cache or reasoning
  parameters are sent) plus a burst at `--concurrency`. Tune it with
  `--performance-requests` (0 disables) and `--performance-max-tokens`.
- The probe streams by default; `--performance-non-streaming` (or the
  **Streaming / Non-streaming** switch in the web UI) measures relays that cannot
  stream. **full** measures both modes, interleaved, and reports them side by side.
- **compare** runs the probe on both endpoints, alternating requests, and adds a
  target-vs-baseline table (5 requests per side on `standard`, too few for the
  consistency checks) whose differences are marked green ✓ where the target is
  better and red ✗ where it is worse.

Tokens are counted twice — from the relay's `usage` and locally — so throughput
is measurable even when `usage` is missing. The local count is an estimate from
a built-in heuristic (about ±15-20%; no tokenizer is used or downloaded), and the
section always says so. A percentile is shown only with
enough samples (p90 from 10, p95 from 20, p99 from 100). The JSON report keeps
every request's timings (numbers only, no text); the HTML report and the web UI
chart them over the audit's timeline.

Audits that run at the same time in `zing serve` (several browser tabs,
monitors) do not distort each other's timings: CPU-heavy preparation, such as
building the long context-window prompts, runs off the server's event loop.

**Request timeouts.** `timeout_sec` (`--timeout`, default 60 s) is the base;
each request gets more for its prompt size and output budget, so a long
context-window probe or a slow self-hosted model is not cut off after a minute.
Local and private hosts (`localhost`, `127.x`, `192.168.x`, `host.docker.internal`,
…) get at least 300 s. `max_request_sec` (`--max-request-time`, default 900 s) is
the hard cap for any single request, streams included, so no request can hang
forever. A context-window probe that still times out is reported as
inconclusive, not as truncation.

## Compare mode and the LLM judge

zing has two detection modes:

- **Pure code (default):** every detector except `quality_judge` decides by
  deterministic code — fingerprints, the context sweep, billing arithmetic,
  streaming timing. No second model is needed; results are reproducible.
- **Code + LLM hybrid (`--judge`):** additionally asks a *trusted* judge model
  (configured separately, never the target) whether the target's answers read
  like the claimed model — fuzzy signals such as quality and reasoning depth that
  pure code can't decide. This is the `quality_judge` detector.

```bash
zing check --base-url ... --model gpt-4o --suite deep --judge \
  --judge-base-url https://api.openai.com/v1 --judge-api-key env:OPENAI_API_KEY --judge-model gpt-4o-mini
```

**Compare mode** (`zing compare`, or **Compare against a trusted baseline** in
the web UI) runs the same probes against a trusted baseline of the claimed model
at the same time. It is the strongest confirmation path: identity answers,
rejected request parameters, tampering canaries and performance are all judged
side by side, and only a baseline lets the verdict's confidence reach *high*.
Without `--judge-base-url`, compare mode uses the baseline as the judge.

## Monitoring

Relays can serve the real model today and quietly swap it next week. `zing watch`
re-audits on a schedule, records each run to the history, and alerts a webhook
when the risk crosses a threshold or **regresses** versus the previous run.

```bash
zing watch --base-url https://relay.example.com/v1 --api-key env:ZING_API_KEY \
  --model gpt-4o --suite standard --interval 3600 \
  --alert-on medium --webhook "$FEISHU_WEBHOOK" \
  --alert-lang en                                     # or --once for cron
```

Alerts are formatted for **Slack / Feishu / DingTalk / generic JSON**,
auto-detected from the webhook URL, and written in the alert language — English
by default; `--alert-lang en|zh|fr|es|pt|it|de`. The generic JSON payload keeps
its keys and machine values (`risk_level`, `score`, …) language-neutral,
translates the human-readable ones (`text`, `headline`, `key_findings`) and
reports the `language`.

**In the web UI**, `zing serve` runs the same monitors in a background scheduler
inside the server process, stores every run in **History** and sends the same
webhook alerts:

- **New UI:** open a run in **History** and choose **Schedule as monitor**. zing
  copies that run's configuration (relay, model, claimed model, provider, suite,
  custom dimensions) into a paused monitor on the **Monitors** page; set its
  interval and API key there (History never stores keys) and switch it on.
  Interval, key, **Alert threshold**, webhooks and **Alert language** can be
  edited in place on each monitor.
- **Classic UI:** fill in the form on the **Monitors** page and **Add monitor**.

Each monitor has its own alert language (defaulting to the UI language), can be
run now, paused or deleted, and pins the knowledge-base profile it was created
with until you re-pin it.

Monitors that come due run at the same time, each as its own audit, but never
more than one audit per relay host at once and at most `ZING_MAX_PARALLEL_AUDITS`
in total; a run waits for a free slot (an audit you start by hand may queue
behind running monitors, too). A run's time is when its audit starts, after any
wait. The regression check compares against the most recent saved run of the
same relay and model, however many other runs were saved since. Alert webhooks
of a run are sent at the same time, so a slow or dead one does not hold up the
others. Keys are stored encrypted in your local data directory
and are never sent back to the browser.

**Master key.** The monitors' API keys are encrypted with a master key that zing
never writes to disk. The first time you store an API key, the **Monitors** page
creates it and shows it once: copy or download it, keep it in a password manager
(your browser can save it), then paste it back to confirm. After every restart
of `zing serve` the page asks for it again (the browser can fill it in); until
then, monitors that need it wait, while keyless monitors and `env:`/`file:` keys
keep running. The status bar on the **Monitors** page also offers **Lock**,
**Rotate** and **Forgot the key?** (drops the encrypted API keys so you can
enter them again). For unattended or Docker use, pass the key as
`ZING_SECRET_KEY` (see [docs/DOCKER.md](docs/DOCKER.md));
`zing secret status | export | rotate` manage it on the command line.

## Embedding, rerank, image and audio audits

These endpoints return vectors, rankings, images or audio instead of chat, so
zing audits them with focused, standalone auditors instead of the ten-dimension
chat pipeline. Each prints a verdict and supports `--json` and `--fail-on-risk`.

### Embeddings and rerank

```bash
# The expected vector dimension is resolved from the knowledge base for the claimed model.
zing embed --base-url https://relay.example.com/v1 \
           --model text-embedding-3-large --claimed-model text-embedding-3-large --fail-on-risk high

# Or give the expected dimension directly:
zing embed --base-url ... --model my-embed --claimed-dimensions 1024 --json

# Rerank: a built-in known-answer probe — a genuine reranker must rank the
# obviously relevant document first.
zing rerank --base-url https://relay.example.com/v1 --model my-rerank
```

`embed` checks connectivity, **dimension match** (the returned vector length
against the claimed model's native dimension — the headline bait-and-switch
signal: a relay claiming 3072-d `text-embedding-3-large` but returning 1024-d
serves a substitute), determinism (same input → cosine ≈ 1), distinctness
(unrelated inputs → cosine well below 1) and the echoed `model` field. Bundled
profiles: OpenAI `text-embedding-3-small` (1536), `text-embedding-3-large`
(3072), `text-embedding-ada-002` (1536), Qwen `text-embedding-v3`/`-v4` (1024).

Both are also on the web UI's **Tools** page (**Embedding audit**, **Rerank
audit**), where the rerank probe can be replaced by your own query and documents.

### Image and audio (TTS) generation

Image generation (`POST /v1/images/generations`) and text-to-speech
(`POST /v1/audio/speech`), decoded with the Python standard library only — image
dimensions from the header bytes (PNG/JPEG/GIF/WebP), WAV duration via `wave`.

```bash
# Does a relay claiming DALL·E 3 actually return the requested 1792x1024? A
# downscaled or wrong-size image (or a size outside the claimed model's native
# sizes, from the knowledge base) is the headline bait-and-switch signal.
zing image --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model dall-e-3 --claimed-model dall-e-3 --size 1792x1024 --fail-on-risk high

# Does a relay claiming tts-1-hd return real audio whose length scales with the
# input (not a fixed placeholder, not HTML/JSON masquerading as audio)?
zing audio --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model tts-1-hd --voice alloy --format wav --save clip.wav
```

`image` checks connectivity, a valid and decodable format, **size match**
(decoded width × height against the request and the claimed model's native
sizes — FAIL/HIGH on a mismatch), distinctness (two prompts → different images,
catching a fixed placeholder), count and the `model` field. `audio` checks
connectivity, container/format validity, that the format is honored, a
non-trivial duration that scales with the input, distinctness and the `model`
field. The knowledge base ships OpenAI DALL·E 2/3, gpt-image-1,
tts-1/tts-1-hd/gpt-4o-mini-tts and Qwen image/TTS profiles.

## Use in CI (GitHub Action)

Gate any workflow on a relay audit with the bundled composite action. It runs
`zing check --compact --fail-on-risk`, exposes `risk` / `score` / `rating` as
outputs, writes a summary to the run and fails the job when the risk gate trips.

```yaml
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - id: zing
        uses: cenbonew/zing@v0.20.0         # pin to a release tag
        with:
          base-url: https://relay.example.com/v1
          api-key: ${{ secrets.RELAY_API_KEY }}   # caller secret; never echoed
          model: gpt-4o
          fail-on-risk: high
      - run: echo "risk=${{ steps.zing.outputs.risk }} score=${{ steps.zing.outputs.score }}"
```

The relay key is forwarded through an environment variable (`--api-key env:…`),
so it never appears on a command line. See [docs/CI.md](docs/CI.md) for every
input and output and a deploy-gating example.

## Knowledge base

zing judges a relay against the **profile** of the model it claims: native
context window, max output, knowledge cutoff, tokenizer, capability flags,
identity keywords and behavioral fingerprints. The packaged profiles cover
OpenAI, Anthropic, Google Gemini, DeepSeek, Qwen, GLM and Moonshot
(`zing kb` lists them). There are three layers, later ones winning:

1. **Packaged** profiles, one YAML file per provider in
   [`zing/knowledge/data/`](zing/knowledge/data).
2. **A directory of your own YAML files**: `--kb-dir ./my-profiles` (repeatable)
   or `ZING_KB_DIR`.
3. **Your entries** (`kb.db` in the data directory), added without YAML files
   or an editable install:
   - in the web UI's **Knowledge** page (`/v2/kb`), with one tab each for
     **Models**, **Providers** and **Relays**. Every tab lists the complete set —
     packaged, `ZING_KB_DIR` and yours (marked **Yours**) — with a filter, an
     on/off switch per item and an **Add …** form: **Add a model** → **Copy the
     research prompt** into the AI assistant of your choice, upload or paste the
     YAML it answers with, then **Check and save**; **Add a provider** takes
     provider YAML the same way; **Add a relay** takes a name and a base URL.
     **Which profile does a model id use?** shows how an id resolves; your
     entries can be exported as YAML;
   - on the web UI's **Audit** and **Tools** pages: **Save to knowledge base**
     keeps a relay's name and base URL (a provider entry without models), listed
     under **Knowledge → Relays**;
   - on the CLI: `zing kb-prompt <model>`, `zing kb-import <file>` (add `--check`
     to only check it) and `zing kb-export`.

Before storing an entry zing checks it: schema and limits, unsafe regular
expressions, every prompt it would send, and model ids that would resolve to a
different profile. A model of yours with a packaged id replaces it (reported as
*shadowing* it), but never changes a packaged provider's own settings;
fingerprints are merged by id. Switching off a packaged model, provider or
relay on the **Knowledge** page is stored in `kb.db` too: a switched-off model
id no longer resolves, a switched-off provider takes its models and base URLs
with it. `zing check` and `zing serve` use exactly the same profiles;
`--no-user-kb` (or `ZING_NO_USER_KB=1`) leaves your entries and switches out.

A model whose `identity_keywords` is empty is not stored that way: zing fills
in its own brand words from the provider and model names (for example `glm`
and `z.ai`) and shows a warning to check them, since
without them the identity check could take the model naming its own vendor for
a rival brand. The research prompt asks the AI assistant for them explicitly.

Every report records the profile it audited against (`knowledge`: provider,
model, how the id matched, its source, and a full snapshot with its content
hash), so a report stays verifiable after the knowledge base changes.

## Reports

`zing check` and `zing compare` print a verdict and write the report to `reports/`
(`--out-dir`) as JSON, Markdown, HTML and PDF (`--format all`, the default);
`--format json|md|html|pdf` writes one format. `--json` and `--compact` print to
stdout instead.

```text
╭─ ✗ HIGH RISK — Strong evidence the relay does not deliver the claimed model… ─╮
│ Target : my-relay · model gpt-4o · provider openai                            │
│ Mode   : check · suite deep                                                   │
│ Score  : 53.5/100 (rating F) · confidence medium                             │
│                                                                               │
│ Overall health score 53.5/100. Findings: 3 high. …                            │
╰───────────────────────────────────────────────────────────────────────────────╯
  • Self-identifies as a rival brand (anthropic) under the claimed model id gpt-4o
  • Real context window ~8000 << declared 128000 (silent truncation suspected)
  • Reported prompt tokens far exceed independent estimate
```

A report contains the verdict (risk, confidence, score, rating), the key
findings with recommendations, the per-dimension scores and **Dimension
details**, every detector's findings with evidence, the performance section, the
knowledge-base profile used and the probe languages. Relay-controlled text is
redacted and escaped before it is written.

## Privacy and local data

- **Local only.** `zing serve` listens on loopback only (`127.0.0.1`, `::1`,
  `localhost`), answers only to those host names and refuses cross-site
  requests; it has no login because nothing outside your machine can reach it.
  zing contacts only the endpoints you configure (target, baseline, judge,
  webhooks); it downloads nothing at runtime, not even tokenizer files.
- **Keys.** Reports and history keep only a fingerprint of an API key. The
  monitors' keys are stored encrypted in `watches.db`; the master key that
  decrypts them is never written to the data directory (you keep it, see
  **Monitoring** above), so a copy of the directory reveals no API key. The
  directory is owner-only all the same.
- **Data directory.** `~/.zing` (or `ZING_DATA_DIR`), created `0700` with `0600`
  files: `history.db` (audit history), `watches.db` (monitors, with their keys
  encrypted) and `kb.db` (your knowledge-base entries). Delete the directory to
  remove everything. `zing data-dir` prints where it is; `--data-dir PATH`
  picks another one for a single run, e.g. `zing serve --data-dir .` keeps the
  databases in the current folder. They are plain SQLite files, so you can open
  them (read-only is safest while zing runs) for your own analysis:
  `history_metrics` holds one row of measured values per run and
  `history_requests` every request record (stored there once, not inside each
  saved report). Don't
  commit `watches.db` if that folder is a repository.

## Responsible use

zing is a black-box auditing aid. It **cannot prove**:

- that a provider stores or trains on your prompts,
- that it always routes to one exact model (relays can route probabilistically),
- billing fraud beyond what independent token estimation can suggest.

Use reports for your own due diligence. **Do not publicly accuse a vendor** based
on a single run without reviewing sample size, cost settings and local law. Run
`zing compare` against a trusted baseline before drawing strong conclusions.

## Further documentation

| Document | For |
|---|---|
| [Methodology](docs/METHODOLOGY.md) | How every check works, its scoring scale and its caveats |
| [Developer guide](DEVELOPER_GUIDE.md) | Architecture, development setup, contributing, translations, Docker, releases |
| [docs/CI.md](docs/CI.md) | The GitHub Action: inputs, outputs, examples |
| [docs/DOCKER.md](docs/DOCKER.md) | Running the web UI in a container |
| [CHANGELOG.md](CHANGELOG.md) | What changed in each release |
| [SECURITY.md](SECURITY.md) | Reporting a vulnerability |

## License

[Apache-2.0](LICENSE)
