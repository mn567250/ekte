"""The page notice (ekte/web/static/v2/notice.js, #193), evaluated under node:
its pure role choice ``EkteNotice.roleFor`` (role="alert" for a critical
notice, role="status" for any other, none with ``role: false``) and
``EkteNotice.levelOf`` ("error" is critical, an unknown level info)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from tests._helpers import run_subprocess

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")

STATIC = Path(__file__).resolve().parent.parent / "ekte" / "web" / "static" / "v2"

_JS = r"""
const path = require("path");
global.window = {};
require(path.join(process.argv[1], "notice.js"));
const N = window.EkteNotice;
const out = JSON.parse(process.argv[2]).map(([fn, arg]) => N[fn](arg));
console.log(JSON.stringify(out));
"""


def run(calls: list[tuple[str, Any]]) -> list[Any]:
    out = run_subprocess(
        ["node", "-e", _JS, str(STATIC), json.dumps(calls)],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout
    return json.loads(out)


@pytest.mark.parametrize(("notice", "role"), [
    ({"level": "critical", "title": "x"}, "alert"),
    ({"level": "error", "title": "x"}, "alert"),
    ({"level": "warning", "title": "x"}, "status"),
    ({"level": "success", "title": "x"}, "status"),
    ({"level": "info", "title": "x"}, "status"),
    ({"title": "x"}, "status"),
    ({"level": "nope", "title": "x"}, "status"),
    ({"level": "info", "role": False}, None),
    ({"level": "critical", "role": False}, None),
    (None, None),
])
def test_role_follows_the_importance(notice, role):
    assert run([("roleFor", notice)]) == [role]


def test_level_of():
    levels = ["info", "success", "warning", "critical", "error", "nope", None, "toString"]
    assert run([("levelOf", lv) for lv in levels]) == [
        "info", "success", "warning", "critical", "critical", "info", "info", "info"]
