"""Telegram bot: share an Instagram reel to it from your phone and it files the post."""

from __future__ import annotations

import asyncio
import logging

from .config import Settings
from .db import Database
from .pipeline import Capturer
from .urls import extract_instagram_urls

log = logging.getLogger(__name__)

HELP = (
    "Send me Instagram reel/post links (share from the Instagram app straight to this chat).\n"
    "I download, transcribe, read the on-screen text, and file the idea in your bank.\n\n"
    "Commands:\n"
    "/ideas [n] [focus...] - generate n ideas from the bank\n"
    "/recent - last 10 captured posts\n"
    "/stats - bank size\n"
    "/help - this message"
)


def run_bot(settings: Settings) -> int:
    if not settings.telegram_token:
        raise SystemExit("TELEGRAM_BOT_TOKEN is not set. Create a bot with @BotFather and add the token to .env.")

    from telegram import Update
    from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

    capturer = Capturer(settings)
    lock = asyncio.Lock()  # process one reel at a time; whisper + the API are heavy enough

    def allowed(update: Update) -> bool:
        if not settings.telegram_allowed_ids:
            return True
        user = update.effective_user
        return bool(user and user.id in settings.telegram_allowed_ids)

    async def guard(update: Update) -> bool:
        if allowed(update):
            return True
        if update.effective_message:
            await update.effective_message.reply_text(
                f"Not authorised. Your Telegram user id is {update.effective_user.id}; add it to TELEGRAM_ALLOWED_USER_IDS."
            )
        return False

    async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if await guard(update):
            await update.effective_message.reply_text(HELP)

    async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await guard(update):
            return
        message = update.effective_message
        text = (message.text or "") + " " + (message.caption or "")
        urls = extract_instagram_urls(text)
        if not urls:
            await message.reply_text("I did not find an Instagram link in that. Share a reel or post URL.")
            return
        for url in urls:
            status = await message.reply_text(f"Working on {url} ...")
            async with lock:
                result = await asyncio.to_thread(capturer.capture, url)
            await status.edit_text(result.short_summary()[:4000])

    async def on_ideas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await guard(update):
            return
        from .ideas import generate_ideas, save_ideas

        args = list(context.args or [])
        count = 5
        if args and args[0].isdigit():
            count = max(1, min(20, int(args.pop(0))))
        focus = " ".join(args) or None
        status = await update.effective_message.reply_text(f"Thinking up {count} ideas ...")
        try:
            async with lock:
                batch = await asyncio.to_thread(generate_ideas, capturer.db, settings, count=count, focus=focus)
            ids = await asyncio.to_thread(save_ideas, capturer.db, batch)
        except Exception as exc:  # noqa: BLE001
            log.exception("idea generation failed")
            await status.edit_text(f"Could not generate ideas: {exc}")
            return
        chunks = []
        for idea_id, idea in zip(ids, batch.ideas):
            chunks.append(f"#{idea_id} {idea.title}\nHook: {idea.hook}\nFormat: {idea.format}\n{idea.outline}")
        await status.edit_text("\n\n".join(chunks)[:4000])

    async def on_recent(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await guard(update):
            return
        rows = capturer.db.list_posts(status="done", limit=10)
        if not rows:
            await update.effective_message.reply_text("Nothing captured yet.")
            return
        from .db import analysis_of

        lines = [f"#{r['id']} @{r['creator'] or '?'}: {analysis_of(r).get('topic', '')}" for r in rows]
        await update.effective_message.reply_text("\n".join(lines)[:4000])

    async def on_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await guard(update):
            return
        counts = capturer.db.counts()
        await update.effective_message.reply_text(
            "\n".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "Empty bank."
        )

    app = ApplicationBuilder().token(settings.telegram_token).build()
    app.add_handler(CommandHandler(["start", "help"], on_start))
    app.add_handler(CommandHandler("ideas", on_ideas))
    app.add_handler(CommandHandler("recent", on_recent))
    app.add_handler(CommandHandler("stats", on_stats))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    log.info("Bot running. Share Instagram links to it from your phone.")
    app.run_polling(drop_pending_updates=True)
    return 0
