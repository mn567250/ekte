"""Pure helpers of the v2 Knowledge page (zing/web/static/v2/kbview.js),
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
const V = window.ZingKbView._;
const models = [
  { key: "model:openai/gpt-4o", id: "gpt-4o", provider: "openai", provider_name: "OpenAI", aliases: ["gpt-4o-2024-08-06"],
    enabled: true, yours: false },
  { key: "model:acme/acme-large", id: "acme-large", provider: "acme", provider_name: "Acme AI", aliases: [],
    enabled: false, yours: true },
  { key: "model:openai/gpt-4o-mini", id: "gpt-4o-mini", provider: "openai", provider_name: "OpenAI", aliases: [],
    enabled: false, yours: false },
];
const relays = [
  { key: "provider:my-relay", provider: "my-relay", display_name: "My Relay", base_urls: ["https://relay.example/v1"] },
];
const keys = (xs) => xs.map((x) => x.key);
console.log(JSON.stringify({
  kinds: ["kb.db:entry/3", "kb_dir:/srv/kb/x.yaml", "packaged:openai.yaml", "", null].map(V.sourceKind),
  files: ["kb.db:entry/3", "kb_dir:/srv/kb/x.yaml", "packaged:openai.yaml"].map(V.sourceFile),
  all: keys(V.filter("models", models, "  ")),
  alias: keys(V.filter("models", models, "2024-08")),
  words: keys(V.filter("models", models, "OPENAI mini")),
  byProvider: keys(V.filter("models", models, "acme ai")),
  none: keys(V.filter("models", models, "zzz")),
  relayUrl: keys(V.filter("relays", relays, "relay.example")),
  groups: V.groups(models, "provider").map((g) => [g.key, keys(g.items)]),
  summary: V.summary(models),
  itemsOf: [V.itemsOf({ relays: relays }, "relays").length, V.itemsOf(null, "models").length, V.itemsOf({}, "x").length],
}));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_kbview_helpers():
    src = Path(__file__).resolve().parent.parent / "zing" / "web" / "static" / "v2" / "kbview.js"
    out = json.loads(subprocess.run(["node", "-e", _JS, str(src)], capture_output=True, text=True, check=True).stdout)
    assert out["kinds"] == ["yours", "kbdir", "packaged", "packaged", "packaged"]
    assert out["files"] == ["#3", "/srv/kb/x.yaml", "openai.yaml"]
    assert out["all"] == ["model:openai/gpt-4o", "model:acme/acme-large", "model:openai/gpt-4o-mini"]
    # aliases, the provider's key and name are searched; every word must match
    assert out["alias"] == ["model:openai/gpt-4o"]
    assert out["words"] == ["model:openai/gpt-4o-mini"]
    assert out["byProvider"] == ["model:acme/acme-large"]
    assert out["none"] == []
    assert out["relayUrl"] == ["provider:my-relay"]
    # groups keep first-seen order
    assert out["groups"] == [
        ["openai", ["model:openai/gpt-4o", "model:openai/gpt-4o-mini"]],
        ["acme", ["model:acme/acme-large"]],
    ]
    assert out["summary"] == {"total": 3, "yours": 1, "off": 2}
    assert out["itemsOf"] == [1, 0, 0]
