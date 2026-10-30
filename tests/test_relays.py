"""Relays and providers as endpoints (ekte/knowledge/relays.py)."""

from __future__ import annotations

import pytest

from ekte.knowledge import load_knowledge_base, store
from ekte.knowledge.relays import RelayError, add_relay, base_urls, is_relay, normalize_url, slug
from ekte.knowledge.schema import ProviderProfile


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://api.openai.com/v1", "https://api.openai.com/v1"),
        ("https://api.anthropic.com/v1/", "https://api.anthropic.com/v1"),
        ("https://api.anthropic.com/v1/messages", "https://api.anthropic.com/v1"),
        ("https://api.moonshot.ai/v1/chat/completions", "https://api.moonshot.ai/v1"),
        ("http://127.0.0.1:8080/v1/embeddings?x=1#top", "http://127.0.0.1:8080/v1"),
        ("  https://relay.example  ", "https://relay.example"),
        ("api.openai.com", None),
        ("/v1/chat/completions", None),
        ("REGION-aiplatform.googleapis.com/v1/projects/{project}", None),
        ("https://{host}/v1", None),
        ("ftp://relay.example", None),
        ("", None),
    ],
)
def test_normalize_url(url, expected):
    assert normalize_url(url) == expected


def test_packaged_providers_have_usable_base_urls():
    kb = load_knowledge_base(include_user=False)
    for prov in kb.providers.values():
        urls = base_urls(prov)
        assert urls, prov.provider
        assert all(u.startswith(("http://", "https://")) and not u.endswith("/") for u in urls)
        assert len(urls) == len(set(urls))
    assert base_urls(kb.providers["openai"]) == ["https://api.openai.com/v1"]
    assert base_urls(kb.providers["anthropic"]) == ["https://api.anthropic.com/v1"]
    assert all("{" not in u for u in base_urls(kb.providers["gemini"]))


def test_slug():
    assert slug("My Relay!") == "my-relay"
    assert slug("Ärger.io") == "arger.io"
    assert slug("  --x--  ") == "x"
    cjk = slug("某中转站")
    assert cjk.startswith("relay-") and cjk == slug("某中转站") and cjk != slug("另一个")
    assert len(slug("a" * 200)) == 64


def test_is_relay():
    assert is_relay(ProviderProfile(provider="x"))
    assert is_relay(ProviderProfile(provider="x", models=[{"id": "m"}]), {"origin": "relay"})
    assert not is_relay(ProviderProfile(provider="x", models=[{"id": "m"}]), {"origin": "import"})


def test_add_relay(tmp_path, monkeypatch):
    monkeypatch.setenv("EKTE_DATA_DIR", str(tmp_path))
    saved = add_relay("  Cheap   GPT  ", "https://relay.example/v1/chat/completions")
    assert saved["provider"] == "cheap-gpt" and saved["display_name"] == "Cheap GPT"
    assert saved["base_url"] == "https://relay.example/v1"
    entry = store.get(saved["entry_id"])
    assert entry["kind"] == "provider" and entry["origin"] == "relay"
    assert entry["body"] == {"display_name": "Cheap GPT", "base_url_hints": ["https://relay.example/v1"]}
    prov = load_knowledge_base().providers["cheap-gpt"]
    assert prov.display_name == "Cheap GPT" and prov.models == [] and base_urls(prov) == ["https://relay.example/v1"]

    for name, url, status in [
        ("cheap gpt", "https://b.example", 409),  # same key as an entry of yours
        ("DeepSeek", "https://b.example", 409),  # a packaged provider
        ("Again", "https://relay.example/v1/", 409),  # a known URL
        ("", "https://b.example", 400),
        ("x", "b.example", 400),
    ]:
        with pytest.raises(RelayError) as err:
            add_relay(name, url)
        assert err.value.status == status, name
    assert len(store.list_entries()) == 1
