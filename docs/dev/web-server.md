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
  unlock, lock, reset, storage mode) and `GET /api/health` answers a liveness
  check. All of these are internal; the public subset is [HTTP API v1](#http-api-v1).
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
  400 (never cached).
- **Response cache** (`ekte/web/cache.py`). Widget endpoints are plain `def`
  handlers wrapped in `@cached_endpoint("<name>")`: the handler gets its query
  parameters in canonical form (keys sorted, values stripped, empty ones
  dropped) and returns JSON. The key is `json([endpoint, params,
  data_version, kb_version, EXTRACT_VERSION, database])`, with no time slot:
  `history.data_version()` is a counter in `history.db`'s `meta` table bumped
  in the same transaction as every write (`save`, `delete`, `clear`, the
  analytics and perf backfills), from any process, so a CLI audit drops the
  cache too; `kb_version` is `ekte.knowledge.relays.kb_version()`. A handler
  whose answer depends on the clock resolves it first (`prepare=`; e.g. the
  summary's `from` without `to` gets `to=now`). The LRU (`ResponseCache`,
  256 entries by default) is thread-safe and single-flight: concurrent misses
  on one key wait for one computation; errors are not cached. Answers carry
  `ETag` (a hash of the key and the ekte version) and `Cache-Control: no-cache`;
  a matching `If-None-Match` gets `304 Not Modified` without computing.
  Reads use `datadir.read_connection(name)`: one reused read-only connection
  per thread (`mode=ro`, WAL, `query_only`), schema-checked only on the first
  open in the process (again if the file was replaced); writes keep using
  `datadir.connect`.
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
| `range` | `24h`, `7d`, `30d`, `90d`, `365d`: `to` = now rounded up to the next minute, `from` = `to` − range; not with `from` / `to` | History `days`, Analytics range presets |
| `surface` | `chat`, `embedding`, `rerank` (NULL reads as chat); empty: all surfaces | both |
| `relay` | a relay key (`relay_map.relay_key`, `(unknown)` without URL), repeatable | both |
| `model` | a claimed model (`(unknown)` without one), repeatable | both |
| `suite`, `mode`, `api`, `stream` | the exact value (`stream` is the stored `stream_mode`), or `-` | History `suite/mode/api/stream`, Analytics `stream_mode` |
| `detect` | `auto`, `manual`, `-` | History `detect` |
| `risk` | `clean`, `low`, `medium`, `high`, `inconclusive` (no risk level is inconclusive) | History `risk` |
| `min_score` | 0–100 (runs without a score are left out) | History `min` |
| `exec` | `manual`, `monitor` | History `exec` (`adhoc`), Analytics `source` |
| `q` | substring, case-insensitive for ASCII (SQL `LIKE`, `%` `_` `\` literal) of base URL, relay label, claimed model, model, suite, mode, api | History `q` |
| `group` | `relay` (default), `model`, `relay_model`, `all` | both |

Keys with a dot belong to one widget (`trend.metric`, `runs.sort`,
`runs.after`) and are ignored by the shared parser; any other unknown key is a
400 error naming it. `parse_query(params, now=None) -> Query` validates
(`QueryError`, an `AnalyticsError`, so the existing 400 handling catches it);
`Query.canonical()` is the sorted, resolved form and `Query.params()` its URL
pairs. `resolve_params` is the `prepare=` of `cached_endpoint`, so a relative
range is cached under its absolute bounds. History's time filter moves from
the save time (`ts`) to the run's start (`started_at`).

**Selection.** `select_runs(q) -> RunSelection` (`.sql` = `FROM … WHERE …`,
`.args`, `.and_where()`) over `history h` (through `idx_history_query`, so
only `history.QUERY_INDEX_COLS` may be used), `history_metrics m` and, only
when needed (text search), the run's relay `rm` (`relay_group`, joined on the
run's `m.relay_id`). Relay filters and grouping use `m.relay_id` itself:
runs are grouped by integer relay id (and model), and only the resulting
groups are joined to their relay. `count_runs`, `default_surface` (the most common
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
registered (`sql_functions`).

**Series.** `series(conn, q, metric, group=None, bucket="day", tz=UTC, *, keys=(),
block=1, fold="week", max_keys=4, quantiles=False) -> SeriesResult` buckets in
SQL: the zone's UTC offset is a `CASE` over its transitions in the data's span
(`offset_sql`), and buckets are integer arithmetic on the run's local time in
seconds, so hour / day / week / `dow_hour` (with `block` and `fold`) buckets
and their values match `analytics.series`. Annotations (ekte version and
knowledge-base profile changes) come from each bucket's smallest and largest
value: only the runs of buckets where a value can change are read. Only
bucket rows (and those runs) reach Python.

**Paging.** `page_runs(conn, q, sort="-time", after=None, limit=20) -> Page`:
`sort` is `time`, `score`, `risk` or `grade`, `-` for descending, ties by id;
`after` is the opaque cursor of the previous page (`Page.after`, None on the
last); `limit` 1–200. Keyset paging, so a run saved meanwhile never shifts
pages; rows are `PAGE_COLUMNS` (the list columns, the relay, headline values).

**Benchmark.** `scripts/bench_fixture.py --data-dir DIR --bench` writes a
synthetic history (20,000 runs, 50 relays, 100 requests per run, 16 kB
reports, an ekte release every 3 weeks rolled out over 2 days, a profile
change every 45 days) and prints p50 / p95 (nearest rank, 40 calls) of
`aggregate`, `series` and `page_runs`;
`EKTE_BENCH=1 pytest -m slow tests/test_query.py` checks the 50 ms p95 budget
(`EKTE_BENCH_BUDGET_MS`).

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
