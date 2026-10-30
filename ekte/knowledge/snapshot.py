"""Snapshots of the knowledge-base profile a run used.

A snapshot is the resolved profile as plain JSON — the provider's own fields
(everything but its model list) plus the one matched model — so it stays
readable and re-usable after the YAML files or kb.db change. Its content hash
(canonical JSON, SHA-256) identifies a profile version: two runs audited
against identical content share a hash, whatever file it came from.

How a requested id matched (exact/alias/fuzzy) is a run result and deliberately
not part of the snapshot or its hash.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from typing import Any

from zing.knowledge.schema import KnowledgeBase, ModelProfile, ProviderProfile, ResolvedProfile
from zing.models import KnowledgeEntryRef, KnowledgeUsage


def snapshot(resolved: ResolvedProfile) -> dict[str, Any]:
    return {
        "provider": resolved.provider.model_dump(mode="json", exclude={"models"}),
        "model": resolved.model.model_dump(mode="json"),
    }


def content_hash(snap: dict[str, Any]) -> str:
    canon = json.dumps(snap, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canon.encode("utf-8")).hexdigest()


def resolved_from_snapshot(snap: dict[str, Any], match_confidence: str | None = None) -> ResolvedProfile:
    """Rebuild a :class:`ResolvedProfile` from a stored snapshot (validates it)."""
    model = ModelProfile(**snap["model"])
    provider = ProviderProfile(**{**snap["provider"], "models": [model]})
    return ResolvedProfile(provider=provider, model=model, match_confidence=match_confidence or "exact")


# --------------------------------------------------------------------------- #
# kb_snapshots table — the same shape in history.db and watches.db
# --------------------------------------------------------------------------- #
def ensure_table(conn: sqlite3.Connection) -> None:
    """Create ``kb_snapshots``: one row per distinct profile content (by hash)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS kb_snapshots (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            content_hash  TEXT NOT NULL UNIQUE,
            provider      TEXT,
            model_id      TEXT,
            profile_json  TEXT NOT NULL,
            created_ts    REAL
        )
        """
    )


def put(conn: sqlite3.Connection, snap: dict[str, Any]) -> int:
    """Store ``snap`` once (deduplicated by content hash); return its row id."""
    digest = content_hash(snap)
    conn.execute(
        """INSERT OR IGNORE INTO kb_snapshots (content_hash, provider, model_id, profile_json, created_ts)
           VALUES (?, ?, ?, ?, ?)""",
        (
            digest,
            (snap.get("provider") or {}).get("provider"),
            (snap.get("model") or {}).get("id"),
            json.dumps(snap, ensure_ascii=False, sort_keys=True),
            time.time(),
        ),
    )
    row = conn.execute("SELECT id FROM kb_snapshots WHERE content_hash = ?", (digest,)).fetchone()
    return int(row[0])


def get(conn: sqlite3.Connection, snapshot_id: int | None) -> dict[str, Any] | None:
    if snapshot_id is None:
        return None
    row = conn.execute(
        "SELECT profile_json FROM kb_snapshots WHERE id = ?", (int(snapshot_id),)
    ).fetchone()
    if row is None:
        return None
    try:
        return json.loads(row[0])
    except (TypeError, ValueError):
        return None


def prune(conn: sqlite3.Connection, table: str) -> int:
    """Delete snapshots no row of ``table`` (column ``kb_snapshot_id``) points to."""
    cur = conn.execute(
        f"""DELETE FROM kb_snapshots WHERE id NOT IN (
               SELECT kb_snapshot_id FROM {table} WHERE kb_snapshot_id IS NOT NULL)"""
    )
    return cur.rowcount


def add_link_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    """Add missing columns (name -> SQL type) to an existing ``table``."""
    have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    for name, sql_type in columns.items():
        if name not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {sql_type}")


def knowledge_usage(
    kb: KnowledgeBase, resolved: ResolvedProfile | None, requested_model: str
) -> KnowledgeUsage:
    """Describe what a run audits against: match, sources, user entries, snapshot."""
    usage = KnowledgeUsage(
        requested_model=requested_model,
        user_kb=kb.user_kb,
        warnings=list(kb.warnings),
    )
    if resolved is None:
        return usage
    name, mid = resolved.provider.provider, resolved.model.id
    key = f"{name}/{mid}"
    refs = [kb.entries[k] for k in (f"provider:{name}", f"model:{key}") if k in kb.entries]
    snap = snapshot(resolved)
    return usage.model_copy(update={
        "matched": True,
        "match_confidence": resolved.match_confidence,
        "provider": name,
        "model_id": mid,
        "provider_source": kb.provider_sources.get(name),
        "model_source": kb.model_sources.get(key),
        "shadows": kb.shadowed.get(key),
        "user_entries": [KnowledgeEntryRef(**r) for r in refs],
        "profile_hash": content_hash(snap),
        "profile": snap,
    })
