#!/usr/bin/env python
"""Create the upgrade fixture of one released ekte version.

    python scripts/make_upgrade_fixture.py 0.31.0

runs the released ekte from PyPI (``uv run --with ekte==0.31.0 --no-project``,
isolated from this checkout) to write a fresh data directory with invented
content, and stores it as ``tests/fixtures/upgrade/v0.31.0/``:

* ``history.db``  audit history (reports in the shape that version writes)
* ``watches.db``  monitors: one with an encrypted stored key, one whose key is
                  not stored (key storage "memory"), one with a key reference
* ``kb.db``       the user's own knowledge-base entries (a provider and a model)
* ``manifest.json``  what the databases hold, as written by the released version
                  (``tests/test_upgrade_fixtures.py`` checks the current
                  version against it)

The content is invented. The only "secrets" are the fake API key
``fixture-api-key-not-real`` and a throw-away master key that exists only for
this fixture (it is in the manifest so the test can unlock the stored key).
Never put real keys or data in a fixture.

If PyPI is not reachable, build the fixture from the release's git tag: check
out the tag (``git worktree add /tmp/rel v0.31.0``), install it
(``pip install /tmp/rel`` into a scratch environment) and run, in that
environment, ``python scripts/make_upgrade_fixture.py --write DIR``
(``--write`` is the part that runs inside the released version); then copy DIR
to ``tests/fixtures/upgrade/v0.31.0``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "tests" / "fixtures" / "upgrade"
REPORT_SAMPLE = ROOT / "tests" / "fixtures" / "web_report.json"
DBS = ("history.db", "watches.db", "kb.db")

FAKE_API_KEY = "fixture-api-key-not-real"
# A valid Fernet key made only for fixtures: it protects nothing.
FIXTURE_MASTER_KEY = "Zml4dHVyZS1tYXN0ZXIta2V5LW5vdC1zZWNyZXQhISE="

KB_YAML = """
provider: fixtureai
display_name: Fixture AI
base_url_hints: [https://api.fixture.test/v1]
models:
- id: fixture-large-1
  aliases: [fixture-large-1-2026-01-01]
  context_window_tokens: 200000
  max_output_tokens: 16384
  identity_keywords: [fixture]
  fingerprints:
  - id: fixture.cutoff
    signal: cutoff
    prompt: What is your knowledge cutoff?
    pure_code_checkable: true
    expect_contains_any: ["2025"]
"""


def write(out: Path, report_path: Path) -> None:
    """Runs inside the released ekte: write the data directory and manifest."""
    os.environ["EKTE_DATA_DIR"] = str(out)
    os.environ["EKTE_SECRET_KEY"] = FIXTURE_MASTER_KEY
    os.environ.pop("EKTE_NO_USER_KB", None)
    import ekte
    from ekte import secretbox
    from ekte.knowledge import store as kb_store
    from ekte.knowledge.importer import import_yaml
    from ekte.web import history, watches

    out.mkdir(parents=True, exist_ok=True)
    base = json.loads(report_path.read_text(encoding="utf-8"))
    base["tool_version"] = ekte.__version__

    history.init()
    runs = []
    for i, (model, score, risk) in enumerate(
        [("gpt-4o-mini", 91.5, "low"), ("gpt-4o", 73.3, "medium"), ("claude-sonnet", 48.0, "high")], 1
    ):
        rep = json.loads(json.dumps(base))
        rep["target"]["model"] = model
        rep["target"]["claimed_model"] = model
        rep["target"]["base_url"] = f"https://relay{i}.example.com/v1"
        rep["verdict"]["overall_score"] = score
        rep["verdict"]["risk_level"] = risk
        rid = history.save(rep)
        runs.append({"id": rid, "model": model, "score": score, "risk_level": risk,
                     "base_url": rep["target"]["base_url"]})

    watches.init()
    box = secretbox.SecretBox([FIXTURE_MASTER_KEY], "fixture")
    secretbox.unlock(box)
    with watches._connect() as conn:
        watches._set_storage(conn, watches.STORAGE_ENCRYPTED)
        watches._set_canary(conn, secretbox.make_canary(box))
    cfg = {"base_url": "https://relay1.example.com/v1", "model": "gpt-4o-mini",
           "interval_sec": 3600, "webhooks": ["https://hooks.example.com/ekte"]}
    w_stored = watches.create({**cfg, "name": "stored key", "api_key": FAKE_API_KEY},
                              key_storage=watches.STORAGE_ENCRYPTED)
    w_unstored = watches.create({**cfg, "name": "unstored key", "api_key": FAKE_API_KEY},
                                key_storage=watches.STORAGE_MEMORY)
    w_ref = watches.create({**cfg, "name": "key reference", "api_key": "env:FIXTURE_KEY"})
    watches.forget_memory_keys()  # as after a restart: the unstored key is gone
    watch_rows = [
        {"id": w_stored, "name": "stored key", "key": "stored"},
        {"id": w_unstored, "name": "unstored key", "key": "unstored"},
        {"id": w_ref, "name": "key reference", "key": "reference"},
    ]

    _result, ids = import_yaml(KB_YAML, origin="import:fixture.yaml")
    kb_rows = [
        {"id": e["id"], "kind": e["kind"], "provider": e["provider"], "model_id": e["model_id"]}
        for e in kb_store.list_entries()
    ]
    assert ids and kb_rows

    # fold the write-ahead logs into the files so only the databases remain
    for name in DBS:
        c = sqlite3.connect(out / name)
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        c.execute("PRAGMA journal_mode=DELETE")
        c.close()
    for p in list(out.iterdir()):
        if p.name not in DBS:
            p.unlink()
    manifest = {
        "version": ekte.__version__,
        "master_key": FIXTURE_MASTER_KEY,
        "api_key": FAKE_API_KEY,
        "history": runs,
        "watches": watch_rows,
        "kb": kb_rows,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("version", nargs="?", help="released version on PyPI, e.g. 0.31.0")
    ap.add_argument("--write", type=Path, help="(internal) write the fixture into this directory with the ekte on the path")
    ap.add_argument("--report", type=Path, default=REPORT_SAMPLE, help="sample report to store in the history")
    args = ap.parse_args()
    if args.write:
        write(args.write, args.report)
        return 0
    if not args.version:
        ap.error("give the released version, e.g. 0.31.0")
    dest = FIXTURES / f"v{args.version}"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "data"
        cmd = ["uv", "run", "--no-project", "--with", f"ekte[web]=={args.version}", "python", "-I",
               str(Path(__file__).resolve()), "--write", str(out), "--report", str(args.report)]
        subprocess.run(cmd, check=True, cwd=tmp)
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(out, dest)
    print(f"wrote {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
