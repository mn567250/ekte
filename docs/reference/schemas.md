# Report, webhook and evidence schemas

The report JSON, the generic webhook payload and the lines of an evidence file each carry a `schema_version`
and have a published [JSON Schema](https://json-schema.org/) (draft 2020-12).
The compatibility rules are in the
[stability policy](stability.md#surface-report); this page describes the formats.
The English text is canonical; this document is not translated.

| Document | Schema file | Version field | Current |
|---|---|---|---|
| Report (`ekte check --json`, `--format json`, history) | [`ekte/schemas/report.schema.json`](../../ekte/schemas/report.schema.json) | `schema_version` | 1.3 |
| Generic webhook payload (`ekte watch`, monitors) | [`ekte/schemas/webhook.schema.json`](../../ekte/schemas/webhook.schema.json) | `schema_version` | 1.0 |
| Evidence file line (`--evidence`, history runs) | [`ekte/schemas/evidence.schema.json`](../../ekte/schemas/evidence.schema.json) | `schema_version` of the header line | 1.0 |

The files are generated from the code that produces the documents (the
`AuditReport` model and the `WebhookPayload` model in `ekte/schemas/`), ship in
the wheel and the sdist, and are reachable under a stable URL:
`https://raw.githubusercontent.com/mn567250/ekte/main/ekte/schemas/report.schema.json`
(and `webhook.schema.json`). The `--compact` verdict also carries
`schema_version` (the report schema version it was derived from) but has no
schema of its own. Slack, Feishu/Lark and DingTalk bodies follow those
platforms' formats and carry no `schema_version`.

## Versions

`schema_version` is `MAJOR.MINOR` and is independent of the ekte version.

- **Minor** (1.0 to 1.1): compatible change, such as a new optional field.
- **Major** (1.x to 2.0): breaking change (removed or renamed field, changed
  type or meaning). Only in a major ekte release, after the deprecation period.
- Consumers accept any minor version of the major they know and **ignore
  unknown fields**; the schemas do not set `additionalProperties: false`.
- A report without `schema_version` was written before 0.32 and is version 1.0.
  Such reports stay readable everywhere ekte reads reports back (history,
  re-run, re-export).

## Report example (abridged)

```json
{
  "schema_version": "1.1",
  "tool_version": "0.32.0",
  "mode": "check",
  "suite": "standard",
  "surface": "chat",
  "target": {"name": "target", "kind": "target", "base_url": "https://relay.example.com/v1", "model": "gpt-4o"},
  "verdict": {"risk_level": "high", "overall_score": 52.6, "rating": "F", "headline": "...", "key_findings": ["Self-identifies as a rival brand"]},
  "dimensions": [],
  "detectors": [],
  "notes": [],
  "warnings": []
}
```

## Webhook example

```json
{
  "schema_version": "1.0",
  "tool": "ekte",
  "event": "audit_alert",
  "language": "en",
  "text": "ekte relay audit alert\nRisk: High risk (HIGH)\n...",
  "risk_level": "high",
  "score": 52.6,
  "rating": "F",
  "headline": "Strong evidence the relay does not deliver the claimed model as advertised.",
  "base_url": "http://127.0.0.1:9099/v1",
  "claimed_model": "gpt-4o",
  "key_findings": ["Self-identifies as a rival brand"],
  "previous_risk_level": null,
  "regressed": false
}
```

## Validating

```bash
ekte check ... --json > report.json
python -m jsonschema -i report.json "$(python -c 'import ekte.schemas as s; print(s.SCHEMA_DIR / "report.schema.json")')"
```

## For contributors

After changing `AuditReport` or the webhook payload:

1. Bump `REPORT_SCHEMA_VERSION` or `WEBHOOK_SCHEMA_VERSION`
   (both in `ekte/models.py`): minor for a compatible change, major only in a
   major release.
2. Run `python scripts/generate_schemas.py --record` to rewrite the schema files
   and record the new version's fingerprint in `ekte/schemas/history.json`.
3. Describe the change under "Changed" or "Added" in the changelog.

`tests/test_schemas.py` fails if the files are stale, or if a schema changed
without a version bump, and validates real outputs against the schemas.

## Evidence files

An evidence file is JSON Lines in one zstd stream (`<run_id>.jsonl.zst`): every
raw HTTP request and response of one run, keys and sensitive headers removed
(see [Reports](../guide/reports.md)). Each line is one JSON document matching
`evidence.schema.json`, told apart by `type`:

- `header` (the first line): `schema_version`, `tool_version`, `run_id`,
  `started_at` (the report's), `mode`, `suite`, `surface`, `target`, `baseline`,
  `judge` and `options` (the run's audit options, which a re-score repeats).
- `exchange` (every further line): `id` (unique in the file, in the order the
  calls finished), `seq` (the request's `seq` in the report's
  `performance.requests`; `null` for calls without a record: the LLM judge,
  image and audio audits), `endpoint`, `detector`, `op`, `start_ms` (since the
  run started), `request` (`method`, `url`, `headers`, `body`), `response`
  (`status`, `http_version`, `headers`, `body`, `chunks`, `done_ms`,
  `read_to_end`; `null` when none arrived) and `error`.

A `body` holds `text` (the body with any `Content-Encoding` undone; base64 when
it is not UTF-8, `encoding` says which), its original `bytes` and `sha256`, and
`truncated`. `chunks` are `[ms since the request started, bytes received so
far]` pairs: how the response arrived. The report names its file in `evidence`
(`run_id`, `file`, `sha256`, `exchanges`, `bytes`, `schema_version`,
`complete`); a reader can check the file against that hash. Each finding's
`evidence_seqs` lists the `seq`s of the requests it rests on (`null`: the
detector does not say, so all of its requests; `[]`: none, e.g. a check of the
configuration). `ekte evidence-export` and `GET /api/v1/history/{id}/evidence/export`
turn a file into HAR 1.2 (each entry carries ekte's own fields in `_ekte`), a
curl script or one JSON document (`{"header": …, "exchanges": […]}`).

A report made by `ekte rescore` (a recorded run judged again by another ekte
version, its requests answered from the evidence file) carries
`rescored_from`: the recorded run's `run_id` and `evidence_sha256`, its
`tool_version`, `generated_at` and `report_id`, and `replayed`, `missing` (per
detector: requests nothing in the file answered; such a detector is
inconclusive) and `unused`. Its `evidence` is the recorded run's file, and its
request records keep that run's `seq`s (a request without a recorded answer
gets a `seq` from 1000000 up).

```json
{"type": "exchange", "id": 13, "seq": 12, "endpoint": "target", "detector": "streaming", "op": "complete", "start_ms": 5120.4, "request": {"method": "POST", "url": "https://relay.example.com/v1/chat/completions", "headers": {"authorization": "«redacted»"}, "body": {"text": "{...}", "encoding": "utf-8", "bytes": 312, "sha256": "...", "truncated": false}}, "response": {"status": 200, "http_version": "HTTP/1.1", "headers": {}, "body": {"text": "data: {...}", "encoding": "utf-8", "bytes": 9123, "sha256": "...", "truncated": false}, "chunks": [[412.0, 180], [433.5, 361]], "done_ms": 1290.2, "read_to_end": false}, "error": null}
```
