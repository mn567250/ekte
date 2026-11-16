# Review of the audit dimensions, detectors and scoring

A critical review of what ekte checks, how each check decides, and how the
results become a score and a verdict. It covers the chat surface in depth
(all 18 detectors, `ekte/scoring.py`, the scale machinery) and the
documentation that describes them. The embedding and rerank detectors were
read for their scales and thresholds only; the image and audio audits
(`ekte/media_audit.py`) were not reviewed.

Every finding marked **verified** was reproduced by running the code at commit
`5bdfa79`: either the scoring functions on synthetic detector results, or the
real detector against a stubbed relay. Findings marked **by reading** follow
from the code but were not executed.

## Verdict

The engineering around the checks is strong: published scales, evidence on
every finding, careful false-positive handling, and documentation that matches
the code almost row for row. The weakness is in what the checks can actually
prove, and in how the score treats what they could not prove:

1. **The score and the risk verdict contradict each other.** A relay with a
   CRITICAL tampering finding scores 98.2 (A). The score cannot be used as a
   gate.
2. **A check that fails to get an answer disappears from the score.** A relay
   that rejects tool calls and JSON mode with HTTP 400 scores 100 on
   capability claims.
3. **Model identity verifies the vendor, not the model.** For most profiles the
   only "behavioral fingerprint" is a second self-identification question. A
   same-vendor downgrade (`gpt-4o` served by `gpt-4o-mini`), the most common
   trick, is not detected without the LLM judge.
4. **Billing inflation below 2.5x passes as "consistent".**

The four questions asked, in short:

| Question | Answer |
|---|---|
| Is the scope of dimensions and detectors correctly defined? | Mostly. Three dimensions hold detectors that do not belong under their name (P2-1). |
| Is the audit logic correctly implemented? | The code does what its scales say. Several checks decide wrongly in common cases (P0-2, P0-3, P1-1, P1-6, P1-7). |
| Do they give a full picture? | No. Same-vendor downgrade, moderate overbilling, clamped output and targeted tampering are outside what the probes can see (P0-3, P0-4, P1-1, P1-2). |
| Is the scoring fair and logically correct? | The risk ladder is sound and conservative. The 0-100 score is not: it disagrees with the risk and rewards unanswered checks (P0-1, P0-2). |

## What is already good

- **Published scales.** Every outcome of every check is declared up front with
  status, severity and points, findings are built from that table, and tests
  pin the invariant. Report and behavior cannot drift apart.
- **Risk is driven by finding severity, not by the score.** HIGH needs hard
  evidence; one soft signal never escalates.
- **Connectivity and transport advisories stay off the substitution ladder.**
  A relay that is down, throttled or reached over `http://localhost` is not
  read as "serves a different model".
- **Failures on ekte's side are separated from the relay's.**
  `detectors/impaired.py` turns a finding inconclusive when every request it
  rests on failed locally or on the network path.
- **False-positive handling is careful and specific:** a rival brand counts
  only when the genuine one is absent; ambiguous brand words ("step", "meta")
  count only written as a name; a context miss is confirmed at the other edge
  and with a fresh needle; HTTP 429 is kept out of the failure rate; reasoning
  models are excused where thinking explains the observation.
- **The context-window probe is well designed:** real-token budgets, start-edge
  first (catches front truncation), verified-to-cap instead of a false pass,
  errors and timeouts never read as truncation.
- **The performance dimension scores consistency, not speed,** with tail
  ratios and uncacheable prompts, so a slow local model is not marked down.
- **Limits are stated honestly:** "evidence of divergence, not proof of
  fraud", a "Not implemented" list per dimension, and a trick-to-detector map
  that admits partial coverage.
- **Docs match code.** All chat-surface scale rows (about 230) in
  `docs/guide/methodology.md` agree with the code in label, status, severity
  and effect, bar one cell (see [Documentation](#documentation-versus-code)).

## Findings

Priorities: **P0** produces a wrong or misleading result in a common case;
**P1** is a real gap or wrong decision in a narrower case; **P2** is a
definition or consistency problem.

### P0-1 The score contradicts the risk verdict (verified)

The overall score is a weighted mean in which one failed dimension is diluted
twice: first by the equal-weight mean of its detectors, then by its weight.

| Scenario (everything else clean) | Score | Rating | Risk |
|---|---|---|---|
| Corroborated response tampering (CRITICAL) | 98.2 | A | high |
| Prompt tokens inflated above 2.5x | 96.4 | A | high |
| API key echoed in the response | 98.6 | A | medium |
| Self-identifies as a rival vendor | 83.2 | B | high |
| 200K window truncated to about 20K | 83.1 | B | high |

A reader sees "A, 98/100" next to "Likely substituted". `--fail-under 80`
passes every row of this table, so a CI gate on the score lets through exactly
the relays ekte exists to catch.

**Change:** cap the overall score by the risk level (for example high ≤ 49,
medium ≤ 69), or make the rating a function of both. Inside a dimension, let a
HIGH or CRITICAL finding cap the dimension score instead of averaging it with
clean sibling detectors (tampering at 10 points currently yields a "Transport
security" score of 70).

### P0-2 An unanswered check drops out and raises the score (verified)

Inconclusive outcomes are "not counted", and a dimension without a score
leaves the weighted mean. That is right for failures on ekte's side, which
`impaired.py` already handles. It is wrong when the relay itself refuses or
fails, because not delivering is the thing being audited.

- **Capability:** a relay answers the tools, JSON-mode and strict-schema probes
  with HTTP 400. All three are "No usable response", not counted
  (`capability.py:117`, `:215`, `:299`). The detector scores **100, Pass**, on
  the max-output check alone. A relay that rejects `tools` for a model that
  claims them is the plainest form of an undelivered capability, and
  `protocol_request` already scores a rejected parameter at 40 points.
- **Context window:** a relay that times out or returns 5xx on long prompts
  instead of truncating them ends the ladder as inconclusive. The dimension
  (weight 19) drops out: score **100.0, A, risk clean**. A relay that
  truncates honestly scores 83.
- **Whole audit:** with only identity and security answering and every other
  detector erroring, the result is still **100.0, A, clean** (confidence low).

**Change:** treat a relay-side 4xx on a claimed capability as not delivered.
Distinguish "could not be judged because the relay failed" from "not
applicable": the first should count against the dimension, or at least be
shown as a coverage percentage beside the score and cap the rating. A score
computed over a third of the weights should not carry the same letter as one
computed over all of them.

### P0-3 Model identity verifies the vendor, not the model (verified)

The dimension carries the highest weight (21) and is described as three
independent signals. In practice:

- **Fingerprint coverage is thin.** Of 190 chat profiles, 44 have no usable
  fingerprint, 58 have one, and only 9 have a fingerprint specific to the
  model. For `gpt-4o` the single usable fingerprint is another
  self-identification prompt that checks for "openai / gpt / chatgpt".
  `gpt-4o` and `gpt-4o-mini` share the identical fingerprint set. The
  profile's knowledge cutoff is never checked by code.
- So for a same-vendor downgrade, both self-identification answers pass and
  only the echoed `model` field is left, which the relay controls.
- **The `model` field comparison is wrong in both directions**
  (`model_identity.py:618`). It flags a different model only by a fixed list
  of tier words or a different leading token:

  | Requested | Returned | Flagged |
  |---|---|---|
  | `gpt-4o` | `gpt-3.5-turbo` | no |
  | `claude-opus-4-5` | `claude-3-haiku-20240307` | no |
  | `gemini-2.5-pro` | `gemini-2.0-pro` | no |
  | `deepseek-reasoner` | `deepseek-chat` | no |
  | `openai/gpt-4o` | `gpt-4o-2024-08-06` | **yes** (false positive) |
  | `anthropic/claude-sonnet-4-5` | `claude-sonnet-4-5-20250929` | **yes** (false positive) |

  The false positive is a MEDIUM finding in a core dimension, so an honest
  aggregator with provider-prefixed ids gets risk "Deviations found".

**Change:** resolve the returned id through the knowledge base and compare
profiles (same profile or a snapshot of it passes; any other known profile is
a divergence; strip a provider prefix first). Add tier-discriminating probes
that need no judge: the knowledge-cutoff check against the profile, tokenizer
counts where `usage` is trustworthy, and in compare mode run the fingerprints
against the baseline and compare answers. Until then, say plainly in the
verdict that a pass means "the vendor is consistent", not "the model is
verified".

### P0-4 Billing: inflation up to 2.5x is reported as consistent (verified)

One 150-token probe is compared with a heuristic estimate, and prompt tokens
are flagged only above 2.5x **and** 50 tokens over (`billing.py:156`). Usage
multiplied by 1.5, 2.0 and 2.4 all score 100 with "Reported usage is within
tolerance". Realistic overbilling (20 to 100 percent) is invisible, in a core
dimension whose stated purpose is to catch it.

The heuristic's own error is documented as 12 to 15 percent and systematic,
so the tolerance is far wider than the instrument needs. And compare mode,
where the baseline returns the exact token count for the same prompt and
tokenizer, is not used by this detector at all.

**Change:** in compare mode, compare `prompt_tokens` with the baseline's
directly (a few percent tolerance). Without a baseline, probe two or three
prompt sizes and test the slope, which separates proportional inflation from
a fixed overhead; tighten the single-probe threshold to about 1.5x. Detect
reasoning from reported `reasoning_tokens` as `streaming` does, not from the
profile alone.

### P1-1 Max output: reaching `finish_reason: length` always passes (verified)

`capability.py:421` scores 100 whenever the finish reason is `length`,
without checking how much came back. A relay that clamps `max_tokens` to 100
returns ten lines with `length` and passes as "Output continued up to the
requested token cap". The probe also never asks for more than 2,048 tokens,
so a relay capping a 64K-output model at 4K is out of reach.

**Change:** on `length`, require the reported completion tokens (or the
character estimate) to be near the requested cap. Offer an opt-in deeper probe
for the declared ceiling.

### P1-2 Tampering without a baseline ends as risk "low" (verified)

A canary whose value came back substituted with its structure intact is
MEDIUM in a non-core dimension: risk **low**, "Mostly consistent with the
claimed model; minor concerns", score 98.9. A proxy that rewrites an install
URL deserves more than that, and the user without a baseline is the one who
most needs the warning.

Separately (by reading): the two canaries use `downloads.ekte.test` and
`ekte==0.1.0`. Real tampering is targeted at known install URLs, popular
package names or wallet addresses; a proxy doing that never touches these
values. Only non-streamed text is checked, not tool-call arguments or streams.

**Change:** repeat a substituted canary once; two substitutions without a
baseline should be HIGH. Add canaries with realistic targets and one sent as a
tool-call argument and one streamed.

### P1-3 A failed stream request counts as substitution evidence (verified)

`streaming.failed` is HIGH with cap 0 and sits on the substitution ladder. One
503 on the single streaming call gives risk **medium**. Because any two HIGH
findings make the risk high (`scoring.py:361`), a failed stream plus an echoed
key reads "Strong evidence the relay does not deliver what it advertises",
though neither says anything about the model.

**Change:** add `streaming.failed` to `ADVISORY_CHECKS` or lower it to MEDIUM
after one retry. Require the two HIGH findings of the "two or more" rule to be
non-advisory and, ideally, from different detectors about what is served.

### P1-4 Probes are identical on every run (by reading)

Needles and canaries come from `stable_marker(seed)` with fixed seeds
(`helpers.py:24`), and every prompt except the performance probe is constant.
The same needle sits at the same size for every user and every run. A
test-aware relay can answer from a table, and an ordinary response cache makes
a monitor's later runs repeat the first run's answers, which hides a change
the monitor exists to notice. The prompt-cache probe's "cold" request is also
warm from the second run on.

**Change:** mix a per-run random value into every marker, needle and
cache-probe prefix, as the performance probe already does.

### P1-5 Compare mode gives high confidence but little extra evidence (verified, and by reading)

Billing, context window, capability, streaming, determinism and vision do not
use the baseline. Model identity records the baseline's self-identification as
information only. Yet a baseline lifts the confidence to "high" once the core
dimensions produced any usable result. The confidence then describes the
configuration, not the evidence.

Also verified: a judge without a baseline lifts confidence from medium to high
(`scoring.py:389`), which the documentation denies in three places (see
below).

**Change:** make the core detectors compare with the baseline (token counts,
fingerprint answers, capability results, time to first token), and grant high
confidence only when they did.

### P1-6 Injected prompt: the leak test fires on an honest answer (verified)

The leak probe counts as leaked any answer over 60 characters containing
"system", "instruction", "assistant", "must" and similar
(`injected_prompt.py:200`). "There are no system or developer instructions
before this message, so I have nothing to repeat." is a leak. It costs 15
points alone and, with a 40-token overhead (a default system prompt in a chat
template is enough), becomes MEDIUM "Hidden system prompt likely injected".
The "two independent tells" are therefore one tell plus a talkative model.

The same phenomenon is also judged twice with opposite severity: a 300-token
hidden prompt is LOW here and HIGH "usage inflation" in billing.

**Change:** treat an answer that denies having instructions as no leak; count
a leak only when the answer quotes instruction-like text. Let billing defer to
the fixed-overhead measurement before calling a fixed offset inflation.

### P1-7 Streaming: one signal does all the work (verified)

A buffered answer replayed as 40 chunks in a burst is caught only by the late
first token. The "uniform gaps" signal needs a coefficient of variation below
0.1 on sub-2 ms gaps (`streaming.py:223`); real burst gaps are tiny but
jittery, so it did not fire and in practice will not. A relay that buffers and
then replays with a 30 ms typing delay passes as "genuine streaming".

**Change:** replace the uniformity test with "share of the total time elapsed
before the first chunk" combined with the tiny mean gap, and compare the
streamed time to first token with the non-streamed total latency of a similar
request: if they are about equal, the answer was complete before the first
chunk left.

### P2 Definition and consistency

1. **Dimension scope.** "Transport security" contains response tampering,
   injected system prompts and prompt caching, none of which is transport.
   Response caching (`determinism`) sits under "Protocol compliance". On the
   embedding surface, determinism is filed under "Concurrency reliability" and
   distinctness under "Capability claims". The `protocol` detector is named
   "OpenAI-compatibility conformance" but also runs against Anthropic and
   Responses targets. Suggested: rename to "Security & integrity", move
   `determinism` beside the integrity checks, and give the embedding checks
   honest dimension names.
2. **Judge "consistent" scores 95, not 100,** so enabling the judge lowers a
   perfect identity dimension to 97.5 (verified).
3. **Context window thresholds use two denominators:** the Warn/Fail boundary
   divides by the probed window, the deduction by the top rung
   (`context_window.py:469`). Recall at the 45 percent rung is "Fail · High"
   although the refinement only showed the window lies below 56 percent.
4. **One fixed token correction (÷1.2) for every tokenizer** (by reading). A
   tokenizer that counts noticeably more than the reference pair would push
   the top rung past a genuine window and produce a "short" finding. Worth a
   test per tokenizer family in the knowledge base.
5. **Single samples decide MEDIUM findings in core dimensions** (one tool-call
   probe with `tool_choice: auto`). A retry before failing would cost one call.
6. **Reasoning detection differs per detector:** billing and determinism use
   the profile only; streaming also uses reported reasoning tokens.
7. **Reliability's slow-tail threshold is 30 s for 8-token replies,** which
   no working relay reaches.
8. **Fingerprint `expect_not_contains` matches substrings** ("meta" in
   "metadata"), unlike the whole-word brand check beside it.
9. **Performance reference** exists for 3 profiles, so "much faster than the
   reference (consistent with a smaller model)" almost never runs.

## Documentation versus code

Checked by script: every scale row in `docs/guide/methodology.md` against the
`SCALE` objects, the weight table against `DIMENSION_WEIGHTS`, the detector
table against the registry, the suite table in `docs/guide/suites.md`, and the
README's counts. Thresholds quoted in prose were checked by hand.

**Consistent:** all chat-surface scale rows (label, status, severity, effect);
dimension weights; detector ids, dimensions and suites; the suite table; the
risk ladder and its advisory checks; "244 model profiles from 23 providers";
every numeric threshold checked in the streaming, billing, injected-prompt,
prompt-cache, determinism, reliability, context-window, identity, embedding
and rerank sections.

**Inconsistent:**

| # | Where | Docs say | Code does |
|---|---|---|---|
| D1 | `methodology.md` "Suites, detectors and modes" and "Method"; `suites.md` line 61 | Confidence can reach high only with a baseline | A usable judge verdict lifts medium to high without a baseline (`scoring.py:389`). The same file's "Verdict confidence" section says so, contradicting itself. |
| D2 | `methodology.md` intro | "every scoring table below is the detector's published scale" | The 51 outcomes of the embedding and rerank scales are not in the document. |
| D3 | `methodology.md` "Embedding surface" | "with per-surface weights" | The embedding weights (40/20/15/15/10) are not listed; the rerank ones are. |
| D4 | `methodology.md` embedding table, column "Id" | `embed.dimension`, `embed.model_field` | These are checks of the detector `embed.identity`, which is not named; the rerank table lists detector ids. |
| D5 | `methodology.md` `streaming.no_content` row | "Not counted" | The scale renders "No deduction" (the detector does leave it unscored; the cell wording differs from the generated one). |
| D6 | `methodology.md` model identity | "Three independent signals"; fingerprints "(knowledge cutoff, tokenizer quirks, formatting, …)" | For most profiles the fingerprint is a second self-identification prompt, and no cutoff is checked by code (P0-3). |
| D7 | `README.md`, capability row | Catches "max output … that isn't delivered" | The probe is capped at 2,048 tokens and passes on any `length` stop (P1-1). |
| D8 | `methodology.md` trick map, #16 | Tampering is "critical" | Without a baseline it is MEDIUM and ends as risk low (P1-2). |
| D9 | `methodology.md` billing | Catches `billing.usage-inflation` | Only above 2.5x; the tolerance is stated, the consequence (2x passes as consistent) is not (P0-4). |

D1 to D5 are documentation fixes. D6 to D9 are accurate descriptions of the
mechanism that overstate what it catches; they are best fixed in the code.

## Suggested order of work

1. P0-1 and P0-2 together: cap the score by risk, cap a dimension by its worst
   finding, and stop relay-side refusals from vanishing. Small changes in
   `scoring.py` and `capability.py` with a large effect on trust in the score.
2. P0-3 `model` field comparison through the knowledge base, and P1-3: both
   are contained fixes that remove wrong verdicts.
3. P1-1, P1-6, P1-4: one-function fixes.
4. P0-4 and P1-5: use the baseline in billing first, then in the other core
   detectors.
5. P0-3 fingerprint coverage: the long-running item; it needs knowledge-base
   work rather than code.
6. Documentation D1 to D5, then the P2 renames (these touch report schemas and
   translations, so plan them with a release).
