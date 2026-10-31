"""Pure helpers of the v2 Knowledge page (ekte/web/static/v2/kbview.js),
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
const V = window.EkteKbView._;
const models = [
  { key: "model:openai/gpt-4o", id: "gpt-4o", provider: "openai", provider_name: "OpenAI", aliases: ["gpt-4o-2024-08-06"],
    enabled: true, yours: false, source: "packaged:openai.yaml" },
  { key: "model:acme/acme-large", id: "acme-large", provider: "acme", provider_name: "Acme AI", aliases: [],
    enabled: false, yours: true, source: "kb.db:entry/2" },
  { key: "model:openai/gpt-4o-mini", id: "gpt-4o-mini", provider: "openai", provider_name: "OpenAI", aliases: [],
    enabled: false, yours: false, source: "packaged:openai.yaml" },
];
const providers = [
  { key: "provider:openai", provider: "openai", display_name: "OpenAI", source: "packaged:openai.yaml" },
  { key: "provider:acme", provider: "acme", display_name: "Acme AI", source: "kb.db:entry/2" },
  { key: "entry:5", provider: "openai", display_name: "OpenAI", addition: true, source: "kb.db:entry/5" },
];
const relays = [
  { key: "provider:my-relay", provider: "my-relay", display_name: "My Relay", base_urls: ["https://relay.example/v1"],
    source: "kb.db:entry/7" },
];
const keys = (xs) => xs.map((x) => x.key);
console.log(JSON.stringify({
  kinds: ["kb.db:entry/3", "kb_dir:/srv/kb/x.yaml", "packaged:openai.yaml", "", null].map(V.sourceKind),
  files: ["kb.db:entry/3", "kb_dir:/srv/kb/x.yaml", "packaged:openai.yaml"].map(V.sourceFile),
  modelProvider: [V.modelProvider("model:openai/gpt-4o"), V.modelProvider("model:x/a/b"), V.modelProvider("provider:x")],
  all: keys(models.filter((m) => V.matches("models", m, {}))),
  byModel: keys(models.filter((m) => V.matches("models", m, { model: "model:openai/gpt-4o" }))),
  byProvider: keys(models.filter((m) => V.matches("models", m, { provider: "openai" }))),
  bySource: keys(models.filter((m) => V.matches("models", m, { source: "yours" }))),
  provByModel: keys(providers.filter((p) => V.matches("providers", p, { model: "model:acme/acme-large" }))),
  relayKept: keys(relays.filter((r) => V.matches("relays", r, { model: "model:openai/gpt-4o", provider: "openai" }))),
  relayPicked: keys(relays.filter((r) => V.matches("relays", r, { relay: "provider:other" }))),
  active: [V.active({}), V.active({ model: "m", source: "yours", relay: "" })],
  options: V.options({ models: models, providers: providers, relays: relays }, { provider: "acme" }),
  groups: V.groups(models, "provider").map((g) => [g.key, keys(g.items)]),
  summary: V.summary(models),
  itemsOf: [V.itemsOf({ relays: relays }, "relays").length, V.itemsOf(null, "models").length, V.itemsOf({}, "x").length],
}));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_kbview_helpers():
    src = Path(__file__).resolve().parent.parent / "ekte" / "web" / "static" / "v2" / "kbview.js"
    out = json.loads(subprocess.run(["node", "-e", _JS, str(src)], capture_output=True, text=True, encoding="utf-8", check=True).stdout)
    assert out["kinds"] == ["yours", "kbdir", "packaged", "packaged", "packaged"]
    assert out["files"] == ["#3", "/srv/kb/x.yaml", "openai.yaml"]
    assert out["modelProvider"] == ["openai", "x", ""]
    assert out["all"] == ["model:openai/gpt-4o", "model:acme/acme-large", "model:openai/gpt-4o-mini"]
    assert out["byModel"] == ["model:openai/gpt-4o"]
    assert out["byProvider"] == ["model:openai/gpt-4o", "model:openai/gpt-4o-mini"]
    assert out["bySource"] == ["model:acme/acme-large"]
    # a model id narrows the providers to its own
    assert out["provByModel"] == ["provider:acme"]
    # relays have no model or provider field: those filters leave them alone
    assert out["relayKept"] == ["provider:my-relay"]
    assert out["relayPicked"] == []
    assert out["active"] == [0, 2]
    # only existing values; the model ids follow the provider; providers once
    assert out["options"] == {
        "models": [{"v": "model:acme/acme-large", "t": "acme-large", "group": "Acme AI"}],
        "providers": [{"v": "openai", "t": "OpenAI"}, {"v": "acme", "t": "Acme AI"}],
        "relays": [{"v": "provider:my-relay", "t": "My Relay"}],
        "sources": ["packaged", "yours"],
    }
    # groups keep first-seen order
    assert out["groups"] == [
        ["openai", ["model:openai/gpt-4o", "model:openai/gpt-4o-mini"]],
        ["acme", ["model:acme/acme-large"]],
    ]
    assert out["summary"] == {"total": 3, "yours": 1, "off": 2}
    assert out["itemsOf"] == [1, 0, 0]
