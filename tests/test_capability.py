"""Capability probes the relay rejects with a 4xx (#248).

A relay that answers the tools, JSON-mode or strict-schema probe with HTTP 400
for a model whose profile claims the feature has refused a claimed capability
(``rejected``, 0 points). Server errors, timeouts, credentials, rate limits and
failures before the relay answered stay ``failed`` (not counted), and so does a
relay that rejects a plain request too. An unclaimed feature or a baseline that
rejects the probe as well is not counted.
"""

from __future__ import annotations

import json
import shutil

import pytest

from ekte.config import AuditOptions
from ekte.context import AuditContext
from ekte.detectors.capability import SCALE, CapabilityDetector, is_feature_rejection
from ekte.detectors.scale import Scale
from ekte.models import CompletionOutcome, DetectorResult, RequestSpec, Status, TargetConfig

_FEATURES = ("capability.tools", "capability.json_mode", "capability.json_schema")


def _rejection(status: int = 400, message: str = "tools are not supported", **kw) -> CompletionOutcome:
    kw.setdefault("error_type", "http_error")
    kw.setdefault("error_class", "relay")
    return CompletionOutcome(ok=False, status_code=status, error_message=message, **kw)


def _answer(spec: RequestSpec) -> CompletionOutcome:
    # A plain answer that runs to the cap: max_output passes.
    return CompletionOutcome(ok=True, status_code=200, content="line\n" * 50, finish_reason="length",
                             usage={"completion_tokens": spec.max_tokens})


class _Stub:
    """A client that rejects every request carrying a feature parameter."""

    def __init__(self, reject: CompletionOutcome | None = None, plain: CompletionOutcome | None = None):
        self.reject = reject if reject is not None else _rejection()
        self.plain = plain
        self.specs: list[RequestSpec] = []

    async def complete(self, spec: RequestSpec) -> CompletionOutcome:
        self.specs.append(spec)
        if spec.tools or spec.response_format:
            return self.reject.model_copy()
        return (self.plain or _answer(spec)).model_copy()


def _ctx(knowledge_base, client, *, model: str | None = "gpt-4o", baseline=None, baseline_api="openai"):
    target = TargetConfig(name="t", kind="target", base_url="https://relay.example/v1", api_key="k",
                          model=model or "no-such-model-xyz", api="openai")
    profile = knowledge_base.resolve(model) if model else None
    ctx = AuditContext(target=target, client=client, options=AuditOptions(suite="standard"),
                       kb=knowledge_base, profile=profile)
    if baseline is not None:
        ctx.baseline = TargetConfig(name="b", kind="baseline", base_url="https://api.example/v1",
                                    api_key="k", model=model or "x", api=baseline_api)
        ctx.baseline_client = baseline
    return ctx


def _check(result: DetectorResult) -> None:
    for f in result.findings:
        o = SCALE.get(f.scale_check, f.outcome or "")
        assert (f.status, f.severity, f.score) == (o.status, o.severity, o.score), f.id
    assert result.score == Scale.mean(result.findings)


def _outcomes(result: DetectorResult) -> dict[str, str | None]:
    return {f.scale_check: f.outcome for f in result.findings if f.scale_check in _FEATURES}


async def test_rejected_claimed_probes_fail_the_detector(knowledge_base):
    # The issue's reproduction: gpt-4o claims tools, JSON mode and strict
    # schemas; the relay answers all three with HTTP 400.
    client = _Stub()
    result = await CapabilityDetector().run(_ctx(knowledge_base, client))
    _check(result)
    assert _outcomes(result) == dict.fromkeys(_FEATURES, "rejected")
    assert result.status == Status.FAIL
    assert result.score is not None and result.score <= 25
    tools = next(f for f in result.findings if f.scale_check == "capability.tools")
    assert "HTTP 400" in tools.summary and "tools are not supported" in tools.summary
    assert tools.evidence["relay_error"] == "tools are not supported"
    assert tools.recommendation
    # One plain control request told "rejects the parameter" from "rejects
    # everything"; later rejections reuse what it showed.
    plain = [s for s in client.specs if not (s.tools or s.response_format)]
    assert len(plain) == 2  # the control and the max-output probe
    assert tools.evidence["plain_status_code"] == 200


async def test_no_control_request_once_a_probe_came_back(knowledge_base):
    # Tools work; JSON mode is rejected. The relay already answered a request,
    # so no extra plain request is needed.
    class _JsonRejecting(_Stub):
        async def complete(self, spec):
            self.specs.append(spec)
            if spec.response_format:
                return _rejection(message="response_format is not supported")
            if spec.tools:
                return CompletionOutcome(ok=True, status_code=200, tool_calls=[
                    {"function": {"name": "get_weather", "arguments": "{}"}}])
            return _answer(spec)

    client = _JsonRejecting()
    result = await CapabilityDetector().run(_ctx(knowledge_base, client))
    _check(result)
    assert _outcomes(result) == {"capability.tools": "delivered", "capability.json_mode": "rejected",
                                 "capability.json_schema": "rejected"}
    assert len(client.specs) == 4


async def test_relay_rejecting_everything_stays_inconclusive(knowledge_base):
    client = _Stub(plain=_rejection(message="bad request"))
    result = await CapabilityDetector().run(_ctx(knowledge_base, client))
    _check(result)
    assert _outcomes(result) == dict.fromkeys(_FEATURES, "failed")
    assert result.score is None


@pytest.mark.parametrize(
    "reject",
    [
        CompletionOutcome(ok=False, status_code=500, error_message="boom", error_type="http_error",
                          error_class="relay"),
        CompletionOutcome(ok=False, error_type="ConnectError", error_message="refused",
                          error_class="network"),
        CompletionOutcome(ok=False, error_type="ReadTimeout", error_message="timed out",
                          error_class="relay"),
        _rejection(401, "invalid key"),
        _rejection(403, "forbidden"),
        _rejection(408, "request timeout"),
        _rejection(429, "slow down"),
        _rejection(400, "pool exhausted", error_class="local"),
    ],
    ids=["500", "network", "timeout", "401", "403", "408", "429", "local"],
)
async def test_other_failures_stay_inconclusive_and_uncounted(knowledge_base, reject):
    client = _Stub(reject=reject)
    result = await CapabilityDetector().run(_ctx(knowledge_base, client))
    _check(result)
    assert _outcomes(result) == dict.fromkeys(_FEATURES, "failed")
    assert result.score == 100.0  # max output alone, as before
    assert len(client.specs) == 4  # no control request


async def test_unprofiled_model_rejection_is_not_counted(knowledge_base):
    client = _Stub()
    result = await CapabilityDetector().run(_ctx(knowledge_base, client, model=None))
    _check(result)
    # no profile: the strict-schema probe is skipped
    assert _outcomes(result) == {"capability.tools": "rejected_unclaimed",
                                 "capability.json_mode": "rejected_unclaimed"}
    assert all(f.status == Status.INFO and f.score is None for f in result.findings
               if f.scale_check in _FEATURES)
    assert result.status == Status.PASS and result.score == 100.0


async def test_unclaimed_strict_schema_rejection_is_not_counted(knowledge_base):
    ctx = _ctx(knowledge_base, _Stub())
    assert ctx.profile is not None
    model = ctx.profile.model.model_copy(update={"supports_json_schema": False})
    ctx.profile = ctx.profile.model_copy(update={"model": model})
    result = await CapabilityDetector().run(ctx)
    _check(result)
    assert _outcomes(result)["capability.json_schema"] == "rejected_unclaimed"


async def test_baseline_rejecting_too_is_a_model_limit(knowledge_base):
    baseline = _Stub(reject=_rejection(message="unsupported"))
    client = _Stub()
    result = await CapabilityDetector().run(_ctx(knowledge_base, client, baseline=baseline))
    _check(result)
    assert _outcomes(result) == dict.fromkeys(_FEATURES, "model_limit")
    assert all(f.status == Status.INFO for f in result.findings if f.scale_check in _FEATURES)
    assert result.score == 100.0
    assert len(baseline.specs) == 3
    # a model limit needs no control request
    assert len(client.specs) == 4


async def test_baseline_accepting_keeps_the_rejection(knowledge_base):
    class _Accepting:
        def __init__(self):
            self.specs = []

        async def complete(self, spec):
            self.specs.append(spec)
            return _answer(spec)

    baseline = _Accepting()
    result = await CapabilityDetector().run(_ctx(knowledge_base, _Stub(), baseline=baseline))
    _check(result)
    assert _outcomes(result) == dict.fromkeys(_FEATURES, "rejected")
    tools = next(f for f in result.findings if f.scale_check == "capability.tools")
    assert tools.evidence["baseline_status_code"] == 200


async def test_baseline_on_another_protocol_is_not_asked(knowledge_base):
    baseline = _Stub()
    result = await CapabilityDetector().run(
        _ctx(knowledge_base, _Stub(), baseline=baseline, baseline_api="anthropic"))
    assert _outcomes(result) == dict.fromkeys(_FEATURES, "rejected")
    assert baseline.specs == []


@pytest.mark.parametrize(
    ("out", "expected"),
    [
        (_rejection(400), True),
        (_rejection(404), True),
        (_rejection(422), True),
        (_rejection(401), False),
        (_rejection(403), False),
        (_rejection(408), False),
        (_rejection(429), False),
        (_rejection(400, error_class="network"), False),
        (CompletionOutcome(ok=False, status_code=503), False),
        (CompletionOutcome(ok=False, error_type="ReadTimeout"), False),
        (CompletionOutcome(ok=True, status_code=200), False),
    ],
)
def test_is_feature_rejection(out, expected):
    assert is_feature_rejection(out) is expected


_LOCALIZE_JS = r"""
const path = require("path");
const dir = process.argv[1], cases = JSON.parse(process.argv[2]);
const out = {};
for (const lang of ["en", "de", "zh"]) {
  for (const m of ["locales.js", "lang.js", "i18n.js"]) delete require.cache[require.resolve(path.join(dir, m))];
  global.window = {};
  global.document = { documentElement: { style: {}, lang: "" }, readyState: "complete", querySelectorAll: () => [], addEventListener() {} };
  global.localStorage = { getItem: () => lang, setItem() {} };
  for (const m of ["locales.js", "lang.js", "i18n.js"]) require(path.join(dir, m));
  out[lang] = cases.map(c => window.EKTE_I18N.localizeFinding(c.id, c.summary, c.evidence, c.title, c.status));
}
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
async def test_rejected_findings_are_localized_with_the_relay_error(knowledge_base, tmp_path):
    from tests._helpers import run_subprocess
    from tests.test_web_locales import _ui_js

    findings = []
    for baseline in (None, _Stub(reject=_rejection(message="unsupported"))):
        result = await CapabilityDetector().run(_ctx(knowledge_base, _Stub(), baseline=baseline))
        findings.append(next(f for f in result.findings if f.scale_check == "capability.tools"))
    result = await CapabilityDetector().run(_ctx(knowledge_base, _Stub(), model=None))
    findings.append(next(f for f in result.findings if f.scale_check == "capability.tools"))
    assert [f.outcome for f in findings] == ["rejected", "model_limit", "rejected_unclaimed"]
    cases = [{"id": f.id, "summary": f.summary, "evidence": f.evidence, "title": f.title,
              "status": f.status.value} for f in findings]
    out = json.loads(run_subprocess(
        ["node", "-e", _LOCALIZE_JS, str(_ui_js(tmp_path)), json.dumps(cases)],
        capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout)
    assert [x["summary"] for x in out["en"]] == [f.summary for f in findings]
    rejected, limit, unclaimed = out["de"]
    assert rejected["title"] == "Angegebene Tool-Aufrufe vom Relay abgelehnt"
    assert rejected["summary"] == (
        "Die Fähigkeit wird angegeben, aber das Relay hat die Sonde mit HTTP 400 abgelehnt: "
        "tools are not supported"
    )
    assert "(HTTP 400)" in limit["summary"] and "Grenze" in limit["summary"]
    assert "nicht angegeben" in unclaimed["summary"] and "tools are not supported" in unclaimed["summary"]
    assert all("tools are not supported" in x["summary"] and "400" in x["summary"] for x in out["zh"])
