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
    media_source: str = "yt-dlp"     # yt-dlp | direct | none


@dataclass
class ObservedPost:
    """What the browser extension saw while you watched a reel."""

    shortcode: str
    url: str
    creator: str | None = None
    caption: str | None = None
    video_url: str | None = None      # CDN link the page was already playing
    posted_at: str | None = None
    duration_sec: float | None = None
    like_count: int | None = None
    comment_count: int | None = None
    screenshots: list[str] = field(default_factory=list, repr=False)   # base64 JPEGs of the player

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ObservedPost":
        def _int(v: Any) -> int | None:
            try:
                return int(v) if v is not None and v != "" else None
            except (TypeError, ValueError):
                return None

        def _float(v: Any) -> float | None:
            try:
                return float(v) if v is not None and v != "" else None
            except (TypeError, ValueError):
                return None

        shortcode = str(payload.get("shortcode") or "").strip()
        url = str(payload.get("url") or "").strip() or f"https://www.instagram.com/reel/{shortcode}/"
        shots = payload.get("screenshots") or []
        return cls(
            shortcode=shortcode,
            url=url,
            creator=(payload.get("creator") or None),
            caption=(payload.get("caption") or None),
            video_url=(payload.get("video_url") or None),
            posted_at=_timestamp_to_iso(payload.get("taken_at")) if payload.get("taken_at") else (payload.get("posted_at") or None),
            duration_sec=_float(payload.get("duration_sec")),
            like_count=_int(payload.get("like_count")),
            comment_count=_int(payload.get("comment_count")),
            screenshots=[s for s in shots if isinstance(s, str) and s],
        )


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


_DIRECT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.instagram.com/",
    "Accept": "*/*",
}


def download_direct(video_url: str, dest: Path, *, timeout: float = 60.0, max_bytes: int = 300_000_000) -> Path:
    """Fetch a CDN media URL the browser was already playing. Raises FetchError on any problem."""
    import urllib.error
    import urllib.request

    if not video_url.lower().startswith(("http://", "https://")):
        raise FetchError("video_url must be an http(s) link")
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(video_url, headers=_DIRECT_HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(dest, "wb") as out:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if "text/html" in ctype:
                raise FetchError(f"CDN link returned HTML instead of media ({ctype})")
            total = 0
            while True:
                chunk = resp.read(1 << 16)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise FetchError("media larger than the 300MB limit")
                out.write(chunk)
    except FetchError:
        dest.unlink(missing_ok=True)
        raise
    except urllib.error.HTTPError as exc:
        dest.unlink(missing_ok=True)
        raise FetchError(f"CDN link refused ({exc.code}); it may have expired") from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        dest.unlink(missing_ok=True)
        raise FetchError(f"could not fetch CDN link: {exc}") from exc
    if dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        raise FetchError("CDN link returned an empty file")
    return dest


def fetch_observed(obs: ObservedPost, settings: Settings) -> FetchedPost:
    """Get media for a post the extension saw. Tries the page's own CDN link, then yt-dlp,
    and finally gives up on media (the caller can still analyse screenshots + caption)."""
    errors: list[str] = []
    video_path: Path | None = None
    media_source = "none"

    if obs.video_url:
        try:
            video_path = download_direct(obs.video_url, settings.media_dir / f"{obs.shortcode}.mp4")
            media_source = "direct"
        except FetchError as exc:
            errors.append(f"direct: {exc}")

    fetched: FetchedPost | None = None
    if video_path is None:
        try:
            fetched = fetch_post(obs.url, obs.shortcode, settings)
            video_path = fetched.video_path
            media_source = "yt-dlp" if video_path else "none"
        except FetchError as exc:
            errors.append(f"yt-dlp: {exc}")
        except Exception as exc:  # noqa: BLE001 - yt-dlp raises assorted things
            errors.append(f"yt-dlp: {type(exc).__name__}: {exc}")

    if video_path is None and not obs.screenshots and not obs.caption:
        raise FetchError("no media, screenshots or caption to analyse; " + "; ".join(errors))

    return FetchedPost(
        shortcode=obs.shortcode,
        url=obs.url,
        creator=obs.creator or (fetched.creator if fetched else None),
        caption=obs.caption or (fetched.caption if fetched else None),
        posted_at=obs.posted_at or (fetched.posted_at if fetched else None),
        duration_sec=obs.duration_sec or (fetched.duration_sec if fetched else None),
        like_count=obs.like_count if obs.like_count is not None else (fetched.like_count if fetched else None),
        comment_count=obs.comment_count if obs.comment_count is not None else (fetched.comment_count if fetched else None),
        video_path=video_path,
        raw={"errors": errors},
        media_source=media_source,
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
