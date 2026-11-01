"""The published JSON Schemas (ekte/schemas/) match the code and real outputs."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest

from ekte import notify, schemas
from ekte.models import AuditReport
from ekte.report import compact_dict, render_json
from tests.test_agent_output import _report

HISTORY = json.loads((schemas.SCHEMA_DIR / "history.json").read_text("utf-8"))
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "web_report.json").read_text("utf-8"))
NAMES = {"report.schema.json": "report", "webhook.schema.json": "webhook"}


@pytest.mark.parametrize("filename", sorted(NAMES))
def test_published_schema_is_current(filename):
    """The committed file is exactly what the code generates (run scripts/generate_schemas.py)."""
    published = (schemas.SCHEMA_DIR / filename).read_text("utf-8")
    assert published == schemas.dumps(schemas.generated()[filename])


@pytest.mark.parametrize("filename", sorted(NAMES))
def test_schema_change_requires_version_bump(filename):
    """A changed schema must carry a new version whose fingerprint is recorded in history.json."""
    schema = schemas.generated()[filename]
    version = schema["x-schema-version"]
    recorded = HISTORY[NAMES[filename]].get(version)
    assert recorded == schemas.fingerprint(schema), (
        f"{filename} changed without bumping its schema version ({version}); bump it and run "
        "`python scripts/generate_schemas.py --record` (see docs/reference/stability.md)"
    )


@pytest.mark.parametrize("filename", sorted(NAMES))
def test_schemas_are_valid_json_schema(filename):
    jsonschema.Draft202012Validator.check_schema(schemas.generated()[filename])


def test_report_json_validates_and_carries_version():
    doc = json.loads(render_json(_report()))
    assert doc["schema_version"] == schemas.REPORT_SCHEMA_VERSION
    jsonschema.validate(doc, schemas.load("report"))


def test_real_fixture_report_validates():
    doc = json.loads(AuditReport.model_validate(FIXTURE).model_dump_json())
    jsonschema.validate(doc, schemas.load("report"))


def test_report_without_schema_version_still_reads():
    """Reports from before the field existed (history, re-export) load as the current version."""
    old = dict(FIXTURE)
    old.pop("schema_version", None)
    assert AuditReport.model_validate(old).schema_version == schemas.REPORT_SCHEMA_VERSION


def test_report_schema_tolerates_unknown_fields():
    doc = json.loads(render_json(_report()))
    doc["added_in_a_later_minor"] = {"x": 1}
    jsonschema.validate(doc, schemas.load("report"))


def test_report_schema_rejects_wrong_types():
    doc = json.loads(render_json(_report()))
    doc["verdict"] = "high"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(doc, schemas.load("report"))


def test_compact_carries_report_schema_version():
    assert compact_dict(_report())["schema_version"] == schemas.REPORT_SCHEMA_VERSION


@pytest.mark.parametrize("previous", [None, FIXTURE])
def test_webhook_payload_validates(previous):
    payload = notify.format_generic(FIXTURE, previous)
    assert payload["schema_version"] == schemas.WEBHOOK_SCHEMA_VERSION
    jsonschema.validate(payload, schemas.load("webhook"))
    # the model and the producer agree on the field set
    assert set(payload) == set(schemas.WebhookPayload.model_fields)


def test_webhook_build_payload_generic_validates():
    payload = notify.build_payload(FIXTURE, kind="generic")
    jsonschema.validate(payload, schemas.load("webhook"))
