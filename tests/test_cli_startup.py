"""CLI startup stays lean: importing zing.cli must not load the heavy stacks.

Every invocation (even `zing --help`) pays for whatever zing.cli imports at module
level, so the httpx client stack, the runner, the knowledge loader, the report
renderers (ReportLab) and asyncio are imported inside the commands that need them.
"""

from __future__ import annotations

import json
import subprocess
import sys

from typer.testing import CliRunner

from zing.cli import app

_LAZY = (
    "httpx",
    "reportlab",
    "asyncio",
    "zing.runner",
    "zing.clients",
    "zing.knowledge",
    "zing.report",
)


def test_import_cli_does_not_load_heavy_modules():
    # A fresh interpreter: this test process has long since imported everything.
    code = (
        "import json, sys\n"
        "import zing.cli\n"
        f"print(json.dumps({{m: m in sys.modules for m in {list(_LAZY)!r}}}))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    ).stdout
    loaded = [m for m, present in json.loads(out).items() if present]
    assert loaded == []


def test_help_still_lists_every_command():
    result = CliRunner().invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("check", "compare", "models", "kb", "serve", "watch", "data-dir"):
        assert cmd in result.output
