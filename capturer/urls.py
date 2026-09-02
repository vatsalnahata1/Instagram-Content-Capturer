"""Find and normalise Instagram post URLs in free text (e.g. a Telegram message)."""

from __future__ import annotations

import re

# Matches reel, post and TV URLs; captures the shortcode.
_INSTAGRAM_RE = re.compile(
    r"https?://(?:www\.)?instagram\.com/(?:[A-Za-z0-9_.]+/)?(reels?|p|tv)/([A-Za-z0-9_-]+)",
    re.IGNORECASE,
)


def extract_instagram_urls(text: str) -> list[str]:
    """Return canonical Instagram URLs found in ``text``, de-duplicated, in order."""
    seen: set[str] = set()
    out: list[str] = []
    for kind, shortcode in _INSTAGRAM_RE.findall(text or ""):
        kind = "reel" if kind.lower().startswith("reel") else kind.lower()
        url = f"https://www.instagram.com/{kind}/{shortcode}/"
        if shortcode not in seen:
            seen.add(shortcode)
            out.append(url)
    return out


def shortcode_from_url(url: str) -> str | None:
    match = _INSTAGRAM_RE.search(url or "")
    return match.group(2) if match else None
