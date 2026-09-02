from pathlib import Path

import pytest

from capturer.config import Settings
from capturer.db import Database


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(data_dir=tmp_path / "data", frames=3, keep_media=False)


@pytest.fixture
def db(settings: Settings) -> Database:
    database = Database(settings.db_path)
    yield database
    database.close()
