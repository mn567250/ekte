# Report and webhook schemas

The report JSON and the generic webhook payload each carry a `schema_version`
and have a published [JSON Schema](https://json-schema.org/) (draft 2020-12).
The compatibility rules are in the
[stability policy](STABILITY.md#surface-report); this page describes the formats.
The English text is canonical; this document is not translated.

| Document | Schema file | Version field | Current |
|---|---|---|---|
| Report (`ekte check --json`, `--format json`, history) | [`ekte/schemas/report.schema.json`](../ekte/schemas/report.schema.json) | `schema_version` | 1.1 |
| Generic webhook payload (`ekte watch`, monitors) | [`ekte/schemas/webhook.schema.json`](../ekte/schemas/webhook.schema.json) | `schema_version` | 1.0 |

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
