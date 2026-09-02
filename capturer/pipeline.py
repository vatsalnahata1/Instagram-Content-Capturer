"""Orchestrates: URL -> download -> transcribe -> frames -> Claude -> database."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from . import analyze as analyze_mod
from . import fetch as fetch_mod
from . import media as media_mod
from . import transcribe as transcribe_mod
from .config import Settings
from .db import Database
from .export import write_exports
from .urls import shortcode_from_url

log = logging.getLogger(__name__)


@dataclass
class CaptureResult:
    post_id: int
    shortcode: str
    url: str
    status: str                 # done | failed | skipped
    creator: str | None = None
    analysis: dict[str, Any] | None = None
    error: str | None = None

    def short_summary(self) -> str:
        if self.status == "skipped":
            return f"Already captured: {self.url}"
        if self.status == "failed":
            return f"Failed: {self.url}\n{self.error}"
        a = self.analysis or {}
        lines = [
            f"Saved #{self.post_id} from @{self.creator or 'unknown'}",
            f"Topic: {a.get('topic', '')}",
            f"Hook ({a.get('hook_type', '')}): {a.get('hook', '')}",
            f"Format: {a.get('format', '')}",
            f"Why it works: {a.get('why_it_works', '')}",
        ]
        remixes = a.get("remix_ideas") or []
        if remixes:
            lines.append("Remix ideas:")
            lines.extend(f"  {i + 1}. {r}" for i, r in enumerate(remixes))
        return "\n".join(lines)


class Capturer:
    """Holds the settings and DB, and lets tests swap out the heavy stages."""

    def __init__(
        self,
        settings: Settings,
        db: Database | None = None,
        *,
        fetcher: Callable[..., fetch_mod.FetchedPost] = fetch_mod.fetch_post,
        observed_fetcher: Callable[..., fetch_mod.FetchedPost] = fetch_mod.fetch_observed,
        transcriber: Callable[..., transcribe_mod.Transcript] = transcribe_mod.transcribe,
        framer: Callable[..., list[media_mod.Frame]] = media_mod.extract_frames,
        analyzer: Callable[..., analyze_mod.PostAnalysis] = analyze_mod.analyze_post,
    ):
        self.settings = settings
        self.db = db or Database(settings.db_path)
        self._fetch = fetcher
        self._fetch_observed = observed_fetcher
        self._transcribe = transcriber
        self._frames = framer
        self._analyze = analyzer

    def capture(self, url: str, *, force: bool = False) -> CaptureResult:
        """Capture from a URL alone (CLI / bot). Media comes from yt-dlp."""
        shortcode = shortcode_from_url(url)
        if not shortcode:
            raise ValueError(f"Not an Instagram post URL: {url}")
        return self._run(
            shortcode, url, force=force, source="url",
            fetch=lambda: self._fetch(url, shortcode, self.settings),
        )

    def capture_observed(self, obs: fetch_mod.ObservedPost, *, force: bool = False) -> CaptureResult:
        """Capture a post the browser extension watched. Uses the page's own media link when
        possible, and falls back to the extension's screenshots if no video can be fetched."""
        if not obs.shortcode:
            raise ValueError("observed post has no shortcode")
        return self._run(
            obs.shortcode, obs.url, force=force, source="extension",
            fetch=lambda: self._fetch_observed(obs, self.settings),
            fallback_frames=[media_mod.Frame(timestamp_sec=float(i), jpeg_b64=b64) for i, b64 in enumerate(obs.screenshots)],
        )

    def _run(
        self,
        shortcode: str,
        url: str,
        *,
        force: bool,
        source: str,
        fetch: Callable[[], fetch_mod.FetchedPost],
        fallback_frames: list[media_mod.Frame] | None = None,
    ) -> CaptureResult:
        existing = self.db.get_post(shortcode)
        if existing and existing["status"] == "done" and not force:
            return CaptureResult(int(existing["id"]), shortcode, url, "skipped", creator=existing["creator"])

        post_id = self.db.upsert_pending(shortcode, url, source=source)
        video_path: Path | None = None
        try:
            log.info("Fetching %s", url)
            post = fetch()
            video_path = post.video_path

            transcript_text = ""
            frames: list[media_mod.Frame] = []
            frames_kind = "video"
            if video_path:
                log.info("Transcribing %s", video_path.name)
                transcript_text = self._transcribe(video_path, self.settings.whisper_model).text
                log.info("Extracting %d frames", self.settings.frames)
                frames = self._frames(video_path, self.settings.frames)
            if not frames and fallback_frames:
                frames = fallback_frames[: max(self.settings.frames, 1)]
                frames_kind = "screenshots"

            log.info("Analysing with %s", self.settings.model)
            analysis = self._analyze(post, transcript_text, frames, self.settings, frames_kind=frames_kind)
            analysis_dict = analysis.model_dump()

            media_source = post.media_source if video_path else ("screenshots" if frames_kind == "screenshots" else "none")
            self.db.mark_done(
                post_id,
                creator=post.creator,
                caption=post.caption,
                posted_at=post.posted_at,
                duration_sec=post.duration_sec,
                like_count=post.like_count,
                comment_count=post.comment_count,
                transcript=transcript_text,
                analysis=analysis_dict,
                media_source=media_source,
            )
            write_exports(self.db, self.settings.export_dir)
            return CaptureResult(post_id, shortcode, url, "done", creator=post.creator, analysis=analysis_dict)
        except Exception as exc:  # noqa: BLE001 - we want every failure recorded, not raised to the caller
            log.exception("Capture failed for %s", url)
            self.db.mark_failed(post_id, f"{type(exc).__name__}: {exc}")
            return CaptureResult(post_id, shortcode, url, "failed", error=str(exc))
        finally:
            if video_path and not self.settings.keep_media:
                try:
                    video_path.unlink(missing_ok=True)
                except OSError:
                    pass
