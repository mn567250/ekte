"""protocol.error_schema: the no-HTTP-response branch carries its error type.

The web UI localizes this branch's summary with a template keyed on the
``error_type`` evidence (ekte/web/static/i18n.js ALT), so it must be set only
when the invalid request got no HTTP response at all.
"""

from __future__ import annotations

from types import SimpleNamespace

from ekte.detectors.protocol import ProtocolDetector
from ekte.models import CompletionOutcome, DetectorResult, Dimension, Status


async def _finding(outcome: CompletionOutcome):
    async def complete(_spec):
        return outcome

    ctx = SimpleNamespace(client=SimpleNamespace(complete=complete))
    result = DetectorResult(id="protocol", name="p", dimension=Dimension.PROTOCOL)
    await ProtocolDetector()._check_error_schema(ctx, result)  # type: ignore[arg-type]
    (finding,) = result.findings
    return finding


async def test_no_http_response_names_the_error_type():
    f = await _finding(CompletionOutcome(ok=False, error_type="ProxyError", error_message="boom"))
    assert f.status == Status.WARN
    assert f.evidence["error_type"] == "ProxyError"
    assert f.summary == (
        "Invalid request got no HTTP response (ProxyError); "
        "could not confirm OpenAI-style client-error handling."
    )
    assert "HTTP None" not in f.summary


async def test_http_status_branches_leave_error_type_unset():
    for code in (404, 302):
        f = await _finding(CompletionOutcome(ok=False, status_code=code, error_type="http_error"))
        assert f.evidence["error_type"] is None, code
        assert f"HTTP {code}" in f.summary
