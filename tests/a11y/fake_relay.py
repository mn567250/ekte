"""A tiny OpenAI-compatible relay on 127.0.0.1 for the browser flows.

Standard library only (``http.server`` in a thread): the web app under test
talks to it like to any relay, so an audit, the embedding check and the rerank
check run end to end without touching the internet. ``fail=True`` makes every
endpoint answer HTTP 500, for the failure paths; ``delay`` (seconds) holds
every POST that long, so a run lasts long enough to watch it.
"""

from __future__ import annotations

import hashlib
import json
import math
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

MODEL = "gpt-4o-mini"
EMBED_DIM = 64


def _vector(text: str) -> list[float]:
    """Deterministic unit vector per input (different inputs differ)."""
    raw = hashlib.sha256(text.encode("utf-8")).digest() * (EMBED_DIM // 32 + 1)
    v = [(b - 127.5) / 127.5 for b in raw[:EMBED_DIM]]
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def _overlap(query: str, doc: str) -> float:
    q = {w.strip(".,?!").lower() for w in query.split()}
    d = {w.strip(".,?!").lower() for w in doc.split()}
    return len(q & d) / (len(q) or 1)


def _reply(body: dict[str, Any]) -> str:
    text = " ".join(
        m.get("content", "") for m in body.get("messages", []) if isinstance(m.get("content"), str)
    )
    low = text.lower()
    if "nothing else:" in low:
        return text[low.index("nothing else:") + len("nothing else:") :].strip() or "ok"
    return "The quick brown fox jumps over the lazy dog."


class _Handler(BaseHTTPRequestHandler):
    server: _Server  # type: ignore[assignment]
    protocol_version = "HTTP/1.1"

    def log_message(self, *args: Any) -> None:  # quiet
        pass

    def _json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict[str, Any]:
        n = int(self.headers.get("Content-Length") or 0)
        try:
            return json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            return {}

    def do_GET(self) -> None:  # noqa: N802
        if self.server.fail:
            return self._json(500, {"error": {"message": "relay is down", "type": "server_error"}})
        if self.path.rstrip("/").endswith("/models"):
            return self._json(200, {"object": "list", "data": [{"id": MODEL, "object": "model"}]})
        self._json(404, {"error": {"message": "not found"}})

    def do_POST(self) -> None:  # noqa: N802
        body = self._body()
        if self.server.delay:
            time.sleep(self.server.delay)
        if self.server.fail:
            return self._json(500, {"error": {"message": "relay is down", "type": "server_error"}})
        path = self.path.rstrip("/")
        if path.endswith("/embeddings"):
            inputs = body.get("input") or []
            inputs = [inputs] if isinstance(inputs, str) else inputs
            return self._json(200, {
                "object": "list",
                "model": body.get("model") or MODEL,
                "data": [{"object": "embedding", "index": i, "embedding": _vector(str(t))} for i, t in enumerate(inputs)],
                "usage": {"prompt_tokens": 8, "total_tokens": 8},
            })
        if path.endswith("/rerank"):
            q, docs = str(body.get("query") or ""), [str(d) for d in body.get("documents") or []]
            res = [{"index": i, "relevance_score": _overlap(q, d)} for i, d in enumerate(docs)]
            res.sort(key=lambda r: -r["relevance_score"])
            return self._json(200, {"model": body.get("model") or MODEL, "results": res})
        if path.endswith("/chat/completions"):
            return self._chat(body)
        self._json(404, {"error": {"message": f"no route for {path}"}})

    def _chat(self, body: dict[str, Any]) -> None:
        text = _reply(body)
        usage = {"prompt_tokens": 20, "completion_tokens": len(text.split()), "total_tokens": 20 + len(text.split())}
        if not body.get("stream"):
            return self._json(200, {
                "id": "chatcmpl-fake", "object": "chat.completion", "created": 1767225600,
                "model": body.get("model") or MODEL,
                "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
                "usage": usage,
            })
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

        def ev(delta: dict[str, Any], finish: str | None = None, **extra: Any) -> None:
            chunk = {"id": "chatcmpl-fake", "object": "chat.completion.chunk", "model": body.get("model") or MODEL,
                     "choices": [{"index": 0, "delta": delta, "finish_reason": finish}], **extra}
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()

        ev({"role": "assistant"})
        words = text.split()
        for i, w in enumerate(words):
            ev({"content": w + (" " if i < len(words) - 1 else "")})
        ev({}, "stop")
        tail = {"id": "chatcmpl-fake", "object": "chat.completion.chunk", "choices": [], "usage": usage}
        self.wfile.write(f"data: {json.dumps(tail)}\n\ndata: [DONE]\n\n".encode())
        self.wfile.flush()
        self.close_connection = True


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    fail = False
    delay = 0.0


class FakeRelay:
    """``with FakeRelay() as relay: relay.url`` -> ``http://127.0.0.1:<port>/v1``."""

    def __init__(self, fail: bool = False, delay: float = 0.0) -> None:
        self.httpd = _Server(("127.0.0.1", 0), _Handler)
        self.httpd.fail = fail
        self.httpd.delay = delay
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> FakeRelay:
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
