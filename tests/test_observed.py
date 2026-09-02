"""Extension-observed captures: direct CDN download, fallbacks, and screenshots-only analysis."""

import http.server
import threading
from pathlib import Path

import pytest

from capturer.analyze import PostAnalysis
from capturer.config import Settings
from capturer.db import Database
from capturer.fetch import FetchError, FetchedPost, ObservedPost, download_direct, fetch_observed
from capturer.media import Frame
from capturer.pipeline import Capturer
from capturer.transcribe import Transcript
from tests.test_pipeline import fake_analysis


class _MediaHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):  # noqa: D401
        pass

    def do_GET(self):
        if self.path.startswith("/ok.mp4"):
            body = b"\x00\x00\x00\x18ftypmp42" + b"x" * 1000
            self.send_response(200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path.startswith("/html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html>login</html>")
        elif self.path.startswith("/empty"):
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()
        else:
            self.send_response(403)
            self.end_headers()


@pytest.fixture(scope="module")
def media_server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _MediaHandler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_download_direct_success(media_server, tmp_path):
    dest = download_direct(f"{media_server}/ok.mp4?sig=1", tmp_path / "m" / "v.mp4")
    assert dest.exists() and dest.stat().st_size > 1000


@pytest.mark.parametrize("path,needle", [("/html", "HTML"), ("/empty", "empty"), ("/gone", "403")])
def test_download_direct_failures(media_server, tmp_path, path, needle):
    with pytest.raises(FetchError) as exc:
        download_direct(f"{media_server}{path}", tmp_path / "v.mp4")
    assert needle in str(exc.value)
    assert not (tmp_path / "v.mp4").exists()


def test_download_direct_rejects_non_http(tmp_path):
    with pytest.raises(FetchError):
        download_direct("blob:https://www.instagram.com/abc", tmp_path / "v.mp4")


def test_observed_from_payload_parses_types():
    obs = ObservedPost.from_payload({
        "shortcode": " AbC ", "creator": "guru", "caption": "", "video_url": "",
        "like_count": "12", "comment_count": None, "taken_at": 1700000000, "duration_sec": "30.5",
        "screenshots": ["AAA", "", 5],
    })
    assert obs.shortcode == "AbC" and obs.url == "https://www.instagram.com/reel/AbC/"
    assert obs.caption is None and obs.video_url is None
    assert obs.like_count == 12 and obs.comment_count is None
    assert obs.posted_at == "2023-11-14T22:13:20+00:00"
    assert obs.duration_sec == 30.5 and obs.screenshots == ["AAA"]


def test_fetch_observed_prefers_direct(media_server, settings, monkeypatch):
    called = []
    monkeypatch.setattr("capturer.fetch.fetch_post", lambda *a: called.append(a))
    obs = ObservedPost(shortcode="X1", url="u", creator="guru", video_url=f"{media_server}/ok.mp4")
    post = fetch_observed(obs, settings)
    assert post.media_source == "direct" and post.video_path.exists() and not called


def test_fetch_observed_falls_back_to_ytdlp(media_server, settings, monkeypatch, tmp_path):
    video = tmp_path / "yt.mp4"
    video.write_bytes(b"x")
    monkeypatch.setattr(
        "capturer.fetch.fetch_post",
        lambda url, sc, s: FetchedPost(sc, url, "yt_creator", "yt caption", None, 12.0, 5, 1, video),
    )
    obs = ObservedPost(shortcode="X2", url="u", video_url=f"{media_server}/gone")
    post = fetch_observed(obs, settings)
    assert post.media_source == "yt-dlp" and post.video_path == video
    assert post.creator == "yt_creator" and post.caption == "yt caption"
    assert post.raw["errors"] and "direct" in post.raw["errors"][0]


def test_fetch_observed_without_media_keeps_screenshots(settings, monkeypatch):
    def boom(*a):
        raise FetchError("login required")
    monkeypatch.setattr("capturer.fetch.fetch_post", boom)
    obs = ObservedPost(shortcode="X3", url="u", caption="cap", screenshots=["AAA"])
    post = fetch_observed(obs, settings)
    assert post.video_path is None and post.media_source == "none"

    with pytest.raises(FetchError):
        fetch_observed(ObservedPost(shortcode="X4", url="u"), settings)


def _capturer(settings, db, *, observed):
    seen = {}

    def transcriber(path, model):
        seen["transcribed"] = path
        return Transcript(text="spoken words", language="en", segments=[])

    def framer(path, count):
        return [Frame(0.5, "VID")]

    def analyzer(post, transcript_text, frames, s, frames_kind="video"):
        seen["frames"] = [f.jpeg_b64 for f in frames]
        seen["frames_kind"] = frames_kind
        seen["transcript"] = transcript_text
        return fake_analysis()

    return Capturer(settings, db, observed_fetcher=observed, transcriber=transcriber, framer=framer, analyzer=analyzer), seen


def test_capture_observed_with_video(settings, db, tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    cap, seen = _capturer(settings, db, observed=lambda obs, s: FetchedPost(
        obs.shortcode, obs.url, "guru", "cap", None, 10.0, 1, 1, video, media_source="direct"))
    res = cap.capture_observed(ObservedPost(shortcode="OB1", url="u", screenshots=["SHOT"]))
    assert res.status == "done"
    assert seen["frames"] == ["VID"] and seen["frames_kind"] == "video" and seen["transcript"] == "spoken words"
    row = db.get_post("OB1")
    assert row["source"] == "extension" and row["media_source"] == "direct"
    assert not video.exists()


def test_capture_observed_screenshots_only(settings, db):
    cap, seen = _capturer(settings, db, observed=lambda obs, s: FetchedPost(
        obs.shortcode, obs.url, "guru", "cap", None, None, None, None, None, media_source="none"))
    res = cap.capture_observed(ObservedPost(shortcode="OB2", url="u", screenshots=["S1", "S2", "S3", "S4", "S5"]))
    assert res.status == "done"
    assert seen["frames"] == ["S1", "S2", "S3"]  # capped at settings.frames
    assert seen["frames_kind"] == "screenshots" and seen["transcript"] == ""
    assert "transcribed" not in seen
    assert db.get_post("OB2")["media_source"] == "screenshots"


def test_capture_observed_rejects_missing_shortcode(settings, db):
    cap, _ = _capturer(settings, db, observed=lambda obs, s: None)
    with pytest.raises(ValueError):
        cap.capture_observed(ObservedPost(shortcode="", url="u"))


def test_db_migration_adds_columns(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE posts (id INTEGER PRIMARY KEY AUTOINCREMENT, shortcode TEXT UNIQUE NOT NULL, url TEXT NOT NULL,
            creator TEXT, caption TEXT, posted_at TEXT, duration_sec REAL, like_count INTEGER, comment_count INTEGER,
            transcript TEXT, analysis TEXT, status TEXT NOT NULL DEFAULT 'pending', error TEXT,
            captured_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        INSERT INTO posts (shortcode, url, status, captured_at, updated_at) VALUES ('old', 'u', 'done', 't', 't');
    """)
    conn.commit(); conn.close()
    db = Database(path)
    row = db.get_post("old")
    assert row["source"] == "url" and row["media_source"] is None
    assert db.post_summary(row)["shortcode"] == "old"
