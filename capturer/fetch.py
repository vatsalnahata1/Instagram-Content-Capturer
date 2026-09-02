"""Download an Instagram post and its metadata with yt-dlp."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings


@dataclass
class FetchedPost:
    shortcode: str
    url: str
    creator: str | None
    caption: str | None
    posted_at: str | None
    duration_sec: float | None
    like_count: int | None
    comment_count: int | None
    video_path: Path | None          # None for image-only posts
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


class FetchError(RuntimeError):
    pass


def _ydl_options(settings: Settings, out_dir: Path) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "outtmpl": str(out_dir / "%(id)s.%(ext)s"),
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best",
        "merge_output_format": "mp4",
        "quiet": True,
        "no_warnings": True,
        "noplaylist": False,
        "restrictfilenames": True,
        "retries": 3,
    }
    if settings.cookies_from_browser:
        opts["cookiesfrombrowser"] = (settings.cookies_from_browser,)
    elif settings.cookies_file:
        opts["cookiefile"] = settings.cookies_file
    return opts


def _pick_entry(info: dict[str, Any]) -> dict[str, Any]:
    """Carousels come back as a playlist; use the first entry that has a video."""
    entries = info.get("entries")
    if not entries:
        return info
    for entry in entries:
        if entry and (entry.get("requested_downloads") or entry.get("url") or entry.get("formats")):
            return entry
    return entries[0] or info


def _timestamp_to_iso(ts: Any) -> str | None:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError):
        return None


def fetch_post(url: str, shortcode: str, settings: Settings) -> FetchedPost:
    """Download the post's video (if any) and return its metadata."""
    import yt_dlp  # imported lazily so tests don't need it

    out_dir = settings.media_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        with yt_dlp.YoutubeDL(_ydl_options(settings, out_dir)) as ydl:
            info = ydl.extract_info(url, download=True)
            entry = _pick_entry(info)
            video_path: Path | None = None
            downloads = entry.get("requested_downloads") or []
            for dl in downloads:
                candidate = Path(dl.get("filepath") or dl.get("filename") or "")
                if candidate.exists():
                    video_path = candidate
                    break
            if video_path is None:
                candidate = Path(ydl.prepare_filename(entry))
                if candidate.exists():
                    video_path = candidate
    except yt_dlp.utils.DownloadError as exc:  # type: ignore[attr-defined]
        raise FetchError(_friendly_download_error(str(exc))) from exc

    top = info if not info.get("entries") else info
    return FetchedPost(
        shortcode=shortcode,
        url=url,
        creator=top.get("uploader") or top.get("channel") or entry.get("uploader"),
        caption=top.get("description") or entry.get("description") or top.get("title"),
        posted_at=_timestamp_to_iso(top.get("timestamp") or entry.get("timestamp")),
        duration_sec=entry.get("duration"),
        like_count=top.get("like_count") or entry.get("like_count"),
        comment_count=top.get("comment_count") or entry.get("comment_count"),
        video_path=video_path,
        raw=entry,
    )


def _friendly_download_error(message: str) -> str:
    lower = message.lower()
    if "login" in lower or "rate-limit" in lower or "rate limit" in lower or "cookies" in lower:
        return (
            "Instagram refused the download (login required or rate limited). "
            "Set INSTAGRAM_COOKIES_FROM_BROWSER=chrome (or another browser you are logged into) "
            "or INSTAGRAM_COOKIES_FILE in your .env and try again."
        )
    return f"Download failed: {message.splitlines()[-1] if message else 'unknown error'}"
