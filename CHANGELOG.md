# Changelog

All notable changes to **zing** are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres
to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Chart motion (web UI v2).** Charts move in when their data changes: lines
  draw left to right with their p25–p75 band growing out of the median,
  stacked bars fill bottom to top, the heat grid fills in a wave, and the live
  performance chart pops in each new request. Nothing moves on a resize or a
  language switch, under `prefers-reduced-motion`, or with the new header
  switch set to "Motion off". CSS animations only, no dependency; the chart
  markup at rest is unchanged.
- **Running median in the performance chart.** A thin line per endpoint
  (median of its last 5 successful, uncached requests) behind the request
  dots, in the live view and in saved reports; also a data-table column.
  Computed on the server (`zing/perf/trend.py`); stored reports and downloads
  are unchanged (`GET /api/history/{id}?trend=1` adds it for display).
- **Heat grid with time blocks (Analytics).** Peak hours and the errors grid
  show weekdays across and the day upward (00:00 at the bottom) in blocks of
  1, 2, 3, 4 or 6 hours (default 4), with square cells and a contribution-graph
  colour scale in both themes. The API takes `block` with `bucket=dow_hour`;
  each block's median comes from its raw runs.

### Changed

- Analytics API answers are cached in-process for up to 30 seconds and dropped
  on every saved, deleted or cleared run.

## [0.20.2] — Correct verdicts for honest endpoints

### Fixed

Verdict correctness: an audit of the dimensions and detectors found several ways an
honest endpoint was marked divergent. All of them are fixed.

- **Context window.** The window is judged against the probed ceiling
  (`--max-context-tokens`), so a window larger than the cap is *verified up to
  the cap* instead of "truncated" (every 1M-token model failed before). Every
  ladder rung stays at or below 90% of the window, leaving room for the output,
  and each prompt is built at size / 1.2 because the heuristic under-counts real
  tokens by 12–15%. Parameter rejections, server errors and empty answers end
  the ladder as inconclusive (`probe_error`), never as a failed recall. A missed
  middle needle is re-probed before lost-in-the-middle is reported. A 413 or
  "prompt is too long" counts as a size rejection.
- **Request parameters.** Clients follow the profile's `unsupported_params` (now
  filled in for o1/o3/o4-mini/gpt-5.x and claude-opus-4-7/4-8): reasoning models
  get `max_completion_tokens` and no rejected sampling parameters, and an
  unprofiled endpoint that rejects a parameter is adapted once, for the rest of
  the audit. The `protocol_request` probes still send their parameters verbatim.
  An endpoint behaving like OpenAI's o3 no longer gets a HIGH verdict.
- **Model identity.** No usable answer at all is inconclusive, not pass/100.
  Generic words that are also brand names (step, command, seed, spark, meta, yi,
  grok) count as a rival brand only when the self-identification answer names
  them, never in fingerprint answers.
- **Knowledge base.** A short model id no longer resolves to a longer, cheaper
  tier (`gpt-4` was audited as gpt-4o-mini); an ambiguous id gets no profile. A
  fuzzy match caps the verdict confidence at low. Gemini's cutoff and Pro-tier
  fingerprints, and Moonshot's cutoff probe, apply only to the models they fit.
- **Verdict.** Transport advisories (plain HTTP, reliability failures) lower their
  dimension but no longer raise the substitution risk; plain HTTP to this machine
  or a private network is a low-severity warning. Integrity tampering is CRITICAL
  only when the baseline actually returned the canary intact (a failing baseline
  corroborates nothing). The LLM judge reaches HIGH only with a stated high
  confidence and a baseline that answered every probe; it is told the claimed
  model.
- **Detectors.** Streaming: no late-first-token signal for reasoning models, and an
  empty stream is inconclusive. Determinism: the caching call needs at least 3
  usable identical samples. Protocol: the stop check is not applicable on the
  Responses API. Capability: unclaimed observations are no longer counted.
  Performance: "slower than the reference" is not counted. Reliability: one
  transient failure in a small burst is a warning. Connectivity, reliability and
  context-window statuses now match their findings.
- **Streamed reasoning.** All three clients record when the first streamed
  reasoning delta arrives (`CompletionOutcome.first_reasoning_ms`). When a model
  streams its reasoning, the streaming detector times the first token of either
  kind, so a relay that buffers a reasoning model and replays it at the end is
  flagged again; only hidden thinking excuses a late first visible token.
- **One parameter fallback.** The context-window and performance probes no
  longer carry their own `max_completion_tokens` retry; the client's adaptation
  covers them (the probe evidence reports the client's renaming).
- **Clients and reports.** The Responses client sends `response_format` as
  `text.format`. A host name that merely starts with "127." is no longer treated
  as loopback. HTML/PDF report groups show points in the detector's scoring method.
  Context-window summaries name the probed window (and the declared one beside
  it), so a capped probe no longer reads as measured against the full claim.

## [0.20.1] — LLM review of the texts in the accessibility report

### Added

- **The LLM review of the texts runs locally and against any endpoint.**
  `python -m tests.a11y.llm_review` takes `--base-url`, `--api-key` (raw,
  `env:VAR` or `file:/path`), `--model` and `--api`; a missing field falls
  back to the zing configuration (`--config`, default `./zing.yaml`: its
  `judge`, else `baseline`, else `target` endpoint, as zing's own judge does),
  then to `ANTHROPIC_BASE_URL`/`ANTHROPIC_API_KEY`, then to the Anthropic API.
  Besides the Messages API it speaks OpenAI-compatible chat completions
  (relays, Ollama, LM Studio, vLLM), detected like an audit target. A local
  endpoint needs no key and costs nothing. A key is only sent to the host it
  was configured for.

### Changed

- **The accessibility report uses the LLM review.** When
  `a11y-llm-review.json` is present (or given with `--llm`),
  `python -m tests.a11y.conformance` counts a completed review as the manual
  part of the steps it covers (9.1.1.1, 9.1.3.3, 9.2.4.4, 9.2.4.6, 9.3.3.2,
  9.3.3.3): a step whose automated part passed passes when the review found
  nothing and fails when it found an issue, and the report records a manual
  review. `/v2/accessibility` names the reviewing model. A skipped, failed,
  dry or incomplete review (fewer pages or languages than were tested)
  changes nothing; without the file the report is built as before
  (`--no-llm` forces that). CI runs the review before building the report.
- **Review and update the report in one command.**
  `python -m tests.a11y.llm_review --update-report [REPORT]` applies the
  finished review to `zing/web/static/v2/bitv-report.json` (the file
  `/v2/accessibility` shows), or builds the report afresh with
  `--results a11y-results.json`. `python -m tests.a11y.conformance --update
  REPORT` applies an existing review file without new results. Every step
  keeps its status from the tests alone (`status_tests`), so a newer review
  replaces the older one; long review notes are cut at a line and their
  finding count is kept.

### Fixed

- **A check's elapsed time survives "Continue in background".** Reopening a
  running audit in UI v2 restarted the time of the check in progress at zero,
  so the check times no longer added up to the audit's total. The server now
  stamps each `detector_start` event with its start time (`at`), and the live
  view times the running check from it.

## [0.20.0] — analytics page

### Added

- **Reports record when the audit started (`started_at`).** An ISO UTC
  timestamp taken at the same instant the request records' `start_ms` offsets
  count from, so the time of every call can be reconstructed. Optional: older
  reports without it stay valid.
- **Per-run metrics in `history.db` (schema version 2).** Every saved run gets
  a row in `history_metrics` (start time, success/error/timeout rates,
  latency, TTFT and decode percentiles, billing ratios, reasoning and cached
  token shares, echoed-model mismatch, context window, finding counts, the zing
  version and knowledge-base profile it was scored with) and its dimension and
  detector scores in `history_dimensions`, groundwork for the analytics views.
  A value the run did not measure is NULL, never 0. Runs saved before the
  upgrade are processed once, in small batches, the first time the new
  version opens the database; for reports without `started_at` the start time
  is estimated from `generated_at` and the span of the request records, and
  marked as estimated.
- **Analytics API (`zing serve`).** Four read-only endpoints over the run
  history, the data behind the analytics page:
  `GET /api/analytics/options` (relays, models, suites, stream modes, APIs and
  the date range present in the history), `GET /api/analytics/summary` (KPIs
  of a range against the previous range of the same length: runs, relays,
  models, median score, high-risk share, success rate, TTFT, decode speed,
  billing ratios), `GET /api/analytics/series` (one metric per relay, model or
  relay + model in hour, day, week or weekday x hour buckets of the viewer's
  time zone, with median, quartiles and run counts) and
  `GET /api/analytics/leaderboard` (the relays of one model, or the models of
  one relay). Relays are grouped by their knowledge-base provider or saved
  relay entry when the query runs, so renaming or saving a relay re-groups the
  whole history. Every value carries how many runs measured it; a run that
  did not is left out, never counted as 0. Buckets with fewer than 3 runs are
  flagged, as are series that mix suites, stream modes or APIs, and the points
  where the zing version or the knowledge-base profile changed. Filters:
  `from`, `to`, `suite`, `stream_mode`, `api`, `source=all|manual|monitor`,
  `relay`, `model`; a bad parameter answers 400.
- **Analytics page (UI v2, `/v2/analytics`).** A new page in the main
  navigation compares relays and models over time from the local history:
  KPI tiles for the chosen period (runs, relays, models, median score,
  high-risk share, success rate, TTFT, decode speed, billing ratios) with the
  change against the period of the same length before and how many runs each
  value rests on; a chart of any metric (or dimension score) per relay, model
  or relay × model by hour, day or week, with the median line, the p25–p75
  band, gaps for empty buckets, faded markers and a hint for buckets with
  fewer than 3 runs, markers where the zing version or knowledge-base profile
  changed and a warning when a series mixes suites, probe modes or protocols;
  and a sortable leaderboard of the relays for a model or the models for a
  relay. Filters: period (7 / 30 / 90 days, all, custom), suite, probe mode,
  protocol, source (manual / monitor), relay, model; by default one suite and
  probe mode (the most common), and the whole view is kept in the URL.
  Hand-drawn SVG, no library, no outgoing requests; every chart is also a
  data table, in all seven languages, light and dark. `GET
  /api/analytics/options` also lists the relay × model pairs
  (`relay_models`).
- **Analytics page: peak hours, errors, model integrity, billing and relay
  overhead.** Five more panels, scoped by the same filters: a weekday × hour
  heatmap of a metric (TTFT by default; latency, speed, success, error,
  rate-limit and timeout rates, score) for all relays
  or one, in the viewer's time zone, cells with fewer than 3 runs hatched and
  empty cells outlined; failed calls by cause (rate limits / HTTP 429, 5xx,
  timeouts, 4xx, network and other errors) as stacked bars over time and a
  table per relay or model with counts and rate-limited / timeout shares,
  stating how many runs have request records; an integrity matrix per relay ×
  model with pass / warn / fail chips (icon and text) for the identity,
  capability, vision, streaming, protocol, integrity, injected-prompt and
  connectivity checks, the model-mismatch share and the measured share of the
  declared context window; billing ratios over time against a 100% reference
  line, reasoning and cached-input shares, and a per-relay summary; and the
  processing time a relay reports next to the network round trip. Every chart
  has its data table. New endpoints `GET /api/analytics/errors` (request
  outcomes counted in SQL by class, per relay or model and per time bucket,
  with coverage), `GET /api/analytics/integrity` and `GET
  /api/analytics/breakdown` (some metrics per group over the range);
  `/api/analytics/series` also takes `group=all`. Each panel loads on its own
  (`PANELS` registry in the page).
- **Analytics page: tabs and share links.** The panels sit in five tabs under
  the page header and one filter panel shared by all of them: Overview (KPIs,
  leaderboard), Trends (comparison over time, peak hours), Reliability
  (errors, relay overhead), Model integrity and Billing; only the shown tab's
  panels load, and a filter change reloads that tab while the others reload
  when shown. The URL fragment keeps the tab, every filter and every panel
  option (`#tab=reliability&range=30&source=monitor&eb=dow_hour&…`), and
  **Copy link to this view** copies it, announcing "Link copied" (where the
  browser offers no clipboard, the link appears selected in a read-only field
  to copy); opening the link restores exactly that view, older links without a
  tab open Overview. The filter panel is now collapsible like History's (the
  same component) and, closed, names the period and every active filter in one
  line. Also: the errors panel offers weekday × hour buckets (a grid of the
  failed share); the billing chart's axis is zoomed to the data around 100%
  instead of starting at 0%, with the 100% label at the left of the plot; each
  integrity cell has one accessible name ("All 7 passed", "Failed: 4 of 7
  passed · 2 failed"); the peak-hours hint speaks of hatched cells.

### Changed

- **History's closed filter panel names the active filters.** Next to the
  count of active filters, a line under the toggle lists them (e.g. "Last 30
  days · Example Relay · Ad-hoc"), and the toggle is described by it. The
  panel is now a component shared with the Analytics page
  (`v2/filterpanel.js`, `v2/filterpanel.css`) and works as before; its toggle
  reads "Filters" (was "Filters & trends") on both pages, so the same control
  has the same name everywhere (BITV 9.3.2.4); the trend picker is still in it.
- **CI runs the accessibility suite only for the pages a change affects.** On
  pull requests a new `accessibility scope` job
  maps the changed files to web UI v2 pages (`python -m tests.a11y.affected`,
  one mapping in `tests/a11y/pages.py`) and the browser suite tests only those
  pages, in one to four jobs; a docs-only change skips it. Changes to the audit pipeline (detectors,
  runner, clients, scoring, reports) run the audit page, whose flow runs a
  real audit. Files every page
  uses, and any web UI file the mapping does not know, still run everything.
  Pushes to `main` and the integration branches, a new nightly run and
  manual runs test every page, and only those full runs build the BITV conformance report. Pip
  and Playwright's Chromium are cached. Locally, `ZING_A11Y_PAGES=history,kb`
  selects pages the same way (tests/a11y/README.md).
- **Smaller `history.db`: request records are stored once.** A report's
  `performance.requests` (target and baseline) move out of the stored report
  JSON into their own table, `history_requests`, and are put back when the
  report is read, so saved reports read back exactly as before. Existing rows
  are converted by the same one-time backfill; a row is either fully converted
  or left as it was, and rows that still hold their records inline keep
  working.

### Fixed

- **Performance chart tooltips no longer track pointer movement.** They open
  when the pointer enters a mark (Audit and History pages), as the other
  charts do.
- **German analytics tile labels break with a hyphen.** "Abrechnungsverhältnis"
  broke mid-word without a hyphen in the overview tiles; it now carries a soft
  hyphen, and tile labels use `hyphens: auto` with the page language.
- **Report meta labels wrap on narrow screens (UI v2).** A long label in the
  report's meta strip, such as the French "Requêtes de la sonde de
  performance", could not shrink and was cut off at 320 px wide (Audit and
  History); it now wraps like its value.

## [0.19.2] — fixes for local and reasoning models

### Changed

- **Accessibility report link moved to the header (UI v2).** The link to the
  conformance report is no longer a text link at the bottom of every page but
  an accessibility icon next to the language switch, in the same place on
  every page. It is named "Accessibility" for screen readers (and as its
  tooltip), marked as the current page on the report itself, and the
  multiple-ways test (9.2.4.5) now counts links in the page header as
  site-wide navigation.

### Fixed

- **Local servers no longer read as response caches.** Ollama, llama.cpp and
  LM Studio reuse the KV cache of the chat template (system prompt, role
  markers) and report those few tokens as cached on every unique prompt, so the
  performance probe flagged nearly every request as a cache hit, excluded all
  samples and showed no latency statistics. A request now counts as cached only
  when its cached input tokens cover at least half the prompt
  (`zing.perf.recorder.is_cache_hit`).
- **Reasoning models no longer fail short probes.** A probe with a small output
  limit (connectivity, determinism, stop sequence, multi-turn, self-identification,
  context-window needle, integrity canaries…) could end at the limit while a
  reasoning model was still thinking, returning an empty or cut-off answer that
  was scored as a failed completion, a missed needle or a value substitution.
  The client now repeats such a request once with a 4,096-token limit
  when the answer is empty, or cut off after reasoning took at least half the
  limit (`RequestSpec.reasoning_retry`, on by default); probes whose limit or
  timing is the measurement opt out. An integrity canary cut off at the output limit
  is inconclusive, never a substitution.
- **Own brand is never a rival.** Self-identification and the fingerprint
  brand check treat the provider key, the brand words of the provider's display
  name and the leading word of the model id or family (e.g. `glm` for
  `glm-4.6v-flash`) as the model's own brand. A profile with an empty
  `identity_keywords` list no longer reports "I am GLM … by Zhipu AI" as a
  rival brand (FAIL HIGH, identity capped at 20).
- **Knowledge-base import fills missing identity keywords.** `zing kb-import`
  and the web **Knowledge base** page fill an empty `identity_keywords` list
  with the provider and model-family words and show a warning so the result can
  be checked; the research prompt now requires the list. `zing kb-import` also
  prints bracketed text in its warnings and errors, which it used to swallow.
- **Fingerprints that cannot fit the identity output cap are skipped.** Probes
  needing more than the 512-token identity cap (e.g. GLM's `true-max-output`,
  which counts to 4,000) could never pass and always diverged. They are now
  skipped, reported as not run, and another probe takes the slot. Importing a
  profile with such a probe now warns that the identity check will skip it.
- **Context-window probe catches front truncation.** Each size is probed at the
  start of the prompt first; a start miss is confirmed after an end-of-prompt
  recall, so a server that silently keeps only the end of a long prompt (e.g.
  Ollama at its `num_ctx`) no longer reports the full probe cap as its window.
- **Reasoning models get room to think up front.** Once an endpoint is known to
  reason (profile `reasoning: true`, or after a repeated probe got its answer),
  short probes are sent with the 4,096-token limit from the start instead of
  twice, which halves the long context-window requests on slow local servers.

## [0.19.1] — history sorting and grouping

### Added

- **History (UI v2): sort, collapse groups, fold the filters.** The column
  header (Time · Risk · Score · Grade) now sorts: rows within each relay group,
  and the groups by their first row; a second click reverses the order, risk
  sorts most severe first. Each group's heading collapses or expands its rows
  (trend tiles stay visible), with **Collapse all / Expand all** next to the
  sort buttons. The filter and trend settings sit in a panel that starts
  closed; its toggle counts the active filters, and the result count and
  **Reset filters** stay visible while it is closed. Sort order, collapsed
  groups and the panel state are remembered per browser. All three are native
  disclosure / toggle buttons that keep focus in place, and a status message
  announces each new sort order (`tests/a11y/test_history_controls.py`).

## [0.19.0] — backend performance

**Upgrade note.** Token counting no longer uses tiktoken, and installs that had
the `tokenizers` extra are scored differently by the billing audit: prompt
inflation now fails above 2.5× the estimate (was 1.8×), and completion tokens
far above the estimate are only a warning (cap 70), never a failure. Reports of
the same relay before and after the upgrade can therefore differ in the
**Billing & usage** dimension. The `tokenizers` extra still installs (it is
empty), so `pip install 'zing-audit[tokenizers,web]'` keeps working; drop it
from new install commands.

### Added

- **`history.latest_for(base_url, claimed_model)`** returns the newest saved
  report of one target and model with a single lookup on the existing
  `idx_history_target` index; the monitor's regression check uses it.
- **Precompressed responses.** `zing/web/caching.py` gains `encoded_response()`,
  `precompressed()`, `accepts_gzip()` and `gzip_etag()`, and `zing/i18n` gains
  `locales_encoded()`: a cached body is gzipped once, when it is built, and
  served with `Content-Encoding: gzip`, `Vary: Accept-Encoding` and its own
  ETag (`"…-gz"`).

### Changed

- **Context-window filler is built in linear time, off the event loop.**
  `build_filler()` re-joined and re-counted the whole text every 50 lines, so
  its cost grew quadratically: 5.7 s at the default 200K-token probe cap and
  118 s at 900K. It now keeps a running per-line sum (about 0.09 s at 200K) with
  byte-identical output, and remembers the last four sizes it built. The
  context-window and prompt-cache detectors build their fillers and haystacks
  in a worker thread (`asyncio.to_thread`). On an instant mock relay a `full`
  audit drops from about 4.3 s to 0.4 s and the longest event-loop stall from
  about 3.9 s to about 130 ms. Audits running in parallel in `zing serve` no
  longer distort each other's timings: a 300 ms request of a second audit used
  to be recorded as 3,980 ms, now as 307 ms.
- **Token counts are always heuristic estimates; nothing is downloaded.**
  `zing/utils/tokenize.py` uses only its built-in, language-aware heuristic for
  every model family. Before, the optional `tokenizers` extra made tiktoken
  fetch a multi-megabyte BPE file over HTTPS on first use, synchronously on the
  event loop; zing now runs in restricted and offline environments that reach
  only the relays you audit. The `tokenizers` extra is empty and kept for
  compatibility. The report fields `tokens_exact` and the billing evidence's
  `exact_tokenizer` stay and are always `false`.
- **Billing scoring is the same for every install** (see the upgrade note):
  prompt inflation is a **Fail** above 2.5× the estimate and more than 50 tokens
  over it; for a non-reasoning model, completion tokens above 3× the estimate
  and more than 80 tokens over it are a **Warning** (`above_heuristic`, cap 70).
- **The performance section always notes that local token counts are
  estimates**, with new wording in every UI language: "Local token counts are
  estimates (about ±15-20%) from a built-in heuristic; zing never downloads a
  tokenizer."
- **Monitors run concurrently.** The `zing serve` scheduler starts every due
  monitor as its own task instead of running them one after another. The relay
  gate still allows one audit per relay host and at most
  `ZING_MAX_PARALLEL_AUDITS` in total; monitors can now fill those slots, so an
  audit started by hand may queue behind them. A run's webhooks are sent
  concurrently, so a dead one (10 s timeout) no longer holds up the others.
  **Run now** answers 409 for a monitor the scheduler has just started, a
  master-key reset cancels scheduled runs that have not started yet, and a
  server shutdown cancels the runs in flight.
- **`/locales.js` and the HTML pages are served precompressed.** They were
  gzipped again by the middleware on every response, on the event loop; now
  once, when built. The full `/locales.js` bundle answers in 1.3 ms instead of
  59 ms, `?lang=de` in 1.1 ms instead of 16 ms, `/v2/` in 1.0 ms instead of
  3.5 ms. A gzip client revalidates with either ETag; a client that refused
  gzip only with the identity one.
- **Read-only callers share the cached knowledge base.**
  `load_knowledge_base(copy=False)` returns the shared cached instance instead
  of a deep copy; the web UI's lists, the catalog, model resolution and the
  Monitors list use it (audits, the CLI and every caller that modifies the
  result keep their own copy). `/api/kb/profiles` drops from about 15 ms to
  7 ms, the catalog from 9.6 ms to 2.3 ms, `/api/kb` from 8 ms to 4.5 ms.
- **Faster CLI startup.** The HTTP clients, the knowledge loader, the runner,
  the report renderers (ReportLab) and asyncio are imported inside the commands
  that use them: `zing --help` starts in 369 ms instead of 467 ms, and every
  command about 100 ms faster.
- **CI** installs `.[dev,web]` (no `tokenizers`) and skips the slow browser
  accessibility suite and its report on pull requests into `perf/integration`;
  it still runs on that branch's pushes and on its pull request into `main`.

### Removed

- **tiktoken support** and `is_exact_tokenizer()` in `zing/utils/tokenize.py`;
  the `tokenizers` extra no longer installs anything.
- **The completion-inflation Fail outcome** (`billing.usage-inflation-completion`
  `inflated`, "Reported completion tokens far exceed the estimate of an exact
  tokenizer.", cap 55) is gone from the billing scale; only the
  `above_heuristic` Warning remains.
- The `tokens_exact` parameter of `build_performance()`.

### Fixed

- **Monitor regression alerts no longer stop after 50 other runs.** The
  previous run of a monitor's target was searched among the newest 50 history
  rows only, so once 50 runs of other targets had been saved in between, the
  regression check and the "since last run" delta silently had nothing to
  compare with. It now uses the most recent saved run of the same target and
  model, however old (`history.latest_for`), read after the audit so a run of
  the same target that queued ahead of it counts.
- **A monitor that waited for its relay no longer comes due again at once.**
  `last_run_ts` is the moment its audit starts (after the wait), not the moment
  it became due.
- **`Accept-Encoding: gzip;q=0` is honoured.** The compression middleware
  gzipped such responses anyway (it only looked for the substring `gzip`).
- **`/console` is served precompressed** with its `-gz` ETag and answers
  conditional requests with 304, like the other pages.

## [0.18.0] — web UI v2: guided relay configuration

### Added

- **Guided relay configuration on the v2 Audit and Tools pages.** The form now
  starts with **Relay / provider**: a provider of the knowledge base or a relay
  you saved. Picking one fills in its base URL (the provider's other known URLs
  are offered as suggestions; **Other** takes any URL). zing then lists the
  relay's models on its own (when a relay is picked and whenever the URL or API
  key changes; **Refresh models** asks again) and **Model to request** becomes a
  pick from that list; a relay without a model list falls back to typing the id.
  **Claimed model** lists the knowledge base's models (chat models on the audit,
  embedding models on the embedding check), preselects the profile the
  requested model resolves to and names the profile the audit will use. The
  trusted baseline and the rerank check are configured the same way, without a
  claimed model.
- **Saved relays.** **Save to knowledge base** keeps a relay that is not listed
  yet under a name you give it: a provider entry in `kb.db` with the name and the
  base URL, no models (no schema change, readable by older versions). It is
  offered in the relay list from then on and listed under **Knowledge → Relays**,
  where it can be switched off or deleted like any entry. API:
  `POST /api/kb/relays {name, base_url}` (400 for bad input, 409 when the name
  or the URL is already known).
- **Knowledge page (v2).** The **Models** page is now **Knowledge** (`/v2/kb`,
  same URL) with three tabs — **Models**, **Providers**, **Relays** — built from
  one pattern: each lists the complete set (packaged, `ZING_KB_DIR` and yours,
  marked **Yours**) with a filter, an on/off switch per item, **Delete** for your
  own items and an **Add …** form (the research-prompt wizard for models,
  provider YAML for providers, name + base URL for relays). Tabs follow the
  WAI-ARIA tabs pattern (arrow keys, Home/End) and can be linked
  (`#providers`, `#relays`, `#add-relays`, …). The model-id lookup names a
  closer profile that is switched off.
- **Switch packaged items off.** A packaged or `ZING_KB_DIR` model, provider or
  relay can be switched off; it is stored in `kb.db` (new table `kb_disabled`,
  ignored by older versions) and applies to the web UI and `zing check` alike:
  the model id no longer resolves, a provider takes its models and base URLs
  with it. `--no-user-kb` / `ZING_NO_USER_KB` ignore the switches. API:
  `GET /api/kb/profiles` now returns `models`, `providers` and `relays` (each
  item with `key`, `source`, `yours`, `enabled`, …); `PUT /api/kb/enabled
  {key, enabled}` switches one item.
- `GET /api/kb` lists each provider's usable `base_urls` (the `base_url_hints`
  without bare hosts, path fragments, URL templates and endpoint suffixes), a
  `relay` flag and its `entry_id`, and each model's `kind` (`chat` /
  `embedding`).

### Changed

- **Declared provider is derived** in web UI v2 instead of typed: the claimed
  model's provider, else the provider the requested model resolves to (exact id
  or alias); a saved relay is never a declared provider. The audit request and
  the History re-run keep sending and restoring `declared_provider`.
- Web UI v2 no longer loads `modelpicker.js` (the classic UI keeps it with
  **Fetch models**); the relay configuration is `v2/relaycfg.js`. Model lists
  are fetched once per URL, key and protocol, a newer request cancels an older
  one, and a fetch never switches the model field while you type in it.
- A 401/403 from a relay's model list reads as "Enter the API key to list the
  models" instead of a connection failure.
- Accessibility: the audit and tools flows of the browser suite now cover the
  relay configuration (listing models, saving and re-picking a relay); the
  accessibility-tree snapshots and the conformance report are regenerated.
- Web UI v2 tabs (Tools, Knowledge) share `v2/tabs.js` and the tab styles in
  `zing.css`. The on/off switch is now the visible, focusable control itself
  (it was a transparent 1×1 checkbox with the focus ring drawn beside it), with
  forced-colours styles. The knowledge-page flow of the browser suite covers all
  three tabs; lists of switchable items are condensed in the accessibility-tree
  snapshots like table rows.

## [0.17.3] — readable durations and numbers in reports

### Fixed

- **Report numbers no longer use scientific notation.** Evidence durations
  (`*_ms`, `*_s`) read in mixed units with only the units they need (`6 s 97 ms`,
  `1 min 5 s`, `850 µs`) instead of `6.1e+03`; other large or tiny values are
  written out in full (`123457`, `0.0000123`). Reliability latencies use the same
  format, in the HTML, Markdown and PDF reports and the web UI report.

## [0.17.2] — request timeouts that fit slow and local models

### Changed

- **Timeouts scale with the request.** `timeout_sec` (`--timeout`, default 60 s) is
  now the base of each completion's timeout, which grows with the prompt size and
  the output budget at deliberately low throughputs (100 tokens/s prefill, 10
  tokens/s decode). Non-streaming calls get time for both, since no byte arrives
  before generation ends; streaming calls get time for prefill between chunks. A
  long context-window probe no longer fails with `ReadTimeout` after a minute.
- **More headroom for local models.** Relays on this machine or a private network
  (`localhost`, `127.x`, `::1`, RFC 1918 and link-local addresses, `*.local`,
  `host.docker.internal`, …) get at least 300 s and are budgeted at 30 tokens/s
  prefill and 3 tokens/s decode, for llama.cpp, Ollama or vLLM on modest hardware.
- **A hard cap per request.** `max_request_sec` (`--max-request-time`, default 900 s)
  bounds every completion, streams included: a relay that trickles a keep-alive
  byte now and then can no longer hold a request open forever. A request past its
  deadline fails as `DeadlineTimeout` and counts as a timeout in the performance
  section. Requests are still not retried.

### Fixed

- **A slow endpoint is no longer reported as truncating its context.** A
  context-window probe that times out ends the ladder without counting as a recall
  failure (and without probing the other edge at the same size). The window above
  the last recalled size is reported as unverified, with the new inconclusive
  outcome `context_window.timed_out`, instead of "Real context window far below the
  declared one". A timed-out depth probe no longer reads as a lost-in-the-middle
  needle.

## [0.17.1] — web UI v2 performance: faster pages and API, no outgoing requests

### Changed

- **One TLS context per process.** Relay clients and webhook alerts share one
  `ssl.SSLContext`, built once in a worker thread, instead of loading the CA bundle
  for every client (and again for a proxy): opening an audit's HTTP client on the
  event loop drops from ~38 ms to ~1 ms.
- **Unreadable typed YAML values are refused cleanly.** `!!int abc`, `!!bool maybe`,
  `!!timestamp 2026-99-99` and the like in an imported profile, a `--kb-dir` profile
  or `zing.yaml` are reported as "not valid YAML: cannot read 'abc' as int" with
  line and column, instead of a server error (500) or a traceback.
- **Faster test runs.** `pytest-xdist` is part of the `dev` extra and CI runs the unit
  tests with `-n auto`. The a11y harness no longer waits for Playwright's `networkidle`
  (500 ms without any request on every page load); it counts each context's requests and
  settles after 150 ms without one, and its longest tests are collected first. The full a11y
  suite went from about 55–65 min serially to 12 min with 4 workers (`-n 4 --dist worksteal`),
  the unit suite from 100 s to about 18 s. A timing-sensitive performance-probe test now gives
  its mock relay a steady response time. In CI the a11y suite runs as four parallel
  shards (`ZING_A11Y_SHARD=k/4`), each on its own runner; a report job merges their
  results (`python -m tests.a11y.conformance --results` takes several files).
- **The web UI downloads only the chosen language.** `/locales.js` sends one
  language (the `?lang=` parameter, else a `zing_lang` cookie the UI now sets
  next to its stored choice) instead of all seven: about 60 KB for English and
  at most 190 KB for any other language instead of 807 KB. It is built once
  per language instead of on every request and revalidated by `ETag`
  (`Cache-Control: no-cache`, 304 when unchanged). Switching languages loads
  the new one on demand; if that fails the current language stays. Without
  the cookie the full bundle is still served.
- **The web UI uses system fonts and makes no outgoing requests.** Every page
  (v2 and classic) used to load a render-blocking stylesheet from Google Fonts,
  so offline or firewalled machines waited on it and a request left the
  machine. The pages now use the operating system's sans-serif and monospace
  fonts (with Chinese fallbacks), and heading letter-spacing is relaxed to suit
  them; no page, script or stylesheet loads anything from another host.
- **Faster date and number formatting in web UI v2.** The History,
  Knowledge base, Monitors, Accessibility and report views build each
  `Intl.DateTimeFormat` / `Intl.NumberFormat` / `Intl.DisplayNames` once per
  language and options and reuse it, instead of creating one per row; the
  formatted text is unchanged.
- **One shared date and number formatter cache.** `lang.js` now offers
  `ZING_LANG.intl(Ctor, opts[, locale])` with the shorthands `numFmt(opts)` and
  `dateFmt(opts)`, keeping one `Intl` formatter per constructor, locale and
  options, shared by a page's scripts. The v2 pages, the report view and the
  performance panel use it instead of their own caches (`report.js` and
  `perf.js` keep a small one for when they run without `lang.js`); formatters
  follow a language switch, and the formatted text is unchanged.
- **Faster knowledge-base loading.** Profiles are parsed with libyaml's C
  loader when PyYAML has it, the packaged profiles are parsed once per process,
  and the merged knowledge base is cached, keyed on the `--kb-dir` /
  `ZING_KB_DIR` files, the data directory and the kb.db entries, so imports,
  edits and deletes still apply immediately. The Models page, `/api/kb/*` and
  the Monitors list (`/api/watches`) answer in a fraction of the time.
- **Faster profile import checks.** Checking and importing a profile YAML (the
  Models page, `/api/kb/scan` and `/api/kb/import`, `zing kb-import`) and
  reading a `zing.yaml` config use libyaml's C parser too: parsing a 27 KB
  profile takes about 5 ms instead of 80 ms. The checks are unchanged (size
  limit, no anchors/aliases, safe tags only) and rejected YAML is reported
  with the same detailed message as before; one new check refuses profiles
  nested more than 32 levels deep (valid ones nest about six; very deep input
  used to end in a server error). A tab after a value on a line, valid YAML that the
  pure-Python parser refused, is now accepted.
- **History loads faster.** `history.db` stores each run's performance headline
  (p50 latency, TTFT and decode speed) in its own columns, so the History list
  and trends no longer parse every saved report: `/api/history?limit=500&perf=1`
  drops from about 700 ms to under 100 ms for 500 runs. Existing databases are
  filled in once, on first use after the upgrade, and the schema check now runs
  once per database instead of on every connection.
- **Web API requests no longer stall the server.** The History, knowledge
  base, Monitors-list/edit and master-key endpoints and report downloads do
  their SQLite, YAML and rendering work in a worker thread instead of on the
  event loop, so other requests and live audits (which timestamp streamed
  chunks on that loop for TTFT and inter-token latency) are not held up while
  a large history list or the knowledge base loads.
- **Monitor runs, background audits and the audit start no longer stall the
  server either.** The scheduler's due-check, a monitor's pinned-profile and
  previous-run lookups, saving a finished audit to history, recording a
  monitor's run and loading the knowledge base when an audit starts now run in
  a worker thread. Cancel is refused (409) during the brief save of a finished
  audit, a server shutdown waits for that save, a monitor run whose report is
  stored is recorded with it, and a monitor stays "running" until its run is
  recorded.
- **Web UI responses are compressed and its assets cached.** `zing serve`
  gzips responses of 1 KiB and more (never the live audit event streams), and
  serves pages with their local scripts and stylesheets linked as
  `…?v=<content hash>`. Those versioned files are cached by the browser for a
  year, so moving between pages no longer re-fetches them; a changed file gets
  a new hash, and pages themselves are always revalidated. Cold page loads
  transfer about a third of what they did.
- **Web UI v2: no forced layout in the header, no polling in background
  tabs.** The shared header keeps the current section's link scrolled into
  view on phones by measuring the link row after the page is parsed (in an
  animation frame) instead of forcing a layout while it is still loading. The
  History page (`/api/jobs`) and the Monitors page (`/api/watches`) stop their
  2-second refresh while the tab is hidden and refresh at once when it is
  shown again.
- **Faster live performance panel.** While an audit streams, the panel now
  updates its tiles, probe bar, chart and legend in place instead of redrawing
  everything each frame, builds the data table only while "Show data table" is
  open (appending new rows), and reuses one number formatter per locale.
  A streamed re-render with 1,000 requests drops from about 500–700 ms to
  about 60 ms (4× CPU throttle). Keyboard focus, the table's scroll position and the tab, progress
  bar and chart semantics stay as before.
- **History renders long lists faster.** Web UI v2 History shows the first 20
  runs of each relay group and adds the rest 20 at a time with a **Show more
  (n remaining)** button (keyboard operable, announced in a status region);
  group trends still cover every matching run, and an open report or a focused
  row stays shown across re-renders. Off-screen groups skip rendering until
  scrolled near (`content-visibility`). With 500 saved runs the page builds
  about half the DOM and resetting a filter takes roughly a third of the time.

## [0.17.0] — web UI v2 accessibility (BITV 2.0 / EN 301 549)

### Added

- **Accessibility of web UI v2 (BITV 2.0 / EN 301 549 / WCAG 2.1 AA).**
  A browser test suite (`tests/a11y/`, `pytest -m a11y`, Playwright with a
  vendored axe-core; extra `a11y`) checks every v2 page in all seven UI
  languages and both themes. It covers axe rules, keyboard and focus,
  reflow/zoom/text spacing, contrast of text, controls, focus rings and
  charts, motion and flashing, hover/focus content, shortcuts and pointer
  cancellation, reading and focus order, consistent navigation and names,
  language of page and parts, markup parsing, error identification, status
  messages in real task flows and accessibility-tree snapshots. 27 of the 44
  applicable test steps are decided automatically and the other 17 partly
  (docs/ACCESSIBILITY.md). CI runs it as an informational job.
- **Accessibility conformance report** at `/v2/accessibility` (linked in every
  v2 footer): per BITV test step how it is tested and its latest result, a
  coverage summary and an accessibility statement with a feedback link,
  generated by `python -m tests.a11y.conformance`.
- Optional advisory LLM review of link texts, headings, labels and error
  messages (`python -m tests.a11y.llm_review`, needs `ANTHROPIC_API_KEY`).

### Fixed

- **Web UI v2 accessibility (BITV 2.0).** Skip link and landmarks on every page; 3:1
  borders for form controls; readable paused-monitor cards; no truncated text
  at 320 px or 200 % zoom; visible, linked, translated form errors; Chinese
  provider names marked `lang="zh"`; tab borders in forced colours; header
  and history rows in reading order; focus kept on busy buttons and after
  re-renders; announced result counts; chart points, legend keys and report
  statuses that do not rely on colour alone.

## [0.16.11] — performance timeline axes fit the data

### Fixed

- **The performance timeline's axes fit the data.** Each axis maximum used to
  round up to 1/2/2.5/5/10 × 10ⁿ with four intervals, so an audit ending at
  about 510 s got an axis to 1000 s. The axis now picks a nice step first (at
  most six intervals) and rounds up to its next multiple (0–600 s by 100 s), in
  the live panel and the HTML and PDF reports.

## [0.16.10] — History v2: filter by execution (ad-hoc / monitor)

### Added

- **History v2: Execution filter** (ad-hoc / monitor), and a Monitor badge
  on the runs a monitor produced.

## [0.16.9] — v2 hero descriptions fill the page width

### Changed

- **v2 hero descriptions fill the page width.**

## [0.16.8] — v2 History: re-run an audit

### Added

- **Re-run an audit from History.** Every History run has a refresh button next
  to the monitor bell, and every expanded report ends with a **Re-run audit**
  button. Both open the audit form prefilled with that run's relay, model,
  claimed model, provider, protocol, suite, custom dimensions and probe request
  mode (`/v2/?rerun=<id>`). History never stores API keys, so the key field
  keeps its default or your browser's saved credential for that relay; a
  compare run's baseline is not restored.

## [0.16.7] — v2: live view for running monitors

### Added

- **Live view for running monitors (v2).** A running monitor keeps an event
  log, so `/v2/?job=monitor-<id>` follows it like an audit; History shows
  **Watch live** next to **Open monitor**.

## [0.16.6] — fix live performance tiles without TTFT / decode speed

### Fixed

- **Live performance tiles showed no TTFT / decode speed** ("— ms" /
  "— tok/s") while only non-streamed calls had finished. They now fall back to
  end-to-end speed, as the final report does, and empty tiles drop the unit.

## [0.16.5] — protocol, auto-detection and request mode in reports, history and monitors

### Added

- **Protocol and request mode in every report, history row and monitor.**
  A report now records the wire protocol each endpoint spoke
  (`target.api` / `baseline.api`: `openai`, `anthropic` or `responses`), whether
  it was auto-detected or set by hand (`api_auto`), and the performance probe's
  configured request mode (`stream_mode`: `stream`, `non_stream` or `both`).
  The Markdown, HTML, PDF and compact JSON reports and the v2 report view
  show them. The v2 history page lists them on each run and can filter on
  protocol, detection and request mode, with "(unknown)" for older runs.
  Monitors show their protocol (with what `auto` detects) and request mode,
  keep a non-streaming probe setting, and a monitor scheduled from a run keeps
  the run's protocol when it was set by hand.

## [0.16.4] — fix the running check's clock in web UI v2

### Fixed

- **Web UI v2: the running check's clock showed a huge time** (e.g.
  "1.791.104.830 s"). It subtracted a `performance.now()` start from
  `Date.now()`, i.e. it counted from 1970; both now use `Date.now()`.

## [0.16.3] — `--data-dir` option and `zing data-dir`

### Added

- **Choose and find the data directory.** A new `--data-dir PATH` option
  (global, and on `zing serve`) puts `history.db`, `watches.db` and `kb.db` in
  another folder for that run, e.g. `zing serve --data-dir .` for the current
  folder; it overrides `ZING_DATA_DIR`. `zing serve` prints the data directory
  at startup, and the new `zing data-dir` command prints it for scripts
  (`sqlite3 "$(zing data-dir)/history.db"`). The default stays `~/.zing`.

## [0.16.2] — encrypted API keys and the master key documented in every language

### Documentation

- **Encrypted API keys and the master key in every language.** The master-key
  dialogs and the Monitors page's key texts are translated into every UI
  language, and the READMEs and developer guides in all languages describe the
  encrypted storage.

## [0.16.1] — master key kept out of the data folder, managed on the Monitors page

### Added

- **The master key stays out of the data folder, managed on the Monitors
  page.** zing never writes the master key to disk. The first time a monitor
  gets an API key, the new UI shows a fresh master key once (copy, download,
  then paste it back to confirm, which also lets the browser's password
  manager save it). After each restart of `zing serve` the page asks for it
  (the password manager fills it in) and monitors that need it wait until
  then; keyless and `env:`/`file:` monitors keep running. The status bar on
  the Monitors page also offers **Lock**, **Rotate** (new key, every API key
  re-encrypted in one transaction, the old key stops working) and **Forgot
  the key?** (drops the encrypted API keys, monitors pause until they are
  entered again). `ZING_SECRET_KEY` still unlocks headless and Docker setups
  automatically. A `secret.key` written by an earlier build keeps working
  until you choose **Move it out**, which switches to a new key and deletes
  the file. A running server notices when `zing secret rotate` changes the
  key and locks itself. `zing secret status | export | rotate` follow the
  same rules (`rotate` also creates the first key and prints it once).

## [0.16.0] — monitor API keys encrypted at rest

### Added

- **Monitor API keys are encrypted at rest.** `zing serve` now stores each
  watch's API key in `watches.db` as a Fernet token (`enc:v1:…`, AES with an
  HMAC check) instead of plain text; `env:VAR` / `file:/path` references stay
  as they are. Existing plain-text keys are encrypted (and scrubbed from the
  database file) the first time the server starts. The master key comes from
  `ZING_SECRET_KEY` (a key, or `env:`/`file:` reference; comma-separated to
  rotate) or is generated in `<data dir>/secret.key` (`0600`). New commands:
  `zing secret status | export | rotate`. A watch whose key no longer decrypts
  is shown as "Unreadable – re-enter" and skipped instead of run without a key.
  The `web` extra now depends on `cryptography`. Downgrading to an older zing
  leaves the stored keys unusable (re-enter them there).

## [0.15.22] — background audits, one audit per relay at a time

### Added

- **Background audits in the new UI.** An audit is now a job owned by the
  `zing serve` process instead of the browser tab: switching pages, reloading
  or closing the tab no longer stops it, and **Continue in background** on the
  scan view detaches it on purpose. **History** shows an **In progress** panel
  with every queued and running audit (and running monitor), its progress and
  **Watch live** / **Cancel**; the live view re-attaches via `/v2/?job=<id>` and
  replays what already happened. New endpoints: `POST /api/jobs`,
  `GET /api/jobs`, `GET /api/jobs/{id}`, `GET /api/jobs/{id}/events` (SSE) and
  `POST /api/jobs/{id}/cancel`.
- **One audit per relay at a time.** Audits of the same relay (by host name;
  every loopback address is one host, so locally served models count once) are
  queued one after another so they cannot skew each other's latency,
  throughput or reliability results; audits of different relays run in
  parallel, at most `ZING_MAX_PARALLEL_AUDITS` (default 4) at once. Monitors and
  the classic UI's audits wait in the same queue; a waiting monitor shows as
  queued on the Monitors page.

## [0.15.21] — PDF reports typeset with ReportLab

### Changed

- **PDF reports no longer need a system library.** The PDF is typeset natively
  with ReportLab (pure Python, BSD-licensed) instead of converting the HTML
  report with WeasyPrint, which needed Pango. ReportLab is a core dependency, so
  `--format pdf`, `--format all` and the web UI's PDF download work on every
  install, Linux, macOS and Windows alike, and the CLI and the web UI produce
  the same document. It carries the HTML report's content (all dimension
  details expanded, findings with evidence, performance charts and tables) and
  writes Chinese with a standard PDF font the viewer supplies, so no fonts are
  shipped. The `pdf` extra is now empty and kept only so older install commands
  still work; the Docker image drops Pango and its fonts.

## [0.15.20] — READMEs split into user READMEs and developer guides

### Documentation

- **READMEs split into user and developer documentation, in all seven
  languages.** Each `README.<lang>.md` now covers only using zing (install,
  CLI, web UI pages of the classic and the new UI, checks, verdict, suites,
  performance, monitoring, non-chat audits, CI, knowledge base, reports,
  privacy) and opens with a table of contents; a new
  `DEVELOPER_GUIDE.<lang>.md` covers architecture, development setup,
  contributing, translations, tests, Docker, CI and releases.
  `CONTRIBUTING.md` now points to the developer guide. The texts were brought
  up to date (98 profiles, the new UI's pages, the `custom` suite, the user
  knowledge base) and use the web UI's and the Methodology's wording in each
  language. `docs/CI.md` pins `v0.11.0` and lists the `responses` protocol.

## [0.15.19] — METHODOLOGY rewritten, one file per language

### Documentation

- **METHODOLOGY rewritten for the current implementation, one file per
  language** (en, zh-CN, fr, es, pt, it, de, with the READMEs' language
  switcher). It documents what the detectors actually do: scoring methods,
  dimension status overrides, weights, rating, risk and confidence rules,
  suites and modes, each detector's probes and every detector's published scale.
  Unimplemented research ideas are marked as roadmap. Scale tables use the web
  UI's own labels in each language.

## [0.15.18] — READMEs: `pdf` extra in install commands

### Documentation

- **READMEs: the `pdf` extra in the install commands**, and the web UI
  section lists every download format.

## [0.15.17] — v2 UI: one relay config; Fetch models for every provider

### Changed

- **One relay configuration in the v2 UI, with "Fetch models" everywhere.**
  The audit, embedding and rerank forms (and the audit's trusted baseline) share
  the same relay URL / API key / model fields and the same model picker on
  "Model to request". "Fetch models" (the relay's own `/models`) is offered for
  every provider, not only "Custom (from relay)": a knowledge-base provider marks
  the models the relay lists (✓) and adds the relay's ids the knowledge base
  does not know yet ("Relay only"), so a model newer than the knowledge base can
  still be picked for an audit, embedding or rerank check.

## [0.15.16] — v2 UI: aligned buttons, fields and texts in every language

### Fixed

- **v2 UI: buttons, fields and texts line up in every language.** Checked on all
  v2 pages and their interactive states (tabs, disclosures, custom suite, scan,
  report, history rows, monitor editors) in all seven languages, desktop and phone:
  the header no longer overflows phones in German / French; audit suite and
  protocol buttons never clip their label (DE "benutzerdefiniert"); scan rows keep
  the check name readable on phones; report dimension bars share one length (a
  "Not run" label takes the empty bar's place) and their subtitles align with the
  name; history rows show mode / suite under the date so every date and risk label
  fits on one line; monitor card values stay in line when a label wraps and an open
  editor gets the full row; Tools tabs, protocol switch and intro tags align;
  Models table headers no longer break. Two monitor status texts were untranslated,
  and French text now keeps `? ! : ;` on the line of the word before them.

## [0.15.15] — Monitors: live progress, Cancel, run-time-aware intervals

### Added

- **Monitors: live progress and Cancel.** A running monitor reports a rough
  percent done in `/api/watches` and can be stopped with the new
  `POST /api/watches/{id}/cancel`; a cancelled run keeps the card's last result.
  The v2 page shows a progress bar and swaps Run now for Cancel run.

### Changed

- **Monitor intervals are never shorter than one run.** Each monitor stores
  how long a full run takes (from the History run it was scheduled from, then
  from every completed run). The interval is picked from fixed steps (5, 10, 15,
  20, 30 min, 1–24 h), none shorter than that run time, and the server rejects
  shorter or over-24 h intervals.

## [0.15.14] — History: no "Schedule as monitor" for monitor runs

### Changed

- **History: no "Schedule as monitor" for runs a monitor produced.** Monitor
  runs are saved with the id of their watch (new `history.watch_id` column,
  added to existing databases on open); the v2 History page disables the bell
  for them and `POST /api/watches/from-history/{id}` refuses them with 409.

## [0.15.13] — v2 Monitors: edit button never renders empty

### Fixed

- **v2 Monitors: the edit button could render empty.** The pen glyph is now
  inlined.

## [0.15.12] — v2 Monitors: running state

### Added

- **v2 Monitors show when a monitor is running.** A Running badge and status
  line (Running / Waiting for next scheduled run); Run now and Delete are
  disabled while it runs. The server tracks in-flight runs (scheduler and Run
  now), adds `running` to `/api/watches`, rejects overlapping runs with 409, and
  the scheduler skips a monitor that is still running.

## [0.15.11] — remove the v2 console page

### Removed

- **The v2 console page** (`/v2/console`) — it was one more view to maintain.
  `/console` stays the classic page and is no longer redirected by the v2 cookie.

## [0.15.10] — monitor "Open in history" prefills the History filters

### Added

- **"Open in history" on a monitor prefills the History filters** (relay,
  model, suite) for that monitor; filters from the link replace the remembered
  ones so stale filters cannot hide its runs.

## [0.15.9] — v2 Monitors: pen icon edit buttons

### Changed

- **v2 Monitors: pen icon buttons for editing** instead of the Change /
  Replace / Edit text buttons.

## [0.15.8] — report: every dimension listed and expandable

### Changed

- **Every dimension is listed and expandable in the audit report; performance
  is one of them.** The v2 report view and the Markdown/HTML/PDF reports list
  all ten dimensions, those that did not run (or were not selected in a custom
  run) included, muted and with the reason; each row expands. The performance
  measurements (charts, stats, baseline comparison) no longer form a separate
  section: they sit in the Performance dimension's details, next to the
  probe's scored checks. A dimension gains such extra content by registering
  a renderer (`DIM_EXTRAS` in `v2/report.js`, `_EXTRAS` in
  `zing/report/dimensions.py`).

## [0.15.7] — History v2: filled Latency p50 and Tokens/s trends

### Changed

- **History v2: the Latency p50 and Tokens/s trends fill the area under their
  line.**

## [0.15.6] — lint fix in the watch update handler

### Fixed

- **Lint:** ruff SIM102 in the watch update handler.

## [0.15.5] — v2 monitors: optional API key

### Changed

- **v2 monitors: the API key is optional**, as on the audit page. A monitor
  scheduled from History can be activated and run without one, so local and
  self-hosted models (Ollama, LM Studio) work; the setup box labels the key
  field optional.

## [0.15.4] — v2: live performance colours match the audit progress accent

### Changed

- **v2: live performance colours match the audit progress accent** on the
  audit and console pages.

## [0.15.3] — v2 audit page: declared provider, live per-check timing, execution log

### Added

- **Declared provider on the v2 audit page.** The audit form takes an optional
  `declared_provider` (as the console already did), sends it with the audit and
  fills it in when a model is chosen from the model picker; the report's meta
  strip shows it.
- **Per-check timing and evidence while an audit runs (v2 audit page).** The
  live checks list shows every check's score and wall-clock time, a running
  clock on the check in progress and the audit's elapsed time; a check with
  findings expands to show all of them with their evidence and recommendation.
- **Execution log in the v2 report.** A collapsed section lists every detector
  in run order with its outcome, score, time and error, the total time and the
  slowest check. It appears wherever the v2 report is shown (audit, console,
  history), including reports saved before this change.

## [0.15.2] — PDF reports; every format downloadable from the v2 UI

### Added

- **PDF reports.** `--format pdf` writes the HTML report typeset as PDF, and
  `--format all` (the default) adds it next to JSON, Markdown and HTML. PDF
  rendering uses WeasyPrint, the new optional `pdf` extra
  (`pip install 'zing-audit[pdf]'`); without it `--format pdf` fails before any
  request is sent and `all` skips the PDF. Rendering never fetches external
  resources. The Docker image includes it.
- **Download every report format from the v2 UI.** The report on the audit,
  console and History pages has a **Download report** row with JSON, Markdown,
  HTML and PDF. Text is exported in the UI language as before; Markdown, HTML
  and PDF are rendered by the new `POST /api/report/export?format=…` endpoint.

## [0.15.1] — Monitors v2: schedule monitors from History

### Added

- **Schedule a History run as a monitor (v2 UI).** Every run in v2 History has
  a **Schedule as monitor** action (a bell button on the row and a button in the
  report). It copies that run's configuration (relay, model, claimed model,
  provider, suite, custom dimensions) into a paused monitor that has no interval
  yet. The v2 monitors page now lists only the configured monitors; the
  duplicate audit form is gone. A newly scheduled monitor shows a setup box for
  the interval and the API key (History never stores keys). Interval, key,
  alert threshold and webhooks can now be edited in place on each card.
  API: `POST /api/watches/from-history/{id}`; `PATCH /api/watches/{id}` also
  takes `interval_sec`, `api_key`, `alert_on` and `webhooks`. The scheduler
  skips a monitor that has no interval yet, and such a monitor can't be
  switched on until its interval is set.

## [0.15.0] — custom suite; performance as a scored dimension

### Added

- **Custom suite: run only the dimensions you pick.** `--suite custom` with
  `--dimension/-D` (repeatable or comma-separated; `-D` alone implies custom, and
  `run.dimensions` works in a config file) runs every detector of the selected
  dimensions at deep depth, which saves time and tokens. The overall score is the weighted mean of the
  selected dimensions only; the rest are reported as "Not selected in this custom
  run.", and without a core dimension the risk is inconclusive. The web start
  page, console and monitors have a `custom` suite button with a dimension
  picker; monitors store their selection. Reports carry `dimensions_selected`,
  and `--dry-run` lists the selection.
- **Performance is its own scored dimension** (weight 6). The probe now scores
  consistency: latency, TTFT and throughput tail ratios, the failure rate, the
  slowdown under concurrent load, and cache hits. A slow but steady endpoint (e.g.
  a local model) scores well. Speed counts only in the `performance.reference`
  check, against the baseline or, new, a knowledge-base `performance.decode_tps`
  range. A slower target is informational there, and only a ≥ 2x faster one
  counts against it. Findings stay at most low severity, so they never move the
  risk verdict.

### Changed

- **Dimension weights rebalanced for performance** (still 100): model_identity
  22→21, context_window 20→19, capability 14→13, reliability 8→6, connectivity
  8→7, performance 6. The `performance.throughput_mismatch` finding became the
  `faster` outcome of `performance.reference`.

## [0.14.9] — History v2: filters and configurable trends; v2 theme switch

### Added

- **History (v2): filters and a latency trend.** A filter bar (search, relay,
  claimed model, suite, mode, risk, minimum score, period) narrows the history;
  groups and their trends are rebuilt from the matching runs only, and the
  filters are remembered in the browser. The group trends are configurable
  (any mix of score, grade, latency p50 and tokens/s; score + latency by
  default), each KPI number in its sparkline's colour; the duplicate "Latest
  score" block is gone. `GET /api/history?perf=1` adds each run's p50
  latency / TTFT / decode speed.
- **Theme switch (v2).** The v2 header has an Auto / Light / Dark picker,
  remembered per browser and applied before first paint on every v2 page.

## [0.14.8] — scoring scales for every remaining detector

### Added

- **Every remaining detector publishes its scoring scale** (capability,
  vision, context window, streaming, reliability, performance, security,
  injected prompt, integrity, prompt cache, LLM judge).

### Changed

- **`capability`: inconclusive checks no longer count** (a probe that failed
  to complete scored 50), as in `protocol`.
- **`security`: the lowest cap wins.** Plain http plus a verbatim API-key echo
  now scores 30 (the key-echo cap), not 40.

## [0.14.7] — deduction scales for model_identity and billing

### Added

- **Deduction scales for `model_identity` and `billing`.** They start at 100,
  and each finding deducts points and/or caps the score (`Finding.deduction` /
  `Finding.cap`).

## [0.14.6] — scoring scales for connectivity and determinism

### Added

- **Scoring scales for `connectivity` and `determinism`.** Both detectors
  publish their scale of outcomes and points, like `protocol`.

## [0.14.5] — performance: error rate counts every request

### Fixed

- **Performance: the error rate ignored failed audit requests** when the
  dedicated probe ran. It was computed over the probe requests only, so the report
  showed 0.0% and "100/100 succeeded" while the chart showed failed requests. Error,
  timeout and 429 rates (and the succeeded count) now cover every call to the
  endpoint: the audit's own, warm-up, burst and probe. Latency and speed stats still
  come from the probe alone.

## [0.14.4] — protocol: request- and response-attribute detectors

### Added

- **Protocol: request- and response-attribute detectors.** Two new detectors in
  the protocol dimension check the wire contract attribute by attribute, for
  OpenAI Chat Completions, Anthropic Messages and OpenAI Responses:
  `protocol_response` judges every attribute of a response (a missing `usage`,
  `completion_tokens: 0` or a `total_tokens` that is not the sum of its parts no
  longer passes), and `protocol_request` checks that every request parameter is
  accepted — and honored where the effect is visible (`system`, output limit,
  `n`, `logprobs`). Accept-only parameters share one call; a 4xx the model itself
  would give (reasoning models, `unsupported_params` in the knowledge base, or a
  baseline that rejects it too) is not counted. The coarser `protocol.shape`
  check is retired (its question is now answered attribute by attribute).
- **Parametrized checks in reports.** A check applied to many subjects (here:
  attributes) publishes its scale once and shows as one row — problems named
  inline, every subject with its observed value and points behind a disclosure —
  in the v2 UI and the Markdown/HTML reports; passed subjects fold into one line
  in the findings list, and several failing subjects take one key finding.
  New optional fields: `Finding.check` / `Finding.subject`,
  `DetectorScoring.titles`; `RequestSpec.capture_raw` /
  `CompletionOutcome.raw_body` (redacted raw response body, on request).

## [0.14.3] — v2 report: scoring scale in an info tip per check

### Changed

- **v2 report: scoring scale in an info tip per check.** Each check's points
  carry an info toggletip listing every outcome that check could have had, with
  its points and this run's outcome marked, instead of the detector's full scale
  below its checks and a repeated outcome line under every check title. It opens
  on hover or keyboard focus, stays open on click (touch) and closes on Escape.

## [0.14.2] — transparent dimension scoring, piloted on protocol

### Added

- **Transparent dimension scoring.** Every report now explains each dimension:
  how its score was computed (equal-weight mean of its detectors), where its
  status came from (and which findings overrode it), and every check behind it,
  passed and failed alike. Markdown/HTML reports gain a **Dimension details**
  section; in the v2 web UI each dimension row expands into the same details.
  New report fields: `DimensionScore.breakdown`, `DetectorResult.scoring` (a
  detector's published scale of outcomes and points), and `Finding.outcome` /
  `Finding.score`; the compact JSON carries each finding's `points`. The
  `protocol` detector is the first with a published scale.

### Changed

- **`protocol`: inconclusive checks no longer count.** A check without a usable
  response used to score 50 and pull the detector down; it is now left out of
  the mean (the detector has no score when no check counted).

## [0.14.1] — local-only `zing serve`, your own knowledge-base profiles (`kb.db`)

### Added

- **Docker image for the web UI** (`Dockerfile`, [docs/DOCKER.md](docs/DOCKER.md)).
  Inside a container the server may listen on the container's interfaces when
  `ZING_CONTAINER=1` is set *and* a container runtime is detected; publish it
  to the host's loopback (`-p 127.0.0.1:8000:8000`). `zing serve` also reads
  `ZING_HOST` / `ZING_PORT`, and opens no browser in a container.
- **Your own knowledge-base profiles (`kb.db`).** A new **Models** page in the
  v2 UI (`/v2/kb`) lists every profile with its source (packaged,
  `ZING_KB_DIR`, yours) and adds models without YAML files or an editable
  install: copy a research prompt for an external AI assistant, upload its YAML
  answer, and zing checks it before storing it — schema and limits, YAML
  anchors, nested-quantifier regular expressions, every fingerprint prompt it
  would send, and model ids that would resolve to a different profile. CLI:
  `zing kb-prompt`, `zing kb-import [--check]`, `zing kb-export`; `zing kb`
  shows a source column. Entries are merged per model and per fingerprint id
  and win over packaged models (reported as shadowing them); a packaged
  provider's own settings are never overridden; invalid entries are skipped
  with a warning. `zing check` and `zing serve` load the same profiles;
  `--no-user-kb` / `ZING_NO_USER_KB=1` leaves them out. `ZING_KB_DIR` behaves
  as before.
  The v2 header now puts its section links on their own row, so all six fit
  in every language.
- **Reports record the knowledge-base profile they used** (`knowledge`):
  provider and model, how the requested id matched, the source file or `kb.db`
  entry, the user entries involved, and a full snapshot with its content hash.
  Shown in the Markdown/HTML reports, the compact JSON and the v2 report.
  `history.db` stores each distinct snapshot once and links it from the run;
  snapshots nothing points to are deleted with the runs.
- **Monitors pin their profile.** A watch snapshots the profile its model
  resolves to when it is created (`watches.db`) and every run audits against
  it, so a knowledge-base edit cannot silently change what a monitor measures.
  The Monitors page shows the pinned profile, flags when the knowledge base has
  changed since, and re-pins on request.

### Security

- **`zing serve` is local-only by construction.** It refuses any bind address
  other than loopback (`127.0.0.1`, `::1`, `localhost`); `--host 0.0.0.0` is no
  longer accepted. It answers only to `Host: localhost`, `127.0.0.1` or `[::1]`
  (DNS-rebinding protection; `ZING_ALLOWED_HOSTS` adds names), refuses
  state-changing requests from another origin or site (CSRF), requires
  `application/json` request bodies, and sends anti-framing / no-sniff /
  no-referrer headers.
- **Owner-only data directory.** `~/.zing` (or `$ZING_DATA_DIR`, when zing
  creates it) is `0700`, and `history.db` / `watches.db` (which holds monitor
  API keys) are `0600`.

## [0.14.0] — web UI v2 side by side with the classic UI

### Added

- **Web UI v2, served side by side with the classic UI for A/B comparison.**
  `/v2/`, `/v2/history`, `/v2/watches`, `/v2/tools` and `/v2/console` rebuild
  every page in the same design language on one shared stylesheet and header.
  Colours meet WCAG AA contrast, the pages have a dark theme, respect reduced
  motion and have no horizontal scroll on phones. Accessibility covers
  segmented controls, disclosures, tabs, meters and the live log. Every page
  uses the same vocabulary ("Model to request" / "Claimed model", which the
  classic audit page had reversed), risk labels and localized dates. All pages
  offer the Responses protocol and the `full` suite, except the tools page,
  which has no embedding/rerank support for them. `?ui=v2` or `?ui=v1` on any
  page picks a UI and a cookie remembers it. Classic pages have a "Try the new
  UI" link and v2 pages a "Classic UI" link back.
- **Locale fragments**: `zing/i18n/locales/fragments/<feature>/<code>.json` add
  UI strings to a language without editing the main locale files.

### Changed

- **Web UI language menu shows language names** (English, 中文, Français, …)
  instead of flags, and the Chinese UI now translates backend text (verdict
  summaries, recommendations, detector names) like the other languages.
- **Performance panel**: every colour is themeable, tabs are keyboard- and
  screen-reader-accessible, charts have a text summary and a data table, and
  numbers use the UI language's format.

### Fixed

- **Web UI: a page no longer stays blank if a script fails** while loading.
- **"Error response schema" finding when the relay sends no HTTP response** read
  "unexpected outcome (HTTP None)" and stayed in English in every other language.
  It now names the error type (e.g. `ProxyError`) and is translated.
- **Classic audit page: the "Insufficient signal" badge had no background**
  (an invalid colour token).
- **`zing serve --help` dropped `[web]`** from the install hint (Rich markup).

## [0.13.3] — web UI: masked API key fields

### Added

- **Masked API key fields in the web UI.** Every key input is now a password
  field with a show/hide eye toggle, so keys stay hidden on screen shares.
  `env:`/`file:` references start revealed, and a literal key is re-masked when a
  run starts. The relay `base_url` acts as the username, so the browser's password
  manager can save and fill one key per relay.

## [0.13.2] — README translations (FR, ES, PT, IT, DE)

### Added

- **README translations** in French (`README.fr.md`), Spanish (`README.es.md`),
  Portuguese (`README.pt.md`), Italian (`README.it.md`) and German
  (`README.de.md`), linked from a language switcher at the top of every README.
  The English `README.md` no longer contains Chinese text, and `README.zh-CN.md`
  is brought up to date with it.

## [0.13.1] — README: uv install instructions

### Documentation

- **README: install with uv**, from PyPI and from source.

## [0.13.0] — performance section and probe in every report

### Added

- **Performance section in every report.** Latency, time to first token, decode
  and end-to-end tokens/s (from the relay's `usage` and from a local token count),
  inter-chunk latency and jitter, error/timeout/429 rates, a network breakdown
  (TCP connect, TLS, `GET /models` round trip, server time) and cold start, as
  count/min/mean/p50/p75/p90/p95/p99/max/stdev. Percentiles are shown only with
  enough samples. Informational: it never changes the score or the verdict. The
  JSON report adds `performance` with every request's timings (numbers only).
- **Performance probe** (`performance` detector, deep/full, and standard in compare
  mode): uncacheable streaming requests (default 100 × 128 tokens, a random
  request id opens each prompt, no cache or reasoning parameters), `GET /models`
  pings, a warm-up reported as cold start, and a concurrency burst. Compare mode
  alternates target and baseline requests and adds a target-vs-baseline table,
  with each difference marked green ✓ (target better) or red ✗ (target worse).
  The probe streams by default; `--performance-non-streaming` (a switch in the web
  UI) measures relays that cannot stream, and the full suite measures both modes.
  New flags `--performance-requests` / `--performance-max-tokens` /
  `--performance-streaming`; `--dry-run` counts the probe's calls. The web UI's
  suite picker gains `full`.
- **Charts.** The HTML report draws the chosen metric per request over the audit's
  timeline (inline SVG, no scripts). The web UI shows the same chart live while an
  audit runs, the full section in the report and in `/history`, and a latency
  trend per target.

## [0.12.1] — web UI: custom provider that fetches the relay's model list

### Added

- **Web UI: custom provider with live model fetch.** The model picker's provider
  list gains **Custom (from relay)**. With a base_url filled in, **Fetch models**
  calls the new `POST /api/models`, which lists the relay's own `/models`. You
  see right away whether the connection works (model count, or the HTTP error)
  and can pick an id the relay really accepts instead of typing it. The pick goes
  into the requested `model` field. The API key is optional, so keyless
  self-hosted endpoints such as Ollama or LM Studio work too.

## [0.12.0] — web UI in seven languages, translated alerts, prompt library

### Added

- **Web UI: language switch.** Every page (`/`, `/console`, `/history`, `/tools`,
  `/watches`) gets a **🇬🇧 EN · 🇨🇳 CN · 🇫🇷 FR · 🇪🇸 ES · 🇵🇹 PT · 🇮🇹 IT · 🇩🇪 DE**
  dropdown in its header; English is the default. Every user-facing string is translated (labels,
  placeholders, tooltips, dialogs, verdicts, finding titles/summaries, detector names,
  recommendations, status codes, the model picker); CN keeps the original Chinese UI
  unchanged. Switching is live (no reload) and remembered in `localStorage`. Backed
  by new shared `/lang.js` and `/locales.js`. The dropdown is generated from a single
  language registry, a new language is one registry entry plus one translation block,
  and `tests/test_web_locales.py` enforces that every language is complete.
- **Web UI: downloaded reports follow the UI language.** "Download report (JSON)" (on
  `/` and in `/history`) translates every human-readable value — verdict headline and
  summary, key findings, finding titles/summaries/recommendations, detector names,
  dimension reasons, notes — into the selected language (CN included), keeping the
  JSON keys, enums, ids and evidence unchanged so the file still validates as a zing
  `AuditReport`; the file name carries the language (`zing-report.<lang>.json`).
- **Webhook alerts in the monitor's language.** Alerts from `zing watch` and the
  `/watches` monitors were always Chinese (with the verdict headline and key findings in
  English). They are now written entirely in the alert language — English by default,
  or any supported language: `zing watch --alert-lang <code>`, and a per-monitor
  **Alert language** in the web UI (stored in `~/.zing`; existing monitors are migrated
  and send English). The generic JSON payload gains a `language` field; its other keys
  and machine values are unchanged.
- **Translations are shared data.** All translations now live in
  `zing/i18n/locales/<code>.json`, used by the web UI (served as `/locales.js`) and by
  Python (`zing.i18n`, for alerts). Adding a language is adding one file.
- **Prompt library.** Every text sent to an LLM API (chat probes, the judge prompt,
  tool schemas, embedding / rerank / image / audio inputs — 53 entries) moved out of the
  code into `zing/prompts/en.json`, loaded via `zing.prompts`. Probes are English and
  independent of the UI/alert language, so verdicts don't depend on who reads them; a
  capture of every request of a full audit is byte-identical before and after the move
  except the vision probe (below). Knowledge-base fingerprints gained `prompt_lang` and
  `language_bound`: the 7 Chinese probes of China-native models (fluency, tokenizer
  echo, native self-id, cultural recall) stay Chinese because the language is the
  measurement, and must say so. Reports gain `prompt_languages`, shown in the web UI.

### Changed

- **Vision probe asks in English only.** It was bilingual
  ("仅用一个词回答：图片是什么颜色？/ In one word, what color is this image?"); Chinese
  answers are still accepted.

### Fixed

- **Web UI: finding summaries that fell back to English.** Findings emitted by several
  detector branches (pass / warn / inconclusive, request failures) had no matching
  translation template, so their summary appeared in English even in the Chinese UI;
  `embed.dimension` without a known claimed dimension read "should produce 0-d".
  Branch-specific and generic "request failed" templates now cover them.

## [0.11.0] — web UI: claimed-model picker + all-SVG icons

### Added

- **Web UI: claimed-model picker.** The “claimed model” field is now a provider → model
  picker driven by the bundled knowledge base (pick e.g. *DeepSeek* then
  *deepseek-v4-flash*) instead of free typing, with a **自定义输入** toggle that falls back
  to a plain text box for unlisted ids. Wired into the audit form, the advanced console,
  the watch form, and the embeddings tool. Backed by a new `GET /api/kb` endpoint
  (public model metadata only — no secrets).

### Changed

- **Web UI: all emoji replaced with SVG icons.** A single canonical inline-SVG icon set
  (`/icons.js`, `window.zingIcon`) renders every glyph — logo, nav (tools/history/watch),
  lock, status check/cross/info, arrows, carets, run/delete/etc. — as crisp,
  `currentColor` line icons across all pages, replacing the previous emoji.

## [0.10.0] — image/audio generation audits, embeddings/rerank in the web UI

### Added

- **Image & audio (TTS) generation audits (`zing image` / `zing audio`).** Two more
  non-chat surfaces. `image` (POST `/v1/images/generations`) checks the returned bytes
  are a valid, decodable image and that the **decoded dimensions match the requested
  size and the claimed model's native sizes** (a downscale/wrong-size is the headline
  货不对板 signal), plus distinctness (two prompts → different images, catching a fixed
  placeholder), count, and the echoed model. `audio` (POST `/v1/audio/speech`) checks
  the bytes are valid audio of the requested container, non-trivial (WAV duration > 0
  and scales with input length), format-honored, and distinct. All decoding is pure
  stdlib (PNG/JPEG/GIF/WebP header parsing; the `wave` module) — no Pillow/numpy. KB
  gained `image_sizes` / `audio_voices` and profiles for OpenAI DALL·E 2/3, gpt-image-1,
  tts-1/tts-1-hd/gpt-4o-mini-tts, plus Qwen image/TTS.
- **Embeddings & rerank in the web UI (`/tools`).** `zing serve` gains a 工具箱 / Tools
  page (linked from the nav) wrapping the existing embedding/rerank auditors: `POST
  /api/embed` and `POST /api/rerank`. Enter a relay + model and get a localized risk
  badge, score, and findings table; the dimension mismatch is surfaced as the headline
  signal (the expected dimension is resolved from the KB when left blank). Rerank uses a
  built-in known-answer probe by default, with an advanced panel for a custom query/docs.
  Keys stay local and are never echoed back to the browser. Verified live against Aliyun
  text-embedding-v4.

### Fixed

- **Flaky embedding test.** `tests/test_embed.py`'s mock seeded vectors with the builtin
  `hash()` (salted by `PYTHONHASHSEED`), so two distinct inputs could collide mod 1000
  and collapse the distinctness check, failing intermittently in CI. The mock now derives
  a process-stable key via `hashlib` and uses a per-input spike vector, so distinct
  inputs are reliably near-orthogonal — deterministic across all hash seeds.

## [0.9.0] — embedding/rerank audits, web-UI monitoring, CI Action

### Added

- **Embedding & rerank audits (`zing embed` / `zing rerank`).** A focused auditor for
  the non-chat surface, separate from the 9-dimension chat pipeline. `embed` checks
  connectivity, **dimension match** (returned vector length vs the claimed model's
  native dimension — the headline 货不对板 signal; e.g. a relay claiming 3072-d
  `text-embedding-3-large` but returning 1024-d is flagged HIGH), determinism (same
  input → cosine ≈ 1), distinctness (unrelated inputs → cosine well below 1), and the
  echoed `model` field. `rerank` runs a known-answer probe (the obviously-relevant
  document must rank first). Both support `--json` and `--fail-on-risk`. KB gained an
  `embedding_dimensions` field and profiles for OpenAI `text-embedding-3-small`/`-large`/
  `ada-002` and Qwen `text-embedding-v3`/`-v4`. Verified live against Aliyun
  text-embedding-v4 (honest → 100/100; sold as `-3-large` → HIGH dimension mismatch).
- **Monitoring in the web UI (`/watches`).** `zing serve` now has a built-in monitor:
  add a watch (target + suite + interval + alert threshold + webhook URLs) and an
  in-process background scheduler re-runs each enabled watch on its interval, persists
  every run to history, and POSTs a Chinese alert to your webhooks when risk crosses
  the threshold or regresses. Run-now / pause / delete from the page. API keys are
  stored only in `~/.zing` and never returned to the browser or shown in the listing.
  Vision findings are now localized to Chinese in the report.
- **GitHub CI Action.** A bundled composite action (`uses: cenbonew/zing@vX.Y.Z`) gates
  any workflow on a relay audit: runs `zing check --compact --fail-on-risk`, exposes
  `risk`/`score`/`rating` outputs, writes a run summary, and fails the job when the gate
  trips. The relay key is passed via a secret and never echoed. See `docs/CI.md` and the
  example workflow.

## [0.8.0] — Responses API, vision audit, monitoring

### Added

- **OpenAI Responses API (`/v1/responses`).** A third wire protocol behind the same
  detector interface: `--api responses` (auto-detected when the base_url path ends in
  `/responses`). Translates to/from `input`/`instructions`/`output` + `input_tokens`/
  `output_tokens` usage; handles streaming and tool calls.
- **Multimodal (vision) detector.** When a model claims vision, zing sends a
  known-answer generated image (a solid-color PNG built with the stdlib) and checks
  the model actually "sees" it — catching a relay that claims vision but routes to a
  text-only substitute. Builds the image part per protocol (OpenAI / Anthropic /
  Responses). Verified live against `qwen3-vl-plus`.
- **Monitoring: `zing watch` + webhook alerts.** Re-audits a relay on a schedule
  (`--interval`, or `--once` for cron), persists each run to history, compares against
  the previous run, and POSTs a concise alert to `--webhook` when risk crosses
  `--alert-on` or regresses. `zing/notify.py` formats alerts for Slack, Feishu (飞书),
  DingTalk (钉钉), or a generic JSON webhook (auto-detected from the URL).
- Web console now supports **compare against a baseline** (the form sends a baseline
  endpoint; the server runs `compare` mode for a corroborated verdict).

## [0.7.0] — web: Chinese findings, history/trends, advanced console

### Added

- **Findings localized to Chinese (web UI).** A new `zing/web/static/i18n.js` catalog
  maps every finding `id` (~65) to a zh title + a zh summary template filled from the
  finding's evidence (falling back to the English summary when a key is absent). The
  report and the live feed now show findings in Chinese.
- **Audit history & trends.** `zing serve` persists every audit to a local SQLite DB
  (`$ZING_DATA_DIR` or `~/.zing/history.db`, stdlib only — no new dep). New endpoints
  (`/api/history`, `/api/history/{id}`, `/api/history/trend`, DELETE) and a `/history`
  page that lists past audits grouped by target+model with a score sparkline; click a
  row to view that saved report. History never leaves your machine.
- **Advanced console view (`/console`).** A dark, power-user UI (ported from the
  console prototype) wired to the same live SSE: terminal-style detector log with
  click-to-expand evidence, dimension bars, and a verdict ring. Linked from the
  default report view; the report view links to history.

## [0.6.0] — web compare + live evidence

### Added

- **Web UI: `compare` against a trusted baseline.** The form has an optional baseline
  section (base_url / key / model / protocol); when filled, the audit runs in
  **compare** mode so the verdict gets baseline corroboration (quality_judge and
  integrity can escalate). The report shows the baseline and `mode: compare`.
- **Web UI: live evidence feed.** The scan now streams each detector's findings and
  evidence as it completes (the `detector_done` SSE event carries a compact, bounded
  findings list), so notable findings appear in real time — e.g. *"Self-identifies as
  a rival brand — self-id said: I'm Doubao, by ByteDance"* — instead of just status
  dots. `run_audit`'s `on_event` callback now includes per-detector findings.

## [0.5.0] — local web UI (`zing serve`)

### Added

- **`zing serve` — a local web UI.** A point-and-click front end for `zing check`:
  enter a relay + the model it claims, watch the audit stream **live** (a radar scan
  with per-detector progress over SSE), then get a shareable verdict report (grade,
  per-dimension breakdown, plain-language findings, downloadable JSON). Runs entirely
  on your machine — keys typed in the browser reach only your local server and the
  target relay, never a third party. New optional extra: `pip install 'zing-audit[web]'`
  (fastapi + uvicorn). `run_audit` gained an `on_event` progress callback that powers
  the live stream.

## [0.4.0] — agent/LLM ergonomics

Make zing pleasant to drive from another program or model.

### Added

- **`--compact`** (`check`/`compare`) — a lean, agent-facing JSON verdict on stdout:
  verdict + per-dimension status + a flat findings list, *without* the bulky
  per-finding evidence. ~66% smaller than `--json` (a standard report drops from
  ~5.2k to ~1.8k tokens).
- **`--dry-run`** (`check`/`compare`) — print the detectors that would run and an
  estimated API-call count (honoring `--reliability-requests`) **without making any
  requests**, so an agent can budget cost first. Each detector now carries a
  `cost_hint`.
- **`kb --json`** and **`models --json`** — machine-readable discovery of the bundled
  knowledge base and of an endpoint's advertised model list.
- **Structured errors in machine mode.** In `--json`/`--compact` mode a config/usage
  error now prints `{"error": {...}}` to stdout (exit 2) instead of a human message,
  so a pipeline can parse failures uniformly.
- Top-level `--help` now documents the agent flags.

## [0.3.0] — accuracy pass on real relays (DeepSeek / Doubao)

Validated against live endpoints (DeepSeek official + Aliyun, Volcengine, …): honest
DeepSeek relays now read CLEAN, and Doubao models passed off as DeepSeek are caught HIGH.

### Added

- **`--claimed-model`** — audit an endpoint's *real* model id against a *different*
  claimed model's profile (e.g. request `doubao-seed-...` but verify it against the
  `deepseek-v4-flash` profile). Lets you confirm a suspected substitution end-to-end.

### Fixed

- **Billing false positives on reasoning models / non-OpenAI tokenizers.** A reasoning
  model's `completion_tokens` legitimately includes hidden reasoning tokens the
  visible-text estimate can't see, and heuristic (non-tiktoken) estimates are
  imprecise — these no longer produce a "token inflation" HIGH. Prompt-token thresholds
  widen for heuristic tokenizers, and prompt-padding is still checked when a reasoning
  model returns empty visible content. (DeepSeek official went MEDIUM → CLEAN.)
- **Substitution false negatives.** Model-identity now flags ANY known vendor brand
  that isn't the model's own — including Doubao/ByteDance, Kimi, GLM, Hunyuan, Ernie,
  MiniMax (with Chinese names) — so a substitute the per-model KB list never enumerated
  is still caught. (A "I'm Doubao, by ByteDance" relay sold as DeepSeek now reads HIGH.)
- KB: added DeepSeek's native brand name (深度求索) to the deepseek profiles so a
  genuine model using it isn't mis-flagged.

## [0.2.1]

### Fixed

- `zing --version` now reports the actual installed version. It was hardcoded in
  `zing/__init__.py` and reported `0.1.0` for the 0.2.0 release; the version is now
  single-sourced from package metadata (`importlib.metadata`) so it can never drift
  from `pyproject.toml`.

## [0.2.0] — Anthropic support & roadmap security detectors

### Added

- **Anthropic Messages API support.** zing now audits Anthropic-native relays
  (`/v1/messages`) as well as OpenAI Chat Completions, behind one detector
  interface. The protocol is auto-detected from the base_url/model or forced with
  `--api openai|anthropic` (and `--target-api` / `--baseline-api` for `compare`).
- **Three new `deep`-suite security detectors** (formerly roadmap):
  - `injected_prompt` — detects a hidden, silently-prepended system prompt from a
    large *fixed* input-token overhead (measured across two message sizes) plus a
    leak probe; needs both signals to warn.
  - `integrity` — known-answer URL/package canaries catch in-flight response/tool-call
    tampering (value substituted, structure preserved). CRITICAL only when a trusted
    baseline returns the canary intact; otherwise MEDIUM.
  - `prompt_cache` — flags prompt-prefix caching by TTFT timing (informational; states
    that cross-user cache sharing is not provable from a single key).
- Automated PyPI publishing via GitHub Actions + Trusted Publishing
  (`.github/workflows/release.yml`); see `docs/PUBLISHING.md`.

## [0.1.0] — first public alpha

First public release. A local-first CLI that audits whether an OpenAI-compatible
API relay (中转站 / reseller / proxy) actually serves the model it claims to —
or quietly substitutes a cheaper one, truncates the context window, fakes
streaming, or inflates token billing (货不对板检测).

### Added

- `zing check` — audit one relay endpoint against what it claims (model id +
  optional provider hint).
- `zing compare` — audit a relay against a trusted baseline of the same declared
  model (the strongest downgrade evidence).
- `zing models` — probe an endpoint's `GET /v1/models` list.
- `zing kb` — inspect the bundled knowledge base.
- `zing init` — write a starter `zing.yaml` config.
- Eleven detectors across nine scored dimensions: model identity & downgrade
  fingerprinting, real context window & truncation, capability claims, token/usage
  billing, streaming authenticity, OpenAI-protocol conformance, determinism/cache
  correctness, concurrent reliability, transport/secret-handling security, plus
  connectivity and an optional LLM-judged quality assessment (`--judge`).
- Bundled knowledge base of **85 native model profiles across 7 platforms**
  (OpenAI, Anthropic, Google Gemini, DeepSeek, Qwen, GLM, Moonshot), editable as
  YAML and overridable via `--kb-dir` / `ZING_KB_DIR`.
- Two detection modes: pure-code deterministic probes (default) and a code+LLM
  hybrid that consults a separate trusted judge model.
- JSON, Markdown, and HTML reports; `--json` for machine/agent consumption.
- Evidence-first verdicts (CLEAN / LOW / MEDIUM / HIGH / INCONCLUSIVE) with
  confidence, designed to avoid false accusations of honest relays.
- Secret hygiene: API keys are fingerprinted (never stored) and relay-controlled
  text is redacted before it reaches any report (JSON/Markdown/HTML).
- `--fail-under` / `--fail-on-risk` exit-code gates for CI use.

[Unreleased]: https://github.com/mn567250/zing-audit/compare/7687cf6...HEAD
[0.17.1]: https://github.com/mn567250/zing-audit/pull/102
[0.17.0]: https://github.com/mn567250/zing-audit/pull/82
[0.16.11]: https://github.com/mn567250/zing-audit/pull/60
[0.16.10]: https://github.com/mn567250/zing-audit/pull/59
[0.16.9]: https://github.com/mn567250/zing-audit/pull/58
[0.16.8]: https://github.com/mn567250/zing-audit/pull/57
[0.16.7]: https://github.com/mn567250/zing-audit/pull/56
[0.16.6]: https://github.com/mn567250/zing-audit/pull/55
[0.16.5]: https://github.com/mn567250/zing-audit/pull/54
[0.16.4]: https://github.com/mn567250/zing-audit/pull/53
[0.16.3]: https://github.com/mn567250/zing-audit/pull/52
[0.16.2]: https://github.com/mn567250/zing-audit/pull/51
[0.16.1]: https://github.com/mn567250/zing-audit/pull/50
[0.16.0]: https://github.com/mn567250/zing-audit/pull/49
[0.15.22]: https://github.com/mn567250/zing-audit/pull/48
[0.15.21]: https://github.com/mn567250/zing-audit/pull/47
[0.15.20]: https://github.com/mn567250/zing-audit/pull/46
[0.15.19]: https://github.com/mn567250/zing-audit/pull/45
[0.15.18]: https://github.com/mn567250/zing-audit/pull/44
[0.15.17]: https://github.com/mn567250/zing-audit/pull/43
[0.15.16]: https://github.com/mn567250/zing-audit/pull/42
[0.15.15]: https://github.com/mn567250/zing-audit/pull/41
[0.15.14]: https://github.com/mn567250/zing-audit/pull/40
[0.15.13]: https://github.com/mn567250/zing-audit/pull/39
[0.15.12]: https://github.com/mn567250/zing-audit/pull/38
[0.15.11]: https://github.com/mn567250/zing-audit/pull/37
[0.15.10]: https://github.com/mn567250/zing-audit/pull/36
[0.15.9]: https://github.com/mn567250/zing-audit/pull/34
[0.15.8]: https://github.com/mn567250/zing-audit/pull/35
[0.15.7]: https://github.com/mn567250/zing-audit/pull/32
[0.15.6]: https://github.com/mn567250/zing-audit/pull/33
[0.15.5]: https://github.com/mn567250/zing-audit/pull/31
[0.15.4]: https://github.com/mn567250/zing-audit/pull/30
[0.15.3]: https://github.com/mn567250/zing-audit/pull/29
[0.15.2]: https://github.com/mn567250/zing-audit/pull/28
[0.15.1]: https://github.com/mn567250/zing-audit/pull/27
[0.15.0]: https://github.com/mn567250/zing-audit/pull/26
[0.14.9]: https://github.com/mn567250/zing-audit/pull/25
[0.14.8]: https://github.com/mn567250/zing-audit/pull/24
[0.14.7]: https://github.com/mn567250/zing-audit/pull/23
[0.14.6]: https://github.com/mn567250/zing-audit/pull/22
[0.14.5]: https://github.com/mn567250/zing-audit/pull/21
[0.14.4]: https://github.com/mn567250/zing-audit/pull/20
[0.14.3]: https://github.com/mn567250/zing-audit/pull/19
[0.14.2]: https://github.com/mn567250/zing-audit/pull/18
[0.14.1]: https://github.com/mn567250/zing-audit/pull/17
[0.14.0]: https://github.com/mn567250/zing-audit/pull/16
[0.13.3]: https://github.com/mn567250/zing-audit/pull/6
[0.13.2]: https://github.com/mn567250/zing-audit/pull/5
[0.13.1]: https://github.com/mn567250/zing-audit/pull/4
[0.13.0]: https://github.com/mn567250/zing-audit/pull/3
[0.12.1]: https://github.com/mn567250/zing-audit/pull/2
[0.12.0]: https://github.com/mn567250/zing-audit/pull/1
[0.11.0]: https://github.com/cenbonew/zing/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/cenbonew/zing/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/cenbonew/zing/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/cenbonew/zing/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/cenbonew/zing/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/cenbonew/zing/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/cenbonew/zing/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/cenbonew/zing/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/cenbonew/zing/compare/v0.2.1...v0.3.0
[0.2.1]: https://github.com/cenbonew/zing/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/cenbonew/zing/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/cenbonew/zing/releases/tag/v0.1.0
