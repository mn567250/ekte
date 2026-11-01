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

The v2 **Analytics** page (`v2/analytics.html`) reads only `/api/analytics/*`
(`options` also lists the relay × model pairs, `relay_models`, for its series
picker). It has one `<section class="card panel">` per panel under one filter
bar, so new panels slot in; filters and view live in the URL fragment
(`#range=30&metric=score&…`) and in `localStorage`. Its charts come from
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
