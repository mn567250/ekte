# zing — Developer guide

> **🇬🇧 English** · [🇨🇳 中文](DEVELOPER_GUIDE.zh-CN.md) · [🇫🇷 Français](DEVELOPER_GUIDE.fr.md) · [🇪🇸 Español](DEVELOPER_GUIDE.es.md) · [🇵🇹 Português](DEVELOPER_GUIDE.pt.md) · [🇮🇹 Italiano](DEVELOPER_GUIDE.it.md) · [🇩🇪 Deutsch](DEVELOPER_GUIDE.de.md)

This guide is for people who change zing: how it is built, how to set up a
development environment, how to contribute, and how it is packaged, run in
Docker and released. What zing does and how to use it is in the
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

zing is a black-box auditing aid: correctness and **not falsely accusing honest
relays** matter more than catching every possible trick. Keep that bar in mind
for any change.

- **Evidence over accusation.** Findings report *divergence and risk*, never
  "fraud". Prefer *inconclusive* to a guess. A new HIGH-severity path needs hard,
  reproducible evidence and must be hard to trip on an honest endpoint.
- **No network in tests.** Detector tests run against the in-process mock server
  in `tests/conftest.py` (httpx `MockTransport`), never a live API.
- **Secrets never leave.** API keys are fingerprinted, never stored in reports.
  Any new output path must route relay-controlled text through
  `zing.utils.redact` and escape it for its format.
- **Same probes for everyone.** Probe texts are English and fixed, whatever the
  UI language, so the same relay gets the same verdict (see
  [Prompt library](#prompt-library)).
- **Local only.** zing contacts only the endpoints the user configures, and the
  web UI only listens on loopback (see [Web server](#web-server)).

## Development setup

Requires Python 3.10+. Node.js is optional: the tests of the browser JavaScript
run under `node` and are skipped without it.

```bash
git clone https://github.com/cenbonew/zing
cd zing
pip install -e '.[dev,web]'   # editable install with the dev tools and the web UI
pytest                        # test suite
ruff check zing tests         # lint
mypy zing                     # type-check
```

With uv: `uv venv && uv pip install -e '.[dev,web]'`. No system
libraries are needed, PDF reports included.

Run from source with `zing …` or `python -m zing …`. `zing serve` serves the
web UI from `zing/web/static/` directly, so a browser reload picks up front-end
changes; there is no build step.

## Repository layout

```text
zing/
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
  prompts/en.json      every text zing sends to an LLM API
  perf/                per-request recorder and the report's performance section
  report/              JSON / Markdown / HTML / PDF renderers and the writer
  embed_audit.py       standalone embedding and rerank auditor
  media_audit.py       standalone image and audio (TTS) auditor
  notify.py            webhook alerts (Slack / Feishu / DingTalk / generic JSON)
  datadir.py           the local data directory and its SQLite files
  secretbox.py         encryption of stored secrets; the master key held in memory
  i18n/                translations shared by the web UI and the alerts
    locales/           <code>.json per language, fragments/<feature>/<code>.json
  utils/               redaction, SSE parsing, statistics, token estimation
  web/
    server.py          FastAPI app: pages, JSON API, SSE audit stream, monitor scheduler
    jobs.py            background audit jobs and the per-relay gate
    security.py        loopback bind, Host allowlist, Origin/JSON checks, headers
    history.py         audit history store (history.db)
    watches.py         monitor store (watches.db)
    masterkey.py       the master key's states and actions (server and `zing secret`)
    static/            classic UI pages and the shared scripts (lang.js, i18n.js, …)
    static/v2/         the new UI's pages, styles and scripts
tests/                 pytest suite; conftest.py holds the mock relay
docs/                  METHODOLOGY (7 languages), CI.md, DOCKER.md, PUBLISHING.md
examples/zing.yaml     annotated config file
prototypes/            static HTML design prototypes of the web UI (not shipped)
action.yml             the GitHub composite action
Dockerfile             web UI image
```

## Architecture

### Audit pipeline

`zing check`, `zing compare`, `zing watch`, the web UI's audit stream and its
monitor scheduler all end in the same function, `zing.runner.run_audit()`:

1. **Configuration.** `zing/config.py` merges the YAML config with command-line
   options into `TargetConfig` (target, optional baseline and judge) and
   `AuditOptions` (suite, dimensions, probe sizes, output). API keys given as
   `env:VAR` or `file:/path` are resolved here.
2. **Knowledge base.** `load_knowledge_base()` loads the packaged profiles,
   `--kb-dir`/`ZING_KB_DIR` and the user's `kb.db`, and resolves the **claimed**
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
6. **Report.** Everything lands in an `AuditReport` (`zing/models.py`) with the
   redacted target, the knowledge-base profile snapshot, the performance section
   and the probe languages. The CLI renders and writes it; the web UI streams it.

`run_audit()` takes an `on_event` callback; the web server turns its events
(detector started/finished with compact findings, batched per-request timings)
into Server-Sent Events for the live view.

### Clients

`zing/clients/` has one client per wire protocol — `openai_compatible.py`
(Chat Completions), `anthropic.py` (Messages) and `responses.py` (Responses) —
with the same interface, built on shared HTTP machinery in `base.py`.
`make_client()` in `clients/__init__.py` chooses one from `--api` or detects it
from the base URL and model. Detectors only speak to this interface
(`RequestSpec` in, `CompletionOutcome` out), so they are protocol-agnostic.

### Detectors and scoring scales

A detector is one self-contained file in `zing/detectors/`: a subclass of
`Detector` (`base.py`) with an `id`, a `name`, a `dimension`, the first suite it
runs in (`min_suite`), an approximate `cost_hint` for `--dry-run`, and
`async def run(self, ctx) -> DetectorResult`. `@register` adds it to the
registry; `zing/detectors/__init__.py` imports every module so the registry is
complete.

Each detector publishes its **scoring scale** (`SCALE`, built with `scale.py`):
every possible outcome of each check with its points, status and severity.
Findings are created from the scale (`SCALE.finding(check, outcome, …)`), so the
report and the behavior cannot disagree. `Scale` scores the mean of its checks;
`DeductionScale` starts at 100 and deducts or caps. The web UI shows the scale
under **Scoring scale**; the [Methodology](docs/METHODOLOGY.md) reproduces every
scale. `connectivity.py` is the canonical, shortest example.

Detectors share one event loop with every other audit in `zing serve`, so
CPU-heavy work must not run on it: a stalled loop delays other audits' requests
and inflates the latencies they record. `helpers.build_filler()` builds filler
text in linear time and memoizes the last few sizes, and the context-window and
prompt-cache detectors call it (and `build_haystack()`) through
`asyncio.to_thread`. Token counts come from `zing/utils/tokenize.py`, a
standard-library heuristic: zing imports no tokenizer library and downloads
nothing at runtime, so it works in restricted environments. The `tokenizer`
argument of `estimate_tokens()` is accepted but does not change the count, and
the report fields `tokens_exact` / `exact_tokenizer` are kept for compatibility
and always false.

### Scoring and verdict

`zing/scoring.py` holds `DIMENSION_WEIGHTS` and the verdict rules: a dimension
score is the equal-weight mean of its detectors, the overall score the weighted
mean of the dimensions that ran, and the risk level follows the severity ladder
described in [Methodology → How zing scores](docs/METHODOLOGY.md#how-zing-scores).
Each dimension records how it was computed in `DimensionScore.breakdown`, which
feeds **Dimension details** in the reports and the expandable rows of
**Per-dimension checks** in the web UI.

### Knowledge base

`zing/knowledge/` defines the profile schema (`schema.py`: `ProviderProfile`,
`ModelProfile`, `FingerprintProbe`), loads and merges the layers
(`loader.py`: packaged YAML → `ZING_KB_DIR`/`--kb-dir` → the user's `kb.db`),
stores the user's entries (`store.py`), checks and imports YAML
(`importer.py`), builds the research prompt for external assistants
(`research.py`) and snapshots the profile a run used (`snapshot.py`). Model ids
resolve through aliases and the declared provider; every report records how the
id matched.

`load_knowledge_base()` caches merged results and returns a deep copy by
default, so callers may modify what they get. Callers that only read it (the web
UI's lists and catalog, resolving a model) pass `copy=False` and get the shared
cached instance, which they must not modify.

Relays are endpoints too: `relays.py` turns a provider's `base_url_hints` into
usable base URLs (`GET /api/kb` → `base_urls`) and saves a relay from the web UI
as a provider entry in `kb.db` (`origin = relay`: a `display_name` and one base
URL, no models; no schema change).

### Prompt library

Every text zing sends to an LLM API — chat probes, the judge's prompt, tool
schemas, embedding / rerank / image / audio inputs — lives in
`zing/prompts/en.json` and is read with `zing.prompts.text()` / `get()`.
`{{name}}` marks a value filled in at run time. The probe language is fixed to
English (`PROBE_LANG`), independent of the UI language, because answer checks and
token estimates are calibrated to these exact texts. Probes whose language *is*
the measurement (e.g. Chinese fluency, tokenizer or self-identification of
China-native models) live with their expected answers in the knowledge base and
declare `prompt_lang` and a `language_bound` reason. The runner records the
languages used in `prompt_languages`.

### Reports

`zing/report/render.py` renders an `AuditReport` to JSON, the compact agent JSON,
Markdown and HTML; `dimensions.py` and `performance.py` render the
**Dimension details** and the performance section; `pdf.py` typesets the PDF
with ReportLab from the same data and helpers (pure Python; only the standard PDF
fonts, with the CID font STSong-Light for Chinese, so nothing is embedded; never
loading external resources), and the CLI and the web UI share it;
`writer.py` writes the files. All relay-controlled text is redacted and escaped
(HTML / Markdown) before output. The web UI's `POST /api/report/export` reuses
these renderers for its **Download report** row, with the human-readable text
translated to the UI language.

### Standalone auditors

Embedding/rerank (`embed_audit.py`) and image/audio (`media_audit.py`) are not
chat surfaces, so they have their own small auditors with their own verdict
dict instead of the detector pipeline. They share the clients' HTTP settings, the
knowledge base (native dimensions, image sizes, voices) and the prompt library.
All decoding (image headers, WAV) is standard library only.

### Web server

`zing/web/server.py` is a FastAPI app created by `create_app()`:

- **Pages.** The classic UI (`/`, `/console`, `/history`, `/watches`, `/tools`)
  and the new UI (`/v2/`, `/v2/history`, `/v2/watches`, `/v2/tools`, `/v2/kb`)
  are static HTML files. `?ui=v2` / `?ui=v1` switches and a cookie remembers the
  choice, so a classic URL redirects to its new counterpart once the new UI was
  chosen.
- **API.** `/api/audit/stream` runs an audit and streams its events over SSE;
  `/api/models` lists a relay's models; `/api/report/export` renders a report;
  `/api/history…`, `/api/watches…`, `/api/kb…`, `/api/embed` and `/api/rerank`
  back the other pages.
- **Relays.** `POST /api/kb/relays` saves a relay `{name, base_url}` (400 for bad
  input, 409 when the name or URL is already known).
- **Background audits.** `jobs.py` runs every audit as a job owned by the
  server. `POST /api/jobs` queues one, `GET /api/jobs` lists queued, running and
  recently finished jobs (plus running monitors) with progress,
  `GET /api/jobs/{id}/events` replays the job's event log and then follows it
  live over SSE, and `POST /api/jobs/{id}/cancel` stops it. The new UI uses
  these, so an audit outlives the page; `/api/audit/stream` (classic UI) wraps
  the same job and cancels it when the stream closes. A relay gate lets one
  audit (or monitor run) at a time use a relay, keyed by host name with every
  loopback address as one host, and at most `ZING_MAX_PARALLEL_AUDITS`
  (default 4) run at once; waiters are served in arrival order.
- **Monitor scheduler.** The app's lifespan starts a background loop that
  starts every due monitor as its own task, so monitors on different relays
  audit at the same time; the relay gate still applies, so monitors can fill
  the `ZING_MAX_PARALLEL_AUDITS` slots and a manual audit may queue behind
  them. A run's `last_run_ts` is the moment its audit starts (after waiting for
  its relay). Each run is stored in the history; the regression check compares
  it with the most recent saved run of the same target and model
  (`history.latest_for()`, one indexed lookup) and sends the webhook alerts
  (`zing/notify.py`) concurrently on a threshold cross or a regression.
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
  in a detected container with `ZING_CONTAINER=1`) and installs
  `LocalOnlyMiddleware`: a Host allowlist against DNS rebinding, Origin and
  `Sec-Fetch-Site` checks against CSRF, JSON-only request bodies, and
  anti-framing / no-sniff / no-referrer headers. The UI has no login by design.

### Web front end

The front end is plain HTML, CSS and browser JavaScript without modules or a
build step. The classic pages live in `zing/web/static/`; the new UI in
`zing/web/static/v2/` shares one header (`nav.js`), the report renderer
(`report.js`), the theme switch (`theme.js`) and the styles (`zing.css`,
`fields.css`, `report.css`, `perf.css`). Shared scripts are served from the root:
`lang.js` (language switch), `locales.js` (translation data), `i18n.js` (finding
translations), `icons.js`, `modelpicker.js` (**Fetch models**), `secretfield.js`
and `perf.js` (performance charts).

The v2 **Audit** and **Tools** pages configure relays with `v2/relaycfg.js`:
relay/provider select → base URL → the relay's models (`/api/models`, on change,
cached per URL/key/protocol) → claimed model from the knowledge base
(`/api/kb/resolve` preselects it) → derived declared provider, plus **Save to
knowledge base** (`POST /api/kb/relays`). Its pure helpers are tested under node;
the classic pages keep `modelpicker.js`.

**Translation convention.** The Chinese text written in the HTML is the
original and stays untouched; every element carries its English text in
`data-en` (and `data-en-placeholder`, `data-en-title`, `data-en-aria-label`).
The English text is the lookup key for every other language. Scripts use
`T(zh, en)` for dynamic text and `ZING_LANG.server(text)` for text coming from
the backend (detector names, recommendations, verdict sentences).

### Local data

`zing/datadir.py` owns `$ZING_DATA_DIR` (default `~/.zing`), created `0700`,
with `0600` SQLite files: `history.db` (`web/history.py`), `watches.db`
(`web/watches.py`, which holds the monitors' API keys, encrypted) and `kb.db`
(`knowledge/store.py`). Each call opens a short-lived connection, so the stores
are safe on FastAPI's thread pool. The global `--data-dir` option (also on
`zing serve`) just sets `ZING_DATA_DIR` to the absolute path, and
`zing data-dir` prints the resolved directory. A directory that already exists
keeps its mode; only the default `~/.zing` is tightened to `0700`. History rows
are indexed by target and model (`idx_history_target`), which
`history.latest_for()` uses to find a monitor's previous run.

Stored API keys are encrypted by `zing/secretbox.py` (Fernet, stored as
`enc:v1:…`; `env:`/`file:` references stay as they are). The master key itself
is never stored: `web/masterkey.py` (`Vault`, shared by the server and
`zing secret`) holds it in the server's memory once it comes from
`ZING_SECRET_KEY`, a legacy `secret.key` or the user on the Monitors page, and
`watches.db` keeps only a check value (`secret_meta`) that rejects a wrong key.
A new key re-encrypts every stored key and rewrites the check value in one
transaction. The key lives in one process's memory, so run one server per data
directory.

## Contributing

### Pull requests

- Keep `pytest`, `ruff check zing tests` and `mypy zing` green (CI runs all three
  on Python 3.10–3.13).
- Describe the relay trick or the false positive a change addresses.
- Update `CHANGELOG.md` under `[Unreleased]`.
- Update the documentation the change touches — README, this guide, the
  Methodology — in **every language** (see [Documentation](#documentation)).

By contributing you agree that your contributions are licensed under the
project's [Apache-2.0](LICENSE) license.

### Adding a detector

1. Create `zing/detectors/<name>.py` and import it in
   `zing/detectors/__init__.py`.
2. Define its `SCALE` (`Scale` or `DeductionScale` from `scale.py`) with every
   outcome of every check, and create findings only through it.
3. Subclass `Detector`; set `id`, `name`, `dimension`, `min_suite` and
   `cost_hint`; set `requires_judge = True` or `requires_baseline = True` if it
   needs one, or override `applies()` for other gating. Decorate it with
   `@register`.
4. Implement `async def run(self, ctx) -> DetectorResult`, starting from
   `self.new_result(scoring=SCALE.scoring())`. Send requests through `ctx.client`
   and take every prompt from `zing/prompts/en.json`.
5. Add behavioral tests for both the flagged and the clean path, using the mock
   relay in `tests/conftest.py`.
6. Translate new finding titles and summaries (see [Translations](#translations))
   and document the detector and its scale in every
   [Methodology](docs/METHODOLOGY.md) file.

### Editing the knowledge base

Profiles live in `zing/knowledge/data/<provider>.yaml`, one file per provider.
Each model carries its native context window, max output, knowledge cutoff,
tokenizer, modalities, capability flags, unsupported parameters, identity
keywords and fingerprints (see `zing/knowledge/schema.py`). When you change a
numeric field, **cite an authoritative source** (the provider's official model
card, pricing or docs) in the pull request: a wrong value causes false positives
against honest relays. `zing kb-import --check <file>` runs the same checks as
the user import (schema, limits, unsafe regular expressions, prompts, id
collisions).

### Changing probe prompts

Probe texts are calibration data. Changing one in `zing/prompts/en.json` can
change answer checks, token estimates and thus verdicts, so adjust the detector
and its tests with it, and mention the change in the CHANGELOG. Never make a
probe follow the UI language.

### Translations

The UI and the webhook alerts share one set of translations in
`zing/i18n/locales/<code>.json`:

- `meta` — code, the language's own name for the dropdown, `html` lang, date
  locale and menu order;
- `strings` — English text → translation (`en.json` is the identity map and the
  canonical list of translatable strings);
- `findings` — finding id → `[title, summary template]` (`zh.json` holds the
  original Chinese catalog).

Features may ship their strings as fragments,
`zing/i18n/locales/fragments/<feature>/<code>.json` holding
`{"strings": {…}}`, merged into the language at load time.
`/locales.js` sends only the chosen language (`?lang=<code>` or the `zing_lang`
cookie `lang.js` sets; every language without either), built once and
revalidated by `ETag`; switching loads the new language on demand.

- **New UI text:** write the Chinese in the HTML and the English in `data-en`
  (or use `T(zh, en)`), then add the English key to `en.json` or a fragment and
  its translation to every other language.
- **New language:** add `zing/i18n/locales/<code>.json` (copy `de.json`) and a
  file per fragment; the dropdown, the pages, the alerts and `--alert-lang` pick
  it up.
- `tests/test_web_locales.py` fails until every UI string and finding is
  translated with its placeholders and markup intact.

**Wording.** A term has one translation per language. Reuse the wording the UI
already uses (page names, dimension names, risk labels, button labels) in new
strings and in the documentation.

### Documentation

User documentation exists in seven languages — English, Chinese (`zh-CN`),
French, Spanish, Portuguese, Italian and German:

| File | Audience |
|---|---|
| `README.md`, `README.<lang>.md` | Users: what zing does, installing, using the CLI and the web UI |
| `DEVELOPER_GUIDE.md`, `DEVELOPER_GUIDE.<lang>.md` | Contributors: architecture, setup, contributing, Docker, releases |
| `docs/METHODOLOGY.md`, `docs/METHODOLOGY.<lang>.md` | Everyone: every check, its scoring scale and caveats |
| `docs/CI.md`, `docs/DOCKER.md`, `docs/PUBLISHING.md` | Reference pages (English) |

The English files are the reference. When you change one, change the others in
the same pull request, and use the UI's own wording in each language (look the
term up in `zing/i18n/locales/`). The METHODOLOGY files quote the scoring
scales with the wording the UI shows under **Scoring scale**.

## Testing

```bash
pytest                       # everything
pytest tests/test_billing.py # one module
pytest -k streaming          # by keyword
pytest -n auto               # in parallel, one worker per CPU (pytest-xdist)
```

- `tests/conftest.py` provides `MockServer`, an OpenAI-compatible endpoint on
  `httpx.MockTransport` with knobs for every divergence zing hunts for (served
  model, self-identity, context truncation, fake streaming, missing or inflated
  usage, tool calls, JSON mode, …). Every knob defaults to an honest relay.
- Anthropic and Responses clients have their own tests (`test_anthropic.py`,
  `test_responses.py`); the web server is tested through FastAPI's test client
  (`test_web*.py`), including the local-only protections
  (`test_web_security.py`).
- The browser scripts (`lang.js`, `modelpicker.js`, `v2/relaycfg.js`, `perf.js`, `secretfield.js`,
  `v2/report.js`, the locales) are evaluated under `node` in
  `test_web_*_js.py` and `test_web_locales.py`; they are skipped without Node.js.
- No test may reach the network.
- `test_cli_startup.py` keeps the CLI fast to start: importing `zing.cli` must
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

## Docker

The `Dockerfile` builds an image of the web UI (Python 3.12 slim with the `web`
extra; PDF reports need no system packages). It runs as an unprivileged
user with the data directory at `/data`.

```bash
docker build -t zing .
docker run --rm -p 127.0.0.1:8000:8000 -v zing-data:/data zing
# open http://localhost:8000
```

**Always publish to `127.0.0.1`.** A bare `-p 8000:8000` publishes the UI — and
every API key typed into it or stored in a monitor — to your network. Inside the
container the server has to listen on all interfaces; that is allowed only when
`ZING_CONTAINER=1` is set (the image sets it) *and* a container runtime is
detected.

| Variable | Default | Purpose |
|---|---|---|
| `ZING_CONTAINER` | unset (`1` in the image) | Allows a non-loopback bind inside a detected container |
| `ZING_HOST` | `127.0.0.1` (`0.0.0.0` in the image) | Bind address; `--host` wins |
| `ZING_PORT` | `8000` | Port; `--port` wins |
| `ZING_DATA_DIR` | `~/.zing` (`/data` in the image) | History, monitors (their keys encrypted) and your knowledge-base entries; mount a volume here. `--data-dir` wins |
| `ZING_SECRET_KEY` | unset | Master key of the monitors' stored API keys (a key, or `file:/run/secrets/…` / `env:VAR`); unset, the Monitors page asks for it after every start. Never stored in `ZING_DATA_DIR` |
| `ZING_KB_DIR` | unset | Extra knowledge-base YAML directory, e.g. `-v ./profiles:/kb:ro -e ZING_KB_DIR=/kb` |
| `ZING_NO_USER_KB` | unset | `1` ignores your own knowledge-base entries (`kb.db`) |
| `ZING_ALLOWED_HOSTS` | unset | Extra host names the UI answers to, comma-separated |

[docs/DOCKER.md](docs/DOCKER.md) is the full reference, including what protects
the UI.

## Continuous integration

| Workflow | Runs | Does |
|---|---|---|
| `.github/workflows/ci.yml` | push and pull request to `main` (and the integration branches `a11y/integration`, `perf/integration`) | `ruff`, `mypy` and `pytest` on Python 3.10–3.13 with the `dev` and `web` extras; builds the wheel and sdist and checks that the wheel installs and loads the knowledge base; runs the accessibility suite (informational, never fails the run) and uploads its findings — except on pull requests into `perf/integration`, where the slow browser suite is skipped (it runs on that branch's pushes and on its pull request into `main`) |
| `.github/workflows/release.yml` | a `v*` tag | builds, runs `twine check` and publishes to PyPI (Trusted Publishing) |
| `.github/workflows/example-audit.yml` | daily schedule, manual | example of a scheduled relay audit with the action |

The composite action itself is `action.yml`, documented in [docs/CI.md](docs/CI.md).

## Releases

1. Move `[Unreleased]` in `CHANGELOG.md` to the new version and bump `version`
   in `pyproject.toml`.
2. Commit, tag `vX.Y.Z` and push the tag; `release.yml` publishes to PyPI.
3. Create the GitHub release with the CHANGELOG notes and update the pinned
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
