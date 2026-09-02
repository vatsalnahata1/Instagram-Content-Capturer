# Instagram Content Capturer

Scroll Instagram in Chrome as usual. A small extension notices every reel you actually watch,
and a local server transcribes it, reads the on-screen text, and files a structured note into your
content idea bank. Later, ask for new content ideas based on everything you have collected.

Built for a creator in the college applications and study abroad niche, but the niche is one
setting. Nothing leaves your machine except the transcript and a few frames sent to Claude.

## How it works

```
Chrome (instagram.com)
  extension watches the reel in view ─┐  after N seconds: creator, caption, CDN link,
                                      │  a few frames grabbed from the video
                                      ▼
laptop:  capturer serve  (http://127.0.0.1:8787)
           ├─ fetch the video from the link the page was already playing
           │    (fallback: yt-dlp; fallback: use the grabbed frames only)
           ├─ faster-whisper transcript (local, free)
           ├─ PyAV keyframes -> Claude reads overlays, hook, format, why it works
           └─ SQLite bank (data/capturer.db)

anytime: capturer ideas -n 10   -> Claude groups the bank into themes and proposes new posts
```

Each captured post is stored with: summary, topic, subtopics, hook and hook type, format,
key points, on-screen text, target audience, call to action, tone, why it works, and three
remix ideas for your niche. The raw transcript and caption are kept too, so you can search them.

## Setup (Mac + Chrome)

Requirements: Python 3.10+, a Claude API key, Google Chrome. No ffmpeg needed.

**1. Install the server**

```bash
git clone https://github.com/vatsalnahata1/Instagram-Content-Capturer
cd Instagram-Content-Capturer
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env      # add your ANTHROPIC_API_KEY and CAPTURER_NICHE
```

**2. Load the extension**

1. Open `chrome://extensions` in Chrome.
2. Turn on **Developer mode** (top right).
3. Click **Load unpacked** and pick the `extension/` folder of this repo.
4. Pin the extension. Its popup shows server status, recent captures, and settings.

**3. Run it**

```bash
capturer serve
```

Keep that terminal open and scroll instagram.com in Chrome. When a reel has played for four
seconds (adjustable in the popup) the extension sends it to the server. A toast in the corner
confirms, the extension badge shows a tick, and the popup lists what was captured. The first
transcription downloads the Whisper `small` model (about 500 MB) and caches it.

Reels you skip past are ignored. Reels already in the bank are not re-processed.

## Getting ideas out

```bash
capturer ideas -n 10 --days 30                         # generate and save ideas
capturer ideas -n 5 --focus "SOP writing for UK masters"
capturer ideas --list                                  # saved ideas you have not used yet
capturer ideas --mark 4:used
capturer list --days 7                                 # what you saved this week
capturer list --search "SOP"                           # search caption, transcript, analysis
capturer show 12                                       # full record for post 12
capturer export posts --format csv --out bank.csv      # into Sheets or Notion
capturer export ideas --out ideas.md
```

The popup's **Generate 5 ideas** button does the same without the terminal.

Other ways in: `capturer add <url>` captures a link directly, and `capturer bot` runs an optional
Telegram bot you can share reels to from your phone (needs `TELEGRAM_BOT_TOKEN` in `.env`).

## Settings (`.env`)

| Variable | What it is |
|---|---|
| `ANTHROPIC_API_KEY` | From https://console.anthropic.com/ |
| `CAPTURER_NICHE` | One line describing your content niche |
| `CAPTURER_WHISPER_MODEL` | `tiny` for speed, `small` (default), `medium` for accuracy |
| `CAPTURER_FRAMES` | Frames sent to Claude per video (default 6) |
| `INSTAGRAM_COOKIES_FROM_BROWSER` | Only for the yt-dlp fallback, e.g. `chrome` |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_IDS` | Only for the optional phone bot |

## Cost

Whisper runs locally and is free. Each post sends a few hundred words plus a handful of small
images to Claude, which costs a few cents per reel. A batch of ideas costs about the same as a
few posts.

## Where it goes next

- **Creator watchlist**: poll a list of accounts on a schedule so the bank grows while you sleep.
- **Embeddings** for dedupe and clustering once the bank passes a few hundred posts.
- **Audio from the tab** as a last-resort fallback when no video link can be fetched.

## Notes

- The extension only reacts to reels you watch in your own logged-in browser, and the server
  only fetches the media link the page was already playing. It does not crawl or scrape feeds.
- Downloaded videos are deleted after processing unless `CAPTURER_KEEP_MEDIA=true`.
- Everything lives in `data/` (SQLite database plus temporary media). Back it up if you care.
- The server binds to 127.0.0.1 only.

## Development

```bash
pip install -e ".[dev]"
pytest                                   # includes an end-to-end test that loads the extension
                                         # into Chromium against a fake instagram.com page
node --test extension/test/extract.test.js
```

The heavy stages (download, transcription, frames, Claude) are injectable on `Capturer`, so the
pipeline is tested end to end with fakes.
