# Embedding, rerank, image and audio audits

> **🇬🇧 English** · [🇨🇳 中文](../i18n/zh-CN/guide/other-endpoints.md) · [🇫🇷 Français](../i18n/fr/guide/other-endpoints.md) · [🇪🇸 Español](../i18n/es/guide/other-endpoints.md) · [🇵🇹 Português](../i18n/pt/guide/other-endpoints.md) · [🇮🇹 Italiano](../i18n/it/guide/other-endpoints.md) · [🇩🇪 Deutsch](../i18n/de/guide/other-endpoints.md) · [🇳🇴 Norsk](../i18n/nb/guide/other-endpoints.md)

These endpoints return vectors, rankings, images or audio instead of chat, so
ekte audits them with focused probes instead of the chat prompts. Each prints a
verdict and supports `--json` and `--fail-on-risk`.

## Endpoint type (surface), embedding and rerank monitors

Every audit, history row and monitor has an **endpoint type** (`surface`):
`chat` (the default), `embedding` or `rerank`. It is independent of the suite.
Embedding and rerank audits run through the same runner, scoring (0–100, A–F),
History, Analytics and Monitors as chat audits; only the detectors differ.
History and Analytics filter by endpoint type, and Analytics shows only the
metrics that apply.

To monitor an embeddings or rerank endpoint, run it on the **Audit** page (pick
**Embeddings** or **Reranking** in the endpoint-type selector) and choose **Monitor this**, or **Schedule as monitor** on its History row. The
monitor re-runs the audit on its schedule, with the same knowledge-base pin,
alert threshold and regression alerts as a chat monitor, and checks **drift**
against its previous run (the vectors of an embedding probe, the ranking and
scores of a rerank probe). An embedding monitor's claimed dimension can be
changed on its card (empty or 0: from the knowledge base). The speed probes
(embeddings: latency, cold start, inputs/s, batch scaling; rerank: latency,
cold start, documents/s, 4 vs 32 documents) run only on the deep, full or
custom suites, or on standard with a baseline.

## Embeddings and rerank

```bash
# The expected vector dimension is resolved from the knowledge base for the claimed model.
ekte embed --base-url https://relay.example.com/v1 \
           --model text-embedding-3-large --claimed-model text-embedding-3-large --fail-on-risk high

# Or give the expected dimension directly:
ekte embed --base-url ... --model my-embed --claimed-dimensions 1024 --json

# Rerank: a built-in known-answer probe — a genuine reranker must rank the
# obviously relevant document first.
ekte rerank --base-url https://relay.example.com/v1 --model my-rerank

# Deeper: adds the rerank speed probe; --no-save keeps the run out of History.
ekte rerank --base-url ... --model my-rerank --suite deep --no-save
# See the checks and the estimated calls first, without sending a request:
ekte rerank --base-url ... --model my-rerank --dry-run
```

`rerank` checks connectivity, the **known-answer probe** (the obviously relevant
document must rank first), the echoed `model` field, determinism (the same
query twice gives the same ranking and scores) and **ranking drift** against
the previous saved run. `ekte embed` and `ekte rerank` take `--suite` and
`--save/--no-save` (saved by default, so the next run has a drift reference)
and `--dry-run`.

`embed` checks connectivity, **dimension match** (the returned vector length
against the claimed model's native dimension — the headline bait-and-switch
signal: a relay claiming 3072-d `text-embedding-3-large` but returning 1024-d
serves a substitute), determinism (same input → cosine ≈ 1), distinctness
(unrelated inputs → cosine well below 1) and the echoed `model` field. Bundled
profiles: OpenAI `text-embedding-3-small` (1536), `text-embedding-3-large`
(3072), `text-embedding-ada-002` (1536), Qwen `text-embedding-v3`/`-v4` (1024),
Google `gemini-embedding-2` (3072).

Both are also in the web UI: they start on the **Audit** page through the
endpoint-type selector (**Embeddings**, **Reranking**). The rerank audit always uses the built-in probes, so every run stays
comparable for drift and monitoring.

## Image and audio (TTS) generation

Image generation (`POST /v1/images/generations`) and text-to-speech
(`POST /v1/audio/speech`), decoded with the Python standard library only — image
dimensions from the header bytes (PNG/JPEG/GIF/WebP), WAV duration via `wave`.

```bash
# Does a relay claiming DALL·E 3 actually return the requested 1792x1024? A
# downscaled or wrong-size image (or a size outside the claimed model's native
# sizes, from the knowledge base) is the headline bait-and-switch signal.
ekte image --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model dall-e-3 --claimed-model dall-e-3 --size 1792x1024 --fail-on-risk high

# Does a relay claiming tts-1-hd return real audio whose length scales with the
# input (not a fixed placeholder, not HTML/JSON masquerading as audio)?
ekte audio --base-url https://relay.example.com/v1 --api-key env:RELAY_KEY \
  --model tts-1-hd --voice alloy --audio-format wav --save-to clip.wav
```

`image` checks connectivity, a valid and decodable format, **size match**
(decoded width × height against the request and the claimed model's native
sizes — FAIL/HIGH on a mismatch), distinctness (two prompts → different images,
catching a fixed placeholder), count and the `model` field. `audio` checks
connectivity, container/format validity, that the format is honored, a
non-trivial duration that scales with the input, distinctness and the `model`
field. The knowledge base ships OpenAI DALL·E 2/3, gpt-image-1, gpt-image-2,
tts-1/tts-1-hd/gpt-4o-mini-tts and Qwen image/TTS profiles.
