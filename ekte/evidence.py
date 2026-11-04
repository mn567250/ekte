"""Evidence files: every raw HTTP request/response pair of an audit run.

A run that keeps evidence writes one file, ``<run_id>.jsonl.zst``: JSON Lines
compressed as one zstd stream. The first line is a :class:`EvidenceHeader`,
every further line one :class:`EvidenceExchange` (one HTTP request and its
response). Each line validates against ``ekte/schemas/evidence.schema.json``
(generated from these models, versioned like the report schema).

Capture happens in the HTTP clients (:mod:`ekte.clients.base`): an httpx
request hook copies the request, a response hook tees the response body as it
is read, with the arrival time of every chunk. A captured call is handed to
the run's :class:`EvidenceWriter` together with the ``seq`` of its
:class:`~ekte.models.RequestRecord`, so ``(run_id, seq)`` finds the pair of
any request the report lists. Calls without a record (the LLM judge, the
media auditor) are kept with ``seq`` None.

The writer serialises, redacts and compresses on a thread of its own, so the
event loop the audit times its requests on never waits for it. Every line is
flushed as a zstd block: a run that crashes leaves a readable ``.part`` file
up to the last line written. :meth:`EvidenceWriter.close` ends the stream,
renames the file into place and returns the :class:`~ekte.models.EvidenceRef`
the report carries (file name, SHA-256, line count).

Secrets: bodies and headers go through :mod:`ekte.utils.redact` with the
run's API keys before they are written; ``Authorization``, ``Cookie``,
``Set-Cookie`` and the other sensitive headers are masked outright.
"""

from __future__ import annotations

import base64
import contextlib
import hashlib
import io
import json
import os
import queue
import threading
import time
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, RootModel

from ekte.models import EVIDENCE_SCHEMA_VERSION, EvidenceRef, RedactedTarget
from ekte.utils.redact import redact_headers, redact_text

SUFFIX = ".jsonl.zst"
PART = ".part"
DIR_NAME = "evidence"
# zstd level of the stream (the size/speed trade-off measured for issue #88).
LEVEL = 3
# Bodies longer than this are cut (their full size and hash stay in the line):
# a guard against a relay that streams without end, far above any probe.
MAX_BODY_BYTES = 64 * 1024 * 1024
# Response chunks timed per exchange, at most; later chunks still go into the
# body but are not timed one by one.
MAX_CHUNKS = 100_000
# Partial files of runs that died, and files no history row claims, are
# removed once they are this old (a running audit keeps writing its file).
STALE_SEC = 24 * 3600

_FILE_MODE = 0o600


# --------------------------------------------------------------------------- #
# Line models (the schema of the file)
# --------------------------------------------------------------------------- #
class EvidenceHeader(BaseModel):
    """The first line of an evidence file: what run the pairs belong to."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["header"] = "header"
    schema_version: str = EVIDENCE_SCHEMA_VERSION
    tool_version: str
    run_id: str
    # When the run started (ISO UTC): every ``start_ms`` counts from here, the
    # same instant as the report's ``started_at``.
    started_at: str
    mode: str  # "check" | "compare" | "image" | "audio"
    suite: str | None = None
    surface: str | None = None
    target: RedactedTarget
    baseline: RedactedTarget | None = None
    # The LLM judge's endpoint (None: no judge ran).
    judge: RedactedTarget | None = None
    # The run's AuditOptions, so a replay (ekte.replay) can run the same audit.
    options: dict[str, Any] | None = None


class EvidenceBody(BaseModel):
    """A request or response body as it was sent or received."""

    model_config = ConfigDict(extra="forbid")

    # The body (decoded from any ``Content-Encoding``), redacted; None when
    # there was none. Text when it is UTF-8, else base64 (``encoding``).
    text: str | None = None
    encoding: Literal["utf-8", "base64"] = "utf-8"
    # Size and SHA-256 of the body before redaction and cutting.
    bytes: int = 0
    sha256: str | None = None
    # True when the body was cut at MAX_BODY_BYTES.
    truncated: bool = False


class EvidenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: str
    url: str
    headers: dict[str, str] = Field(default_factory=dict)
    body: EvidenceBody = Field(default_factory=EvidenceBody)


class EvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: int
    http_version: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    body: EvidenceBody = Field(default_factory=EvidenceBody)
    # Arrival of the body, chunk by chunk as the transport delivered it:
    # ``[ms since the request started, bytes received so far]`` (encoded
    # bytes, before any Content-Encoding is undone). For a stream this is the
    # timing the streaming and performance checks measured.
    chunks: list[tuple[float, int]] = Field(default_factory=list)
    # When the last byte arrived, ms since the request started.
    done_ms: float | None = None
    # True when the body was read until the transport reported its end. A
    # stream the client stops reading at its final event (``data: [DONE]``),
    # a deadline or an error reads False: what arrived until then is above.
    read_to_end: bool = True


class EvidenceExchange(BaseModel):
    """One HTTP request and its response (None when none arrived)."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["exchange"] = "exchange"
    # Unique within the file, in the order the calls finished (1, 2, …).
    id: int
    # The RequestRecord this exchange belongs to (``performance.requests``,
    # ``history_requests``); None for calls without a record (LLM judge, media).
    seq: int | None = None
    endpoint: str  # "target" | "baseline" | "judge"
    detector: str | None = None
    op: str = "complete"
    # When the request started, ms since the run started.
    start_ms: float
    request: EvidenceRequest
    response: EvidenceResponse | None = None
    # The error of a failed call (the client's redacted message), else None.
    error: str | None = None


class EvidenceLine(RootModel[Annotated[EvidenceHeader | EvidenceExchange, Field(discriminator="type")]]):
    """Any line of an evidence file."""


# --------------------------------------------------------------------------- #
# Capture (filled by the client's httpx hooks)
# --------------------------------------------------------------------------- #
@dataclass
class Capture:
    """One HTTP exchange as the hooks saw it, raw (redacted when written)."""

    method: str
    url: str
    request_headers: dict[str, str]
    request_body: bytes | None
    started: float  # perf_counter at the request hook
    status: int | None = None
    http_version: str | None = None
    response_headers: dict[str, str] = field(default_factory=dict)
    raw: bytearray = field(default_factory=bytearray)
    raw_total: int = 0
    chunks: list[tuple[float, int]] = field(default_factory=list)
    done: float | None = None
    complete: bool = False
    # True when ``raw`` already holds the decoded body.
    decoded: bool = False

    @classmethod
    def of_request(cls, request: httpx.Request) -> Capture:
        try:
            body: bytes | None = request.content
        except httpx.RequestNotRead:  # a streamed upload: ekte sends none
            body = None
        return cls(
            method=request.method,
            url=str(request.url),
            request_headers=dict(request.headers.items()),
            request_body=body,
            started=time.perf_counter(),
        )

    def on_response(self, response: httpx.Response) -> None:
        self.status = response.status_code
        self.http_version = response.http_version
        self.response_headers = dict(response.headers.items())
        if response.is_stream_consumed:
            # Built from bytes and read at once (in-process transports):
            # nothing left to tee, the decoded body is all there is.
            body = response.content
            self.raw += body[:MAX_BODY_BYTES]
            self.raw_total = len(body)
            self.decoded = True
            self.done = time.perf_counter()
            self.chunks.append((round((self.done - self.started) * 1000, 3), len(body)))
            self.complete = True
            return
        response.stream = _TeeStream(response.stream, self)


class _TeeStream(httpx.AsyncByteStream):
    """Pass a response body through, keeping a copy and the chunk timings."""

    def __init__(self, inner: Any, capture: Capture) -> None:
        self._inner = inner
        self._capture = capture

    async def __aiter__(self) -> Any:
        cap = self._capture
        async for chunk in self._inner:
            now = time.perf_counter()
            cap.raw_total += len(chunk)
            if len(cap.raw) < MAX_BODY_BYTES:
                cap.raw += chunk[: MAX_BODY_BYTES - len(cap.raw)]
            if len(cap.chunks) < MAX_CHUNKS:
                cap.chunks.append((round((now - cap.started) * 1000, 3), cap.raw_total))
            cap.done = now
            yield chunk
        cap.complete = True
        if cap.done is None:
            cap.done = time.perf_counter()

    async def aclose(self) -> None:
        aclose = getattr(self._inner, "aclose", None)
        if aclose is not None:
            await aclose()


# --------------------------------------------------------------------------- #
# Writing
# --------------------------------------------------------------------------- #
# Set (to 1/true/yes) to keep no evidence for runs saved to history, e.g.
# ``ekte serve --no-evidence``.
ENV_OFF = "EKTE_NO_EVIDENCE"


def default_on() -> bool:
    """Whether runs saved to history keep their evidence (the default)."""
    return os.environ.get(ENV_OFF, "").strip().lower() not in ("1", "true", "yes", "on")


def new_run_id() -> str:
    return uuid.uuid4().hex


def evidence_dir(base: Path | None = None) -> Path:
    """The data directory's evidence folder (created owner-only)."""
    if base is None:
        from ekte import datadir

        base = datadir.ensure_data_dir()
    path = base / DIR_NAME
    if not path.is_dir():
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        with contextlib.suppress(OSError):
            path.chmod(0o700)
    return path


def data_dir_path(run_id: str) -> Path:
    """Where a run saved to history keeps its evidence."""
    return evidence_dir() / f"{run_id}{SUFFIX}"


def stored_file(name: str | None) -> Path | None:
    """The data directory's evidence file of that (bare) name, if it exists."""
    if not name or "/" in name or "\\" in name or not name.endswith(SUFFIX) or name.startswith("."):
        return None
    from ekte import datadir

    path = datadir.data_dir() / DIR_NAME / name
    return path if path.is_file() else None


def _body(data: bytes | None, secrets: list[str | None]) -> EvidenceBody:
    if data is None:
        return EvidenceBody()
    size, digest = len(data), hashlib.sha256(data).hexdigest()
    cut = data[:MAX_BODY_BYTES]
    try:
        text = cut.decode("utf-8")
    except UnicodeDecodeError:
        return EvidenceBody(
            text=base64.b64encode(cut).decode("ascii"), encoding="base64",
            bytes=size, sha256=digest, truncated=len(cut) < size,
        )
    return EvidenceBody(
        text=redact_text(text, extra_secrets=secrets), bytes=size, sha256=digest,
        truncated=len(cut) < size,
    )


def _decoded(cap: Capture) -> bytes:
    """The response body with its Content-Encoding undone (as the client read it)."""
    raw = bytes(cap.raw)
    if cap.decoded or not raw or not cap.response_headers.get("content-encoding"):
        return raw
    try:
        return httpx.Response(200, headers=cap.response_headers, content=raw).content
    except Exception:  # a body cut mid-stream, an unknown encoding: keep it as sent
        return raw


def exchange_line(
    cap: Capture,
    *,
    line_id: int,
    t0: float,
    secrets: list[str | None],
    seq: int | None,
    endpoint: str,
    detector: str | None,
    op: str,
    error: str | None,
) -> EvidenceExchange:
    """The redacted line for one captured exchange."""
    response = None
    if cap.status is not None:
        body = _body(_decoded(cap), secrets)
        if cap.raw_total > len(cap.raw):  # cut while teeing: the size as received
            body.truncated, body.bytes, body.sha256 = True, cap.raw_total, None
        response = EvidenceResponse(
            status=cap.status,
            http_version=cap.http_version,
            headers=redact_headers(cap.response_headers, extra_secrets=secrets),
            body=body,
            chunks=list(cap.chunks),
            done_ms=round((cap.done - cap.started) * 1000, 3) if cap.done is not None else None,
            read_to_end=cap.complete,
        )
    return EvidenceExchange(
        id=line_id,
        seq=seq,
        endpoint=endpoint,
        detector=detector,
        op=op,
        start_ms=round((cap.started - t0) * 1000, 3),
        request=EvidenceRequest(
            method=cap.method,
            url=redact_text(cap.url, extra_secrets=secrets),
            headers=redact_headers(cap.request_headers, extra_secrets=secrets),
            body=_body(cap.request_body, secrets),
        ),
        response=response,
        error=redact_text(error, extra_secrets=secrets) or None if error else None,
    )


@dataclass
class _Item:
    captures: list[Capture]
    seq: int | None
    endpoint: str
    detector: str | None
    op: str
    error: str | None


_STOP = object()


class EvidenceWriter:
    """Writes one run's evidence file on a background thread.

    :meth:`add` only queues (safe and cheap on the event loop);
    :meth:`close` waits for the queue, ends the zstd stream and moves the
    ``.part`` file into place.
    """

    def __init__(
        self,
        path: Path,
        header: EvidenceHeader,
        *,
        t0: float,
        secrets: list[str | None] | None = None,
    ) -> None:
        import zstandard

        self.path = Path(path)
        self.run_id = header.run_id
        self.t0 = t0
        self.secrets: list[str | None] = [s for s in (secrets or []) if s]
        self._part = self.path.with_name(self.path.name + PART)
        self._part.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _FILE_MODE)
        self._file = os.fdopen(fd, "wb")
        self._zstd = zstandard
        self._stream = zstandard.ZstdCompressor(level=LEVEL).stream_writer(self._file, closefd=False)
        self._lines = 0
        self._next_id = 0
        self._queue: queue.Queue[Any] = queue.Queue()
        self._error: BaseException | None = None
        self._closed = False
        self._write(header)
        self._thread = threading.Thread(target=self._run, name=f"ekte-evidence-{self.run_id[:8]}", daemon=True)
        self._thread.start()

    # -- producer side (event loop) ----------------------------------------- #
    def add(
        self,
        captures: list[Capture],
        *,
        seq: int | None,
        endpoint: str,
        detector: str | None,
        op: str,
        error: str | None = None,
    ) -> None:
        if self._closed or not captures:
            return
        self._queue.put(_Item(list(captures), seq, endpoint, detector, op, error))

    def close(self) -> EvidenceRef:
        """Finish the file; returns its reference for the report. Blocking:
        call it off the event loop (``asyncio.to_thread``)."""
        if not self._closed:
            self._closed = True
            self._queue.put(_STOP)
            self._thread.join()
            self._stream.close()  # ends the zstd frame
            self._file.flush()
            with contextlib.suppress(OSError):
                os.fsync(self._file.fileno())
            self._file.close()
            os.replace(self._part, self.path)
        digest = hashlib.sha256()
        with open(self.path, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                digest.update(block)
        return EvidenceRef(
            run_id=self.run_id,
            file=self.path.name,
            sha256=digest.hexdigest(),
            exchanges=self._lines - 1,
            bytes=self.path.stat().st_size,
            complete=self._error is None,
        )

    def abort(self) -> None:
        """Stop and delete the file (the run produced no report)."""
        if not self._closed:
            self._closed = True
            self._queue.put(_STOP)
            self._thread.join()
            with contextlib.suppress(Exception):
                self._stream.close()
            with contextlib.suppress(Exception):
                self._file.close()
        for p in (self._part, self.path):
            with contextlib.suppress(OSError):
                p.unlink()

    # -- consumer side (thread) --------------------------------------------- #
    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is _STOP:
                return
            if self._error is not None:
                continue  # a failed write ends the file; drain the queue
            try:
                for cap in item.captures:
                    self._next_id += 1
                    self._write(
                        exchange_line(
                            cap, line_id=self._next_id, t0=self.t0, secrets=self.secrets,
                            seq=item.seq, endpoint=item.endpoint, detector=item.detector,
                            op=item.op, error=item.error,
                        )
                    )
            except Exception as exc:  # disk full and the like: never break the audit
                self._error = exc

    def _write(self, line: BaseModel) -> None:
        data = line.model_dump_json(exclude_none=False).encode("utf-8") + b"\n"
        self._stream.write(data)
        self._stream.flush(self._zstd.FLUSH_BLOCK)
        self._lines += 1


# --------------------------------------------------------------------------- #
# Reading
# --------------------------------------------------------------------------- #
def iter_lines(path: Path) -> Iterator[dict[str, Any]]:
    """Every line of an evidence file as a dict, validated against the models.

    A ``.part`` file (or one cut short) yields its complete lines and stops.
    Raises ``ValueError`` for a file of a newer major schema version.
    """
    import zstandard

    with open(path, "rb") as fh:
        reader = zstandard.ZstdDecompressor().stream_reader(fh, read_across_frames=True)
        text = io.TextIOWrapper(reader, encoding="utf-8")
        first = True
        try:
            for raw in text:
                if not raw.endswith("\n"):
                    return  # cut mid-line
                data = json.loads(raw)
                if first:
                    first = False
                    version = str(data.get("schema_version") or "1.0")
                    major = version.split(".", 1)[0]
                    if major != EVIDENCE_SCHEMA_VERSION.split(".", 1)[0]:
                        raise ValueError(
                            f"evidence file schema {version} is not supported by this ekte "
                            f"(reads {EVIDENCE_SCHEMA_VERSION.split('.', 1)[0]}.x)"
                        )
                yield data
        except zstandard.ZstdError:
            return  # a truncated stream: what was flushed has been read


def header(path: Path) -> dict[str, Any] | None:
    for line in iter_lines(path):
        return line if line.get("type") == "header" else None
    return None


def exchanges(path: Path, seq: int | None = None, line_id: int | None = None) -> list[dict[str, Any]]:
    """The exchange lines of a file: all, those of one ``seq``, or one ``id``."""
    out = []
    for line in iter_lines(path):
        if line.get("type") != "exchange":
            continue
        if line_id is not None and line.get("id") != line_id:
            continue
        if seq is not None and line.get("seq") != seq:
            continue
        out.append(line)
        if line_id is not None:
            break
    return out


def index(path: Path) -> list[dict[str, Any]]:
    """A light listing of every exchange (no bodies), for a UI."""
    rows = []
    for line in iter_lines(path):
        if line.get("type") != "exchange":
            continue
        req = line.get("request") or {}
        resp = line.get("response") or {}
        rows.append({
            "id": line.get("id"),
            "seq": line.get("seq"),
            "endpoint": line.get("endpoint"),
            "detector": line.get("detector"),
            "op": line.get("op"),
            "start_ms": line.get("start_ms"),
            "method": req.get("method"),
            "url": req.get("url"),
            "status": resp.get("status") if resp else None,
            "request_bytes": (req.get("body") or {}).get("bytes", 0),
            "response_bytes": (resp.get("body") or {}).get("bytes", 0) if resp else 0,
            "error": line.get("error"),
        })
    return rows


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


# --------------------------------------------------------------------------- #
# Housekeeping
# --------------------------------------------------------------------------- #
def sweep(keep: set[str], *, now: float | None = None, base: Path | None = None) -> int:
    """Delete stale files of the data directory's evidence folder: ``.part``
    files and files no history row names (``keep``), older than STALE_SEC.
    Returns how many were removed."""
    if base is None:
        from ekte import datadir

        base = datadir.data_dir()
    folder = base / DIR_NAME
    if not folder.is_dir():
        return 0
    now = time.time() if now is None else now
    removed = 0
    for path in folder.iterdir():
        name = path.name
        if not (name.endswith(SUFFIX) or name.endswith(SUFFIX + PART)):
            continue
        if name in keep:
            continue
        try:
            if now - path.stat().st_mtime < STALE_SEC:
                continue
            path.unlink()
            removed += 1
        except OSError:
            continue
    return removed


def remove(name: str | None) -> None:
    """Delete the data directory's evidence file of that name (if any)."""
    path = stored_file(name)
    if path is not None:
        with contextlib.suppress(OSError):
            path.unlink()


# --------------------------------------------------------------------------- #
# Export: one JSON document, HAR, a curl script
# --------------------------------------------------------------------------- #
EXPORT_FORMATS = ("json", "har", "curl")
# Headers curl sets itself, or that describe the original transfer only.
_CURL_SKIP = {"host", "content-length", "accept-encoding", "connection", "user-agent"}
# Masked auth headers come back as a reference to an environment variable.
_AUTH_HEADERS = {"authorization", "x-api-key", "api-key", "x-goog-api-key", "proxy-authorization"}


def _selected(path: Path, seqs: list[int] | None) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    head: dict[str, Any] = {}
    lines: list[dict[str, Any]] = []
    wanted = set(seqs) if seqs else None
    for line in iter_lines(path):
        if line.get("type") == "header":
            head = line
        elif line.get("type") == "exchange" and (wanted is None or line.get("seq") in wanted):
            lines.append(line)
    return head, lines


def export_json(path: Path, seqs: list[int] | None = None) -> dict[str, Any]:
    """The file (or the exchanges of ``seqs``) as one JSON document."""
    head, lines = _selected(path, seqs)
    return {"header": head, "exchanges": lines}


def _har_headers(headers: dict[str, str] | None) -> list[dict[str, str]]:
    return [{"name": k, "value": v} for k, v in (headers or {}).items()]


def _har_content(body: dict[str, Any] | None, mime: str) -> dict[str, Any]:
    body = body or {}
    out: dict[str, Any] = {"size": body.get("bytes", 0), "mimeType": mime}
    if body.get("text") is not None:
        out["text"] = body["text"]
        if body.get("encoding") == "base64":
            out["encoding"] = "base64"
    return out


def export_har(path: Path, seqs: list[int] | None = None) -> dict[str, Any]:
    """The exchanges as an HTTP Archive (HAR 1.2), for browser dev tools and
    HAR viewers. Timings: ``wait`` is the time to the first byte of the body,
    ``receive`` the rest; ekte's own fields go in ``_ekte``."""
    from datetime import datetime, timedelta

    from ekte import __version__

    head, lines = _selected(path, seqs)
    try:
        t0 = datetime.fromisoformat(str(head.get("started_at")))
    except ValueError:
        t0 = None
    entries = []
    for x in lines:
        req, resp = x.get("request") or {}, x.get("response")
        started = (t0 + timedelta(milliseconds=x.get("start_ms") or 0)).isoformat() if t0 else ""
        req_mime = (req.get("headers") or {}).get("content-type", "")
        first = (resp or {}).get("chunks") or []
        done = (resp or {}).get("done_ms")
        wait = first[0][0] if first else (done or 0)
        entry: dict[str, Any] = {
            "startedDateTime": started,
            "time": done if done is not None else -1,
            "request": {
                "method": req.get("method", ""),
                "url": req.get("url", ""),
                "httpVersion": (resp or {}).get("http_version") or "HTTP/1.1",
                "cookies": [],
                "headers": _har_headers(req.get("headers")),
                "queryString": [],
                "headersSize": -1,
                "bodySize": (req.get("body") or {}).get("bytes", 0),
            },
            "response": {
                "status": (resp or {}).get("status", 0),
                "statusText": "",
                "httpVersion": (resp or {}).get("http_version") or "HTTP/1.1",
                "cookies": [],
                "headers": _har_headers((resp or {}).get("headers")),
                "content": _har_content(
                    (resp or {}).get("body"), ((resp or {}).get("headers") or {}).get("content-type", "")
                ),
                "redirectURL": "",
                "headersSize": -1,
                "bodySize": ((resp or {}).get("body") or {}).get("bytes", 0) if resp else -1,
            },
            "cache": {},
            "timings": {
                "send": 0,
                "wait": wait,
                "receive": max(0.0, (done or wait) - wait),
            },
            "_ekte": {k: x.get(k) for k in ("id", "seq", "endpoint", "detector", "op", "error")},
        }
        if (req.get("body") or {}).get("text") is not None:
            entry["request"]["postData"] = {"mimeType": req_mime, "text": req["body"]["text"]}
        entries.append(entry)
    return {
        "log": {
            "version": "1.2",
            "creator": {"name": "ekte", "version": __version__},
            "comment": f"ekte evidence, run {head.get('run_id', '?')} (keys removed)",
            "entries": entries,
        }
    }


def _sh(value: str) -> str:
    """Single-quote ``value`` for a POSIX shell."""
    return "'" + value.replace("'", "'\\''") + "'"


def export_curl(path: Path, seqs: list[int] | None = None) -> str:
    """A POSIX shell script that sends the exchanges' requests again with curl.

    The relay's key is not in the file: masked auth headers read it from
    ``$EKTE_API_KEY`` instead. Binary request bodies are left out.
    """
    head, lines = _selected(path, seqs)
    out = [
        "#!/bin/sh",
        f"# ekte evidence, run {head.get('run_id', '?')}: the requests again, with curl.",
        "# Set EKTE_API_KEY first; ekte never stores the key in the evidence file.",
        "set -e",
        "",
    ]
    for x in lines:
        req = x.get("request") or {}
        label = f"seq {x['seq']}" if x.get("seq") is not None else f"line {x.get('id')}"
        out.append(f"# {label} · {x.get('endpoint')} · {x.get('detector') or '-'} · {x.get('op')}")
        args = [f"curl -sS -X {_sh(str(req.get('method', 'GET')))} {_sh(str(req.get('url', '')))}"]
        for k, v in (req.get("headers") or {}).items():
            low = k.lower()
            if low in _CURL_SKIP or low == "cookie":
                continue
            if low in _AUTH_HEADERS:
                ref = "Bearer ${EKTE_API_KEY}" if low == "authorization" else "${EKTE_API_KEY}"
                args.append(f'-H "{k}: {ref}"')
            else:
                args.append(f"-H {_sh(f'{k}: {v}')}")
        body = req.get("body") or {}
        has_body = body.get("text") is not None and body.get("encoding") != "base64"
        delim = "EKTE_BODY"
        while has_body and delim in body["text"]:
            delim += "_"  # a body that contains the delimiter gets a longer one
        if has_body:
            args.append(f"--data-binary @- <<'{delim}'")
        out.append(" \\\n  ".join(args))
        if has_body:
            out.append(body["text"])
            out.append(delim)
        out.append("echo")
        out.append("")
    return "\n".join(out)
