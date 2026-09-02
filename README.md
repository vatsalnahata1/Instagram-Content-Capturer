# Instagram Content Capturer

Share a reel to a bot while you scroll. It downloads the post, transcribes the speech, reads the
on-screen text from the video frames, and files a structured note into a local idea bank.
Later, ask it for new content ideas based on everything you have collected.

Built for a creator in the college applications and study abroad niche, but the niche is one
setting.

## How it works

```
phone: Instagram -> Share -> Telegram bot
                                  |
laptop/server: capturer bot  -->  yt-dlp (download + caption + creator)
                                  -> faster-whisper (transcript, local, free)
                                  -> PyAV keyframes -> Claude (reads overlays, hook, format, why it works)
                                  -> SQLite bank (data/capturer.db)
                                  -> reply on Telegram with the summary + 3 remix ideas

anytime: capturer ideas -n 10   -> Claude groups the bank into themes and proposes new posts
```

Each captured post is stored with: summary, topic, subtopics, hook and hook type, format,
key points, on-screen text, target audience, call to action, tone, why it works, and three
remix ideas for your niche. The raw transcript and caption are kept too, so you can search them.

## Setup

Requirements: Python 3.10+, a Claude API key, and a Telegram account. No ffmpeg needed.

```bash
git clone https://github.com/vatsalnahata1/Instagram-Content-Capturer
cd Instagram-Content-Capturer
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env      # then fill in the values below
```

`.env`:

| Variable | What it is |
|---|---|
| `ANTHROPIC_API_KEY` | From https://console.anthropic.com/ |
| `TELEGRAM_BOT_TOKEN` | Message `@BotFather` on Telegram, run `/newbot`, paste the token |
| `TELEGRAM_ALLOWED_USER_IDS` | Your Telegram user id (message `@userinfobot`). Keeps strangers out |
| `CAPTURER_NICHE` | One line describing your content niche |
| `INSTAGRAM_COOKIES_FROM_BROWSER` | `chrome`, `firefox`, `safari`, etc. Instagram usually needs a logged-in session to allow downloads. Log into Instagram in that browser once on the machine running the bot |

The first transcription downloads the Whisper `small` model (about 500 MB) and caches it.
Set `CAPTURER_WHISPER_MODEL=tiny` for speed or `medium` for accuracy.

## Use it

Start the bot on your laptop (or a cheap always-on box, a Raspberry Pi, or a small VPS):

```bash
capturer bot
```

On your phone: open a reel, tap Share, pick Telegram, pick your bot. Within a minute the bot
replies with the topic, hook, format, why it works, and three remix ideas. Every post you send
lands in the bank.

Bot commands: `/ideas 5 essay hooks` generates five ideas focused on essay hooks, `/recent` lists
the last ten posts, `/stats` shows bank size.

From the command line:

```bash
capturer add https://www.instagram.com/reel/XXXX/     # capture without the bot
capturer list --days 7                                 # what you saved this week
capturer list --search "SOP"                           # search caption, transcript, analysis
capturer show 12                                       # full record for post 12
capturer ideas -n 10 --days 30 --focus "UK masters"    # generate and save ideas
capturer ideas --list                                  # saved ideas you have not used yet
capturer ideas --mark 4:used                           # mark idea 4 as used
capturer export posts --format csv --out bank.csv      # into Sheets or Notion
capturer export ideas --out ideas.md
```

## Cost

Whisper runs locally and is free. Each post sends a few hundred words plus six small images to
Claude, which costs a few cents per reel. A batch of ideas costs about the same as a handful of
posts. Set `CAPTURER_FRAMES=3` to send fewer images.

## Where it goes next

- **Browser extension** for desktop: capture reels automatically as you scroll instagram.com,
  no share step.
- **Creator watchlist**: poll a list of accounts on a schedule so the bank grows while you sleep.
- **Embeddings** for dedupe and clustering once the bank passes a few hundred posts.

## Notes

- Instagram's terms prohibit automated collection at scale. This tool only fetches posts you
  personally choose to send it. Keep it that way.
- Downloaded videos are deleted after processing unless `CAPTURER_KEEP_MEDIA=true`.
- Everything lives in `data/` (SQLite database plus temporary media). Back it up if you care.

## Development

```bash
pip install -e ".[dev]"
pytest
```

The heavy stages (download, transcription, frames, Claude) are injectable on `Capturer`, so the
pipeline is tested end to end with fakes.
