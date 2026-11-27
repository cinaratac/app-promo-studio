"""Offline demo: renders a sample video without any API key, app or Claude.

  python -m tools.demo

Creates two synthetic screenshots (assets/screenshots/demo_month.png, demo_editor.png) with drawing
regions, a short script with a shot plan, placeholder "voice" clips (soft tones, no TTS) and renders
videos/000_demo/000_demo.mp4. Use it to check your setup (Python packages, ffmpeg, fonts).
"""
import json
import math
import sys
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from promovideo.core import ASSETS, ROOT, font

SHOTS = ASSETS / "screenshots"
VDIR = ROOT / "videos" / "000_demo"
SR = 24000

LINES = [
    {"id": "l1", "text": "Can you remember what last Tuesday looked like?", "highlight": "Tuesday", "min_dur": 2.6},
    {"id": "l2", "text": "Draw one tiny doodle for each day.", "highlight": "doodle", "min_dur": 2.8},
    {"id": "l3", "text": "At the end of the month, your days tell a story.", "highlight": "story"},
    {"id": "l4", "text": "Try it today.", "highlight": "today"},
]

MONTH_XS = [30, 177, 324, 471, 618, 765, 912, 1059]
MONTH_YS = [640, 840, 1040, 1240, 1440, 1640]


def _month():
    im = Image.new("RGB", (1089, 1900), (250, 249, 245))
    d = ImageDraw.Draw(im)
    d.text((544, 300), "November", font=font(84, "ExtraBold"), fill=(40, 60, 45), anchor="mm")
    for i, w in enumerate("MTWTFSS"):
        d.text(((MONTH_XS[i] + MONTH_XS[i + 1]) / 2, 580), w, font=font(36, "SemiBold"), fill=(120, 125, 120), anchor="mm")
    for n in range(1, 31):
        r, c = divmod(n - 1 + 5, 7)
        x0, x1, y0, y1 = MONTH_XS[c], MONTH_XS[c + 1], MONTH_YS[r], MONTH_YS[r + 1]
        d.rounded_rectangle([x0 + 4, y0 + 4, x1 - 4, y1 - 4], 18, fill=(255, 255, 255), outline=(225, 228, 222), width=2)
        d.text((x0 + 16, y0 + 12), str(n), font=font(30, "SemiBold"), fill=(90, 95, 90))
    im.save(SHOTS / "demo_month.png")


def _editor():
    im = Image.new("RGB", (1089, 1900), (250, 249, 245))
    d = ImageDraw.Draw(im)
    d.text((544, 260), "Tuesday, November 12", font=font(56, "Bold"), fill=(40, 60, 45), anchor="mm")
    d.text((544, 350), "What did today look like?", font=font(40, "Regular"), fill=(110, 115, 110), anchor="mm")
    d.rounded_rectangle([120, 460, 969, 1310], 30, fill=(255, 255, 255), outline=(225, 228, 222), width=3)
    for k, col in enumerate([(30, 32, 30), (200, 70, 60), (240, 200, 80), (140, 180, 215), (140, 185, 140), (195, 160, 225)]):
        d.ellipse([200 + k * 120, 1420, 270 + k * 120, 1490], fill=col)
    im.save(SHOTS / "demo_editor.png")


def _regions():
    p = SHOTS / "regions.json"
    reg = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    reg["demo_month.png"] = {"grid": {"xs": MONTH_XS, "ys": MONTH_YS, "count": 30, "start": 5, "id": "d{n}",
                                      "pad": [8, 52, 8, 8], "draw_pad": [22, 52, 22, 14]}}
    reg["demo_editor.png"] = {"canvas": {"clear": [[130, 470, 959, 1300]], "draw": [260, 560, 830, 1210]}}
    p.write_text(json.dumps(reg, indent=2), encoding="utf-8")


def _tone_clip(text, dst):
    """Placeholder voice: one soft tone pulse per word with short pauses at commas."""
    out = [np.zeros(int(0.08 * SR))]
    for w in text.split():
        n = int(SR * (0.16 + 0.035 * len(w)))
        t = np.arange(n) / SR
        env = np.sin(np.pi * t / t[-1]) ** 2
        out.append(0.18 * env * np.sin(2 * math.pi * 220 * t))
        out.append(np.zeros(int(SR * (0.22 if w[-1] in ",.?!" else 0.06))))
    x = (np.concatenate(out) * 32767).astype(np.int16)
    with wave.open(str(dst), "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes(x.tobytes())


def main():
    from promovideo import audio as au
    from promovideo.auto import SCENES_SHIM, AUDIO_SHIM
    from promovideo.render import build_cached, test_frames

    SHOTS.mkdir(parents=True, exist_ok=True)
    _month()
    _editor()
    _regions()
    shots = [
        {"screen": "demo_month.png", "fill": {"seed": 4, "theme": "daily"},
         "cam": [[0, 1.0, 544, 1150], [0.45, 1.8, 400, 1040]],
         "marks": [{"type": "circle", "x": 397, "y": 1050, "r": 95, "at": 0.6, "color": "yellow"}]},
        {"screen": "demo_editor.png", "cam": [[0, 1.0, 544, 950], [0.3, 1.12, 544, 900]],
         "marks": [{"type": "drawing", "cell": "canvas", "motif": "coffee", "at": 0.15, "dur": 1.9},
                   {"type": "tap", "x": 355, "y": 1455, "at": 0.85}]},
        {"screen": "demo_month.png", "fill": {"seed": 9, "theme": "mixed", "density": 1.0},
         "cam": [[0, 1.6, 544, 1150], [0.7, 1.0, 544, 1150]],
         "marks": [{"type": "sparkle", "x": 900, "y": 300, "r": 50, "at": 0.75}]},
        {"end": True},
    ]
    (VDIR / "voice").mkdir(parents=True, exist_ok=True)
    (VDIR / "out").mkdir(exist_ok=True)
    script = {"title": "Demo", "lines": LINES, "shots": shots, "music": "auto", "scenario": "demo",
              "end_card": {"subtitle": "Now on the App Store.", "subtitle_highlight": "App Store."}}
    (VDIR / "script.json").write_text(json.dumps(script, indent=2), encoding="utf-8")
    for ln in LINES:
        _tone_clip(ln["text"], VDIR / "voice" / f"{ln['id']}.wav")
    au.analyze_dir(VDIR / "voice", VDIR / "voice" / "timing.json")
    (VDIR / "scenes.py").write_text(SCENES_SHIM, encoding="utf-8")
    (VDIR / "audio.py").write_text(AUDIO_SHIM, encoding="utf-8")
    test_frames(VDIR)
    final, ok, *_ = build_cached(VDIR, jobs=2, on_progress=lambda r, m: print(f"\r{int(r * 100):3d}% {m}", end=""))
    print(f"\n{'OK' if ok else 'CHECK FAILED'}: {final}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
