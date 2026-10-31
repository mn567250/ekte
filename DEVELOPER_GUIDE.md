# ekte — Developer guide

> **🇬🇧 English** · [🇨🇳 中文](DEVELOPER_GUIDE.zh-CN.md) · [🇫🇷 Français](DEVELOPER_GUIDE.fr.md) · [🇪🇸 Español](DEVELOPER_GUIDE.es.md) · [🇵🇹 Português](DEVELOPER_GUIDE.pt.md) · [🇮🇹 Italiano](DEVELOPER_GUIDE.it.md) · [🇩🇪 Deutsch](DEVELOPER_GUIDE.de.md) · [🇳🇴 Norsk](DEVELOPER_GUIDE.nb.md)

This guide is for people who change ekte: how it is built, how to set up a
development environment, how to contribute, and how it is packaged, run in
Docker and released. What ekte does and how to use it is in the
[README](README.md); how every check works and is scored is in the
[Methodology](docs/METHODOLOGY.md).

---

## Contents

- [Principles](#principles)
- [Development setup](#development-setup)
- [Repository layout](#repository-layout)
- [Architecture](#architecture)
  - [Audit pipeline](#audit-pipeline)
  - [Clients](#clients)
  - [Detectors and scoring scales](#detectors-and-scoring-scales)
  - [Scoring and verdict](#scoring-and-verdict)
  - [Knowledge base](#knowledge-base)
  - [Prompt library](#prompt-library)
  - [Reports](#reports)
  - [Surfaces](#surfaces)
  - [Standalone auditors](#standalone-auditors)
  - [Web server](#web-server)
  - [Web front end](#web-front-end)
  - [Local data](#local-data)
- [Contributing](#contributing)
  - [Pull requests](#pull-requests)
  - [Adding a detector](#adding-a-detector)
  - [Editing the knowledge base](#editing-the-knowledge-base)
  - [Changing probe prompts](#changing-probe-prompts)
  - [Translations](#translations)
  - [Documentation](#documentation)
- [Testing](#testing)
- [Docker](#docker)
- [Continuous integration](#continuous-integration)
- [Releases](#releases)
- [Security](#security)
- [License](#license)

## Principles

ekte is a black-box auditing aid: correctness and **not falsely accusing honest
relays** matter more than catching every possible trick. Keep that bar in mind
for any change.

- **Evidence over accusation.** Findings report *divergence and risk*, never
  "fraud". Prefer *inconclusive* to a guess. A new HIGH-severity path needs hard,
  reproducible evidence and must be hard to trip on an honest endpoint.
- **No network in tests.** Detector tests run against the in-process mock server
  in `tests/conftest.py` (httpx `MockTransport`), never a live API.
- **Secrets never leave.** API keys are fingerprinted, never stored in reports.
  Any new output path must route relay-controlled text through
  `ekte.utils.redact` and escape it for its format.
- **Same probes for everyone.** Probe texts are English and fixed, whatever the
  UI language, so the same relay gets the same verdict (see
  [Prompt library](#prompt-library)).
- **Local only.** ekte contacts only the endpoints the user configures, and the
  web UI only listens on loopback (see [Web server](#web-server)).

## Development setup

Requires Python 3.11+. Node.js is optional: the tests of the browser JavaScript
run under `node` and are skipped without it.

```bash
git clone https://github.com/mn567250/ekte
cd ekte
pip install -e '.[dev,web]'   # editable install with the dev tools and the web UI
pytest                        # test suite
ruff check ekte tests         # lint
mypy ekte                     # type-check
```

With uv: `uv venv && uv pip install -e '.[dev,web]'`. No system
libraries are needed, PDF reports included.

Run from source with `ekte …` or `python -m ekte …`. `ekte serve` serves the
web UI from `ekte/web/static/` directly, so a browser reload picks up front-end
changes; there is no build step.

## Repository layout

```text
ekte/
  cli.py               Typer CLI: check, compare, models, kb*, serve, watch, embed, rerank, image, audio
  config.py            YAML config, secret references (env:/file:), AuditOptions
  runner.py            run_audit(): wires everything up and runs the detectors
  context.py           AuditContext handed to every detector
  models.py            pydantic data contracts: TargetConfig, Finding, DetectorResult, AuditReport, …
  scoring.py           dimension scores, weights, overall score, risk verdict, confidence
  clients/             HTTP clients: OpenAI-compatible, Anthropic Messages, OpenAI Responses
  detectors/           one file per detector, plus base.py (registry), scale.py, helpers.py
  judge/               the trusted LLM judge used by quality_judge
  knowledge/           KB schema, loader, user store (kb.db), importer, research prompt, snapshots
    data/              packaged provider profiles (*.yaml)
  prompts/en.json      every text ekte sends to an LLM API
  perf/                per-request recorder and the report's performance section
  report/              JSON / Markdown / HTML / PDF renderers and the writer
  embed_audit.py       standalone embedding and rerank auditor
  media_audit.py       standalone image and audio (TTS) auditor
  notify.py            webhook alerts (Slack / Feishu / DingTalk / generic JSON)
  datadir.py           the local data directory and its SQLite files
  legacy.py            the ZING_* settings and the ~/.zing copy from before the rename
  secretbox.py         encryption of stored secrets; the master key held in memory
  i18n/                translations shared by the web UI and the alerts
    locales/           <code>.json per language, fragments/<feature>/<code>.json
  utils/               redaction, SSE parsing, statistics, token estimation
  web/
    server.py          FastAPI app: pages, JSON API, SSE audit stream, monitor scheduler
    jobs.py            background audit jobs and the per-relay gate
    security.py        loopback bind, Host allowlist, Origin/JSON checks, headers
    history.py         audit history store (history.db)
    analytics_store.py its analytics tables: per-run metrics, request records
    analytics.py       analytics queries: KPIs, time series, leaderboards
    watches.py         monitor store (watches.db)
    masterkey.py       the master key's states and actions (server and `ekte secret`)
    static/            scripts shared by every page (lang.js, i18n.js, icons.js, …)
    static/v2/         the web UI's pages, styles and scripts
tests/                 pytest suite; conftest.py holds the mock relay
docs/                  METHODOLOGY (8 languages), CI.md, DOCKER.md, PUBLISHING.md
examples/ekte.yaml     annotated config file
action.yml             the GitHub composite action
Dockerfile             web UI image
```

## Architecture

### Audit pipeline

`ekte check`, `ekte compare`, `ekte watch`, the web UI's audit stream and its
monitor scheduler all end in the same function, `ekte.runner.run_audit()`:

1. **Configuration.** `ekte/config.py` merges the YAML config with command-line
   options into `TargetConfig` (target, optional baseline and judge) and
   `AuditOptions` (suite, dimensions, probe sizes, output). API keys given as
   `env:VAR` or `file:/path` are resolved here.
2. **Knowledge base.** `load_knowledge_base()` loads the packaged profiles,
   `--kb-dir`/`EKTE_KB_DIR` and the user's `kb.db`, and resolves the **claimed**
   model (defaulting to the requested one) to a profile. A monitor passes its
   pinned snapshot instead.
3. **Clients.** `make_client()` creates a client for the target (and baseline)
   for the chosen or auto-detected protocol. A `RequestRecorder` wraps every call
   for the performance section.
4. **Detectors.** `select_detectors()` picks the registered detectors for the
   suite (or the custom dimensions), dropping those that need a judge or a
   baseline that is missing. They run **sequentially**, on purpose: concurrent
   requests would trip rate limits and confound the timing measurements (the
   reliability and performance probes manage their own bounded concurrency).
   `run_detector()` times each one and turns a crash into a result with status
   **Error**, so one misbehaving relay response never aborts the audit.
5. **Scoring.** `scoring.build_dimensions()` and `build_verdict()` turn the
   detector results into dimension scores, the overall score and rating, the risk
   verdict and its confidence.
6. **Report.** Everything lands in an `AuditReport` (`ekte/models.py`) with the
   redacted target, the knowledge-base profile snapshot, the performance section
   and the probe languages. The CLI renders and writes it; the web UI streams it.

`run_audit()` takes an `on_event` callback; the web server turns its events
(detector started/finished with compact findings, batched per-request timings)
into Server-Sent Events for the live view.

### Clients

`ekte/clients/` has one client per wire protocol — `openai_compatible.py`
(Chat Completions), `anthropic.py` (Messages) and `responses.py` (Responses) —
with the same interface, built on shared HTTP machinery in `base.py`.
`make_client()` in `clients/__init__.py` chooses one from `--api` or detects it
from the base URL and model. Detectors only speak to this interface
(`RequestSpec` in, `CompletionOutcome` out), so they are protocol-agnostic.

The clients also adapt requests to what the model accepts (`base.py`): the
runner seeds `unsupported_params` from the profile, sampling parameters listed
there are left out, and on Chat Completions a listed `max_tokens` sends the
limit as `max_completion_tokens`. A 4xx that names such a parameter adds it to
the set and repeats the request once adapted (the rejected attempt is recorded
with phase `param_retry`). A probe that judges the raw rejection sets
`RequestSpec.exact_params`.

### Detectors and scoring scales

A detector is one self-contained file in `ekte/detectors/`: a subclass of
`Detector` (`base.py`) with an `id`, a `name`, a `dimension`, the first suite it
runs in (`min_suite`), an approximate `cost_hint` for `--dry-run`, and
`async def run(self, ctx) -> DetectorResult`. `@register` adds it to the
registry; `ekte/detectors/__init__.py` imports every module so the registry is
complete.

Each detector publishes its **scoring scale** (`SCALE`, built with `scale.py`):
every possible outcome of each check with its points, status and severity.
Findings are created from the scale (`SCALE.finding(check, outcome, …)`), so the
report and the behavior cannot disagree. `Scale` scores the mean of its checks;
`DeductionScale` starts at 100 and deducts or caps. The web UI shows the scale
under **Scoring scale**; the [Methodology](docs/METHODOLOGY.md) reproduces every
scale. `connectivity.py` is the canonical, shortest example.

Detectors share one event loop with every other audit in `ekte serve`, so
CPU-heavy work must not run on it: a stalled loop delays other audits' requests
and inflates the latencies they record. `helpers.build_filler()` builds filler
text in linear time and memoizes the last few sizes, and the context-window and
prompt-cache detectors call it (and `build_haystack()`) through
`asyncio.to_thread`. Token counts come from `ekte/utils/tokenize.py`, a
standard-library heuristic: ekte imports no tokenizer library and downloads
nothing at runtime, so it works in restricted environments. The `tokenizer`
argument of `estimate_tokens()` is accepted but does not change the count, and
the report fields `tokens_exact` / `exact_tokenizer` are kept for compatibility
and always false.

### Scoring and verdict

`ekte/scoring.py` holds `DIMENSION_WEIGHTS` and the verdict rules: a dimension
score is the equal-weight mean of its detectors, the overall score the weighted
mean of the dimensions that ran, and the risk level follows the severity ladder
described in [Methodology → How ekte scores](docs/METHODOLOGY.md#how-ekte-scores).
Each dimension records how it was computed in `DimensionScore.breakdown`, which
feeds **Dimension details** in the reports and the expandable rows of
**Per-dimension checks** in the web UI.

### Knowledge base

`ekte/knowledge/` defines the profile schema (`schema.py`: `ProviderProfile`,
`ModelProfile`, `FingerprintProbe`), loads and merges the layers
(`loader.py`: packaged YAML → `EKTE_KB_DIR`/`--kb-dir` → the user's `kb.db`),
stores the user's entries (`store.py`), checks and imports YAML
(`importer.py`), builds the research prompt for external assistants
(`research.py`) and snapshots the profile a run used (`snapshot.py`). Model ids
resolve exactly, through aliases or by normalized name, narrowed by the declared
provider. The fuzzy fallback takes the longest KB name the claim contains (a
snapshot or decorated id) unless the rest of the claim names another tier or
variant (`-mini`, `-lite`, `-image`, …); a truncated claim resolves only when a
single model's name starts with it, so an ambiguous id such as `gpt-4`
resolves to no profile rather than to a guessed tier. Every report records how
the id matched.

`load_knowledge_base()` caches merged results and returns a deep copy by
default, so callers may modify what they get. Callers that only read it (the web
UI's lists and catalog, resolving a model) pass `copy=False` and get the shared
cached instance, which they must not modify.

Relays are endpoints too: `relays.py` turns a provider's `base_url_hints` into
usable base URLs (`GET /api/kb` → `base_urls`) and saves a relay from the web UI
as a provider entry in `kb.db` (`origin = relay`: a `display_name` and one base
URL, no models; no schema change).

### Prompt library

Every text ekte sends to an LLM API — chat probes, the judge's prompt, tool
schemas, embedding / rerank / image / audio inputs — lives in
`ekte/prompts/en.json` and is read with `ekte.prompts.text()` / `get()`.
`{{name}}` marks a value filled in at run time. The probe language is fixed to
English (`PROBE_LANG`), independent of the UI language, because answer checks and
token estimates are calibrated to these exact texts. Probes whose language *is*
the measurement (e.g. Chinese fluency, tokenizer or self-identification of
China-native models) live with their expected answers in the knowledge base and
declare `prompt_lang` and a `language_bound` reason. The runner records the
languages used in `prompt_languages`.

### Reports

`ekte/report/render.py` renders an `AuditReport` to JSON, the compact agent JSON,
Markdown and HTML; `dimensions.py` and `performance.py` render the
**Dimension details** and the performance section; `pdf.py` typesets the PDF
with ReportLab from the same data and helpers (pure Python; only the standard PDF
fonts, with the CID font STSong-Light for Chinese, so nothing is embedded; never
loading external resources), and the CLI and the web UI share it;
`writer.py` writes the files. All relay-controlled text is redacted and escaped
(HTML / Markdown) before output. The web UI's `POST /api/report/export` reuses
these renderers for its **Download report** row, with the human-readable text
translated to the UI language.

### Surfaces

The **surface** is the kind of endpoint audited: `chat` (default),
`embedding` or `rerank` (`ekte.config.SURFACES`; later image, TTS). It is a second
axis next to the suite, carried by `AuditOptions.surface`, `AuditReport.surface`
and a nullable `surface` column in `history.db` and `watches.db` (`NULL` and a
missing JSON field mean `chat`; no migration).

- Detectors declare `surface: ClassVar[str]`; `select_detectors` filters by it
  before the suite tier. The embedding and rerank detectors reuse the existing
  dimensions.
- Scoring weights and the profile / core / infra dimension sets are per surface
  (`scoring.SURFACE_WEIGHTS`); chat keeps its values.
- The recorder tags embedding calls `op="embed"` and rerank calls
  `op="rerank"` (`ekte.config.SURFACE_OPS`); `perf/summary.py` functions take
  an `op` parameter (default `complete`).
- `embed_audit.run_embedding_audit()` and `run_rerank_audit()` (used by
  `ekte embed` / `ekte rerank` and `/api/embed` / `/api/rerank`) run the runner
  with `surface="embedding"` or `"rerank"`, pass the previous saved run of the
  same surface as `previous_report` (drift) and save the report unless told
  not to (`--no-save`).
- Rerank detectors: `rerank.connectivity`, `rerank.known_answer` (CAPABILITY),
  `rerank.identity` and `rerank.drift` (MODEL_IDENTITY), `rerank.determinism`
  (RELIABILITY) and `performance.rerank`. Weights: MODEL_IDENTITY 30,
  CAPABILITY 30, PERFORMANCE 20, RELIABILITY 10, CONNECTIVITY 10.
- Monitors: a watch's `surface` and `embedding_dimensions` (0 = from the KB)
  feed `AuditOptions` in `_run_one_watch_inner`; an embedding or rerank watch
  reads its drift reference with `history.latest_for(..., surface=...)` before
  the audit and compares alerts only with runs of the same surface. The surface
  is set at creation (`POST /api/watches`, `/api/watches/from-history/{id}`,
  which also takes `embedding_dimensions`) and cannot be changed by `PATCH`;
  `PATCH` changes an embedding watch's `embedding_dimensions` (the v2 Monitors
  card edits it inline).

### Standalone auditors

Image/audio (`media_audit.py`) are not surfaces yet, so they have their own
small auditors with their own verdict
dict instead of the detector pipeline. They share the clients' HTTP settings, the
knowledge base (native dimensions, image sizes, voices) and the prompt library.
All decoding (image headers, WAV) is standard library only.

### Web server

`ekte/web/server.py` is a FastAPI app created by `create_app()`:

- **Pages.** The web UI (`/v2/`, `/v2/history`, `/v2/watches`, `/v2/analytics`,
  `/v2/kb`, `/v2/accessibility`) is static HTML. There is no Tools page:
  embedding and rerank audits start on the audit page through the endpoint-type
  selector (`/v2/?surface=embedding|rerank`), and `/v2/tools` serves a small page
  that forwards old links there (`#rerank` picks rerank, `?rerun=` is passed on).
  The addresses of the removed classic UI (`/`, `/history`, `/watches`, `/tools`,
  `/console`) redirect (308) to their v2 pages, keeping the query string.
- **API.** `/api/jobs…` runs audits (below); `/api/models` lists a relay's
  models; `/api/report/export` renders a report; `/api/history…`,
  `/api/watches…`, `/api/kb…` and `/api/analytics…` back the other pages.
  `/api/audit/stream` (one audit streamed over SSE), `/api/embed` and
  `/api/rerank` (one synchronous embedding / rerank audit) are no longer used by
  the web UI; their future is tracked in issues #3 and #4.
- **Relays.** `POST /api/kb/relays` saves a relay `{name, base_url}` (400 for bad
  input, 409 when the name or URL is already known).
- **Analytics.** `GET /api/analytics/options` (relays, models, suites, stream
  modes, APIs and the date range in the history), `/api/analytics/summary`
  (KPIs of `from`–`to` against the previous range of the same length),
  `/api/analytics/series` (`metric` per `group=relay|model|relay_model`, up to
  4 `keys`, in `bucket=hour|day|week|dow_hour` buckets of the viewer's `tz` or
  `tz_offset`; `dow_hour` also takes `block` (hours per row) and
  `fold=week|4weeks|month_week`, which falls back to `week` until the runs cover
  90 or 180 days) and `/api/analytics/leaderboard` (`model=` for its relays, or
  `relay=` for its models). All take the filters `from`, `to`, `suite`,
  `stream_mode`, `api`, `source=all|manual|monitor`, `relay` and `model`.
  `ekte/web/analytics.py` computes everything in Python from
  `history.analytics_runs()`: metric ids come from a fixed whitelist, relays are
  grouped by knowledge-base entry when the query runs, a value a run did not
  measure is left out (each value has its `n` and `coverage`), and buckets with
  fewer than `MIN_RUNS` (3) runs are flagged `low_n`. A bad parameter answers
  400; responses are `Cache-Control: no-store`.
- **Analytics panels.** `/api/analytics/breakdown` (up to 8 `metrics` per
  `group=relay|model|relay_model|all` over the range), `/api/analytics/errors`
  (the target's completion calls by outcome class
  `success|client_4xx|rate_limited|server_5xx|timeout|network|other`, per
  `group=relay|model` and per `bucket`, counted in SQL by
  `history.analytics_request_classes()` without loading request rows; a call's
  time is its run's start plus its offset, to the minute; `covered` = runs that
  have request records) and `/api/analytics/integrity` (pass / warn / fail
  counts of the identity, capability, vision, streaming, protocol, integrity,
  injected-prompt and connectivity detectors per relay × model, the
  model-mismatch share and the median effective / declared context window).
  `/api/analytics/series` also takes `group=all`. Same filters and errors as
  above.
- **Background audits.** `jobs.py` runs every audit as a job owned by the
  server. `POST /api/jobs` queues one, `GET /api/jobs` lists queued, running and
  recently finished jobs (plus running monitors) with progress,
  `GET /api/jobs/{id}/events` replays the job's event log and then follows it
  live over SSE, and `POST /api/jobs/{id}/cancel` stops it. The web UI uses
  these, so an audit outlives the page; `/api/audit/stream` wraps
  the same job and cancels it when the stream closes. A relay gate lets one
  audit (or monitor run) at a time use a relay, keyed by host name with every
  loopback address as one host, and at most `EKTE_MAX_PARALLEL_AUDITS`
  (default 4) run at once; waiters are served in arrival order.
- **Monitor scheduler.** The app's lifespan starts a background loop that
  starts every due monitor as its own task, so monitors on different relays
  audit at the same time; the relay gate still applies, so monitors can fill
  the `EKTE_MAX_PARALLEL_AUDITS` slots and a manual audit may queue behind
  them. A run's `last_run_ts` is the moment its audit starts (after waiting for
  its relay). Each run is stored in the history; the regression check compares
  it with the most recent saved run of the same target and model
  (`history.latest_for()`, one indexed lookup) and sends the webhook alerts
  (`ekte/notify.py`) concurrently on a threshold cross or a regression.
  `POST /api/watches/{id}/run` answers 409 while the scheduler has just started
  that monitor; a master-key reset cancels scheduled runs that have not started
  yet, and shutdown cancels the runs in flight.
- **Compression and caching.** `caching.py` gzips responses of 1 KiB or more
  (except Server-Sent Events) for clients that accept it (`gzip;q=0` refuses).
  Pages and `/locales.js` are gzipped once when they are built and served
  precompressed with `Content-Encoding: gzip`, `Vary: Accept-Encoding` and a
  separate ETag ending in `-gz`; pages are served through `html_page(page,
  request.scope)` so they get that path and answer conditional requests with
  304. Local script and stylesheet URLs in pages carry a `?v=<content hash>` and
  are cached as immutable.
- **Security.** `security.py` resolves the bind address (loopback only, except
  in a detected container with `EKTE_CONTAINER=1`) and installs
  `LocalOnlyMiddleware`: a Host allowlist against DNS rebinding, Origin and
  `Sec-Fetch-Site` checks against CSRF, JSON-only request bodies, and
  anti-framing / no-sniff / no-referrer headers. The UI has no login by design.

### Web front end

The front end is plain HTML, CSS and browser JavaScript without modules or a
build step. The pages live in `ekte/web/static/v2/` and share one header (`nav.js`), the report renderer
(`report.js`), the theme switch (`theme.js`) and the styles (`tokens.css`, `ekte.css`,
`fields.css`, `report.css`, `perf.css`). Shared scripts are served from the root:
`lang.js` (language switch), `locales.js` (translation data), `i18n.js` (finding
translations), `icons.js` (including the ekte logo), `secretfield.js` and
`perf.js` (performance charts).
Every colour of the v2 UI, in both themes, is a token in `v2/tokens.css`
(written once as `light-dark(<light>, <dark>)`); all other v2 styles, pages and
scripts use `var(--…)` only, never a literal colour.

Every v2 page but Accessibility has one **page notice** right under its hero
(`<div class="znote" id="note">`, drawn by `v2/notice.js`, styled by `.znote`
in `ekte.css`): `EkteNotice.show(el, {level, title, detail, items, actions})`
with the level `info`, `success`, `warning` or `critical` setting tint, border
and icon (critical is `role="alert"`, the others `role="status"`; showing the
same notice again changes nothing). The page picks the most important message
and lists the others in `items`. Audit: server unreachable / audits running /
the newest saved run / runs locally; History: history unreadable / monitor
runs paused (master key locked) or older runs still processed / run count;
Analytics: data unreadable / runs not yet in the charts or with an estimated
start time / what it is based on; Knowledge: load failure / skipped or
ignored entries / switched-off items / complete. Monitors keeps its master-key
bar (`masterkey.js`), which looks and sits the same. The history-wide numbers
come from `GET /api/history/status` (`history.status()`: run count, oldest and
newest run, rows the analytics backfill has not processed,
runs with an estimated start time).

The v2 **Audit** page configures relays with `v2/relaycfg.js`:
relay/provider select → base URL → the relay's models (`/api/models`, on change,
cached per URL/key/protocol) → claimed model from the knowledge base
(`/api/kb/resolve` preselects it) → derived declared provider, plus **Save to
knowledge base** (`POST /api/kb/relays`). Its pure helpers are tested under node.

The v2 **Analytics** page (`v2/analytics.html`) reads only `/api/analytics/*`
(`options` also lists the relay × model pairs, `relay_models`, for its series
picker). It has one `<section class="card panel">` per panel under one filter
bar, so new panels slot in; filters and view live in the URL fragment
(`#range=30&metric=score&…`) and in `localStorage`. Its charts come from
`v2/charts.js` (`EkteCharts.timeChart`: hand-drawn inline SVG with median line,
p25–p75 band, gaps for empty buckets, faded markers for `low_n` buckets,
annotation lines and a hover tooltip; `fmt` / `fmtDelta` format values by unit)
and `v2/charts.css` (four validated series colours per theme, told apart by
marker shape too). Every chart is also rendered as a data table.

Each panel is self-contained: a `PANELS` registry in the page script lists its
section id, `load()` (fetch with the current filters and view, then render) and
`render()` (redraw from the loaded data, e.g. on a language switch), so panels
can be rearranged without touching each other. `EkteCharts.heatmap` draws the
weekday × hour grid (five-step one-hue sequential scale per theme, hatched cells
for `low_n`, outlined empty cells), `EkteCharts.stackBars` the stacked error
bars, and `timeChart` takes a `ref` line (100% billing ratio).
`EkteCharts.donut` (a ring of parts of one whole with an HTML figure in the
middle) and `EkteCharts.meter` (a thin bar of parts) draw the Coverage card of
the accessibility report; their `k-*` colours (who decides a step: blue the
test suite, violet a person) come from `tokens.css`. `v2/chartmotion.js`
(`EkteMotion.enter`) draws a donut clockwise and grows meters from the left,
like every other chart, only when new data arrives and never under reduced
motion or the header's "Motion off".

The page header and the filter panel sit above five in-page tabs
(`v2/tabs.js`, as on Knowledge): each `PANELS` entry names its `tab`,
and only the shown tab's panels load; a filter change reloads that tab and
marks the others stale (`activate()` loads them when shown). `tabs.js` takes
`writeHash: false` here, because the page writes the whole view into the
fragment itself — `#tab=trends&range=30&suite=…&metric=…` (`stateQuery()`),
which **Copy link to this view** copies (a selected read-only field where the
clipboard API is missing or refuses); a fragment without `tab` opens Overview,
and a pasted link (`hashchange`) re-reads the view. The collapsible filter
panel is `v2/filterpanel.js` + `v2/filterpanel.css`, shared with History, Monitors and Knowledge:
`EkteFilterPanel.create(section, {label, title, storeKey, open, onReset})`
returns `render({body, foot, count, summary})`, `sync({count, summary})`,
`setOpen()` and `focusStart()`; the page owns its filters and fields, the panel
the toggle with its active-filter badge, the one-line summary shown while
closed, the remembered open state and **Reset filters**.

**Translation convention.** The Chinese text written in the HTML is the
original and stays untouched; every element carries its English text in
`data-en` (and `data-en-placeholder`, `data-en-title`, `data-en-aria-label`).
The English text is the lookup key for every other language. Scripts use
`T(zh, en)` for dynamic text and `EKTE_LANG.server(text)` for text coming from
the backend (detector names, recommendations, verdict sentences).

### Local data

`ekte/datadir.py` owns `$EKTE_DATA_DIR` (default `~/.ekte`), created `0700`,
with `0600` SQLite files: `history.db` (`web/history.py`), `watches.db`
(`web/watches.py`; the monitors' API keys only if the user chose to store
them, encrypted) and `kb.db` (`knowledge/store.py`). Each call opens a short-lived connection, so the stores
are safe on FastAPI's thread pool. The global `--data-dir` option (also on
`ekte serve`) just sets `EKTE_DATA_DIR` to the absolute path, and
`ekte data-dir` prints the resolved directory. A directory that already exists
keeps its mode; only the default `~/.ekte` is tightened to `0700`. History rows
are indexed by target and model (`idx_history_target`), which
`history.latest_for()` uses to find a monitor's previous run.

Since schema version 2 (`PRAGMA user_version`) `history.db` also holds the
analytics tables, defined in `web/analytics_store.py`: `history_metrics` (one
row of extracted metrics per run: start time, rates, latency/TTFT/decode
percentiles, billing ratios, finding counts and more; NULL where the run did
not measure a value), `history_dimensions` (dimension and detector scores) and
`history_requests` (the run's request records, target and baseline, in list
order). A report's `performance.requests` are kept only there: `save()` takes
them out of `report_json` (`requests_split` marks the row) and `get()` /
`latest_for()` put them back, so a report reads back identical to the one
saved; whatever the columns cannot reproduce exactly goes into the JSON column
`extra`. `extract_metrics()` is pure and versioned (`EXTRACT_VERSION`). After
the migration a batched backfill (one short transaction per batch, idempotent)
moves older rows' records and extracts their metrics, and re-extracts rows
written by an older `EXTRACT_VERSION`; `history.backfill_analytics()` runs it
again on demand. A run's start time is the report's `started_at`; reports from
before that field get `generated_at` minus the span of their request records
(`started_at_estimated` = 1).

Where the monitors' API keys are kept is the user's choice
(`watches.get_key_storage()`, a `secret_meta` row): `memory`, the default, stores
none — the `api_key` column holds the marker `mem:` and the key lives in
`watches._memory_keys` until the process stops (a restart leaves the row
`key_missing`, which the scheduler treats like a locked key: the run waits, no
alert); `encrypted` stores them as below. With no row yet, a store that already
has encrypted keys or a check value, or a set `EKTE_SECRET_KEY` / legacy
`secret.key`, starts in `encrypted`; the choice is recorded at startup.
`Vault.set_storage()` (`POST /api/secret/storage`) switches and moves the keys
in one transaction (`keys_to_memory()` erases the encrypted ones and the check
value and scrubs the file; `keys_to_store()` seals the held ones). A request
can pass `key_storage: "memory"` to keep its key out of the database whatever
the setting; nothing can force storage.

Stored API keys are encrypted by `ekte/secretbox.py` (Fernet, stored as
`enc:v1:…`; `env:`/`file:` references stay as they are). The master key itself
is never stored: `web/masterkey.py` (`Vault`, shared by the server and
`ekte secret`) holds it in the server's memory once it comes from
`EKTE_SECRET_KEY`, a legacy `secret.key` or the user on the Monitors page, and
`watches.db` keeps only a check value (`secret_meta`) that rejects a wrong key.
A new key re-encrypts every stored key and rewrites the check value in one
transaction. The key lives in one process's memory, so run one server per data
directory.

`ekte/legacy.py` keeps installs from before the rename working: every `EKTE_*`
setting is read through `legacy.getenv`, which falls back to the old `ZING_*`
name (noticed once on stderr), and `datadir.data_dir()` copies `~/.zing` to
`~/.ekte` once when only the old directory exists (SQLite files through the
backup API, into a temporary sibling renamed into place). `~/.zing` is never
changed or deleted. `lang.js` copies the browser's `zing.*` settings to `ekte.*`
the same way, and the server still reads the `zing_lang` / `zing_ui` cookies
until the `ekte_*` ones exist.

## Contributing

### Pull requests

- Keep `pytest`, `ruff check ekte tests` and `mypy ekte` green (CI runs all three
  on Python 3.11–3.14).
- Describe the relay trick or the false positive a change addresses.
- Update `CHANGELOG.md` under `[Unreleased]`.
- Update the documentation the change touches — README, this guide, the
  Methodology — in **every language** (see [Documentation](#documentation)).

By contributing you agree that your contributions are licensed under the
project's [Apache-2.0](LICENSE) license.

### Adding a detector

1. Create `ekte/detectors/<name>.py` and import it in
   `ekte/detectors/__init__.py`.
2. Define its `SCALE` (`Scale` or `DeductionScale` from `scale.py`) with every
   outcome of every check, and create findings only through it.
3. Subclass `Detector`; set `id`, `name`, `dimension`, `min_suite` and
   `cost_hint`; set `requires_judge = True` or `requires_baseline = True` if it
   needs one, or override `applies()` for other gating. Decorate it with
   `@register`.
4. Implement `async def run(self, ctx) -> DetectorResult`, starting from
   `self.new_result(scoring=SCALE.scoring())`. Send requests through `ctx.client`
   and take every prompt from `ekte/prompts/en.json`.
5. Add behavioral tests for both the flagged and the clean path, using the mock
   relay in `tests/conftest.py`.
6. Translate new finding titles and summaries (see [Translations](#translations))
   and document the detector and its scale in every
   [Methodology](docs/METHODOLOGY.md) file.

### Editing the knowledge base

Profiles live in `ekte/knowledge/data/<provider>.yaml`, one file per provider.
Each model carries its native context window, max output, knowledge cutoff,
tokenizer, modalities, capability flags, unsupported parameters, identity
keywords and fingerprints (see `ekte/knowledge/schema.py`). When you change a
numeric field, **cite an authoritative source** (the provider's official model
card, pricing or docs) in the pull request: a wrong value causes false positives
against honest relays. `ekte kb-import --check <file>` runs the same checks as
the user import (schema, limits, unsafe regular expressions, prompts, id
collisions).

Provider-level `fingerprints` run on every model of the provider. A probe whose
expectation holds only for some models (a knowledge cutoff, a Pro-tier recall
check, a reasoning trap) belongs in those models' own `fingerprints`, or a
truthful answer from another model counts as a divergence.

Always fill `identity_keywords` with the vendor and model-family words the
model uses for itself. The identity check also counts the provider key, the
display name and the model id as the genuine brand, widened to the vendor's
other names in `VENDOR_BRANDS` (`ekte/knowledge/identity.py`, which is also the
detector's rival-brand list); the import fills empty keywords from these names
with a warning. Add a new vendor's brand words there as one group.

### Changing probe prompts

Probe texts are calibration data. Changing one in `ekte/prompts/en.json` can
change answer checks, token estimates and thus verdicts, so adjust the detector
and its tests with it, and mention the change in the CHANGELOG. Never make a
probe follow the UI language.

### Translations

The UI and the webhook alerts share one set of translations in
`ekte/i18n/locales/<code>.json`:

- `meta` — code, the language's own name for the dropdown, `html` lang, date
  locale and menu order;
- `strings` — English text → translation (`en.json` is the identity map and the
  canonical list of translatable strings);
- `findings` — finding id → `[title, summary template]` (`zh.json` holds the
  original Chinese catalog).

Features may ship their strings as fragments,
`ekte/i18n/locales/fragments/<feature>/<code>.json` holding
`{"strings": {…}}`, merged into the language at load time.
`/locales.js` sends only the chosen language (`?lang=<code>` or the `ekte_lang`
cookie `lang.js` sets; every language without either), built and gzipped once
per variant and revalidated by `ETag`; switching loads the new language on
demand.

- **UI text:** write the Chinese in the HTML and the English in `data-en`
  (or use `T(zh, en)`), then add the English key to `en.json` or a fragment and
  its translation to every other language.
- **New language:** add `ekte/i18n/locales/<code>.json` (copy `de.json`) and a
  file per fragment; the dropdown, the pages, the alerts and `--alert-lang` pick
  it up.
- `tests/test_web_locales.py` fails until every UI string and finding is
  translated with its placeholders and markup intact.

**Wording.** A term has one translation per language. Reuse the wording the UI
already uses (page names, dimension names, risk labels, button labels) in new
strings and in the documentation.

### Documentation

User documentation exists in eight languages — English, Chinese (`zh-CN`),
French, Spanish, Portuguese, Italian, German and Norwegian (Bokmål, `nb`):

| File | Audience |
|---|---|
| `README.md`, `README.<lang>.md` | Users: what ekte does, installing, using the CLI and the web UI |
| `DEVELOPER_GUIDE.md`, `DEVELOPER_GUIDE.<lang>.md` | Contributors: architecture, setup, contributing, Docker, releases |
| `docs/METHODOLOGY.md`, `docs/METHODOLOGY.<lang>.md` | Everyone: every check, its scoring scale and caveats |
| `docs/CI.md`, `docs/DOCKER.md`, `docs/PUBLISHING.md` | Reference pages (English) |

The English files are the reference. When you change one, change the others in
the same pull request, and use the UI's own wording in each language (look the
term up in `ekte/i18n/locales/`). The METHODOLOGY files quote the scoring
scales with the wording the UI shows under **Scoring scale**.

## Testing

```bash
pytest                       # everything
pytest tests/test_billing.py # one module
pytest -k streaming          # by keyword
pytest -n auto               # in parallel, one worker per CPU (pytest-xdist)
```

- `tests/conftest.py` provides `MockServer`, an OpenAI-compatible endpoint on
  `httpx.MockTransport` with knobs for every divergence ekte hunts for (served
  model, self-identity, context truncation, fake streaming, missing or inflated
  usage, tool calls, JSON mode, …). Every knob defaults to an honest relay.
- Anthropic and Responses clients have their own tests (`test_anthropic.py`,
  `test_responses.py`); the web server is tested through FastAPI's test client
  (`test_web*.py`), including the local-only protections
  (`test_web_security.py`).
- The browser scripts (`lang.js`, `v2/relaycfg.js`, `perf.js`, `secretfield.js`,
  `v2/report.js`, the locales) are evaluated under `node` in
  `test_web_*_js.py` and `test_web_locales.py`; they are skipped without Node.js.
- No test may reach the network.
- `test_cli_startup.py` keeps the CLI fast to start: importing `ekte.cli` must
  not load the HTTP clients, the runner, the knowledge loader, the report
  renderers (ReportLab) or the web server. Import those inside the command that
  needs them.
- `test_filler_perf.py` pins the filler text byte for byte and fails when the
  context-window probe stalls the event loop.
- `tests/a11y/` checks web UI v2 against BITV 2.0 / EN 301 549 / WCAG 2.1 AA
  in a real browser (Playwright + axe-core), in every UI language and both
  themes: `pip install -e '.[web,a11y]' && playwright install chromium`, then
  `pytest -m a11y`. Without Playwright the directory is skipped. What is
  automated and what still needs a manual BITV review is in
  [docs/ACCESSIBILITY.md](docs/ACCESSIBILITY.md).
- `EKTE_A11Y_PAGES=history,kb` runs only the a11y tests of those pages (plus
  the checks that span every page); `python -m tests.a11y.affected --base
  origin/main --head HEAD` prints the pages a change affects. Both use one
  mapping, `tests/a11y/pages.py`: a new page is added to its `PAGES` and
  `RULES` ([tests/a11y/README.md](tests/a11y/README.md)).

## Docker

The `Dockerfile` builds an image of the web UI (Python 3.12 slim with the `web`
extra; PDF reports need no system packages). It runs as an unprivileged
user with the data directory at `/data`.

```bash
docker build -t ekte .
docker run --rm -p 127.0.0.1:8000:8000 -v ekte-data:/data ekte
# open http://localhost:8000
```

**Always publish to `127.0.0.1`.** A bare `-p 8000:8000` publishes the UI — and
every API key typed into it or stored in a monitor — to your network. Inside the
container the server has to listen on all interfaces; that is allowed only when
`EKTE_CONTAINER=1` is set (the image sets it) *and* a container runtime is
detected.

| Variable | Default | Purpose |
|---|---|---|
| `EKTE_CONTAINER` | unset (`1` in the image) | Allows a non-loopback bind inside a detected container |
| `EKTE_HOST` | `127.0.0.1` (`0.0.0.0` in the image) | Bind address; `--host` wins |
| `EKTE_PORT` | `8000` | Port; `--port` wins |
| `EKTE_DATA_DIR` | `~/.ekte` (`/data` in the image) | History, monitors (their keys encrypted) and your knowledge-base entries; mount a volume here. `--data-dir` wins |
| `EKTE_SECRET_KEY` | unset | Master key of the monitors' stored API keys (a key, or `file:/run/secrets/…` / `env:VAR`); unset, the Monitors page asks for it after every start. Never stored in `EKTE_DATA_DIR` |
| `EKTE_KB_DIR` | unset | Extra knowledge-base YAML directory, e.g. `-v ./profiles:/kb:ro -e EKTE_KB_DIR=/kb` |
| `EKTE_NO_USER_KB` | unset | `1` ignores your own knowledge-base entries (`kb.db`) |
| `EKTE_ALLOWED_HOSTS` | unset | Extra host names the UI answers to, comma-separated |

[docs/DOCKER.md](docs/DOCKER.md) is the full reference, including what protects
the UI.

## Continuous integration

| Workflow | Runs | Does |
|---|---|---|
| `.github/workflows/ci.yml` | push and pull request to `main` (and the integration branches `a11y/integration`, `perf/integration`); nightly and manual (accessibility only) | `ruff`, `mypy` and `pytest` on Python 3.11–3.14 with the `dev` and `web` extras; builds the wheel and sdist and checks that the wheel installs and loads the knowledge base; runs the accessibility suite (informational, never fails the run) and uploads its findings: every page on pushes, the nightly and manual runs (with the BITV conformance report), on pull requests only the pages the change affects (none for docs-only changes) — except on pull requests into `perf/integration`, where the slow browser suite is skipped (it runs on that branch's pushes and on its pull request into `main`) |
| `.github/workflows/release.yml` | a `v*` tag | builds, runs `twine check` and publishes to PyPI (Trusted Publishing) |
| `.github/workflows/example-audit.yml` | daily schedule, manual | example of a scheduled relay audit with the action |

The composite action itself is `action.yml`, documented in [docs/CI.md](docs/CI.md).

## Releases

1. Re-check the supported Python versions against the stability policy
   (docs/STABILITY.md): `requires-python`, the classifiers, the CI matrix and
   the docs must name the same versions (`tests/test_python_versions.py`
   checks the first three). Announce a dropped version in the changelog.
2. Move `[Unreleased]` in `CHANGELOG.md` to the new version and bump `version`
   in `pyproject.toml`.
3. Commit, tag `vX.Y.Z` and push the tag; `release.yml` publishes to PyPI.
4. Create the GitHub release with the CHANGELOG notes and update the pinned
   action version in the READMEs and `docs/CI.md`.

The one-time PyPI setup and the manual fallback are in
[docs/PUBLISHING.md](docs/PUBLISHING.md).

## Security

Report vulnerabilities privately, as described in [SECURITY.md](SECURITY.md).
In scope are, above all: a key or secret reaching a report, relay-controlled
text injecting markup into a report or the UI, egress to anything but the
configured endpoints, and ways around the web UI's local-only protections.

## License

[Apache-2.0](LICENSE)
