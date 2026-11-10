"""The performance budget report: tests/bench_report.py writes it,
scripts/bench_report.py renders it (issue #162). No benchmark runs here."""

import importlib.util
import json
from pathlib import Path

from tests import bench_report

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("bench_report_script", ROOT / "scripts" / "bench_report.py")
assert _spec and _spec.loader
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)


def test_record_without_report_env_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.delenv(bench_report.REPORT_ENV, raising=False)
    monkeypatch.chdir(tmp_path)
    bench_report.record("query", {"a": (1.0, 2.0)}, 50)
    assert list(tmp_path.iterdir()) == []


def test_record_collects_suites_and_replaces_a_case(tmp_path, monkeypatch):
    out = tmp_path / "sub" / "bench.json"
    monkeypatch.setenv(bench_report.REPORT_ENV, str(out))
    bench_report.record("query", {"a": (1.0, 2.0), "b": (40.0, 60.0)}, 50)
    bench_report.record("history_api", {"a": (3.0, 4.0)}, 50)
    bench_report.record("query", {"b": (10.0, 20.0)}, 50)
    cases = json.loads(out.read_text(encoding="utf-8"))["cases"]
    assert {(c["suite"], c["case"]): (c["p95_ms"], c["ok"]) for c in cases} == {
        ("query", "a"): (2.0, True), ("history_api", "a"): (4.0, True), ("query", "b"): (20.0, True)}
    # over budget means "not below", as the tests assert
    bench_report.record("query", {"b": (10.0, 50.0)}, 50)
    assert [c["ok"] for c in json.loads(out.read_text(encoding="utf-8"))["cases"]
            if c["case"] == "b"] == [False]


def test_budget_reads_its_variable(monkeypatch):
    monkeypatch.delenv("EKTE_BENCH_BUDGET_MS", raising=False)
    monkeypatch.delenv("EKTE_BENCH_VERSION_BUDGET_MS", raising=False)
    assert bench_report.budget() == 50
    assert bench_report.budget(5, "EKTE_BENCH_VERSION_BUDGET_MS") == 5
    monkeypatch.setenv("EKTE_BENCH_BUDGET_MS", "120")
    monkeypatch.setenv("EKTE_BENCH_VERSION_BUDGET_MS", "8")
    assert bench_report.budget() == 120
    assert bench_report.budget(5, "EKTE_BENCH_VERSION_BUDGET_MS") == 8


def test_render_marks_cases_over_budget(tmp_path, monkeypatch):
    out = tmp_path / "bench.json"
    monkeypatch.setenv(bench_report.REPORT_ENV, str(out))
    bench_report.record("query", {"fast": (1.0, 2.0), "slow | pipe": (70.0, 90.0)}, 50)
    summary = tmp_path / "summary.md"
    summary.write_text("before\n", encoding="utf-8")
    assert script.main([str(out), "--out", str(summary), "--note", "CI budget 50 ms"]) == 0
    text = summary.read_text(encoding="utf-8")
    assert text.startswith("before\n### Performance budget\n\nCI budget 50 ms\n")
    assert "**1 of 2 cases over budget.**" in text
    assert "| query | fast | 1.0 ms | 2.0 ms | 50.0 ms | ✅ |" in text
    assert "| query | slow \\| pipe | 70.0 ms | 90.0 ms | 50.0 ms | ❌ |" in text


def test_render_without_results(tmp_path, capsys):
    assert script.main([str(tmp_path / "missing.json")]) == 0
    assert "No results" in capsys.readouterr().out
    (tmp_path / "bad.json").write_text("{not json", encoding="utf-8")
    assert script.load(tmp_path / "bad.json") == []
    assert "All 1 cases within budget" in script.render(
        [{"suite": "s", "case": "c", "p50_ms": 1, "p95_ms": 2, "budget_ms": 5, "ok": True}])
