"""Local HTTP server the Chrome extension talks to.

Binds to 127.0.0.1 only. One worker thread processes captures in order, because Whisper and
the Claude call are heavy; the HTTP handlers just enqueue and answer quickly.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

from . import __version__
from .config import Settings
from .fetch import ObservedPost
from .pipeline import Capturer

log = logging.getLogger(__name__)

MAX_BODY = 40 * 1024 * 1024  # screenshots are base64 JPEGs; 40MB is generous


class CaptureQueue:
    """Serialises capture work and remembers what is queued or running."""

    def __init__(self, capturer: Capturer):
        self.capturer = capturer
        self._queue: "queue.Queue[tuple[ObservedPost, bool]]" = queue.Queue()
        self._pending: dict[str, str] = {}   # shortcode -> queued | running
        self._lock = threading.Lock()
        self.recent: list[dict[str, Any]] = []
        self._thread = threading.Thread(target=self._worker, name="capture-worker", daemon=True)
        self._thread.start()

    def enqueue(self, obs: ObservedPost, *, force: bool = False) -> dict[str, Any]:
        existing = self.capturer.db.get_post(obs.shortcode)
        if existing and existing["status"] == "done" and not force:
            return {"status": "skipped", "post_id": existing["id"], "shortcode": obs.shortcode}
        with self._lock:
            if obs.shortcode in self._pending:
                return {"status": self._pending[obs.shortcode], "shortcode": obs.shortcode}
            self._pending[obs.shortcode] = "queued"
        self._queue.put((obs, force))
        return {"status": "queued", "shortcode": obs.shortcode, "queue_size": self._queue.qsize()}

    def state(self, shortcode: str) -> str | None:
        with self._lock:
            return self._pending.get(shortcode)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"queued": sum(1 for v in self._pending.values() if v == "queued"),
                    "running": [k for k, v in self._pending.items() if v == "running"]}

    def _worker(self) -> None:
        while True:
            obs, force = self._queue.get()
            with self._lock:
                self._pending[obs.shortcode] = "running"
            try:
                result = self.capturer.capture_observed(obs, force=force)
                self.recent.insert(0, {"shortcode": result.shortcode, "status": result.status,
                                       "post_id": result.post_id, "creator": result.creator,
                                       "topic": (result.analysis or {}).get("topic"), "error": result.error})
                del self.recent[50:]
                log.info("Processed %s: %s", obs.shortcode, result.status)
            except Exception as exc:  # noqa: BLE001
                log.exception("worker crashed on %s", obs.shortcode)
                self.recent.insert(0, {"shortcode": obs.shortcode, "status": "failed", "error": str(exc)})
            finally:
                with self._lock:
                    self._pending.pop(obs.shortcode, None)
                self._queue.task_done()


class Handler(BaseHTTPRequestHandler):
    server: "CaptureHTTPServer"

    # ---- plumbing ---------------------------------------------------------

    def log_message(self, fmt: str, *args: Any) -> None:  # quieter than the default
        log.debug("%s " + fmt, self.address_string(), *args)

    def _cors(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError("request body too large")
        data = json.loads(self.rfile.read(length).decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    # ---- routes ------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        app = self.server.app
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        path = parsed.path.rstrip("/") or "/"

        if path in ("/", "/health"):
            self._json(200, {"ok": True, "version": __version__, "niche": app.settings.niche,
                             "model": app.settings.model, "counts": app.capturer.db.counts(),
                             **app.queue.snapshot()})
        elif path == "/posts":
            limit = min(int((params.get("limit") or ["10"])[0]), 200)
            rows = app.capturer.db.list_posts(status=None, limit=limit)
            self._json(200, {"posts": [app.capturer.db.post_summary(r) for r in rows]})
        elif path.startswith("/post/"):
            key = path.split("/", 2)[2]
            row = app.capturer.db.get_post(key)
            if not row:
                pending = app.queue.state(key)
                self._json(200 if pending else 404, {"status": pending or "unknown", "shortcode": key})
                return
            record = dict(row)
            record["analysis"] = json.loads(record["analysis"]) if record.get("analysis") else None
            record["queue_state"] = app.queue.state(row["shortcode"])
            self._json(200, record)
        elif path == "/ideas":
            status = (params.get("status") or ["new"])[0]
            rows = app.capturer.db.list_ideas(status=None if status == "all" else status, limit=100)
            self._json(200, {"ideas": [dict(r) for r in rows]})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        app = self.server.app
        path = urlparse(self.path).path.rstrip("/")
        try:
            body = self._read_json()
        except (ValueError, json.JSONDecodeError) as exc:
            self._json(400, {"error": f"bad request: {exc}"})
            return

        if path == "/capture":
            obs = ObservedPost.from_payload(body)
            if not obs.shortcode:
                self._json(400, {"error": "shortcode is required"})
                return
            result = app.queue.enqueue(obs, force=bool(body.get("force")))
            self._json(202 if result["status"] in ("queued", "running") else 200, result)
        elif path == "/ideas":
            from .ideas import generate_ideas, save_ideas

            count = max(1, min(int(body.get("count") or 5), 20))
            try:
                batch = generate_ideas(app.capturer.db, app.settings, count=count, focus=body.get("focus") or None)
                ids = save_ideas(app.capturer.db, batch, app.settings)
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            except Exception as exc:  # noqa: BLE001
                log.exception("idea generation failed")
                self._json(500, {"error": str(exc)})
                return
            self._json(200, {"themes": [t.model_dump() for t in batch.themes],
                             "ideas": [{"id": i, **idea.model_dump()} for i, idea in zip(ids, batch.ideas)]})
        else:
            self._json(404, {"error": "not found"})


class CaptureHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, app: "App", host: str, port: int):
        self.app = app
        super().__init__((host, port), Handler)


class App:
    def __init__(self, settings: Settings, capturer: Capturer | None = None):
        self.settings = settings
        self.capturer = capturer or Capturer(settings)
        self.queue = CaptureQueue(self.capturer)


def make_server(settings: Settings, host: str = "127.0.0.1", port: int = 8787, capturer: Capturer | None = None) -> CaptureHTTPServer:
    return CaptureHTTPServer(App(settings, capturer), host, port)


def serve(settings: Settings, host: str = "127.0.0.1", port: int = 8787) -> int:
    server = make_server(settings, host, port)
    log.info("Capturer server listening on http://%s:%d  (niche: %s)", host, port, settings.niche)
    print(f"Listening on http://{host}:{port}. Keep this running while you scroll Instagram in Chrome.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
