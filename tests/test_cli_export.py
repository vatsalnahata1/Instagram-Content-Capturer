import os

from capturer import cli
from capturer.db import Database
from capturer.export import ideas_to_markdown, posts_to_csv, posts_to_markdown


def seed(db: Database) -> int:
    pid = db.upsert_pending("abc", "https://www.instagram.com/reel/abc/")
    db.mark_done(
        pid, creator="studyguru", caption="cap", posted_at=None, duration_sec=1.0, like_count=5, comment_count=1,
        transcript="t", analysis={"topic": "SOP", "hook": "h", "hook_type": "mistake", "format": "talking head",
                                  "key_points": ["a", "b"], "remix_ideas": ["r1"], "on_screen_text": ["X"]},
    )
    db.add_ideas([{"title": "Idea one", "hook": "hook", "outline": "1\n2", "source_ids": [pid]}])
    return pid


def test_exports(db):
    seed(db)
    md = posts_to_markdown(db)
    assert "@studyguru - SOP" in md and "- a" in md and "On-screen text: X" in md
    csv_text = posts_to_csv(db)
    assert "studyguru" in csv_text and "a | b" in csv_text
    ideas = ideas_to_markdown(db, status=None)
    assert "Idea one" in ideas and "Sources: #1" in ideas


def test_cli_list_show_stats(settings, db, capsys, monkeypatch):
    seed(db)
    db.close()
    monkeypatch.setenv("CAPTURER_DATA_DIR", str(settings.data_dir))
    monkeypatch.chdir(settings.data_dir)  # no .env here

    assert cli.main(["list"]) == 0
    assert "@studyguru" in capsys.readouterr().out
    assert cli.main(["show", "abc"]) == 0
    assert "SOP" in capsys.readouterr().out
    assert cli.main(["show", "nope"]) == 1
    capsys.readouterr()
    assert cli.main(["stats"]) == 0
    assert "posts_done" in capsys.readouterr().out
    assert cli.main(["ideas", "--list"]) == 0
    assert "Idea one" in capsys.readouterr().out
    assert cli.main(["ideas", "--mark", "1:used"]) == 0
    assert cli.main(["export", "--format", "csv"]) == 0
    assert "studyguru" in capsys.readouterr().out


def test_cli_add_requires_instagram_url(settings, capsys, monkeypatch):
    monkeypatch.setenv("CAPTURER_DATA_DIR", str(settings.data_dir))
    assert cli.main(["add", "https://youtube.com/x"]) == 2
