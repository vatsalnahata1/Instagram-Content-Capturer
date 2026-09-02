"""Configuration loaded from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def load_dotenv(path: Path | None = None) -> None:
    """Minimal .env loader so we don't need python-dotenv. Existing env wins."""
    path = path or Path.cwd() / ".env"
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    niche: str = "college applications and studying abroad"
    model: str = "claude-opus-5"
    data_dir: Path = field(default_factory=lambda: Path("data"))
    whisper_model: str = "small"
    frames: int = 6
    keep_media: bool = False
    telegram_token: str = ""
    telegram_allowed_ids: set[int] = field(default_factory=set)
    cookies_from_browser: str = ""
    cookies_file: str = ""
    export_dir: Path | None = None   # e.g. a Google Drive folder; exports are rewritten after every capture

    @property
    def db_path(self) -> Path:
        return self.data_dir / "capturer.db"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv()
        allowed = os.environ.get("TELEGRAM_ALLOWED_USER_IDS", "")
        ids = {int(x) for x in allowed.replace(";", ",").split(",") if x.strip().isdigit()}
        export_raw = os.environ.get("CAPTURER_EXPORT_DIR", "").strip()
        return cls(
            export_dir=Path(export_raw).expanduser() if export_raw else None,
            niche=os.environ.get("CAPTURER_NICHE", cls.niche),
            model=os.environ.get("CAPTURER_MODEL", cls.model),
            data_dir=Path(os.environ.get("CAPTURER_DATA_DIR", "data")),
            whisper_model=os.environ.get("CAPTURER_WHISPER_MODEL", cls.whisper_model),
            frames=int(os.environ.get("CAPTURER_FRAMES", cls.frames)),
            keep_media=_bool(os.environ.get("CAPTURER_KEEP_MEDIA"), False),
            telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            telegram_allowed_ids=ids,
            cookies_from_browser=os.environ.get("INSTAGRAM_COOKIES_FROM_BROWSER", ""),
            cookies_file=os.environ.get("INSTAGRAM_COOKIES_FILE", ""),
        )
