"""Re-score a recorded run with this ekte version, from its evidence file.

A run that kept its evidence (:mod:`ekte.evidence`) holds every request it
sent and every response it received. :func:`rescore` runs the same audit again
— same options, same endpoints, the knowledge-base profile pinned from the
original report — but every client gets a :class:`ReplayTransport` instead of
the network: each request is answered with the recorded response to the same
request, chunk by chunk at the recorded arrival times, so the streaming and
performance checks measure what was measured then. Nothing reaches the relay.

Matching is exact: the endpoint (target, baseline, judge), method, URL path
and request body (JSON normalised, redacted like the file, the performance
probes' random request ids masked) must equal a recorded request; identical
requests are answered in recorded order. A detector of this version that asks
something the recorded run never asked gets no answer: it is marked
inconclusive (finding ``replay.missing``), never scored on a guess.

The re-scored report keeps the recorded run's request ``seq``\\ s (each record
takes the ``seq`` of the exchange that answered it), so its findings point
into the same, unchanged evidence file; its ``rescored_from`` says what was
replayed and what was missing.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import re
import time
from collections import Counter, deque
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from ekte import evidence
from ekte.models import (
    AuditReport,
    DetectorResult,
    EvidenceRef,
    Finding,
    KnowledgeUsage,
    RescoreRef,
    Severity,
    Status,
    TargetConfig,
)
from ekte.perf.recorder import current_detector, current_net_trace
from ekte.utils.redact import redact_text

# The performance probes open every request with a random 16-hex-digit id.
_NONCE = re.compile(r"(?<![0-9a-f])[0-9a-f]{16}(?![0-9a-f])")
# Headers that describe the original transfer, not the response.
_DROP_HEADERS = {"content-encoding", "content-length", "transfer-encoding"}

MISSING_ID = "replay.missing"


class ReplayMiss(httpx.TransportError):
    """No recorded exchange answers this request."""


def request_key(endpoint: str, method: str, url: str, body: str | None) -> tuple[str, str, str, str]:
    """What a request is matched on: endpoint, method, URL path and the body
    (JSON with sorted keys, performance-probe ids masked)."""
    text = body or ""
    with contextlib.suppress(ValueError):  # not JSON: compared as sent
        text = json.dumps(json.loads(text), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return endpoint, method.upper(), urlsplit(url).path, _NONCE.sub("<id>", text)


class _ReplayStream(httpx.AsyncByteStream):
    """A recorded body, delivered at the recorded chunk arrival times."""

    def __init__(self, body: bytes, chunks: list[list[float]], started: float, raw_total: int) -> None:
        self.body, self.chunks, self.started, self.raw_total = body, chunks, started, raw_total

    async def __aiter__(self) -> Any:
        if not self.chunks or not self.raw_total:
            yield self.body
            return
        sent = 0
        for at_ms, received in self.chunks:
            delay = self.started + at_ms / 1000 - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
            # recorded sizes are encoded bytes: cut the decoded body in proportion
            upto = len(self.body) if received >= self.raw_total else round(len(self.body) * received / self.raw_total)
            if upto > sent:
                yield self.body[sent:upto]
                sent = upto
        if sent < len(self.body):
            yield self.body[sent:]


class Replay:
    """The recorded exchanges of one run, handed out to a re-scoring audit."""

    def __init__(
        self,
        lines: list[dict[str, Any]],
        *,
        ref: EvidenceRef,
        tool_version: str | None = None,
        generated_at: str | None = None,
        report_id: int | None = None,
    ) -> None:
        self.evidence = ref
        self._tool_version, self._generated_at, self._report_id = tool_version, generated_at, report_id
        self._queues: dict[tuple[str, str, str, str], deque[dict[str, Any]]] = {}
        for line in lines:
            req = line.get("request") or {}
            key = request_key(
                str(line.get("endpoint")), str(req.get("method", "")), str(req.get("url", "")),
                (req.get("body") or {}).get("text"),
            )
            self._queues.setdefault(key, deque()).append(line)
        self.total = len(lines)
        self.replayed = 0
        self.missing: Counter[str] = Counter()

    # -- serving -------------------------------------------------------------- #
    def take(self, endpoint: str, request: httpx.Request) -> dict[str, Any] | None:
        try:
            body: str | None = request.content.decode("utf-8")
        except (httpx.RequestNotRead, UnicodeDecodeError):
            body = None
        # the file's bodies are redacted: compare like with like
        key = request_key(endpoint, request.method, str(request.url), redact_text(body) if body else body)
        queue = self._queues.get(key)
        if not queue:
            self.missing[current_detector() or "-"] += 1
            return None
        self.replayed += 1
        return queue.popleft()

    def transport(self, endpoint: str) -> ReplayTransport:
        return ReplayTransport(self, endpoint)

    # -- results -------------------------------------------------------------- #
    def after_detector(self, result: DetectorResult) -> DetectorResult:
        """A detector that asked something the recorded run never asked is
        inconclusive: its score would rest on answers that do not exist."""
        missed = self.missing.get(result.id, 0)
        if not missed:
            return result
        result.status = Status.INCONCLUSIVE
        result.score = None
        result.findings.append(
            Finding(
                id=MISSING_ID,
                title="Not re-scored: the recorded run has no answer to some requests",
                status=Status.INCONCLUSIVE,
                severity=Severity.INFO,
                summary=(
                    f"{missed} request(s) this check sends now were not sent in the recorded run, "
                    "so there is no recorded answer; the check reads inconclusive instead of "
                    "being scored on a guess. Run a new audit to score it."
                ),
                evidence={"missing_requests": missed},
                evidence_seqs=[],
            )
        )
        return result

    def summary(self) -> RescoreRef:
        return RescoreRef(
            run_id=self.evidence.run_id,
            evidence_sha256=self.evidence.sha256,
            tool_version=self._tool_version,
            generated_at=self._generated_at,
            report_id=self._report_id,
            replayed=self.replayed,
            missing=dict(self.missing),
            unused=self.total - self.replayed,
        )


class ReplayTransport(httpx.AsyncBaseTransport):
    """An httpx transport that answers from the recorded exchanges."""

    def __init__(self, replay: Replay, endpoint: str) -> None:
        self.replay, self.endpoint = replay, endpoint

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        started = time.perf_counter()
        line = self.replay.take(self.endpoint, request)
        if line is None:
            raise ReplayMiss("no recorded answer to this request", request=request)
        net = current_net_trace()
        if net is not None:
            net.replayed_seq = line.get("seq")
        resp = line.get("response")
        if resp is None:  # the recorded call got no response either
            raise httpx.ConnectError(str(line.get("error") or "no response recorded"), request=request)
        body_rec = resp.get("body") or {}
        text = body_rec.get("text") or ""
        body = base64.b64decode(text) if body_rec.get("encoding") == "base64" else text.encode("utf-8")
        chunks = [list(c) for c in resp.get("chunks") or []]
        raw_total = int(chunks[-1][1]) if chunks else 0
        # the headers arrive with the first chunk of the body
        if chunks:
            delay = started + chunks[0][0] / 1000 - time.perf_counter()
            if delay > 0:
                await asyncio.sleep(delay)
        headers = [
            (k.encode("latin-1", "replace"), str(v).encode("utf-8"))
            for k, v in (resp.get("headers") or {}).items()
            if k.lower() not in _DROP_HEADERS
        ]
        version = str(resp.get("http_version") or "HTTP/1.1").encode("ascii", "replace")
        return httpx.Response(
            int(resp.get("status") or 0),
            headers=headers,
            stream=_ReplayStream(body, chunks, started, raw_total),
            request=request,
            extensions={"http_version": version},
        )


# --------------------------------------------------------------------------- #
# Re-scoring
# --------------------------------------------------------------------------- #
def _config(t: dict[str, Any] | None, kind: str) -> TargetConfig | None:
    if not t:
        return None
    return TargetConfig(
        name=t.get("name") or kind,
        kind=kind,
        base_url=t["base_url"],
        model=t["model"],
        claimed_model=t.get("claimed_model"),
        declared_provider=t.get("declared_provider"),
        # auto-detected then: detected again (to the same protocol), so the
        # report says so as the original did
        api="auto" if t.get("api_auto") is not False else (t.get("api") or "auto"),
        # the replay never sends a key: requests go to the recorded file
        api_key="",
    )


# Why a file cannot be replayed for a report: fixed texts, safe to show a client.
NO_EVIDENCE = "this report kept no evidence: there is nothing to replay"
HASH_DIFFERS = "the evidence file is not the one the report names (its SHA-256 differs)"
NO_OPTIONS = "this evidence file does not record the run's options; it cannot be replayed"
NO_TARGET = "this evidence file names no target"
UNREADABLE = "the evidence file cannot be read"


def refusal(report: dict[str, Any], path: Path) -> str | None:
    """Why ``path`` cannot be replayed for ``report`` (one of the fixed texts
    above), or None when it can. Blocking: reads and hashes the file."""
    ref_raw = report.get("evidence")
    if not isinstance(ref_raw, dict):
        return NO_EVIDENCE
    if evidence.sha256_of(path) != EvidenceRef(**ref_raw).sha256:
        return HASH_DIFFERS
    try:
        head = evidence.header(path) or {}
    except evidence.EvidenceVersionError:
        return evidence.EvidenceVersionError.PUBLIC
    except ValueError:
        return UNREADABLE
    if not head.get("options"):
        return NO_OPTIONS
    if not head.get("target"):
        return NO_TARGET
    return None


def check(report: dict[str, Any], path: Path) -> tuple[EvidenceRef, list[dict[str, Any]]]:
    """The report's evidence reference and the file's lines, if ``path`` can
    be replayed for ``report`` (blocking); else ``ValueError`` saying why."""
    reason = refusal(report, path)
    if reason is not None:
        raise ValueError(reason)
    return EvidenceRef(**report["evidence"]), list(evidence.iter_lines(path))


async def rescore(
    report: dict[str, Any],
    path: Path,
    *,
    report_id: int | None = None,
    on_event: Any = None,
) -> AuditReport:
    """Run ``report``'s audit again with this ekte version, answering every
    request from its evidence file ``path``.

    Raises ``ValueError`` when the file is not the one the report names (its
    SHA-256 differs), lacks the run's options, or is of an unknown version.
    """
    from ekte.config import AuditOptions
    from ekte.runner import run_audit

    ref, lines = await asyncio.to_thread(check, report, path)
    head = lines[0]
    options = AuditOptions(**head["options"])
    target = _config(head.get("target"), "target")
    assert target is not None  # check() refuses a file without one
    baseline = _config(head.get("baseline"), "baseline")
    judge = _config(head.get("judge"), "judge")
    knowledge = report.get("knowledge")
    pinned = (
        KnowledgeUsage(**knowledge)
        if isinstance(knowledge, dict) and isinstance(knowledge.get("profile"), dict)
        else None
    )
    replay = Replay(
        [x for x in lines if x.get("type") == "exchange"],
        ref=ref,
        tool_version=report.get("tool_version"),
        generated_at=report.get("generated_at"),
        report_id=report_id,
    )
    new = await run_audit(
        target,
        options,
        baseline=baseline,
        judge_target=judge if options.judge else None,
        mode=str(report.get("mode") or "check"),
        command=f"ekte rescore {report_id}" if report_id is not None else "ekte rescore",
        pinned=pinned,
        on_event=on_event,
        replay=replay,
    )
    if new.knowledge is not None and pinned is not None:
        # the original run's profile: pinned as that run had it (by a monitor or not)
        new.knowledge.pinned = bool(knowledge.get("pinned")) if isinstance(knowledge, dict) else False
    return new
