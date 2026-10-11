"""The user's own knowledge base (kb.db): layering, import checks, snapshots.

No network: audits use the mock relay from conftest; the web parts are skipped
without the optional fastapi extra.
"""

from __future__ import annotations

import json
import re

import pytest

from zing.knowledge import load_knowledge_base, store
from zing.knowledge.importer import export_yaml, import_yaml, scan
from zing.knowledge.research import research_prompt
from zing.knowledge.snapshot import content_hash, knowledge_usage, resolved_from_snapshot, snapshot

NEW_PROVIDER_YAML = """
provider: acmeai
display_name: Acme AI
base_url_hints: [https://api.acme.test/v1]
models:
- id: acme-large-2
  aliases: [acme-large-2-2026-01-01]
  context_window_tokens: 200000
  max_output_tokens: 16384
  identity_keywords: [acme]
  fingerprints:
  - id: acme.cutoff
    signal: cutoff
    prompt: What is your knowledge cutoff?
    pure_code_checkable: true
    expect_contains_any: ["2025"]
"""


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ZING_NO_USER_KB", raising=False)
    monkeypatch.delenv("ZING_KB_DIR", raising=False)
    return tmp_path


# ----- loader layering ---------------------------------------------------- #
def test_no_kb_db_is_created_by_loading(data_dir):
    kb = load_knowledge_base()
    assert kb.user_kb and not kb.warnings
    assert not (data_dir / "kb.db").exists()
    assert kb.model_sources["openai/gpt-4o"] == "packaged:openai.yaml"


def test_imported_model_is_used_everywhere(data_dir):
    result, ids = import_yaml(NEW_PROVIDER_YAML, origin="import:acme.yaml")
    assert result.ok, result.errors
    assert len(ids) == 2  # provider entry + model entry
    kb = load_knowledge_base()
    r = kb.resolve("acme-large-2")
    assert r is not None and r.provider.provider == "acmeai"
    assert r.model.context_window_tokens == 200000
    assert kb.model_sources["acmeai/acme-large-2"].startswith("kb.db:entry/")
    assert kb.provider_sources["acmeai"].startswith("kb.db:entry/")
    # opt-out keeps packaged + ZING_KB_DIR only
    assert load_knowledge_base(include_user=False).resolve("acme-large-2") is None


def test_cache_follows_kb_db_changes(data_dir):
    assert load_knowledge_base().resolve("acme-large-2") is None
    result, ids = import_yaml(NEW_PROVIDER_YAML, origin="import:acme.yaml")
    assert result.ok, result.errors
    kb = load_knowledge_base()
    assert kb.resolve("acme-large-2") is not None
    model_entry = next(e for e in store.list_entries() if e["kind"] == "model")
    # disable / re-enable (same file size) and delete are seen at once
    assert store.set_enabled(model_entry["id"], False)
    assert load_knowledge_base().resolve("acme-large-2") is None
    assert store.set_enabled(model_entry["id"], True)
    assert load_knowledge_base().resolve("acme-large-2") is not None
    assert store.delete(model_entry["id"])
    kb = load_knowledge_base()
    assert kb.resolve("acme-large-2") is None and "acmeai" in kb.providers
    # an edited body (re-import) replaces the cached profile
    import_yaml(NEW_PROVIDER_YAML.replace("200000", "100000"))
    assert load_knowledge_base().resolve("acme-large-2").model.context_window_tokens == 100000


def test_shared_load_is_one_instance_until_kb_db_changes(data_dir):
    shared = load_knowledge_base(copy=False)
    assert load_knowledge_base(copy=False) is shared
    assert load_knowledge_base(full=True, copy=False) is not shared  # its own cache key
    # a copying caller gets its own object every time
    assert load_knowledge_base() is not shared and load_knowledge_base() is not load_knowledge_base()
    # an import is a new kb.db state: a new shared instance with the new model
    result, ids = import_yaml(NEW_PROVIDER_YAML, origin="import:acme.yaml")
    assert result.ok, result.errors
    after_import = load_knowledge_base(copy=False)
    assert after_import is not shared and after_import.resolve("acme-large-2") is not None
    assert shared.resolve("acme-large-2") is None  # what an earlier reader holds stays as it was
    # so is a toggle
    assert store.set_enabled(ids[-1], False)
    after_toggle = load_knowledge_base(copy=False)
    assert after_toggle is not after_import and after_toggle.resolve("acme-large-2") is None


def test_a_copying_callers_changes_never_reach_the_cache(data_dir):
    import_yaml(NEW_PROVIDER_YAML, origin="import:acme.yaml")
    pristine = load_knowledge_base(copy=False).model_dump(mode="json")
    mine = load_knowledge_base()
    mine.providers["openai"].models.clear()
    mine.providers["acmeai"].models[0].aliases.append("mutated")
    del mine.providers["anthropic"]
    mine.warnings.append("mutated")
    mine.model_sources.clear()
    assert load_knowledge_base(copy=False).model_dump(mode="json") == pristine
    assert load_knowledge_base().model_dump(mode="json") == pristine
    # the packaged profiles a build starts from are untouched too
    assert load_knowledge_base(include_user=False).providers["openai"].models


def test_a_stray_change_to_a_shared_instance_stays_out_of_the_packaged_profiles(data_dir):
    from zing.knowledge.loader import _load_packaged

    import_yaml(NEW_PROVIDER_YAML, origin="import:acme.yaml")  # a key of this data dir only
    count = len(_load_packaged()["openai"][0].models)
    load_knowledge_base(copy=False).providers["openai"].models.clear()  # what callers must not do
    assert len(_load_packaged()["openai"][0].models) == count
    assert load_knowledge_base(full=True, copy=False).providers["openai"].models


def test_uncached_loads_are_fresh_copies_even_without_copy(data_dir):
    preview = load_knowledge_base(user_entries=[], copy=False)
    preview.providers["openai"].models.clear()
    assert load_knowledge_base(copy=False).providers["openai"].models
    assert load_knowledge_base(user_entries=[], copy=False).providers["openai"].models


def test_cache_follows_data_dir(data_dir, tmp_path_factory, monkeypatch):
    import_yaml(NEW_PROVIDER_YAML)
    assert load_knowledge_base().resolve("acme-large-2") is not None
    monkeypatch.setenv("ZING_DATA_DIR", str(tmp_path_factory.mktemp("other-data")))
    assert load_knowledge_base().resolve("acme-large-2") is None
    monkeypatch.setenv("ZING_DATA_DIR", str(data_dir))
    assert load_knowledge_base().resolve("acme-large-2") is not None


def test_env_opt_out(data_dir, monkeypatch):
    import_yaml(NEW_PROVIDER_YAML)
    monkeypatch.setenv("ZING_NO_USER_KB", "1")
    kb = load_knowledge_base()
    assert not kb.user_kb and kb.resolve("acme-large-2") is None


def test_model_for_packaged_provider_merges_by_id(data_dir):
    before = load_knowledge_base()
    n = len(before.providers["openai"].models)
    text = """
provider: openai
display_name: Should Be Ignored
relay_red_flags: [my red flag]
fingerprints:
- {id: mine.fp, signal: s, prompt: hello}
models:
- id: my-openai-model
  context_window_tokens: 1000
"""
    result, _ = import_yaml(text)
    assert result.ok, result.errors
    assert any("display_name" in w["path"] for w in result.warnings)
    kb = load_knowledge_base()
    openai = kb.providers["openai"]
    assert len(openai.models) == n + 1
    assert openai.display_name == before.providers["openai"].display_name  # scalars not overridden
    assert "my red flag" in openai.relay_red_flags
    assert [f.id for f in openai.fingerprints][-1] == "mine.fp"
    assert kb.provider_sources["openai"] == "packaged:openai.yaml"


def test_user_model_shadows_packaged_one_and_is_warned(data_dir):
    result = scan("provider: openai\nmodels:\n- id: gpt-4o\n  context_window_tokens: 1234\n")
    assert result.ok and result.models[0]["action"] == "shadow"
    assert any("replaces openai/gpt-4o" in w["message"] for w in result.warnings)
    import_yaml("provider: openai\nmodels:\n- id: gpt-4o\n  context_window_tokens: 1234\n")
    kb = load_knowledge_base()
    assert kb.resolve("gpt-4o").model.context_window_tokens == 1234
    assert kb.shadowed["openai/gpt-4o"] == "packaged:openai.yaml"


def test_invalid_stored_entries_are_skipped_with_a_warning(data_dir):
    store.upsert("model", "openai", {"id": "broken", "no_such_field": 1}, model_id="broken")
    store.upsert("model", "nobody", {"id": "orphan"}, model_id="orphan")
    kb = load_knowledge_base()
    assert kb.resolve("gpt-4o") is not None  # the rest still loads
    assert len(kb.warnings) == 2
    assert any("orphan" in w and "not in the knowledge base" in w for w in kb.warnings)


def test_disabled_entries_do_not_apply(data_dir):
    _, ids = import_yaml(NEW_PROVIDER_YAML)
    model_entry = next(i for i in ids if store.get(i)["kind"] == "model")
    store.set_enabled(model_entry, False)
    assert load_knowledge_base().resolve("acme-large-2") is None
    store.set_enabled(model_entry, True)
    assert load_knowledge_base().resolve("acme-large-2") is not None



# ----- switching packaged items off (kb_disabled) ------------------------- #
def test_switching_off_packaged_items(data_dir):
    store.set_item_enabled("model", "openai", "gpt-4o", False)
    kb = load_knowledge_base()
    assert "openai/gpt-4o" not in kb.model_sources and kb.disabled == ["model:openai/gpt-4o"]
    assert all(m.id != "gpt-4o" for m in kb.providers["openai"].models)
    # the complete set and the opt-out still have it
    assert "openai/gpt-4o" in load_knowledge_base(full=True).model_sources
    assert "openai/gpt-4o" in load_knowledge_base(include_user=False).model_sources
    store.set_item_enabled("provider", "openai", None, False)
    kb = load_knowledge_base()
    assert "openai" not in kb.providers and "provider:openai" in kb.disabled
    assert not any(k.startswith("openai/") for k in kb.model_sources)
    store.set_item_enabled("provider", "openai", None, True)
    store.set_item_enabled("model", "openai", "gpt-4o", True)
    kb = load_knowledge_base()
    assert kb.model_sources["openai/gpt-4o"] == "packaged:openai.yaml" and not kb.disabled
    assert store.disabled_items() == []


def test_switch_off_leaves_the_users_own_entries_alone(data_dir):
    result, _ids = import_yaml("provider: openai\nmodels:\n- id: gpt-4o\n  context_window_tokens: 1234\n")
    assert result.ok, result.errors
    store.set_item_enabled("model", "openai", "gpt-4o", False)
    kb = load_knowledge_base()
    assert kb.model_sources["openai/gpt-4o"].startswith("kb.db:entry/") and not kb.disabled


def test_catalog_lists_complete_sets_with_state(data_dir):
    from zing.knowledge import catalog
    from zing.knowledge.relays import add_relay

    result, _ids = import_yaml(NEW_PROVIDER_YAML, origin="import:acme.yaml")
    assert result.ok, result.errors
    add_relay("My Relay", "https://relay.example/v1")
    catalog.set_enabled("model:openai/gpt-4o", False)
    catalog.set_enabled("model:acmeai/acme-large-2", False)  # yours: the entry's own column
    data = catalog.catalog()
    models = {m["key"]: m for m in data["models"]}
    assert models["model:openai/gpt-4o"]["enabled"] is False and not models["model:openai/gpt-4o"]["yours"]
    acme = models["model:acmeai/acme-large-2"]
    assert acme["yours"] and acme["enabled"] is False and acme["entry_id"]
    assert models["model:openai/gpt-4o-mini"]["enabled"] is True
    assert {p["key"] for p in data["relays"]} == {"provider:my-relay"}
    assert "provider:acmeai" in {p["key"] for p in data["providers"]}
    assert data["disabled"] == 1
    # a provider switched off: its models are listed but off
    catalog.set_enabled("provider:openai", False)
    data = catalog.catalog()
    m = next(x for x in data["models"] if x["key"] == "model:openai/gpt-4o-mini")
    assert m["enabled"] is False and m["provider_enabled"] is False
    # the relay is still listed (and its name taken) while switched off
    catalog.set_enabled("provider:my-relay", False)
    relay = catalog.catalog()["relays"][0]
    assert relay["enabled"] is False and relay["base_urls"] == ["https://relay.example/v1"]
    with pytest.raises(catalog.ToggleError) as err:
        catalog.set_enabled("model:openai/nope", False)
    assert err.value.status == 404


def test_catalog_from_shared_loads_matches_copies_and_changes_nothing(data_dir):
    from zing.knowledge import catalog
    from zing.knowledge.relays import add_relay

    # user entries, a relay, a shadowing model, disabled items of both kinds
    result, ids = import_yaml(NEW_PROVIDER_YAML, origin="import:acme.yaml")
    assert result.ok, result.errors
    import_yaml("provider: openai\nmodels:\n- id: gpt-4o\n  context_window_tokens: 1000\n")
    add_relay("My Relay", "https://relay.example/v1")
    catalog.set_enabled("model:openai/gpt-4o-mini", False)
    catalog.set_enabled("model:acmeai/acme-large-2", False)
    catalog.set_enabled("provider:anthropic", False)

    effective = load_knowledge_base(copy=False)
    full = load_knowledge_base(full=True, copy=False)
    before = (effective.model_dump(mode="json"), full.model_dump(mode="json"))
    data = catalog.catalog()
    # the same lists as from the caller's own copies (what catalog() used before)
    copied = catalog.build(load_knowledge_base(full=True), load_knowledge_base(), store.list_entries())
    assert data == copied
    # each model's state by the pre-set rule: same source in the audit load and
    # its id among the provider's effective models
    for m in data["models"]:
        key, name = f"{m['provider']}/{m['id']}", m["provider"]
        eff = effective.providers.get(name)
        prov_on = eff is not None and effective.provider_sources.get(name) == full.provider_sources[name]
        eff_src = effective.model_sources.get(key) if prov_on else None
        on = eff_src == full.model_sources[key] and eff is not None and any(
            x.id == m["id"] for x in eff.models)
        assert m["enabled"] is on and m["provider_enabled"] is prov_on, key
    models = {m["key"]: m for m in data["models"]}
    assert models["model:openai/gpt-4o-mini"]["enabled"] is False
    assert models["model:openai/gpt-4o"]["enabled"] is True and models["model:openai/gpt-4o"]["yours"]
    assert models["model:acmeai/acme-large-2"]["enabled"] is False
    assert models["model:anthropic/" + next(
        m.id for m in full.providers["anthropic"].models)]["provider_enabled"] is False
    # neither the lists nor the toggles changed the shared instances
    data["warnings"].append("x")
    catalog.set_enabled("model:openai/gpt-4o-mini", True)
    assert (effective.model_dump(mode="json"), full.model_dump(mode="json")) == before
    assert load_knowledge_base(copy=False).warnings == effective.warnings
    assert catalog.catalog()["models"] != data["models"]  # the toggle is seen


def test_catalog_keeps_your_model_less_provider_among_providers(data_dir):
    from zing.knowledge import catalog

    result, _ids = import_yaml("provider: newprov\ndisplay_name: New\nbase_url_hints: [https://n.example/v1]\nmodels: []\n")
    assert result.ok, result.errors
    data = catalog.catalog()
    assert "provider:newprov" in {p["key"] for p in data["providers"]}
    assert "provider:newprov" not in {p["key"] for p in data["relays"]}


def test_catalog_lists_additions_to_a_packaged_provider(data_dir):
    from zing.knowledge import catalog

    result, _ids = import_yaml("provider: openai\nbase_url_hints: [https://proxy.example/v1]\nmodels: []\n")
    assert result.ok, result.errors
    add = next(p for p in catalog.catalog()["providers"] if p.get("addition"))
    assert add["key"].startswith("entry:") and add["yours"] and add["enabled"]
    assert add["base_urls"] == ["https://proxy.example/v1"]
    catalog.set_enabled(add["key"], False)
    assert not next(p for p in catalog.catalog()["providers"] if p.get("addition"))["enabled"]

# ----- import checks ------------------------------------------------------ #
BAD_YAML = [
        ("", "empty"),
        ("- just a list", "mapping"),
        ("provider: Bad Key\nmodels: []", "provider key"),
        ("provider: x\nmodels:\n- id: m\n  unknown_field: 1", "unknown field"),
        ("provider: x\nmodels:\n- id: has space", "without spaces"),
        ("provider: x\nbase: &a {k: 1}\nmodels:\n- id: m\n  extra: *a", "anchors"),
        ("provider: x\nmodels:\n- id: m\n  fingerprints:\n  - {id: f, signal: s, prompt: p, expect_regex: '(a+)+$'}", "nested quantifiers"),
        ("provider: x\nmodels:\n- id: m\n  fingerprints:\n  - {id: f, signal: s, prompt: p, expect_regex: '(['}", "invalid regular expression"),
        ("provider: x\nmodels:\n- id: m\n  fingerprints:\n  - {id: f, signal: s, prompt: p, max_tokens: 999999}", "max_tokens"),
        ("provider: x\nmodels:\n- id: m\n  fingerprints:\n  - {id: f, signal: s, prompt: p, prompt_lang: zh}", "language_bound"),
        ("provider: x\nmodels:\n- id: m\n- id: m", "duplicate model"),
        ("provider: x\nbase_url_hints: [ftp://nope]\nmodels:\n- id: m", "http"),
        ("provider: x\nmodels: [{id: [not, a, string]}]", "id"),
        ("key: [unclosed", "not valid YAML"),
        ("provider: x\n\tmodels: []", "not valid YAML"),
        ("provider: x\nmodels:\n- id: m\n  note: \"bad \\q escape\"", "not valid YAML"),
        ("provider: x\nmodels: [{id: m}]]", "not valid YAML"),
        ("provider: x\nmodels: []\n---\n{a: 1", "not valid YAML"),
        ("provider: x\nnote: \x07\nmodels: []", "unacceptable character"),
        ("provider: x\nnote: !foo bar\nmodels: []", "constructor for the tag"),
        ("provider: x\nnote: !!python/object/apply:os.system [ls]\nmodels: []", "constructor for the tag"),
        ("a: &a [x, x]\nb: &b [*a, *a]\nc: [*b, *b]", "anchors"),
        ("provider: x\nmodels: []\n---\nprovider: y\nm: *undefined", "anchors"),
        ("provider: x\nmodels: []\nnote: " + "[" * 33 + "]" * 33, "nested more than 32 levels"),
        ("provider: x\nmodels:\n" + "".join("  " * i + "- \n" for i in range(40)), "nested more than"),
        # A typed scalar its constructor cannot convert: refused like any YAML error.
        ("provider: x\nmodels: []\nnote: !!int abc", "cannot read 'abc' as int"),
        ("provider: x\nmodels: []\nnote: !!float nope", "cannot read 'nope' as float"),
        ("provider: x\nmodels: []\nnote: !!bool maybe", "cannot read 'maybe' as bool"),
        ("provider: x\nmodels:\n- id: m\n  released: !!timestamp 2026-99-99", "(line 4, column 13)"),
        ("provider: x\nmodels: []\nnote: !!int 0x", "as int"),
        # Deep enough to overflow the C stack in libyaml's composer, were it reached.
        ("provider: x\nmodels: []\nnote: " + "[" * 200_000 + "]" * 200_000, "nested more than"),
]


def _short_id(value):
    return repr(value)[:40] if isinstance(value, str) else None


@pytest.mark.parametrize(("text", "needle"), BAD_YAML, ids=_short_id)
def test_scan_rejects_bad_yaml(data_dir, text, needle):
    result = scan(text)
    assert not result.ok
    assert any(needle.lower() in (e["message"] + " " + e["path"]).lower() for e in result.errors), result.errors
    assert not (data_dir / "kb.db").exists() or store.list_entries() == []


@pytest.mark.parametrize("text", [NEW_PROVIDER_YAML, *(t for t, _ in BAD_YAML)], ids=_short_id)
def test_scan_is_the_same_with_the_c_and_pure_python_yaml_loaders(data_dir, monkeypatch, text):
    # scan() parses with libyaml when available; the documents it accepts and
    # the errors it reports (via the pure-Python loader's more detailed
    # message) must be exactly those of the pure-Python SafeLoader.
    import yaml

    from zing.utils import yamlio

    if not hasattr(yaml, "CSafeLoader"):
        pytest.skip("PyYAML built without libyaml")
    assert yamlio.SAFE_LOADER is yaml.CSafeLoader
    with_c = scan(text).to_dict()
    monkeypatch.setattr(yamlio, "SAFE_LOADER", yaml.SafeLoader)
    assert scan(text).to_dict() == with_c


def test_scan_reports_the_detailed_yaml_error(data_dir):
    # libyaml alone would say "found character that cannot start any token".
    result = scan("provider: x\n\tmodels: []")
    assert result.errors == [{"path": "", "message": "not valid YAML: found character '\\t' "
                              "that cannot start any token (line 2, column 1)"}]


def test_scan_rejects_oversized_input(data_dir):
    assert not scan("provider: x\n" + "#" * (600 * 1024)).ok


def test_scan_lists_probes_and_writes_nothing(data_dir):
    result = scan(NEW_PROVIDER_YAML)
    assert result.ok
    assert [p["id"] for p in result.probes] == ["acme.cutoff"]
    assert result.probes[0]["prompt"] == "What is your knowledge cutoff?"
    assert store.list_entries() == []


def test_scan_reports_resolution_changes(data_dir):
    # A new model whose id captures an existing alias-level lookup elsewhere.
    kb = load_knowledge_base()
    victim = next(m for p, m in kb.all_models() if p.provider == "openai" and m.aliases)
    alias = victim.aliases[0]
    text = f"provider: acmeai\nmodels:\n- id: thief\n  aliases: ['{alias}']\n"
    result = scan(text)
    assert result.ok  # a warning, not an error
    assert any(alias in w["message"] for w in result.warnings)


def test_reimport_updates_in_place_and_export_roundtrips(data_dir):
    _, ids1 = import_yaml(NEW_PROVIDER_YAML)
    result, ids2 = import_yaml(NEW_PROVIDER_YAML.replace("200000", "300000"))
    assert result.models[0]["action"] == "update"
    assert sorted(ids1) == sorted(ids2)
    assert load_knowledge_base().resolve("acme-large-2").model.context_window_tokens == 300000
    exported = export_yaml()
    assert "acme-large-2" in exported and "300000" in exported
    store.delete(ids2[0])
    store.delete(ids2[1])
    assert import_yaml(exported)[0].ok
    assert load_knowledge_base().resolve("acme-large-2").model.context_window_tokens == 300000


def test_research_prompt_names_fields_and_model():
    text = research_prompt("acme-large-2", "acmeai", load_knowledge_base())
    assert "acme-large-2" in text and "acmeai" in text
    for field in ("context_window_tokens", "identity_forbidden", "expect_regex", "language_bound", "sources"):
        assert field in text
    assert "openai" in text  # existing provider keys are listed
    assert "```yaml" in text


# ----- snapshots ---------------------------------------------------------- #
def test_snapshot_roundtrip_and_hash_ignores_match_confidence(data_dir):
    kb = load_knowledge_base()
    exact = kb.resolve("gpt-4o")
    snap = snapshot(exact)
    assert "models" not in snap["provider"] and snap["model"]["id"] == "gpt-4o"
    again = resolved_from_snapshot(snap, "alias")
    assert again.model == exact.model and again.match_confidence == "alias"
    assert content_hash(snapshot(again)) == content_hash(snap)
    usage = knowledge_usage(kb, exact, "gpt-4o")
    assert usage.matched and usage.match_confidence == "exact"
    assert usage.model_source == "packaged:openai.yaml" and usage.profile_hash == content_hash(snap)
    none = knowledge_usage(kb, None, "nope")
    assert not none.matched and none.profile is None


async def test_report_carries_the_knowledge_used(data_dir, mock_server, target_config, monkeypatch):
    from zing.config import AuditOptions
    from zing.runner import run_audit

    import_yaml("provider: openai\nmodels:\n- id: gpt-4o\n  context_window_tokens: 1234\n")
    monkeypatch.setattr("zing.runner.make_client", _mock_client_factory(mock_server))
    report = await run_audit(target_config, AuditOptions(suite="smoke"))
    k = report.knowledge
    assert k is not None and k.matched and k.provider == "openai" and k.model_id == "gpt-4o"
    assert k.model_source.startswith("kb.db:entry/") and k.shadows == "packaged:openai.yaml"
    assert [e.kind for e in k.user_entries] == ["model"]
    assert k.profile["model"]["context_window_tokens"] == 1234
    # --no-user-kb: packaged profile, and the report says so
    report2 = await run_audit(target_config, AuditOptions(suite="smoke"), use_user_kb=False)
    assert report2.knowledge.user_kb is False
    assert report2.knowledge.model_source == "packaged:openai.yaml"
    assert report2.knowledge.profile_hash != k.profile_hash
    # human renderers show it
    from zing.report.render import compact_dict, render_html, render_markdown

    assert "## Knowledge base" in render_markdown(report)
    assert "Knowledge base" in render_html(report)
    assert compact_dict(report)["knowledge"]["source"].startswith("kb.db:entry/")


async def test_pinned_profile_wins_over_the_live_kb(data_dir, mock_server, target_config, monkeypatch):
    from zing.config import AuditOptions
    from zing.runner import run_audit

    kb = load_knowledge_base()
    pinned = knowledge_usage(kb, kb.resolve("gpt-4o"), "gpt-4o")
    import_yaml("provider: openai\nmodels:\n- id: gpt-4o\n  context_window_tokens: 1234\n")
    monkeypatch.setattr("zing.runner.make_client", _mock_client_factory(mock_server))
    report = await run_audit(target_config, AuditOptions(suite="smoke"), pinned=pinned)
    assert report.knowledge.pinned
    assert report.knowledge.profile_hash == pinned.profile_hash


async def test_invalid_pinned_snapshot_falls_back_to_the_live_kb(data_dir, mock_server, target_config, monkeypatch):
    from zing.config import AuditOptions
    from zing.runner import run_audit

    kb = load_knowledge_base()
    pinned = knowledge_usage(kb, kb.resolve("gpt-4o"), "gpt-4o")
    pinned.profile["model"]["field_from_the_future"] = 1
    monkeypatch.setattr("zing.runner.make_client", _mock_client_factory(mock_server))
    report = await run_audit(target_config, AuditOptions(suite="smoke"), pinned=pinned)
    assert not report.knowledge.pinned and report.knowledge.matched
    assert any("pinned profile no longer valid" in w for w in report.knowledge.warnings)


def _mock_client_factory(mock_server):
    from zing.clients import OpenAICompatibleClient

    def make(cfg):
        return OpenAICompatibleClient(cfg, transport=mock_server.transport)

    return make


# ----- history.db / watches.db snapshot tables ------------------------------ #
def _report_with(profile_hash: str, snap: dict) -> dict:
    return {
        "generated_at": "t",
        "target": {"base_url": "https://x/v1", "claimed_model": "gpt-4o", "model": "gpt-4o"},
        "verdict": {"risk_level": "clean", "overall_score": 90.0},
        "knowledge": {"requested_model": "gpt-4o", "matched": True, "match_confidence": "exact",
                      "profile_hash": profile_hash, "profile": snap},
    }


def test_history_stores_each_profile_once_and_prunes(data_dir):
    import sqlite3

    from zing.web import history

    kb = load_knowledge_base()
    snap = snapshot(kb.resolve("gpt-4o"))
    h = content_hash(snap)
    a = history.save(_report_with(h, snap))
    b = history.save(_report_with(h, snap))
    with sqlite3.connect(data_dir / "history.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM kb_snapshots").fetchone()[0] == 1
        stored = json.loads(conn.execute("SELECT report_json FROM history WHERE id=?", (a,)).fetchone()[0])
    assert stored["knowledge"]["profile"] is None  # deduplicated out of the row
    assert history.get(a)["knowledge"]["profile"] == snap  # and put back on read
    assert history.recent()[0]["kb_match"] == "exact"
    history.delete(a)
    assert history.snapshot_for(b) == snap
    history.delete(b)
    with sqlite3.connect(data_dir / "history.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM kb_snapshots").fetchone()[0] == 0


def test_history_db_from_before_snapshots_is_migrated(data_dir):
    import sqlite3

    from zing.web import history

    with sqlite3.connect(data_dir / "history.db") as conn:
        conn.execute(
            "CREATE TABLE history (id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, base_url TEXT,"
            " claimed_model TEXT, model TEXT, mode TEXT, suite TEXT, risk_level TEXT, score REAL,"
            " rating TEXT, report_json TEXT)"
        )
        conn.execute("INSERT INTO history (report_json) VALUES ('{\"verdict\": {}}')")
    assert history.get(1) == {"verdict": {}}
    assert history.recent()[0]["kb_match"] is None


def test_watch_pins_a_snapshot_and_cleans_up(data_dir):
    import sqlite3

    from zing.web import watches

    kb = load_knowledge_base()
    usage = knowledge_usage(kb, kb.resolve("gpt-4o"), "gpt-4o").model_dump(mode="json")
    wid = watches.create({"base_url": "https://x/v1", "model": "gpt-4o"}, knowledge=usage)
    listed = watches.list_all()[0]
    assert listed["kb"]["model_id"] == "gpt-4o" and listed["kb"]["profile"] is None
    pinned = watches.pinned_knowledge(wid)
    assert pinned["profile"] == usage["profile"] and pinned["pinned_at"]
    watches.pin(wid, None)
    assert watches.pinned_knowledge(wid) is None
    with sqlite3.connect(data_dir / "watches.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM kb_snapshots").fetchone()[0] == 0
    watches.pin(wid, usage)
    watches.delete(wid)
    with sqlite3.connect(data_dir / "watches.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM kb_snapshots").fetchone()[0] == 0


# ----- web API + page ------------------------------------------------------- #
@pytest.fixture
def client(data_dir):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from zing.web.server import create_app

    return TestClient(create_app(), base_url="http://localhost")


def test_kb_api_refuses_an_unreadable_typed_value_cleanly(client):
    # Used to escape scan() as a bare ValueError: a 500 on the Models page.
    text = "provider: x\nmodels: []\nnote: !!int abc"
    scanned = client.post("/api/kb/scan", json={"yaml": text})
    assert scanned.status_code == 200 and not scanned.json()["ok"]
    assert "cannot read 'abc' as int" in scanned.json()["errors"][0]["message"]
    imported = client.post("/api/kb/import", json={"yaml": text})
    assert imported.status_code == 400 and imported.json()["errors"]
    assert client.get("/api/kb/profiles").json()["entries"] == []


def test_kb_api_scan_import_list_toggle_delete(client):
    r = client.post("/api/kb/scan", json={"yaml": NEW_PROVIDER_YAML})
    assert r.status_code == 200 and r.json()["ok"] and client.get("/api/kb/profiles").json()["entries"] == []
    bad = client.post("/api/kb/import", json={"yaml": "provider: x\nmodels:\n- id: m\n  nope: 1"})
    assert bad.status_code == 400 and bad.json()["errors"]
    ok = client.post("/api/kb/import", json={"yaml": NEW_PROVIDER_YAML, "filename": "acme.yaml"})
    assert ok.status_code == 201 and len(ok.json()["entry_ids"]) == 2
    data = client.get("/api/kb/profiles").json()
    acme = next(m for m in data["models"] if m["key"] == "model:acmeai/acme-large-2")
    assert acme["source"].startswith("kb.db:entry/") and acme["yours"]
    assert {e["origin"] for e in data["entries"]} == {"import:acme.yaml"}
    assert "body" not in data["entries"][0]
    res = client.post("/api/kb/resolve", json={"model": "acme-large-2"}).json()
    assert res["matched"] and res["provider"] == "acmeai"
    eid = next(e["id"] for e in data["entries"] if e["kind"] == "model")
    assert client.patch(f"/api/kb/entries/{eid}", json={"enabled": False}).status_code == 200
    assert not client.post("/api/kb/resolve", json={"model": "acme-large-2"}).json()["matched"]
    assert client.delete(f"/api/kb/entries/{eid}").status_code == 200
    assert client.delete(f"/api/kb/entries/{eid}").status_code == 404
    exp = client.get("/api/kb/export")
    assert exp.status_code == 200 and "acmeai" in exp.text and "attachment" in exp.headers["content-disposition"]
    prompt = client.get("/api/kb/prompt", params={"model": "acme-large-2"})
    assert prompt.status_code == 200 and "acme-large-2" in prompt.text


def test_kb_api_enabled_switch(client):
    r = client.put("/api/kb/enabled", json={"key": "model:openai/gpt-4o", "enabled": False})
    assert r.status_code == 200 and r.json()["ok"]
    data = client.get("/api/kb/profiles").json()
    assert next(m for m in data["models"] if m["key"] == "model:openai/gpt-4o")["enabled"] is False
    res = client.post("/api/kb/resolve", json={"model": "gpt-4o"}).json()
    assert res["matched"] is False or res["model_id"] != "gpt-4o"
    assert all(m["id"] != "gpt-4o" for p in client.get("/api/kb").json()["providers"] for m in p["models"])
    assert client.put("/api/kb/enabled", json={"key": "model:openai/nope", "enabled": False}).status_code == 404
    assert client.put("/api/kb/enabled", json={"key": "weird", "enabled": False}).status_code == 400
    assert client.put("/api/kb/enabled", json={"enabled": False}).status_code == 400
    assert client.put("/api/kb/enabled", json={"key": "model:openai/gpt-4o", "enabled": True}).status_code == 200
    assert client.post("/api/kb/resolve", json={"model": "gpt-4o"}).json()["model_id"] == "gpt-4o"


def test_kb_api_resolve_names_a_switched_off_profile(client):
    client.post("/api/kb/import", json={"yaml": NEW_PROVIDER_YAML})
    client.put("/api/kb/enabled", json={"key": "provider:acmeai", "enabled": False})
    res = client.post("/api/kb/resolve", json={"model": "acme-large-2"}).json()
    assert res == {"matched": False, "switched_off": {"provider": "acmeai", "model_id": "acme-large-2"}}
    # a fuzzy match is still used, but the exact profile that is off is named
    client.put("/api/kb/enabled", json={"key": "model:openai/gpt-4o-mini", "enabled": False})
    res = client.post("/api/kb/resolve", json={"model": "gpt-4o-mini"}).json()
    assert res["matched"] and res["match_confidence"] != "exact"
    assert res["switched_off"] == {"provider": "openai", "model_id": "gpt-4o-mini"}


def test_kb_import_refuses_cross_site_and_non_json(client):
    r = client.post("/api/kb/import", json={"yaml": NEW_PROVIDER_YAML}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.post("/api/kb/import", content=json.dumps({"yaml": NEW_PROVIDER_YAML}), headers={"Content-Type": "text/plain"})
    assert r.status_code == 415
    assert store.list_entries() == []


def test_kb_page_and_nav(client):
    r = client.get("/v2/kb")
    assert r.status_code == 200 and '<header class="znav" data-page="kb"' in r.text
    assert re.search(r'<script src="/v2/static/nav\.js(\?v=[0-9a-f]+)?"></script>', r.text)
    assert '"/v2/kb"' in client.get("/v2/static/nav.js").text
    assert client.get("/v2/kb?ui=v1", follow_redirects=False).headers["location"] == "/"


def test_watch_api_pins_and_repins(client):
    wid = client.post("/api/watches", json={"base_url": "https://x/v1", "model": "gpt-4o"}).json()["id"]
    row = client.get("/api/watches").json()[0]
    assert row["kb"]["model_id"] == "gpt-4o" and row["kb_changed"] is False
    import_yaml("provider: openai\nmodels:\n- id: gpt-4o\n  context_window_tokens: 1234\n")
    row = client.get("/api/watches").json()[0]
    assert row["kb_changed"] is True
    assert client.patch(f"/api/watches/{wid}", json={"repin": True}).status_code == 200
    row = client.get("/api/watches").json()[0]
    assert row["kb_changed"] is False and row["kb"]["model_source"].startswith("kb.db:entry/")


def test_cli_kb_import_check_and_prompt(data_dir, tmp_path):
    from typer.testing import CliRunner

    from zing.cli import app

    f = tmp_path / "acme.yaml"
    f.write_text(NEW_PROVIDER_YAML, encoding="utf-8")
    runner = CliRunner()
    res = runner.invoke(app, ["kb-import", str(f), "--check"])
    assert res.exit_code == 0 and store.list_entries() == []
    res = runner.invoke(app, ["kb-import", str(f)])
    assert res.exit_code == 0 and len(store.list_entries()) == 2
    res = runner.invoke(app, ["kb", "acmeai", "--json"])
    assert json.loads(res.stdout)["models"][0]["source"].startswith("kb.db:entry/")
    res = runner.invoke(app, ["kb", "acmeai", "--json", "--no-user-kb"])
    assert json.loads(res.stdout)["models"] == []
    res = runner.invoke(app, ["kb-prompt", "acme-large-2"])
    assert res.exit_code == 0 and "acme-large-2" in res.stdout
    bad = tmp_path / "bad.yaml"
    bad.write_text("provider: x\nmodels:\n- id: m\n  nope: 1\n", encoding="utf-8")
    assert runner.invoke(app, ["kb-import", str(bad)]).exit_code == 1
