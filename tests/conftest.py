"""Shared test fixtures: a configurable in-process mock OpenAI-compatible server.

Tests never touch the network. We inject an ``httpx.MockTransport`` into the real
:class:`OpenAICompatibleClient`, so the client, SSE parsing, and detectors all run
against deterministic, scenario-driven responses. The :class:`MockServer` exposes
knobs to reproduce the divergences ekte hunts for: model downgrade, context
truncation, fake streaming, missing/inflated usage, tool calls, and JSON mode.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

from ekte.clients import OpenAICompatibleClient
from ekte.config import AuditOptions
from ekte.context import AuditContext
from ekte.knowledge import load_knowledge_base
from ekte.models import TargetConfig
from tests._helpers import BASE_URL, DEFAULT_MODEL, MockServer  # noqa: F401

# per-step results of the a11y suite (EKTE_A11Y_RESULTS); registered here so
# the pytest-xdist controller loads it too
pytest_plugins = ["tests.a11y.results"]


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture
def mock_server() -> MockServer:
    """An honest mock relay; mutate its knobs in the test to inject a scenario."""
    return MockServer()


@pytest.fixture(scope="session", autouse=True)
def _isolated_data_dir(tmp_path_factory):
    """Keep every test away from the developer's real ~/.ekte (history,
    watches and the user knowledge base in kb.db). Tests that need their own
    directory still monkeypatch EKTE_DATA_DIR per test."""
    import os

    saved = {k: os.environ.get(k) for k in ("EKTE_DATA_DIR", "EKTE_KB_DIR", "EKTE_NO_USER_KB")}
    os.environ["EKTE_DATA_DIR"] = str(tmp_path_factory.mktemp("ekte-data"))
    os.environ.pop("EKTE_KB_DIR", None)
    os.environ.pop("EKTE_NO_USER_KB", None)
    yield
    for k, v in saved.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


@pytest.fixture(scope="session")
def knowledge_base(_isolated_data_dir):
    """The packaged knowledge base (loaded once)."""
    return load_knowledge_base()


@pytest.fixture
def target_config() -> TargetConfig:
    return TargetConfig(
        name="target",
        kind="target",
        base_url=BASE_URL,
        api_key="sk-test-secret-key-do-not-leak",
        model=DEFAULT_MODEL,
    )


@pytest.fixture
async def client(
    mock_server: MockServer, target_config: TargetConfig
) -> Iterator[OpenAICompatibleClient]:
    """An opened client wired to the mock server's transport."""
    async with OpenAICompatibleClient(target_config, transport=mock_server.transport) as c:
        yield c


@pytest.fixture
async def audit_context(
    mock_server: MockServer,
    target_config: TargetConfig,
    knowledge_base,
) -> Iterator[AuditContext]:
    """A fully-formed AuditContext for exercising detectors against the mock."""
    async with OpenAICompatibleClient(target_config, transport=mock_server.transport) as c:
        ctx = AuditContext(
            target=target_config,
            client=c,
            options=AuditOptions(suite="full"),
            kb=knowledge_base,
            profile=knowledge_base.resolve(target_config.model),
        )
        yield ctx


@pytest.fixture(autouse=True)
def _master_key(monkeypatch):
    """Each test starts with a fresh master key held in memory (as after the
    user entered it), and EKTE_SECRET_KEY unset. Tests of the locked or
    first-run states call ``vault.reset_state()`` themselves."""
    monkeypatch.delenv("EKTE_SECRET_KEY", raising=False)
    try:
        from ekte import secretbox
        from ekte.web.masterkey import vault
    except ImportError:  # pragma: no cover - the web extra is not installed
        yield
        return
    import contextlib

    vault.reset_state()
    with contextlib.suppress(secretbox.SecretError):  # cryptography missing
        secretbox.unlock(secretbox.SecretBox([secretbox.generate_key()], "test"))
    yield
    vault.reset_state()
