"""Automatic shot plan: builds a varied 'shots' list for an approved scenario without waiting for Claude.

- A different seed per video -> different doodles (derived from the scenario id, reproducible)
- Doodle theme picked from the topic (winter, emotions, daily...)
- Screens come from the scenario's 'screenshots' list (else every image in assets/screenshots);
  screens with drawing regions (assets/screenshots/regions.json) are preferred
- Screens with one large region (a canvas/card) get a live drawing; screens with many cells get
  filled, and the camera zooms in on a few drawn cells with circle marks
- Screens without regions get a gentle camera pan
If Claude wrote a plan, that plan is used; this is only for missing plans.
"""
import zlib

import numpy as np
from PIL import Image

from promovideo import regions as R
from promovideo.auto import SHOTS

COLORS = ["yellow", "pink", "blue", "green", "purple"]
IMG_EXT = {".png", ".jpg", ".jpeg", ".jfif", ".webp"}

THEME_WORDS = [
    ("winter", ("winter", "snow", "christmas", "new year", "december", "cold")),
    ("emotions", ("feel", "mood", "happy", "sad", "emotion", "anxious")),
    ("summer", ("summer", "holiday", "vacation", "beach", "sea")),
    ("autumn", ("autumn", "fall", "october", "november", "rain")),
]


def _theme(s):
    if s.get("theme"):
        return s["theme"]
    t = " ".join([s.get("angle", ""), s.get("title", ""), " ".join(l["text"] for l in s.get("lines", []))]).lower()
    for theme, words in THEME_WORDS:
        if any(w in t for w in words):
            return theme
    return "daily"


def _all_screens():
    return sorted(p.name for p in SHOTS.glob("*") if p.suffix.lower() in IMG_EXT)


def _size(name):
    with Image.open(SHOTS / name) as im:
        return im.size


def _kind(name):
    """'canvas' (one big region), 'grid' (many cells), 'cards' (a few cells) or 'plain' (no regions)."""
    n = len(R.regions().get(name, {}))
    return "plain" if n == 0 else "canvas" if n == 1 else "grid" if n > 10 else "cards"


def _screens(s, n, rng):
    """Pick one screen per sentence: scenario screens first, enriched with region screens, no immediate repeats."""
    existing = set(_all_screens())
    given = [x for x in dict.fromkeys(s.get("screenshots", [])) if x in existing]
    pool = given or sorted(existing)
    if not pool:
        raise ValueError("no screenshots found: put your app screenshots in assets/screenshots")
    region_pool = [x for x in pool if R.has(x)]
    pool = pool + [x for x in sorted(existing) if R.has(x) and x not in pool] if not region_pool else pool
    out = []
    for k in range(n):
        if k == 0:
            c = pool[0]
        else:
            opts = [x for x in pool if x != out[-1]] or pool
            c = opts[int(rng.integers(len(opts)))]
        out.append(c)
    # at least one live drawing if a canvas screen exists
    canvas = [x for x in pool if _kind(x) == "canvas"]
    if canvas and not any(_kind(x) == "canvas" for x in out):
        out[min(1, n - 1)] = canvas[0]
    return out


def _parts(ln):
    return len(ln.get("caption_parts") or [1])


def plan(s):
    sid = s["id"]
    base = zlib.crc32(sid.encode()) % 100000
    rng = np.random.default_rng(base)
    theme = _theme(s)
    lines = s["lines"]
    body = lines[:-1] if len(lines) > 1 else lines
    screens = _screens(s, len(body), rng)
    shots = []
    for k, (ln, scr) in enumerate(zip(body, screens)):
        if ln.get("shot"):          # Claude already wrote a shot for this line
            shots.append(ln["shot"])
            continue
        w, h = _size(scr)
        cx0, cy0 = w / 2, h / 2
        fill = {"seed": base * 10 + k, "theme": theme}
        kind = _kind(scr)
        sh = {"screen": scr}
        if kind == "canvas":
            cid = next(iter(R.regions()[scr]))
            x, y = R.center(scr, cid)
            sh.update(fill=fill, cam=[[0, 1.0, cx0, cy0], [0.35, 1.15, (cx0 + x) / 2, (cy0 + y) / 2]],
                      marks=[{"type": "drawing", "cell": cid, "motif": "auto", "theme": theme, "at": 0.12, "dur": 1.9},
                             {"type": "sparkle", "x": x + (w * 0.3), "y": y - (h * 0.15), "r": 45, "at": 0.85}])
        elif kind == "grid":
            drawn = list(R.plan_fill(scr, fill).items())
            if not drawn:
                sh.update(fill=fill, cam=[[0, 1.0, cx0, cy0], [1, 1.12, cx0, cy0]])
                shots.append(sh)
                continue
            picks = [drawn[int(i)] for i in rng.choice(len(drawn), size=min(len(drawn), max(2, _parts(ln))), replace=False)]
            picks.sort(key=lambda kv: (R.center(scr, kv[0])[1], R.center(scr, kv[0])[0]))
            cam, marks = [[0, 1.0, cx0, cy0]], []
            span = 0.85 / len(picks)
            for i, (cid, _) in enumerate(picks):
                x, y = R.center(scr, cid)
                bx0, by0, bx1, by1 = R.cell(scr, cid)["draw"]
                cx = min(max(x, w * 0.25), w * 0.75)
                t0 = 0.08 + i * span
                cam += [[t0 + 0.08, 1.9, cx, y + 20], [t0 + span - 0.02, 1.9, cx, y + 20]]
                marks.append({"type": "circle", "x": x, "y": y - 10, "r": max(bx1 - bx0, by1 - by0) * 0.6,
                              "at": t0 + 0.14, "color": COLORS[(k + i) % len(COLORS)]})
            sh.update(fill=fill, cam=cam, marks=marks)
        elif kind == "cards":
            drawn = list(R.plan_fill(scr, fill)) or list(R.regions()[scr])
            cid = drawn[int(rng.integers(len(drawn)))]
            x, y = R.center(scr, cid)
            bx0, by0, bx1, by1 = R.cell(scr, cid)["draw"]
            sh.update(fill=fill, cam=[[0, 1.0, cx0, cy0], [0.3, 1.15, cx0, (cy0 + y) / 2], [0.55, 1.6, x, y], [1, 1.6, x, y]],
                      marks=[{"type": "circle", "x": x, "y": y, "rx": (bx1 - bx0) * 0.6, "ry": (by1 - by0) * 0.6,
                              "at": 0.62, "color": COLORS[k % len(COLORS)]}])
        else:
            # screen without regions (settings etc.): gentle pan, no marks
            sh.update(cam=[[0, 1.0, cx0, cy0], [1, 1.15, cx0, cy0 + h * 0.05]])
        shots.append(sh)
    if len(lines) > 1:
        shots.append({"end": True})
    return shots
