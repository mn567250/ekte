"""CLI startup stays lean: importing zing.cli must not load the heavy stacks.

Every invocation (even `zing --help`) pays for whatever zing.cli imports at module
level, so the httpx client stack, the runner, the knowledge loader, the report
renderers (ReportLab) and asyncio are imported inside the commands that need them.
"""

from __future__ import annotations

import json
import re
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
    "zing.detectors",
    "zing.embed_audit",
    "zing.media_audit",
    "zing.web",
    "uvicorn",
)


def test_import_cli_does_not_load_heavy_modules():
    # A fresh interpreter: this test process has long since imported everything.
    code = (
        "import json, sys\n"
        "import zing.cli\n"
        f"print(json.dumps({{m: m in sys.modules for m in {list(_LAZY)!r}}}))\n"
    )
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    loaded = [m for m, present in json.loads(proc.stdout).items() if present]
    assert loaded == []


# rich colours the help when the environment asks for it (FORCE_COLOR, some CI
# runners); the escape codes would sit between the panel border and the name.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def test_help_still_lists_every_command():
    result = CliRunner().invoke(app, ["--help"], env={"COLUMNS": "200"})
    assert result.exit_code == 0
    output = _ANSI.sub("", result.output)
    for cmd in ("check", "compare", "models", "kb", "serve", "watch", "data-dir", "secret"):
        # A command row in rich's help panel: "│ <name>  <help...>".
        assert re.search(rf"^\W*{re.escape(cmd)}\s{{2,}}", output, re.M), cmd
