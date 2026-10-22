# Tool surfaces: embeddings as first-class audits

Goal: the Tools (embedding audit first) run through the same detector /
scoring / History / Monitors / Analytics pipeline as chat audits, so for
example embedding speed is traceable over time.

## Decisions

1. **Surface axis.** Every target, report, history row and watch has a
   `surface`: `chat` (default) or `embedding` (later `rerank`, `image`, `tts`).
   It is orthogonal to the suite (suite = depth). `NULL` in the databases and a
   missing field in saved report JSON mean `chat`; no data migration, no
   backfill (tool audits were never saved).
2. **Detectors declare their surface** (`surface: ClassVar[str] = "chat"`);
   `select_detectors` filters by the target's surface first, then suite tier,
   custom dimensions, judge/baseline as today.
3. **Reuse existing dimensions; no new ones.**

   | Embedding check | Dimension |
   |---|---|
   | connectivity | CONNECTIVITY |
   | vector dimension vs KB `embedding_dimensions` | MODEL_IDENTITY |
   | echoed model field | MODEL_IDENTITY |
   | vector drift on a pinned probe input vs the previous run | MODEL_IDENTITY |
   | determinism (same input twice) | RELIABILITY |
   | distinctness (unrelated inputs) | CAPABILITY |
   | performance probe | PERFORMANCE |

4. **One shared 0–100 score and A–F grade** (`scoring._rating`). Weights and
   the profile / core / infra dimension sets are per surface; chat keeps its
   current values exactly. For embeddings a dimension mismatch (MODEL_IDENTITY
   HIGH) makes the risk HIGH.
5. **Performance probe: adapt, don't fork.** Extract the surface-neutral parts
   of `zing/detectors/performance.py` (phase loop ping → warm-up → N probes →
   burst, endpoint alternation, tail-ratio consistency findings, error and load
   findings) into a shared module. `PerformanceDetector` (chat, id
   `performance`) keeps byte-identical output. New `EmbedPerformanceDetector`
   (id `performance.embed`, dimension PERFORMANCE):
   - uncacheable inputs (random nonce prefix); identical vectors for different
     inputs are flagged as cached and left out of the stats;
   - no streaming; second axis is **batch size** (1 vs 16 inputs): per-item
     latency scaling linearly suggests a relay that splits or serialises;
   - metrics: latency p50/p95, cold start, inputs/s, input tokens/s;
   - **gating identical to the chat probe** (deep/full/custom, or standard with
     a baseline);
   - no knowledge-base speed reference: consistency, errors, load behaviour,
     plus comparison with a trusted baseline when one is given.
6. **Recorder.** `RequestRecord.op` gains `embed`; the client's
   `embeddings()` call is recorded like `complete`. `perf/summary.py`
   functions that filter on `op == "complete"` take an `op` parameter
   (default `complete`, so chat output is unchanged). Embedding latency goes
   into the existing `latency_p50_ms` / `latency_p95_ms` / `cold_start_ms`
   metric columns.
7. **History.** Tool runs are saved like audits. One History list with a
   surface badge and filter.
8. **Analytics.** `surface` is a **mandatory** filter, defaulting to the most
   common surface (same pattern as the suite filter). `Metric` gets a
   `surfaces` set, so `options()` only offers applicable metrics
   (chat-only: TTFT, decode, ITL, billing, reasoning, cache, context). The
   integrity view lists the embedding detector ids. All existing views are
   reused.
9. **Monitors.** Watches get a `surface` column; scheduler, webhooks, master
   key, relay gate, KB pinning and regression alerts are reused. "Monitor
   this" on the Tools page result.
10. **Entry points.** `/api/embed` and `zing embed` become thin wrappers around
    the runner with `surface=embedding`; the Tools page keeps working.

v1 scope: embeddings only. Rerank follows in v2 (below); image and TTS follow
the same pattern.

## Implementation batches

All four batches are done.

1. (done) Surface axis (models, config, history/watches columns, detector filter),
   per-surface scoring, recorder `op=embed`, `summary` `op` parameter. No chat
   behaviour change.
2. (done) Embedding detectors incl. drift, shared probe module +
   `EmbedPerformanceDetector`, runner wiring, `/api/embed` and `zing embed`
   via the runner, saved to history.
3. (done) History surface badge/filter; Analytics mandatory surface filter,
   `Metric.surfaces`, integrity ids; report view hides chat-only sections.
4. (done) Monitors with a surface, "Monitor this" on Tools; docs and CHANGELOG.

## v2: rerank

Rerank is the third surface, built the same way; nothing above changes.

| Rerank check | Id | Dimension |
|---|---|---|
| connectivity | `rerank.connectivity` | CONNECTIVITY |
| known-answer probe: the obvious document ranks first | `rerank.known_answer` | CAPABILITY |
| echoed model field | `rerank.identity` | MODEL_IDENTITY |
| ranking and scores of a pinned probe vs the previous run | `rerank.drift` | MODEL_IDENTITY |
| determinism (same query twice) | `rerank.determinism` | RELIABILITY |
| performance probe (4 vs 32 documents) | `performance.rerank` | PERFORMANCE |

- **Scoring.** Weights MODEL_IDENTITY 30, CAPABILITY 30, PERFORMANCE 20,
  RELIABILITY 10, CONNECTIVITY 10; a HIGH on model identity or capability
  makes the risk HIGH.
- **Recorder.** `op=rerank` (`zing.config.SURFACE_OPS`); rerank does not
  stream.
- **Probe.** Shared phase loop and gating of `perf_probe`; the second axis is
  the document count (4 vs 32 per query): a per-document latency at 0.6x or
  more of the small request's is linear scaling (a relay that splits or
  serialises). No knowledge-base speed reference.
- **Entry points.** `/api/rerank` and `zing rerank` through the runner, with
  `--suite`, `--save/--no-save` and a dry-run estimate (as for `zing embed`).
- **History, Analytics, Monitors.** Surface badge and filter, rerank label in
  the Analytics surface select, rerank integrity ids; monitors with
  `surface=rerank` check drift against their previous run. The v2 Monitors
  card also edits an embedding watch's claimed dimension (before, API only).
- **Docs.** README, DEVELOPER_GUIDE and METHODOLOGY in all seven languages
  cover the surface axis, embeddings and rerank.

All rerank batches are done: surface foundation, detectors, probe, entry
points, Tools / History / report UI, Monitors / Analytics UI and docs.
