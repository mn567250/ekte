"""The masked API key fields (ekte/web/static/secretfield.js), evaluated under node."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_JS = r"""
const path = require("path");
global.window = {};
global.document = undefined;  // no DOM: loading must not touch it
require(path.join(process.argv[1], "secretfield.js"));
const S = window.EkteSecret;
const refs = ["env:EKTE_API_KEY", " FILE:/run/secrets/k", "sk-abc", "", null, "envy:x"].map(S.isReference);

// remember(): a minimal form with a literal key, a reference and an orphan key.
const input = (value, secret) => ({ value, type: "text", getAttribute: () => secret });
const urls = { "i-url": { value: " https://relay.test/v1 " }, "b-url": { value: "https://api.test/v1" } };
global.document = { getElementById: id => urls[id] || null };
const target = input("sk-target", "i-url"), ref = input("env:OPENAI_API_KEY", "b-url"),
      baseline = input(" sk-base ", "b-url"), orphan = input("sk-orphan", "nope");
const form = { querySelectorAll: () => [target, ref, baseline, orphan] };
const stored = [];
window.PasswordCredential = function (c) { this.id = c.id; this.password = c.password; };
Object.defineProperty(globalThis, "navigator", { configurable: true, value: {
  credentials: { store: c => { stored.push({ id: c.id, password: c.password }); return Promise.resolve(); } } } });
S.remember(form);
setTimeout(() => console.log(JSON.stringify({
  refs, stored, types: [target.type, ref.type, baseline.type, orphan.type] })), 0);
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_secretfield_references_and_vault_storage():
    static = Path(__file__).resolve().parent.parent / "ekte" / "web" / "static"
    out = json.loads(subprocess.run(
        ["node", "-e", _JS, str(static)], capture_output=True, text=True, check=True,
    ).stdout)
    # env:/file: references aren't secrets; everything else is.
    assert out["refs"] == [True, True, False, False, False, False]
    # Literal keys are stored under their relay URL, one after the other;
    # references and keys without a URL never reach the password manager.
    assert out["stored"] == [
        {"id": "https://relay.test/v1", "password": "sk-target"},
        {"id": "https://api.test/v1", "password": "sk-base"},
    ]
    # Literal keys are re-masked after a run; references are left as they are.
    assert out["types"] == ["password", "text", "password", "password"]
