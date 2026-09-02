"""Turn a downloaded post (caption + transcript + keyframes) into a structured record with Claude."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from .config import Settings
from .fetch import FetchedPost
from .media import Frame


class PostAnalysis(BaseModel):
    """What we keep about every post. Field descriptions steer the model."""

    summary: str = Field(description="Two or three sentences: what the post says and how it says it.")
    topic: str = Field(description="Primary topic in a few words, e.g. 'Common App essay mistakes'.")
    subtopics: list[str] = Field(description="Specific sub-themes covered.")
    hook: str = Field(description="The opening line or on-screen text used to stop the scroll, verbatim where possible.")
    hook_type: str = Field(description="One of: question, bold claim, mistake, story, listicle, contrarian, curiosity gap, relatable pain, other.")
    format: str = Field(description="One of: talking head, text overlay on b-roll, voiceover, skit, screen recording, carousel, interview, green screen, other.")
    key_points: list[str] = Field(description="The substantive points, claims or steps, one per item.")
    on_screen_text: list[str] = Field(description="Text overlays visible in the frames, in order. Empty if none.")
    target_audience: str = Field(description="Who this is for, e.g. 'Indian students applying to US masters programs'.")
    call_to_action: str = Field(description="What the viewer is asked to do (comment, follow, DM, link in bio). 'none' if absent.")
    tone: str = Field(description="One or two words, e.g. 'urgent', 'reassuring', 'humorous'.")
    why_it_works: str = Field(description="Why this post likely performs: hook, emotion, specificity, timing.")
    remix_ideas: list[str] = Field(description="Three concrete ways the user could make their own version for their niche.")


SYSTEM_PROMPT = """You analyse short-form social media posts for a content creator.
The creator's niche: {niche}.

You will get a post's caption, creator handle, a speech transcript, and sample frames from the video.
Read the frames for on-screen text overlays and visual format; read the transcript for the substance.
Be concrete and specific. Quote hooks and overlay text verbatim when you can read them.
If there is no speech, say so in the summary and rely on the frames and caption.
Remix ideas must fit the creator's niche and be something they could film this week."""


def _build_user_content(post: FetchedPost, transcript_text: str, frames: list[Frame]) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = []
    for frame in frames:
        content.append({"type": "text", "text": f"Frame at {frame.timestamp_sec:.1f}s:"})
        content.append(
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": frame.jpeg_b64}}
        )
    meta = [
        f"URL: {post.url}",
        f"Creator: {post.creator or 'unknown'}",
        f"Posted: {post.posted_at or 'unknown'}",
        f"Duration: {post.duration_sec or 'unknown'} seconds",
        f"Likes: {post.like_count if post.like_count is not None else 'unknown'}",
        f"Comments: {post.comment_count if post.comment_count is not None else 'unknown'}",
    ]
    content.append({"type": "text", "text": "\n".join(meta)})
    content.append({"type": "text", "text": f"Caption:\n{post.caption or '(no caption)'}"})
    content.append({"type": "text", "text": f"Transcript:\n{transcript_text or '(no speech detected)'}"})
    content.append({"type": "text", "text": "Analyse this post."})
    return content


class AnalysisRefused(RuntimeError):
    pass


def analyze_post(post: FetchedPost, transcript_text: str, frames: list[Frame], settings: Settings, client=None) -> PostAnalysis:
    import anthropic  # lazy so tests can run without the SDK configured

    client = client or anthropic.Anthropic()
    response = client.messages.parse(
        model=settings.model,
        max_tokens=16000,
        system=SYSTEM_PROMPT.format(niche=settings.niche),
        messages=[{"role": "user", "content": _build_user_content(post, transcript_text, frames)}],
        output_format=PostAnalysis,
    )
    if response.stop_reason == "refusal":
        detail = getattr(response, "stop_details", None)
        raise AnalysisRefused(f"Claude declined to analyse this post ({getattr(detail, 'category', 'unknown')}).")
    if response.parsed_output is None:
        raise RuntimeError("Claude returned no structured analysis.")
    return response.parsed_output
