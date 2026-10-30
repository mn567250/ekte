"""Offline tests of the advisory LLM review (tests/a11y/llm_review.py).

No network: the pure extraction post-processing, the request building and the
response parsing are tested directly, the HTTP client against an
httpx.MockTransport (plain JSON and streamed answers). A few tests run the
in-page extraction against a static HTML snippet in Chromium; they are skipped
when Playwright or a browser is not installed (the default CI test job).
"""

from __future__ import annotations

import json
import os
import re
import sys
import types
from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from tests.a11y import llm_review as lr

RAW = {
    "title": "  ekte —   audit  ",
    "lang": "en",
    "headings": [[1, "Audit"], [1, "Audit"], [2, "x" * 400]],
    "links": [
        {"name": "More", "href": "/a", "context": ""},
        {"name": "More", "href": "/b", "context": "Read the guide"},
        {"name": "More", "href": "/a", "context": ""},
    ],
    "controls": [{"role": "button", "name": "Go", "state": ""}],
    "fields": [{"label": "Relay URL", "placeholder": "https://…", "description": "", "required": False, "type": "text"}],
    "images": [
        {"kind": "svg", "name": "", "decorative": True},
        {"kind": "img", "name": "chart.png", "decorative": False, "src": "chart.png"},
    ],
    "instructions": [f"instruction sentence {i}" for i in range(lr.LIMITS["instructions"] + 7)],
}


def _answer(findings: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    body = {
        "model": lr.MODEL,
        "stop_reason": "end_turn",
        "content": [{"type": "thinking", "thinking": ""}, {"type": "text", "text": json.dumps({"findings": findings})}],
        "usage": {"input_tokens": 1000, "output_tokens": 100, "cache_read_input_tokens": 2000},
    }
    body.update(extra)
    return body


def _sse(events: list[dict[str, Any]]) -> bytes:
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


def _stream_events(text_parts: list[str], *, model: str = lr.MODEL, usage: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    ev: list[dict[str, Any]] = [
        {"type": "message_start", "message": {"id": "msg_1", "model": model, "usage": {"input_tokens": 1000, "output_tokens": 1}}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "hmm"}},
        {"type": "content_block_stop", "index": 0},
        {"type": "ping"},
        {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
    ]
    ev += [{"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": t}} for t in text_parts]
    ev += [
        {"type": "content_block_stop", "index": 1},
        {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": usage or {"output_tokens": 500}},
        {"type": "message_stop"},
    ]
    return ev


F_LINK = {"step": "9.2.4.4", "lang": "en", "element": 'link "More"', "problem": "ambiguous", "suggestion": "Name it"}


# --------------------------------------------------------------------------- #
# compaction
# --------------------------------------------------------------------------- #
def test_compact_page_cleans_groups_and_payload_caps() -> None:
    rec = lr.compact_page(RAW, [{"form": "Start", "text": " Invalid ", "field": ""}])
    assert rec["title"] == "ekte — audit"
    pay = lr.page_payload(rec)
    # identical headings are merged with a count (not silently dropped)
    assert pay["headings"][0] == [1, "Audit", 2] and len(pay["headings"]) == 2
    assert len(pay["headings"][1][1]) == lr.MAX_TEXT and pay["headings"][1][1].endswith("…")
    # same name + same target: one item with a count; another target stays separate
    assert pay["links"] == [
        {"name": "More", "href": "/a", "count": 2},
        {"name": "More", "href": "/b", "context": "Read the guide"},
    ]
    assert pay["fields"] == [{"label": "Relay URL", "placeholder": "https://…", "type": "text"}]
    # decorative images are counted, not sent
    assert pay["decorative_images"] == 1
    assert pay["images"] == [{"kind": "img", "name": "chart.png", "src": "chart.png"}]
    assert len(pay["instructions"]) == lr.LIMITS["instructions"]
    assert pay["truncated"] == {"instructions": 7}
    assert pay["messages"] == [{"form": "Start", "text": "Invalid"}]


# --------------------------------------------------------------------------- #
# bug 1: duplicates stay visible (count + targets)
# --------------------------------------------------------------------------- #
def test_repeated_names_are_counted_with_their_targets() -> None:
    raw = {
        "controls": [
            {"role": "button", "name": "Hide evidence", "state": "expanded=true", "target": f"ev-{i}", "key": f"#ev-b{i}"}
            for i in range(33)
        ]
        + [{"role": "button", "name": "Re-run audit", "key": "#a"}, {"role": "button", "name": "Re-run audit", "key": "#b"}],
        "links": [{"name": "Docs", "href": "/d", "key": "k1"}, {"name": "Docs", "href": "/e", "key": "k2"}],
    }
    pay = lr.page_payload(lr.compact_page(raw))
    hide = pay["controls"][0]
    assert hide["name"] == "Hide evidence" and hide["count"] == 33
    assert hide["targets"] == [f"ev-{i}" for i in range(lr.MAX_TARGETS)] and hide["targets_more"] == 33 - lr.MAX_TARGETS
    assert "target" not in hide and "key" not in hide
    assert pay["controls"][1] == {"role": "button", "name": "Re-run audit", "count": 2}
    assert pay["links"] == [{"name": "Docs", "count": 2, "targets": ["/d", "/e"]}]
    # the rubric tells the model what count/targets mean
    assert '"count"' in lr.RUBRIC and '"targets"' in lr.RUBRIC


def test_control_description_is_kept_and_separates_repeats() -> None:
    raw = {
        "controls": [
            {"role": "button", "name": "Show key", "target": "k1", "description": "OpenAI API key", "key": "#a"},
            {"role": "button", "name": "Show key", "target": "k2", "description": "Relay token", "key": "#b"},
            {"role": "button", "name": "Show key", "target": "k3", "description": "Relay token", "key": "#c"},
            {"role": "button", "name": "Go", "description": "", "key": "#d"},
        ]
    }
    pay = lr.page_payload(lr.compact_page(raw))
    assert pay["controls"] == [
        {"role": "button", "name": "Show key", "target": "k1", "description": "OpenAI API key"},
        {"role": "button", "name": "Show key", "description": "Relay token", "count": 2, "targets": ["k2", "k3"]},
        {"role": "button", "name": "Go"},  # empty description dropped
    ]
    assert "description" in lr.RUBRIC.split('"fields"')[0]


# --------------------------------------------------------------------------- #
# bug 2: language-aware instruction filter, translation aligned by element
# --------------------------------------------------------------------------- #
def test_instruction_filter_is_language_aware() -> None:
    assert lr.long_enough("历史只保存在本地。")  # short Chinese sentence: kept
    assert lr.long_enough("稳定可达？")
    assert not lr.long_enough("检测中…")
    assert not lr.long_enough("Optional")
    assert lr.long_enough("Leave it empty.")
    assert lr.text_weight("ab 中文") == 3 + 6


def test_translation_view_aligns_by_element_key() -> None:
    en = lr.compact_page(
        {
            "title": "T",
            "headings": [{"level": 1, "name": "Audit", "key": "#h"}],
            "instructions": [
                {"text": "Only English has this extra sentence.", "key": "#extra"},
                {"text": "History stays on this machine.", "key": "#p1"},
                {"text": "Is it stable?", "key": "#q"},
            ],
        }
    )
    zh = lr.compact_page(
        {
            "title": "T-zh",
            "headings": [{"level": 1, "name": "检测", "key": "#h"}],
            "instructions": [{"text": "历史只保存在本机。", "key": "#p1"}, {"text": "稳定？", "key": "#q"}],
        }
    )
    de = lr.compact_page({"title": "T-de", "instructions": [{"text": "Der Verlauf bleibt lokal.", "key": "#p1"}]})
    view = lr.translation_view({"zh": zh, "de": de, "en": en})
    assert view["langs"] == ["en", "de", "zh"]
    rows = {(r["kind"], r["en"]): r for r in view["rows"]}
    # the zh sentence is compared with the English sentence of the same element,
    # not with whatever happens to be at the same list position
    p1 = rows[("instruction", "History stays on this machine.")]
    assert p1["zh"] == "历史只保存在本机。" and p1["de"] == "Der Verlauf bleibt lokal."
    extra = rows[("instruction", "Only English has this extra sentence.")]
    assert extra["zh"] is None and extra["de"] is None
    # a row too short in one language is kept when it is long enough in another
    assert rows[("instruction", "Is it stable?")]["zh"] == "稳定？"
    assert rows[("heading", "Audit")]["zh"] == "检测"
    assert view["rows"][0] == {"kind": "title", "en": "T", "de": "T-de", "zh": "T-zh"}


def test_translation_view_accepts_old_shapes() -> None:
    recs = {lang: lr.compact_page(dict(RAW, title=f"T-{lang}")) for lang in ("zh", "de", "en")}
    view = lr.translation_view(recs)
    assert view["langs"] == ["en", "de", "zh"]
    assert view["rows"][0]["de"] == "T-de"


# --------------------------------------------------------------------------- #
# bug 3 + 5: names from the accessibility tree, name source of fields
# --------------------------------------------------------------------------- #
AX_DOM = {
    "backendNodeId": 1,
    "children": [
        {"backendNodeId": 10, "attributes": ["class", "cta", "data-lr-ax", "0"]},
        {"backendNodeId": 11, "attributes": ["data-lr-ax", "1", "placeholder", "Search"]},
        {"backendNodeId": 12, "attributes": ["data-lr-ax", "2"], "shadowRoots": [{"backendNodeId": 13, "attributes": ["data-lr-ax", "3"]}]},
    ],
}
AX_NODES = [
    {"backendDOMNodeId": 10, "name": {"value": "Verify embedding endpoint", "sources": [
        {"type": "attribute", "attribute": "aria-label"},
        {"type": "contents", "value": {"type": "computedString", "value": "Verify embedding endpoint"}},
    ]}},
    {"backendDOMNodeId": 11, "name": {"value": "Search", "sources": [
        {"type": "relatedElement", "attribute": "aria-labelledby"},
        {"type": "attribute", "attribute": "aria-label"},
        {"type": "relatedElement", "nativeSource": "labelfor"},
        {"type": "attribute", "attribute": "title", "superseded": True},
        {"type": "placeholder", "attribute": "placeholder", "value": {"type": "computedString", "value": "Search"}},
    ]}},
    {"backendDOMNodeId": 12, "ignored": True, "name": {"value": "x"}},
    {"backendDOMNodeId": 13, "name": {"value": "Relay URL", "sources": [
        {"type": "relatedElement", "nativeSource": "labelfor", "value": {"type": "computedString", "value": "Relay URL"}},
        {"type": "placeholder", "superseded": True, "value": {"type": "computedString", "value": "https://"}},
    ]}},
]


def test_ax_names_replace_dom_names() -> None:
    names = lr.ax_names(AX_DOM, AX_NODES)
    assert names == {
        "0": {"name": "Verify embedding endpoint", "from": "contents"},
        "1": {"name": "Search", "from": "placeholder"},
        "3": {"name": "Relay URL", "from": "label"},
    }
    raw = {
        "controls": [{"role": "button", "name": "Verify embedding endpoint Running checks…", "ax": "0"}],
        "fields": [
            {"label": "", "name_from": "none", "placeholder": "Search", "ax": "1"},
            {"label": "Relay URL", "name_from": "label", "visible_label": "Relay URL", "ax": "3"},
            {"label": "kept", "name_from": "title", "ax": "9"},
        ],
    }
    lr.apply_ax_names(raw, names)
    # the hidden busy label is not part of the real accessible name
    assert raw["controls"][0]["name"] == "Verify embedding endpoint"
    assert raw["fields"][0]["label"] == "Search" and raw["fields"][0]["name_from"] == "placeholder"
    assert raw["fields"][1]["name_from"] == "label"
    assert raw["fields"][2]["label"] == "kept"  # no tree node: DOM fallback stays
    pay = lr.page_payload(lr.compact_page(raw))
    assert pay["fields"][0] == {"label": "Search", "name_from": "placeholder", "placeholder": "Search"}
    assert pay["controls"][0] == {"role": "button", "name": "Verify embedding endpoint"}
    for word in ("name_from", "visible_label", '"placeholder"'):
        assert word in lr.RUBRIC


def test_name_source_none() -> None:
    assert lr._name_source([{"type": "contents", "value": {"value": "  "}}]) == "none"
    assert lr._name_source(None) == "none"


# --------------------------------------------------------------------------- #
# bug 4: every tab panel is extracted and merged
# --------------------------------------------------------------------------- #
def test_merge_raw_keeps_every_tab_panel_once() -> None:
    nav = {"name": "Tools", "href": "/v2/tools", "key": "#nav>a:2"}
    embed = {
        "title": "Tools",
        "links": [nav],
        "controls": [{"role": "tab", "name": "Embedding", "state": "selected=true", "key": "#tab-embed"}],
        "fields": [{"label": "Relay URL", "key": "#e-url"}],
        "instructions": [{"text": "Embedding help text here.", "key": "#panel-embed>p:1"}],
    }
    rerank = {
        "title": "Tools",
        "links": [nav],
        "controls": [{"role": "tab", "name": "Embedding", "state": "selected=false", "key": "#tab-embed"},
                     {"role": "button", "name": "Verify rerank endpoint", "key": "#r-go"}],
        "fields": [{"label": "Relay URL", "key": "#r-url"}, {"label": "Documents", "key": "#r-docs"}],
        "instructions": [{"text": "Rerank help text here.", "key": "#panel-rerank>p:1"}],
    }
    merged = lr.merge_raw([embed, rerank])
    assert merged["links"] == [nav]
    assert [c["key"] for c in merged["controls"]] == ["#tab-embed", "#r-go"]
    assert merged["controls"][0]["state"] == "selected=true"  # first state wins
    assert [f["key"] for f in merged["fields"]] == ["#e-url", "#r-url", "#r-docs"]
    assert len(merged["instructions"]) == 2
    assert lr.merge_raw([]) == {}


# --------------------------------------------------------------------------- #
# bug 8 (browser safety): destructive disclosures, non-GET requests
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "word, bad",
    [("rdel", True), ("del", True), ("trash", True), ("clr", True), ("clrConfirm", False), ("confirm", True),
     ("model", False), ("delta", False), ("dtog", False), ("more", False), ("Delete", True)],
)
def test_destructive_words(word: str, bad: bool) -> None:
    assert bool(re.search(lr.DESTRUCTIVE, word, re.I)) is bad


def test_only_safe_requests_reach_the_app() -> None:
    base = "http://127.0.0.1:8000"
    assert lr.is_blocked_request("POST", base + "/api/watches/1/activate", base)
    assert lr.is_blocked_request("delete", base + "/api/history/1", base)
    assert not lr.is_blocked_request("GET", base + "/api/history", base)
    assert not lr.is_blocked_request("POST", "https://elsewhere.example/api", base)


# --------------------------------------------------------------------------- #
# request
# --------------------------------------------------------------------------- #
def test_build_request_shape() -> None:
    rec = lr.page_payload(lr.compact_page(RAW))
    body = lr.build_request("page", "audit", rec, lang="de")
    assert body["model"] == "claude-opus-5-5"
    # the rubric is the cached system prompt; nothing volatile in it
    assert body["system"] == [{"type": "text", "text": lr.RUBRIC, "cache_control": {"type": "ephemeral"}}]
    assert len(lr.RUBRIC) > 4000  # well above the 512-token cache minimum
    for step in lr.STEPS:
        assert f'"{step}"' in lr.RUBRIC
    # sampling parameters are rejected by this model; the answer is schema-bound
    assert not {"temperature", "top_p", "top_k", "thinking"} & set(body)
    assert body["output_config"]["format"] == {"type": "json_schema", "schema": lr.FINDINGS_SCHEMA}
    assert body["output_config"]["effort"] == "high"
    assert body["fallbacks"] == "default"
    # streamed with room for a long answer (bug 8: no max_tokens cut-offs)
    assert body["stream"] is True and body["max_tokens"] == lr.MAX_TOKENS >= 64000
    user = body["messages"][0]["content"]
    assert body["messages"][0]["role"] == "user"
    assert '{"lang":"de"' not in user and '"lang": "de"' in user and '"page": "audit"' in user
    data = user.split("<page_data>\n", 1)[1].rsplit("\n</page_data>", 1)[0]
    assert json.loads(data) == rec
    # deterministic: same input, same bytes
    assert json.dumps(lr.build_request("page", "audit", rec, lang="de")) == json.dumps(body)


def test_schema_steps_match_rubric() -> None:
    enum = lr.FINDINGS_SCHEMA["properties"]["findings"]["items"]["properties"]["step"]["enum"]
    assert enum == list(lr.STEPS)
    assert {"9.1.1.1", "9.2.4.4", "9.2.4.6", "9.1.3.3", "9.3.3.3", "9.3.3.2", "translation"} == set(enum)


# --------------------------------------------------------------------------- #
# response parsing
# --------------------------------------------------------------------------- #
def test_parse_response_keeps_valid_findings_only() -> None:
    body = _answer(
        [
            F_LINK,
            dict(F_LINK),  # duplicate
            dict(F_LINK, step="1.4.3"),  # not a reviewed step
            dict(F_LINK, step="translation"),  # wrong task
            dict(F_LINK, element=""),  # unusable
            "junk",
        ]
    )
    fs = lr.parse_response(body, "page", "audit", "de")
    assert fs == [
        {"step": "9.2.4.4", "page": "audit", "lang": "de", "element": 'link "More"', "problem": "ambiguous", "suggestion": "Name it"}
    ]


def test_parse_response_translation_keeps_model_lang() -> None:
    body = _answer([dict(F_LINK, step="translation", lang="fr"), F_LINK])
    fs = lr.parse_response(body, "translation", "kb")
    assert [(f["step"], f["lang"]) for f in fs] == [("translation", "fr")]


@pytest.mark.parametrize(
    "body, msg",
    [
        ({"stop_reason": "refusal", "stop_details": {"category": "cyber"}, "content": []}, "refusal"),
        ({"stop_reason": "max_tokens", "content": [{"type": "text", "text": '{"find'}]}, "max_tokens"),
        ({"stop_reason": "end_turn", "content": [{"type": "text", "text": "no json"}]}, "not JSON"),
        ({"stop_reason": "end_turn", "content": [{"type": "text", "text": "[]"}]}, "findings"),
        ({"stop_reason": "end_turn", "content": []}, "no text"),
    ],
)
def test_parse_response_errors(body: dict[str, Any], msg: str) -> None:
    with pytest.raises(lr.ReviewError, match=msg):
        lr.parse_response(body, "page", "audit", "en")


# --------------------------------------------------------------------------- #
# bug 6: verdicts only "ok" when every planned request was answered
# --------------------------------------------------------------------------- #
def _jobs(*rows: tuple[str, str, str, str]) -> list[dict[str, Any]]:
    return [{"task": t, "page": p, "lang": lg, "status": s} for t, p, lg, s in rows]


def test_aggregate_complete_partial_and_unreviewed() -> None:
    f = lr.parse_response(_answer([F_LINK]), "page", "audit", "en")
    steps = lr.aggregate(f, _jobs(("page", "audit", "en", "reviewed")))
    assert set(steps) == set(lr.STEPS)
    assert steps["9.2.4.4"]["verdict"] == "issues"
    assert steps["9.2.4.4"]["findings"] == [
        {"page": "audit", "lang": "en", "element": 'link "More"', "problem": "ambiguous", "suggestion": "Name it"}
    ]
    assert steps["9.1.1.1"]["verdict"] == "ok"
    assert steps["translation"]["verdict"] == "not-reviewed"

    jobs = _jobs(
        ("page", "audit", "en", "reviewed"),
        ("page", "audit", "zh", "error"),
        ("page", "tools", "en", "not-sent"),
        ("translation", "audit", "all", "not-sent"),
    )
    steps = lr.aggregate([], jobs)
    for step in ("9.1.1.1", "9.3.3.3"):
        assert steps[step]["verdict"] == "partial"
        assert steps[step]["unreviewed"] == ["audit/zh", "tools/en"]
        assert (steps[step]["reviewed"], steps[step]["planned"]) == (1, 3)
    assert steps["translation"]["verdict"] == "not-reviewed"
    assert steps["translation"]["unreviewed"] == ["audit/all"]
    # findings do not hide that the step is incomplete
    assert lr.aggregate(f, jobs)["9.2.4.4"]["verdict"] == "partial"
    assert lr.aggregate(f, None)["9.2.4.4"]["verdict"] == "issues"


# --------------------------------------------------------------------------- #
# bug 8: cost with the model that answered
# --------------------------------------------------------------------------- #
def test_cost_uses_the_answering_model() -> None:
    assert lr.usage_cost({"input_tokens": 1_000_000, "output_tokens": 1_000_000}) == pytest.approx(24.0)
    assert lr.usage_cost({"cache_read_input_tokens": 1_000_000}) == pytest.approx(0.2)
    # answered by a fallback model: its own prices
    assert lr.usage_cost({"input_tokens": 1_000_000, "output_tokens": 1_000_000}, "claude-opus-4-8") == pytest.approx(30.0)
    # per attempt (usage.iterations is the billing source of truth)
    usage = {
        "input_tokens": 1_000_000,
        "output_tokens": 0,
        "iterations": [
            {"type": "message", "input_tokens": 1_000_000, "output_tokens": 0},
            {"type": "fallback_message", "input_tokens": 1_000_000, "output_tokens": 0},
        ],
    }
    assert lr.usage_cost(usage, "claude-opus-4-8", lr.MODEL) == pytest.approx(4.0 + 5.0)
    usage["iterations"][1]["model"] = "claude-sonnet-5-5"
    assert lr.usage_cost(usage, "claude-opus-4-8", lr.MODEL) == pytest.approx(4.0 + 2.0)
    # unknown model: never underestimated
    assert lr.usage_cost({"output_tokens": 1_000_000}, "claude-future-9") == pytest.approx(
        max(p["output"] for p in lr.PRICES.values())
    )


# --------------------------------------------------------------------------- #
# HTTP client (mocked transport)
# --------------------------------------------------------------------------- #
def _client(handler: Any, **kw: Any) -> tuple[lr.Client, list[float]]:
    sleeps: list[float] = []
    c = lr.Client("sk-test", transport=httpx.MockTransport(handler), sleep=sleeps.append, **kw)
    return c, sleeps


def test_client_sends_headers_and_counts_usage() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json=_answer([F_LINK]))

    c, sleeps = _client(handler)
    out = c.send(lr.build_request("page", "audit", {}, lang="en"))
    assert out["model"] == lr.MODEL and not sleeps
    req = seen[0]
    assert str(req.url) == lr.API_URL
    assert req.headers["x-api-key"] == "sk-test"
    assert req.headers["anthropic-version"] == "2023-06-01"
    assert req.headers["anthropic-beta"] == lr.FALLBACK_BETA
    assert json.loads(req.content)["model"] == lr.MODEL
    assert c.requests == 1 and c.usage["cache_read_input_tokens"] == 2000
    assert c.cost == pytest.approx(lr.usage_cost(_answer([])["usage"]))


def test_client_reads_a_streamed_answer() -> None:
    text = json.dumps({"findings": [F_LINK]})

    def handler(req: httpx.Request) -> httpx.Response:
        assert json.loads(req.content)["stream"] is True
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=_sse(_stream_events([text[:10], text[10:]], usage={"output_tokens": 30000})),
        )

    c, _ = _client(handler)
    out = c.send(lr.build_request("translation", "kb", {"rows": []}))
    assert out["stop_reason"] == "end_turn" and out["model"] == lr.MODEL
    assert lr.parse_response(out, "page", "kb", "en")[0]["element"] == 'link "More"'
    # a long answer (30k output tokens) is fine; usage is the final cumulative one
    assert c.usage == {"input_tokens": 1000, "output_tokens": 30000}


def test_read_sse_with_mid_stream_fallback() -> None:
    ev = _stream_events(['{"findings":'], model="claude-opus-4-8")
    ev.insert(-3, {"type": "content_block_start", "index": 2, "content_block": {"type": "fallback", "from": {"model": lr.MODEL}, "to": {"model": "claude-opus-4-8"}}})
    ev.insert(-3, {"type": "content_block_stop", "index": 2})
    ev.insert(-3, {"type": "content_block_start", "index": 3, "content_block": {"type": "text", "text": ""}})
    ev.insert(-3, {"type": "content_block_delta", "index": 3, "delta": {"type": "text_delta", "text": "[]}"}})
    lines = _sse(ev).decode().splitlines()
    msg = lr.read_sse(lines)
    assert [b["type"] for b in msg["content"]] == ["thinking", "text", "fallback", "text"]
    assert lr.parse_response(msg, "page", "a", "en") == []
    assert msg["model"] == "claude-opus-4-8"


def test_client_retries_broken_streams() -> None:
    calls: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:  # overloaded mid-stream
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=_sse([{"type": "error", "error": {"type": "overloaded_error", "message": "x"}}]))
        if len(calls) == 2:  # connection dropped before message_stop
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=_sse(_stream_events(["{}"])[:4]))
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=_sse(_stream_events(['{"findings":[]}'])))

    c, sleeps = _client(handler)
    out = c.send(lr.build_request("page", "a", {}, lang="en"))
    assert lr.parse_response(out, "page", "a", "en") == []
    assert len(calls) == 3 and len(sleeps) == 2 and c.requests == 1


def test_client_retries_with_backoff() -> None:
    codes = iter([529, 429, 200])

    def handler(req: httpx.Request) -> httpx.Response:
        code = next(codes)
        if code == 429:
            return httpx.Response(429, headers={"retry-after": "7"}, json={"error": {}})
        if code == 200:
            return httpx.Response(200, json=_answer([]))
        return httpx.Response(code, json={"error": {"type": "overloaded_error"}})

    c, sleeps = _client(handler)
    c.send({"x": 1})
    assert len(sleeps) == 2
    assert 2.0 <= sleeps[0] <= 3.0  # exponential backoff with jitter
    assert sleeps[1] == 7.0  # retry-after honoured
    assert c.requests == 1  # retries do not count against the request budget


def test_client_retries_transport_errors_then_gives_up() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    c, sleeps = _client(handler, retries=3)
    with pytest.raises(lr.ReviewError, match="gave up after 4 attempts: ConnectError"):
        c.send({})
    assert len(sleeps) == 3 and sleeps == sorted(sleeps)


def test_client_does_not_retry_client_errors() -> None:
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(400, json={"error": {"message": "bad"}})

    c, sleeps = _client(handler)
    with pytest.raises(lr.ReviewError, match="HTTP 400"):
        c.send({})
    assert len(calls) == 1 and not sleeps


def test_cost_guard_stops_sending() -> None:
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        return httpx.Response(200, json=_answer([]))

    c, _ = _client(handler, max_requests=2)
    c.send({})
    c.send({})
    with pytest.raises(lr.BudgetStop, match="request limit"):
        c.send({})
    assert len(calls) == 2


def test_cost_guard_counts_the_next_request_before_sending() -> None:
    """--max-cost is not overshot: a request whose estimated cost would take
    the total above the limit is not sent."""
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(1)
        # every answer costs about $0.10 (5000 output tokens at $20/M)
        return httpx.Response(200, json=_answer([], usage={"input_tokens": 0, "output_tokens": 5000}))

    body = lr.build_request("page", "a", {"x": "y" * 3000}, lang="en")
    c, _ = _client(handler, max_cost=0.25)
    est0 = c.estimate(body)
    assert 0.1 < est0 < 0.25  # default output estimate + input
    c.send(body)
    c.send(body)  # 0.10 spent + ~0.11 estimated <= 0.25
    with pytest.raises(lr.BudgetStop, match="cost limit"):
        c.send(body)  # 0.20 spent + ~0.11 estimated > 0.25: not sent
    assert len(calls) == 2 and c.cost <= 0.25
    # the old guard (check after the fact) would have sent a third request
    assert c.cost < c.max_cost


def test_estimate_tokens_counts_cjk_conservatively() -> None:
    assert lr.estimate_tokens("中文" * 100) >= 200
    assert lr.estimate_tokens("a" * 300) >= 100


# --------------------------------------------------------------------------- #
# endpoint: command line, ekte.yaml, environment, defaults
# --------------------------------------------------------------------------- #
EKTE_YAML = """\
target:
  base_url: https://relay.example.com/v1
  api_key: env:RELAY_KEY
  model: gpt-4o
baseline:
  base_url: https://api.openai.com/v1
  api_key: env:OPENAI_KEY
  model: gpt-4o
judge:
  base_url: https://judge.example.com/v1
  api_key: env:JUDGE_KEY
  model: claude-sonnet-5-5
"""
ENV = {"JUDGE_KEY": "sk-judge", "OPENAI_KEY": "sk-openai", "RELAY_KEY": "sk-relay", "ANTHROPIC_API_KEY": "sk-ant"}


def _yaml(tmp_path: Any, text: str = EKTE_YAML) -> str:
    f = tmp_path / "ekte.yaml"
    f.write_text(text, encoding="utf-8")
    return str(f)


def test_endpoint_defaults_to_the_anthropic_api(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)  # no ./ekte.yaml
    ep = lr.resolve_endpoint(env={"ANTHROPIC_API_KEY": "sk-ant"})
    assert ep == lr.Endpoint(lr.API_BASE, "sk-ant", lr.MODEL, "anthropic", "default")
    assert ep.url == lr.API_URL and ep.official and not ep.local
    # ANTHROPIC_BASE_URL is the host without /v1 (SDK convention)
    ep = lr.resolve_endpoint(env={"ANTHROPIC_BASE_URL": "https://gw.example.com", "ANTHROPIC_API_KEY": "k"})
    assert ep.url == "https://gw.example.com/v1/messages" and ep.source == "env" and ep.api_key == "k"
    assert not ep.official


def test_endpoint_from_ekte_yaml_judge_then_baseline_then_target(tmp_path: Any) -> None:
    cfg = _yaml(tmp_path)
    ep = lr.resolve_endpoint(config=cfg, env=ENV)
    assert (ep.base_url, ep.api_key, ep.model, ep.api, ep.source) == (
        "https://judge.example.com/v1", "sk-judge", "claude-sonnet-5-5", "anthropic", "ekte.yaml:judge")
    no_judge = EKTE_YAML.split("judge:")[0]
    ep = lr.resolve_endpoint(config=_yaml(tmp_path, no_judge), env=ENV)
    assert (ep.base_url, ep.api_key, ep.api, ep.source) == (
        "https://api.openai.com/v1", "sk-openai", "openai", "ekte.yaml:baseline")
    ep = lr.resolve_endpoint(config=_yaml(tmp_path, no_judge.split("baseline:")[0]), env=ENV)
    assert (ep.api_key, ep.model, ep.source) == ("sk-relay", "gpt-4o", "ekte.yaml:target")
    assert ep.url == "https://relay.example.com/v1/chat/completions"


def test_endpoint_default_config_is_the_working_directory_ekte_yaml(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _yaml(tmp_path)
    monkeypatch.chdir(tmp_path)
    assert lr.resolve_endpoint(env=ENV).source == "ekte.yaml:judge"


def test_endpoint_command_line_wins_per_field(tmp_path: Any) -> None:
    cfg = _yaml(tmp_path)
    # only the model: URL and key still from the configuration
    ep = lr.resolve_endpoint(model="claude-opus-5-5", config=cfg, env=ENV)
    assert (ep.base_url, ep.api_key, ep.model) == ("https://judge.example.com/v1", "sk-judge", "claude-opus-5-5")
    # the same URL on the command line keeps the configured key
    ep = lr.resolve_endpoint(base_url="https://judge.example.com/v1/", config=cfg, env=ENV)
    assert ep.api_key == "sk-judge" and ep.source == "cli"
    # another URL: no key from the configuration or ANTHROPIC_API_KEY (never sent to another host)
    ep = lr.resolve_endpoint(base_url="https://other.example.com/v1", model="m", config=cfg, env=ENV)
    assert ep.api_key == "" and ep.api == "openai"
    ep = lr.resolve_endpoint(base_url="https://other.example.com/v1", api_key="env:RELAY_KEY", model="m",
                             api="anthropic", config=cfg, env=ENV)
    assert (ep.api_key, ep.api) == ("sk-relay", "anthropic")
    assert ep.url == "https://other.example.com/v1/messages"


def test_endpoint_needs_a_model_for_another_url(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from ekte.config import ConfigError

    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError, match="--model"):
        lr.resolve_endpoint(base_url="http://localhost:11434/v1", env={})
    ep = lr.resolve_endpoint(base_url="http://localhost:11434/v1", model="qwen3", env={})
    assert ep.local and ep.api == "openai" and ep.api_key == ""
    assert ep.url == "http://localhost:11434/v1/chat/completions"
    # a full endpoint URL is used as given
    assert lr.Endpoint("http://h:1/v1/chat/completions", api="openai").url == "http://h:1/v1/chat/completions"


def test_build_request_openai_shape() -> None:
    rec = lr.page_payload(lr.compact_page(RAW))
    body = lr.build_request_openai("page", "audit", rec, lang="de", model="qwen3")
    assert body["model"] == "qwen3" and body["stream"] is True
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert body["messages"][0]["content"].startswith(lr.RUBRIC) and '"findings"' in body["messages"][0]["content"]
    # same user turn as the Messages API request
    assert body["messages"][1]["content"] == lr.build_request("page", "audit", rec, lang="de")["messages"][0]["content"]
    assert body["response_format"]["json_schema"]["schema"] == lr.FINDINGS_SCHEMA
    assert lr.build_request_openai("page", "a", {}, json_schema=False)["response_format"] == {"type": "json_object"}
    # no Anthropic-only fields
    assert not {"system", "output_config", "fallbacks", "max_tokens"} & set(body)
    # relays: no server-side fallback request
    assert "fallbacks" not in lr.make_request(lr.Endpoint("https://relay.example/v1"), "page", "a", {})


def _openai_chunks(parts: list[str], *, finish: str = "stop") -> bytes:
    ev = [{"model": "qwen3", "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}}]}]
    ev += [{"model": "qwen3", "choices": [{"index": 0, "delta": {"content": p}}]} for p in parts]
    ev += [{"model": "qwen3", "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
           {"model": "qwen3", "choices": [], "usage": {"prompt_tokens": 900, "completion_tokens": 50,
                                                       "prompt_tokens_details": {"cached_tokens": 100}}}]
    return ("".join(f"data: {json.dumps(e)}\n\n" for e in ev) + "data: [DONE]\n\n").encode()


def test_openai_client_streams_and_is_free_on_a_local_host() -> None:
    text = "<think>checking</think>\n```json\n" + json.dumps({"findings": [F_LINK]}) + "\n```"
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=_openai_chunks([text[:15], text[15:]]))

    ep = lr.Endpoint("http://127.0.0.1:11434/v1", "", "qwen3", "openai", "cli")
    c = lr.Client(endpoint=ep, transport=httpx.MockTransport(handler), sleep=lambda s: None, max_cost=0.0)
    out = c.send(c.request("page", "audit", {}, lang="en"))
    assert str(seen[0].url) == "http://127.0.0.1:11434/v1/chat/completions"
    assert "authorization" not in seen[0].headers and "x-api-key" not in seen[0].headers
    assert out["stop_reason"] == "end_turn" and out["model"] == "qwen3"
    assert lr.parse_response(out, "page", "audit", "en")[0]["element"] == 'link "More"'
    assert c.usage == {"input_tokens": 800, "output_tokens": 50, "cache_read_input_tokens": 100}
    assert c.cost == 0.0  # a local model costs nothing; max_cost=0 did not stop it


def test_openai_client_sends_bearer_and_falls_back_to_json_mode() -> None:
    seen: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        seen.append(body)
        assert req.headers["authorization"] == "Bearer sk-relay"
        if body["response_format"]["type"] == "json_schema":
            return httpx.Response(400, json={"error": {"message": "response_format json_schema is not supported"}})
        answer = {"model": "gpt-x", "choices": [{"message": {"content": json.dumps({"findings": []})},
                                                 "finish_reason": "stop"}], "usage": {"prompt_tokens": 10}}
        return httpx.Response(200, json=answer)

    ep = lr.Endpoint("https://relay.example.com/v1", "sk-relay", "gpt-x", "openai", "cli")
    c = lr.Client(endpoint=ep, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    assert lr.parse_response(c.send(c.request("page", "a", {})), "page", "a", "en") == []
    assert [b["response_format"]["type"] for b in seen] == ["json_schema", "json_object"]
    # later requests go straight to JSON mode
    c.send(c.request("page", "b", {}))
    assert seen[-1]["response_format"]["type"] == "json_object" and len(seen) == 3
    assert c.requests == 2


def test_read_sse_openai_maps_finish_reasons_and_broken_streams() -> None:
    out = lr.read_sse_openai(_openai_chunks(['{"find'], finish="length").decode().splitlines())
    assert out["stop_reason"] == "max_tokens"
    with pytest.raises(lr.ReviewError, match="max_tokens"):
        lr.parse_response(out, "page", "a")
    with pytest.raises(lr._Retryable):
        lr.read_sse_openai(['data: {"choices": [{"delta": {"content": "x"}}]}'])
    assert lr.from_openai({"choices": [{"message": {"content": None, "refusal": "no"}, "finish_reason": "stop"}]})[
        "stop_reason"] == "refusal"


# --------------------------------------------------------------------------- #
# whole review (mocked API, no browser)
# --------------------------------------------------------------------------- #
def test_review_end_to_end() -> None:
    records = {
        "audit": {"en": lr.compact_page(RAW), "de": lr.compact_page(RAW)},
        "kb": {"en": lr.compact_page(RAW)},
    }
    asked: list[dict[str, Any]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        asked.append(body)
        head = json.loads(body["messages"][0]["content"].split("\n")[1])
        if head["task"] == "translation":
            return httpx.Response(200, json=_answer([dict(F_LINK, step="translation", lang="de")]))
        if head["page"] == "kb":
            return httpx.Response(200, json={"stop_reason": "refusal", "content": [], "usage": {}})
        return httpx.Response(200, json=_answer([F_LINK]))

    c, _ = _client(handler)
    rep = lr.review(records, c, pages={"audit": "/v2/", "kb": "/v2/kb"}, log=lambda s: None)
    # page+lang requests, plus one translation request for the page with 2 languages
    assert [(e["task"], e["page"], e["lang"]) for e in rep["pages"]] == [
        ("page", "audit", "en"),
        ("page", "audit", "de"),
        ("translation", "audit", "all"),
        ("page", "kb", "en"),
    ]
    assert len(asked) == 4
    assert [e["status"] for e in rep["pages"]] == ["reviewed", "reviewed", "reviewed", "error"]
    assert "refusal" in rep["pages"][3]["error"]
    assert rep["pages"][0]["path"] == "/v2/" and "data" in rep["pages"][0]
    # bug 8: the translation payload is saved for auditing, exactly as sent
    tr = rep["pages"][2]
    assert tr["data"]["langs"] == ["en", "de"] and tr["data"]["rows"]
    sent = asked[2]["messages"][0]["content"].split("<page_data>\n", 1)[1].rsplit("\n</page_data>", 1)[0]
    assert json.loads(sent) == tr["data"]
    assert {f["lang"] for f in rep["steps"]["9.2.4.4"]["findings"]} == {"en", "de"}
    assert rep["steps"]["translation"]["verdict"] == "issues"
    # bug 6: kb/en failed, so page steps are partial, not "ok"
    assert rep["steps"]["9.3.3.3"]["verdict"] == "partial"
    assert rep["steps"]["9.3.3.3"]["unreviewed"] == ["kb/en"]
    assert rep["steps"]["9.2.4.4"]["verdict"] == "partial"
    assert rep["status"] == "partial"
    assert rep["failures"] == [{"task": "page", "page": "kb", "lang": "en", "status": "error", "error": rep["pages"][3]["error"]}]
    assert rep["model"] == lr.MODEL and rep["requests"] == 4 and rep["cost_usd_estimate"] > 0
    assert set(rep["cost_usd_by_model"]) == {lr.MODEL}
    assert set(rep) >= {"generated_at", "model", "pages", "steps"}
    json.dumps(rep)  # serialisable


def test_review_budget_stop_is_recorded_per_page() -> None:
    records = {"audit": {"en": lr.compact_page(RAW), "de": lr.compact_page(RAW)}}
    c, _ = _client(lambda req: httpx.Response(200, json=_answer([])), max_requests=1)
    rep = lr.review(records, c, log=lambda s: None)
    assert [e["status"] for e in rep["pages"]] == ["reviewed", "not-sent", "not-sent"]
    assert "request limit" in rep["pages"][1]["error"]
    assert rep["steps"]["9.1.1.1"]["verdict"] == "partial"
    assert rep["steps"]["9.1.1.1"]["unreviewed"] == ["audit/de"]
    assert rep["steps"]["translation"]["verdict"] == "not-reviewed"
    assert [(f["page"], f["lang"], f["status"]) for f in rep["failures"]] == [("audit", "de", "not-sent"), ("audit", "all", "not-sent")]


def test_review_all_ok_and_collection_meta() -> None:
    rec = lr.compact_page(dict(RAW, states=2, blocked_requests=["POST /api/x"], skipped_disclosures=3))
    c, _ = _client(lambda req: httpx.Response(200, json=_answer([])))
    rep = lr.review({"tools": {"en": rec}}, c, log=lambda s: None)
    assert rep["status"] == "ok" and "failures" not in rep
    assert {s["verdict"] for k, s in rep["steps"].items() if k != "translation"} == {"ok"}
    assert rep["pages"][0]["collection"] == {"states": 2, "blocked_requests": ["POST /api/x"], "skipped_disclosures": 3}
    assert "states" not in rep["pages"][0]["data"]


def test_review_dry_run_marks_steps_not_reviewed() -> None:
    rep = lr.review({"audit": {"en": lr.compact_page(RAW)}}, None, log=lambda s: None)
    assert [e["status"] for e in rep["pages"]] == ["dry-run"]
    assert rep["status"] == "dry-run"
    assert {s["verdict"] for s in rep["steps"].values()} == {"not-reviewed"}


# --------------------------------------------------------------------------- #
# bug 7: a report is always written
# --------------------------------------------------------------------------- #
def test_main_without_key_writes_a_skipped_report(monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: Any) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "r.json"
    assert lr.main(["--out", str(out)]) == 0
    assert "ANTHROPIC_API_KEY is not set" in capsys.readouterr().out
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["status"] == "skipped: no API key" and rep["advisory"] is True
    assert rep["endpoint"] == {"base_url": lr.API_BASE, "api": "anthropic", "source": "default"}


def test_main_bad_config_writes_an_error_report(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "r.json"
    assert lr.main(["--config", str(tmp_path / "missing.yaml"), "--out", str(out)]) == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["status"] == "error" and "missing.yaml" in rep["error"]


def test_main_local_endpoint_needs_no_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    _fake_harness(monkeypatch)
    monkeypatch.setattr(lr, "collect", lambda pages, langs: {"audit": {lg: lr.compact_page(RAW) for lg in langs}})
    sent: list[lr.Endpoint] = []

    def fake_send(self: lr.Client, body: dict[str, Any]) -> dict[str, Any]:
        sent.append(self.endpoint)
        self.requests += 1
        return lr.from_openai({"model": "qwen3", "choices": [{"message": {"content": '{"findings": []}'},
                                                               "finish_reason": "stop"}]})

    monkeypatch.setattr(lr.Client, "send", fake_send)
    out = tmp_path / "r.json"
    assert lr.main(["--base-url", "http://localhost:11434/v1", "--model", "qwen3", "--out", str(out)]) == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["status"] == "ok" and rep["model"] == "qwen3" and len(sent) == 3
    assert rep["endpoint"] == {"base_url": "http://localhost:11434/v1", "api": "openai", "source": "cli"}
    assert rep["pages_reviewed"] == ["audit"] and rep["langs"] == ["en", "de"]
    assert rep["cost_usd_estimate"] == 0


def _fake_harness(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = types.ModuleType("tests.a11y.harness")
    mod.LANGS = ["en", "de"]  # type: ignore[attr-defined]
    mod.PAGES = {"audit": "/v2/"}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "tests.a11y.harness", mod)


def test_main_crash_writes_an_error_report(monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: Any) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.chdir(tmp_path)
    _fake_harness(monkeypatch)

    def boom(*a: Any, **k: Any) -> Any:
        raise RuntimeError("chromium crashed")

    monkeypatch.setattr(lr, "collect", boom)
    out = tmp_path / "r.json"
    assert lr.main(["--out", str(out)]) == 0  # still advisory
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["status"] == "error"
    assert rep["error"] == "RuntimeError: chromium crashed"
    assert "chromium crashed" in rep["traceback"]
    assert "failed: RuntimeError" in capsys.readouterr().out


def test_main_dry_run_writes_report(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    _fake_harness(monkeypatch)
    monkeypatch.setattr(lr, "collect", lambda pages, langs: {"audit": {lg: lr.compact_page(RAW) for lg in langs}})
    out = tmp_path / "r.json"
    assert lr.main(["--dry-run", "--out", str(out)]) == 0
    rep = json.loads(out.read_text(encoding="utf-8"))
    assert rep["status"] == "dry-run" and len(rep["pages"]) == 3


def _review_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.chdir(tmp_path)
    _fake_harness(monkeypatch)
    monkeypatch.setattr(lr, "collect", lambda pages, langs: {"audit": {lg: lr.compact_page(RAW) for lg in langs}})

    def fake_send(self: lr.Client, body: dict[str, Any]) -> dict[str, Any]:
        self.requests += 1
        head = json.loads(body["messages"][-1]["content"].split("\n")[1])
        fs = [F_LINK] if head["task"] == "page" and head.get("lang") == "de" else []
        return lr.from_openai({"model": "qwen3", "choices": [{"message": {"content": json.dumps({"findings": fs})},
                                                               "finish_reason": "stop"}]})

    monkeypatch.setattr(lr.Client, "send", fake_send)


def _tested_report(path: Any) -> dict[str, Any]:
    from tests.a11y import conformance

    rep = conformance.build_report({"langs": ["en", "de"], "pages": {"audit": "/v2/"}}, None)
    path.write_text(json.dumps(rep), encoding="utf-8")
    return rep


LOCAL = ["--base-url", "http://localhost:1234/v1", "--model", "qwen3"]


def test_main_update_report_applies_the_review(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    _review_run(monkeypatch, tmp_path)
    bitv = tmp_path / "bitv-report.json"
    before = _tested_report(bitv)
    assert lr.main([*LOCAL, "--out", str(tmp_path / "r.json"), "--update-report", str(bitv)]) == 0
    after = json.loads(bitv.read_text(encoding="utf-8"))
    steps = {s["step"]: s for s in after["steps"]}
    assert steps["9.2.4.4"]["review"]["by"] == "qwen3" and steps["9.2.4.4"]["review"]["counted"] is True
    assert after["review"]["method"] == "llm" and after["conformance"]["manual_review"] is True
    assert after["tested"] == before["tested"]
    assert {s["status_tests"] for s in after["steps"]} == {s["status"] for s in before["steps"]}


def test_main_update_report_leaves_the_report_alone_on_a_dry_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: Any) -> None:
    _review_run(monkeypatch, tmp_path)
    bitv = tmp_path / "bitv-report.json"
    _tested_report(bitv)
    text = bitv.read_text(encoding="utf-8")
    assert lr.main([*LOCAL, "--dry-run", "--out", str(tmp_path / "r.json"), "--update-report", str(bitv)]) == 0
    assert bitv.read_text(encoding="utf-8") == text
    assert "not changed" in capsys.readouterr().out


def test_main_update_report_from_results(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    from tests.a11y import results

    _review_run(monkeypatch, tmp_path)
    res = tmp_path / "a11y-results.json"
    res.write_text(json.dumps(results.build_results({}, {"langs": ["en", "de"], "pages": {"audit": "/v2/"}})), encoding="utf-8")
    bitv = tmp_path / "new.json"
    assert lr.main([*LOCAL, "--out", str(tmp_path / "r.json"), "--update-report", str(bitv), "--results", str(res)]) == 0
    assert json.loads(bitv.read_text(encoding="utf-8"))["review"]["model"] == "qwen3"
    with pytest.raises(SystemExit):
        lr.main([*LOCAL, "--results", str(res)])  # --results only with --update-report


# --------------------------------------------------------------------------- #
# in-page extraction against static HTML (needs Playwright + Chromium)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def chromium() -> Iterator[Any]:
    sync_api = pytest.importorskip("playwright.sync_api")
    pw = sync_api.sync_playwright().start()
    try:
        try:
            browser = pw.chromium.launch(executable_path=os.environ.get("EKTE_A11Y_CHROMIUM") or None)
        except Exception as exc:  # no browser installed
            pytest.skip(f"no Chromium for Playwright: {exc}")
        yield browser
        browser.close()
    finally:
        pw.stop()


HTML = """<!doctype html><html lang="en"><head><title>T</title><style>
.cta .blbl { display: none } .cta[aria-busy=true] .blbl { display: inline } .sr { position:absolute; width:1px; height:1px; overflow:hidden; clip: rect(0 0 0 0) }
</style></head><body><main id="main">
<button class="cta" id="go"><span class="lbl">Verify embedding endpoint</span><span class="blbl">Running checks…</span></button>
<p id="p1">Is this the real <b>thing</b>? Read the <a href="/tp">third party</a>.</p>
<p>Rerank<code>-check</code> runs <span style="visibility:hidden">secret</span>fast.</p>
<label for="q" class="sr">Query</label><input id="q" placeholder="Search">
<input id="ph" placeholder="Only a placeholder">
<label for="u">Relay URL</label><input id="u" placeholder="https://">
<p>历史只保存在本机。</p>
<dd>No webhooks<button type="button" style="display:inline-block">Edit</button></dd>
<button aria-expanded="false" class="rdel" aria-controls="c1">Delete entry</button><div id="c1" hidden>Really delete?</div>
<button aria-expanded="false" aria-controls="m1" class="more">More</button><div id="m1" hidden>More text here, a lot.</div>
<button aria-expanded="false" data-act="del">x</button>
<span id="d1">Relay URL</span><button aria-describedby="d1">Show key</button>
</main></body></html>"""


def test_extraction_uses_real_accessible_names(chromium: Any) -> None:
    page = chromium.new_page()
    try:
        page.set_content(HTML)
        raw = lr._extract(page)
        assert raw["names"] == "accessibility-tree"
        names = [c["name"] for c in raw["controls"]]
        # bug 3: hidden busy label not included
        assert "Verify embedding endpoint" in names
        show = next(c for c in raw["controls"] if c["name"] == "Show key")
        assert show["description"] == "Relay URL"
        rec = lr.compact_page(raw)
        texts = [i["text"] for i in rec["instructions"]]
        # bug 3: no spaces around inline elements, CSS-hidden text skipped
        assert "Is this the real thing? Read the third party." in texts
        assert "Rerank-check runs fast." in texts
        assert "No webhooks Edit" in texts  # an inline-block box is a word boundary
        assert "历史只保存在本机。" in texts  # bug 2: kept in the page payload
        assert "历史只保存在本机。" in lr.page_payload(rec)["instructions"]
        # bug 5: placeholder-only field vs. visually hidden label vs. visible label
        fields = {f.get("placeholder"): f for f in rec["fields"]}
        assert fields["Only a placeholder"]["name_from"] == "placeholder"
        assert "visible_label" not in fields["Only a placeholder"]
        assert fields["Search"]["name_from"] == "label" and "visible_label" not in fields["Search"]
        assert fields["https://"]["name_from"] == "label" and fields["https://"]["visible_label"] == "Relay URL"
        assert all(f.get("key") for f in rec["fields"])
    finally:
        page.close()


def test_expand_safe_leaves_destructive_disclosures_closed(chromium: Any) -> None:
    page = chromium.new_page()
    try:
        page.set_content(HTML)
        opened, skipped = page.evaluate(lr.EXPAND_SAFE_JS, lr.DESTRUCTIVE)
        assert (opened, skipped) == (1, 2)
        assert page.get_attribute(".rdel", "aria-expanded") == "false"
    finally:
        page.close()
