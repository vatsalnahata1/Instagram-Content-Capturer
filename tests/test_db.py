from capturer.db import Database, analysis_of


def test_upsert_is_idempotent(db: Database):
    a = db.upsert_pending("abc", "https://www.instagram.com/reel/abc/")
    b = db.upsert_pending("abc", "https://www.instagram.com/reel/abc/")
    assert a == b
    assert db.get_post("abc")["status"] == "pending"


def test_mark_done_and_search(db: Database):
    pid = db.upsert_pending("abc", "https://www.instagram.com/reel/abc/")
    db.mark_done(
        pid, creator="studyguru", caption="SOP tips", posted_at=None, duration_sec=30.0,
        like_count=10, comment_count=2, transcript="write a strong statement of purpose",
        analysis={"topic": "SOP writing", "hook": "Stop making this SOP mistake"},
    )
    row = db.get_post(pid)
    assert row["status"] == "done"
    assert analysis_of(row)["topic"] == "SOP writing"
    assert [r["id"] for r in db.search_posts("statement of purpose")] == [pid]
    assert db.search_posts("nothing here") == []
    assert db.list_posts(status="done")[0]["creator"] == "studyguru"


def test_mark_failed_and_counts(db: Database):
    pid = db.upsert_pending("bad", "https://www.instagram.com/reel/bad/")
    db.mark_failed(pid, "boom")
    assert db.get_post("bad")["error"] == "boom"
    assert db.counts() == {"posts_failed": 1}


def test_ideas_roundtrip(db: Database):
    ids = db.add_ideas([
        {"title": "A", "hook": "h", "angle": "a", "format": "f", "outline": "1\n2", "rationale": "r", "source_ids": [1, 2]},
        {"title": "B"},
    ])
    assert len(ids) == 2
    assert [r["title"] for r in db.list_ideas()] == ["B", "A"]
    assert db.set_idea_status(ids[0], "used")
    assert [r["title"] for r in db.list_ideas(status="new")] == ["B"]
    assert not db.set_idea_status(999, "used")
    assert db.counts() == {"ideas_new": 1, "ideas_used": 1}
