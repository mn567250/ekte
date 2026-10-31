#!/usr/bin/env python3
"""Write (or with --check, verify) the published JSON Schemas in ekte/schemas/.

Run after changing the report model or the webhook payload. If the schema
changed, bump the version first (REPORT_SCHEMA_VERSION or
WEBHOOK_SCHEMA_VERSION in ekte/models.py) and run with --record to add
the new version's fingerprint to ekte/schemas/history.json.
"""

from __future__ import annotations

import json
import sys

from ekte import schemas

HISTORY = schemas.SCHEMA_DIR / "history.json"


def main(argv: list[str]) -> int:
    check = "--check" in argv
    record = "--record" in argv
    history = json.loads(HISTORY.read_text("utf-8")) if HISTORY.exists() else {}
    bad = 0
    for filename, schema in schemas.generated().items():
        name = filename.split(".")[0]
        path = schemas.SCHEMA_DIR / filename
        text = schemas.dumps(schema)
        version = schema["x-schema-version"]
        recorded = history.setdefault(name, {})
        fp = schemas.fingerprint(schema)
        if record:
            recorded[version] = fp
        if check:
            if not path.exists() or path.read_text("utf-8") != text:
                print(f"{filename} is stale: run scripts/generate_schemas.py")
                bad = 1
            if recorded.get(version) != fp:
                print(f"{name} schema changed without a version bump (still {version})")
                bad = 1
        else:
            path.write_text(text, encoding="utf-8")
    if record:
        HISTORY.write_text(json.dumps(history, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return bad


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
