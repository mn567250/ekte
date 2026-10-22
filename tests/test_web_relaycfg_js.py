"""Pure helpers of the v2 relay configuration (zing/web/static/v2/relaycfg.js),
evaluated under node. The DOM flow itself is covered by the browser suite
(tests/a11y/test_flows.py)."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_JS = r"""
global.window = {};
require(process.argv[1]);
const H = window.ZingRelayConfig._;
const kb = [
  { provider: "openai", display_name: "OpenAI", base_urls: ["https://api.openai.com/v1"], relay: false,
    models: [{ id: "gpt-4o", aliases: [], kind: "chat" }, { id: "text-embedding-3-small", aliases: [], kind: "embedding" }] },
  { provider: "deepseek", display_name: "DeepSeek (DeepSeek-AI / Hangzhou)", relay: false,
    base_urls: ["https://api.deepseek.com", "https://api.deepseek.com/anthropic"], models: [{ id: "deepseek-chat", aliases: [] }] },
  { provider: "my-relay", display_name: "My Relay", base_urls: ["https://relay.example/v1"], relay: true, models: [] },
  { provider: "nourl", display_name: "No URL", base_urls: [], relay: false, models: [{ id: "x", aliases: [], kind: "chat" }] },
];
const g = H.relayGroups(kb);
console.log(JSON.stringify({
  norm: ["https://api.anthropic.com/v1/messages", "http://h:1/v1/", "api.openai.com", " https://x.example/v1/chat/completions?a=1 "].map(H.normUrl),
  groups: { providers: g.providers.map(p => p.provider), relays: g.relays.map(p => p.provider) },
  match: ["https://api.deepseek.com/anthropic/", "https://relay.example/v1/chat/completions", "https://nope.example", ""]
    .map(u => (H.matchRelay(u, kb) || {}).provider || null),
  chat: H.claimedGroups(kb, "chat").map(x => [x.provider, x.models.map(m => m.id)]),
  embedding: H.claimedGroups(kb, "embedding").map(x => [x.provider, x.models.map(m => m.id)]),
  rerank: H.claimedGroups(kb, "rerank").map(x => [x.provider, x.models.map(m => m.id)]),
  states: [
    { ok: true, models: ["a", "b"] }, { ok: true, models: [] }, { ok: false, status_code: 401, error: "no" },
    { ok: false, status_code: 403 }, { ok: false, status_code: 500, error: "boom" }, { ok: false, error: "timeout" }, null,
  ].map(H.fetchState),
  short: H.shortName("DeepSeek (DeepSeek-AI / Hangzhou)"),
}));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_relaycfg_helpers():
    src = Path(__file__).resolve().parent.parent / "zing" / "web" / "static" / "v2" / "relaycfg.js"
    out = json.loads(subprocess.run(["node", "-e", _JS, str(src)], capture_output=True, text=True, check=True).stdout)
    assert out["norm"] == ["https://api.anthropic.com/v1", "http://h:1/v1", "", "https://x.example/v1"]
    # providers with base URLs, then the user's relays; one without a URL is left out
    assert out["groups"] == {"providers": ["openai", "deepseek"], "relays": ["my-relay"]}
    assert out["match"] == ["deepseek", "my-relay", None, None]
    # claimed models by kind (a model without kind is a chat model); relays have none
    assert out["chat"] == [["openai", ["gpt-4o"]], ["deepseek", ["deepseek-chat"]], ["nourl", ["x"]]]
    assert out["embedding"] == [["openai", ["text-embedding-3-small"]]]
    # rerank models are never offered as chat ones (this knowledge base has none)
    assert out["rerank"] == []
    assert out["states"] == [
        {"kind": "ok", "count": 2},
        {"kind": "empty", "count": 0},
        {"kind": "auth", "code": 401},
        {"kind": "auth", "code": 403},
        {"kind": "error", "message": "HTTP 500: boom"},
        {"kind": "error", "message": "timeout"},
        {"kind": "error", "message": "?"},
    ]
    assert out["short"] == "DeepSeek"
