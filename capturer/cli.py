"""Command-line entry point: ``capturer <command>``."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone

from . import __version__
from .config import Settings
from .db import Database, analysis_of
from .export import ideas_to_markdown, posts_to_csv, posts_to_markdown
from .pipeline import Capturer
from .urls import extract_instagram_urls


def _since(days: int | None) -> str | None:
    if not days:
        return None
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds")


def cmd_add(args: argparse.Namespace, settings: Settings) -> int:
    urls = extract_instagram_urls(" ".join(args.urls))
    if not urls:
        print("No Instagram URLs found in the arguments.", file=sys.stderr)
        return 2
    capturer = Capturer(settings)
    failures = 0
    for url in urls:
        result = capturer.capture(url, force=args.force)
        print(result.short_summary())
        print("-" * 40)
        failures += result.status == "failed"
    return 1 if failures else 0


def cmd_list(args: argparse.Namespace, settings: Settings) -> int:
    db = Database(settings.db_path)
    rows = db.search_posts(args.search, limit=args.limit) if args.search else db.list_posts(
        status=None if args.all else "done", limit=args.limit, since=_since(args.days)
    )
    if not rows:
        print("Nothing captured yet.")
        return 0
    for row in rows:
        a = analysis_of(row)
        status = "" if row["status"] == "done" else f" [{row['status']}]"
        print(f"#{row['id']:<4} @{(row['creator'] or '?'):<22} {a.get('topic', row['error'] or '')}{status}")
        if a.get("hook"):
            print(f"      hook: {a['hook'][:110]}")
    return 0


def cmd_show(args: argparse.Namespace, settings: Settings) -> int:
    db = Database(settings.db_path)
    row = db.get_post(args.key)
    if not row:
        print(f"No post {args.key}", file=sys.stderr)
        return 1
    record = dict(row)
    record["analysis"] = analysis_of(row)
    if args.json:
        print(json.dumps(record, indent=2, ensure_ascii=False))
        return 0
    a = record["analysis"]
    print(f"#{row['id']} @{row['creator']}  {row['url']}")
    print(f"status: {row['status']}  captured: {row['captured_at']}  posted: {row['posted_at']}")
    if row["error"]:
        print(f"error: {row['error']}")
    print(f"\nCaption:\n{row['caption'] or '(none)'}")
    print(f"\nTranscript:\n{row['transcript'] or '(none)'}")
    if a:
        print("\nAnalysis:")
        for key, value in a.items():
            if isinstance(value, list):
                print(f"  {key}:")
                for item in value:
                    print(f"    - {item}")
            else:
                print(f"  {key}: {value}")
    return 0


def cmd_ideas(args: argparse.Namespace, settings: Settings) -> int:
    from .ideas import generate_ideas, save_ideas

    db = Database(settings.db_path)
    if args.list:
        print(ideas_to_markdown(db, status=None if args.all else "new", limit=args.limit))
        return 0
    if args.mark:
        idea_id, _, status = args.mark.partition(":")
        if status not in {"new", "used", "discarded"} or not idea_id.isdigit():
            print("Use --mark ID:used or ID:discarded or ID:new", file=sys.stderr)
            return 2
        ok = db.set_idea_status(int(idea_id), status)
        print("updated" if ok else "no such idea")
        return 0 if ok else 1

    batch = generate_ideas(db, settings, count=args.count, since=_since(args.days), focus=args.focus)
    ids = save_ideas(db, batch)
    print("Themes in your bank:")
    for theme in batch.themes:
        print(f"- {theme.name} (posts {', '.join(f'#{i}' for i in theme.post_ids)}): {theme.observation}")
    print(f"\n{len(ids)} new ideas saved:\n")
    for idea_id, idea in zip(ids, batch.ideas):
        print(f"#{idea_id} {idea.title}")
        print(f"   hook: {idea.hook}")
        print(f"   format: {idea.format} | angle: {idea.angle}")
        for line in idea.outline.splitlines():
            if line.strip():
                print(f"     - {line.strip()}")
        print()
    return 0


def cmd_export(args: argparse.Namespace, settings: Settings) -> int:
    db = Database(settings.db_path)
    if args.what == "ideas":
        text = ideas_to_markdown(db, status=None)
    elif args.format == "csv":
        text = posts_to_csv(db)
    else:
        text = posts_to_markdown(db)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"Wrote {args.out}")
    else:
        print(text)
    return 0


def cmd_stats(args: argparse.Namespace, settings: Settings) -> int:
    db = Database(settings.db_path)
    for key, value in sorted(db.counts().items()):
        print(f"{key:<18} {value}")
    return 0


def cmd_serve(args: argparse.Namespace, settings: Settings) -> int:
    from .server import serve

    return serve(settings, host=args.host, port=args.port)


def cmd_bot(args: argparse.Namespace, settings: Settings) -> int:
    from .bot import run_bot

    return run_bot(settings)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="capturer", description="Instagram content idea bank")
    parser.add_argument("--version", action="version", version=f"capturer {__version__}")
    parser.add_argument("-v", "--verbose", action="store_true", help="show pipeline progress")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("add", help="capture one or more Instagram URLs")
    p.add_argument("urls", nargs="+")
    p.add_argument("--force", action="store_true", help="re-process even if already captured")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("list", help="list captured posts")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--days", type=int, default=None, help="only posts captured in the last N days")
    p.add_argument("--search", default=None, help="substring search in caption, transcript and analysis")
    p.add_argument("--all", action="store_true", help="include pending and failed posts")
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show", help="show one post in full")
    p.add_argument("key", help="post id or Instagram shortcode")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("ideas", help="generate ideas from the bank (or list / mark existing ones)")
    p.add_argument("-n", "--count", type=int, default=10)
    p.add_argument("--days", type=int, default=None, help="only use posts captured in the last N days")
    p.add_argument("--focus", default=None, help="steer ideas, e.g. 'SOP writing for UK masters'")
    p.add_argument("--list", action="store_true", help="list saved ideas instead of generating")
    p.add_argument("--all", action="store_true", help="with --list: include used/discarded ideas")
    p.add_argument("--limit", type=int, default=50)
    p.add_argument("--mark", default=None, help="ID:used | ID:discarded | ID:new")
    p.set_defaults(func=cmd_ideas)

    p = sub.add_parser("export", help="export posts or ideas")
    p.add_argument("what", choices=["posts", "ideas"], nargs="?", default="posts")
    p.add_argument("--format", choices=["md", "csv"], default="md")
    p.add_argument("--out", default=None)
    p.set_defaults(func=cmd_export)

    p = sub.add_parser("stats", help="counts of posts and ideas by status")
    p.set_defaults(func=cmd_stats)

    p = sub.add_parser("serve", help="run the local server the Chrome extension talks to")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8787)
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("bot", help="run the Telegram bot (share reels to it from your phone)")
    p.set_defaults(func=cmd_bot)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose or args.command in ("bot", "serve") else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = Settings.from_env()
    return int(args.func(args, settings) or 0)


if __name__ == "__main__":
    sys.exit(main())
