"""Per-run probes (#256): every needle, canary and cache prefix is derived from
the run's nonce, so two audits of the same target send different probes while
one audit stays internally consistent, and a replay reuses the recorded nonce."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from types import SimpleNamespace

import pytest

from ekte import evidence, replay
from ekte.context import RUN_NONCE_ENV, new_run_nonce
from ekte.detectors.helpers import build_filler, stable_marker
from ekte.detectors.integrity import is_bech32_address, wallet_address
from ekte.utils.tokenize import estimate_tokens
from tests.test_replay import _record

# The detectors whose probes carry a per-run value.
PER_RUN = ("connectivity", "security", "context_window", "prompt_cache", "integrity")


def test_marker_is_stable_within_a_run_and_differs_across_runs():
    assert stable_marker("connectivity", "a" * 16) == stable_marker("connectivity", "a" * 16)
    assert stable_marker("connectivity", "a" * 16) != stable_marker("connectivity", "b" * 16)
    assert stable_marker("cache-a", "a" * 16) != stable_marker("cache-b", "a" * 16)
    assert re.fullmatch(r"EKTE-[0-9A-F]{10}", stable_marker("security", "c" * 16))


def test_empty_nonce_gives_the_markers_of_runs_before_the_nonce():
    """A replay of a run recorded before #256 sends the fixed markers it sent."""
    legacy = "EKTE-" + hashlib.sha256(b"connectivity").hexdigest()[:10].upper()
    assert stable_marker("connectivity", "") == legacy


def test_filler_varies_per_run_at_practically_the_same_token_count():
    base = build_filler(4000, None)
    one, two = build_filler(4000, None, "a" * 16), build_filler(4000, None, "b" * 16)
    assert len({base, one, two}) == 3
    assert build_filler(4000, None, "") == base  # the pre-nonce filler
    counts = [estimate_tokens(t) for t in (base, one, two)]
    assert max(counts) - min(counts) <= max(counts) * 0.02
    # still numbered, five digits per line
    assert all(re.match(r"\[\d{5}\] ", line) for line in one.split("\n"))


def test_filler_is_memoized_per_nonce():
    build_filler.cache_clear()
    first = build_filler(3000, None, "d" * 16)
    assert build_filler(3000, None, "d" * 16) is first


def test_wallet_address_comes_from_the_nonce():
    target = SimpleNamespace(base_url="https://relay.example/v1", model="m", claimed_model=None)
    a = wallet_address(SimpleNamespace(target=target, run_nonce="a" * 16))
    b = wallet_address(SimpleNamespace(target=target, run_nonce="b" * 16))
    assert a != b and is_bech32_address(a) and is_bech32_address(b)
    assert a == wallet_address(SimpleNamespace(target=target, run_nonce="a" * 16))
    # no nonce (the replay of an older run): derived from the endpoint, as then
    legacy = wallet_address(SimpleNamespace(target=target, run_nonce=""))
    assert is_bech32_address(legacy) and legacy == wallet_address(SimpleNamespace(target=target))


def test_new_run_nonce_is_random_unless_fixed(monkeypatch):
    monkeypatch.delenv(RUN_NONCE_ENV, raising=False)
    a, b = new_run_nonce(), new_run_nonce()
    assert a != b and re.fullmatch(r"[0-9a-f]{16}", a)
    monkeypatch.setenv(RUN_NONCE_ENV, " fixed-nonce ")
    assert new_run_nonce() == "fixed-nonce"


def _bodies(path) -> dict[str, list[str]]:
    """The request bodies each per-run detector sent, in order."""
    out: dict[str, list[str]] = {d: [] for d in PER_RUN}
    for x in evidence.exchanges(path):
        if x["detector"] in out:
            out[x["detector"]].append((x["request"].get("body") or {}).get("text") or "")
    return out


def _user_texts(bodies: list[str]) -> list[str]:
    texts = []
    for body in bodies:
        if not body.startswith("{"):
            continue  # a GET (connectivity's /models) has no body
        for m in json.loads(body).get("messages") or []:
            if isinstance(m.get("content"), str):
                texts.append(m["content"])
    return texts


@pytest.fixture
def two_runs(tmp_path, monkeypatch):
    monkeypatch.delenv(RUN_NONCE_ENV, raising=False)
    first, second = tmp_path / "a.jsonl.zst", tmp_path / "b.jsonl.zst"
    return (_record(monkeypatch, first, suite="deep"), first), (_record(monkeypatch, second, suite="deep"), second)


def test_two_audits_send_different_needles_canaries_and_cache_prefixes(two_runs):
    (r1, p1), (r2, p2) = two_runs
    assert r1["run_nonce"] and r2["run_nonce"] and r1["run_nonce"] != r2["run_nonce"]
    # the evidence header records it too
    assert evidence.header(p1)["run_nonce"] == r1["run_nonce"]
    b1, b2 = _bodies(p1), _bodies(p2)
    for det in PER_RUN:
        assert _user_texts(b1[det]), f"{det} sent no prompt"
    for det in ("connectivity", "security", "context_window", "prompt_cache"):
        assert not set(_user_texts(b1[det])) & set(_user_texts(b2[det])), det
    # integrity: the fixed canaries stay, the wallet address is per run
    wallet = re.compile(r"\bbc1[0-9a-z]{20,}\b")
    w1 = {m for t in _user_texts(b1["integrity"]) for m in wallet.findall(t)}
    w2 = {m for t in _user_texts(b2["integrity"]) for m in wallet.findall(t)}
    assert w1 and w2 and not w1 & w2


def test_one_audit_is_internally_consistent(two_runs):
    (report, path), _ = two_runs
    nonce = report["run_nonce"]
    texts = _user_texts(_bodies(path)["prompt_cache"])
    # cold and warm send the same prefix; the control another one
    assert texts[0] == texts[1] != texts[2]
    assert texts[0].startswith(stable_marker("cache-a", nonce) + "\n")
    assert texts[2].startswith(stable_marker("cache-b", nonce) + "\n")
    assert stable_marker("connectivity", nonce) in _user_texts(_bodies(path)["connectivity"])[0]


def test_a_fixed_nonce_sends_identical_probes(tmp_path, monkeypatch):
    monkeypatch.setenv(RUN_NONCE_ENV, "0123456789abcdef")
    p1, p2 = tmp_path / "a.jsonl.zst", tmp_path / "b.jsonl.zst"
    r1, r2 = _record(monkeypatch, p1), _record(monkeypatch, p2)
    assert r1["run_nonce"] == r2["run_nonce"] == "0123456789abcdef"
    assert _bodies(p1) == _bodies(p2)


def test_a_replay_reuses_the_recorded_nonce(tmp_path, monkeypatch):
    monkeypatch.delenv(RUN_NONCE_ENV, raising=False)
    path = tmp_path / "e.jsonl.zst"
    before = _record(monkeypatch, path, suite="deep")
    # a fixed nonce in the environment does not override the recorded one
    monkeypatch.setenv(RUN_NONCE_ENV, "ffffffffffffffff")
    after = json.loads(asyncio.run(replay.rescore(before, path)).model_dump_json())
    assert after["run_nonce"] == before["run_nonce"]
    assert after["rescored_from"]["missing"] == {}
    # the header alone (a report without the field) is enough
    report = dict(before)
    report.pop("run_nonce")
    assert replay.recorded_nonce(report, evidence.header(path)) == before["run_nonce"]


def test_a_run_from_before_the_nonce_replays_with_the_fixed_probes():
    assert replay.recorded_nonce({}, {"type": "header"}) == ""
    assert replay.recorded_nonce({"run_nonce": None}, {"run_nonce": None}) == ""
