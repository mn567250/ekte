"""Unit tests for ekte.notify — webhook alert formatters and delivery.

No network: :func:`send` is exercised against an ``httpx.MockTransport`` injected
into a patched ``httpx.AsyncClient`` so we can assert the request shape and the
boolean result without touching a real webhook.
"""

from __future__ import annotations

import json

import httpx
import pytest

from ekte import notify

# A representative high-risk report dict (AuditReport.model_dump() shape).
REPORT = {
    "verdict": {
        "overall_score": 42.0,
        "rating": "D",
        "risk_level": "high",
        "headline": "Likely downgrade",
        "key_findings": ["发现一", "发现二", "发现三"],
    },
    "target": {
        "base_url": "https://relay.example.com/v1",
        "claimed_model": "gpt-4o",
        "model": "gpt-4o-mini",
    },
}
PREV_LOW = {"verdict": {"risk_level": "low"}}
PREV_HIGH = {"verdict": {"risk_level": "high"}}


# --------------------------------------------------------------------------- #
# Text digest
# --------------------------------------------------------------------------- #
def test_build_text_contains_core_fields():
    text = notify.build_text(REPORT)
    assert "https://relay.example.com/v1" in text   # base_url
    assert "gpt-4o" in text                          # claimed model
    assert "42.0/100" in text                        # score
    assert "D" in text                               # rating
    assert "发现一" in text                          # a key finding
    assert "Likely downgrade" in text                # headline


def test_build_text_caps_key_findings():
    rep = {
        "verdict": {"risk_level": "high", "key_findings": [f"f{i}" for i in range(20)]},
        "target": {"base_url": "https://x/v1", "model": "m"},
    }
    text = notify.build_text(rep)
    assert "f0" in text and "f4" in text
    assert "f5" not in text  # only the first 5 are shown


def test_build_text_delta_when_previous_given():
    worse = notify.build_text(REPORT, PREV_LOW)
    assert "Since last run" in worse and "worse" in worse
    none = notify.build_text(REPORT, None)
    assert "Since last run" not in none


def test_build_text_defaults_to_english():
    text = notify.build_text(REPORT, PREV_LOW)
    assert text.startswith("🛰️ ekte relay audit alert")
    assert "Risk: 🔴 High risk (HIGH)" in text and "Score: 42.0/100 (grade D)" in text
    # the only Chinese left is the fixture's own sample finding titles
    for sample in REPORT["verdict"]["key_findings"]:
        text = text.replace(sample, "")
    assert not any("\u4e00" <= ch <= "\u9fff" for ch in text)


def test_build_text_chinese_keeps_original_wording():
    text = notify.build_text(REPORT, PREV_LOW, lang="zh")
    assert text.startswith("🛰️ ekte 中继体检告警")
    assert "风险：🔴 高风险（HIGH）" in text and "评分：42.0/100（评级 D）" in text
    assert "较上次：🔵 低风险（LOW） → 🔴 高风险（HIGH）（恶化 ⬆️）" in text


def test_unknown_language_falls_back_to_english():
    assert notify.build_text(REPORT, lang="xx") == notify.build_text(REPORT)


# A real report (from `ekte check` against a dishonest local relay).
def _real_report():
    from pathlib import Path

    return json.loads((Path(__file__).parent / "fixtures" / "web_report.json").read_text("utf-8"))


@pytest.mark.parametrize("lang", ["en", "zh", "fr", "es", "pt", "it", "de", "nb"])
def test_real_alert_is_fully_in_its_language(lang):
    from ekte import i18n

    report = _real_report()
    text = notify.build_text(report, PREV_LOW, lang=lang)
    has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in text)
    assert has_cjk == (lang == "zh")
    en_headline = report["verdict"]["headline"]
    en_findings = report["verdict"]["key_findings"][:5]
    if lang == "en":
        assert en_headline in text and all(f in text for f in en_findings)
    else:
        # headline and every key finding translated, not copied in English
        assert en_headline not in text
        assert not any(f"• {f}" in text for f in en_findings)
        assert i18n.ui(lang, "Key findings:") in text


def test_generic_payload_keys_stay_english_values_follow_language():
    report = _real_report()
    en = notify.format_generic(report, PREV_LOW)
    de = notify.format_generic(report, PREV_LOW, lang="de")
    assert set(en) == set(de)
    assert en["language"] == "en" and de["language"] == "de"
    for key in ("risk_level", "score", "rating", "base_url", "claimed_model", "previous_risk_level", "regressed"):
        assert en[key] == de[key]
    assert de["headline"] != en["headline"] and de["key_findings"] != en["key_findings"]


# --------------------------------------------------------------------------- #
# Per-platform payload shapes
# --------------------------------------------------------------------------- #
def test_format_slack_shape():
    payload = notify.format_slack(REPORT)
    assert set(payload) == {"text"}
    assert isinstance(payload["text"], str) and payload["text"]


def test_format_feishu_shape():
    payload = notify.format_feishu(REPORT)
    assert payload["msg_type"] == "text"
    assert isinstance(payload["content"]["text"], str)
    assert "relay.example.com" in payload["content"]["text"]


def test_format_dingtalk_shape():
    payload = notify.format_dingtalk(REPORT)
    assert payload["msgtype"] == "text"
    assert isinstance(payload["text"]["content"], str)
    assert "relay.example.com" in payload["text"]["content"]


def test_format_generic_shape():
    payload = notify.format_generic(REPORT, PREV_LOW)
    assert payload["tool"] == "ekte"
    assert payload["event"] == "audit_alert"
    assert payload["risk_level"] == "high"
    assert payload["score"] == 42.0
    assert payload["rating"] == "D"
    assert payload["base_url"] == "https://relay.example.com/v1"
    assert payload["claimed_model"] == "gpt-4o"
    assert payload["key_findings"] == ["发现一", "发现二", "发现三"]
    assert payload["previous_risk_level"] == "low"
    assert payload["regressed"] is True
    assert isinstance(payload["text"], str)


def test_format_generic_no_previous():
    payload = notify.format_generic(REPORT)
    assert payload["previous_risk_level"] is None
    assert payload["regressed"] is False


# --------------------------------------------------------------------------- #
# URL auto-detection
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://hooks.slack.com/services/T/B/X", "slack"),
        ("https://open.feishu.cn/open-apis/bot/v2/hook/abc", "feishu"),
        ("https://open.larksuite.com/open-apis/bot/v2/hook/abc", "feishu"),
        ("https://oapi.dingtalk.com/robot/send?access_token=x", "dingtalk"),
        ("https://example.com/my/webhook", "generic"),
        ("not a url", "generic"),
    ],
)
def test_detect_kind(url, expected):
    assert notify.detect_kind(url) == expected


def test_build_payload_auto_uses_url_host():
    slack = notify.build_payload(REPORT, kind="auto", webhook_url="https://hooks.slack.com/x")
    assert set(slack) == {"text"}
    feishu = notify.build_payload(REPORT, kind="auto", webhook_url="https://open.feishu.cn/x")
    assert feishu["msg_type"] == "text"


def test_build_payload_explicit_kind_overrides_url():
    # Explicit kind wins even when the host would auto-detect to something else.
    payload = notify.build_payload(REPORT, kind="dingtalk", webhook_url="https://hooks.slack.com/x")
    assert payload["msgtype"] == "text"


# --------------------------------------------------------------------------- #
# regressed() ordering
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "current,previous,expected",
    [
        ("high", "low", True),
        ("medium", "low", True),
        ("low", "clean", True),
        ("high", "high", False),     # equal is not a regression
        ("low", "high", False),      # improvement
        ("clean", "low", False),
        ("high", None, False),       # no previous
    ],
)
def test_regressed_ordering(current, previous, expected):
    cur = {"verdict": {"risk_level": current}}
    prev = None if previous is None else {"verdict": {"risk_level": previous}}
    assert notify.regressed(cur, prev) is expected


# --------------------------------------------------------------------------- #
# send() against a MockTransport
# --------------------------------------------------------------------------- #
class _Recorder:
    """Captures the single POST send() makes, so we can assert on it."""

    def __init__(self, status: int = 200):
        self.status = status
        self.requests: list[httpx.Request] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, json={"ok": True})

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)


def _patch_async_client(monkeypatch, transport: httpx.MockTransport) -> None:
    """Force httpx.AsyncClient(...) to use our MockTransport, ignoring kwargs."""
    real = httpx.AsyncClient

    def factory(*args, **kwargs):
        kwargs.pop("transport", None)
        return real(transport=transport)

    monkeypatch.setattr(notify.httpx, "AsyncClient", factory)


async def test_send_posts_and_returns_true(monkeypatch):
    rec = _Recorder(status=200)
    _patch_async_client(monkeypatch, rec.transport)

    ok = await notify.send(
        "https://hooks.slack.com/services/T/B/X", REPORT, previous=PREV_LOW
    )
    assert ok is True
    assert len(rec.requests) == 1
    req = rec.requests[0]
    assert req.method == "POST"
    body = json.loads(req.content.decode())
    # Auto-detected slack shape, with the regression delta in the text.
    assert set(body) == {"text"}
    assert "Since last run" in body["text"]


async def test_send_uses_the_requested_language(monkeypatch):
    rec = _Recorder(status=200)
    _patch_async_client(monkeypatch, rec.transport)
    ok = await notify.send("https://hooks.slack.com/services/T/B/X", REPORT, previous=PREV_LOW, lang="zh")
    assert ok is True
    assert "较上次" in json.loads(rec.requests[0].content.decode())["text"]


async def test_send_explicit_kind_feishu(monkeypatch):
    rec = _Recorder(status=200)
    _patch_async_client(monkeypatch, rec.transport)

    ok = await notify.send("https://example.com/hook", REPORT, kind="feishu")
    assert ok is True
    body = json.loads(rec.requests[0].content.decode())
    assert body["msg_type"] == "text"


async def test_send_non_2xx_returns_false(monkeypatch):
    rec = _Recorder(status=500)
    _patch_async_client(monkeypatch, rec.transport)

    ok = await notify.send("https://example.com/hook", REPORT)
    assert ok is False
    assert len(rec.requests) == 1  # it still attempted the POST


async def test_send_network_error_returns_false(monkeypatch):
    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    _patch_async_client(monkeypatch, httpx.MockTransport(boom))
    ok = await notify.send("https://example.com/hook", REPORT)
    assert ok is False  # never raises


async def test_send_empty_url_returns_false():
    assert await notify.send("", REPORT) is False
