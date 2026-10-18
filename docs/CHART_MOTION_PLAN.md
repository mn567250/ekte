# Chart motion and heat grid: implementation plan

Status: implemented on this branch (work packages 1–4, backend and caching);
see the CHANGELOG. Changes agreed after the prototype: the heat grid runs
upward (00:00 at the bottom, 24:00 at the top) and its block size is a
dropdown next to Metric and Relay; the running-median line has no toggle.
Prototype: [`prototypes/chart-motion/index.html`](../prototypes/chart-motion/index.html)
(open the file directly; rebuild with `python prototypes/chart-motion/build.py`).
It runs the app's own, unchanged `zing.css`, `charts.css`, `charts.js`,
`perf.css` and `perf.js` with example data, plus the new pieces listed below.

## Goals and constraints

- Subtle motion on the UI v2 charts (analytics, history performance, live view).
- No chart library and no new dependency: the charts stay hand-drawn SVG, the
  motion is CSS animations plus a small opt-in script (~4.5 KB gzipped).
- No loss in accessibility: no element added or removed, no ARIA changed; the
  temporary classes / styles / `<animate>` are removed when the motion ends,
  so the DOM at rest equals today's draw. `prefers-reduced-motion` and the
  header switch turn it off completely. Every motion is < 1 s and runs once.
- No loss in performance: only opacity, transform, stroke-dashoffset, fill and
  one SVG `<animate>` on the band path; no rAF loop; no layout reads.
- Motion plays only when the data changes (new filter, metric, range, block
  size, first draw, new live request), never on resize or a language switch.

## Agreed behaviour (from the prototype review)

| Chart | Motion / change |
|---|---|
| Line charts (`timeChart`) | Line draws left to right in one sweep; segments after a gap wait their turn; markers pop in as the sweep reaches them; the p25–p75 band grows out of the median line once its segment is drawn (SMIL `<animate>` on `d`, works in Safari); version marks fade in. |
| Stacked bars (`stackBars`) | Bars start left to right; within a bar the segments grow one after another, bottom → middle → top. |
| Heat grid (replaces `heatmap`) | Weekdays across (7 columns), time of day down in blocks of **1, 2, 3, 4 or 6 h** (default **4 h** = 7 × 6), square cells, block selector above the chart. Motion: empty outlines first, then every cell fills through the colour scale at the same pace (110 ms per step) and stops at its own step, in a wave from bottom-left (left → right, bottom → top). |
| Heat colours | Contribution-graph style in both themes: lowest step close to the card, higher = more intense. Light `#cfdef2 #9dc1ee #629ce6 #2a76ce #12549e`, dark `#1e2f44 #254974 #2b66ae #3586e6 #62aaff` (one hue, even OKLCH lightness steps, top step ≥ 7:1 on `--card`). Few-runs hatching drawn in ink so it shows on the faint steps. |
| Live view (`perf.js`) | Dots keep every encoding (target / baseline colour, lighter audit requests, hollow non-streaming, cached grey, × for failed). Sweep on first draw and metric-tab switch; afterwards only new requests pop in. A **running-median line** per endpoint (last 5 successful, uncached requests) is always drawn behind the dots — no toggle. Failures and cached requests do not feed it. |
| Tooltips | Fade in over 140 ms. |
| Motion switch | A header control next to the language / theme selects (`nav.js`), persisted per browser (localStorage, try/catch); default follows `prefers-reduced-motion`. |

## Work packages (in order)

1. **Motion layer** — add `zing/web/static/v2/chartmotion.{js,css}` (from the
   prototype). `ZingMotion.enter(host|svg)`, `pop(svg, marks)`, `fresh(host, k)`.
   Load on analytics, history and the audit page.
   - `analytics.html`: call `enter()` in `drawChart()` only for new data, never
     from `redrawCharts()` (resize) or the language re-render.
   - History performance and the live view: see 4.
2. **Header motion switch** — `nav.js`: a toggle beside `lang-sel` /
   `theme-sel` (same style), sets `data-motion="off"` on `<html>`;
   `chartmotion.js` treats that like reduced motion. i18n strings in the
   `v2-foundation` fragment (all locales).
3. **Heat grid + colours** — move `heatgrid.js` into `charts.js` as the new
   `heatmap` (same name and cfg where possible, `bucketH` added), new `--c-q*`
   tokens + hatch rule in `charts.css`; block selector in `analytics.html`
   (both the latency heat map and the error heat map). Data from the server
   (see Backend).
4. **Live view / history** — in `perf.js` `chartSvg()`: draw the running-median
   path behind the dots from server-provided values (see Backend), add its
   legend entry and a sentence to the accessible name, add a "running median"
   column to the data table. Call `ZingMotion.enter()` from `Live.build()` /
   metric switch and `ZingMotion.pop()` for the marks of new records in
   `Live.patch()` (the prototype's render hook shows the exact logic: compare
   the request numbers before and after the redraw).
5. **Tests** — node tests as `tests/test_web_perf_js.py` for the new median
   path and heat-grid markup; pytest for the backend buckets / medians; the
   Playwright checks from the prototype (accessibility tree identical during
   and after motion, DOM at rest == plain draw, nothing under reduced motion).
6. **Docs** — `docs/ACCESSIBILITY.md` (motion, switch, reduced motion),
   CHANGELOG.

## Backend: move the heavy calculations down

The browser should only draw. Medians are already computed server-side in
`zing/web/analytics.py` (`percentile()`, type 7, from raw runs) — extend that
instead of averaging in the browser (the prototype's run-weighted mean of
hourly medians is a stand-in, **not** a median).

- **Heat grid blocks**: new bucket `dow_block` with a `block` parameter
  (1, 2, 3, 4, 6; validated like `BUCKETS`) next to `dow_hour` in `_bucket()`:
  key `"{dow}-{block_index}"`, extra `{dow, h0, h1}`. Medians, p25/p75, `n`
  and the few-runs flag per cell come from the existing `aggregate()` over the
  raw runs of that cell, so every block size gets real medians.
- **Live running median**: the audit stream (`zing/perf`, records sent to
  `ZingPerf.Live.add`) attaches per record, per endpoint, the median of the
  last 5 successful uncached values for each metric (`latency`, `ttft`, `tps`,
  `itl`), e.g. `trend: {latency: …, ttft: …}`. O(5) per record on the server;
  the same values are stored with the report so history and the PDF can show
  the identical line.
- **Caching**: analytics results are pure functions of (filters, bucket,
  block, tz, data version). Cache the computed response in-process (small LRU,
  e.g. 64 entries) keyed on the normalised query plus the history store's
  latest write id / run count; invalidate on every saved or deleted run. If
  profiling shows the SQLite read dominates, push the per-cell grouping into
  SQL (`GROUP BY` on the local weekday / block computed in Python is not
  possible with tz offsets, so keep percentiles in Python and cache).

## Prototype pieces → final location

| Prototype file | Goes to |
|---|---|
| `chartmotion.js` / `.css` | `zing/web/static/v2/chartmotion.{js,css}` |
| `heatgrid.js` | merged into `charts.js` (`heatmap`) |
| `perftrend.js` | logic inside `perf.js` `chartSvg()` (values from the server) |
| page `<style>` heat tokens / hatch | `charts.css` |
| page hook around `Live.render` | `perf.js` `Live.build` / `Live.patch` |

## Measured in the prototype (headless Chromium)

- Accessibility tree identical during and after motion; DOM at rest identical
  to a plain draw; nothing animates under reduced motion; tooltips work
  mid-animation; no horizontal scroll at 390 px; light and dark.
- < 3 ms script to start motion on four charts; no dropped frames at normal
  CPU speed; a few 24–48 ms frames at 4× CPU slowdown when all four charts
  animate at once (1-hour heat grid alone: 1–2 slow frames, mostly the draw).
- Not yet checked: Firefox and Safari.
