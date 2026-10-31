"""Knowledge-base freshness: dates on profiles, the report field, the stale warning."""

from __future__ import annotations

from datetime import date, timedelta

from ekte.knowledge import load_knowledge_base
from ekte.knowledge.freshness import STALE_AFTER_DAYS, bundled_date, stale_warning
from ekte.knowledge.snapshot import knowledge_usage
from ekte.models import KnowledgeUsage
from ekte.report.render import _knowledge_lines, compact_dict


def test_every_packaged_profile_has_a_valid_last_verified():
    kb = load_knowledge_base(include_user=False)
    assert kb.providers
    for prov in kb.providers.values():
        assert prov.last_verified, prov.provider
        date.fromisoformat(prov.last_verified)


def test_bundled_date_is_the_oldest_profile_date():
    kb = load_knowledge_base(include_user=False)
    assert bundled_date() == min(p.last_verified for p in kb.providers.values())


def test_usage_carries_the_kb_date_even_without_a_match():
    kb = load_knowledge_base(include_user=False)
    usage = knowledge_usage(kb, None, "no-such-model")
    assert usage.kb_date == bundled_date()
    assert ("Knowledge-base date", usage.kb_date) in _knowledge_lines(usage)


def test_stale_warning_only_after_the_threshold():
    verified = date(2026, 1, 1)
    edge = verified + timedelta(days=STALE_AFTER_DAYS)
    assert stale_warning("2026-01-01", today=edge) is None
    msg = stale_warning("2026-01-01", today=edge + timedelta(days=1))
    assert msg and "2026-01-01" in msg and "update ekte" in msg and "kb-import" in msg
    assert stale_warning(None) is None
    assert stale_warning("garbage") is None


def test_old_report_without_kb_date_still_loads():
    assert KnowledgeUsage(requested_model="x").kb_date is None


async def _audit(monkeypatch):
    import ekte.detectors  # noqa: F401
    from ekte.clients import make_client as real
    from ekte.config import AuditOptions
    from ekte.models import TargetConfig
    from ekte.runner import run_audit
    from tests._helpers import BASE_URL, DEFAULT_MODEL, MockServer

    server = MockServer()
    monkeypatch.setattr(
        "ekte.runner.make_client", lambda config, **_: real(config, transport=server.transport)
    )
    return await run_audit(
        TargetConfig(name="t", kind="target", base_url=BASE_URL, model=DEFAULT_MODEL),
        AuditOptions(suite="custom", dimensions=["connectivity"]),
    )


async def test_report_shows_the_date_and_stays_quiet_when_fresh(monkeypatch):
    monkeypatch.setattr("ekte.knowledge.freshness.date", _FixedDate(date.fromisoformat(bundled_date())))
    report = await _audit(monkeypatch)
    assert report.knowledge.kb_date == bundled_date()
    assert compact_dict(report)["knowledge"]["kb_date"] == bundled_date()
    assert not any("knowledge base was last verified" in w for w in report.warnings)


async def test_stale_data_warns_without_changing_the_verdict(monkeypatch):
    fresh = await _audit(monkeypatch)
    later = date.fromisoformat(bundled_date()) + timedelta(days=STALE_AFTER_DAYS + 1)
    monkeypatch.setattr("ekte.knowledge.freshness.date", _FixedDate(later))
    stale = await _audit(monkeypatch)
    assert any("knowledge base was last verified" in w for w in stale.warnings)
    assert stale.verdict.risk_level == fresh.verdict.risk_level
    assert stale.verdict.overall_score == fresh.verdict.overall_score


def _FixedDate(today):
    class Fixed(date):
        @classmethod
        def today(cls):
            return today

    return Fixed
