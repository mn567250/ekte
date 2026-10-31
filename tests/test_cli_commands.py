"""Every command's success path, main error paths, exit codes and machine output (issue #32).

Complements tests/test_cli_contract.py (help texts, the exit-code table, ``--json``
purity). Commands run in-process through Typer's ``CliRunner``. No test reaches
the network: every ``httpx.AsyncClient`` gets an in-process ``MockTransport``
that routes by URL path; a request nothing is routed for answers 404 instead of
leaving the machine.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from ekte import cli
from tests._helpers import MockServer
from tests.test_embed_surface import EmbedServer
from tests.test_media import AudioMock, ImageMock
from tests.test_rerank_surface import RerankServer

runner = CliRunner()
BASE = "https://relay.cli.test/v1"
TARGET = ["--base-url", BASE, "--model", "gpt-4o", "--api-key", "sk-cli-secret-123456"]


class Routes:
    """Routes requests by path suffix to the mock servers a test installs."""

    def __init__(self) -> None:
        self.table: list[tuple[str, httpx.MockTransport | object]] = []
        self.hooks: list[httpx.Request] = []

    def add(self, suffix: str, handler) -> None:
        self.table.append((suffix, handler))

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        for suffix, handler in self.table:
            if path.endswith(suffix):
                return handler(request)
        if path.endswith("/hook"):
            self.hooks.append(request)
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(404, json={"error": {"message": f"no route for {path}"}})


@pytest.fixture
def routes(monkeypatch, tmp_path) -> Routes:
    r = Routes()
    original = httpx.AsyncClient.__init__

    def init(self, *args, **kwargs):
        kwargs["transport"] = kwargs.get("transport") or httpx.MockTransport(r)
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", init)
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EKTE_NO_USER_KB", "1")
    monkeypatch.delenv("EKTE_SECRET_KEY", raising=False)
    return r


@pytest.fixture
def chat(routes) -> MockServer:
    server = MockServer()
    routes.add("/models", server.handler)
    routes.add("/chat/completions", server.handler)
    return server


def _invoke(*args: str):
    return runner.invoke(cli.app, list(args))


def _quick(*extra: str) -> list[str]:
    return [*TARGET, "--suite", "smoke", "--reliability-requests", "0", "--performance-requests", "0", *extra]


# --------------------------------------------------------------------------- init
def test_init_writes_a_starter_config_that_check_can_read(tmp_path):
    path = tmp_path / "starter.yaml"
    res = _invoke("init", "--path", str(path))
    assert res.exit_code == 0 and path.exists()
    assert _invoke("config", "migrate", str(path), "--check").exit_code == 0


def test_init_refuses_to_overwrite_without_force(tmp_path):
    path = tmp_path / "ekte.yaml"
    path.write_text("keep me", encoding="utf-8")
    assert _invoke("init", "--path", str(path)).exit_code == 2
    assert path.read_text(encoding="utf-8") == "keep me"
    assert _invoke("init", "--path", str(path), "--force").exit_code == 0
    assert path.read_text(encoding="utf-8") != "keep me"


# --------------------------------------------------------------------------- check
def test_check_writes_reports_and_prints_a_summary(chat, tmp_path):
    out = tmp_path / "reports"
    res = _invoke("check", *_quick("--out-dir", str(out), "--format", "all"))
    assert res.exit_code == 0, res.output
    assert "Dimensions" in res.output and "Reports" in res.output
    names = sorted(p.suffix for p in out.iterdir())
    assert {".json", ".md", ".html"} <= set(names)
    report = json.loads(next(out.glob("*.json")).read_text("utf-8"))
    assert report["mode"] == "check" and report["target"]["model"] == "gpt-4o"
    assert "sk-cli-secret-123456" not in json.dumps(report)


def test_check_single_format_writes_only_that_format(chat, tmp_path):
    out = tmp_path / "md"
    assert _invoke("check", *_quick("--out-dir", str(out), "--format", "md")).exit_code == 0
    assert {p.suffix for p in out.iterdir()} == {".md"}


def test_check_json_prints_the_full_report_and_writes_no_files(chat, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    res = _invoke("check", *_quick("--json"))
    assert res.exit_code == 0, res.output
    report = json.loads(res.stdout)
    assert {"verdict", "dimensions", "detectors", "target"} <= set(report)
    assert not (tmp_path / "reports").exists()


def test_check_compact_prints_the_lean_verdict(chat):
    res = _invoke("check", *_quick("--compact"))
    assert res.exit_code == 0, res.output
    data = json.loads(res.stdout)
    assert data["tool"] == "ekte" and "verdict" in data and "findings" in data


def test_check_gates_set_exit_code_1(chat):
    assert _invoke("check", *_quick("--json", "--fail-under", "101")).exit_code == 1
    assert _invoke("check", *_quick("--json", "--fail-under", "0")).exit_code == 0
    assert _invoke("check", *_quick("--json", "--fail-on-risk", "high")).exit_code in (0, 1)


def test_check_configuration_errors_exit_2(routes, tmp_path):
    assert _invoke("check").exit_code == 2  # no base URL / model
    assert _invoke("check", *TARGET, "--suite", "nonsense").exit_code == 2
    assert _invoke("check", *TARGET, "--format", "docx").exit_code == 2
    assert _invoke("check", "--config", str(tmp_path / "missing.yaml")).exit_code == 2
    res = _invoke("check", "--json")
    assert res.exit_code == 2
    assert json.loads(res.stdout)["error"]["type"] == "config_error"


def test_check_reads_target_and_options_from_a_config_file(chat, tmp_path):
    cfg = tmp_path / "ekte.yaml"
    cfg.write_text(
        f"target:\n  base_url: {BASE}\n  model: gpt-4o\n  api_key: sk-from-file\n"
        "run:\n  suite: smoke\n  reliability_requests: 0\n  performance_requests: 0\n",
        encoding="utf-8",
    )
    res = _invoke("check", "--config", str(cfg), "--json")
    assert res.exit_code == 0, res.output
    assert json.loads(res.stdout)["suite"] == "smoke"


def test_check_dry_run_lists_detectors_without_a_request(chat):
    res = _invoke("check", *TARGET, "--suite", "standard", "--dry-run")
    assert res.exit_code == 0 and "Dry run" in res.output
    assert chat.requests == []
    plan = json.loads(_invoke("check", *TARGET, "--dry-run", "--json").stdout)
    assert plan["dry_run"] is True and plan["estimated_api_calls"] > 0 and plan["detectors"]


def test_check_dimension_selection_runs_the_custom_suite(chat):
    plan = json.loads(_invoke("check", *TARGET, "-D", "streaming", "--dry-run", "--json").stdout)
    assert plan["suite"] == "custom" and plan["dimensions"] == ["streaming"]


# --------------------------------------------------------------------------- compare
def test_compare_needs_a_baseline_and_reports_both_sides(chat):
    assert _invoke("compare", "--json").exit_code == 2
    res = _invoke(
        "compare", "--target-base-url", BASE, "--target-model", "gpt-4o", "--suite", "smoke",
        "--performance-requests", "0", "--json",
        "--baseline-base-url", BASE, "--baseline-model", "gpt-4o",
        "--baseline-api-key", "sk-baseline-secret",
    )
    assert res.exit_code == 0, res.output
    report = json.loads(res.stdout)
    assert report["mode"] == "compare" and report["baseline"]["model"] == "gpt-4o"
    assert "sk-baseline-secret" not in res.stdout


def test_compare_dry_run_and_bad_option(routes):
    args = [
        "compare", "--target-base-url", BASE, "--target-model", "m",
        "--baseline-base-url", BASE, "--baseline-model", "b",
    ]
    plan = json.loads(_invoke(*args, "--dry-run", "--json").stdout)
    assert plan["mode"] == "compare" and plan["baseline"]["model"] == "b"
    assert _invoke(*args, "--dry-run").exit_code == 0
    assert _invoke(*args, "--fail-on-risk", "nope").exit_code == 2


# --------------------------------------------------------------------------- models
def test_models_lists_what_the_endpoint_advertises(chat):
    res = _invoke("models", "--base-url", BASE)
    assert res.exit_code == 0 and "gpt-4o" in res.output
    data = json.loads(_invoke("models", "--base-url", BASE, "--json").stdout)
    assert data["ok"] is True and "gpt-4o" in data["models"] and data["count"] == len(data["models"])


def test_models_endpoint_failure_exits_3(chat):
    chat.models_status = 500
    res = _invoke("models", "--base-url", BASE)
    assert res.exit_code == 3 and "Failed" in res.output
    data = json.loads(_invoke("models", "--base-url", BASE, "--json").stdout)
    assert data["ok"] is False and data["error"]["status_code"] == 500


def test_models_bad_url_is_a_usage_error(routes):
    assert _invoke("models", "--base-url", "not a url").exit_code == 2
    res = _invoke("models", "--base-url", "not a url", "--json")
    assert res.exit_code == 2 and json.loads(res.stdout)["error"]["type"] == "config_error"


# --------------------------------------------------------------------------- knowledge base
def test_kb_table_json_and_provider_filter():
    res = _invoke("kb")
    assert res.exit_code == 0 and "knowledge base" in res.output
    everything = json.loads(_invoke("kb", "--json").stdout)
    only = json.loads(_invoke("kb", "openai", "--json").stdout)
    assert everything["count"] >= only["count"] > 0
    assert only["providers"] == ["openai"] and all(m["provider"] == "openai" for m in only["models"])
    assert json.loads(_invoke("kb", "no-such-provider", "--json").stdout)["count"] == 0
    assert _invoke("kb", "openai", "--no-user-kb").exit_code == 0


def test_kb_prompt_names_the_model():
    res = _invoke("kb-prompt", "acme-model-9", "--provider", "acme")
    assert res.exit_code == 0 and "acme-model-9" in res.output


_PROFILE = """\
provider: acme
display_name: Acme
models:
  - id: acme-1
    context_window_tokens: 32000
    max_output_tokens: 4096
"""


def test_kb_import_check_import_and_export_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("EKTE_NO_USER_KB", raising=False)
    f = tmp_path / "acme.yaml"
    f.write_text(_PROFILE, encoding="utf-8")

    res = _invoke("kb-import", str(f), "--check")
    assert res.exit_code == 0 and "Check passed" in res.output

    checked = json.loads(_invoke("kb-import", str(f), "--check", "--json").stdout)
    assert checked["entry_ids"] == []

    res = _invoke("kb-import", str(f))
    assert res.exit_code == 0 and "Stored" in res.output and "acme/acme-1" in res.output
    stored = json.loads(_invoke("kb-import", str(f), "--json").stdout)
    assert stored["entry_ids"]

    exported = _invoke("kb-export")
    assert exported.exit_code == 0 and "acme-1" in exported.stdout
    assert "acme-1" not in _invoke("kb-export", "--provider", "other").stdout
    assert "acme-1" in _invoke("kb", "acme", "--json").stdout


def test_kb_import_rejects_a_bad_file_and_a_missing_one(tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path / "data"))
    bad = tmp_path / "bad.yaml"
    bad.write_text("not: [a, provider", encoding="utf-8")
    res = _invoke("kb-import", str(bad))
    assert res.exit_code == 1 and "Not imported" in res.output
    assert _invoke("kb-import", str(bad), "--json").exit_code == 1
    assert _invoke("kb-import", str(tmp_path / "missing.yaml")).exit_code == 2


# --------------------------------------------------------------------------- data-dir / config
def test_data_dir_prints_the_directory_and_honours_the_global_option(tmp_path, monkeypatch):
    monkeypatch.delenv("EKTE_DATA_DIR", raising=False)
    res = _invoke("--data-dir", str(tmp_path / "elsewhere"), "data-dir")
    assert res.exit_code == 0 and res.stdout.strip() == str((tmp_path / "elsewhere").resolve())
    data = json.loads(_invoke("data-dir", "--json").stdout)
    assert data["data_dir"] == str((tmp_path / "elsewhere").resolve())


def test_no_arguments_prints_the_help():
    res = _invoke()
    assert "Usage" in res.output and "COMMAND" in res.output


def test_config_migrate_rewrites_with_a_backup(tmp_path):
    f = tmp_path / "ekte.yaml"
    old = "target:\n  base_url: https://x.test/v1\n"
    f.write_text(old, encoding="utf-8")
    res = _invoke("config", "migrate", str(f))
    assert res.exit_code == 0 and "Updated" in res.output
    assert (tmp_path / "ekte.yaml.bak").read_text(encoding="utf-8") == old
    assert f.read_text(encoding="utf-8") != old
    again = _invoke("config", "migrate", str(f))
    assert again.exit_code == 0 and "already" in again.output
    assert json.loads(_invoke("config", "migrate", str(f), "--json").stdout)["status"] == "current"


def test_config_migrate_check_and_json_report_the_changes(tmp_path):
    f = tmp_path / "ekte.yaml"
    f.write_text("target:\n  base_url: https://x.test/v1\n", encoding="utf-8")
    res = _invoke("config", "migrate", str(f), "--check")
    assert res.exit_code == 1 and "outdated" in res.output
    data = json.loads(_invoke("config", "migrate", str(f), "--check", "--json").stdout)
    assert data["status"] == "outdated" and data["changes"] and data["backup"] is None
    assert not (tmp_path / "ekte.yaml.bak").exists()
    updated = json.loads(_invoke("config", "migrate", str(f), "--json").stdout)
    assert updated["status"] == "updated" and updated["backup"].endswith(".bak")


# --------------------------------------------------------------------------- embed / rerank
def test_embed_audit_success_json_and_gate(routes):
    server = EmbedServer(dim=64)
    routes.add("/embeddings", server._handle)
    routes.add("/models", server._handle)
    args = ["embed", "--base-url", BASE, "--model", "text-embedding-3-large", "--claimed-dimensions", "64"]
    res = _invoke(*args, "--no-save")
    assert res.exit_code == 0 and "Embedding audit" in res.output
    data = json.loads(_invoke(*args, "--no-save", "--json").stdout)
    assert {"risk_level", "score", "findings", "target"} <= set(data)
    wrong = _invoke(*args[:-1], "4096", "--no-save", "--json", "--fail-on-risk", "low")
    assert wrong.exit_code == 1


def test_embed_errors_and_dry_run(routes):
    assert _invoke("embed").exit_code == 2
    assert _invoke("embed", *TARGET, "--suite", "huge").exit_code == 2
    assert _invoke("embed", *TARGET, "--fail-on-risk", "nope").exit_code == 2
    res = _invoke("embed", *TARGET, "--dry-run")
    assert res.exit_code == 0 and "Dry run" in res.output


def test_rerank_audit_success_and_gate(routes):
    server = RerankServer()
    routes.add("/rerank", server._handle)
    routes.add("/models", server._handle)
    args = ["rerank", "--base-url", BASE, "--model", "acme-rerank-v2"]
    res = _invoke(*args, "--no-save")
    assert res.exit_code == 0, res.output
    assert json.loads(_invoke(*args, "--no-save", "--json").stdout)["findings"]

    # an endpoint that ranks backwards is a substituted or broken model
    swapped = RerankServer(reverse=True)
    routes.table.clear()
    routes.add("/rerank", swapped._handle)
    routes.add("/models", swapped._handle)
    res = _invoke(*args, "--no-save", "--json", "--fail-on-risk", "low")
    assert res.exit_code == 1

    # a failing endpoint is inconclusive, which never trips the gate
    broken = RerankServer(status=500)
    routes.table.clear()
    routes.add("/rerank", broken._handle)
    routes.add("/models", broken._handle)
    res = _invoke(*args, "--no-save", "--json", "--fail-on-risk", "low")
    assert res.exit_code == 0 and json.loads(res.stdout)["risk_level"] == "inconclusive"


def test_rerank_errors(routes):
    assert _invoke("rerank").exit_code == 2
    assert _invoke("rerank", *TARGET, "--fail-on-risk", "nope", "--json").exit_code == 2
    assert _invoke("rerank", *TARGET, "--dry-run").exit_code == 0


# --------------------------------------------------------------------------- image / audio
def test_image_audit_saves_a_sample_and_prints_json(routes, tmp_path):
    routes.add("/images/generations", ImageMock(width=64, height=64)._handler)
    sample = tmp_path / "sample.png"
    args = ["image", "--base-url", BASE, "--model", "acme-image", "--size", "64x64"]
    res = _invoke(*args, "--save-to", str(sample))
    assert res.exit_code == 0 and "Image generation audit" in res.output and "Saved sample" in res.output
    assert sample.read_bytes().startswith(b"\x89PNG")
    data = json.loads(_invoke(*args, "--json").stdout)
    assert data["risk_level"] in {"clean", "low"} and data["findings"]


def test_image_wrong_size_trips_the_gate(routes):
    routes.add("/images/generations", ImageMock(width=32, height=32)._handler)
    res = _invoke("image", "--base-url", BASE, "--model", "dall-e-3", "--size", "64x64",
                  "--json", "--fail-on-risk", "medium")
    assert res.exit_code == 1


def test_image_deprecated_save_still_works_with_a_warning(routes, tmp_path):
    routes.add("/images/generations", ImageMock(width=16, height=16)._handler)
    sample = tmp_path / "old.png"
    res = _invoke("image", "--base-url", BASE, "--model", "dall-e-3", "--size", "16x16",
                  "--save", str(sample))
    assert res.exit_code == 0 and sample.exists()
    assert "--save-to" in res.output


def test_image_errors(routes):
    assert _invoke("image").exit_code == 2
    res = _invoke("image", "--json")
    assert res.exit_code == 2 and "error" in json.loads(res.stdout)
    assert _invoke("image", *TARGET, "--fail-on-risk", "nope").exit_code == 2


def test_audio_audit_saves_a_clip_and_prints_json(routes, tmp_path):
    routes.add("/audio/speech", AudioMock()._handler)
    clip = tmp_path / "clip.wav"
    args = ["audio", "--base-url", BASE, "--model", "tts-1"]
    res = _invoke(*args, "--save-to", str(clip))
    assert res.exit_code == 0 and "Audio (TTS)" in res.output and "Saved sample clip" in res.output
    assert clip.read_bytes().startswith(b"RIFF")
    data = json.loads(_invoke(*args, "--audio-format", "wav", "--json").stdout)
    assert data["risk_level"] in {"clean", "low"}


def test_audio_garbage_trips_the_gate(routes):
    routes.add("/audio/speech", AudioMock(garbage=True)._handler)
    res = _invoke("audio", "--base-url", BASE, "--model", "tts-1", "--json", "--fail-on-risk", "medium")
    assert res.exit_code == 1


def test_audio_deprecated_options_still_work(routes, tmp_path):
    routes.add("/audio/speech", AudioMock()._handler)
    clip = tmp_path / "old.wav"
    res = _invoke("audio", "--base-url", BASE, "--model", "tts-1", "--format", "wav", "--save", str(clip))
    assert res.exit_code == 0 and clip.exists()
    assert "--audio-format" in res.output and "--save-to" in res.output


def test_audio_errors(routes):
    assert _invoke("audio").exit_code == 2
    assert _invoke("audio", *TARGET, "--fail-on-risk", "nope").exit_code == 2


# --------------------------------------------------------------------------- watch
def test_watch_once_runs_a_cycle_and_prints_json_lines(chat, routes):
    res = _invoke("watch", *TARGET, "--suite", "smoke", "--once", "--json")
    assert res.exit_code == 0, res.output
    lines = [json.loads(line) for line in res.stdout.splitlines() if line.strip()]
    assert len(lines) == 1
    cycle = lines[0]
    assert cycle["event"] == "cycle" and cycle["claimed_model"] == "gpt-4o"
    assert isinstance(cycle["alert"], bool) and "risk_level" in cycle


def test_watch_posts_an_alert_to_the_webhook(chat, routes):
    chat.self_identity = "I am Doubao, a model by ByteDance."
    chat.served_model = "gpt-3.5-turbo"
    res = _invoke(
        "watch", *TARGET, "--suite", "standard", "--once", "--alert-on", "low",
        "--webhook", "https://hooks.cli.test/hook", "--webhook-kind", "generic",
    )
    assert res.exit_code == 0, res.output
    assert routes.hooks and routes.hooks[0].method == "POST"
    assert "alert" in res.output


def test_watch_alert_without_a_webhook_says_so(chat):
    chat.self_identity = "I am Doubao, a model by ByteDance."
    chat.served_model = "gpt-3.5-turbo"
    res = _invoke("watch", *TARGET, "--suite", "standard", "--once", "--alert-on", "low")
    assert res.exit_code == 0 and "no --webhook configured" in res.output


def test_watch_configuration_errors_exit_2(routes):
    assert _invoke("watch", "--once").exit_code == 2
    assert _invoke("watch", *TARGET, "--alert-on", "nope", "--once").exit_code == 2
    assert _invoke("watch", *TARGET, "--alert-lang", "xx", "--once").exit_code == 2
    res = _invoke("watch", *TARGET, "--alert-lang", "xx", "--once", "--json")
    assert res.exit_code == 2 and "error" in json.loads(res.stdout)


# --------------------------------------------------------------------------- serve
def test_serve_starts_the_server_on_loopback(monkeypatch, tmp_path):
    pytest.importorskip("uvicorn")
    started = {}

    def fake_run(app, **kwargs):
        started.update(kwargs)

    monkeypatch.setattr("uvicorn.run", fake_run)
    res = _invoke("serve", "--no-open", "--port", "8765", "--data-dir", str(tmp_path / "d"))
    assert res.exit_code == 0, res.output
    assert started["host"] == "127.0.0.1" and started["port"] == 8765
    assert "http://localhost:8765" in res.output


def test_serve_refuses_a_public_bind_address(monkeypatch):
    pytest.importorskip("uvicorn")
    monkeypatch.delenv("EKTE_CONTAINER", raising=False)
    monkeypatch.setattr("uvicorn.run", lambda *a, **k: pytest.fail("must not start"))
    assert _invoke("serve", "--host", "0.0.0.0", "--no-open").exit_code == 2


def test_serve_without_the_web_extra_exits_2(monkeypatch):
    monkeypatch.setitem(sys.modules, "uvicorn", None)
    res = _invoke("serve", "--no-open")
    assert res.exit_code == 2 and "web" in res.output


# --------------------------------------------------------------------------- secret
@pytest.fixture
def fresh_vault(routes):
    """A first start of the master-key vault (it is process-wide state)."""
    from ekte.web.masterkey import vault

    vault.reset_state()
    yield vault
    vault.reset_state()


def test_secret_status_reports_an_uninitialized_key_as_text_and_json(fresh_vault):
    res = _invoke("secret", "status")
    assert res.exit_code == 0 and "master key" in res.output
    data = json.loads(_invoke("secret", "status", "--json").stdout)
    assert data["state"] == "uninitialized" and data["source"] is None


def test_secret_export_without_a_key_exits_2(fresh_vault):
    res = _invoke("secret", "export")
    assert res.exit_code == 2 and "no master key" in res.output


def test_secret_rotate_creates_a_key_that_status_does_not_leak(fresh_vault):
    res = _invoke("secret", "rotate")
    assert res.exit_code == 0, res.output
    key = res.stdout.strip().splitlines()[-1]
    assert len(key) >= 16
    status = _invoke("secret", "status")
    assert key not in status.output


def test_secret_with_an_environment_key(fresh_vault, monkeypatch):
    from ekte import secretbox

    key = secretbox.generate_key()
    monkeypatch.setenv("EKTE_SECRET_KEY", key)
    fresh_vault.reset_state()
    data = json.loads(_invoke("secret", "status", "--json").stdout)
    assert data["state"] == "ready" or data["source"]
    exported = _invoke("secret", "export")
    assert exported.exit_code == 0 and exported.stdout.strip() == key
    # a single environment key: rotation is two steps and prints "new,old"
    rotated = _invoke("secret", "rotate")
    assert rotated.exit_code == 0
    new_pair = rotated.stdout.strip().splitlines()[-1]
    assert new_pair.endswith(key) and "," in new_pair
    # with the new key first, rotation re-encrypts and succeeds
    monkeypatch.setenv("EKTE_SECRET_KEY", new_pair)
    fresh_vault.reset_state()
    again = _invoke("secret", "rotate")
    assert again.exit_code == 0 and "Re-encrypted" in again.output


def test_secret_status_with_a_bad_environment_key(fresh_vault, monkeypatch):
    monkeypatch.setenv("EKTE_SECRET_KEY", "not-a-valid-key")
    res = _invoke("secret", "status")
    assert res.exit_code == 0
    assert _invoke("secret", "export").exit_code == 2


# --------------------------------------------------------------------------- helpers
def test_run_wrapper_returns_the_typer_exit_code(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["ekte", "data-dir"])
    with pytest.raises(SystemExit) as exc:
        cli.run()
    assert exc.value.code == 0


def test_main_module_entry_point(monkeypatch):
    import runpy

    monkeypatch.setattr(sys, "argv", ["ekte", "data-dir"])
    with pytest.raises(SystemExit) as exc:
        runpy.run_module("ekte", run_name="__main__")
    assert exc.value.code == 0


def test_exit_code_helpers_ignore_unknown_levels():
    class V:
        overall_score = None
        risk_level = cli.RiskLevel.HIGH

    class R:
        verdict = V()

    assert cli._exit_code(R(), 50.0, None) == 0  # type: ignore[arg-type]
    assert cli._exit_code(R(), None, "bogus") == 0  # type: ignore[arg-type]
    assert cli._embed_exit_code({"risk_level": "high"}, "bogus") == 0
    assert cli._embed_exit_code({"risk_level": "inconclusive"}, "low") == 0
    assert Path(".")  # keep Path import used
