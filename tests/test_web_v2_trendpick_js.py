"""History's trend picker rules (ekte/web/static/v2/trendpick.js), evaluated
under node: at least one and at most two trends, the others disabled at two,
the last one locked, URL values cleaned (#127)."""

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
require(path.join(process.argv[1], "trendpick.js"));
const P = window.EkteTrendPick;
console.log(JSON.stringify(new Function("P", process.argv[2])(P)));
"""

ORDER = ["score", "grade", "latency_p50", "ttft_p50", "decode_tps", "error_rate"]


def run(body: str) -> Any:
    out = run_subprocess(["node", "-e", _JS, str(STATIC), body],
                         capture_output=True, text=True, encoding="utf-8", check=True).stdout
    return json.loads(out)


def call(fn: str, *args: Any) -> Any:
    return run(f"return P.{fn}({', '.join(json.dumps(a) for a in args)});")


@pytest.mark.parametrize(("value", "want"), [
    ("score,latency_p50", ["score", "latency_p50"]),
    ("latency_p50,score", ["score", "latency_p50"]),  # put in button order
    (["error_rate"], ["error_rate"]),
    ("score,score", ["score"]),
    ("score,bogus,grade,error_rate", ["score", "grade"]),  # at most two, as given
    ("", ["score", "latency_p50"]),  # nothing valid: the fallback
    ("bogus", ["score", "latency_p50"]),
])
def test_clean(value: Any, want: list[str]) -> None:
    assert call("clean", value, ORDER, 2, "score,latency_p50") == want


def test_toggle_keeps_one_to_two() -> None:
    # adding a second, removing one of two
    assert call("toggle", ["score"], "grade", ORDER, 2) == ["score", "grade"]
    assert call("toggle", ["score", "grade"], "score", ORDER, 2) == ["grade"]
    # the last one cannot be turned off, a third cannot be turned on
    assert call("toggle", ["score"], "score", ORDER, 2) == ["score"]
    assert call("toggle", ["score", "grade"], "error_rate", ORDER, 2) == ["score", "grade"]
    assert call("toggle", ["score"], "nope", ORDER, 2) == ["score"]


def test_buttons_disable_the_rest_at_the_maximum() -> None:
    two = call("buttons", ["score", "latency_p50"], ORDER, 2)
    assert [b["id"] for b in two] == ORDER
    assert {b["id"] for b in two if b["pressed"]} == {"score", "latency_p50"}
    # the two selected stay enabled (either may be turned off), the others not
    assert {b["id"] for b in two if b["disabled"]} == set(ORDER) - {"score", "latency_p50"}
    one = call("buttons", ["grade"], ORDER, 2)
    # with one selected, only that one is locked
    assert [b["id"] for b in one if b["disabled"]] == ["grade"]
    assert [b["id"] for b in one if b["pressed"]] == ["grade"]
