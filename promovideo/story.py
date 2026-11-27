"""Instagram story generator: photo (1080x1920 JPG) or short video (6-12 s, music, no voice-over).

spec = {
  "kind": "photo" | "video",
  "headline": "Which day did you draw today?",  # big text at the top (required)
  "highlight": "draw",                          # yellow band (optional)
  "sub": "One drawing a day.",                  # small text under the phone (optional)
  "screen": "editor.png",                       # one of brand.json "story_screens"
  "cell": "paper",                              # video: region for the live drawing (empty = automatic)
  "motif": "auto",                              # one of doodlelib.MOTIFS or auto
  "theme": "daily", "seed": 7,
  "duration": 8, "music": "auto" | "none" | track name
}
The Instagram UI covers the top ~250 px and bottom ~300 px; text and logo stay outside those areas.

Story screens are configured in brand.json:
  "story_screens": {
    "editor.png": {"crop": [0, 70, 471, 1024], "cell": "paper", "center": [235, 540], "zoom": 1.12},
    "month.png":  {"cell": null, "center": [472, 1250], "zoom": 2.5, "ring": true}
  }
  crop: optional area of the screenshot, cell: default live-drawing region (null = pick a filled one),
  center: opening camera center, zoom: zoom on the cell, ring: circle the cell after drawing (small cells).
"""
import json
import subprocess
import zlib
from pathlib import Path

import numpy as np
from PIL import Image

from . import doodlelib, regions
from .brand import BRAND
from .core import FPS, W, H, SCREEN_W, SCREEN_H, INK, ACCENTS, find_bin, clamp01, ease_back, ease_out, ease_in_out, lerp
from .doodle import Doodle
from .gfx import Phone, ScreenSource, bg_frame, caption_image, paste_center, app_icon, title_image, draw_end_card
from .music import resolve as resolve_music


def screens():
    """screen -> config dict (from brand.json "story_screens")."""
    return {k: v for k, v in (BRAND.get("story_screens") or {}).items() if not k.startswith("_")}


HEAD_Y, PH_Y, PH_S, SUB_Y, LOGO_Y = 330, 1010, 0.56, 1545, 1650
END_LEN = 1.8


def _theme_seed(spec):
    seed = int(spec.get("seed", zlib.crc32(spec.get("headline", "").encode()) % 9973))
    return spec.get("theme", "daily"), seed


class Story:
    def __init__(self, spec):
        self.spec = spec
        self.kind = spec.get("kind", "photo")
        cfgs = screens()
        if not cfgs:
            raise ValueError('no story screens configured: add "story_screens" to brand.json')
        scr = spec.get("screen") or next(iter(cfgs))
        if scr not in cfgs:
            raise ValueError(f"story screen not supported: {scr} (options: {list(cfgs)})")
        self.screen = scr
        cfg = cfgs[scr]
        crop, dcell = cfg.get("crop"), cfg.get("cell")
        theme, seed = _theme_seed(spec)
        self.theme, self.seed = theme, seed
        rng = np.random.default_rng(seed)
        fill = {"seed": seed, "theme": theme}
        if cfg.get("keep_all_cells") is False:
            fill["keep"] = []
        # live-drawing cell (video) / highlighted cell (photo)
        cell = spec.get("cell") or dcell
        if not cell:
            drawn = list(regions.plan_fill(scr, fill))
            cell = drawn[int(rng.integers(len(drawn)))] if drawn else sorted(regions.regions()[scr])[0]
        self.cell = cell
        live = (cell,) if self.kind == "video" else ()
        img = regions.prepare(scr, fill, clear_ids=live)
        self.src = ScreenSource(crop=crop, image=img)
        self.phone = Phone()
        self.dur = float(spec.get("duration", 8)) if self.kind == "video" else 0
        # camera: full screen -> zoom towards the cell
        o = self.src
        c0 = tuple(cfg.get("center") or (o.ox + SCREEN_W / o.scale / 2, o.oy + SCREEN_H / o.scale / 2))
        self.c0 = c0
        cx, cy = regions.center(scr, cell)
        self.zoom = float(cfg.get("zoom", 1.55))
        ring = bool(cfg.get("ring"))
        if self.zoom < 1.3:   # large region (a canvas/card): move halfway towards it
            self.c1 = (lerp(c0[0], cx, .5), lerp(c0[1], cy, .5))
        elif ring:            # small cell: center on it, keep inside the screen
            self.c1 = (min(max(cx, 250), 695), cy - 90)
        else:
            self.c1 = (c0[0], cy)
        # live drawing
        self.live = Doodle()
        if self.kind == "video":
            motif = spec.get("motif", "auto")
            if motif == "auto":
                motif = doodlelib.choose(1, theme, seed=seed)[0]
            self.motif = motif
            box = regions.cell(scr, cell)["draw"]
            bw = min(box[2] - box[0], box[3] - box[1]) * o.scale
            doodlelib.draw_motif(self.live, motif, box, 1.3, min(2.4, self.dur * 0.3), seed=seed,
                                 width=max(5.0, bw * 0.045), map_pt=lambda x, y: o.src(x, y))
            if ring:  # small cell: circle it after drawing
                hx, hy = o.src(cx, cy)
                r = max(box[2] - box[0], box[3] - box[1]) * o.scale * 0.72
                self.live.circle(hx, hy, r, r, 1.3 + min(2.4, self.dur * 0.3) + 0.1, 0.5, width=7, color=ACCENTS["yellow"])
        # frame sparkles (frame coordinates)
        self.deco = Doodle()
        t0 = 0.5 if self.kind == "video" else 0
        dd = 0.45 if self.kind == "video" else 0
        cols = list(ACCENTS.values())
        for k, (x, y, r) in enumerate([(150, 620, 38), (935, 760, 30), (120, 1380, 26), (960, 1300, 40)]):
            self.deco.sparkle(x, y, r, t0 + k * 0.25 * (dd > 0), dd, width=8, color=cols[k % len(cols)])
        self.n = int(round(self.dur * FPS))

    # ---------- frame ----------
    def _screen(self, t, final=False):
        o = self.src
        if self.kind == "video":
            e = ease_in_out(clamp01((t - 0.6) / 0.7))
        else:
            e = 0.0  # photo: full screen
        z = lerp(1.0, self.zoom, e)
        x = lerp(self.c0[0], self.c1[0], e)
        y = lerp(self.c0[1], self.c1[1], e)
        cx, cy = o.src(x, y)
        v = o.view(z, cx, cy)
        self.live.render(v, t if not final else 1e9, offset=(SCREEN_W / 2 - cx * z, SCREEN_H / 2 - cy * z), scale=z)
        return v

    def _texts(self, f, t, video):
        s = self.spec
        head = caption_image(s["headline"], s.get("highlight", ""), size=76, max_w=900)
        if video:
            a = clamp01((t - 0.3) / 0.2)
            sc = 0.9 + 0.1 * ease_back(clamp01((t - 0.3) / 0.3))
        else:
            a, sc = 1, 1
        paste_center(f, head, W / 2, HEAD_Y, sc, a)
        if s.get("sub"):
            sub = caption_image(s["sub"], s.get("sub_highlight", ""), size=50, max_w=880, plate=False, color=(70, 90, 120))
            paste_center(f, sub, W / 2, SUB_Y, 1, clamp01((t - 3.6) / 0.3) if video else 1)

    def _logo_row(self, f, a=1.0):
        ic = app_icon(120)
        ti = title_image(size=60)
        tw = ic.shape[1] - 40 + 20 + ti.shape[1]
        x0 = W / 2 - tw / 2
        paste_center(f, ic, x0 + (ic.shape[1] - 80) / 2 + 20, LOGO_Y, 1, a)
        paste_center(f, ti, x0 + ic.shape[1] - 40 + 20 + ti.shape[1] / 2, LOGO_Y + 4, 1, a)

    def photo(self):
        f = bg_frame()
        self.deco.render(f, 1e9)
        self.phone.draw(f, self._screen(0, final=True), W / 2, PH_Y, PH_S)
        self._texts(f, 1e9, False)
        self._logo_row(f)
        return f

    def frame(self, i):
        t = i / FPS
        f = bg_frame()
        end_t = self.dur - END_LEN
        if t < end_t + 0.35:
            # intro: the phone slides in from below
            e = ease_out(clamp01(t / 0.6))
            y = lerp(H + 700, PH_Y, e)
            out = clamp01((t - end_t) / 0.35)
            lay = f.copy()
            self.deco.render(lay, t)
            self.phone.draw(lay, self._screen(t), W / 2, y + 120 * ease_in_out(out), PH_S * (1 - 0.08 * out))
            self._texts(lay, t, True)
            f = (lay.astype(np.float32) * (1 - out) + f.astype(np.float32) * out).astype(np.uint8)
        if t >= end_t:
            ec = BRAND["end_card"]
            draw_end_card(f, t, end_t, ec.get("subtitle", ""), ec.get("highlight", ""))
        return f


def _music(name, seed=""):
    return resolve_music(name, seed=seed)


def render(spec, dst, on_progress=None):
    """spec -> dst (.jpg or .mp4). Returns the dst path."""
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    st = Story(spec)
    if st.kind == "photo":
        Image.fromarray(st.photo()).save(dst.with_suffix(".jpg"), quality=93)
        return dst.with_suffix(".jpg")
    from .audio import mix
    ff = find_bin("ffmpeg")
    tmpv = dst.with_name(dst.stem + "_v.mp4")
    cmd = [ff, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
           "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", str(tmpv)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(st.n):
        p.stdin.write(st.frame(i).tobytes())
        if on_progress and i % 15 == 0:
            on_progress(90 * i / st.n)
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("ffmpeg video error")
    music = _music(spec.get("music", "auto"), seed=spec.get("headline", ""))
    wav = dst.with_name(dst.stem + "_a.wav")
    mix(st.dur, [], [("pop", 0.35, 1.0), ("sparkle", st.dur - END_LEN + 0.3, 1.0)], wav, music=music, music_level_db=-6.0)
    out = dst.with_suffix(".mp4")
    r = subprocess.run([ff, "-v", "error", "-y", "-i", str(tmpv), "-i", str(wav), "-map", "0:v", "-map", "1:a",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                        "-ar", "48000", "-shortest", "-movflags", "+faststart", str(out)])
    if r.returncode != 0:
        raise RuntimeError("ffmpeg audio mux error")
    tmpv.unlink(missing_ok=True)
    wav.unlink(missing_ok=True)
    spec["_music_used"] = music
    if on_progress:
        on_progress(100)
    return out


def preview(spec, dst, times=(0.2, 1.0, 2.5, 4.5, 7.0)):
    """Save a few frames of the video side by side as thumbnails (for checking)."""
    st = Story(spec)
    if st.kind == "photo":
        Image.fromarray(st.photo()).resize((540, 960)).save(dst)
        return dst
    ims = [Image.fromarray(st.frame(min(st.n - 1, int(t * FPS)))).resize((270, 480)) for t in times]
    sheet = Image.new("RGB", (270 * len(ims), 480), (255, 255, 255))
    for k, im in enumerate(ims):
        sheet.paste(im, (270 * k, 0))
    sheet.save(dst)
    return dst


if __name__ == "__main__":
    import sys
    spec = json.loads(sys.argv[1])
    print(render(spec, sys.argv[2]))
