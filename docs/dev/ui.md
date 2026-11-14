# Web front end

The front end is plain HTML, CSS and browser JavaScript without modules or a
build step. The pages live in `ekte/web/static/v2/` and share one header (`nav.js`), the report renderer
(`report.js`), the theme switch (`theme.js`) and the styles (`tokens.css`, `ekte.css`,
`fields.css`, `report.css`, `perf.css`). Shared scripts are served from the root:
`lang.js` (language switch), `locales.js` (translation data), `i18n.js` (finding
translations), `icons.js` (including the ekte logo), `secretfield.js` and
`perf.js` (performance charts).
Every color of the v2 UI, in both themes, is a token in `v2/tokens.css`
(written once as `light-dark(<light>, <dark>)`); all other v2 styles, pages and
scripts use `var(--…)` only, never a literal color.

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
The custom suite's **Dimensions to run** chips are `v2/dimpick.js`. The
"Running" list of background audits and running monitors (`GET /api/jobs`) is
`v2/jobs.js` with `v2/jobs.css`, shared by the Audit and Monitors pages. The
Knowledge page draws each of its three tabs with one section component,
`v2/kbsection.js`, on top of the DOM-free helpers in `v2/kbview.js`.

The v2 **Analytics** page (`v2/analytics.html`, #126) only draws: every
number, grade, colour family, delta direction (`direction`, `trend_key`) and
request outcome class comes from `/api/analytics/*`, `/api/filters/options`
and `/api/metrics` (`docs/dev/web-server.md`, "Analytics API"); labels are the
registry's i18n keys (`EkteFilters.keyed`), values are formatted by the
metric's `format`. It has one `<section class="card panel">` per panel under
the shared filter panel (`EkteFilters`: range, surface, relay, model, suite,
protocol, probe requests, execution and the page-wide **Group by** `group`),
so new panels slot in. The **KPI grid** is the summary's 12 `tiles` in
`KPI_GRID` order, always 4 columns × 3 rows (2 columns below 600 px); a tile
with `applies: false` keeps its slot and shows "n/a" ("Not measured on this
surface"); the delta's colour and word follow `direction` (`none`: faded,
with the "previous period has fewer than N runs" note); the count-up figure is
`aria-hidden` beside a screen-reader value; pooled rates (`agg: "pooled"`)
have a toggletip with the metric's `agg_hint` (hover and focus, hoverable,
Escape hides it). The **errors** panel stacks the relay's outcome classes over
the calls it answered (429, relay timeout, 5xx, 4xx and other) and keeps
network and ekte failures apart, greyed out in legend and tables (they are not
the relay's fault), with the relay error rate and the impaired share shown
separately. Its charts come from
`v2/charts.js` (`EkteCharts.timeChart`: hand-drawn inline SVG with median line,
p25–p75 band, gaps for empty buckets, faded markers for `low_n` buckets,
annotation lines and a hover tooltip; `fmt` / `fmtDelta` format values by unit)
and `v2/charts.css` (four validated series colors per theme, told apart by
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
the accessibility report; their `k-*` colors (who decides a step: blue the
test suite, violet a person) come from `tokens.css`. `v2/chartmotion.js`
(`EkteMotion.enter`, styles in `v2/chartmotion.css`) draws a donut clockwise and grows meters from the left,
like every other chart, only when new data arrives and never under reduced
motion or the header's "Motion off".

The **performance timeline** (`perf.js` `chartSvg`) is one chart for the live
panel of a running audit and for the report view; the downloaded HTML and PDF
reports draw the same plot from `ekte/report/performance.py` `Timeline` (inline
SVG there, ReportLab in `ekte/report/pdf.py`), including each endpoint's running
median and p25–p75 band (`ekte/perf/trend.py`). Its time axis ends where the
last request ended (`timeAxis` / `time_axis`: no rounded-up end; ticks only
where their label fits). It sweeps in like the other line charts (the band
grows out of its line). While an audit runs, the live panel's time axis creeps
on with the clock between requests (`Live.creep`: one animation frame at a
time, positions only, never the accessible name); when an axis changes, the
requests slide to their new place and the line and band morph
(`EkteMotion.rescale`). With reduced motion or "Motion off" none of it runs:
the axis ends at the last request and changes only when one lands.
`Live.stop()` (the audit's end) brings it back to the last request.

The page header and the filter panel sit above five in-page tabs
(`v2/tabs.js`, as on Knowledge): each `PANELS` entry names its `tab` (and
sub-tab) and the URL namespaces it reads, and only the shown panels load, each
with its own `AbortController` and all at once through
`EkteFilters.fetchWidget`; a filter change reloads them and marks the others
stale (`activate()` loads them when shown), a widget key (`trend.*`, `heat.*`,
`board.*`, `errors.*`, `bill.*`) reloads its panel only. The whole view is the
URL query string (`EkteFilters`): shared filters, widget keys sent to their
endpoint, page-only keys no endpoint reads (`bill.metric`, `lb.sort`,
`table.*` for open data tables) and the view keys `tab`, `os` / `ts` / `rs`
(sub-tabs); **Copy link to this view** in the panel's foot copies it. Old
`#tab=…` fragment links open the defaults. The collapsible filter
panel is `v2/filterpanel.js` + `v2/filterpanel.css`, shared with History, Monitors and Knowledge:
`EkteFilterPanel.create(section, {label, title, storeKey, open, onReset})`
returns `render({body, foot, count, summary})`, `sync({count, summary})`,
`setOpen()` and `focusStart()`; the page owns its filters and fields, the panel
the toggle with its active-filter badge, the one-line summary shown while
closed, the remembered open state and **Reset filters**.

The v2 **History** page (`v2/history.html`, #127) only draws: groups, their
trend tiles and rows come from `GET /api/history/groups` and
`GET /api/history/runs` (`docs/dev/web-server.md`, "History API"), with the
server's order, grades, colour families (`family`) and trend text keys
(`trend_key`); the page keeps layout, sparkline scaling (0–100 for scores, the
grade scale, else the points' range), number and date formatting and the
collapsed groups (localStorage). The first page of groups (20) loads with the
first page of rows of every open group; "Show more" under a group appends its
next page by cursor (`runs.after`), "Show more groups" the next groups
(`groups.after`); focus stays on the button while more remain, then moves to
the first added row or group toggle, and `#hmore` announces the count. The URL
holds the filters (`EkteFilters`), the sort (`groups.sort`, also sent as
`runs.sort`), the trends (`trend.metrics`, default `score,latency_p50`) and the
focused run (`runs.focus`: the open report or the last row "Show more"
revealed; a `#r-<id>` link sets it), sent as `groups.focus` / `runs.focus` so
a copied link shows that run again. The trend picker (in the filter panel,
`EkteFilters` `extra`) lists `history_trends` of `GET /api/metrics` by
`label_key`; `v2/trendpick.js` (`EkteTrendPick.clean / toggle / buttons`,
tested under node) keeps one or two on: with two on the others are `disabled`
and `aria-disabled`, with one on that one is, and a "2 / 2" hint next to the
label (the group's description, in words for screen readers) counts them.

**Shared filters and URL state** (`v2/filters.js`, `window.EkteFilters`, #125;
History (#127) and Analytics (#126) use it, Monitors and Knowledge keep
their own fields). One module owns the filter fields, the view state and widget
fetching, inside the `filterpanel.js` frame; it holds no metric logic.
`EkteFilters.create({section, fields, defaults, page, onChange, optionsUrl, foot, extra, live})`
(`foot`: HTML or a function returning it, `extra()`: the page's own controls
after the fields, both called on every render):
`fields` are keys of the Query core URL schema (`docs/dev/web-server.md`) the
page shows (`range` brings `from` / `to`); their types, labels, fixed values,
"(unknown)" (`-`) and the option lists of `GET /api/filters/options` (read as
`{"<key>": [{value, label?, runs?}]}`, asked with the shared filters) live in
the module.

- **The query string is the view.** It is read on load and every change is
  written with `history.replaceState` (no history entry, no reload). Shared
  filters are top-level keys, widget keys are namespaced with a dot
  (`trend.metric`, `runs.after`), view keys (`tab`) are never sent to an
  endpoint. Values equal to their default are left out (`key=` keeps an empty
  value over a non-empty default); unknown keys, invalid values and keys of
  fields the page does not show are dropped, so old links (`#hash`, `days`,
  `min`, `stream_mode`, `exec=adhoc`) open the defaults.
- `state()` is the parsed view; `widgetParams(ns)` the query string a widget
  sends, unchanged: the shared filters with a value plus its `ns.*` keys
  (`EkteFilters.state()` / `.widgetParams()` ask the page's instance).
- **localStorage is only a fallback**: the page's last filters
  (`ekte.v2.filters.<page>`) apply when the URL has no filter key, and are then
  written into the URL; every access is wrapped in try/catch.
- `load({ns: {url, done, fail}})` fetches every widget at once through
  `EkteFilters.fetchWidget(url, {signal})`: a plain `fetch` (default cache
  mode, `credentials: "same-origin"`, `Accept: application/json`) that keeps
  no copy of its own. The server's `ETag` + `Cache-Control: no-cache` make the
  browser's HTTP cache hold every answer, across reloads and pages, and
  revalidate it on each use; a `304` reaches the page as a `200` with the
  stored body. An error status rejects with an `Error` carrying `.status` and
  the server's message. History's status and report detail
  (`/api/history/status`, `/api/history/{id}?trend=1`) load through it too. A
  newer load or any filter change aborts the requests in flight
  (`AbortController`); `fail` gets one widget's error, never an abort.
- **Copy link to this view** sits in the panel's foot on every page using the
  module (a selected read-only field where the clipboard refuses).
- **Accessibility**: every field has a visible label (relay / model are
  checkbox groups named by their legend), the frame keeps focus, badge,
  summary and Reset, and each change is announced in the page's `#live`
  region ("Filters updated: N active").
- `EkteFilters.keyed(key, labels)` reads an i18n key such as `metric.score`,
  falling back to `GET /api/metrics`' `labels` (English has no keyed strings).

**Live refresh** (`v2/live.js`, `window.EkteLive`, #156; History and
Analytics load it). One poller per tab (a second copy of the script changes
nothing) asks `GET /api/version` every 10 s while
`document.visibilityState` is `visible`, and once as soon as the tab is shown
again; a hidden tab sends nothing. It is a plain `fetch`, so the browser
revalidates by `ETag` and an unchanged answer is a `304`. When a token
changes it dispatches `ekte:data` (a history write from any process, the CLI
included) and / or `ekte:live` (a job or monitor run started or ended,
monitor settings changed) on `window`, with `detail: {before, after}`; the
first answer is only the baseline. Errors are silent and the next tick asks
again. `EkteLive.start()` / `stop()` / `poll()` / `tokens()` are for tests;
`EkteLive.version()` asks once without touching the baseline. The scheduling
logic is `EkteLive.createPoller(env)`, pure (clock, request, visibility and
events passed in) and tested under node (`tests/test_web_v2_live_js.py`). No
page polls a data endpoint on a fixed interval: they refetch their own cached
URLs only on an event.

- **Analytics**, on `ekte:data`: the panels already loaded load again with the
  same view, in place and quietly. The shown ones load now, the others are
  marked stale and load when their tab is shown. `p.quiet` makes `panelLoad`
  keep the panel until the answers are in and redraw it through
  `stillRender()`: `state.still` (no count-up, no chart entry motion),
  `steady()` (the scroll position) and the panel's focused control focused
  again (by id, control attribute or place). Open tables and sub-tabs are URL
  keys, so they stay. Nothing is announced: `#live` is left alone and the page
  notice is repainted with `aria-live="off"` until the next change the viewer
  makes. The filter options update too, but not the panel while it has the
  focus. A failed quiet load keeps what is shown. A filter change aborts it
  (each panel's `AbortController`); during a filter change's own load the
  refresh waits for it. An empty page ("no audits yet") starts quietly with its
  first saved run.
- **History**, on `ekte:data`: the list never reloads by itself. The page asks
  the groups' answer for the current filters with `groups.limit=1` (a cached
  URL) and reads `total_runs`; N is that total minus the total shown. A notice
  above the list (`#fresh`, drawn by `notice.js` but no live region itself)
  says "N new runs" with **Show** (N > 0) or "History changed" with
  **Refresh**. It is announced once, politely, through `#live`; a further
  change while it is shown updates N in place without a new announcement. The
  button loads the list again (the focused run and collapsed groups kept) and
  moves focus to the focused run, else the first one. Any load of the list (a
  filter or sort change too) removes the notice. Each load notes the data
  version it shows (`EkteLive.version()`, asked before the list), so a change
  the page made itself (a delete) raises no notice.

**No business logic in pages.** History and Analytics (and every page that
shows metrics) draw what the server sends; they compute no metric, grade,
colour family, delta direction, outcome class, filter, grouping or order of
their own. The server sends values with their `grade`, `family`,
`direction`, `trend_key`, units (`format`) and label keys
(`docs/dev/web-server.md`, "Metric registry"); the page keeps only layout,
sparkline and chart scaling, number and date formatting per language,
animation and remembering the current view. A new rule (a threshold, a
classification, a new aggregate) goes into `ekte/web/metrics.py`,
`ekte/scoring.py` or `ekte/web/query.py`, never into a page;
`tests/test_metrics_e2e.py` fails when a page compares a score with a grade
threshold, an HTTP status with a code, or defines its own median.

The monitors' **Open in history** links use the schema: `surface`, `relay`
(the watch's `relay_key` from `/api/watches`, the relay its runs are grouped
under), `model` and `suite`, plus `#r-<run>`.

**Translation convention.** The pages are written in English
(`<html lang="en">`); every translatable element carries the same English
again in `data-en` (and `data-en-placeholder`, `data-en-title`,
`data-en-aria-label`). That English is the lookup key for every other
language, Chinese included: `lang.js` replaces the markup with the chosen
language's string from `ekte/i18n/locales/`, and a missing one stays English.
The server puts the language of the `ekte_lang` cookie into `<html lang>` and
the `<title>` (`ekte/web/caching.py`), so the browser tab never shows another
language while the page loads. Scripts use
`T(zh, en)` for dynamic text and `EKTE_LANG.server(text)` for text coming from
the backend (detector names, recommendations, verdict sentences).
