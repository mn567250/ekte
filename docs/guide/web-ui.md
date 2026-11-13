# Web UI (`ekte serve`)

> **🇬🇧 English** · [🇨🇳 中文](../i18n/zh-CN/guide/web-ui.md) · [🇫🇷 Français](../i18n/fr/guide/web-ui.md) · [🇪🇸 Español](../i18n/es/guide/web-ui.md) · [🇵🇹 Português](../i18n/pt/guide/web-ui.md) · [🇮🇹 Italiano](../i18n/it/guide/web-ui.md) · [🇩🇪 Deutsch](../i18n/de/guide/web-ui.md) · [🇳🇴 Norsk](../i18n/nb/guide/web-ui.md)

Prefer point-and-click? A local web UI wraps the same engine — no CLI needed.

```bash
pip install 'ekte[web]'     # or: uv tool install 'ekte[web]'
ekte serve                        # opens http://localhost:8000
```

The form guides you through the configuration:

1. Choose the **Relay / provider**: a provider of the knowledge base or a relay
   you saved. Its base URL is filled in (other known URLs of the provider are
   offered as suggestions). For any other relay choose **Other** and enter the
   **Relay URL**.
2. Add the **API key** if the relay needs one.
3. ekte lists the relay's models on its own (when you pick a relay and whenever
   the URL or key changes; **Refresh models** asks again). Pick the **Model to
   request**. A relay without a model list falls back to typing the id
   (**Enter manually**).
4. Optionally pick the **Claimed model** from the knowledge base's models: the
   model the relay says it serves. When the requested model is in the knowledge
   base it is preselected; change it only if the relay sells the model under
   another name. The provider profile ekte audits against follows from it.

A relay that is not in the list yet can be kept with **Save to knowledge base**
under a name you give it; next time it is one pick away. The trusted baseline
(**Compare against a trusted baseline**) and the embedding and rerank audits are
configured the same way.

Then **Start audit** and watch the checks run **live**: every check shows its
score and how long it took, and a check with findings expands to show the
evidence. The result is a shareable verdict report: grade, the per-dimension
checks with their scoring scales, plain-language findings and the performance
section, and an **Execution log** of every detector.

Everything runs on your machine: a key typed in the browser reaches only your
local ekte server and the relay you audit, never a third party. See
[Privacy and local data](privacy.md#privacy-and-local-data).

## Pages

The web UI is served at the root of the address `ekte serve` opens, with the audit page at `/`. Earlier addresses redirect to the matching page until 1.0.0 (see [Web UI addresses](../reference/stability.md#surface-web-addresses)).

| Page | Address | What it is for |
|---|---|---|
| **Audit** | `/` | Audit a relay (optionally against a baseline) and read the report; embedding and rerank audits start here too, through the endpoint-type selector |
| **Monitors** | `/watches` | Scheduled re-audits with webhook alerts |
| **History** | `/history` | Every audit run on this machine, grouped by relay + claimed model, with trends |
| **Analytics** | `/analytics` | Relays and models compared over time: KPIs, charts with data tables, leaderboards |
| **Knowledge** | `/kb` | The knowledge base in three tabs — models, providers, relays: browse, switch on/off, add your own |
| **Accessibility** | `/accessibility` | The accessibility conformance report and statement (the icon next to the language switch); no manual review by a person yet (a known limitation) |

Across the pages: filters and configurable trends (score, grade, latency p50,
decode speed p50) on **History**; **Schedule as monitor** and **Re-run audit** on every History run; **Download
report** in every format; and a theme switch (Auto theme / Light / Dark). Every page but Accessibility has one notice right under its
introduction, colored by importance (information, success, warning,
critical): e.g. the last finished audit on **Audit**, the master key on
**Monitors**, runs still being processed on **History** and **Analytics**,
skipped entries on **Knowledge**.

**Background audits.** An audit started on the **Audit** page keeps
running when you switch pages or close the tab; **Continue in background** sends
it there on purpose. **History** lists every queued and running audit (and every
running monitor) with its progress; **Watch live** reopens the live view, which
catches up on everything that already happened. Audits of the same relay run one
after another, so they never skew each other's latency or reliability results
(all loopback addresses count as one host, so models served from your own
machine queue too); audits of different relays run in parallel, at most four at
once (`EKTE_MAX_PARALLEL_AUDITS`). Monitors wait for their relay the same way.

**Raw requests and responses.** A run saved to **History** keeps every raw
request and response it exchanged (see [Privacy](privacy.md)). In its report,
**Show evidence** under a finding lists the requests of the check behind it;
each opens the request as sent and the response as received, with how its
chunks arrived, and **Raw evidence** → **Evidence file** downloads them all.
The audit form's **Raw requests/responses** setting (**Keep** / **Don't keep**)
decides it per run; each monitor has the same setting on **Monitors**.

Under a finding the list holds only the requests that finding rests on.
Each pair, and the whole run, also downloads as HAR or as a curl script that
sends the requests again (`EKTE_API_KEY` supplies the key).

**Re-score with this version** on a saved run with evidence replays it the
same way and saves the result as a new run in **History**; its report says
which run it replayed.

**Analytics.** `/analytics` turns the local history into
comparisons: KPI tiles for the chosen period (runs, median score, high-risk
share, success rate, TTFT, decode speed, billing ratios) with the change
against the period of the same length before; a chart of any metric per relay,
model or relay × model by hour, day or week (median line with the p25–p75 band,
up to four series, every chart also as a data table, and on request a
forecast — see below); and a leaderboard of the
relays for a model, or the models for a relay. Relays are grouped by their
knowledge-base entry (saved relays and providers), so renaming a relay
regroups its history. Buckets with fewer than 3 runs are drawn faded — a single
audit can be an outlier; a monitor gives regular measurements. Older runs show
what they measured: the page says how many runs a value is based on. By default
it compares one suite and probe mode (the most common ones), so unlike runs are
not mixed; the filters and view are kept in the URL, so a view can be
bookmarked or shared. Nothing leaves the machine.

Further panels answer narrower questions: **peak hours** (a weekday × hour
heatmap of TTFT, latency and decode speed (median and p95 / p5 tails),
inter-token jitter, network and relay times, success or error rate in your time zone — does a
relay slow down or fail more at busy times? By weekday, or with 90 days of runs
over a 4-week cycle and with 180 days by week of the month), **errors and reliability** (failed
calls by cause — rate limits (HTTP 429), server errors (5xx), timeouts, network
errors — over time and per relay or model, from the stored request records,
with how many runs have them), **model integrity** (identity, context-window and
capability check results per relay × model, the share of runs whose echoed
model differs and the measured share of the declared context window),
**billing and tokens** (billing ratios over time against the 100% line — above
it the relay reports more tokens than ekte counted — plus reasoning and cached
input shares) and **relay overhead** (the processing time a relay reports next
to the network round trip to it).

**Forecast (Analytics › Trends).** *Comparison over time* has a **Forecast**
select, off by default: the next 12 or 24 hours, 3 or 7 days, or 2 or 4 weeks,
depending on the time buckets. Each series then goes on as a dashed line with
a faint band, over a light area labelled "Forecast". The line is a straight
line through the bucket medians (weighted by runs, odd buckets left out) and
starts at the last bucket with 3 or more runs, so it joins the history; the
band is the middle half of the runs (p25–p75), widened the further ahead it
reaches. A note under the chart says per series whether it is rising or
falling and by how much per bucket, whether that is better or worse, and
where it should be at the end of the forecast. The fit starts again after an
ekte-version or knowledge-base mark and after a step in the data (a jump such
as a backend or model change), since earlier values are not comparable. There
is no forecast for a series with fewer than 6 buckets of 3 or more runs since
then (more runs — a monitor — or another bucket size help), nor for pooled
rates such as the success rate, which have no p25–p75 band. The data table
lists the forecast buckets as extra rows marked "Forecast (estimate)". A
forecast is an estimate, not a measurement.

**Tabs and share links (Analytics).** The panels sit in five tabs —
**Overview** (KPIs, leaderboard), **Trends** (comparison over time, peak
hours), **Reliability** (errors, relay overhead), **Model integrity** and
**Billing** — under the page header and one filter panel shared by all of
them; only the tab you look at loads. The URL keeps the tab, the filters and
every chart option (`?tab=reliability&range=30d&relay=…&errors.bucket=dow_hour`), and
**Copy link to this view** copies it (or shows it in a field to copy where the
browser does not allow that): opening the link shows exactly that view. The
filter panel is the same on **History**, **Monitors** and **Analytics**: closed, it shows how
many filters are active and names them in one line (e.g. "Last 30 days ·
standard · Streaming · Example Relay"), so a shared view says what it shows. **History** and **Analytics** start on the last 30
days: today and the 29 days before it, from midnight in your time zone (**All
time** shows every run). A shared link keeps the period, not the dates: each
viewer sees it in their own time zone.

**Success, error, 429 and impaired rates.** Every request ekte sent to the
relay during a run has exactly one outcome: a success, a relay error (a
timeout while waiting for the relay, a 5xx or 4xx answer, or another broken
answer), a rate limit (HTTP 429), or a failure that never reached the relay
(the network between you and the relay, or ekte itself). Repeated attempts
count once. The relay is judged only on the requests that reached it:

- **Success rate** = successes ÷ requests that reached the relay;
- **Error rate** = relay errors ÷ requests that reached the relay;
- **Rate-limited (429) rate** = rate limits ÷ requests that reached the relay;

so these three always add up to 100%. The **impaired share** is the part of
all requests that failed before reaching the relay (network or ekte
failures): it says how far the run itself can be trusted, not how good the
relay is, and a high share means re-running the audit. Over several runs the
rates are pooled — all requests of the runs counted together — so one bad run
among many good ones still shows (nine runs at 0% and one at 40% give about
4%, not 0%); scores, latencies, speeds and billing ratios are the median of
the runs. History, Analytics and the report show the same numbers for the
same runs, and a single run shows exactly the values of its report. The
reliability check in the report has a rate of its own, labelled
"Reliability check success rate", which feeds the score only.

## Languages

A language dropdown in the header of every page switches the UI between
**🇬🇧 English** (default), **🇨🇳 Chinese** (the original UI), **🇫🇷 French**,
**🇪🇸 Spanish**, **🇵🇹 Portuguese**, **🇮🇹 Italian**, **🇩🇪 German** and
**🇳🇴 Norwegian** (Bokmål); the choice
is remembered per browser.

Reports downloaded from the UI (**Download report**: JSON, Markdown, HTML or PDF)
follow the selected language: the JSON keys, enum values (`risk_level`,
`status`, `severity`, …), ids and evidence stay exactly as in the CLI's report
(the JSON is still a valid ekte report), while the human-readable values
(verdict headline and summary, finding titles and summaries, recommendations,
detector names, notes) are translated, and the file name carries the language
(`ekte-report.de.json`, `ekte-report.de.pdf`). The section headings of the
Markdown/HTML/PDF files are English. The CLI's own `--format json|md|html|pdf`
reports stay English.

**Prompts sent to the audited endpoint do not follow the UI language.** Every
text ekte sends to an LLM API is English, so the same relay gets the same
verdict whoever reads the report (answer checks and token estimates are
calibrated to these exact texts). The only exceptions are knowledge-base
fingerprints whose language *is* the measurement — for example the Chinese
fluency, tokenizer and self-identification probes of China-native models. Each
report records the probe languages it actually used (`prompt_languages`, e.g.
`["en", "zh"]`).

Each report also records how the endpoint was spoken to: the wire protocol
(`target.api`: `openai`, `anthropic` or `responses`), whether `--api auto`
detected it (`target.api_auto`), and the performance probe's request mode
(`stream_mode`: `stream`, `non_stream` or `both` for the full suite). The web
UI's history page can filter on all three. `started_at` records when the audit
started (UTC); the `start_ms` of every request record counts from it.
