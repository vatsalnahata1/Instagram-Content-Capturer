"""Loads the real extension into Chromium and drives it against a fake instagram.com reel.

Verifies: MAIN-world interceptor reads the GraphQL response, the content script detects the
playing reel and the watch threshold and grabs frames from the video, the background worker posts
a complete payload to the local server, and the server queues it.

Skipped unless playwright is importable and a Chromium binary is available. Set
IGCC_E2E_HEADED=1 to run headed (e.g. under xvfb-run) if the headless build refuses extensions.
"""

from __future__ import annotations

import base64
import json
import os
import shutil
import threading
import time
from pathlib import Path

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

from capturer.fetch import FetchedPost  # noqa: E402
from capturer.pipeline import Capturer  # noqa: E402
from capturer.server import make_server  # noqa: E402
from tests.test_pipeline import fake_analysis  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EXTENSION = ROOT / "extension"


def _chromium_path() -> str | None:
    for candidate in (
        os.environ.get("IGCC_CHROMIUM"),
        "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
        shutil.which("chromium"),
        shutil.which("google-chrome"),
    ):
        if candidate and Path(candidate).exists():
            return candidate
    return None


def _make_video(path: Path) -> bytes:
    import av
    from PIL import Image, ImageDraw

    # VP8/WebM: Playwright's Chromium build has no H.264 decoder.
    with av.open(str(path), mode="w", format="webm") as container:
        stream = container.add_stream("libvpx", rate=24)
        stream.width, stream.height, stream.pix_fmt = 480, 640, "yuv420p"
        for i in range(24 * 6):
            img = Image.new("RGB", (480, 640), (30, 30, 120))
            ImageDraw.Draw(img).text((40, 40), f"3 SOP MISTAKES {i // 24}", fill=(255, 255, 255))
            for packet in stream.encode(av.VideoFrame.from_image(img)):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)
    return path.read_bytes()


REEL_HTML = """<!doctype html><html><head><title>Reel</title></head><body style="margin:0">
<article style="width:480px">
  <header><a href="/guru/">guru</a></header>
  <video id="v" src="data:video/webm;base64,__VIDEO_B64__" autoplay muted loop playsinline
         style="width:480px;height:640px;display:block"></video>
  <div><span dir="auto">Three SOP mistakes that get you rejected #studyabroad</span></div>
  <a href="/reel/ABC123/">permalink</a>
</article>
<script>
  // Real Instagram plays reels from blob:/MediaSource URLs, so the <video> src is never a CDN
  // link; the CDN link only exists in the API response. A data: URL stands in for that here
  // (routing the media request through Playwright stalls its route dispatch).
  document.getElementById('v').play().catch(e => console.log('play failed', e));
  setTimeout(() => fetch('https://www.instagram.com/graphql/query', {method: 'POST', body: 'q'}), 200);
</script>
</body></html>"""

GRAPHQL = {
    "data": {"xdt_api__v1__clips__home__connected_v2": {"edges": [{"node": {"media": {
        "code": "ABC123", "pk": "1",
        "video_versions": [{"width": 720, "url": "https://www.instagram.com/video/ABC123.mp4"}],
        "user": {"username": "guru_api"},
        "caption": {"text": "API caption wins"},
        "like_count": 4321, "comment_count": 99, "taken_at": 1700000000, "video_duration": 6.0,
    }}}]}}
}


@pytest.fixture
def capture_server(settings, db):
    received: list[dict] = []

    def observed(obs, s):
        received.append(obs)
        return FetchedPost(obs.shortcode, obs.url, obs.creator, obs.caption, None, None, None, None, None, media_source="none")

    cap = Capturer(settings, db, observed_fetcher=observed, analyzer=lambda *a, **k: fake_analysis())
    srv = make_server(settings, port=0, capturer=cap)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", received
    srv.shutdown()


@pytest.mark.timeout(120)
def test_extension_captures_watched_reel(capture_server, tmp_path):
    chromium = _chromium_path()
    if not chromium:
        pytest.skip("no Chromium binary available")
    base, received = capture_server
    reel_html = REEL_HTML.replace("__VIDEO_B64__", base64.b64encode(_make_video(tmp_path / "reel.webm")).decode())
    headed = os.environ.get("IGCC_E2E_HEADED") == "1"

    with sync_playwright() as p:
        try:
            context = p.chromium.launch_persistent_context(
                str(tmp_path / "profile"),
                executable_path=chromium,
                headless=not headed,
                args=[
                    f"--disable-extensions-except={EXTENSION}",
                    f"--load-extension={EXTENSION}",
                    "--autoplay-policy=no-user-gesture-required",
                    "--no-sandbox",
                ] + ([] if headed else ["--headless=new"]),
                ignore_default_args=["--headless"] if not headed else [],
                viewport={"width": 900, "height": 900},
            )
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"could not launch Chromium with extension: {exc}")

        try:
            # Fake instagram.com entirely, so no network is needed and the extension runs unmodified.
            def route(r):
                url = r.request.url
                if "/graphql/query" in url:
                    r.fulfill(status=200, content_type="application/json", body=json.dumps(GRAPHQL))
                elif url.startswith("https://www.instagram.com/reels/") or url.startswith("https://www.instagram.com/reel/"):
                    r.fulfill(status=200, content_type="text/html", body=reel_html)
                else:
                    r.fulfill(status=204, body="")

            context.route("https://www.instagram.com/**", route)

            # Wait for the extension's service worker, then point it at our server with a 1s threshold.
            deadline = time.time() + 20
            while not context.service_workers and time.time() < deadline:
                time.sleep(0.2)
            if not context.service_workers:
                pytest.skip("extension service worker did not start (headless build may not support extensions)")
            sw = context.service_workers[0]
            sw.evaluate(
                "cfg => new Promise(res => chrome.storage.sync.set(cfg, res))",
                {"enabled": True, "minWatchSeconds": 2, "serverUrl": base, "screenshots": 2},
            )

            page = context.new_page()
            page.goto("https://www.instagram.com/reels/ABC123/")
            page.wait_for_function("document.getElementById('v') && !document.getElementById('v').paused", timeout=15000)

            # Wait through Playwright, not time.sleep: the sync API only dispatches route
            # callbacks (our fake GraphQL response) while a Playwright call is in progress.
            deadline = time.time() + 30
            while not received and time.time() < deadline:
                page.wait_for_timeout(250)
            assert received, "extension never posted a capture to the server"
            obs = received[0]
            assert obs.shortcode == "ABC123"
            assert obs.url == "https://www.instagram.com/reel/ABC123/"
            assert obs.creator == "guru_api", "creator should come from the intercepted API response"
            assert obs.caption == "API caption wins"
            assert obs.video_url == "https://www.instagram.com/video/ABC123.mp4"
            assert obs.like_count == 4321 and obs.comment_count == 99
            assert obs.duration_sec == 6.0
            assert obs.posted_at == "2023-11-14T22:13:20+00:00"
            assert len(obs.screenshots) >= 1, "content script should have grabbed frames from the video"
            # Screenshots are base64 JPEG (starts with /9j/)
            assert obs.screenshots[0].startswith("/9j/")

            toast = page.locator("#igcc-toast")
            toast.wait_for(timeout=10000)
            assert "sent @guru_api" in toast.text_content()

            # Watching the same reel again must not re-send.
            page.wait_for_timeout(4000)
            assert len(received) == 1
        finally:
            context.close()
