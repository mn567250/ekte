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
  `/api/watches…`, `/api/kb…` and `/api/analytics…` back the other pages. All of these are internal; the public subset is [HTTP API v1](#http-api-v1).
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

## HTTP API v1

The public part of the HTTP API lives under `/api/v1/` and follows the [stability policy](../reference/stability.md#surface-http-api): it changes incompatibly only in a major release, after a deprecation period. Every other path under `/api/` is internal and may change in any release. Internal responses carry `X-Ekte-API: internal`, v1 responses `X-Ekte-API: v1`. The web UI uses the internal paths.

| Endpoint | Request | Response |
|---|---|---|
| `POST /api/v1/jobs` | JSON body with `base_url`, `model` and optionally `api_key`, `claimed_model`, `suite`, `surface`, `dimensions`, `baseline` | 200 and the job; 400 for bad input |
| `GET /api/v1/jobs/{id}` | none | 200 and the job; 404 for an unknown id |
| `GET /api/v1/jobs/{id}/events` | none | 200 and `text/event-stream`: the job's events so far, then live, ending with `done`; 404 for an unknown id |
| `GET /api/v1/history` | optional `limit` (1–500, default 50) and `perf` | 200 and a JSON array of run summaries, newest first |
| `GET /api/v1/history/{id}` | none | 200 and the saved report as stored; 404 for an unknown id |

A job has `id`, `status` (`queued`, `running`, `done`, `error` or `cancelled`), progress fields, `report_id` once the report is saved, and `error`; the API key is never returned. Each event is an SSE line `data: {JSON}` with a `type`; the `report` event carries the report and its `report_id`, and `done` is always the last event. Clients ignore event types and fields they do not know.

Every error is JSON with one field, `error`, with a human-readable message, and one of these status codes: 400 (bad request), 404 (not found), 403 (cross-site or cross-origin request refused), 415 (body is not JSON), 421 (unknown Host).

```json
{"error": "not found"}
```

- **Local only.** The protections of the web server apply to `/api/v1/` as to every path: loopback binding by default, the Host check, the refusal of cross-site writes and JSON-only bodies. They answer in the same error format.
