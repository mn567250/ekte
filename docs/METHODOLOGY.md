# zing — Methodology

> **🇬🇧 English** · [🇨🇳 中文](METHODOLOGY.zh-CN.md) · [🇫🇷 Français](METHODOLOGY.fr.md) · [🇪🇸 Español](METHODOLOGY.es.md) · [🇵🇹 Português](METHODOLOGY.pt.md) · [🇮🇹 Italiano](METHODOLOGY.it.md) · [🇩🇪 Deutsch](METHODOLOGY.de.md)

This document explains how **zing** reaches its verdict: which black-box probes
each detector sends, how their outcomes become points, how points become
dimension scores and an overall score, and how the risk verdict is decided. It
describes the current implementation; every scoring table below is the
detector's published scale (`SCALE` in `zing/detectors/*.py`) with the same
wording the web UI shows under **Scoring scale**.

> zing reports **black-box evidence of divergence and risk, not cryptographic
> proof of fraud.** See [Limitations & responsible use](#limitations--responsible-use).

---

## Core stance

A relay may legitimately drift, update snapshots, pool capacity or buffer an
upstream that cannot stream. zing therefore treats every single signal as a
*risk indicator*, never as a verdict: findings are evidence-first, worded
cautiously, and an ambiguous result stays **inconclusive** rather than being
forced into pass or fail. The risk verdict only reaches HIGH on hard,
high-severity evidence, and the strongest confirmation path is always
**compare mode** (`zing compare`): run the same probes against a *trusted
baseline of the claimed model* at the same time.

## How zing scores

### Detector score

Every detector publishes its **scoring scale** (`DetectorResult.scoring`, built
with `zing/detectors/scale.py`): every possible outcome of each of its checks,
with status, severity and effect on the score. Each finding records the
`outcome` it hit, so report and behavior cannot disagree. A scale uses one of
two methods:

- **Mean of checks** (`Scale`, method `mean_of_checks`): each check scores
  points; the detector score is the mean of the counted checks. An outcome
  marked **Not counted** (typically an inconclusive check) neither raises nor
  lowers the score.
- **Deductions** (`DeductionScale`, method `deductions`): the score starts at
  100, findings deduct points (`Finding.deduction`) and/or cap the score
  (`Finding.cap`); the lowest cap wins.

A *parametrized* check applies one row set to many subjects (for example every
response attribute): each subject is scored on its own, the scale is published
once per check, and reports list the subjects under their check.

### Dimension score and status

zing scores ten dimensions. A dimension's score is the **equal-weight mean of
its detectors' scores**: a detector with many checks does not outweigh one with
few, and a detector without a numeric score is left out. Its status is the
worst status its detectors concluded, except that a HIGH/CRITICAL finding
forces **Fail** and a MEDIUM finding lifts **Pass** to **Warning**, whatever the
score. Every report records this per dimension (`DimensionScore.breakdown`:
each detector's score, whether it counted, and any status override with the
findings that caused it) and shows it under **Dimension details**
(Markdown/HTML/PDF) and in the expandable rows of **Per-dimension checks** in
the web UI. A detector that crashes is reported with status **Error** and never
aborts the audit.

### Overall score, rating and weights

The **overall health score** is the weighted mean over the dimensions that
produced a score (`DIMENSION_WEIGHTS` in `zing/scoring.py`). A dimension that
did not run (not in the suite, or not selected in a `custom` run) drops out and
the remaining weights are renormalised. The rating is A (≥ 90), B (≥ 80),
C (≥ 70), D (≥ 60) or F.

| Dimension | Id | Weight | Role |
|---|---|---|---|
| Model identity | `model_identity` | 21 | core |
| Context window | `context_window` | 19 | core |
| Capability claims | `capability` | 13 | core |
| Protocol compliance | `protocol` | 8 |  |
| Billing & usage | `billing` | 8 |  |
| Connectivity | `connectivity` | 7 |  |
| Streaming authenticity | `streaming` | 6 |  |
| Concurrency reliability | `reliability` | 6 |  |
| Transport security | `security` | 6 |  |
| Performance | `performance` | 6 |  |

The three **core dimensions** are the ones whose failure most directly reveals
a bait-and-switch.

### Risk verdict

The risk level is driven by **finding severity**, not by the score. Findings of
the connectivity dimension are left out of the ladder: a relay that is down or
throttled could not be assessed, which is not evidence of a different model.

| Risk | Label in the UI | When |
|---|---|---|
| `inconclusive` | Insufficient signal | No core dimension produced a usable result (Pass, Warning or Fail) — for example the relay is unreachable, the model is unprofiled, or a `custom` run selected no core dimension |
| `high` | Bait-and-switch | A CRITICAL finding, a HIGH/CRITICAL finding in a core dimension, or two or more HIGH findings |
| `medium` | Deviations found | Exactly one HIGH finding outside the core dimensions, or a MEDIUM finding in a core dimension |
| `low` | Mostly trustworthy | Any other MEDIUM finding |
| `clean` | Consistent (likely genuine) | None of the above |

### Verdict confidence

- **low** — the claimed model is not in the knowledge base, or fewer than two
  core dimensions produced a usable result;
- **medium** — at least two core dimensions produced a usable result;
- **high** — a baseline was used *and* all three core dimensions produced a
  usable result, or the confidence was medium and the LLM judge returned a
  usable verdict.

## Suites, detectors and modes

| Detector | Id | Dimension | From suite |
|---|---|---|---|
| Connectivity & basic completion | `connectivity` | Connectivity | `smoke` |
| OpenAI-compatibility conformance | `protocol` | Protocol compliance | `standard` |
| Request attribute support | `protocol_request` | Protocol compliance | `standard` |
| Response attribute availability | `protocol_response` | Protocol compliance | `standard` |
| Determinism & cache-correctness | `determinism` | Protocol compliance | `deep` |
| Real context window & truncation | `context_window` | Context window | `deep` |
| Model identity & downgrade fingerprinting | `model_identity` | Model identity | `standard` |
| LLM-judged quality / downgrade assessment | `quality_judge` | Model identity | `deep` (only with `--judge`) |
| Capability-claim verification | `capability` | Capability claims | `standard` |
| Multimodal (vision) capability verification | `vision` | Capability claims | `deep` |
| Streaming authenticity | `streaming` | Streaming authenticity | `standard` |
| Token/usage billing audit | `billing` | Billing & usage | `standard` |
| Concurrent reliability & latency | `reliability` | Concurrency reliability | `standard` |
| Transport & secret-handling signals | `security` | Transport security | `smoke` |
| Injected system-prompt detection | `injected_prompt` | Transport security | `deep` |
| Response integrity / tampering | `integrity` | Transport security | `deep` |
| Prompt prefix-cache (timing) | `prompt_cache` | Transport security | `deep` |
| Performance probe | `performance` | Performance | `deep` (on `standard` only in compare mode, 5 requests) |

- **smoke** runs connectivity and security; **standard** adds the protocol,
  identity, capability, streaming, billing and reliability detectors; **deep**
  adds the long-context, determinism, vision, injected-prompt, integrity,
  prompt-cache and performance probes (and the judge with `--judge`); **full**
  runs the same detectors as deep and measures performance both streaming and
  non-streaming; **custom** runs every detector of the selected dimensions at
  deep depth.
- **Pure code (default):** every detector except `quality_judge` decides by
  deterministic code — string and regex checks, arithmetic, timing statistics.
  No second model is needed.
- **Code + LLM hybrid (`--judge`):** `quality_judge` asks a separately
  configured, trusted judge model (never the target) whether the target's
  answers read like the claimed model. Without `--judge-base-url`, compare mode
  uses the baseline as the judge.
- **Compare mode** (`zing compare`) gives the probes a trusted baseline:
  `model_identity` records the baseline's self-identification next to the
  target's, `protocol_request` re-sends rejected parameters to the baseline,
  `integrity` escalates a substitution the baseline does not make to CRITICAL,
  `quality_judge` shows the judge both sides, and `performance` probes both
  endpoints alternately. Confidence can only reach high with a baseline.
- **Knowledge base:** the claimed model's profile (`zing/knowledge/data/*.yaml`
  plus your own entries in `kb.db`) supplies the declared context window, max
  output, tokenizer, capability flags, identity keywords and behavioral
  fingerprints the probes are judged against. Every report records the profile
  it used (`knowledge`).
- **Prompt language:** every probe text lives in `zing/prompts/en.json` and is
  English whatever the UI language; only fingerprints whose language *is* the
  measurement declare `prompt_lang` and `language_bound`. Each report lists the
  probe languages it used (`prompt_languages`).
- **Reasoning models:** a short probe that ends at its output limit with its
  answer missing, or cut off after reasoning took at least half the limit
  (`reasoning_tokens` reported), is repeated once with a 4,096-token
  limit, so a model that thinks before it answers is not read as failing.
  Probes whose limit or timing is the measurement (performance, prompt cache,
  reliability, injected prompt, maximum output, the `max_tokens` request
  attribute) are never
  repeated. Once an endpoint is known to reason (its profile says
  `reasoning: true`, or after its first such repeat), short probes are sent
  with the 4,096-token limit from the start instead of twice.
- **Request parameters:** reasoning models refuse some parameters: on Chat
  Completions `max_tokens` (they take `max_completion_tokens`), and on every
  protocol sampling parameters such as `temperature`. The client leaves out the
  parameters the profile lists under `unsupported_params` and sends the output
  limit as `max_completion_tokens` when `max_tokens` is listed. An endpoint
  without a profile that names such a parameter in a 4xx gets the request once
  more, adapted, and every later request goes out adapted from the start; the
  rejected attempt is not counted as a relay error. The `protocol_request`
  probes are sent exactly as built, since the raw rejection is what they judge.

---

## `connectivity` — Connectivity

**Catches.** No trick directly: it is the gate every other detector depends on.
It separates a dead or misconfigured key from a relay worth auditing.

**How it works.** `GET /v1/models` (records whether the claimed model is
listed) and one chat completion at `temperature=0` asking the model to echo an
exact canary marker; records latency and the echoed `model` field.

**Scoring scale** (`zing/detectors/connectivity.py`):

| Check | Outcome | Status | Effect |
|---|---|---|---|
| `connectivity.models` | The model list (/v1/models) responded. | Pass | 100 pts |
|  | The model list (/v1/models) did not respond; some relays disable it. | Warning · Low | 60 pts |
| `connectivity.chat` | A chat completion returned content and echoed the canary. | Pass | 100 pts |
|  | A chat completion returned content but did not echo the canary. | Pass | 85 pts |
|  | The chat completion failed or returned no content. | Fail · High | 0 pts |

**Caveats.** A missing `/v1/models` is benign; many relays disable it. A
transient network error or 5xx can fail the chat check: re-run. Connectivity
proves nothing about *which* model answered. Its findings never raise the risk
verdict.

---

## `protocol` — Protocol compliance

**Catches.** Relays whose middleware breaks the wire contract (dropped turns,
ignored stop sequences, malformed errors, missing or zeroed response fields,
stripped request parameters) and, via determinism, `cache.ignore-temperature`.
It partly covers `capability.json-tool-fakery`.

### `protocol` — OpenAI-compatibility conformance

**How it works.** Three probes: a multi-turn conversation that must recall a
color from an earlier turn; a `stop` sequence that must truncate the output; and
a deliberately invalid request (empty `messages`) that must be rejected with a
4xx, ideally with an OpenAI-style error body.

| Check | Outcome | Status | Effect |
|---|---|---|---|
| `protocol.multi_turn` | The color from an earlier turn was recalled. | Pass | 100 pts |
|  | The color from an earlier turn was not recalled. | Warning · Medium | 55 pts |
|  | No usable response to judge by. | Inconclusive · Low | Not counted |
| `protocol.stop` | Output stopped at the stop sequence. | Pass | 100 pts |
|  | Stop handling could not be confirmed from the text. | Warning · Low | 70 pts |
|  | Text after the stop sequence was returned. | Warning · Low | 60 pts |
|  | No usable response to judge by. | Inconclusive · Low | Not counted |
| `protocol.error_schema` | Rejected with a 4xx and an OpenAI-style error body. | Pass | 100 pts |
|  | Rejected with a 4xx, but the body is not OpenAI-style. | Warning · Low | 80 pts |
|  | No HTTP response; client-error handling could not be confirmed. | Warning · Low | 55 pts |
|  | Another HTTP status; client-error handling could not be confirmed. | Warning · Low | 55 pts |
|  | The invalid request caused a server error (5xx). | Fail · Medium | 35 pts |
|  | The invalid request was accepted (2xx). | Fail · Medium | 30 pts |

### `protocol_response` — Response attribute availability

**How it works.** One normal non-streaming call; every attribute of the target's
wire protocol (OpenAI Chat Completions, Anthropic Messages or OpenAI Responses;
catalog in `zing/detectors/wire_attrs.py`) is judged on the raw body. Core
attributes are e.g. `model`, `choices[0].message.role/content`,
`finish_reason`, `usage.prompt_tokens`, `usage.completion_tokens` and
`usage.total_tokens` (which must equal the sum of the two); minor ones are
`id`, `object`, `created`/`created_at`, `choices[0].index` and `type`. A zero
where a count must be positive (`completion_tokens: 0` for a non-empty answer)
scores as zero, not as valid.

| Check | Outcome | Status | Effect |
|---|---|---|---|
| `protocol_response.core` (Core response attributes) | Present with a valid value. | Pass | 100 pts |
|  | Present but zero or empty (e.g. completion_tokens: 0). | Fail · Medium | 20 pts |
|  | Present with a wrong type or value (e.g. total ≠ sum of parts). | Warning · Medium | 40 pts |
|  | Missing from the response. | Fail · Medium | 0 pts |
| `protocol_response.minor` (Minor response attributes) | Present with a valid value. | Pass | 100 pts |
|  | Present but zero or empty. | Warning · Low | 50 pts |
|  | Present with a wrong type or value. | Warning · Low | 70 pts |
|  | Missing from the response. | Warning · Low | 60 pts |
| `protocol_response.call` (Response-attribute probe) | The probe call returned no response body to judge by. | Inconclusive · Low | Not counted |

### `protocol_request` — Request attribute support

**How it works.** Every request parameter of the wire protocol is sent (about
five calls). Parameters with an observable effect get their own call and must
show it: `system`/`instructions` followed, the output limit ending in
`finish_reason: length`, `n: 2` returning two choices, `logprobs` returned.
Accept-only parameters (`temperature`, `top_p`, `seed`, penalties, `user`,
`top_k`, `metadata`) share one call and are retried one by one only when it is
rejected. A 4xx counts as a model limit (not counted) rather than a rejection
when the knowledge base lists the parameter under `unsupported_params`, when a
sampling parameter is sent to a reasoning model, or when a baseline on the same
protocol rejects it too. Tools and JSON mode stay with `capability`, `stop` with
`protocol`, stream usage with `streaming`.

| Check | Outcome | Status | Effect |
|---|---|---|---|
| `protocol_request.param` (Request parameters) | Accepted, and its effect is visible in the response. | Pass | 100 pts |
|  | Accepted (its effect cannot be observed from one response). | Pass | 100 pts |
|  | Accepted, but its effect is missing from the response. | Warning · Low | 50 pts |
|  | Rejected with a 4xx (possibly a limit of the model itself). | Warning · Low | 40 pts |
|  | Rejected with a 4xx, while the baseline accepts it. | Fail · Medium | 15 pts |
|  | Rejected, but the model itself does not support it; not counted. | Info | Not counted |
|  | Server error or no response; not counted. | Inconclusive · Low | Not counted |

### `determinism` — Determinism & cache-correctness

**How it works.** Four identical creative prompts at `temperature=1.0` (no
seed): a genuine model varies, byte-identical output across all samples points
to a response cache that ignores sampling. The verdict is suppressed for
reasoning models, which legitimately ignore temperature. Two identical factual
prompts at `temperature=0` are informational only.

| Check | Outcome | Status | Effect |
|---|---|---|---|
| `determinism.temp1_variability` | Repeated samples at temperature=1.0 differed, as genuine sampling does. | Pass | 100 pts |
|  | Samples were identical, but reasoning models legitimately ignore temperature. | Info | 100 pts |
|  | All samples at temperature=1.0 were byte-identical, suggesting response caching. | Warning · Medium | 55 pts |
|  | No usable response to judge by. | Inconclusive · Low | Not counted |
| `determinism.temp0_stability` | Identical answers at temperature=0 (expected); informational, not scored. | Info | Not counted |
|  | Answers differed at temperature=0; informational, not scored. | Info | Not counted |
|  | No usable response to judge by. | Inconclusive · Low | Not counted |

**Caveats.** Gateways may add provider-specific extra fields; only missing or
invalid required fields are flagged. Anthropic↔OpenAI dialect translation
legitimately reshapes some structures. Confirm a suspected defect by repeating
it and, where possible, in compare mode.

---

## `context_window` — Context window

**Catches.** `context.window-truncation` (a relay advertises 128K/200K/1M but
silently trims the prompt) and `context.lost-in-middle-rag` (a cheap
RAG/summarization shim forwards only parts of the prompt).

**How it works.** Needle-in-a-haystack recall at `temperature=0`: a unique
marker is embedded in non-repetitive filler sized with zing's heuristic token
estimate, and the model must return it.

1. An ascending doubling ladder from 2K tokens up to the declared window, capped
   by `--max-context-tokens` (default 200K), with a rung near 90% of the top
   (at most seven sizes). Each size is probed with the needle at the **start**
   edge (depth 0.0) first: a truncation that keeps the question at the end of
   the prompt can only drop its start (a local server cutting the prompt to its
   context length keeps the end), so a recall there passes the size in one
   call. A miss is confirmed at the end edge (depth 0.95); if the end is
   recalled, the start is probed once more with a fresh needle, and a second
   miss fails the size as **front truncation** (named in the verdict's
   evidence). At most three calls per size; the ladder stops at the first
   confirmed failure.
2. One binary-search step between the last recalled and the first failing size.
3. Lost-in-the-middle: at min(32K, measured window) the needle is placed at
   depths 0.1, 0.5 and 0.9; start and end recalled but not the middle is a
   finding.
4. A 4xx whose message names the context length is a size rejection; a
   rejection of `max_tokens` (reasoning models) is retried with
   `max_completion_tokens` and never read as a ceiling.
5. A timed-out probe ends the ladder without counting as a failure: the window
   above the last recalled size is reported as unverified (inconclusive), never
   as truncation.

The measured window is compared with the declared one. Without a declared
window the measurement is reported but not scored.

| Check | Outcome | Status | Effect |
|---|---|---|---|
| `context_window.window` (Effective context window) | Recall held up to at least 90% of the declared window; deducts the share of the declared window that did not recall. | Pass | up to −10 pts |
|  | Recall held up to 50-90% of the declared window; deducts the share of the declared window that did not recall. | Warning · Medium | up to −50 pts |
|  | Recall failed below half of the declared window; deducts the share of the declared window that did not recall. | Fail · High | up to −100 pts |
|  | Not even the smallest probe size recalled the needle. | Fail · High | −100 pts |
| `context_window.lost_in_middle` | The start and end were recalled but the middle was not. | Warning · Medium | −15 pts |
| `context_window.rejected_below_claim` | A prompt well below the declared window was rejected as too long. | Fail · High | No deduction |
| `context_window.measured` | No declared window to compare against: measured only, not scored. | Info | No deduction |
| `context_window.no_ladder` | No probe size fit between the floor and the cap. | Inconclusive · Low | No deduction |
| `context_window.timed_out` | A probe timed out before the declared window was reached: a slow endpoint, not evidence of truncation. | Inconclusive · Low | No deduction |

**Caveats.** Genuine long-context models also lose needles in the middle, so
only an **edge** failure is read as truncation. Recall near the ceiling is
probabilistic; re-run before concluding. The probe is bounded by
`--max-context-tokens`, so a larger window is not exercised in full. Compare
with a trusted baseline to separate model behavior from shim behavior.

---

## `model_identity` — Model identity

**Catches.** `downgrade.silent-substitution` (a premium name on a cheaper or
open backend), and signals of `downgrade.reasoning-collapse`,
`downgrade.quantized-distilled` and `downgrade.partial-probabilistic-routing`
when they change behavior.

### `model_identity` — Model identity & downgrade fingerprinting

**How it works.** Three independent signals:

1. **Self-identification** at `temperature=0`, matched whole-word against the
   profile's identity keywords (the genuine brand) and a list of rival brands
   (the profile's `identity_forbidden` plus a built-in list). A rival brand
   only counts when the genuine brand is absent; "I am Claude, not GPT" is a
   benign contrast.
   The genuine brand is the profile's `identity_keywords` plus the profile's
   own names: the provider key, the leading name of the provider's display
   name, the leading word of the model id and family, and that vendor's other
   names in the built-in list (`z.ai` also covers `zhipu`). A model naming its
   own vendor is therefore never a rival brand, even when `identity_keywords`
   is empty. Derived names never override `identity_forbidden`, generic words
   ("ai", "platform", …) never count, and a platform's own brand does not count
   for another vendor's model it serves.
   Brand words that are also everyday words (`step`, `command`, `seed`,
   `spark`, `meta`, `yi`, `grok`) count only in this self-identification
   answer and only written as a name ("made by Meta", "Command R", "grok-2";
   at the start of a sentence or list item only with a version attached,
   "Step-2"); fingerprint answers never
   count them, so "let me think step by step" is not a rival brand. A vendor
   that owns such a word keeps it as its own.
2. **Behavioral fingerprints** from the knowledge base (knowledge cutoff,
   tokenizer quirks, formatting, language-bound probes, …): up to six
   pure-code probes, each checked with `expect_contains`, `expect_contains_any`,
   `expect_not_contains` or `expect_regex`; output capped at 512 tokens. A
   probe that needs more output (such as a max-output check) is skipped,
   listed as Info, and another probe takes its slot. A
   diverging fingerprint deducts its weight share of 100 points (at most 25);
   one alone stays LOW, two or more add a MEDIUM aggregate.
3. **Echoed `model` field** of a plain call: snapshot suffixes and aliases are
   tolerated; a smaller-tier word (`mini`, `flash`, `lite`, `8b`, …) or a
   different family is flagged.

Without a knowledge-base profile the detector is inconclusive.
It is also inconclusive and unscored (`model_identity.no_evidence`) when
neither the self-identification nor any fingerprint returned a usable
answer and the echoed `model` field does not diverge: a relay that rejects
or empties every request gives no identity evidence, and an echo of the
requested name proves nothing on its own. Partial evidence scores normally.

| Check | Outcome | Status | Effect |
|---|---|---|---|
| `model_identity.self_id` | The self-description named the genuine brand. | Pass | No deduction |
|  | The self-description named a rival brand and not the genuine one. | Fail · High | cap 20 |
|  | The self-description named the genuine brand and a rival (usually a benign contrast). | Warning · Low | No deduction |
|  | The self-description named neither the genuine brand nor a rival. | Warning · Low | No deduction |
|  | No usable response to judge by. | Inconclusive | No deduction |
| `model_identity.fp` (Behavioral fingerprints) | The answer matched the claimed model's native behavior. | Pass | No deduction |
|  | The answer diverged from native behavior: deducts the probe's weight share of 100 points. | Warning · Low | up to −25 pts |
|  | The answer named a rival brand and not the genuine one: deducts the probe's weight share. | Fail · High | up to −25 pts · cap 20 |
|  | No usable response to judge by. | Inconclusive | No deduction |
|  | The probe needs more output than the 512-token identity cap; not run. | Info | No deduction |
| `model_identity.fp_aggregate` | Two or more behavioral fingerprints diverged. | Warning · Medium | No deduction |
| `model_identity.model_field` | The echoed model field matched the requested model. | Pass | No deduction |
|  | The echoed model field names a different or smaller model. | Warning · Medium | No deduction |
|  | The response had no usable model field. | Inconclusive | No deduction |
| `model_identity.no_evidence` | No self-identification or fingerprint answer was usable and the model field did not diverge: not scored. | Inconclusive | No deduction |

### `quality_judge` — LLM-judged quality / downgrade assessment

**How it works.** Only with `--judge` (deep and up). A short battery of
tier-discriminating prompts (multi-step reasoning, a precise coding task,
nuanced instruction-following) goes to the target and, in compare mode, to the
baseline; a separate trusted judge sees only the answers and returns a verdict
and a confidence. The judge is told the claimed model (`claimed_model` when set, else the
requested id). A judge verdict is HIGH only when the judge stated **high**
confidence and a usable baseline corroborated the difference — one that
returned a non-empty answer for every probe the target answered. A low,
medium, missing or unrecognized confidence stays MEDIUM, and so does a
baseline that errored or left probes unanswered.

| Check | Outcome | Status | Effect |
|---|---|---|---|
| `quality_judge.verdict` (LLM judge verdict) | The judge found the answers consistent with the claimed model. | Pass | 95 pts |
|  | The judge found the answers unlike the claimed model (low, medium or no stated confidence). | Warning · Medium | 50 pts |
|  | The judge is confident the answers are unlike the claimed model (no usable baseline). | Warning · Medium | 25 pts |
|  | The judge is confident, and a trusted baseline corroborated the difference. | Fail · High | 25 pts |
|  | The judge could not commit to a verdict. | Inconclusive · Low | Not counted |
|  | No target answers to judge. | Inconclusive · Low | Not counted |

**Caveats.** Official APIs update snapshots silently, so divergence can be
benign drift; zing reports "divergent", never "proven substitution". Models
hallucinate their own names, so self-identification alone never decides. A relay
could memorize a fixed probe battery. A high-confidence verdict requires compare
mode against the exact claimed snapshot.

**Not implemented.** Embedding-distance fingerprinting (LLMmap-style),
distributional two-sample tests, and high-volume sampling for probabilistic
routing are research directions, not current checks.

---

## `capability` — Capability claims

**Catches.** `capability.json-tool-fakery`: tool calling, JSON mode, strict
schemas, output length or vision claimed but not delivered — or *over*-delivered,
hinting at a substitute.

### `capability` — Capability-claim verification

**How it works.** Four probes at `temperature=0`, each judged against the
profile's capability flags:

- **Tools:** one tool offered with `tool_choice: "auto"` and an explicit request
  to use it; a tool call must come back. Arguments delivered as an object rather
  than the JSON string OpenAI returns are flagged as a non-OpenAI engine.
- **JSON mode:** `response_format: json_object` must return a parseable object
  carrying the requested value.
- **Strict schema:** a strict `json_schema`; conformance is verified when the
  model claims it and noted (informational) when it does not. Skipped without a
  profile.
- **Max output:** a long generation capped at min(declared max output, 2048)
  tokens; reaching the cap or a plausible length passes, stopping below a
  quarter of it is flagged.

An observation without a claim to verify — no tool call or JSON object when the
feature is not claimed, or any strict-schema result when the profile says the
model lacks strict schemas — is noted but not counted, so a model is never
marked down for what nobody claimed.

| Check | Outcome | Status | Effect |
|---|---|---|---|
| `capability.tools` | A tool call came back for an explicit tool-use request. | Pass | 100 pts |
|  | Tool calling is claimed but no tool call came back. | Fail · Medium | 0 pts |
|  | No tool call came back, and tool calling is not claimed. | Info | Not counted |
|  | No usable response to judge by. | Inconclusive · Low | Not counted |
| `capability.tools.encoding` | Tool arguments arrived as an object, not the JSON string OpenAI returns. | Warning · Low | Not counted |
| `capability.json_mode` | JSON mode returned a parseable object with the requested value. | Pass | 100 pts |
|  | A JSON object came back with the wrong value; JSON mode is not claimed. | Info | Not counted |
|  | No parseable JSON object came back; JSON mode is not claimed. | Info | Not counted |
|  | JSON mode is claimed but no valid object with the value came back. | Fail · Medium | 0 pts |
|  | No usable response to judge by. | Inconclusive · Low | Not counted |
| `capability.json_schema` | The strict schema is claimed and the response conformed. | Pass | 100 pts |
|  | The strict schema was not enforced, consistent with the claim. | Info | Not counted |
|  | The response conformed although the claimed model lacks strict schemas. | Info | Not counted |
|  | The strict schema is claimed but the response did not conform. | Warning · Low | 40 pts |
|  | No usable response to judge by. | Inconclusive · Low | Not counted |
| `capability.max_output` | Output continued up to the requested token cap. | Pass | 100 pts |
|  | Output stopped before the cap at a plausible length. | Pass | 90 pts |
|  | Output stopped below a quarter of the requested length. | Warning · Low | 70 pts |
|  | Output stopped below a quarter of the request despite a large claimed maximum. | Warning · Low | 60 pts |
|  | No usable response to judge by. | Inconclusive · Low | Not counted |

### `vision` — Multimodal (vision) capability verification

**How it works.** Deep and up, and only when the profile claims vision: a small
solid-orange PNG generated at run time is sent inline with a one-word color
question. A text-only substitute cannot name the color reliably.

| Check | Outcome | Status | Effect |
|---|---|---|---|
| `vision.color` | The model named the color of the test image. | Pass | 100 pts |
|  | Vision is claimed but the model did not name the image's color. | Warning · Medium | 0 pts |
|  | No usable response to judge by. | Inconclusive | Not counted |
| `vision.not_claimed` | Vision is not claimed, so no image was sent. | Info | Not counted |

**Caveats.** Genuine models occasionally skip a tool or emit invalid JSON; one
probe per capability is a signal, not a rate. Dialect translation legitimately
reshapes tool-call JSON. The max-output probe does not exercise the full declared
ceiling. One image is suggestive, not proof.

---

## `streaming` — Streaming authenticity

**Catches.** `stream.fake-streaming`: the relay buffers the whole upstream
answer and replays it as one or a few chunks, losing the latency benefit.

**How it works.** One streamed request (`max_tokens` 256,
`stream_options.include_usage`) with chunk arrival times recorded. Three
buffering signals: **few chunks** (two or fewer) and **late first token** (TTFT
above 90% of the total duration), both judged only once at least 220 characters
came back, and **uniform gaps** (four or more chunks whose gaps are almost
equal, CV < 0.1, and under 2 ms: dumped together). A stream without a usage
chunk is flagged separately.

| Check | Outcome | Status | Effect |
|---|---|---|---|
| `streaming.healthy` | Many chunks, an early first token and spread-out gaps: genuine streaming. | Pass | No deduction |
| `streaming.few_chunks` | Buffering signal: the first deducts 40 points, a second 20, any further one nothing. | Warning · Medium | up to −40 pts |
| `streaming.late_ttft` | Buffering signal: the first deducts 40 points, a second 20, any further one nothing. | Warning · Medium | up to −40 pts |
| `streaming.uniform_gaps` | Buffering signal: the first deducts 40 points, a second 20, any further one nothing. | Warning · Medium | up to −40 pts |
| `streaming.no_usage` | No usage chunk in the stream: deducts 15 points when nothing is buffered. | Warning · Low | up to −15 pts |
| `streaming.failed` | The streaming request failed. | Fail · High | cap 0 |

So: genuine 100 · usage missing 85 · one buffering signal 60 · two or more 40 ·
failed 0.

**Caveats.** Short outputs, a fast small model or network jitter can resemble a
burst. An upstream that cannot stream forces the relay to buffer legitimately;
read it as "the relay does not stream", not as malice. Re-run and compare with a
known-streaming baseline.

---

## `billing` — Billing & usage

**Catches.** `billing.usage-inflation` (over-reported prompt or completion
tokens), `billing.missing-usage` (no, partial or inconsistent `usage`) and, as
a corroborating signal, `prompt.injected-system-prompt`.

**How it works.** One deterministic call (a known paragraph to summarize,
`temperature=0`). The prompt and the visible answer are counted independently
with a language-aware heuristic (about ±25%), for every model family: zing uses
no tokenizer library and downloads none. Reported prompt tokens above 2.5× the
estimate and more than 50 tokens over it count as inflation. Completion tokens
of a reasoning model legitimately include hidden reasoning tokens and are not
flagged; otherwise completion tokens above 3× the estimate and more than 80
tokens over it are a soft warning, never a failure, because the estimate of a
short answer is noisy. `total` must equal `prompt + completion` (±2), and a
total without the split is flagged. An undercount (below half the estimate) is
informational (not buyer-harmful).

| Check | Outcome | Status | Effect |
|---|---|---|---|
| `billing.request-failed` | No usable response to judge by. | Inconclusive · Low | No deduction |
| `billing.missing-usage` | The response carried no token usage at all. | Warning · Medium | cap 75 |
| `billing.usage-inflation` | Reported prompt tokens far exceed the independent estimate. | Fail · High | cap 55 |
| `billing.usage-inflation-completion` | Reported completion tokens are far above a heuristic estimate. | Warning · Medium | cap 70 |
| `billing.reasoning-tokens` | Completion tokens exceed the visible text, as expected for a reasoning model. | Info | No deduction |
| `billing.usage-undercount-prompt` | Reported prompt tokens are well below the estimate (not buyer-harmful). | Info | No deduction |
| `billing.usage-undercount-completion` | Reported completion tokens are well below the estimate (not buyer-harmful). | Info | No deduction |
| `billing.total-mismatch` | The reported total does not equal prompt + completion tokens. | Warning · Low | cap 90 |
| `billing.partial-usage` | Usage reports a total without the prompt/completion split. | Warning · Medium | cap 80 |
| `billing.usage-consistent` | Reported usage is within tolerance of the independent estimate. | Pass | No deduction |

A failed probe request leaves the detector unscored.

**Caveats.** Chat templates and special tokens add a small fixed offset, so an
exact match is not expected. If the served model differs from the claimed one,
the "right" tokenizer is unknown. Hidden reasoning tokens cannot be counted
from outside. One probe measures one size; a size-scaling multiplier needs
repeated runs or compare mode.

---

## `reliability` — Concurrency reliability

**Catches.** Parts of `throttle.rate-limit-quality`: a relay that fails or
crawls under modest parallelism.

**How it works.** A burst of identical tiny requests (`--reliability-requests`,
default 8) at bounded concurrency (`--concurrency`, default 3). The success rate
is computed over the requests genuinely attempted: HTTP 429 is honest
throttling and is bucketed separately. The score deducts the failed share; a p95
latency above 30 s keeps 85% of what is left.

| Check | Outcome | Status | Effect |
|---|---|---|---|
| `reliability.success_rate` | Every attempted request in the burst succeeded. | Pass | No deduction |
|  | Up to 10% of the attempted requests failed; deducts the failed share. | Warning · Low | up to −10 pts |
|  | More than 10% of the attempted requests failed; deducts the failed share. | Fail · Medium | up to −100 pts |
|  | Every request was rate-limited (HTTP 429): not scored. | Inconclusive · Low | No deduction |
| `reliability.latency` | p95 latency above 30 s under load; deducts 15% of the remaining score. | Warning · Low | up to −15 pts |
| `reliability.rate_limited` | Part of the burst was rate-limited: honest throttling, not counted. | Info | No deduction |
| `reliability.skipped` | The reliability probe was disabled. | Info | No deduction |

The dedicated speed measurements belong to the `performance` dimension.

**Caveats.** Genuine providers also slow down and return 429 under real load.
One snapshot misses time-of-day behavior; `zing watch` re-audits on a schedule.

**Not implemented.** Longitudinal and load-conditioned quality probing and the
shared-upstream-key signals (`infra.shared-upstream-key`: quota decreasing while
idle, leaked upstream request ids) are on the roadmap.

---

## `security` — Transport security

**Catches.** `prompt.injected-system-prompt`, `integrity.response-tampering`,
evidence toward `privacy.prompt-logging-leakage` (prefix caching), and basic
transport and secret hygiene.

### `security` — Transport & secret-handling signals

**How it works.** Checks that the endpoint uses HTTPS, that the API key never
appears verbatim in a response, and which response headers reveal an upstream or
proxy (`server`, `via`, `x-powered-by`, `x-upstream-*`, `x-litellm-*`, …;
informational). It also states the limit: prompt logging and shared upstream
keys are not provable from outside.

| Check | Outcome | Status | Effect |
|---|---|---|---|
| `security.tls` | The endpoint uses HTTPS. | Pass | No deduction |
|  | The endpoint is not HTTPS; the API key travels in clear text. | Fail · High | cap 40 |
| `security.key_echo` | The API key does not appear in the response. | Pass | No deduction |
|  | The API key appears verbatim in the response. | Fail · High | cap 30 |
| `security.headers` | No response header reveals the upstream (informational). | Pass | No deduction |
|  | Response headers reveal the upstream or proxy (informational). | Info · Low | No deduction |
|  | No response headers to inspect. | Inconclusive | No deduction |
| `security.note` | Prompt logging and shared upstream keys are not provable from outside. | Info | No deduction |

### `injected_prompt` — Injected system-prompt detection

**How it works.** Two independent tells. (1) A **fixed input-token overhead**:
two user messages of different sizes without a system message; reported
`prompt_tokens` minus the independent estimate must stay small. An overhead of
at least 30 tokens that stays constant (within 16) across both sizes reads as a
hidden prepended prompt rather than proportional inflation. (2) A **leak
probe** asking the model to repeat any preceding instructions. Only both
together reach MEDIUM.

| Check | Outcome | Status | Effect |
|---|---|---|---|
| `injected_prompt.verdict` (Injected system prompt) | Input-token overhead is small and no hidden instructions leaked. | Pass | 100 pts |
|  | Instruction-like text leaked when asked (weak on its own). | Info · Low | 85 pts |
|  | A large fixed input-token overhead, constant across message sizes. | Warning · Low | 75 pts |
|  | A fixed input-token overhead and a leaked preamble together. | Warning · Medium | 55 pts |
|  | No usable prompt token counts to measure the overhead. | Inconclusive | Not counted |

### `integrity` — Response integrity / tampering

**How it works.** Known-answer canaries whose values are sensitive — an install
URL and a pinned `pip install` package — must come back verbatim. An exact echo
passes, a non-echo (paraphrase, refusal) is inconclusive, and only a
structure-preserving **value substitution** counts as tampering. In compare mode
a substitution the trusted baseline does not make is CRITICAL.
Only a baseline that returns the canary intact corroborates: a baseline that
errors or returns nothing usable confirms nothing, so the substitution stays
MEDIUM (evidence `baseline_unavailable`).
An answer cut off at the output limit is inconclusive, not a substitution.

| Check | Outcome | Status | Effect |
|---|---|---|---|
| `integrity.verdict` (Response integrity) | Known-answer canaries came back intact. | Pass | 100 pts |
|  | A canary value was substituted (not yet confirmed by a baseline). | Fail · Medium | 45 pts |
|  | A canary value was substituted while the trusted baseline kept it intact. | Fail · Critical | 10 pts |
|  | No canary was echoed verbatim, so tampering could not be assessed. | Inconclusive | Not counted |

### `prompt_cache` — Prompt prefix-cache (timing)

**How it works.** A unique ~1,200-token prefix is streamed twice (cold, then
warm) and a different control prefix once. When the warm TTFT is below half of
both the cold and the control TTFT, and at least 150 ms faster than cold,
prefix caching is active. Always informational: prefix caching is a legitimate
optimization.

| Check | Outcome | Status | Effect |
|---|---|---|---|
| `prompt_cache.verdict` (Prompt-prefix caching) | A repeated prompt prefix came back much faster: prefix caching is active. | Info | Not counted |
|  | A repeated prompt prefix was not distinctly faster. | Info | Not counted |
|  | One or more timing probes returned no usable timing. | Inconclusive | Not counted |

**Caveats.** Models invent fake "system prompts" when asked to leak, so a leak
alone stays LOW. Dialect translation reshapes tool-call JSON; only a *value*
substitution counts. Conditional tampering (only for some keywords, clients or
after a warm-up) can evade a finite set of probes. Black-box logging is
**unprovable** from the client, and zing cannot show *cross-user* cache sharing
from one key: the absence of a timing signal does not prove prompts are not
logged.

---

## `performance` — Performance

**What it measures.** How **consistent** the endpoint is, not how fast. A local
or self-hosted model that is slow but steady scores well; raw speed only counts
against a reference.

**How it works.** The dedicated probe runs on deep, full and custom, and on
standard only in compare mode (5 requests per side, too few for the consistency
checks). Per endpoint: three `GET /models` pings, one warm-up request (reported
as cold start), `--performance-requests` uniform requests (default 100) of
`--performance-max-tokens` output tokens (default 128), then on deep/full a burst
at `--concurrency`. Every request is uncacheable: a random request id opens the
prompt, topics rotate, no cache or reasoning parameters are sent; a response
that still comes back cached is flagged and left out of the statistics. The
probe streams by default (`--performance-non-streaming` for relays that cannot
stream); full measures both modes, interleaved. In compare mode target and
baseline alternate so network drift hits both equally.
Cached input tokens only count when they cover at least half the prompt: local
servers (Ollama, llama.cpp, LM Studio) reuse the cached chat template of every
prompt, which is not a stored answer.
Every call of the audit is kept as a request record (`performance.requests`,
numbers only, never prompt or response text); its `start_ms` counts from the
report's `started_at` (UTC), so each call's time can be reconstructed.

Consistency uses tail ratios (p90 ÷ p50 for latency and TTFT, p50 ÷ p10 for
throughput), which one stray request cannot move the way it moves a standard
deviation; they need at least 10 clean samples. The reference is the trusted
baseline, or else the knowledge-base profile's `performance.decode_tps` range.

| Check | Outcome | Status | Effect |
|---|---|---|---|
| `performance.summary` | Latency, TTFT and throughput were measured. | Info | Not counted |
|  | None of the probe requests succeeded. | Inconclusive | Not counted |
| `performance.latency_consistency` | Latency is steady (tail ratio at most 1.3). | Pass | 100 pts |
|  | Latency is stable (tail ratio at most 1.75). | Pass | 85 pts |
|  | Latency varies noticeably (tail ratio at most 2.5). | Warning · Low | 65 pts |
|  | Latency is erratic (tail ratio above 2.5). | Fail · Low | 40 pts |
|  | Too few samples to judge how consistent latency is. | Info | Not counted |
| `performance.ttft_consistency` | Time to first token is steady (tail ratio at most 1.3). | Pass | 100 pts |
|  | Time to first token is stable (tail ratio at most 1.75). | Pass | 85 pts |
|  | Time to first token varies noticeably (tail ratio at most 2.5). | Warning · Low | 65 pts |
|  | Time to first token is erratic (tail ratio above 2.5). | Fail · Low | 40 pts |
|  | Too few samples to judge how consistent time to first token is. | Info | Not counted |
| `performance.throughput_consistency` | Throughput is steady (tail ratio at most 1.3). | Pass | 100 pts |
|  | Throughput is stable (tail ratio at most 1.75). | Pass | 85 pts |
|  | Throughput varies noticeably (tail ratio at most 2.5). | Warning · Low | 65 pts |
|  | Throughput is erratic (tail ratio above 2.5). | Fail · Low | 40 pts |
|  | Too few samples to judge how consistent throughput is. | Info | Not counted |
| `performance.errors` | At most 2% of the probe requests failed. | Pass | 100 pts |
|  | Up to 10% of the probe requests failed or timed out. | Warning · Low | 80 pts |
|  | Many probe requests failed or timed out. | Fail · Low | 50 pts |
| `performance.load_stability` | Latency holds up under concurrent load (at most 1.5x). | Pass | 100 pts |
|  | Latency rises under concurrent load (up to 3x). | Warning · Low | 80 pts |
|  | Latency degrades sharply under concurrent load (above 3x). | Fail · Low | 55 pts |
| `performance.cache_hit` | Unique probe prompts came back from a cache (left out of the statistics). | Warning · Low | 60 pts |
|  | The baseline served unique probe prompts from a cache (not scored). | Info | Not counted |
| `performance.reference` | Throughput is in line with the reference for this model. | Pass | 100 pts |
|  | Slower than the reference (e.g. local or smaller hardware); not a failure. | Info | Not counted |
|  | Much faster than the reference (consistent with a smaller model). | Warning · Low | 60 pts |
| `performance.reasoning` | The model spends hidden reasoning tokens; TTFT includes thinking. | Info | Not counted |
| `performance.relay_overhead` | Latency compared with the trusted baseline (informational). | Info | Not counted |
| `performance.skipped` | The performance probe was disabled. | Info | Not counted |

**Caveats.** Latency depends on the network path and the provider's load at
that moment; repeat a poor consistency result at another time. The
knowledge-base ranges are deliberately wide medians of native APIs, and a
slower target is noted, never scored. All findings are at most LOW severity, so
this dimension moves the score, never the risk verdict.

---

## Trick → detector mapping

The 16 relay tricks from the research map onto zing as follows.

| # | Trick (id) | Severity | Detector(s) | Current coverage |
|---|---|---|---|---|
| 1 | `downgrade.silent-substitution` | critical | `model_identity`, `quality_judge` | self-identification, fingerprints, `model` field; judge; compare mode |
| 2 | `downgrade.reasoning-collapse` | critical | `model_identity`, `quality_judge` | fingerprints and judge only; no dedicated difficulty ladder yet |
| 3 | `downgrade.quantized-distilled` | high | `quality_judge`, `model_identity` | judge with a baseline; no distribution test yet |
| 4 | `downgrade.partial-probabilistic-routing` | high | `model_identity` | only if the sampled requests hit the substitute; high-volume sampling is roadmap |
| 5 | `context.window-truncation` | high | `context_window` | edge-needle ladder + binary search; measured vs declared |
| 6 | `context.lost-in-middle-rag` | high | `context_window` | depths 0.1/0.5/0.9 at a mid size |
| 7 | `stream.fake-streaming` | medium | `streaming` | chunk count, first-token timing, gap uniformity |
| 8 | `billing.usage-inflation` | high | `billing` | independent heuristic token estimate of one known probe |
| 9 | `billing.missing-usage` | medium | `billing`, `protocol_response`, `streaming` | usage presence, split and arithmetic; stream usage chunk |
| 10 | `privacy.prompt-logging-leakage` | high | `prompt_cache` | prefix caching by TTFT (informational); cross-user sharing and logging stay unprovable from one key |
| 11 | `infra.shared-upstream-key` | high | — | roadmap (quota decreasing while idle, leaked upstream request ids) |
| 12 | `cache.ignore-temperature` | medium | `determinism` | byte-identical output at temperature 1.0; suppressed for reasoning models |
| 13 | `prompt.injected-system-prompt` | medium | `injected_prompt`, `billing` | fixed input-token overhead (two sizes) + leak probe |
| 14 | `throttle.rate-limit-quality` | medium | `reliability`, `performance` | success rate (429 separate), tail latency, load stability; longitudinal probing is roadmap |
| 15 | `capability.json-tool-fakery` | medium | `capability`, `protocol_request` | tools, JSON mode, strict schema, parameters; one probe each, not rates |
| 16 | `integrity.response-tampering` | critical | `integrity` | known-answer URL/package canaries; CRITICAL when a baseline corroborates |

---

## Limitations & responsible use

**zing reports divergence and risk, not proof of fraud.** The verdict uses
cautious language (clean / low / medium / high / inconclusive), keeps ambiguous
results inconclusive, and escalates to high only on hard, high-severity
evidence.

**What black-box auditing cannot prove:**

- **Prompt logging or data retention.** A timing signal is evidence of caching;
  its absence does not prove prompts are not logged.
- **Response integrity** without provider-signed responses: conditional
  tampering can evade finite probing.
- **Shared keys or key theft:** at most a shared-pool *risk*.
- **Benign drift versus substitution:** official APIs update snapshots silently.
- **Constant routing:** a relay can route probabilistically, and one audit sees
  only the requests it sent.

**Method.** Findings that depend on exact comparison use `temperature=0` and
constrained prompts. Each finding carries its evidence (inputs, observed values,
counts, timings), and every report records the profile, prompt languages and
settings it ran with, so a result can be checked independently. A relay may be
test-aware: re-run at other times, and prefer compare mode against a trusted
baseline of the **exact claimed snapshot** — it is the strongest way to separate
model behavior from relay behavior and the only way to reach high confidence.

**Responsible disclosure.** Do **not** publicly accuse a vendor on the basis of
a zing report. Before acting, re-run with more samples and at other times,
confirm with compare mode, and rule out drift, network and load explanations.
If a serious concern remains, raise it privately with the vendor first, as
questions about observed behavior rather than allegations.
