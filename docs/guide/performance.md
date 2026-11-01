# Performance

> **🇬🇧 English** · [🇨🇳 中文](../i18n/zh-CN/guide/performance.md) · [🇫🇷 Français](../i18n/fr/guide/performance.md) · [🇪🇸 Español](../i18n/es/guide/performance.md) · [🇵🇹 Português](../i18n/pt/guide/performance.md) · [🇮🇹 Italiano](../i18n/it/guide/performance.md) · [🇩🇪 Deutsch](../i18n/de/guide/performance.md) · [🇳🇴 Norsk](../i18n/nb/guide/performance.md)

Every report carries a **performance** section: latency, time to first token
(TTFT), decode and end-to-end tokens/s, inter-chunk latency and jitter,
error/timeout/429 rates, a network breakdown (TCP connect, TLS, a `GET /models`
round trip, server time) and cold start, each as count / min / mean / p50 / p75 /
p90 / p95 / p99 / max / stdev.

When the dedicated probe runs, it scores the **Performance** dimension. The score
is about **consistency**, not raw speed, so a slow but steady endpoint (a local
or self-hosted model) is not marked down for not being a data center; the
checks and their points are in the
[Methodology](methodology.md#performance--performance). Performance findings
are at most low severity: they move the score, never the risk verdict. Without the probe (`standard` without a baseline, `smoke`), the
dimension does not run and drops out of the overall score.

- **standard** collects the section from the audit's own requests.
- **deep / full / custom** add a dedicated probe: 100 uncacheable requests of 128
  output tokens (a random request id opens every prompt; no cache or reasoning
  parameters are sent) plus a burst at `--concurrency`. Tune it with
  `--performance-requests` (0 disables) and `--performance-max-tokens`.
- The probe streams by default; `--performance-non-streaming` (or the
  **Streaming / Non-streaming** switch in the web UI) measures relays that cannot
  stream. **full** measures both modes, interleaved, and reports them side by side.
- **compare** runs the probe on both endpoints, alternating requests, and adds a
  target-vs-baseline table (5 requests per side on `standard`, too few for the
  consistency checks) whose differences are marked green ✓ where the target is
  better and red ✗ where it is worse.

Tokens are counted twice — from the relay's `usage` and locally — so throughput
is measurable even when `usage` is missing. The local count is an estimate from
a built-in heuristic (about ±15-20%; no tokenizer is used or downloaded), and the
section always says so. A percentile is shown only with
enough samples (p90 from 10, p95 from 20, p99 from 100). The JSON report keeps
every request's timings (numbers only, no text); the HTML report and the web UI
chart them over the audit's timeline.

Audits that run at the same time in `ekte serve` (several browser tabs,
monitors) do not distort each other's timings: CPU-heavy preparation, such as
building the long context-window prompts, runs off the server's event loop.

**Request timeouts.** `timeout_sec` (`--timeout`, default 60 s) is the base;
each request gets more for its prompt size and output budget, so a long
context-window probe or a slow self-hosted model is not cut off after a minute.
Local and private hosts (`localhost`, `127.x`, `192.168.x`, `host.docker.internal`,
…) get at least 300 s. `max_request_sec` (`--max-request-time`, default 900 s) is
the hard cap for any single request, streams included, so no request can hang
forever. A context-window probe that still times out is reported as
inconclusive, not as truncation.
