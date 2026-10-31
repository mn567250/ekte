"""The monitors' master key UI (ekte/web/static/v2/masterkey.js), evaluated under node."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_JS = r"""
const path = require("path");
global.window = { addEventListener() {}, dispatchEvent() {} };
global.Event = function (t) { this.type = t; };
require(path.join(process.argv[1], "masterkey.js"));
const M = window.EkteMasterKey;
const out = {};

out.decide = [
  { state: "uninitialized", actions: ["new"] },
  { state: "locked", actions: ["unlock", "reset"] },
  { state: "unlocked", actions: ["new", "lock"] },
  { state: "env_mismatch", actions: [] },
  null,
].map(M.decide);

const stored = [];
window.PasswordCredential = function (c) { Object.assign(this, c); };
Object.defineProperty(globalThis, "navigator", { configurable: true, value: {
  credentials: { store: c => { stored.push({ id: c.id, name: c.name, password: c.password }); return Promise.resolve(); } } } });

// withKey(doFetch, ask): a 423 asks for the key (the dialogs, stubbed here),
// then retries exactly once; without a 423 nothing is asked.
function run(statuses, answer) {
  let calls = 0, asked = 0;
  const doFetch = () => Promise.resolve({ status: statuses[Math.min(calls++, statuses.length - 1)] });
  const ask = () => { asked++; return Promise.resolve(answer); };
  return M.withKey(doFetch, ask).then(r => [r.status, calls, asked]);
}
(async () => {
  await M.storeCredential("k-123");
  await M.storeCredential("");  // nothing to store
  out.stored = stored;
  out.plain = await run([200], true);
  out.unlocked = await run([423, 200], true);
  out.cancelled = await run([423, 200], false);
  out.stillLocked = await run([423, 423], true);
  console.log(JSON.stringify(out));
})();
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node to evaluate the UI's JS")
def test_masterkey_logic_and_vault_storage():
    static = Path(__file__).resolve().parent.parent / "ekte" / "web" / "static" / "v2"
    out = json.loads(subprocess.run(
        ["node", "-e", _JS, str(static)], capture_output=True, text=True, encoding="utf-8", check=True,
    ).stdout)
    # A missing key opens setup, a locked one the unlock dialog; otherwise nothing.
    assert out["decide"] == ["setup", "unlock", None, None, None]
    # The browser vault gets one entry under a fixed username, and only for a key.
    assert out["stored"] == [{"id": "ekte-master-key", "name": "ekte master key", "password": "k-123"}]
    # [final status, requests made, dialogs opened]
    assert out["plain"] == [200, 1, 0]
    assert out["unlocked"] == [200, 2, 1]
    assert out["cancelled"] == [423, 1, 1]  # the user closed the dialog: no retry
    assert out["stillLocked"] == [423, 2, 1]  # retried once, never loops
