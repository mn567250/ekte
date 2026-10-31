"""The LLM judge's handling of good, malformed and failed responses (issue #32).

No network: the judge talks to a real ``OpenAICompatibleClient`` whose transport
is an in-process ``httpx.MockTransport``.
"""

from __future__ import annotations

import json

import httpx
import pytest

from ekte.clients import OpenAICompatibleClient
from ekte.judge.judge import Judge, JudgeUnavailable, _parse_json
from ekte.models import TargetConfig


def _target() -> TargetConfig:
    return TargetConfig(
        name="judge", kind="judge", base_url="https://judge.test/v1", api_key="sk-judge", model="judge-1"
    )


def _chat(content: str | None, status: int = 200) -> httpx.Response:
    if status >= 400:
        return httpx.Response(status, json={"error": {"message": "judge exploded"}})
    return httpx.Response(
        200,
        json={
            "model": "judge-1",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 3, "total_tokens": 6},
        },
    )


async def _ask(handler, **kw) -> dict:
    async with OpenAICompatibleClient(_target(), transport=httpx.MockTransport(handler)) as client:
        return await Judge(client, "judge-1").evaluate_json("sys", "user", **kw)


async def test_plain_json_reply_is_returned():
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return _chat('{"verdict": "same", "confidence": 0.9}')

    out = await _ask(handler, max_tokens=123)
    assert out == {"verdict": "same", "confidence": 0.9}
    assert seen["temperature"] == 0.0
    assert seen["response_format"] == {"type": "json_object"}
    assert seen["messages"][0] == {"role": "system", "content": "sys"}
    assert seen["messages"][1] == {"role": "user", "content": "user"}


@pytest.mark.parametrize(
    "reply",
    [
        'Sure!\n```json\n{"a": 1}\n```\nHope this helps',
        '```\n{"a": 1}\n```',
        'The answer is {"a": 1} as requested.',
        '  {"a": 1}  ',
    ],
)
async def test_json_wrapped_in_prose_or_fences_is_extracted(reply):
    assert await _ask(lambda r: _chat(reply)) == {"a": 1}


@pytest.mark.parametrize("reply", ["no json here", "{not: valid}", "[1, 2, 3]", '```json\n{"a": }\n```', '"just a string"'])
async def test_malformed_reply_reports_a_parse_error_with_the_raw_text(reply):
    out = await _ask(lambda r: _chat(reply))
    assert out["_error"] == "could not parse judge JSON"
    assert out["_raw"] == reply.strip()[:500]


async def test_raw_text_in_parse_error_is_capped():
    out = await _ask(lambda r: _chat("x" * 2000))
    assert len(out["_raw"]) == 500


@pytest.mark.parametrize("status", [400, 401, 429, 500, 503])
async def test_failed_call_reports_an_error_instead_of_raising(status):
    out = await _ask(lambda r: _chat(None, status=status))
    assert "_error" in out and out["_error"]
    assert "sk-judge" not in json.dumps(out)


async def test_empty_content_is_a_failed_call():
    out = await _ask(lambda r: _chat(""))
    assert "_error" in out


async def test_transport_error_reports_an_error():
    def handler(request):
        raise httpx.ConnectError("refused")

    out = await _ask(handler)
    assert "_error" in out


def test_parse_json_non_dict_top_level_is_rejected():
    assert _parse_json("[1]")["_error"] == "could not parse judge JSON"
    assert _parse_json('{"k": [1, 2]}') == {"k": [1, 2]}


def test_judge_unavailable_is_an_exception():
    assert issubclass(JudgeUnavailable, Exception)
