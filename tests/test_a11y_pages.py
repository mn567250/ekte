"""Page selection of the a11y suite and the changed file -> page mapping.

Pure Python (no browser): tests/a11y/pages.py and tests/a11y/affected.py. One
test collects the real suite in a subprocess and is skipped without Playwright.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.a11y import affected as affected_cli
from tests.a11y import pages
from tests.a11y.pages import (
    ALL,
    PAGES,
    RULES,
    TEST_PAGES,
    Scope,
    affected,
    match,
    matrix,
    pages_of_test,
    parse_pages,
    selected,
)

ROOT = Path(__file__).resolve().parent.parent
SUITE = ROOT / "tests" / "a11y"
V2 = ROOT / "ekte" / "web" / "static" / "v2"
# the HTML file each page id serves
PAGE_HTML = {
    "audit": "index.html",
    "history": "history.html",
    "monitors": "watches.html",
    "kb": "kb.html",
    "analytics": "analytics.html",
    "accessibility": "accessibility.html",
}


def scope(*paths: str) -> Scope:
    return affected(list(paths))


# --------------------------------------------------------------------------- #
# EKTE_A11Y_PAGES
# --------------------------------------------------------------------------- #
def test_parse_pages():
    assert parse_pages("") is None and parse_pages("  ") is None and parse_pages("all") is None
    assert parse_pages("history, kb,") == {"history", "kb"}
    assert parse_pages("tools,all") is None
    with pytest.raises(ValueError, match="reports"):
        parse_pages("history,reports")


def test_pages_of_test():
    # parametrised by page_id
    assert pages_of_test("test_axe.py", "test_wcag_rules_as_loaded", {"page_id": "kb", "lang": "en"}) == {"kb"}
    # test_time_media.py states: "<page>", "<page>+expanded", "<page>-<state>"
    assert pages_of_test("test_time_media.py", "test_no_time_limits", {"state": "kb"}) == {"kb"}
    assert pages_of_test("test_time_media.py", "test_no_time_limits", {"state": "kb+expanded"}) == {"kb"}
    assert pages_of_test("test_time_media.py", "x", {"state": "monitors-running"}) == {"monitors"}
    assert pages_of_test("test_time_media.py", "x", {"state": "history-charts", "theme": "dark"}) == {"history"}
    # a whole file, one test of a file
    assert pages_of_test("test_history_paging.py", "test_show_more_by_keyboard", {}) == {"history"}
    assert pages_of_test("test_flows.py", "test_kb_flow", {"lang": "de"}) == {"kb"}
    assert pages_of_test("test_structure.py", "test_list_states_not_by_colour_alone", {"lang": "en"}) == {"history", "monitors"}
    # cross-page checks and self-checks belong to no page
    assert pages_of_test("test_semantics.py", "test_consistent_navigation_and_landmarks", {"lang": "en"}) is None
    assert pages_of_test("test_structure.py", "test_every_page_reachable_from_every_page", {"viewport": "375px"}) is None
    assert pages_of_test("test_parsing.py", "test_checker_catches_broken_markup", {}) is None
    assert pages_of_test("test_time_media.py", "x", {"state": "nothing-here"}) is None


def test_selected():
    assert selected(frozenset({"kb"}), None)
    assert selected(None, frozenset({"kb"}))  # cross-page tests always run
    assert selected(frozenset({"history", "monitors"}), frozenset({"monitors"}))
    assert not selected(frozenset({"history"}), frozenset({"kb", "tools"}))


def _functions(tree: ast.Module) -> dict[str, ast.FunctionDef]:
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def _pages_named(node: ast.AST) -> set[str]:
    """Pages a piece of test code names: PAGES["id"] or a page's path literal."""
    by_path = {path: pid for pid, path in PAGES.items()}
    found = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Subscript) and isinstance(n.value, ast.Name) and n.value.id == "PAGES":
            if isinstance(n.slice, ast.Constant) and n.slice.value in PAGES:
                found.add(n.slice.value)
        elif isinstance(n, ast.Constant) and isinstance(n.value, str):
            # "/kb", or a URL glob such as "**/watches*"
            path = n.value.removeprefix("**").removesuffix("*")
            if n.value.startswith("**") and path == "/":
                continue  # "**/*" matches any URL; it does not name the audit page
            if path in by_path:
                found.add(by_path[path])
    return found


def test_test_pages_entries_exist_and_cover_the_pages_they_open():
    # a stale entry would silently stop matching; an entry naming too few
    # pages would skip the test when only another page it opens changes
    for key, ids in TEST_PAGES.items():
        assert ids and set(ids) <= set(PAGES), key
        file, _, name = key.partition("::")
        path = SUITE / file
        assert path.is_file(), key
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if name:
            fn = _functions(tree).get(name)
            assert fn is not None, key
            assert not {a.arg for a in fn.args.args} & {"page_id", "state"}, key
            assert _pages_named(fn) <= set(ids), key
        else:
            assert _pages_named(tree) <= set(ids), key


# --------------------------------------------------------------------------- #
# changed files -> pages
# --------------------------------------------------------------------------- #
def test_single_page_files():
    assert scope("ekte/web/static/v2/history.html").as_dict() == {
        "pages": ["history"], "full": False, "reason": "ekte/web/static/v2/history.html -> history"}
    assert scope("ekte/web/static/v2/kbview.js").pages == ("kb",)
    assert scope("ekte/web/static/v2/watches.html", "ekte/web/masterkey.py").pages == ("monitors",)
    assert scope("ekte/web/static/v2/bitv-report.json").pages == ("accessibility",)
    assert scope("tests/a11y/test_history_controls.py").pages == ("history",)
    assert scope("tests/a11y/snapshots/kb-zh.yml").pages == ("kb",)
    assert scope("ekte/web/analytics.py").pages == ("analytics",)
    assert scope("ekte/web/static/v2/charts.js").pages == ("analytics", "accessibility")
    assert scope("ekte/web/static/v2/filterpanel.js").pages == ("history", "monitors", "kb", "analytics")


def test_multi_page_files_union_in_page_order():
    s = scope("ekte/web/static/v2/tabs.js", "ekte/web/static/v2/report.js")
    assert s.pages == ("audit", "history", "monitors", "kb", "analytics") and not s.full
    assert "ekte/web/static/v2/report.js -> audit, history" in s.reason
    assert scope("ekte/i18n/locales/fragments/v2-scoring/de.json").pages == ("audit", "history", "analytics")
    assert scope("ekte/knowledge/data/openai.yaml").pages == ("audit", "kb")


@pytest.mark.parametrize("path", [
    "ekte/web/static/v2/nav.js",
    "ekte/web/static/v2/tokens.css",
    "ekte/web/static/v2/ekte.css",
    "ekte/web/static/v2/theme.js",
    "ekte/web/static/i18n.js",
    "ekte/web/static/locales.js",
    "ekte/web/server.py",
    "ekte/web/security.py",
    "ekte/i18n/locales/de.json",
    "ekte/i18n/__init__.py",
    "ekte/i18n/locales/fragments/v2-history/en.json",  # re-declares "Cancel", used everywhere
    "tests/a11y/harness.py",
    "tests/a11y/conftest.py",
    "tests/a11y/vendor/axe.min.js",
    "tests/a11y/test_axe.py",
    "tests/fixtures/web_report.json",
    ".github/workflows/ci.yml",
    "pyproject.toml",
    "uv.lock",
])
def test_shared_files_run_everything(path):
    s = scope("README.md", path)
    assert s.full and s.pages == tuple(PAGES)
    assert path in s.reason


@pytest.mark.parametrize("path", [
    "ekte/web/static/v2/newpage.html",
    "ekte/web/static/v2/newwidget.js",
    "ekte/web/static/newshared.js",
    "ekte/web/newapi.txt",
    "ekte/i18n/README",  # matched by ekte/i18n/** (all) anyway
    "tests/a11y/new_helper.json",
])
def test_fail_safe_unknown_web_files_run_everything(path):
    s = scope("ekte/web/static/v2/history.html", path)
    assert s.full and s.pages == tuple(PAGES)


def test_fail_safe_is_reached_only_by_unmatched_files():
    assert match("ekte/web/static/v2/newpage.html") is None
    s = scope("ekte/web/static/v2/newpage.html")
    assert s.full and "fail-safe" in s.reason


@pytest.mark.parametrize("paths", [
    ["README.md", "docs/i18n/de/README.md", "docs/guide/methodology.md", "docs/dev/accessibility.md", "CHANGELOG.md"],
    ["tests/test_model_identity.py", "ekte/cli.py", "ekte/__main__.py", "ekte/media_audit.py"],
    ["tests/a11y/README.md", "tests/a11y/llm_review.py", "tests/test_a11y_llm_review.py"],
    [],
])
def test_files_outside_web_ui_v2_select_nothing(paths):
    s = scope(*paths)
    assert s.pages == () and not s.full
    assert matrix(s) == []


def test_audit_pipeline_runs_the_audit_page():
    # test_audit_flow runs a real audit (fake relay) and renders the report
    for path in ("ekte/detectors/model_identity.py", "ekte/runner.py", "ekte/clients/anthropic.py",
                 "ekte/scoring.py", "ekte/utils/sse.py", "ekte/prompts/en.json"):
        assert scope(path).pages == ("audit",), path
    assert scope("ekte/report/render.py").pages == ("audit", "history")
    s = scope("ekte/detectors/context_window.py", "docs/guide/methodology.md", "tests/test_context_window.py")
    assert s.pages == ("audit",) and matrix(s) == [{"shard": "1/1", "pages": "audit"}]


def _imports(*modules: str) -> dict[str, str]:
    """ekte modules reachable from ``modules`` by import (module -> path), also
    through imports inside functions."""
    seen: dict[str, str] = {}
    todo = list(modules)
    while todo:
        mod = todo.pop()
        if mod in seen:
            continue
        path = ROOT / (mod.replace(".", "/") + ".py")
        if not path.exists():
            path = ROOT / mod.replace(".", "/") / "__init__.py"
            if not path.exists():
                continue  # a name imported from a module, not a module
        seen[mod] = path.relative_to(ROOT).as_posix()
        pkg = mod if path.name == "__init__.py" else mod.rpartition(".")[0]
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                todo += [a.name for a in node.names if a.name.startswith("ekte")]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                if node.level:
                    parts = pkg.split(".")
                    base = ".".join(parts[: len(parts) - node.level + 1] + ([base] if base else []))
                if base.startswith("ekte"):
                    todo += [base] + [f"{base}.{a.name}" for a in node.names]
    return seen


def test_every_module_the_server_imports_has_a_rule():
    # a module the web UI runs on can break a page, so none may select nothing
    found = _imports("ekte.web.server")
    assert "ekte/runner.py" in found.values() and "ekte/report/render.py" in found.values()
    for path in found.values():
        got = match(path)
        assert got, f"{path} is imported by the web server but selects no page"


def test_every_module_an_audit_runs_selects_the_audit_page():
    for path in _imports("ekte.runner").values():
        got = match(path)
        assert got == ALL or (got and "audit" in got), f"{path} runs in an audit but does not select the audit page"


def test_every_page_affected_is_a_full_run():
    s = scope(*(f"ekte/web/static/v2/{f}" for f in PAGE_HTML.values()))
    assert s.full and s.pages == tuple(PAGES) and s.reason == "every page is affected"


def test_paths_are_normalised():
    assert scope("./ekte/web/static/v2/kb.html", " ", "ekte/web/static/v2/kb.html\n").pages == ("kb",)


def test_every_existing_ui_file_has_a_rule():
    # the fail-safe is for files added later; today's files are all mapped
    for top in ("ekte/web", "ekte/i18n", "tests/a11y"):
        for path in (ROOT / top).rglob("*"):
            rel = path.relative_to(ROOT).as_posix()
            if path.is_file() and "__pycache__" not in rel:
                assert match(rel) is not None, rel


def _assets(html: str) -> set[str]:
    out = set()
    for ref in re.findall(r'(?:src|href)="(/[^"?#]+\.(?:js|css))', html):
        if ref.startswith("/static/"):
            out.add("ekte/web/static/v2/" + ref.removeprefix("/static/"))
        else:
            out.add("ekte/web/static" + ref)
    for ref in re.findall(r'fetch\("(/static/[^"?#]+)"', html):
        out.add("ekte/web/static/v2/" + ref.removeprefix("/static/"))
    return out


def test_asset_rules_cover_every_page_that_loads_the_asset():
    for pid, file in PAGE_HTML.items():
        assert match(f"ekte/web/static/v2/{file}") == (pid,)
        assets = _assets((V2 / file).read_text(encoding="utf-8"))
        assert assets, file
        for asset in assets:
            got = match(asset)
            assert got is not None, f"{asset} (loaded by {file}) has no rule"
            assert got == ALL or pid in got, f"{asset} is loaded by {file}: its rule must include {pid}"


def test_narrowed_fragments_are_used_only_on_their_pages():
    # a fragment string used by a file of another page would make the rule
    # skip that page; strings are looked up by their English text
    sources = {p.relative_to(ROOT).as_posix(): p.read_text(encoding="utf-8")
               for d in ("ekte/web/static", "ekte/web/static/v2") for p in (ROOT / d).glob("*.*")
               if p.suffix in (".html", ".js")}
    fragments = ROOT / "ekte" / "i18n" / "locales" / "fragments"
    narrowed = [(pat, ids) for pat, ids in RULES if pat.startswith("ekte/i18n/locales/fragments/") and ids != ALL]
    assert narrowed
    for pattern, ids in narrowed:
        name = pattern.split("/")[4]
        keys = json.loads((fragments / name / "en.json").read_text(encoding="utf-8"))["strings"]
        for key in keys:
            quoted = re.compile("[\"']" + re.escape(key) + "[\"']")
            for rel, text in sources.items():
                if quoted.search(text):
                    got = match(rel)
                    assert got is not None and got != ALL and set(got) <= set(ids), (
                        f"{name}: {key!r} is used in {rel} ({got}), outside {ids}")


# --------------------------------------------------------------------------- #
# CI jobs
# --------------------------------------------------------------------------- #
def test_matrix_full_run_keeps_four_round_robin_shards():
    m = matrix(pages.full_scope("push"))
    assert m == [{"shard": f"{k}/4", "pages": "all"} for k in (1, 2, 3, 4)]


def test_matrix_partial_runs_share_the_selection():
    one = matrix(scope("ekte/web/static/v2/watches.html"))
    assert one == [{"shard": "1/1", "pages": "monitors"}]
    two = matrix(scope("ekte/web/static/v2/kb.html", "ekte/web/static/v2/history.html"))
    assert len(two) == 2 and {e["pages"] for e in two} == {"history,kb"}
    five = matrix(scope(*(f"ekte/web/static/v2/{f}" for f in list(PAGE_HTML.values())[:5])))
    assert 2 < len(five) <= 4 and [e["shard"] for e in five] == [f"{k}/{len(five)}" for k in range(1, len(five) + 1)]


def test_job_count_grows_with_the_selection():
    counts = [pages.job_count(list(PAGES)[:n]) for n in range(1, len(PAGES) + 1)]
    assert counts == sorted(counts) and counts[0] == 1 and counts[-1] <= pages.FULL_JOBS
    assert set(pages.WEIGHTS) == set(PAGES) | {"common"}


# --------------------------------------------------------------------------- #
# python -m tests.a11y.affected
# --------------------------------------------------------------------------- #
def test_cli_files_and_full(capsys):
    assert affected_cli.main(["--files", "ekte/web/static/v2/kb.html", "README.md"]) == 0
    assert json.loads(capsys.readouterr().out) == {"pages": ["kb"], "full": False, "reason": "ekte/web/static/v2/kb.html -> kb"}
    affected_cli.main(["--full", "nightly"])
    out = json.loads(capsys.readouterr().out)
    assert out["full"] and out["pages"] == list(PAGES) and out["reason"] == "nightly"


def test_cli_stdin(capsys, monkeypatch):
    import io

    monkeypatch.setattr(sys, "stdin", io.StringIO("docs/guide/github-action.md\nekte/web/static/v2/watches.html\n"))
    affected_cli.main(["--files", "-"])
    assert json.loads(capsys.readouterr().out)["pages"] == ["monitors"]


def test_cli_git_failure_runs_everything(capsys, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # not a git repository
    affected_cli.main(["--base", "deadbeef", "--head", "cafebabe"])
    out = json.loads(capsys.readouterr().out)
    assert out["full"] and "failed" in out["reason"]


def test_cli_git_diff(capsys):
    # the merge base of HEAD with itself: no changes
    if subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True).returncode:
        pytest.skip("not a git checkout")
    affected_cli.main(["--base", "HEAD", "--head", "HEAD"])
    assert json.loads(capsys.readouterr().out) == {"pages": [], "full": False, "reason": "no changed files"}


def test_cli_github_output(capsys, tmp_path, monkeypatch):
    target = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(target))
    affected_cli.main(["--files", "ekte/web/static/v2/history.html", "--github-output"])
    lines = dict(line.split("=", 1) for line in target.read_text(encoding="utf-8").splitlines())
    assert lines["pages"] == "history" and lines["full"] == "false" and lines["run"] == "true"
    assert json.loads(lines["matrix"]) == {"include": matrix(scope("ekte/web/static/v2/history.html"))}
    target.unlink()
    affected_cli.main(["--files", "README.md", "--github-output"])
    lines = dict(line.split("=", 1) for line in target.read_text(encoding="utf-8").splitlines())
    assert lines["run"] == "false" and lines["pages"] == "" and json.loads(lines["matrix"]) == {"include": []}


# --------------------------------------------------------------------------- #
# the real suite (collection only)
# --------------------------------------------------------------------------- #
def _collect(**env: str) -> subprocess.CompletedProcess[str]:
    pytest.importorskip("playwright.sync_api")
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests/a11y", "-m", "a11y", "--collect-only", "-q", "-p", "no:cacheprovider",
         "-p", "no:xdist"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", env={**os.environ, **env}, timeout=120,
    )


def _ids(proc: subprocess.CompletedProcess[str]) -> list[str]:
    return [line for line in proc.stdout.splitlines() if "::" in line]


def test_collection_selects_pages_and_rejects_unknown_ids():
    everything = _ids(_collect(EKTE_A11Y_PAGES="all"))
    history = _ids(_collect(EKTE_A11Y_PAGES="history"))
    assert 0 < len(history) < len(everything)
    assert any("test_history_paging.py" in i for i in history)
    assert not any("-kb-" in i or "[kb-" in i or "test_kb_flow" in i for i in history)
    # cross-page checks stay
    assert any("test_consistent_navigation_and_landmarks" in i for i in history)
    # with the shard on top: the parts add up to the selection
    parts = [_ids(_collect(EKTE_A11Y_PAGES="history", EKTE_A11Y_SHARD=f"{k}/2")) for k in (1, 2)]
    assert sorted(parts[0] + parts[1]) == sorted(history)
    bad = _collect(EKTE_A11Y_PAGES="history,reports")
    assert bad.returncode != 0 and "unknown page id(s) reports" in bad.stderr + bad.stdout
