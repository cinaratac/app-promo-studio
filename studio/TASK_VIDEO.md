# Task: shot plans and video revisions (Claude's part on the video side)

The panel produces videos by itself (`studio/worker.py` → `studio/produce.py` → `promovideo/auto.py`). Voice-over, timing, mixing, rendering and checks are automatic; progress shows in the panel as a percentage. The user watches the finished video in the panel and approves it; approved videos go to the Buffer queue.

Claude does two things:
1. Write shot plans (`shots`) for scenarios that have none.
2. Apply the user's video change requests (`status: "video_revise"`).

Working folder: the root of this repository.

## A. Writing a shot plan
Scope: `approved` and `pending` scenarios without a `shots` field. `approved` ones first.

1. Look at the scenario's `screenshots` and `visual_plan`. Other real screens may be used as well (`studio/APP_FACTS.md`).
2. To find coordinates, draw a grid on the screenshot and look at it (convert `.jfif`/`.webp` to PNG first):
   ```
   python -c "from PIL import Image,ImageDraw;im=Image.open('assets/screenshots/X').convert('RGB');d=ImageDraw.Draw(im);[d.line([(x,0),(x,im.height)],fill=(255,0,0)) or d.text((x+2,2),str(x),fill=(255,0,0)) for x in range(0,im.width,100)];[d.line([(0,y),(im.width,y)],fill=(0,0,255)) or d.text((2,y+2),str(y),fill=(0,0,255)) for y in range(0,im.height,100)];im.save('<scratchpad>/grid.png')"
   ```
3. Write the `shots` list. The full format is at the top of `promovideo/auto.py`.
   - One shot per sentence. The last sentence is `{"end": true}`.
   - Coordinates are ORIGINAL image pixels.
   - `cam` keys are `[time 0..1, zoom, center_x, center_y]`. Zoom 1 shows the whole screen, 2 a close-up.
   - Marks (`circle`, `underline`, `arrow`, `scribble`, `sparkle`, `tap`) come after the camera has arrived (`at` > the time the camera arrives).
   - For sentences with `caption_parts`, split camera and mark times roughly evenly across the parts.
   - For images showing a phone frame or personal content, use `crop` to keep only the app area. Personal photos and wallpapers are **never** shown.
   - The caption covers the bottom center of the frame (y≈1290). Bring important content to the upper middle with the camera.
   - **Variety (required):** videos must not look alike; the same screenshot should not always show the same doodles.
     - On screens with drawing regions (`assets/screenshots/regions.json`, see `promovideo/regions.py`) add a `fill` to each shot. Use a **different** `seed` per video and a `theme` that fits the topic: `winter`, `daily`, `summer`/`autumn`, `emotions`, `mixed`.
     - Avoid seed collisions: check the seeds of the last 10 scenarios.
     - Where a canvas/card region exists, have at least one **live drawing**: `{"type": "drawing", "cell": "<region id>", "motif": "<name>" | "auto", "at": .., "dur": 1.4–2.2}`. The motif is drawn stroke by stroke as if someone were drawing it.
     - Motifs: `MOTIFS` in `promovideo/doodlelib.py`; match the topic (coffee, cat, snowflake, rain…).
     - Vary screens and camera work too. Do not always use the same sequence (e.g. overview → close-up → pull back); balance close-ups, pans and wide shots differently per video.
     - To put marks (circles, arrows) on filled cells, preview the regions first:
       ```
       python -m promovideo.regions month.png '{"seed":11,"theme":"winter"}' <scratchpad>/preview.png
       ```
       The preview shows each region's id and center coordinate. Open it and check what was drawn where.
4. Check:
   - Save the scenario and run `python -m studio.cli validate <sid>`.
   - For a visual check, if the video folder exists, render test frames (`python -m promovideo.render videos/<folder> test`) and look at `out/contact.jpg`.
   - Without a folder, the panel creates the contact sheet during production; the user approves the video anyway.
5. With the panel open, `approved` scenarios are produced automatically. Otherwise:
   ```
   python -m studio.worker --once
   ```

## B. Video change request (`video_revise`)
**Change only what the user asked for.** Do not touch other shots, sentences, seeds or music. The system reuses unchanged scenes and audio from its cache. An unnecessary change (e.g. changing another shot's `fill.seed`) re-renders that scene too and can break a part the user liked.

1. Read and apply the latest `video_feedback` entry:
   - Visual problem: fix `shots` (camera, mark position, timing).
   - Pronunciation problem (a word is read wrong): do not touch the caption; add or fix `tts_text` on that line. If needed, try a few spellings with `python -c "from studio.tts import synthesize, transcribe; ..."`, transcribe them and pick the best.
   - Text change: fix `lines`. Only lines whose text changed get new audio; the others are kept.
   - Music change: change the `music` field.
2. Append `{"by":"claude","type":"revision","text":"<what changed>"}` to `history`.
3. Set the status to `approved`: `python -m studio.cli set <sid> approved`. The panel re-produces the video in the same folder.

## Rules
- No copyrighted music. Music is only what is in `assets/music` (the scenario's `music` field).
- Never invent buttons or text that belong to the app.
- The logo comes last (last shot `end`).
