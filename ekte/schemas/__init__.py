"""Versioned JSON Schemas for the report JSON and the generic webhook payload.

The schemas are generated from the code that produces the documents
(:class:`ekte.models.AuditReport` and :class:`WebhookPayload`), so the two cannot
drift. The generated files live next to this module (``report.schema.json``,
``webhook.schema.json``) and ship in the wheel; ``python scripts/generate_schemas.py``
rewrites them and ``--check`` fails when they are stale.

Schema versions are ``MAJOR.MINOR`` strings, independent of the ekte version:

* a **compatible** change (a new optional field) raises MINOR;
* a **breaking** change (see docs/reference/stability.md) raises MAJOR, and only in a major
  ekte release.

``history.json`` records the SHA-256 of every released schema version. A test
fails when the generated schema no longer matches the recorded hash of its
current version, i.e. when the schema changed without a version bump.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from ekte.models import REPORT_SCHEMA_VERSION, WEBHOOK_SCHEMA_VERSION, AuditReport

SCHEMA_DIR = Path(__file__).parent
_ID_BASE = "https://raw.githubusercontent.com/mn567250/ekte/main/ekte/schemas/"

__all__ = [
    "REPORT_SCHEMA_VERSION",
    "WEBHOOK_SCHEMA_VERSION",
    "WebhookPayload",
    "report_schema",
    "webhook_schema",
    "generated",
    "load",
    "fingerprint",
    "dumps",
]


class WebhookPayload(BaseModel):
    """The generic webhook payload (``format_generic`` in ``ekte.notify``)."""

    model_config = ConfigDict(extra="allow")

    schema_version: str = WEBHOOK_SCHEMA_VERSION
    tool: str = "ekte"
    event: str = "audit_alert"
    language: str
    text: str
    risk_level: str
    score: float | None = None
    rating: str | None = None
    headline: str
    base_url: str | None = None
    claimed_model: str | None = None
    key_findings: list[str]
    previous_risk_level: str | None = None
    regressed: bool


def _relax(node: Any) -> None:
    """Consumers must ignore unknown fields: drop ``additionalProperties: false``."""
    if isinstance(node, dict):
        if node.get("additionalProperties") is False:
            del node["additionalProperties"]
        for v in node.values():
            _relax(v)
    elif isinstance(node, list):
        for v in node:
            _relax(v)


def _build(model: type[BaseModel], name: str, version: str, title: str) -> dict[str, Any]:
    schema = model.model_json_schema(mode="serialization")
    _relax(schema)
    schema["title"] = title
    schema["properties"]["schema_version"] = {
        "type": "string",
        "pattern": r"^[0-9]+\.[0-9]+$",
        "default": version,
        "description": (
            f"Version of this schema (MAJOR.MINOR), independent of the ekte version; "
            f"this schema describes version {version}. Documents without the field "
            "were written before schemas were versioned and match version 1.0."
        ),
    }
    ordered: dict[str, Any] = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": f"{_ID_BASE}{name}.schema.json",
        "x-schema-version": version,
    }
    ordered.update(schema)
    return ordered


def report_schema() -> dict[str, Any]:
    return _build(AuditReport, "report", REPORT_SCHEMA_VERSION, "ekte audit report")


def webhook_schema() -> dict[str, Any]:
    return _build(WebhookPayload, "webhook", WEBHOOK_SCHEMA_VERSION, "ekte webhook payload (generic)")


def dumps(schema: dict[str, Any]) -> str:
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def fingerprint(schema: dict[str, Any]) -> str:
    return hashlib.sha256(dumps(schema).encode("utf-8")).hexdigest()


def generated() -> dict[str, dict[str, Any]]:
    """Schema file name -> generated schema."""
    return {"report.schema.json": report_schema(), "webhook.schema.json": webhook_schema()}


def load(name: str) -> dict[str, Any]:
    """The published schema (``"report"`` or ``"webhook"``) as a dict."""
    data: dict[str, Any] = json.loads((SCHEMA_DIR / f"{name}.schema.json").read_text("utf-8"))
    return data
