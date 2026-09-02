from pathlib import Path

from capturer import cli
from capturer.config import Settings
from capturer.db import Database
from capturer.export import EXPORT_FILES, write_exports
from tests.test_cli_export import seed
from tests.test_pipeline import make_capturer


def test_write_exports_creates_all_files_atomically(db, tmp_path):
    seed(db)
    out = tmp_path / "drive" / "Content Bank"
    written = write_exports(db, out)
    assert [p.name for p in written] == list(EXPORT_FILES)
    assert "studyguru" in (out / "content-bank.csv").read_text()
    assert "Idea one" in (out / "ideas.md").read_text()
    assert not [p for p in out.iterdir() if p.name.startswith(".")], "no temp files left behind"


def test_write_exports_is_noop_without_dir(db):
    assert write_exports(db, None) == []


def test_write_exports_swallows_unwritable_dir(db, tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    assert write_exports(db, blocker / "sub") == []   # parent is a file -> OSError, logged not raised


def test_capture_refreshes_exports(tmp_path):
    export_dir = tmp_path / "drive"
    settings = Settings(data_dir=tmp_path / "data", frames=3, export_dir=export_dir)
    db = Database(settings.db_path)
    cap = make_capturer(settings, db, tmp_path)
    assert cap.capture("https://www.instagram.com/reel/TeSt123/").status == "done"
    assert (export_dir / "content-bank.csv").exists()
    assert "Stop writing your SOP like this" in (export_dir / "content-bank.md").read_text()


def test_settings_reads_export_dir(monkeypatch):
    monkeypatch.setenv("CAPTURER_EXPORT_DIR", "~/Drive/Bank")
    assert Settings.from_env().export_dir == Path("~/Drive/Bank").expanduser()
    monkeypatch.setenv("CAPTURER_EXPORT_DIR", "")
    assert Settings.from_env().export_dir is None


def test_cli_export_sync(settings, db, tmp_path, monkeypatch, capsys):
    seed(db)
    db.close()
    monkeypatch.setenv("CAPTURER_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("CAPTURER_EXPORT_DIR", str(tmp_path / "drive"))
    monkeypatch.chdir(settings.data_dir)
    assert cli.main(["export", "--sync"]) == 0
    assert "content-bank.csv" in capsys.readouterr().out
    monkeypatch.setenv("CAPTURER_EXPORT_DIR", "")
    assert cli.main(["export", "--sync"]) == 2
