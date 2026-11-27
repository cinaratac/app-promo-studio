# Task: scenario run

Runs in two modes:
- **Daily morning run:** all steps 0–5.
- **Hourly request check:** only steps 1 and 2 (revisions and requests), then 4 and 5.

When you revise a scenario, update its `shots` field to match the new text too.

Working folder: the root of this repository. Follow this file from start to finish. The user is not around during this run; do not ask questions, decide according to the rules.

## 0. Preparation
1. Get the status summary:
   ```
   python -m studio.cli status
   ```
2. Read `studio/style_notes.md`. The user's preferences live there; always follow them.
3. Look at the history of recently rejected and revised scenarios (`scenarios/*.json`, `history` field). Work out which hooks and topics the user likes.
4. Look at performance: `studio/performance_notes.md` (automatic; each video is measured 3 days after it is published). See which formats, openings and lengths get more views and engagement. These are **trends, not rules**: try what works more often, but about a third of the scenarios should use new or rarely tried formats/openings; do not decide based on "little data" (n<3) rows. The user's own rules (style notes) always come first.
5. Read the app facts: `studio/APP_FACTS.md`. Only describe features listed there; never invent features.

## 1. Revisions (priority 1)
For every scenario with `status: "revise"`:
- Apply the latest `feedback` entry.
- Texts the user edited by hand in the panel are already in the file; do not undo them.
- Increase `version` by 1 and set `status: "pending"`.
- Append `{"by":"claude","type":"revision","text":"<what changed, one sentence>"}` to `history`.
- If the feedback contains a general preference (e.g. "always make it shorter"), add it as a one-line rule to the "Learned from feedback" section of `studio/style_notes.md`.

## 2. Custom requests (priority 2)
For every request with `status: "open"` in `scenarios/requests.json`, write as many scenarios as its `count` field (1 if missing). If `text` is empty, write on varied topics (from the angle pool in step 3, without repeating the most recent ones). If `text` is filled in, all of them are on that topic, but with different hooks and angles. Add a `request_id` field to the scenario, then close the request:
```
python -m studio.cli req-done <rid> <sid> [sid2]
```
If a request asks for something the app does not have, do not invent it. Say so clearly in the scenario's `summary` and write about the closest real feature.

## 3. Stock top-up
Only in the **daily morning run** (not in the request check). Goal: at least **6** scenarios waiting for approval (`pending`), so the user always has scenarios ready. Write as many new ones as are missing.
- Vary the topics. Look at the `angle` of the last 10 scenarios; do not use the same angle twice in a row.
- Angle pool: the "Angles" list in `studio/APP_FACTS.md` (each angle is based on a real feature).
- Store/availability wording comes from `studio/APP_FACTS.md` and `brand.json` (`end_card`). Never claim a store, price or "free" that is not stated there.

## 3b. Story and engaging structure
Videos should not just be screenshots + text, and they should not all look the same.
- Each scenario tells a small story where it fits: **situation/problem → discovery (the app) → small happy ending**.
- Rotate formats; never the same format twice in a row:
  - **mini story** (the structure above)
  - **dialogue**: two voices; one asks or doubts, the other shows the phone
  - **riddle**: show the result first ("what happened here?"), then the story behind it
  - **before / after**
  - **POV / familiar moment**: "11 PM, and you can't remember how the day went…"
  - **challenge**: "one minute a day for 7 days"
  - **tip**
- The first second of every scenario is surprising or funny (a reaction, a question, an unexpected fact). No cliché openings (see the rejections in the style notes).

## 4. Scenario file format
Get the number for the new scenario:
```
python -m studio.cli next-id
```
Then write `scenarios/<sid>.json` as UTF-8:
```json
{
  "id": "s004",
  "status": "pending",
  "version": 1,
  "created": "<ISO time>",
  "title": "Short title shown in the panel",
  "angle": "widgets",
  "summary": "One sentence: what the video says and why it works",
  "est_seconds": 18,
  "request_id": null,
  "screenshots": ["week.png"],
  "format": "dialogue",
  "opening": "question",
  "theme": "daily",
  "lines": [
    {"id": "l1", "text": "Hook sentence?", "highlight": "keyword", "min_dur": 3.2},
    {"id": "l2", "text": "...", "highlight": "...",
     "caption_parts": ["Part one,", "part two."], "highlight_parts": ["one", "two"]}
  ],
  "visual_plan": ["l1 visuals: which screen, where the camera goes, which doodle", "l2 ..."],
  "end_card": {"subtitle": "Now on the App Store.", "subtitle_highlight": "App Store."},
  "music": "auto",
  "post": {
    "title": "YouTube title (≤100 characters)",
    "language": "en",
    "caption": "Instagram/TikTok/YouTube caption: 2–4 short lines, the last line says where to get the app",
    "hashtags": ["myapp", "productivity", "planner"],
    "tiktok": {"hashtags": ["myapp", "productivity", "planner"]}
  },
  "shots": [],
  "history": [{"at": "<ISO>", "by": "claude", "type": "created", "text": ""}]
}
```

Rules:
- `highlight` must appear verbatim in the sentence.
- **TTS spelling (`tts_text`):** TTS sometimes mispronounces brand names or foreign words. Add `tts_text` to that line; the caption stays `text`, the voice is generated from `tts_text`. Example: `{"text": "Get it on the App Store.", "tts_text": "Get it on the App Store."}` with a phonetic spelling where needed. Keep a list of known fixes in `studio/style_notes.md`.
- Speaking rate is about 2.6 words/second. `est_seconds` = that + 3 s for the end card. There is no fixed target length; choose the length by content and vary it (style notes).
- `visual_plan` only uses real screens in `assets/screenshots`. Never show personal photos, wallpapers or other people's data; use `crop` to keep only the app area.
- **Variety:** every scenario's shot plan has new doodles (`fill`, a different seed and a fitting theme) and, where a canvas region exists, at least one live drawing (`drawing`). Details in `studio/TASK_VIDEO.md` section A.
- **The shot plan (`shots`) is required.** Write every scenario with its `shots`. Rules in `studio/TASK_VIDEO.md` section A, format at the top of `promovideo/auto.py`. An approved scenario is produced right away; without `shots` an automatic plan is used (`studio/autoshots.py`), which is less tailored.
- After writing each file, check it and fix any errors:
  ```
  python -m studio.cli validate <sid>
  ```

## 5. Finish
Print `python -m studio.cli status` and a short summary: how many revisions, requests and new scenarios. The user approves scenarios in the panel (`python -m studio.panel`).

## Performance tags (`format`, `opening`)
Write both fields on every scenario; the performance stats compare videos by them (`studio/stats.py`).
- `format`: `mini story`, `dialogue`, `riddle`, `before/after`, `POV`, `challenge`, `tip`, `other`
- `opening` (type of the first second): `question`, `funny reaction`, `surprising fact`, `POV/moment`, `challenge`, `confession`, `other`
If you tried something new, pick the closest one; `other` if nothing fits.
