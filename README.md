# App Promo Studio

Turn your app's real screenshots into short vertical promo videos (Reels, Shorts, TikTok) and
Instagram stories, with hand-drawn animations, captions, voice-over and music, then publish them on a schedule.

- **Everything is animated with code** (Python + OpenCV + ffmpeg): a phone mockup, camera moves,
  hand-drawn circles/arrows/sparkles, live doodles drawn stroke by stroke inside your screenshots,
  captions with highlighted words and an end card with your logo. 1080×1920, 30 fps, h264 + aac.
- **A local approval panel** (`http://127.0.0.1:8765`): review scenarios, edit text, approve or
  reject, watch finished videos, ask for changes, create stories and see performance stats.
- **Claude Code writes the scenarios** on a schedule (optional): scenario ideas, shot plans and fixes
  are driven by plain instruction files in `studio/TASK_*.md`. Production itself needs no AI.
- **Publishing via Buffer** (Instagram Reels, YouTube Shorts, TikTok) with Cloudflare R2 as the public
  video host, or directly through the platform APIs.
- **Performance loop:** every post is measured 3 days after publishing; the summary feeds back into new scenarios.

> Only real screenshots are used, and scenarios may only describe features listed in `studio/APP_FACTS.md`.
> The engine never invents UI.

## How it works

```
Claude (scheduled)            Panel (you)                 Worker (automatic)            Buffer
writes scenarios  ──────────▶ approve / edit / reject ──▶ TTS → timing → render ──────▶ review → queue → post
+ shot plans                  ask for changes ◀────────── contact sheet + video          ▲
                                                                                         │ 3 days later
                              performance tab ◀──────── studio/stats.py ◀───────────────┘
```

## Requirements

- Python 3.10+
- [ffmpeg](https://ffmpeg.org/) on your PATH (`ffmpeg -version` should work)
- The [Poppins](https://fonts.google.com/specimen/Poppins) font: put `Poppins-Regular.ttf`,
  `Poppins-SemiBold.ttf`, `Poppins-Bold.ttf` and `Poppins-ExtraBold.ttf` into `assets/fonts/`
- For voice-over: a [Speko](https://platform.speko.ai) API key (or replace `synthesize()` in `studio/tts.py` with your TTS)
- For publishing: a Buffer account and a Cloudflare R2 bucket (both have free tiers)
- For automatic scenario writing: [Claude Code](https://claude.com/claude-code)

## Quick start

```bash
git clone https://github.com/<you>/app-promo-studio.git
cd app-promo-studio
pip install -r requirements.txt
# add the Poppins fonts to assets/fonts/ (see Requirements)
python -m tools.demo
```

The demo renders `videos/000_demo/000_demo.mp4` from two synthetic screenshots with placeholder
tones instead of a voice. No API key is needed. If that works, your setup is fine.

## Make it yours

1. **Brand:** edit `brand.json` (app name, colors, end-card text, language, voice). Put your logo at
   `assets/app_icon.png` (square PNG). Without it a letter icon is drawn.
2. **Screenshots:** put real screenshots of your app into `assets/screenshots/` (portrait, any size).
3. **Drawing regions (optional, recommended):** copy `assets/screenshots/regions.example.json` to
   `regions.json` and mark the areas where user content lives (calendar cells, a canvas, cards).
   The engine clears these areas and draws new doodles into them, so every video looks different.
   Check a definition with:
   ```bash
   python -m promovideo.regions month.png '{"seed": 3}' preview.png
   ```
4. **App facts:** fill in `studio/APP_FACTS.md`: features, the screenshot that proves each one, where to
   get the app. Scenarios and stories only describe what is listed there.
5. **Style:** adjust `studio/style_notes.md` (tone, length, words to avoid). The panel appends your feedback.
6. **Music (optional):** add royalty-free `.wav` tracks you have the rights to into `assets/music/`
   and describe them in `assets/music/music.json` (`{"calm_piano": {"title": "...", "description": "..."}}`).
7. **Stories (optional):** list the screens that stories may use under `story_screens` in `brand.json`.
8. **Keys:** copy `.env.example` to `.env` and fill in what you use. Never commit `.env`.

## Run the panel

```bash
python -m studio.panel
```

Opens `http://127.0.0.1:8765` (local only). While it is open, approved scenarios are produced one by
one in the background. Set `STUDIO_PORT` to use another port.

On Windows, `start-panel.bat` opens the panel and `start-background.bat` starts it minimized
(put a shortcut to it in `shell:startup` to start production when you log in).

## Let Claude write scenarios (optional)

In Claude Code, open this folder and create two scheduled tasks:

| Task | Schedule | Prompt |
|---|---|---|
| Scenario run | daily, e.g. 09:00 | `Run python -m studio.cli lock; if it prints BUSY, stop. Follow studio/TASK_SCENARIO.md as the daily morning run, then studio/TASK_VIDEO.md and studio/TASK_STORY.md. Finally run python -m studio.cli unlock.` |
| Request check | hourly | `Run python -m studio.cli pending-work; if it prints NONE, stop. Otherwise run python -m studio.cli lock (stop if BUSY), follow studio/TASK_SCENARIO.md as the hourly request check, then studio/TASK_VIDEO.md and studio/TASK_STORY.md, and run python -m studio.cli unlock.` |

You can also write scenarios by hand: create `scenarios/s001.json` in the format shown in
`studio/TASK_SCENARIO.md`, then approve it in the panel. Without a `shots` field, an automatic shot
plan is generated (`studio/autoshots.py`).

## Publishing setup

1. **Buffer:** create an account, connect your Instagram (professional account), YouTube and TikTok
   channels, turn off "notifications by default" in each channel, set a posting schedule, and create an
   API key at *Settings → API*. Put it into `BUFFER_API_KEY`.
2. **Cloudflare R2:** create a bucket, allow public access (R2.dev subdomain), create an API token with
   *Object Read & Write* for that bucket, and fill the `R2_*` values. Buffer fetches videos from there.
3. Test the connection:
   ```bash
   python -m publisher check
   ```
4. Videos you approve in the panel go to `approved/` and straight into the Buffer queue. Once they are
   posted everywhere they are moved to `published/`. See `python -m publisher` for all commands.

## Command reference

| Command | What it does |
|---|---|
| `python -m studio.panel` | approval panel + background production |
| `python -m studio.worker --once` | produce all approved scenarios once |
| `python -m studio.produce <sid>` | produce one scenario |
| `python -m studio.cli status` | status summary |
| `python -m studio.cli validate <sid>` | check a scenario file |
| `python -m studio.stats collect` | measure posts that reached day 3 |
| `python -m promovideo.render <video_dir> test\|build` | test frames / full render of a video folder |
| `python -m publisher check\|queue\|publish\|status` | publishing |

## Project layout

```
promovideo/   rendering engine (camera, doodles, captions, audio mix, story generator)
studio/       scenario store, panel, worker, TTS, stats, Claude task instructions
publisher/    Buffer + R2 publishing (and direct Instagram/YouTube/TikTok APIs)
tools/        demo and helpers
assets/       your screenshots, logo, music and fonts (not committed)
scenarios/ videos/ out/ approved/ published/ stories/ stats/   your data (not committed)
```

## Notes

- Make sure you have the rights to every screenshot, logo and music track you use.
- Platform rules change. Check Buffer's, Instagram's, YouTube's and TikTok's terms for automated posting
  and AI-generated content labels (`BUFFER_AI_LABEL`).

## License

MIT, see [LICENSE](LICENSE). Fonts and music you add keep their own licenses.
