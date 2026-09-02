import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from capturer.fetch import FetchedPost
from capturer.pipeline import Capturer
from capturer.server import make_server
from tests.test_pipeline import fake_analysis


@pytest.fixture
def server(settings, db):
    gate = threading.Event()

    def observed(obs, s):
        gate.wait(5)  # lets tests observe the "running" state
        return FetchedPost(obs.shortcode, obs.url, obs.creator, obs.caption, None, None, None, None, None, media_source="none")

    cap = Capturer(settings, db, observed_fetcher=observed, analyzer=lambda *a, **k: fake_analysis())
    srv = make_server(settings, port=0, capturer=cap)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield base, gate, db
    srv.shutdown()


def call(base, path, body=None, method=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base + path, data=data, method=method or ("POST" if data else "GET"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.loads(resp.read() or b"{}"), dict(resp.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}"), dict(exc.headers)


def wait_for(pred, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.05)
    return False


def test_health_and_cors(server):
    base, _, _ = server
    status, body, headers = call(base, "/health")
    assert status == 200 and body["ok"] and body["queued"] == 0
    assert headers.get("Access-Control-Allow-Origin") == "*"
    req = urllib.request.Request(base + "/capture", method="OPTIONS")
    with urllib.request.urlopen(req) as resp:
        assert resp.status == 204


def test_capture_flow(server):
    base, gate, db = server
    status, body, _ = call(base, "/capture", {"shortcode": "S1", "creator": "guru", "caption": "hi", "screenshots": ["AAA"]})
    assert status == 202 and body["status"] == "queued"
    # duplicate while queued/running is reported, not re-queued
    status, body, _ = call(base, "/capture", {"shortcode": "S1"})
    assert status == 202 and body["status"] in ("queued", "running")
    assert wait_for(lambda: call(base, "/post/S1")[1].get("queue_state") == "running")
    gate.set()
    assert wait_for(lambda: db.get_post("S1") is not None and db.get_post("S1")["status"] == "done")
    status, body, _ = call(base, "/post/S1")
    assert status == 200 and body["analysis"]["topic"] == "SOP mistakes" and body["source"] == "extension"
    status, body, _ = call(base, "/posts?limit=5")
    assert body["posts"][0]["shortcode"] == "S1" and body["posts"][0]["hook"]
    status, body, _ = call(base, "/capture", {"shortcode": "S1"})
    assert status == 200 and body["status"] == "skipped"


def test_bad_requests(server):
    base, _, _ = server
    assert call(base, "/capture", {})[0] == 400
    assert call(base, "/nope")[0] == 404
    assert call(base, "/post/unknown")[0] == 404
    req = urllib.request.Request(base + "/capture", data=b"not json", method="POST", headers={"Content-Type": "application/json"})
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req)
    assert exc.value.code == 400


def test_ideas_endpoint_empty_bank(server):
    base, _, _ = server
    status, body, _ = call(base, "/ideas", {"count": 3})
    assert status == 400 and "empty" in body["error"].lower()
    status, body, _ = call(base, "/ideas")
    assert status == 200 and body["ideas"] == []
