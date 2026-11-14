# Web server

`ekte/web/server.py` is a FastAPI app created by `create_app()`:

- **Pages.** The web UI (`/`, `/history`, `/watches`, `/analytics`,
  `/kb`, `/accessibility`) is static HTML served at the root, its scripts and
  styles under `/static/`. There is no Tools page: embedding and rerank audits
  start on the audit page through the endpoint-type selector
  (`/?surface=embedding|rerank`). Until 1.0.0 the former addresses redirect (308) to the
  page at the root, keeping the query string: `/v2/…` (`/v2/tools` goes to
  `/?surface=embedding`, and `#rerank` picks rerank) and the removed classic UI's
  `/tools` and `/console`. These redirects are deprecated and removed in 1.0.0.
- **API.** `/api/jobs…` runs audits (below); `/api/models` lists a relay's
  models; `/api/report/export` renders a report; `/api/history…`,
  `/api/watches…`, `/api/kb…` and `/api/analytics…` back the other pages,
  `/api/secret…` the master key of the monitors' stored API keys (status, new,
  unlock, lock, reset, storage mode), `GET /api/version` is the change signal
  the pages poll (below) and `GET /api/health` answers a liveness
  check. All of these are internal; the public subset is [HTTP API v1](#http-api-v1).
- **Relays.** `POST /api/kb/relays` saves a relay `{name, base_url}` (400 for bad
  input, 409 when the name or URL is already known).
- **Analytics.** `GET /api/filters/options` and `/api/analytics/summary`,
  `series`, `heatmap`, `leaderboard`, `breakdown`, `errors` and `integrity`:
  one endpoint per widget on the query core, see [Analytics API](#analytics-api).
- **Response cache** (`ekte/web/cache.py`). Widget endpoints are plain `def`
  handlers wrapped in `@cached_endpoint("<name>")`: the handler gets its query
  parameters in canonical form (keys sorted, values stripped, empty ones
  dropped) and returns JSON. The key is `json([endpoint, params,
  data_version, kb_version, EXTRACT_VERSION, database])`, with no time slot:
  `history.data_version()` is a counter in `history.db`'s `meta` table bumped
  in the same transaction as every write (`save`, `delete`, `clear`, the
  analytics backfill), from any process, so a CLI audit drops the
  cache too; `kb_version` is `ekte.knowledge.relays.kb_version()`. A handler
  whose answer depends on the clock resolves it first (`prepare=`; e.g. the
  Analytics widgets' `from` without `to` gets `to` = now, rounded up to the minute). The LRU (`ResponseCache`,
  256 entries by default) is thread-safe and single-flight: concurrent misses
  on one key wait for one computation; errors are not cached. Answers carry
  `ETag` (a hash of the key and the ekte version) and `Cache-Control: no-cache`;
  a matching `If-None-Match` gets `304 Not Modified` without computing.
  `GET /api/history/status` and the report detail `GET /api/history/{id}`
  (keyed per run and `trend`; its own 16-entry LRU, as reports are large; an
  unknown id answers 404, never cached) go through it as well. POST / DELETE,
  `/api/secret`, `/api/jobs*` and the evidence endpoints (`no-store`) stay
  uncached.
  Reads use `datadir.read_connection(name)`: one reused read-only connection
  per thread (`mode=ro`, WAL, `query_only`), schema-checked only on the first
  open in the process (again if the file was replaced); writes keep using
  `datadir.connect`.
- **Change signal** (`GET /api/version`, #151). Answers
  `{"data": "<token>", "live": "<token>"}`: opaque strings that clients only
  compare for equality (`server.version_tokens()`).
  - `data` is a hash of exactly what keys the response cache above:
    `history.data_version()`, `kb_version`, `EXTRACT_VERSION` and the
    database (keep `version_tokens()` and `cache_key()` in step). It changes
    with every history write from any process (a CLI audit included) and with
    a knowledge-base change, and only then.
  - `live` is a hash of this process's id (a restarted server never repeats
    a token), the in-process counter `jobs.live_version()` and
    `watches.data_version()`. The counter is bumped (`jobs.bump_live()`) when
    a job is queued, waits for its relay, starts running or ends (done, error
    or cancelled: every end emits `done`), when a monitor run starts and ends
    (`_run_one_watch`), and when the master key is entered or locked (the
    monitors' key status changes without a write). `watches.data_version()`
    is a counter in `watches.db`'s `meta` table (schema version 5), bumped in
    the same transaction as every write that changes what `/api/watches`
    returns: `create`, `update`, `set_enabled`, `set_language`, `delete`,
    `pin`, `mark_run`, `mark_attempt` and the key-storage changes
    (`keys_to_memory`, `keys_to_store`, `migrate_keys`, `adopt_key`,
    `forget_keys`), from any process.
  - Cheap: two primary-key lookups on the reused read connections (no table
    is scanned; `tests/test_web_version.py` checks the query plans) and the
    cached knowledge-base fingerprint; budget 5 ms p95. The answer carries an
    `ETag` (a hash of both tokens and the ekte version) and
    `Cache-Control: no-cache`; a matching `If-None-Match` gets `304`.
- **Background audits.** `jobs.py` runs every audit as a job owned by the
  server. `POST /api/jobs` queues one, `GET /api/jobs` lists queued, running and
  recently finished jobs (plus running monitors) with progress,
  `GET /api/jobs/{id}/events` replays the job's event log and then follows it
  live over SSE, and `POST /api/jobs/{id}/cancel` stops it. The web UI uses
  these, so an audit outlives the page. A relay gate lets one
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
  (`ekte/notify.py`) concurrently when a threshold is crossed or a regression is found.
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

## Endpoints

The complete list, by page (the docstring of `ekte/web/server.py` has the
same). Internal unless under `/api/v1/` ([HTTP API v1](#http-api-v1)).

| Endpoint | What it answers |
|---|---|
| `GET /`, `/history`, `/watches`, `/analytics`, `/kb`, `/accessibility` | the pages (`/v2/…`, `/tools`, `/console`: 308 redirects until 1.0.0) |
| `GET /api/health` | `{ok, version}` |
| `GET /api/version` | the change signal `{data, live}` (ETag, 304; see **Change signal** above) |
| `POST /api/jobs` (`/api/v1/jobs`), `GET /api/jobs`, `GET /api/jobs/{id}` (`/api/v1/…`), `GET /api/jobs/{id}/events` (`/api/v1/…`), `POST /api/jobs/{id}/cancel` | background audits |
| `POST /api/models`, `POST /api/report/export` | a relay's models; a report rendered as JSON / Markdown / HTML / PDF |
| `GET /api/kb`, `POST /api/kb/relays`, `GET /api/kb/profiles`, `PUT /api/kb/enabled`, `GET /api/kb/prompt`, `POST /api/kb/resolve`, `POST /api/kb/scan`, `POST /api/kb/import`, `GET /api/kb/export`, `PATCH` / `DELETE /api/kb/entries/{id}` | the knowledge base |
| `GET /api/metrics` | the [metric registry](#metric-registry) |
| `GET /api/filters/options` | every filter key's values with run counts ([Analytics API](#analytics-api); History uses it too) |
| `GET /api/analytics/summary`, `series`, `heatmap`, `leaderboard`, `breakdown`, `errors`, `integrity` | the Analytics widgets ([Analytics API](#analytics-api)) |
| `GET /api/history/groups`, `GET /api/history/runs` | the History widgets ([History API](#history-api)) |
| `GET /api/history/status` | the history as a whole, for the page notices (cached) |
| `GET /api/history/{id}` (`?trend=1`, cached), `GET /api/v1/history/{id}` | one saved report |
| `DELETE /api/history/{id}`, `DELETE /api/history` | delete one run, or all |
| `GET /api/v1/history` | the newest runs (public; `limit`, `perf`) |
| `GET /api/v1/history/{id}/evidence`, `…/evidence/exchanges`, `…/evidence/export`, `POST /api/history/{id}/rescore` (`/api/v1/…`) | a run's evidence; re-score it |
| `GET /api/watches`, `GET /api/watches/options` | the monitors, filtered and cached, and their filter options (see [Monitors API](#monitors-api)) |
| `POST /api/watches`, `POST /api/watches/from-history/{id}`, `PATCH` / `DELETE /api/watches/{id}`, `POST /api/watches/{id}/run`, `POST /api/watches/{id}/cancel` | monitors |
| `GET /api/secret`, `POST /api/secret/new`, `…/new/confirm`, `…/unlock`, `…/lock`, `…/reset`, `…/storage` | the monitors' master key |

Every widget endpoint (metrics, filter options, Analytics, History groups and
runs) is a cached GET on the [query core](#query-core): the old Python
Analytics path (`analytics.summary()` and friends, loading every run in
range) and `/api/analytics/options` are gone (#123, #128).

## Query core

`ekte/web/query.py` is the one server-side path from URL parameters to
values: parameters → runs (SQL `WHERE`) → groups → aggregated values → page.
History and Analytics endpoints build on it; Python never filters runs and
never loads one row per run to aggregate. Every function takes a connection
from `history.query_connection()` (this thread's read connection, analytics
tables backfilled, `relay_map` current).

**URL schema.** Every key is optional. A key given twice is a 400 error, except
`relay` and `model`, which repeat (any value matches). Empty values count as
not given; `-` means "(unknown)", i.e. the run has no value.

| Key | Values | Replaces |
|---|---|---|
| `from`, `to` | ISO 8601 (naive = UTC) against the run's `started_at`; `to` exclusive | Analytics `from` / `to` |
| `range` | `24h`, `7d`, `30d`, `90d`, `365d`. A **day range** (`7d` … `365d`, N days) is today plus the previous N − 1 calendar days in `tz`: `from` = 00:00 local of the first day (`zoneinfo` calendar days, so a range across a DST change is N days, not N × 24 h), no `to`. **`24h`** is exact: `to` = now rounded up to the next minute, `from` = `to` − 24 h. Not with `to`; a day range takes `from` only in its resolved form (a local midnight in `tz`, as `Query.canonical()` writes it). The pages default to `30d` (`filters.js` `FIELDS`); `range=` (empty) is all time | History `days`, Analytics range presets |
| `tz` | the viewer's time zone, an IANA name (default `UTC`; unknown: 400). Selects no runs: it places day ranges and is the default zone of `trend.tz`, `heat.tz` and `errors.tz`. `EkteFilters.widgetParams()` sends the browser's zone with every widget request; the page URL never holds it, so a shared link resolves in each viewer's zone | the pages' `trend.tz` / `heat.tz` / `errors.tz` |
| `surface` | `chat`, `embedding`, `rerank` (NULL reads as chat); empty: all surfaces | both |
| `relay` | a relay key (`relay_map.relay_key`, `(unknown)` without URL), repeatable | both |
| `model` | a claimed model (`(unknown)` without one), repeatable | both |
| `suite`, `mode`, `api`, `stream` | the exact value (`stream` is the stored `stream_mode`), or `-` | History `suite/mode/api/stream`, Analytics `stream_mode` |
| `detect` | `auto`, `manual`, `-` | History `detect` |
| `risk` | `clean`, `low`, `medium`, `high`, `inconclusive` (no risk level is inconclusive) | History `risk` |
| `min_score` | 0–100 (runs without a score are left out) | History `min` |
| `exec` | `manual`, `monitor` | History `exec` (`adhoc`), Analytics `source` |
| `watch` | a monitor id (positive integer, not repeatable): the runs of exactly that monitor, also after it was deleted | — (new, [#155](https://github.com/mn567250/ekte/issues/155)) |
| `q` | substring, case-insensitive for ASCII (SQL `LIKE`, `%` `_` `\` literal) of base URL, relay label, claimed model, model, suite, mode, api | History `q` |
| `group` | `relay` (default), `model`, `relay_model`, `all` | both |

Keys with a dot belong to one widget (`trend.metric`, `runs.sort`,
`runs.after`) and are ignored by the shared parser; any other unknown key is a
400 error naming it. `parse_query(params, now=None) -> Query` validates
(`QueryError`, an `AnalyticsError`, so the existing 400 handling catches it);
`Query.canonical()` is the sorted, resolved form and `Query.params()` its URL
pairs: `from` (plus `to` for `24h`), `range` for a day range (it names the day
count) and `tz` unless UTC. `resolve_params` is the `prepare=` of
`cached_endpoint`, so a relative range is cached under its absolute bounds: a
day range's key and `ETag` stay the same all day and change at the viewer's
next midnight (otherwise only the data version invalidates them); `24h`
changes them every minute. History's time filter moves from
the save time (`ts`) to the run's start (`started_at`).

**Selection.** `select_runs(q) -> RunSelection` (`.sql` = `FROM … WHERE …`,
`.args`, `.and_where()`) over the run rows `history_metrics m` only
(`ekte/web/run_row.py`): the time on `m.started_us` (`time_sql`, exact to the
microsecond), the surface on `m.surface_id`, the other few-valued keys as
`m.facet_id IN (…)` (looked up once in `facet_combo`), relays and models by
`m.relay_id` / `m.model_id`, `watch` on `m.watch_id` (the run's
`history.watch_id`, copied onto the run row by its triggers, history schema
16), `min_score` on `m.score`. Only text search
(`q`) joins `history h` (through `idx_history_query`) and the run's relay
`rm`. Runs are grouped by an integer of their row (`run_row.GROUP_ID_SQL`:
relay id, model id, or both packed as `relay_id << 20 | model_id`), read in
`idx_run_row` order for relay and relay × model groups, and only the
resulting groups are named (`run_row.label_sql`). Group times come back as
microseconds and are spelled as `started_at` once per group (`us_text`). `count_runs`, `default_surface` (the most common
surface of a selection, for endpoints that need one).

**Aggregation.** `aggregate(conn, q, metrics, group=None, *, quantiles=False)
-> list[GroupResult]` (busiest first): per group `key`, `label`, `kind`,
`in_kb` (and `relay` / `model` for `relay_model`), `runs`, `first_run` /
`last_run`, and per metric a `Cell`: `value`, `n`, `coverage`, `low_n`
(`n` < `MIN_RUNS`), `median` / `p25` / `p75` (median metrics; quartiles with
`quantiles=True`) and `numerator` / `denominator` (pooled). The kind is the
registry's `Metric.agg`: `median` (SQLite `median()` / `percentile()`, type 7),
`pooled` for `success_rate`, `error_rate`, `rate_limited_rate`,
`timeout_rate`, `impaired_rate` (Σ count ÷ Σ `requests_judged`, or
`requests_total` for impaired; the run's count is its stored rate × base,
which is exactly its `history_outcomes` count), `share` (high risk, model
mismatch). One run returns exactly its stored value for every metric. Without
`median()` in the SQLite build, Python aggregates with the same results are
registered (`sql_functions`; the median's `step` is a bound `list.append`, so a
row costs one C call, and the values are filtered and sorted once in
`finalize`). `aggregate_rows(...)` (same arguments, plus
`finish`: per metric id, a function that completes each cell dict in place)
returns the same groups as `GroupResult.public()` dicts, built straight from
the fetched rows without a `Cell` / `GroupResult` per cell: the leaderboard
and breakdown widgets use it, as a board of hundreds of groups holds
thousands of cells.

**Series.** `series(conn, q, metric, group=None, bucket="day", tz=UTC, *, keys=(),
block=1, fold="week", max_keys=4, quantiles=False) -> SeriesResult` buckets in
SQL: the zone's UTC offset is a `CASE` over its transitions in the data's span
(`offset_sql`), and buckets are integer arithmetic on the run's local time in
seconds, so hour / day / week / `dow_hour` (with `block` and `fold`) buckets
and their values match the plain-Python reference of the tests
(`tests/analytics_reference.py`). Annotations (ekte version and
knowledge-base profile changes) come from each value's first and last run per
series: a value that follows another changes at its first run, and only the
runs where values overlap in time (a rollback) are read one by one. Only
bucket rows (and those runs) reach Python.

**Paging.** `page_runs(conn, q, sort="-time", after=None, limit=20) -> Page`:
`sort` is `time`, `score`, `risk` or `grade`, `-` for descending, ties by id;
`after` is the opaque cursor of the previous page (`Page.after`, None on the
last); `limit` 1–200. Keyset paging, so a run saved meanwhile never shifts
pages; rows are `PAGE_COLUMNS` (the list columns, the relay, headline values).

### Benchmark

`scripts/bench_fixture.py --data-dir DIR --bench` writes a
synthetic history (20,000 runs, 50 relays, 100 requests per run, 16 kB
reports, an ekte release every 3 weeks with an occasional one-day rollback,
a profile change every 45 days) plus 200 monitors in `watches.db`
(`--monitors`, formerly `--watches`: spread over the fixture's relays and
models, about 70 % active, 20 % paused and 10 % drafts, with mixed alert
thresholds, last risks and a few run windows), and prints p50 / p95 (nearest rank, 40 calls) of
`aggregate`, `series` and `page_runs`.

The budget tests (marked `slow`) check that every case's p95 stays under the
budget: `tests/test_query.py` (the query core), `tests/test_analytics_widgets.py`
(the Analytics widgets), `tests/test_history_api.py` (the History API),
`tests/test_watches_api.py` (the Monitors API) and
`tests/test_web_version.py` (`/api/version`, 5 ms). They
are skipped unless `EKTE_BENCH=1`; run them serially, so the timings are not
shared with other tests:

```bash
EKTE_BENCH=1 pytest tests -m slow -p no:xdist
EKTE_BENCH=1 EKTE_BENCH_REPORT=bench.json pytest tests -m slow -p no:xdist
python scripts/bench_report.py bench.json   # the Markdown table
```

- **Measurement.** Every case is measured the same way
  (`tests.bench_report.measure()`, which uses `times()` and `p95()` of
  `scripts/bench_fixture.py`): one warm-up call, then 40 timed calls; p50 is
  the median, p95 the nearest rank (the 38th of 40). Before a case the
  garbage collector collects and freezes what is alive (`gc.freeze()`), so a
  full collection during the calls does not scan the test session's heap; it
  stays on for the objects the calls themselves create. A new budget test
  times its cases with `measure()`.

- **Budgets.** 50 ms p95 by default, the budget of the reference machine;
  `EKTE_BENCH_BUDGET_MS` overrides it. A case with a budget of its own has
  its own variable: `/api/version` (5 ms, `tests/test_web_version.py`)
  reads `EKTE_BENCH_VERSION_BUDGET_MS`. A new budget test
  reads its budget with `tests.bench_report.budget()` (a case with its own
  budget passes its own variable) and takes the `bench_data` fixture
  (`tests/conftest.py`): the 20k-run fixture, built once per pytest session
  and shared, read only.
- **Report.** With `EKTE_BENCH_REPORT=<path>` every budget test adds each
  case's p50, p95 and budget to that JSON file (`tests.bench_report.record()`,
  called before the test asserts, so failing cases are in it too);
  `scripts/bench_report.py` renders it as a table (suite, case, p50, p95,
  budget, ✅ / ❌). Without the variable nothing is written.
- **CI.** The "performance budget" job of `.github/workflows/ci.yml` runs
  the budget tests on every pull request into `main` and `*/integration`
  (skipped when a pull request changes only `docs/**`, `*.md` or locale
  fragments), on pushes to `*/integration` and on manual runs, on one
  ubuntu runner with Python 3.12. Shared runners are slower and noisier than
  the reference machine, so the job sets its own budgets through
  `EKTE_BENCH_BUDGET_MS` and `EKTE_BENCH_VERSION_BUDGET_MS`: the smallest
  round value that the slowest case of 5 calibration runs stays under by at
  least 30 %; the values and their calibration are in the comment on the job.
  The local defaults stay 50 ms and 5 ms.
- **Reading the result.** The job's summary (the run's page on GitHub) shows
  the table: ❌ marks a case whose p95 is not below the CI budget, and fails
  the job. The JSON is the run's `bench-report` artifact (kept 14 days).
  Timings on shared runners vary by some 10-20 % between runs; a case that
  creeps towards the budget over several pull requests is worth a look before
  it fails.

## Metric registry

`ekte/web/metrics.py` is the only metric catalogue (`ekte.web.analytics`
re-exports `METRICS`, `Metric`, `MIN_RUNS`). Each `Metric` has `id`, `unit`,
`format` (`score`, `grade`, `percent`, `ms`, `tok_s`, `ratio_percent`,
`tokens`, `count`, `seconds`), `agg` (`median`, `pooled`, `share`; `count` for
the `COUNTS` runs / relays / models), `surfaces`, `higher_is_better`
(`True` / `False` / `None`) and i18n keys: `label_key` (`metric.<id>`),
`short_label_key` (`metric.<id>.short`, for narrow tiles), `kpi_label_key`
(`metric.<id>.kpi`, the label of the aggregate, e.g. "Median score") and
`agg_hint_key` (`metric.<id>.agg_hint`, how runs combine). A metric without a
short or KPI label of its own names its plain `label_key` there. The keys are
translated in the browser; their texts are in
`ekte/i18n/locales/fragments/metrics/<code>.json` (`ekte.i18n.keyed(key, lang)`
reads them in Python). `grade` is a metric: the run's grade letter on the 1..6
scale (F = 1 … A = 6, `scoring.GRADE_SCALE`), aggregated as a median.

`KPI_GRID` (the 12 Analytics tiles, 4 × 3 in reading order) and
`HISTORY_TRENDS` (`score`, `grade`, `latency_p50`, `ttft_p50`, `decode_tps`,
`error_rate`) are named lists here, not in the pages. `GET /api/metrics`
(cached, ETag) answers `catalogue()`: `metrics` (every metric's public
fields), `kpi_grid`, `history_trends`, `max_trends`, `min_runs`, `grades`,
`families`, `directions`, `trend_keys` and `labels` (every key's English
text, for English, the key language whose bundle carries no keyed strings).

**Display semantics.** `present(metric, value, previous=None, n=None,
previous_n=None, *, surface=None) -> dict` decides on the server what the
page shows: `family` (`good`, `sky`, `warn`, `bad`, `grey`, or the neutral
series families `lat` for milliseconds and `tps` for token speeds; a score or
dimension score by its grade letter from `scoring.GRADE_THRESHOLDS`, read at
call time, a grade by its letter), `grade` (letter for scores and grades),
`delta` (value − previous), `direction` (`better`, `worse`, `neutral` for no
change or a metric without a better side, `none` without a delta or when
`previous_n` < `MIN_RUNS`; counts are always judged), `trend_key`
(`trend.rising` / `trend.falling` / `trend.unchanged`), `low_n` and `applies`
(False when the metric is not measured on `surface`: the "n/a" tiles).

## Analytics API

`ekte/web/analytics_widgets.py` answers the Analytics page's widgets (and the
filter options of both pages), one GET per widget, on top of the
[query core](#query-core) and the [metric registry](#metric-registry); the
page only draws. Every endpoint:

- takes every key of the query core's URL schema (`range`, `from`, `to`,
  `surface`, `relay`, `model`, `suite`, `mode`, `api`, `stream`, `detect`,
  `risk`, `min_score`, `exec`, `watch`, `q`, `group`) plus its own namespaced keys
  (below); other widgets' dotted keys are ignored. An unknown key (shared or
  of its own namespace), a key given twice or an invalid value answers 400
  `{"error": "..."}` (never cached);
- is cached (`cached_endpoint`, ETag / `304`): `range` is resolved first, and
  `from` without `to` gets `to` = now rounded up to the next minute;
- uses one surface: without `surface`, the most common surface of the
  selection (`query.default_surface`), named in the answer; it is counted once
  per selection and data version (`analytics_widgets.SURFACE_CACHE`, keyed
  like the answers), not once per widget;
- selects, groups and aggregates in SQLite (no endpoint loads runs or request
  records into Python), and answers in a size that grows with groups and
  buckets, never with runs.

Every answer starts with `from`, `to` (canonical ISO, or null), `surface`,
`filters` (`Query.canonical()`) and `min_runs` (3). A **cell** is
`Cell.public()`: `value`, `n` (runs with a value), `coverage` (`n` ÷ runs),
`low_n`, `median` / `p25` / `p75` (median metrics), `numerator` /
`denominator` (pooled rates); judged cells add `family` (colour family) and
`grade` (`present()`). A **group** is `key`, `label`, `kind`, `in_kb` (and
`relay`, `model` for `relay_model`), `runs`, `low_n`, `first_run`,
`last_run`. Rates are pooled (Σ outcome counts ÷ Σ judged requests), values
per run are medians, so one run gives exactly its stored value.

### `GET /api/filters/options`

The values present for each filter key, counted under the current filters
**except that key** (a selected value and its siblings stay listed):

```json
{"filters": {...}, "keys": ["surface", "relay", "model", "suite", "mode", "api", "stream", "detect", "risk", "exec", "watch"],
 "runs": 60, "surface_default": "chat",
 "surface": [{"value": "chat", "runs": 60}],
 "relay": [{"value": "cheap-gpt", "label": "Cheap GPT", "kind": "relay", "in_kb": true, "runs": 15}],
 "model": [{"value": "model-a", "runs": 40}, {"value": "(unknown)", "runs": 2}],
 "suite": [{"value": "standard", "runs": 31}, {"value": "-", "runs": 1}],
 "mode": [...], "api": [...], "stream": [...],
 "detect": [{"value": "auto", "runs": 20}, {"value": "manual", "runs": 20}, {"value": "-", "runs": 20}],
 "risk": [{"value": "inconclusive", "runs": 5}, ...], "exec": [{"value": "manual", "runs": 48}, ...],
 "watch": [{"value": "7", "runs": 9, "label": "relay check"},
           {"value": "3", "runs": 2, "label": "Deleted monitor #3", "deleted": true}],
 "span": {"first": "<iso>", "last": "<iso>"}, "dimensions": ["protocol", ...]}
```

`value` is spelled as the URL takes it (`-` = none; relays and models use
`(unknown)`, their group key); a relay's `label` is what History calls it
(`history_api.relay_labels`: its knowledge-base name, else the host of its
URL); a monitor's (`watch`) is its name, read from `watches.db` once per
request, or, for a monitor that no longer exists, `Deleted monitor #<id>`
with `deleted: true` (the panel shows it translated); the widget endpoints'
`prepare` adds the monitors' data version (`options.watches`,
`watches.data_version()`) to the cache key, so a renamed or deleted monitor
gets a new answer and `ETag` although the history did not change. `watch` lists only
monitor runs, so its counts add up to `exec=monitor`'s. Lists are ordered by
runs, then label / value.
`runs` counts the full selection; `span` is the first and last run under
every filter except `from` / `to`; `dimensions` lists the `dim:<key>` keys of
the selection. The surface is not defaulted here: `surface_default` names the
one the widgets would use. One statement: the runs matching `min_score` / `q`
are read once; `relay` (by relay id), `model` and `watch` are a `GROUP BY` over them,
and the other lists, `span` and `runs` are folded from one `GROUP BY` of each
run's facet combination (`history_metrics.facet_id`, `ekte/web/run_row.py`).

### `GET /api/analytics/summary` (`kpi.*`: none)

The 12 tiles of `KPI_GRID` in order (runs, relays, models, score,
risk_high_share, success_rate, error_rate, latency_p50, ttft_p50,
decode_tps, billing_ratio_prompt, billing_ratio_completion), for the range
and the previous range (none without `from`): for a day range the N calendar
days before it in `tz` (`[from − N days, from)`), otherwise the span of the
same length before `from`. A day range's answer has `"to": null` (no end
bound); the page labels it up to today ("Oct 12 – Nov 10"):

```json
{..., "previous": {"from": "<iso>", "to": "<iso>"} | null, "runs": 30,
 "tiles": [{"id": "error_rate", "value": 0.05, "n": 30, "coverage": 1.0, "applies": true,
            "previous": 0.04, "previous_n": 30, "delta": 0.01, "direction": "worse",
            "trend_key": "trend.rising", "family": "grey", "grade": null, "low_n": false,
            "numerator": 30, "denominator": 600, "format": "percent", "label_key": "metric.error_rate"}]}
```

`applies: false` (a chat-only tile on another surface) has `value`, `n`,
`coverage`, `previous`, `previous_n` null: the page shows "n/a" in its slot.
`success_rate + error_rate + rate_limited_rate = 1` whenever there is a judged
request (same denominator). The counts have `n` = runs and are always judged.

### `GET /api/analytics/series`

One metric per group (`group`) over time: `trend.metric` (default `score`;
`dim:<key>` too), `trend.bucket` `hour|day|week` (default `day`), `trend.tz`
(IANA, default the shared `tz`), `trend.key` (repeatable, up to 4 series keys; default the
busiest groups). The answer is `SeriesResult.public()`: `metric`
(`Metric.public()`), `group`, `bucket`, `tz`, `span_days`, `series` (a group
plus `n`, `coverage`, `mixed` {suite, stream_mode, api}, `annotations`
(ekte version / knowledge-base profile changes) and `points`: `bucket` (local
ISO start), `runs` and a judged cell with quartiles).

`trend.ahead` asks for a forecast that many buckets on: `12` or `24` for
`hour`, `3` or `7` for `day`, `2` or `4` for `week`; `0` or absent for none.
Another value is a 400 naming the key. Each series then carries `forecast`
(`null` without `trend.ahead`), computed by `ekte/web/forecast.py` from the
series' own buckets (no extra query; the module docstring has the method and
its constants):

```json
{
  "status": "ok",
  "ahead": 7,
  "buckets_used": 9, "buckets_needed": 6, "dropped": 0,
  "since": "2026-11-01T00:00:00+01:00",
  "step": "2026-11-01T00:00:00+01:00",
  "slope": 8.1, "slope_se": 1.9, "clear": true, "direction": "worse",
  "start": {"bucket": "…", "value": 0.0, "p25": 0.0, "p75": 0.0},
  "points": [{"bucket": "…", "value": 0.0, "p25": 0.0, "p75": 0.0}]
}
```

`status` is `ok`, `few_buckets` (fewer than `buckets_needed` buckets with 3 or
more runs since the last annotation or detected step) or `not_median` (a
`pooled` or `share` metric: no p25 / p75 to project); with any other status
than `ok` only `status`, `ahead`, `buckets_used` and `buckets_needed` are set.
`since` is the first fitted bucket, `step` the bucket a detected jump starts
(or `null`), `dropped` the odd buckets left out, `slope` / `slope_se` the
line's slope and its standard error in metric units per bucket, `clear`
whether `|slope| > 1.28 × slope_se`, `direction` that trend judged as for a
KPI change (`better`, `worse`, `neutral` for a metric without a better side,
`none` without a clear trend). `start` is the last fitted bucket (its
median and p25 / p75, so the forecast joins the history); `points` are the
`ahead` buckets after the series' last bucket, keyed like `points[].bucket`
(local calendar days and Mondays, DST-safe).

### `GET /api/analytics/heatmap`

The weekday × time-of-day grid of one metric: `heat.metric`, `heat.block`
(hours per row 1, 2, 3, 4, 6), `heat.fold` (`week`, `4weeks`, `month_week`;
falls back to `week` until the runs cover 90 / 180 days: `fold` vs
`fold_requested`), `heat.tz` (default the shared `tz`), `heat.key` (one series key of `group`; default
all selected runs as one series of group `all`). Same shape as `series` with
`bucket: "dow_hour"`, `block`, `fold`; each point has `dow` (1 = Monday),
`hour`, `hours` (block > 1) and `week` (folds).

### `GET /api/analytics/leaderboard`

`board.by` `relay|model|relay_model` (default `relay`): one row per group
with the cells of `BOARD_METRICS` that apply to the surface (score,
success_rate, error_rate, latency_p50, ttft_p50, decode_tps, billing ratios,
model_mismatch_rate, risk_high_share), best median score first (no score
last). Relays of one model: `model=<m>&board.by=relay`. Answer: `by`,
`metrics` (`Metric.public()`), `rows` (group + `metrics` {id: judged cell}).

### `GET /api/analytics/breakdown`

`breakdown.metric` (repeatable, 1–8 ids, `dim:<key>` too) per group
(`group`, `all` included) over the range, busiest group first, cells with
quartiles. Answer: `group`, `metrics`, `runs`, `rows` (as the leaderboard).

### `GET /api/analytics/errors`

The selected runs' target requests by outcome (`history_outcomes`, all ops,
read from each run's row: `history_metrics.outcome_<class>`;
classes `success`, `rate_limited`, `relay_timeout`, `relay_5xx`, `relay_4xx`,
`relay_other`, `network`, `local`), per group (`group`), in total and per
time bucket of the run's start: `errors.bucket` `hour|day|week|dow_hour`
(default `day`), `errors.block` (dow_hour), `errors.tz` (default the shared `tz`); `errors.run=<id>`
adds that run's per-minute timeline from its request records (`OUTCOME_SQL`:
`errorclass.outcome()` in SQL over `error_class`, `error_type`, `status_code`,
`retried`, `phase`; repeated attempts and `param_retry` never count).

```json
{..., "group": "relay", "bucket": "day", "block": 1, "tz": "UTC", "classes": [...8 classes],
 "runs": 60, "covered": 58, "coverage": 0.97, "totals": <shares>,
 "groups": [{<group>, "runs": 15, "covered": 15, "coverage": 1.0, "low_n": false, ...<shares>}],
 "buckets": [{"bucket": "<local ISO>", "dow"?, "hour"?, "hours"?, "runs": 2, "covered": 2, "low_n": true, ...<shares>}],
 "run": {"id": 7, "minutes": [{"minute": 0, ...<shares>}]}}
```

`<shares>` is `counts` {class: n}, `requests` (all), `judged` (all − network
− local), `shares` {class: relay classes over judged, network / local over
all}, `success_rate`, `rate_limited_rate`, `relay_error_rate`,
`timeout_rate` (over judged; the first three add up to 1) and
`impaired_rate` (network + local over all), so the page can grey out network
and ekte failures. `covered` = runs with outcome counts. One statement for
groups and buckets.

### `GET /api/analytics/integrity` (`integrity.*`: none)

One row per relay × model: `checks` {detector: `pass`, `warn`, `fail`,
`other` (not judged), `n` (judged), `pass_rate`, `low_n`} for the
`INTEGRITY_CHECKS` any selected run has, `model_mismatch` (a share cell) and
`context` (median, p25, p75 of effective ÷ declared context window over the
runs that measured both, `n`, `coverage`, `claimed`, `effective`; chat only).
Answer: `runs`, `checks` (column order), `has_context`, `rows`.

## History API

`ekte/web/history_api.py` computes the History page's widgets on the server,
on top of the [query core](#query-core) and the [metric registry](#metric-registry),
so the page only draws. Both endpoints are cached (`cached_endpoint`, ETag /
304; `range` is resolved first), take every key of the query core's URL
schema with `group=relay_model` as the default (also `relay`, `model`,
`all`), ignore the dotted keys of other widgets and answer 400
`{"error": "..."}` for an invalid value or an unknown key of their own
namespaces. No endpoint loads the runs into Python: groups are one aggregate
pass per group and base URL, rows are keyset pages.

**Order** (`groups.sort`, `runs.sort`): `time`, `risk`, `score` or `grade`,
descending with a leading `-` (default `-time`). The value is the run's start
time (`history_metrics.started_at`), its risk (clean < inconclusive < low <
medium < high; no risk level is inconclusive), its score, or its grade
(F < E < D < C < B < A). Runs without a value come last in either direction;
ties go to the most recently saved run (higher id). Rows are in that order in
their group, and groups are ordered by their first run under it, as the page
always sorted. Cursors (`after`) are opaque and belong to one sort.

**Relay labels.** A saved relay or provider is called by its name; an unsaved
URL by its host with port, or, when several unsaved URLs share host and port,
by host, port and path (no scheme, no trailing slash). Computed once per
`relay_map` content over every URL in it (`relay_labels(conn)`,
`url_labels(urls)`, `host_of(url)`, `url_place(url)`).

### `GET /api/history/groups`

| Key | Values |
|---|---|
| `trend.metrics` | required: 1 or 2 ids of `HISTORY_TRENDS` (`score`, `grade`, `latency_p50`, `ttft_p50`, `decode_tps`, `error_rate`), comma-separated or repeated; 0, 3, a duplicate or another id is a 400. Answered in `HISTORY_TRENDS` order |
| `groups.sort` | see **Order** |
| `groups.limit` | 1–200, default 20 |
| `groups.after` | the previous page's `after` |
| `groups.focus` | a run id: the page grows (whole pages) until it holds that run's group |

```json
{
  "group": "relay_model", "sort": "-time", "limit": 20,
  "trend_metrics": ["score", "latency_p50"], "points_max": 50, "min_runs": 3,
  "total_groups": 37, "total_runs": 1204,
  "after": "<cursor or null>",
  "focus": {"id": 812, "found": true, "key": "https://relay.example/v1|gpt-4o"},
  "groups": [{
    "key": "https://relay.example/v1|gpt-4o",
    "kind": "relay_model",
    "label": "relay.example · gpt-4o",
    "relay": {"key": "https://relay.example/v1", "label": "relay.example", "kind": "url", "in_kb": false},
    "claimed_model": "gpt-4o",
    "base_urls": ["https://relay.example/v1"],
    "runs": 42, "low_n": false,
    "latest": {"<run row, as in /api/history/runs>": "..."},
    "trends": {
      "score": {
        "metric": "score", "points": [81.5, 84.0, 79.0], "first": 81.5, "n": 3,
        "last": {"value": 79.0, "family": "sky", "grade": "C", "delta": -2.5,
                 "direction": "worse", "trend_key": "trend.falling", "low_n": false, "applies": true}
      }
    }
  }]
}
```

`focus` is null without `groups.focus`; otherwise `found` says whether the
page holds the run's group (`key`). For a run that is not among the filtered
runs, see **The `focus` answer** below. `relay` is null for `group=model|all`, `claimed_model` null for
`relay|all` (and for runs without a claimed model). `label` is the relay label
(`relay`), the model (`model`), `(all)` (`all`) or `<relay label> · <model>`,
with `(unknown)` for a missing part. `base_urls` lists the group's URLs, the
most recently used first. `latest` is the group's newest run (start time,
then id). Trend `points` are the stored per-run values (`score`, the grade on
the 1..6 scale, `latency_p50_ms`, `ttft_p50_ms`, `decode_tps_p50`, the run's
#118 `error_rate`; a run with no judged request has none) of the group's
newest 50 runs, oldest to newest, runs without a value left out; `first` /
`last.value` / `n` are what the accessible description reads, and `last` is
`present(metric, last, first, n=n, surface=<surface filter>)`.

### `GET /api/history/runs`

| Key | Values |
|---|---|
| `group.key` | required: a group's `key` (under the same `group` and filters) |
| `runs.sort` | see **Order** |
| `runs.limit` | 1–200, default 20 |
| `runs.after` | the previous page's `after` |
| `runs.focus` | a run id: when it is in this group after the cursor, the page grows (whole pages of `runs.limit`) until it holds it |

```json
{
  "group": "relay_model", "key": "https://relay.example/v1|gpt-4o", "sort": "-time",
  "limit": 20, "total": 42, "after": "<cursor or null>",
  "focus": {"id": 812, "found": true},
  "rows": [{
    "id": 812, "ts": "2026-11-01T09:12:40+00:00",
    "started_at": "2026-11-01T09:10:02.000000+00:00", "started_at_estimated": false,
    "base_url": "https://relay.example/v1", "relay_key": "https://relay.example/v1",
    "claimed_model": "gpt-4o", "model": "gpt-4o", "mode": "check", "suite": "standard",
    "surface": "chat", "api": "openai", "api_auto": true, "detect": "auto", "stream_mode": "stream",
    "risk_level": "clean", "score": 84.0, "grade": "B", "kb_match": "match",
    "family": {"risk": "good", "score": "good", "grade": "good"},
    "watch_id": null, "exec": "manual",
    "latency_p50_ms": 812.4, "ttft_p50_ms": 301.0, "decode_tps_p50": 61.2, "error_rate": 0.02
  }]
}
```

`limit` is the page size actually used (larger than asked when `runs.focus`
grew it); `total` counts the group's runs under the filters; `focus` is null
without `runs.focus`. `risk_level` is `inconclusive` for a run without one,
`mode` `check` for one without, `detect` `auto` / `manual` / null and `exec`
`manual` / `monitor`; `family` holds the colour families of the risk badge,
score and grade (`metrics.family`).

### The `focus` answer

`groups.focus` and `runs.focus` name a run by its id, whatever the filters.
The answer's `focus` is:

| The run | `focus` |
|---|---|
| on the page (the groups' page holds its group; the runs' page holds it) | `{"id": 812, "found": true}`, plus `"key"` for `groups` |
| among the filtered runs but not on this page (`runs`: another group, or before the cursor) | `{"id": 812, "found": false}` |
| exists, outside the filters | `{"id": 812, "found": false, "outside": true, "started_at": "2026-08-14T09:10:02.000000+00:00", "by_range_only": true, "excluded_by": ["range"]}` |
| does not exist | `{"id": 812, "found": false}` |

`started_at` is the run's start (UTC, as in its run row; null without one).
`excluded_by` lists the URL keys of the filters that leave the run out, in
the schema's order (`range` stands for `range` / `from` / `to`; filters are
ANDed, so the run matches them all exactly when it matches each);
`by_range_only` is `excluded_by == ["range"]`: the run matches every other
filter. Costs one statement on the run's own row (by its id) with one
`EXISTS` per filter set, and only when the run is not on the page; no extra
query over the runs.

History widens the range when `by_range_only` is true: `range=` (empty), `from`
= 00:00 of the run's day in the viewer's zone, written with its UTC offset
(`2026-08-14T00:00:00+02:00`: a bare `YYYY-MM-DD` would be read as UTC
midnight), no `to`, every other filter and the focus kept; the page notice
says "Range widened to show run #n" once. Otherwise the notice says "Run #n
doesn't match the current filters", and its "Show it" clears the filters in
`excluded_by` (the range widened as above when it is one of them), keeping
the focus.

### `GET /api/history/{rid}?trend=1`

Besides the running request medians, the report gains `history_trends`:
`{metric id: present(...)}` for every `HISTORY_TRENDS` metric, from the same
per-run SQL as the group trends, so a group of that run alone shows exactly
these values (and `query.aggregate` over that run gives the same, n = 1).

The History page reads only these endpoints (#127); the old internal
`GET /api/history` (the newest ≤ 500 runs, `limit` / `perf` / `relay`) is
gone. `GET /api/v1/history` is part of the public API and keeps its shape
(`limit`, `perf`); with `perf=1` the headline (`latency_p50_ms`,
`ttft_p50_ms`, `decode_tps_p50`) comes from the run's `history_metrics` row,
the one store of those values since schema version 13 dropped the copies on
`history` (#128).

## Monitors API

`ekte/web/watches_api.py` answers the Monitors page in the shared pattern:
filtered on the server, cached, no live state.

- **`GET /api/watches?<keys>`**: the monitors matching the filters, newest
  first, as a JSON list. Rows never contain an API key (`has_key` and
  `key_status` say whether one is set) and carry no live run state. Each row
  has `state`, `alerting`, `relay_key` and `relay_label` besides the stored
  settings.
- **`GET /api/watches/options?<keys>`**: `{"filters", "keys", "monitors",
  "<key>": [{value, monitors, label?}]}` for `surface`, `relay` (with its
  `label`), `model`, `suite`, `api`, `stream`, `state` and `alerting`.
  Counts are **monitors**, each list under every filter but its own (as
  `/api/filters/options` counts runs), most monitors first; `monitors` is
  how many match every filter.

| Key | A monitor matches when |
|---|---|
| `q` | the text is a substring (ASCII case-insensitive) of its name, base URL, relay label, claimed model, model or suite |
| `surface` | its surface is the value |
| `relay` | its `relay_key` (the relay its runs are grouped under) is one of the values; repeatable |
| `model` | its claimed model, else its model (`(unknown)` without either), is one of the values; repeatable |
| `suite`, `api`, `stream` | its suite / resolved protocol (`api_resolved`) / probe request mode (`stream_mode`) is the value; `-` for none |
| `state` | `active` (enabled, set up), `paused` (set up, disabled) or `draft` (scheduled from History, no interval yet; the key stays optional) |
| `alerting` | `yes`: its last run's risk is at or above its `alert_on` threshold (`watches.risk_meets`, the rule the scheduler alerts on); else `no` |

The shared keys are validated by `query.parse_query` (same values and
errors). Any other key, the run-only keys `range`, `from`, `to`, `risk`,
`exec`, `group`, … and dotted widget keys included, is a 400
`unknown parameter`. Filtering runs in Python over the monitor rows (bounded
by the number of monitors, not runs); relays and knowledge-base profiles are
resolved once per request. Budget: 50 ms p95 with 200 monitors, cold cache
(`tests/test_watches_api.py`).

**Caching.** Both go through `cached_endpoint` (ETag, `Cache-Control:
no-cache`, 304). Besides the history data version and the knowledge-base
relay version, `watches_api.resolve_params` (the `prepare`) adds a token of
what else the rows depend on: `watches.data_version()` (a monitor created,
edited, deleted or run), the master key held and the keys held in memory
(`key_status`), the audit knowledge base (`kb_changed`), the phase of every
run window (`in_window`, `next_window_ts`) and the server process.

**Live state** (running, queued, progress) is `GET /api/jobs`: a running
monitor is the job `monitor-<id>` with `kind: "monitor"`, `watch_id`,
`status` (`queued` while it waits for its relay, then `running`),
`progress` (percent, `null` while queued), `done`, `total`, `current` and
`waiting_for`. The Monitors page reads both and merges them by `watch_id`.

## HTTP API v1

The public part of the HTTP API lives under `/api/v1/` and follows the [stability policy](../reference/stability.md#surface-http-api): it changes incompatibly only in a major release, after a deprecation period. Every other path under `/api/` is internal and may change in any release. Internal responses carry `X-Ekte-API: internal`, v1 responses `X-Ekte-API: v1`. The web UI uses the internal paths.

| Endpoint | Request | Response |
|---|---|---|
| `POST /api/v1/jobs` | JSON body with `base_url`, `model` and optionally `api_key`, `claimed_model`, `suite`, `surface`, `dimensions`, `baseline`, `evidence` (`false`: keep no raw request/response pairs) | 200 and the job; 400 for bad input |
| `GET /api/v1/jobs/{id}` | none | 200 and the job; 404 for an unknown id |
| `GET /api/v1/jobs/{id}/events` | none | 200 and `text/event-stream`: the job's events so far, then live, ending with `done`; 404 for an unknown id |
| `GET /api/v1/history` | optional `limit` (1–500, default 50) and `perf` | 200 and a JSON array of run summaries, newest first |
| `GET /api/v1/history/{id}` | none | 200 and the saved report as stored; 404 for an unknown id |
| `GET /api/v1/history/{id}/evidence` | none | 200 and the run's evidence file (`application/zstd`); 404 for an unknown id or a run that kept none |
| `POST /api/v1/history/{id}/rescore` | none | 200 and a job (as `POST /api/v1/jobs`, with `rescore_of`) that re-scores the run from its evidence file with this ekte version and saves the result as a new run; 404 for an unknown id; 409 when the run kept no evidence or the file cannot be replayed |
| `GET /api/v1/history/{id}/evidence/export` | optional `format` (`har` (default), `curl`, `json`) and `seq` (repeatable) | 200 and the exchanges as an attachment: HAR 1.2, a curl script that sends the requests again (the key from `$EKTE_API_KEY`) or one JSON document; 400 for an unknown format; 404 as above; 409 as below |
| `GET /api/v1/history/{id}/evidence/exchanges` | optional `seq`, `id` or `detector` | 200 and `{"run_id", "file", "verified", "exchanges"}`: without `seq` / `id` a listing without bodies (`verified`: the file's SHA-256 is the one the report names), with `seq` the full pairs of that request record, with `id` one pair; 404 for an unknown run or exchange, or a run that kept none; 409 for a file of an unknown major schema version |

A job has `id`, `status` (`queued`, `running`, `done`, `error` or `cancelled`), progress fields, `report_id` once the report is saved, and `error`; the API key is never returned. Each event is an SSE line `data: {JSON}` with a `type`; the `report` event carries the report and its `report_id`, and `done` is always the last event. Clients ignore event types and fields they do not know.

Every error is JSON with one field, `error`, with a human-readable message, and one of these status codes: 400 (bad request), 404 (not found), 409 (evidence file of an unknown schema version), 403 (cross-site or cross-origin request refused), 415 (body is not JSON), 421 (unknown Host).

```json
{"error": "not found"}
```

- **Local only.** The protections of the web server apply to `/api/v1/` as to every path: loopback binding by default, the Host check, the refusal of cross-site writes and JSON-only bodies. They answer in the same error format.
