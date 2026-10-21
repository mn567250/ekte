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

v1 scope: embeddings only. Rerank, image and TTS follow the same pattern.

## Implementation batches

1. Surface axis (models, config, history/watches columns, detector filter),
   per-surface scoring, recorder `op=embed`, `summary` `op` parameter. No chat
   behaviour change.
2. Embedding detectors incl. drift, shared probe module +
   `EmbedPerformanceDetector`, runner wiring, `/api/embed` and `zing embed`
   via the runner, saved to history.
3. History surface badge/filter; Analytics mandatory surface filter,
   `Metric.surfaces`, integrity ids; report view hides chat-only sections.
4. Monitors with a surface, "Monitor this" on Tools; docs and CHANGELOG.
