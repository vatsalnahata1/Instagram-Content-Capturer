"""Export the bank and ideas to Markdown or CSV so they can live in Notion, Sheets, etc."""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import tempfile
from pathlib import Path

from .db import Database, analysis_of

log = logging.getLogger(__name__)

EXPORT_FILES = ("content-bank.csv", "content-bank.md", "ideas.md")


def posts_to_markdown(db: Database, limit: int = 500) -> str:
    out = ["# Content bank", ""]
    for row in db.list_posts(status="done", limit=limit):
        a = analysis_of(row)
        out.append(f"## #{row['id']} @{row['creator'] or 'unknown'} - {a.get('topic', '')}")
        out.append(f"- URL: {row['url']}")
        out.append(f"- Captured: {row['captured_at']}  Posted: {row['posted_at'] or '?'}  Likes: {row['like_count'] or '?'}")
        out.append(f"- Hook ({a.get('hook_type', '')}): {a.get('hook', '')}")
        out.append(f"- Format: {a.get('format', '')}  Tone: {a.get('tone', '')}")
        out.append(f"- Audience: {a.get('target_audience', '')}")
        out.append(f"- Summary: {a.get('summary', '')}")
        if a.get("key_points"):
            out.append("- Key points:")
            out.extend(f"  - {p}" for p in a["key_points"])
        if a.get("on_screen_text"):
            out.append("- On-screen text: " + " | ".join(a["on_screen_text"]))
        out.append(f"- Why it works: {a.get('why_it_works', '')}")
        if a.get("remix_ideas"):
            out.append("- Remix ideas:")
            out.extend(f"  - {r}" for r in a["remix_ideas"])
        out.append("")
    return "\n".join(out)


def posts_to_csv(db: Database, limit: int = 5000) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "id", "creator", "url", "captured_at", "posted_at", "likes", "comments", "topic", "subtopics",
        "hook", "hook_type", "format", "audience", "tone", "summary", "key_points", "on_screen_text",
        "why_it_works", "remix_ideas", "transcript",
    ])
    for row in db.list_posts(status="done", limit=limit):
        a = analysis_of(row)
        writer.writerow([
            row["id"], row["creator"], row["url"], row["captured_at"], row["posted_at"], row["like_count"],
            row["comment_count"], a.get("topic"), " | ".join(a.get("subtopics") or []), a.get("hook"),
            a.get("hook_type"), a.get("format"), a.get("target_audience"), a.get("tone"), a.get("summary"),
            " | ".join(a.get("key_points") or []), " | ".join(a.get("on_screen_text") or []),
            a.get("why_it_works"), " | ".join(a.get("remix_ideas") or []), row["transcript"],
        ])
    return buf.getvalue()


def ideas_to_markdown(db: Database, status: str | None = "new", limit: int = 500) -> str:
    out = ["# Ideas", ""]
    for row in db.list_ideas(status=status, limit=limit):
        sources = json.loads(row["source_ids"] or "[]")
        out.append(f"## #{row['id']} {row['title']}  ({row['status']})")
        out.append(f"- Hook: {row['hook']}")
        out.append(f"- Angle: {row['angle']}")
        out.append(f"- Format: {row['format']}")
        out.append("- Outline:")
        out.extend(f"  - {line.strip()}" for line in (row["outline"] or "").splitlines() if line.strip())
        out.append(f"- Why: {row['rationale']}")
        if sources:
            out.append("- Sources: " + ", ".join(f"#{s}" for s in sources))
        out.append("")
    return "\n".join(out)


def _atomic_write(path: Path, text: str) -> None:
    """Write via a temp file + rename so a syncing folder (Google Drive, Dropbox) never sees a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_exports(db: Database, export_dir: Path | None) -> list[Path]:
    """Rewrite the bank and ideas files in ``export_dir``. Returns the paths written.

    Never raises: an unreachable folder (Drive not mounted, permissions) is logged and skipped so
    a capture is not marked failed because of a backup problem.
    """
    if not export_dir:
        return []
    written: list[Path] = []
    try:
        for name, text in (
            ("content-bank.csv", posts_to_csv(db)),
            ("content-bank.md", posts_to_markdown(db)),
            ("ideas.md", ideas_to_markdown(db, status=None)),
        ):
            target = export_dir / name
            _atomic_write(target, text)
            written.append(target)
        log.info("Exports refreshed in %s", export_dir)
    except OSError as exc:
        log.warning("Could not write exports to %s: %s", export_dir, exc)
    return written
