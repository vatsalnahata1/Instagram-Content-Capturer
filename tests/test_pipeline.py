from pathlib import Path

from capturer.analyze import PostAnalysis
from capturer.config import Settings
from capturer.db import Database, analysis_of
from capturer.fetch import FetchedPost
from capturer.media import Frame
from capturer.pipeline import Capturer
from capturer.transcribe import Transcript

URL = "https://www.instagram.com/reel/TeSt123/"


def fake_analysis() -> PostAnalysis:
    return PostAnalysis(
        summary="A creator lists three SOP mistakes.",
        topic="SOP mistakes",
        subtopics=["generic openings", "no specifics"],
        hook="Stop writing your SOP like this",
        hook_type="mistake",
        format="talking head",
        key_points=["Do not open with a childhood story", "Name the professor"],
        on_screen_text=["3 SOP MISTAKES"],
        target_audience="Indian students applying to US masters",
        call_to_action="comment SOP",
        tone="urgent",
        why_it_works="Specific mistake framing creates fear of missing out.",
        remix_ideas=["3 SOP mistakes for UK", "The one line every SOP needs", "SOP before/after"],
    )


def make_capturer(settings: Settings, db: Database, tmp_path: Path, *, fail_stage: str | None = None) -> Capturer:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"fake")
    calls: dict[str, int] = {}

    def fetcher(url, shortcode, s):
        calls["fetch"] = calls.get("fetch", 0) + 1
        if fail_stage == "fetch":
            raise RuntimeError("login required")
        return FetchedPost(
            shortcode=shortcode, url=url, creator="studyguru", caption="SOP tips #studyabroad",
            posted_at="2026-01-01T00:00:00+00:00", duration_sec=42.0, like_count=1200, comment_count=40,
            video_path=video,
        )

    def transcriber(path, model_name):
        calls["transcribe"] = calls.get("transcribe", 0) + 1
        assert path == video and model_name == s_model
        return Transcript(text="stop writing your sop like this", language="en", segments=[(0.0, 3.0, "stop writing your sop like this")])

    def framer(path, count):
        calls["frames"] = calls.get("frames", 0) + 1
        assert count == settings.frames
        return [Frame(timestamp_sec=1.0, jpeg_b64="AAAA")]

    def analyzer(post, transcript_text, frames, s):
        calls["analyze"] = calls.get("analyze", 0) + 1
        if fail_stage == "analyze":
            raise RuntimeError("api down")
        assert transcript_text == "stop writing your sop like this"
        assert len(frames) == 1
        return fake_analysis()

    s_model = settings.whisper_model
    cap = Capturer(settings, db, fetcher=fetcher, transcriber=transcriber, framer=framer, analyzer=analyzer)
    cap.calls = calls  # type: ignore[attr-defined]
    cap.video = video  # type: ignore[attr-defined]
    return cap


def test_capture_success_stores_everything_and_cleans_media(settings, db, tmp_path):
    cap = make_capturer(settings, db, tmp_path)
    result = cap.capture(URL)
    assert result.status == "done"
    assert result.creator == "studyguru"
    row = db.get_post("TeSt123")
    assert row["status"] == "done"
    assert row["transcript"] == "stop writing your sop like this"
    assert row["like_count"] == 1200
    assert analysis_of(row)["hook"] == "Stop writing your SOP like this"
    assert not cap.video.exists(), "media should be deleted when keep_media is false"
    assert "Remix ideas" in result.short_summary()


def test_capture_skips_already_done_unless_forced(settings, db, tmp_path):
    cap = make_capturer(settings, db, tmp_path)
    assert cap.capture(URL).status == "done"
    cap.video.write_bytes(b"fake")
    assert cap.capture(URL).status == "skipped"
    assert cap.calls["fetch"] == 1
    assert cap.capture(URL, force=True).status == "done"
    assert cap.calls["fetch"] == 2


def test_capture_records_failure(settings, db, tmp_path):
    cap = make_capturer(settings, db, tmp_path, fail_stage="fetch")
    result = cap.capture(URL)
    assert result.status == "failed"
    assert "login required" in result.error
    assert db.get_post("TeSt123")["status"] == "failed"
    # a retry after a failure runs the pipeline again
    cap2 = make_capturer(settings, db, tmp_path)
    assert cap2.capture(URL).status == "done"


def test_capture_analysis_failure_deletes_media(settings, db, tmp_path):
    cap = make_capturer(settings, db, tmp_path, fail_stage="analyze")
    assert cap.capture(URL).status == "failed"
    assert not cap.video.exists()


def test_capture_rejects_non_instagram():
    import pytest

    cap = Capturer(Settings(data_dir=Path(":memory:").parent), Database(":memory:"))
    with pytest.raises(ValueError):
        cap.capture("https://youtube.com/watch?v=1")
