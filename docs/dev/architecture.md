# Architecture

## Audit pipeline

`ekte check`, `ekte compare`, `ekte watch`, the web UI's audit stream and its
monitor scheduler all end in the same function, `ekte.runner.run_audit()`:

1. **Configuration.** `ekte/config.py` merges the YAML config with command-line
   options into `TargetConfig` (target, optional baseline and judge) and
   `AuditOptions` (suite, dimensions, probe sizes, output). API keys given as
   `env:VAR` or `file:/path` are resolved here.
   The format is defined in `ekte/configfile.py` (one table of keys, types and defaults) and published as the JSON schema [`docs/schemas/config.schema.json`](../schemas/config.schema.json), regenerated with `uv run python -m ekte.configfile` (a test fails when it is stale). `ekte/config.py` loads the file through it, so every command validates it. A format change needs a new `CURRENT_VERSION`, the renames in `RENAMES_FROM` (used by `ekte config migrate`) and a changelog entry; a deprecated key goes into `DEPRECATED` with its replacement. See the [stability policy](../reference/stability.md#surface-config).
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

## Clients

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

## Detectors and scoring scales

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
under **Scoring scale**; the [Methodology](../guide/methodology.md) reproduces every
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

## Scoring and verdict

`ekte/scoring.py` holds `DIMENSION_WEIGHTS` and the verdict rules: a dimension
score is the equal-weight mean of its detectors, the overall score the weighted
mean of the dimensions that ran, and the risk level follows the severity ladder
described in [Methodology → How ekte scores](../guide/methodology.md#how-ekte-scores).
Each dimension records how it was computed in `DimensionScore.breakdown`, which
feeds **Dimension details** in the reports and the expandable rows of
**Per-dimension checks** in the web UI.

## Knowledge base

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

## Prompt library

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

## Reports

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

## Surfaces

The **surface** is the kind of endpoint audited: `chat` (default),
`embedding` or `rerank` (`ekte.config.SURFACES`; image and TTS are planned). It is a second
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
  `ekte embed` / `ekte rerank`) run the runner
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

## Standalone auditors

Image and audio auditing (`media_audit.py`) is not a surface yet, so it has its
own small auditors, each with its own verdict dict, instead of the detector
pipeline. They share the clients' HTTP settings, the
knowledge base (native dimensions, image sizes, voices) and the prompt library.
All decoding (image headers, WAV) is standard library only.

## Local data

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
until the `ekte_*` ones exist. All of it is deprecated and removed in 1.0.0 (the notices name that version); ekte never deletes an old `~/.zing`.
