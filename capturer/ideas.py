"""Generate fresh content ideas from the bank of analysed posts."""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from .config import Settings
from .db import Database, analysis_of


class Theme(BaseModel):
    name: str = Field(description="Short theme name.")
    post_ids: list[int] = Field(description="IDs of the bank posts in this theme.")
    observation: str = Field(description="What the creators in this theme are doing and what is missing.")


class Idea(BaseModel):
    title: str = Field(description="Working title, under 12 words.")
    hook: str = Field(description="The first line or on-screen text, ready to use.")
    angle: str = Field(description="What makes this different from the posts it draws on.")
    format: str = Field(description="Talking head, text overlay, skit, carousel, screen recording, etc.")
    outline: str = Field(description="Three to six beats, one per line, for a 30-60 second video.")
    rationale: str = Field(description="Why this should perform, referencing what worked in the source posts.")
    source_ids: list[int] = Field(description="IDs of the bank posts that inspired it. Empty if none.")


class IdeaBatch(BaseModel):
    themes: list[Theme]
    ideas: list[Idea]


SYSTEM_PROMPT = """You are a content strategist for a creator in this niche: {niche}.
You get a bank of short-form posts other creators made, already analysed into structured notes.
First group them into themes and note what is saturated and what is missing.
Then propose {count} new post ideas the creator can film this week.
Rules:
- Do not copy a post. Take the mechanism (hook style, format, emotional angle) and apply it to a new specific point.
- Prefer ideas that fill a gap in the bank over ideas that pile onto a saturated theme.
- Every idea needs a hook that would work as the first line of the video, and a concrete outline.
- Cite the post IDs each idea draws on.
{focus}"""


def _bank_text(db: Database, *, limit: int, since: str | None) -> tuple[str, list[int]]:
    rows = db.list_posts(status="done", limit=limit, since=since)
    ids: list[int] = []
    parts: list[str] = []
    for row in rows:
        a = analysis_of(row)
        ids.append(int(row["id"]))
        parts.append(
            json.dumps(
                {
                    "id": row["id"],
                    "creator": row["creator"],
                    "captured_at": row["captured_at"],
                    "likes": row["like_count"],
                    "topic": a.get("topic"),
                    "subtopics": a.get("subtopics"),
                    "hook": a.get("hook"),
                    "hook_type": a.get("hook_type"),
                    "format": a.get("format"),
                    "key_points": a.get("key_points"),
                    "audience": a.get("target_audience"),
                    "why_it_works": a.get("why_it_works"),
                },
                ensure_ascii=False,
            )
        )
    return "\n".join(parts), ids


def generate_ideas(
    db: Database,
    settings: Settings,
    *,
    count: int = 10,
    limit: int = 200,
    since: str | None = None,
    focus: str | None = None,
    client=None,
) -> IdeaBatch:
    import anthropic

    bank, ids = _bank_text(db, limit=limit, since=since)
    if not ids:
        raise ValueError("The bank is empty. Capture some posts first.")

    client = client or anthropic.Anthropic()
    focus_line = f"The creator wants ideas focused on: {focus}" if focus else ""
    response = client.messages.parse(
        model=settings.model,
        max_tokens=16000,
        system=SYSTEM_PROMPT.format(niche=settings.niche, count=count, focus=focus_line),
        messages=[{"role": "user", "content": f"Content bank ({len(ids)} posts), one JSON object per line:\n{bank}"}],
        output_format=IdeaBatch,
    )
    if response.stop_reason == "refusal" or response.parsed_output is None:
        raise RuntimeError("Claude did not return ideas.")
    batch: IdeaBatch = response.parsed_output
    valid = set(ids)
    for idea in batch.ideas:
        idea.source_ids = [i for i in idea.source_ids if i in valid]
    return batch


def save_ideas(db: Database, batch: IdeaBatch) -> list[int]:
    return db.add_ideas(idea.model_dump() for idea in batch.ideas)


def idea_to_dict(idea: Idea) -> dict[str, Any]:
    return idea.model_dump()
