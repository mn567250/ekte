"""Tests for the local web server (`ekte serve`).

Skipped automatically when the optional web extra (fastapi) isn't installed.
These don't hit the network: they cover health, the served SPA, and the
validation/error path of the SSE endpoint.
"""

from __future__ import annotations

import re

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from ekte.web.server import create_app  # noqa: E402

_VERSION = re.compile(r"\?v=[0-9a-f]+(?=[\"'])")


def _unversioned(html: str) -> str:
    """A served page as written on disk: without the ?v=<hash> on asset URLs."""
    return _VERSION.sub("", html)


@pytest.fixture
def client():
    return TestClient(create_app(), base_url="http://localhost")


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["name"] == "ekte"


def test_serves_spa(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "ekte" in r.text and "中转站" in r.text


def test_spa_fallback_for_deep_link(client):
    r = client.get("/some/deep/link")
    assert r.status_code == 200
    assert "<!doctype html>" in r.text.lower()


def test_audit_stream_bad_input_is_clean_error(client):
    # No base_url/model → a clean SSE error event, not a 500.
    r = client.post("/api/audit/stream", json={"model": "", "base_url": ""})
    assert r.status_code == 200
    assert "text/event-stream" in r.headers["content-type"]
    assert '"type": "error"' in r.text
    assert '"type": "done"' in r.text


def test_audit_stream_unknown_suite_errors(client):
    r = client.post(
        "/api/audit/stream",
        json={"base_url": "https://x.example/v1", "model": "gpt-4o", "suite": "bogus"},
    )
    assert '"type": "error"' in r.text


def test_serves_console_and_history_and_i18n(client):
    for path in ("/console", "/history"):
        r = client.get(path)
        assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    j = client.get("/i18n.js")
    assert j.status_code == 200 and "EKTE_I18N" in j.text


def test_serves_lang_js_and_pages_load_it(client):
    js = client.get("/lang.js")
    assert js.status_code == 200
    assert "application/javascript" in js.headers["content-type"]
    assert "EKTE_LANG" in js.text
    loc = client.get("/locales.js")
    assert loc.status_code == 200
    assert "application/javascript" in loc.headers["content-type"]
    assert "EKTE_LOCALES" in loc.text
    for path in ("/", "/console", "/history", "/tools", "/watches"):
        html = _unversioned(client.get(path).text)
        # locales must load before lang.js, which reads them at switch time
        assert '<script src="/locales.js"></script>\n<script src="/lang.js"></script>' in html
        # the dropdown is filled from LANG_LIST in lang.js, not per page
        assert 'class="lang-sel"' in html and "<option" not in html.split('class="lang-sel"')[1].split("</select>")[0]
    # the language list and translations come from ekte/i18n/locales/*.json
    assert loc.text.startswith("window.EKTE_I18N_DATA = {")
    for code in ("en", "zh", "fr", "es", "pt", "it", "de"):
        assert f'"code":"{code}"' in loc.text


def test_serves_icons_and_modelpicker_js(client):
    icons = client.get("/icons.js")
    assert icons.status_code == 200
    assert "application/javascript" in icons.headers["content-type"]
    assert "EKTE_ICONS" in icons.text and "ekteIcon" in icons.text

    mp = client.get("/modelpicker.js")
    assert mp.status_code == 200
    assert "application/javascript" in mp.headers["content-type"]
    assert "EkteModelPicker" in mp.text


def test_api_kb_lists_providers_with_models(client):
    r = client.get("/api/kb")
    assert r.status_code == 200
    body = r.json()
    providers = body["providers"]
    assert isinstance(providers, list) and providers
    # Every provider entry exposes only public metadata (no api keys).
    for p in providers:
        assert {"provider", "display_name", "base_urls", "relay", "entry_id", "models"} <= set(p)
        for m in p["models"]:
            assert set(m) == {"id", "aliases", "kind"} and m["kind"] in ("chat", "embedding")
    # At least one provider has models; deepseek ships a deepseek-* id.
    assert any(p["models"] for p in providers)
    deepseek = next((p for p in providers if p["provider"] == "deepseek"), None)
    assert deepseek is not None
    assert any(m["id"].startswith("deepseek") for m in deepseek["models"])
    # usable base URLs only (the hints also hold paths, hosts and templates)
    assert deepseek["base_urls"][0] == "https://api.deepseek.com" and not deepseek["relay"]
    openai = next(p for p in providers if p["provider"] == "openai")
    assert openai["base_urls"] == ["https://api.openai.com/v1"]
    assert any(m["kind"] == "embedding" for m in openai["models"])


def test_api_kb_relays_saves_a_relay(client, tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    r = client.post("/api/kb/relays", json={"name": "My Relay", "base_url": "https://relay.example.com/v1/"})
    assert r.status_code == 201, r.text
    saved = r.json()
    assert saved["provider"] == "my-relay" and saved["display_name"] == "My Relay"
    assert saved["base_url"] == "https://relay.example.com/v1" and saved["entry_id"]
    mine = next(p for p in client.get("/api/kb").json()["providers"] if p["provider"] == "my-relay")
    assert mine["relay"] and mine["base_urls"] == ["https://relay.example.com/v1"] and mine["models"] == []
    assert mine["entry_id"] == saved["entry_id"]
    # taken names and known URLs are refused; nothing is overwritten
    assert client.post("/api/kb/relays", json={"name": "my relay", "base_url": "https://other.example/v1"}).status_code == 409
    assert client.post("/api/kb/relays", json={"name": "OpenAI", "base_url": "https://other.example/v1"}).status_code == 409
    dup = client.post("/api/kb/relays", json={"name": "Copy", "base_url": "https://api.openai.com/v1/chat/completions"})
    assert dup.status_code == 409 and "already in the knowledge base" in dup.json()["error"]
    for bad in ({"name": "", "base_url": "https://x.example"}, {"name": "x", "base_url": "relay.example.com"},
                {"name": "x" * 65, "base_url": "https://x.example"}):
        assert client.post("/api/kb/relays", json=bad).status_code == 400
    assert client.post("/api/kb/relays", json=["x"]).status_code == 400
    # a saved relay can be deleted like any other entry
    assert client.delete(f"/api/kb/entries/{saved['entry_id']}").status_code == 200
    assert all(p["provider"] != "my-relay" for p in client.get("/api/kb").json()["providers"])


def test_history_module_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    from ekte.web import history

    assert history.recent() == []
    sample = {
        "generated_at": "2026-06-07T00:00:00Z",
        "target": {"base_url": "https://relay.test/v1", "claimed_model": "deepseek-v4-pro", "model": "doubao-x"},
        "mode": "compare",
        "suite": "standard",
        "verdict": {"risk_level": "high", "overall_score": 21.0, "rating": "F"},
    }
    rid = history.save(sample)
    assert isinstance(rid, int) and rid > 0
    rows = history.recent()
    assert len(rows) == 1 and rows[0]["risk_level"] == "high" and rows[0]["score"] == 21.0
    full = history.get(rid)
    assert full["verdict"]["rating"] == "F" and full["target"]["model"] == "doubao-x"
    trend = history.trend("https://relay.test/v1", "deepseek-v4-pro")
    assert len(trend) == 1 and trend[0]["score"] == 21.0
    history.delete(rid)
    assert history.recent() == []


def test_history_endpoints(tmp_path, monkeypatch, client):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    assert client.get("/api/history").json() == []
    from ekte.web import history

    rid = history.save({
        "generated_at": "t", "target": {"base_url": "https://x/v1", "claimed_model": "m", "model": "m"},
        "mode": "check", "suite": "smoke", "verdict": {"risk_level": "clean", "overall_score": 95.0, "rating": "A"},
    })
    listed = client.get("/api/history").json()
    assert len(listed) == 1 and listed[0]["id"] == rid
    assert client.get(f"/api/history/{rid}").json()["verdict"]["overall_score"] == 95.0
    assert client.get("/api/history/999999").status_code == 404


def test_audit_stream_invalid_baseline_errors(client):
    # A compare request with a malformed baseline base_url is a clean error event.
    r = client.post(
        "/api/audit/stream",
        json={
            "base_url": "https://x.example/v1",
            "model": "gpt-4o",
            "baseline": {"base_url": "ftp://nope", "model": "gpt-4o"},
        },
    )
    assert '"type": "error"' in r.text


def test_serves_perf_js_and_pages_load_it(client):
    js = client.get("/perf.js")
    assert js.status_code == 200
    assert "application/javascript" in js.headers["content-type"]
    assert "EktePerf" in js.text
    for path in ("/", "/history"):
        assert '<script src="/perf.js"></script>' in _unversioned(client.get(path).text)


def test_audit_stream_batches_request_records(tmp_path, monkeypatch, client):
    import asyncio
    import json

    from ekte.models import AuditReport, RedactedTarget, Verdict

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))

    async def fake_run_audit(target, options, *, on_event=None, **_):
        on_event({"type": "start", "total": 1, "probe_requests": 0})
        for seq in range(3):  # a burst: batched into one event
            on_event({"type": "request_done", "record": {"seq": seq}})
        await asyncio.sleep(0.35)  # past the batch window: flushed on its own
        on_event({"type": "request_done", "record": {"seq": 3}})
        on_event({"type": "detector_done", "id": "x"})
        return AuditReport(
            tool_version="0", mode="check", suite="standard",
            target=RedactedTarget(name="t", kind="target", base_url=target.base_url, model="m"),
            verdict=Verdict(),
        )

    monkeypatch.setattr("ekte.web.server.run_audit", fake_run_audit)
    r = client.post("/api/audit/stream", json={"base_url": "https://x.example/v1", "model": "m"})
    events = [
        json.loads(line[5:]) for line in r.text.splitlines() if line.startswith("data:")
    ]
    types = [e["type"] for e in events]
    assert "request_done" not in types
    batches = [[rec["seq"] for rec in e["records"]] for e in events if e["type"] == "requests"]
    assert batches == [[0, 1, 2], [3]]
    # a pending batch is flushed before the next non-request event
    assert types.index("requests") < types.index("detector_done") < types.index("report")
    assert types[-1] == "done"


def test_history_trend_carries_performance_headline(tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    from ekte.web import history

    base = {"target": {"base_url": "https://x/v1", "claimed_model": "m", "model": "m"},
            "verdict": {"overall_score": 90.0}}
    history.save(base)
    history.save({**base, "performance": {"target": {
        "latency_ms": {"p50": 812.5}, "ttft_ms": {"p50": 240.0},
        "decode_tps_local": {"p50": None}, "decode_tps_reported": {"p50": 55.0}}}})
    old, new = history.trend("https://x/v1", "m")
    assert old["latency_p50_ms"] is None and old["score"] == 90.0
    assert new["latency_p50_ms"] == 812.5 and new["ttft_p50_ms"] == 240.0
    assert new["decode_tps_p50"] == 55.0


def test_history_list_carries_performance_headline_on_request(tmp_path, monkeypatch, client):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    from ekte.web import history

    history.save({"target": {"base_url": "https://x/v1", "claimed_model": "m", "model": "m"},
                  "verdict": {"overall_score": 90.0},
                  "performance": {"target": {"latency_ms": {"p50": 812.5}, "decode_tps_local": {"p50": 61.0}}}})
    plain = client.get("/api/history").json()[0]
    assert "latency_p50_ms" not in plain and "report_json" not in plain
    row = client.get("/api/history?perf=1").json()[0]
    assert row["latency_p50_ms"] == 812.5 and row["decode_tps_p50"] == 61.0
    assert row["ttft_p50_ms"] is None and row["score"] == 90.0
    assert "report_json" not in row

def test_api_key_fields_are_masked_and_paired_with_their_url(client):

    js = client.get("/secretfield.js")
    assert js.status_code == 200
    assert "application/javascript" in js.headers["content-type"]
    assert "EkteSecret" in js.text
    for path in ("/", "/console", "/tools", "/watches"):
        html = _unversioned(client.get(path).text)
        assert '<script src="/icons.js"></script>\n<script src="/secretfield.js"></script>' in html
        keys = re.findall(r'<input[^>]*\bid="\w+-key"[^>]*>', html)
        assert keys, path
        for tag in keys:
            # masked in the markup itself, so it holds even before any JS runs
            assert 'type="password"' in tag and "data-secret=" in tag, tag
            url_id = re.search(r'data-secret="([\w-]+)"', tag).group(1)
            assert re.search(rf'<input[^>]*\bid="{url_id}"', html), (path, url_id)
        # One current-password per form: a second would read as a
        # change-password form to the browser's password manager.
        for form in re.findall(r"<form\b.*?</form>", html, re.S):
            n = form.count('autocomplete="current-password"')
            assert n <= 1, path
            assert form.count('autocomplete="username"') == n, path


# ----- v2 UI, served side by side with the classic one (A/B) ------------- #

_V2_PAGES = {"/": "audit", "/history": "history", "/watches": "monitors"}


def test_v2_pages_share_the_design_system(client):
    for classic, page in _V2_PAGES.items():
        r = client.get("/v2" + classic if classic != "/" else "/v2/")
        assert r.status_code == 200 and "text/html" in r.headers["content-type"], classic
        html = _unversioned(r.text)
        assert '<script src="/locales.js"></script>\n<script src="/lang.js"></script>' in html
        assert '<link rel="stylesheet" href="/v2/static/ekte.css" />' in html
        assert f'<header class="znav" data-page="{page}"' in html
        assert '<script src="/v2/static/nav.js"></script>' in html
    for asset, kind in (("ekte.css", "text/css"), ("nav.js", "javascript"), ("report.js", "javascript"), ("report.css", "text/css")):
        r = client.get("/v2/static/" + asset)
        assert r.status_code == 200 and kind in r.headers["content-type"], asset
    assert client.get("/v2/static/missing.css").status_code == 404
    assert client.get("/v2", follow_redirects=False).headers["location"] == "/v2/"


def test_v2_monitors_page_manages_the_master_key(client):
    html = _unversioned(client.get("/v2/watches").text)
    assert '<script src="/v2/static/masterkey.js"></script>' in html
    assert 'id="mk-bar"' in html
    r = client.get("/v2/static/masterkey.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"]
    # one vault entry: a fixed username, "new-password" to save, "current-password" to fill
    js = r.text
    assert 'autocomplete="new-password"' in js and 'autocomplete="current-password"' in js
    assert "localStorage" not in js and "sessionStorage" not in js


def test_ui_switch_is_remembered_in_a_cookie(client):
    # default: classic, no redirect
    r = client.get("/history", follow_redirects=False)
    assert r.status_code == 200 and "ekte_ui" not in r.headers.get("set-cookie", "")
    # ?ui=v2 on a classic page: go to its v2 counterpart and remember the choice
    r = client.get("/history?ui=v2", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/v2/history"
    assert "ekte_ui=v2" in r.headers["set-cookie"]
    # with the cookie, classic pages redirect to v2
    client.cookies.set("ekte_ui", "v2")
    for classic in _V2_PAGES:
        r = client.get(classic, follow_redirects=False)
        assert r.status_code == 307, classic
        assert r.headers["location"] == ("/v2/" if classic == "/" else "/v2" + classic)
    # the classic Tools page has no v2 page of its own: the audit page's surface selector
    r = client.get("/tools", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/v2/?surface=embedding"
    # ?ui=v1 on a v2 page: back to classic, remembered as v1
    r = client.get("/v2/watches?ui=v1", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/watches"
    assert "ekte_ui=v1" in r.headers["set-cookie"]
    client.cookies.clear()
    assert client.get("/watches", follow_redirects=False).status_code == 200


def test_ui_choice_made_before_the_rename_still_applies(client):
    # zing_ui=v2 from an install that still ran as zing: v2 until ekte_ui is set
    client.cookies.set("zing_ui", "v2")
    r = client.get("/history", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/v2/history"
    # choosing v1 writes ekte_ui=v1, which wins over the legacy cookie (left as is)
    r = client.get("/v2/history?ui=v1", follow_redirects=False)
    assert "ekte_ui=v1" in r.headers["set-cookie"] and "zing_ui" not in r.headers["set-cookie"]
    client.cookies.set("ekte_ui", "v1")
    assert client.get("/history", follow_redirects=False).status_code == 200
    client.cookies.clear()


def test_language_cookie_made_before_the_rename_still_applies(client):
    client.cookies.set("zing_lang", "de")
    legacy = client.get("/locales.js").text
    client.cookies.clear()
    assert legacy == client.get("/locales.js?lang=de").text
    assert len(legacy) < len(client.get("/locales.js").text)  # one language, not all


def test_classic_pages_link_to_the_v2_ui(client):
    for classic in (*_V2_PAGES, "/tools"):
        assert 'class="try-v2" href="?ui=v2"' in client.get(classic).text, classic


def test_v2_tools_forwards_to_the_audit_page_surface(client):
    # /v2/tools was retired for the audit page's endpoint-type selector. The
    # old page picked its rerank tab by the fragment (#rerank), which never
    # reaches the server, so a tiny page forwards in the browser.
    r = client.get("/v2/tools?rerun=3", follow_redirects=False)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert r.headers["cache-control"] == "no-store"
    html = r.text
    assert '<html lang="en">' in html and "<title>" in html and "<h1>" in html
    assert 'location.hash === "#rerank" ? "rerank" : "embedding"' in html
    assert '"/v2/?surface="' in html and 'get("rerun")' in html and '"&rerun=" + encodeURIComponent(rerun)' in html
    assert "location.replace(to)" in html
    # without JavaScript: a meta refresh to the embedding surface and links to both
    assert '<meta http-equiv="refresh" content="0; url=/v2/?surface=embedding">' in html
    noscript = html.split("<noscript>", 1)[1].split("</noscript>", 1)[0]
    assert 'href="/v2/?surface=embedding"' in noscript and 'href="/v2/?surface=rerank"' in noscript
    assert 'data-page="tools"' not in html
    # ?ui=v1 still goes to the classic Tools page, which is unchanged
    r = client.get("/v2/tools?ui=v1", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/tools"
    assert 'class="try-v2" href="?ui=v2"' in client.get("/tools").text
    assert "/v2/tools" not in client.get("/v2/static/nav.js").text


def test_console_is_classic_only(client):
    # unknown /v2/ paths fall back to the v2 audit page, never a console page
    html = client.get("/v2/console").text
    assert 'data-page="audit"' in html and 'data-page="console"' not in html
    assert "/v2/console" not in client.get("/v2/static/nav.js").text
    client.cookies.set("ekte_ui", "v2")
    assert client.get("/console", follow_redirects=False).status_code == 200


def test_v2_audit_api_key_starts_empty_and_masked(client):
    # no shared env:EKTE_API_KEY default: each relay brings its own key, and
    # an empty field starts masked (only a reference value starts revealed)
    html = client.get("/v2/").text
    tag = re.search(r'<input[^>]*\bid="i-key"[^>]*>', html).group(0)
    assert 'type="password"' in tag and 'data-secret="i-url"' in tag
    assert "value=" not in tag


def test_v2_audit_sends_the_declared_provider(client):
    # the declared provider is derived by the relay configuration (a hidden
    # field) and still sent with the audit
    html = client.get("/v2/").text
    assert '<input type="hidden" id="i-prov">' in html
    assert 'declared_provider: $("#i-prov").value.trim()' in html
    assert 'claimed: "#i-claimed", provider: "#i-prov"' in html
    assert "/v2/static/relaycfg.js" in html and "/modelpicker.js" not in html


def test_v2_accessibility_report_page(client):
    # BITV 2.0 / EN 301 549 conformance report: a v2 page in the design system
    r = client.get("/v2/accessibility")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    html = _unversioned(r.text)
    assert '<script src="/locales.js"></script>\n<script src="/lang.js"></script>' in html
    assert '<link rel="stylesheet" href="/v2/static/ekte.css" />' in html
    assert '<header class="znav" data-page="a11y"' in html
    assert '<script src="/v2/static/nav.js"></script>' in html
    assert '<main id="main" tabindex="-1">' in html and "<footer>" not in html  # nav.js adds the shared one
    assert "/v2/static/bitv-report.json" in html
    assert "https://github.com/mn567250/ekte/issues" in html
    # v2 only: ?ui=v1 goes to the classic start page
    r = client.get("/v2/accessibility?ui=v1", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/"


def test_v2_analytics_page(client):
    # charts over the run history: a v2 page in the design system, linked from
    # every page's main navigation
    r = client.get("/v2/analytics")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    html = _unversioned(r.text)
    assert '<script src="/locales.js"></script>\n<script src="/lang.js"></script>' in html
    assert '<link rel="stylesheet" href="/v2/static/ekte.css" />' in html
    assert '<link rel="stylesheet" href="/v2/static/charts.css" />' in html
    assert '<header class="znav" data-page="analytics"' in html
    assert '<main id="main" tabindex="-1">' in html
    assert '<script src="/v2/static/nav.js"></script>\n<script src="/v2/static/notice.js"></script>\n<script src="/v2/static/charts.js"></script>' in html
    for api in ("/api/analytics/options", "/api/analytics/summary", "/api/analytics/series", "/api/analytics/leaderboard"):
        assert api in html
    # no outgoing requests: every script and stylesheet is local
    assert not re.search(r'(?:src|href)="(?:https?:)?//', html)
    js = client.get("/v2/static/nav.js").text
    assert '["analytics", "/v2/analytics", "bars", "分析", "Analytics"]' in js
    assert "bars:" in client.get("/icons.js").text
    # tabs and the filter panel History shares
    assert '<script src="/v2/static/filterpanel.js"></script>\n<script src="/v2/static/tabs.js"></script>' in html
    assert '<link rel="stylesheet" href="/v2/static/filterpanel.css" />' in html
    assert 'role="tablist"' in html and 'id="tab-integrity"' in html
    hist = _unversioned(client.get("/v2/history").text)
    assert '<script src="/v2/static/filterpanel.js"></script>' in hist
    assert '<link rel="stylesheet" href="/v2/static/filterpanel.css" />' in hist
    for asset, kind in (("charts.js", "javascript"), ("charts.css", "text/css"), ("filterpanel.js", "javascript"),
                        ("filterpanel.css", "text/css")):
        r = client.get("/v2/static/" + asset)
        assert r.status_code == 200 and kind in r.headers["content-type"], asset
    # v2 only: ?ui=v1 goes to the classic history page
    r = client.get("/v2/analytics?ui=v1", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/history"


def test_v2_accessibility_report_data_is_served(client):
    import json

    cat = client.get("/v2/static/bitv-catalogue.json")
    assert cat.status_code == 200
    steps = cat.json()["steps"]
    assert len(steps) == 50 and len({s["step"] for s in steps}) == 50
    rep = client.get("/v2/static/bitv-report.json")
    assert rep.status_code == 200 and "json" in rep.headers["content-type"]
    data = json.loads(rep.text)
    assert [s["step"] for s in data["steps"]] == [s["step"] for s in steps]
    assert data["totals"]["steps"] == 50 and data["totals"]["applicable"] == 44
    assert {s["status"] for s in data["steps"]} <= {"pass", "fail", "not tested", "manual review pending", "n/a"}


def test_v2_header_links_the_accessibility_report(client):
    # nav.js adds an icon-only link next to the language switch of every v2
    # page's header (same place everywhere), named by aria-label
    js = client.get("/v2/static/nav.js").text
    assert '<a class="a11y" href="/v2/accessibility"' in js
    assert 'data-en-aria-label="Accessibility"' in js and 'ico("a11y"' in js
    # the one shared page footer (all local / black box) comes from nav.js
    assert 'footer.className = "zdisc"' in js or 'f.className = "zdisc"' in js
    assert "data-trust" not in js.split("*/", 1)[1]
    assert "a11y:" in client.get("/icons.js").text
    for path in ("/v2/", "/v2/history", "/v2/watches", "/v2/kb", "/v2/analytics", "/v2/accessibility"):
        assert '<script src="/v2/static/nav.js"></script>' in _unversioned(client.get(path).text), path


async def test_health_stays_responsive_while_history_loads(tmp_path, monkeypatch):
    # A slow (blocking) history query must not stall the event loop: audits
    # timestamp their chunks on it, and every other request waits behind it.
    import asyncio
    import threading

    import httpx

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    started, release = threading.Event(), threading.Event()

    def slow_recent(limit: int = 50, perf: bool = False) -> list:
        started.set()
        release.wait(5)  # blocks its thread, as a large SQLite read does
        return []

    monkeypatch.setattr("ekte.web.history.recent", slow_recent)
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as ac:
        slow = asyncio.create_task(ac.get("/api/history", params={"limit": 500}))
        try:
            assert await asyncio.to_thread(started.wait, 5)
            health = await asyncio.wait_for(ac.get("/api/health"), 2)
            assert health.status_code == 200
            # Answered while the history request is still blocked in its thread.
            assert not slow.done()
        finally:
            release.set()
        r = await slow
    assert r.status_code == 200 and r.json() == []


# The audit loop timestamps streamed chunks with perf_counter, so the blocking
# store/knowledge-base calls around an audit must not stall it either.


def _blocking(result=None, exc: Exception | None = None):
    """A stand-in for a slow blocking call, plus its started/release events."""
    import threading

    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def call(*_a, **_k):
        started.set()
        release.wait(5)  # blocks its thread, as a slow SQLite write or YAML load does
        finished.set()
        if exc is not None:
            raise exc
        return result

    call.finished = finished  # type: ignore[attr-defined]
    return call, started, release


async def _health_answers(transport) -> None:
    import asyncio

    import httpx

    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as ac:
        health = await asyncio.wait_for(ac.get("/api/health"), 2)
    assert health.status_code == 200


def _fake_report(target):
    from ekte.models import AuditReport, RedactedTarget, Verdict

    return AuditReport(
        tool_version="0", mode="check", suite="standard",
        target=RedactedTarget(name="t", kind="target", base_url=target.base_url, model="m"),
        verdict=Verdict(),
    )


async def test_health_stays_responsive_while_a_monitor_run_saves(tmp_path, monkeypatch):
    import asyncio

    import httpx

    from ekte.web import history, server, watches

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))

    async def fake_run_audit(target, options, **_):
        return _fake_report(target)

    monkeypatch.setattr(server, "run_audit", fake_run_audit)
    wid = watches.create({"base_url": "https://relay.test/v1", "api_key": "sk-x", "model": "m"})
    real_save, real_mark = history.save, watches.mark_run
    slow_save, save_started, save_release = _blocking()
    slow_mark, mark_started, mark_release = _blocking()

    def save(*a, **k):
        slow_save()
        return real_save(*a, **k)

    def mark(*a, **k):
        slow_mark()
        return real_mark(*a, **k)

    monkeypatch.setattr(history, "save", save)
    monkeypatch.setattr(watches, "mark_run", mark)
    transport = httpx.ASGITransport(app=create_app())
    run = asyncio.create_task(server._run_one_watch(watches.get(wid)))
    try:
        assert await asyncio.to_thread(save_started.wait, 5)
        await _health_answers(transport)
        assert not run.done()
        save_release.set()
        assert await asyncio.to_thread(mark_started.wait, 5)
        await _health_answers(transport)
        # Still listed as running until its run is recorded, so the scheduler
        # cannot start it again in between.
        assert wid in server._running_watches and not run.done()
    finally:
        save_release.set()
        mark_release.set()
    await asyncio.wait_for(run, 5)
    assert wid not in server._running_watches
    row = watches.get(wid)
    assert row is not None and row["last_report_id"] is not None


async def test_a_monitor_save_is_never_abandoned(tmp_path, monkeypatch):
    import asyncio

    from ekte.web import history, server, watches

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))

    async def fake_run_audit(target, options, **_):
        return _fake_report(target)

    monkeypatch.setattr(server, "run_audit", fake_run_audit)
    wid = watches.create({"base_url": "https://relay.test/v1", "api_key": "sk-x", "model": "m"})
    real_save = history.save
    slow, started, release = _blocking()

    def save(*a, **k):
        slow()
        return real_save(*a, **k)

    monkeypatch.setattr(history, "save", save)

    # Cancel is refused while the finished audit is being saved.
    run = asyncio.create_task(server._run_one_watch(watches.get(wid)))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        assert not server._cancel_watch(wid)
    finally:
        release.set()
    await asyncio.wait_for(run, 5)
    row = watches.get(wid)
    assert row is not None and row["last_report_id"] is not None

    # A server shutdown waits for the save, records the run, then propagates.
    started.clear()
    release.clear()
    run = asyncio.create_task(server._run_one_watch(watches.get(wid)))
    try:
        assert await asyncio.to_thread(started.wait, 5)
        job = server._running_watches[wid]["job"]
        run.cancel()
        await asyncio.sleep(0.05)
        assert not run.done()  # waits for the save instead of abandoning it
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(run, 5)
    assert len(history.recent(10)) == 2
    assert job.report_id is not None
    assert wid not in server._running_watches
    row = watches.get(wid)
    assert row is not None and row["last_report_id"] == job.report_id


async def test_scheduler_tick_does_not_block_the_loop(tmp_path, monkeypatch):
    import asyncio

    import httpx

    from ekte.web import server

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    slow, started, release = _blocking(result=[])
    monkeypatch.setattr("ekte.web.watches.due", slow)
    transport = httpx.ASGITransport(app=create_app())
    loop_task = asyncio.create_task(server._scheduler_loop())
    try:
        assert await asyncio.to_thread(started.wait, 5)
        await _health_answers(transport)
        assert not slow.finished.is_set()  # answered while the tick's query still blocks
    finally:
        release.set()
        loop_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await loop_task


async def test_health_stays_responsive_while_a_job_saves(tmp_path, monkeypatch):
    import asyncio

    import httpx

    from ekte.web import history, jobs

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))

    async def fake_run_audit(target, options, **_):
        return _fake_report(target)

    monkeypatch.setattr("ekte.web.server.run_audit", fake_run_audit)
    real_save = history.save
    slow, started, release = _blocking()

    def save(*a, **k):
        slow()
        return real_save(*a, **k)

    monkeypatch.setattr(history, "save", save)
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as ac:
        created = await ac.post("/api/jobs", json={"base_url": "https://x.example/v1", "model": "m"})
        job = jobs.manager.get(created.json()["id"])
        assert job is not None
        try:
            assert await asyncio.to_thread(started.wait, 5)
            health = await asyncio.wait_for(ac.get("/api/health"), 2)
            assert health.status_code == 200
            assert job.status == "running"  # still saving
        finally:
            release.set()
        assert job.task is not None
        await asyncio.wait_for(job.task, 5)
    assert job.status == "done" and job.report_id is not None


async def test_a_cancel_during_a_job_save_comes_too_late(tmp_path, monkeypatch):
    import asyncio

    from ekte.web import history, jobs

    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    real_save = history.save
    slow, started, release = _blocking()

    def save(*a, **k):
        slow()
        return real_save(*a, **k)

    monkeypatch.setattr(history, "save", save)
    mgr = jobs.JobManager(jobs.RelayGate(limit=4))

    async def run(emit):
        return {"verdict": {}, "target": {"base_url": "https://r.example/v1"}}

    job = mgr.submit({}, ["https://r.example"], run)
    try:
        assert await asyncio.to_thread(started.wait, 5)
        assert not mgr.cancel(job.id)
        assert job.status == "running"
    finally:
        release.set()
    assert job.task is not None
    await asyncio.wait_for(job.task, 5)
    assert job.status == "done" and job.report_id is not None
    assert [e["type"] for e in job.events][-2:] == ["report", "done"]


async def test_settle_delays_a_cancel_until_the_work_is_done():
    import asyncio

    from ekte.web import jobs

    gate, log = asyncio.Event(), []

    async def work(fail: bool) -> str:
        await gate.wait()
        log.append("done")
        if fail:
            raise RuntimeError("boom")
        return "ok"

    gate.set()
    assert await jobs.settle(work(False)) == "ok"
    for fail in (False, True):
        gate.clear()
        log.clear()
        task = asyncio.create_task(jobs.settle(work(fail)))
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()  # a second cancel is delayed too
        await asyncio.sleep(0.01)
        assert not task.done()
        gate.set()
        with pytest.raises(asyncio.CancelledError):  # wins over the error
            await task
        assert log == ["done"]
    with pytest.raises(RuntimeError, match="boom"):
        await jobs.settle(work(True))


async def test_job_save_errors_stay_best_effort(monkeypatch):
    from ekte.web import history, jobs

    def broken(*_a, **_k):
        raise RuntimeError("disk full")

    monkeypatch.setattr(history, "save", broken)
    mgr = jobs.JobManager(jobs.RelayGate(limit=4))

    async def run(emit):
        return {"verdict": {}}

    job = mgr.submit({}, ["https://r.example"], run)
    assert job.task is not None
    await job.task
    assert job.status == "done" and job.report_id is None


async def test_audit_knowledge_base_load_does_not_block_the_loop(monkeypatch):
    import asyncio

    from ekte.config import AuditOptions, TargetConfig
    from ekte.runner import run_audit

    slow, started, release = _blocking(exc=RuntimeError("kb stop"))
    monkeypatch.setattr("ekte.runner.load_knowledge_base", slow)
    audit = asyncio.create_task(
        run_audit(TargetConfig(base_url="https://x.example/v1", model="m"), AuditOptions())
    )
    try:
        assert await asyncio.to_thread(started.wait, 5)
        ticks = 0
        for _ in range(5):  # the loop keeps turning while the KB loads
            await asyncio.sleep(0.01)
            ticks += 1
        assert ticks == 5 and not audit.done()
    finally:
        release.set()
    with pytest.raises(RuntimeError, match="kb stop"):
        await asyncio.wait_for(audit, 5)
