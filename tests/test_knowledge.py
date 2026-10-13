"""Tests for knowledge-base loading and model-id resolution."""

from __future__ import annotations

from zing.knowledge import KnowledgeBase, load_knowledge_base
from zing.knowledge.schema import (
    FingerprintProbe,
    ModelProfile,
    ProviderProfile,
    ResolvedProfile,
    _normalize,
)


# --------------------------------------------------------------------------- #
# loading
# --------------------------------------------------------------------------- #
def test_c_yaml_loader_matches_pure_python_for_packaged_profiles():
    # The loader prefers libyaml's CSafeLoader; it must yield exactly the data
    # the pure-Python SafeLoader does for every shipped profile.
    from importlib import resources

    import pytest
    import yaml

    from zing.utils import yamlio

    if not hasattr(yaml, "CSafeLoader"):
        pytest.skip("PyYAML built without libyaml")
    assert yamlio.SAFE_LOADER is yaml.CSafeLoader
    files = [e for e in resources.files("zing.knowledge.data").iterdir()
             if e.name.endswith((".yaml", ".yml"))]
    assert files
    for entry in files:
        text = entry.read_text(encoding="utf-8")
        assert yaml.load(text, Loader=yaml.CSafeLoader) == yaml.load(text, Loader=yaml.SafeLoader), entry.name


def test_cached_knowledge_base_is_a_private_copy():
    first = load_knowledge_base()
    first.providers["openai"].models.clear()
    first.providers["openai"].fingerprints.clear()
    first.warnings.append("mutated")
    del first.providers["anthropic"]
    second = load_knowledge_base()
    assert second is not first
    assert second.providers["openai"].models and "anthropic" in second.providers
    assert "mutated" not in second.warnings


def test_kb_dir_edit_invalidates_cache(tmp_path, monkeypatch):
    monkeypatch.delenv("ZING_KB_DIR", raising=False)
    path = tmp_path / "acme.yaml"
    path.write_text("provider: acmeai\nmodels:\n- id: acme-one\n", encoding="utf-8")
    kb = load_knowledge_base([tmp_path])
    assert kb.resolve("acme-one") is not None
    path.write_text("provider: acmeai\nmodels:\n- id: acme-two-longer\n", encoding="utf-8")
    kb = load_knowledge_base([tmp_path])
    assert kb.resolve("acme-two-longer") is not None
    assert [m.id for m in kb.providers["acmeai"].models] == ["acme-two-longer"]
    path.unlink()
    assert "acmeai" not in load_knowledge_base([tmp_path]).providers
    monkeypatch.setenv("ZING_KB_DIR", str(tmp_path))
    (tmp_path / "beta.yaml").write_text("provider: betaai\nmodels: []\n", encoding="utf-8")
    assert "betaai" in load_knowledge_base().providers


def test_load_knowledge_base_has_providers(knowledge_base):
    assert isinstance(knowledge_base, KnowledgeBase)
    assert knowledge_base.providers, "expected packaged provider profiles"
    # Spot-check a couple of well-known providers ship with the package.
    assert "openai" in knowledge_base.providers
    assert "anthropic" in knowledge_base.providers


def test_load_knowledge_base_is_callable_fresh():
    kb = load_knowledge_base()
    assert kb.providers
    # all_models flattens (provider, model) pairs.
    pairs = kb.all_models()
    assert pairs
    assert all(isinstance(p, ProviderProfile) and isinstance(m, ModelProfile) for p, m in pairs)


# --------------------------------------------------------------------------- #
# _normalize
# --------------------------------------------------------------------------- #
def test_normalize_strips_separators_and_lowercases():
    assert _normalize("GPT-4o") == "gpt4o"
    assert _normalize("Claude 3.5 Sonnet") == "claude35sonnet"
    assert _normalize("deepseek_chat") == "deepseekchat"
    assert _normalize("") == ""


# --------------------------------------------------------------------------- #
# resolve — against a small synthetic KB (deterministic, independent of data) #
# --------------------------------------------------------------------------- #
def _synthetic_kb() -> KnowledgeBase:
    model = ModelProfile(
        id="acme-large",
        aliases=["acme-l", "acme-large-2024-01-01"],
        family="acme",
        context_window_tokens=128000,
        max_output_tokens=4096,
    )
    other = ModelProfile(id="acme-small", aliases=["acme-s"])
    provider = ProviderProfile(provider="acme", models=[model, other])
    return KnowledgeBase(providers={"acme": provider})


def test_resolve_exact_id():
    kb = _synthetic_kb()
    r = kb.resolve("acme-large")
    assert isinstance(r, ResolvedProfile)
    assert r.model.id == "acme-large"
    assert r.match_confidence == "exact"


def test_resolve_alias():
    kb = _synthetic_kb()
    r = kb.resolve("acme-l")
    assert r is not None
    assert r.model.id == "acme-large"
    assert r.match_confidence == "alias"


def test_resolve_normalized_exact_treated_as_alias():
    kb = _synthetic_kb()
    # Different casing/separators of an exact id resolve via the normalized path.
    r = kb.resolve("ACME_LARGE")
    assert r is not None
    assert r.model.id == "acme-large"
    assert r.match_confidence == "alias"


def test_resolve_fuzzy_substring():
    kb = _synthetic_kb()
    # A relay-decorated id that is a superset of the real id -> fuzzy match.
    r = kb.resolve("relay-acme-large-turbo")
    assert r is not None
    assert r.model.id == "acme-large"
    assert r.match_confidence == "fuzzy"


def test_resolve_unknown_returns_none():
    kb = _synthetic_kb()
    assert kb.resolve("totally-unrelated-xyz") is None


def test_resolve_empty_returns_none():
    kb = _synthetic_kb()
    assert kb.resolve("") is None


def test_resolve_provider_hint_narrows():
    other = ProviderProfile(
        provider="globex", models=[ModelProfile(id="acme-large", aliases=[])]
    )
    base = _synthetic_kb()
    base.providers["globex"] = other
    r = base.resolve("acme-large", provider_hint="globex")
    assert r is not None
    assert r.provider.provider == "globex"


# --------------------------------------------------------------------------- #
# resolve — against the real packaged KB
# --------------------------------------------------------------------------- #
def test_resolve_real_known_model(knowledge_base):
    r = knowledge_base.resolve("gpt-4o")
    assert r is not None
    assert r.model.id == "gpt-4o"
    assert r.provider.provider == "openai"
    assert r.match_confidence == "exact"
    # Native specs are populated for a known model.
    assert r.model.context_window_tokens > 0


def _tier_kb() -> KnowledgeBase:
    models = [
        ModelProfile(id="acme-4o"),
        ModelProfile(id="acme-4o-mini"),
        ModelProfile(id="acme-4.1"),
        ModelProfile(id="acme-3-pro-20250101", aliases=["acme-3-pro-latest"]),
        ModelProfile(id="o3"),
    ]
    return KnowledgeBase(providers={"acme": ProviderProfile(provider="acme", models=models)})


def test_resolve_fuzzy_contained_name_prefers_longest():
    kb = _tier_kb()
    # A suffixed/snapshot claim keeps the longest KB name it contains.
    r = kb.resolve("acme-4o-mini-2099-01-01-custom")
    assert r is not None and r.model.id == "acme-4o-mini" and r.match_confidence == "fuzzy"
    r = kb.resolve("vendor/acme-4o-2099-01-01")
    assert r is not None and r.model.id == "acme-4o" and r.match_confidence == "fuzzy"


def test_resolve_fuzzy_short_claim_does_not_pick_a_longer_tier():
    kb = _tier_kb()
    # "acme-4" is contained in acme-4o, acme-4o-mini and acme-4.1: ambiguous,
    # so no profile rather than a guessed (often cheaper) tier.
    assert kb.resolve("acme-4") is None
    assert kb.resolve("acme") is None
    # A shorter claim that only one model extends still resolves (fuzzy).
    r = kb.resolve("acme-3-pro")
    assert r is not None and r.model.id == "acme-3-pro-20250101" and r.match_confidence == "fuzzy"


def test_resolve_fuzzy_needs_a_token_boundary():
    kb = _tier_kb()
    # "o3" occurs inside "pro3" but not where a token of the claim starts.
    assert kb.resolve("acme-pro3") is None
    r = kb.resolve("o3-2099-01-01")
    assert r is not None and r.model.id == "o3"


def test_resolve_fuzzy_tie_between_models_is_ambiguous():
    models = [ModelProfile(id="acme-x1"), ModelProfile(id="acme-y1")]
    kb = KnowledgeBase(providers={"acme": ProviderProfile(provider="acme", models=models)})
    # Both names are contained, equally long: refuse to guess.
    assert kb.resolve("acme-x1-acme-y1") is None


def test_resolve_real_short_claims_are_not_assigned_a_tier(knowledge_base):
    for claim in ["gpt-4", "gpt", "claude", "gemini", "gemini-2.5", "deepseek", "qwen", "qwen3", "glm-4", "kimi"]:
        assert knowledge_base.resolve(claim) is None, claim


def test_resolve_real_decorated_ids_still_match(knowledge_base):
    cases = {
        "gpt-4o-2024-11-20-custom": "gpt-4o",
        "openai/gpt-4o": "gpt-4o",
        "models/gemini-2.5-pro": "gemini-2.5-pro",
        "gemini-2.5-flash-preview-05-20": "gemini-2.5-flash",
        "gemini-2.0-flash-001": "gemini-2.0-flash",
        "deepseek-chat-v3": "deepseek-chat",
    }
    for claim, expected in cases.items():
        r = knowledge_base.resolve(claim)
        assert r is not None and r.model.id == expected and r.match_confidence == "fuzzy", claim


# --------------------------------------------------------------------------- #
# ResolvedProfile.all_fingerprints
# --------------------------------------------------------------------------- #
def test_all_fingerprints_merges_provider_and_model():
    provider = ProviderProfile(
        provider="acme",
        fingerprints=[FingerprintProbe(id="p1", signal="s", prompt="q")],
        models=[
            ModelProfile(
                id="acme-large",
                fingerprints=[FingerprintProbe(id="m1", signal="s", prompt="q")],
            )
        ],
    )
    resolved = ResolvedProfile(provider=provider, model=provider.models[0])
    ids = [fp.id for fp in resolved.all_fingerprints()]
    assert ids == ["p1", "m1"]


def test_no_fingerprint_contradicts_the_models_own_cutoff(knowledge_base):
    # A probe applied to a model must not reject that model's own documented
    # knowledge cutoff, nor demand a different YYYY-MM.
    import re

    for provider, model in knowledge_base.all_models():
        cutoff = re.match(r"\d{4}-\d{2}", model.knowledge_cutoff or "")
        if not cutoff:
            continue
        own = cutoff.group(0)
        for fp in ResolvedProfile(provider=provider, model=model).all_fingerprints():
            where = f"{provider.provider}/{model.id}: {fp.id}"
            assert not any(own in s for s in fp.expect_not_contains), where
            for s in fp.expect_contains:
                if re.fullmatch(r"\d{4}-\d{2}", s):
                    assert s == own, where


def test_gemini_tier_probes_are_scoped_to_their_models(knowledge_base):
    def probes(model_id: str) -> set[str]:
        r = knowledge_base.resolve(model_id)
        assert r is not None and r.match_confidence == "exact"
        return {fp.id for fp in r.all_fingerprints()}

    # gemini-2.0-flash's own cutoff is 2024-08 and it is not a reasoning model.
    assert {"knowledge-cutoff", "factual-recall-pro-size", "reasoning-trap-bat-ball"}.isdisjoint(
        probes("gemini-2.0-flash")
    )
    for flash in ["gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-3-flash-preview"]:
        ids = probes(flash)
        assert "knowledge-cutoff" in ids and "factual-recall-pro-size" not in ids, flash
    for pro in ["gemini-2.5-pro", "gemini-3-pro-preview", "gemini-3.1-pro-preview"]:
        assert {"knowledge-cutoff", "factual-recall-pro-size"} <= probes(pro), pro


def test_moonshot_cutoff_probe_skips_legacy_v1_models(knowledge_base):
    legacy = knowledge_base.resolve("moonshot-v1-8k")
    assert legacy is not None
    assert "knowledge-cutoff" not in {fp.id for fp in legacy.all_fingerprints()}
    k2 = knowledge_base.resolve("kimi-k2.6")
    assert k2 is not None
    assert "knowledge-cutoff" in {fp.id for fp in k2.all_fingerprints()}


def test_performance_reference_ranges():
    import pytest
    from pydantic import ValidationError

    from zing.knowledge.schema import ModelProfile, PerformanceReference

    ref = PerformanceReference(decode_tps=[40, 120], ttft_ms=[300, 1500], source="x")
    assert ref.decode_tps == (40.0, 120.0)
    assert ModelProfile(id="m", performance={"decode_tps": [10, 20]}).performance is not None
    assert ModelProfile(id="m").performance is None  # optional: old entries stay valid
    for bad in ([120, 40], [0, 10]):
        with pytest.raises(ValidationError):
            PerformanceReference(decode_tps=bad)


def test_bundled_performance_references_load():
    from zing.knowledge import load_knowledge_base

    kb = load_knowledge_base(None, include_user=False)
    refs = [m.performance for _, m in kb.all_models() if m.performance]
    assert refs and all(r.decode_tps and r.source for r in refs)
