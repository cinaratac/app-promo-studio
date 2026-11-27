"""Automatic video from a shot list (script.json "shots"): rendered without any AI in the loop.

Each sentence (lines[i]) has exactly one shot. Coordinates are pixels of the ORIGINAL screenshot.

shot = {
  "screen": "month.png",               # file in assets/screenshots; if omitted the previous screen continues
  "crop": [x0, y0, x1, y1],            # optional: keep only the app area of the image
  "cam": [[0, 1.0, 472, 1180], [0.6, 2.0, 290, 1200]],   # [time 0..1, zoom, center_x, center_y]
  "fill": {"seed": 7, "theme": "winter"},  # optional: NEW doodles inside cells (see promovideo/regions.py)
                                        # theme: daily | winter | summer | autumn | emotions | mixed
                                        # keep: ["d13"] keep the real drawing in these cells; only: [...] fill only these
  "marks": [                            # time 'at' 0..1 (fraction of the shot duration)
     {"type": "circle", "x": 205, "y": 1170, "r": 70, "at": 0.5, "color": "yellow"},
     {"type": "underline", "x0": 100, "x1": 400, "y": 860, "at": 0.4},
     {"type": "arrow", "from": [100, 900], "to": [200, 1000], "at": 0.5},
     {"type": "scribble", "x0": 0, "y0": 0, "x1": 100, "y1": 40, "at": 0.5, "color": "blue"},
     {"type": "sparkle", "x": 800, "y": 300, "r": 40, "at": 0.3},
     {"type": "tap", "x": 205, "y": 1170, "at": 0.3},
     {"type": "drawing", "cell": "paper", "motif": "cat", "at": 0.2, "dur": 1.8}
                                        # live drawing: the region (regions.py) is cleared, the motif is drawn stroke by stroke
                                        # motif: one of doodlelib.MOTIFS or "auto"
  ],
  "end": true                           # end card (logo) - last sentence
}
Marks stay pinned to the right place on screen while the camera moves.
"""
import hashlib
import zlib
import json
from pathlib import Path

import numpy as np

from .core import ASSETS, FPS, ACCENTS, INK, SCREEN_W, SCREEN_H, ease_in_out, ease_back, lerp, clamp01
from .doodle import Doodle
from .gfx import Phone, ScreenSource, bg_frame, draw_caption, draw_tap, draw_end_card
from . import doodlelib, regions
from .timeline import build

SHOTS = ASSETS / "screenshots"
PH_X, PH_Y, PH_S = 540, 860, 0.78
COLORS = {**ACCENTS, "ink": INK, "black": INK}
MARK_DUR = {"circle": 0.5, "underline": 0.4, "arrow": 0.5, "scribble": 0.45, "sparkle": 0.45}
XFADE = 0.35


class AutoVideo:
    def __init__(self, vdir):
        self.vdir = Path(vdir)
        self.script, self.scenes, self.total = build(self.vdir)
        self.n = int(round(self.total * FPS))
        shots = self.script.get("shots") or []
        if len(shots) != len(self.scenes):
            raise ValueError(f"number of shots ({len(shots)}) must equal number of lines ({len(self.scenes)})")
        self.phone = Phone()
        self._src_cache = {}
        self.items = []
        prev = None
        for sc, sh in zip(self.scenes, shots):
            it = {"scene": sc, "shot": sh, "end": bool(sh.get("end"))}
            if sh.get("screen"):
                live = tuple(sorted(m["cell"] for m in sh.get("marks", []) if m.get("type") == "drawing"))
                it["src"] = self._src(sh["screen"], sh.get("crop"), sh.get("fill"), live)
                it["screen_name"] = sh["screen"]
            elif prev is not None and any(m.get("type") == "drawing" for m in sh.get("marks", [])):
                live = tuple(sorted(m["cell"] for m in sh.get("marks", []) if m.get("type") == "drawing"))
                pshot = prev["shot_screen"]
                it["src"] = self._src(pshot.get("screen"), pshot.get("crop"), pshot.get("fill"),
                                      tuple(sorted(set(prev["live"]) | set(live))))
                it["screen_name"] = pshot.get("screen")
            else:
                it["src"] = prev["src"] if prev else None
                it["screen_name"] = prev.get("screen_name") if prev else None
            it["shot_screen"] = sh if sh.get("screen") else (prev["shot_screen"] if prev else {})
            it["live"] = tuple(sorted(m["cell"] for m in sh.get("marks", []) if m.get("type") == "drawing")) \
                if sh.get("screen") else tuple(sorted(set(prev["live"] if prev else ()) |
                                                      {m["cell"] for m in sh.get("marks", []) if m.get("type") == "drawing"}))
            if it["src"] is None and not it["end"]:
                raise ValueError(f"{sc.id}: the first shot needs a 'screen'")
            cam = sh.get("cam") or ([[0, *prev["cam"][-1][1:]]] if prev and not sh.get("screen") else None)
            if not cam and it["src"] is not None:
                o = it["src"]
                cam = [[0, 1.0, o.ox + SCREEN_W / o.scale / 2, o.oy + min(o.h, SCREEN_H) / o.scale / 2]]
            it["cam"] = sorted(cam or [[0, 1, 0, 0]], key=lambda k: k[0])
            it["changed"] = prev is not None and bool(sh.get("screen")) and it["src"] is not prev["src"]
            it["doodle"], it["taps"], it["frame_doodle"] = self._marks(it)
            it["inherit_live"] = (prev.get("inherit_live", []) + [prev]) if (prev and not sh.get("screen")) else []
            self.items.append(it)
            if not it["end"]:
                prev = it
        self.end_t = next((it["scene"].start for it in self.items if it["end"]), None)

    # ---------- setup ----------
    def _src(self, name, crop, fill=None, live=()):
        key = (name, tuple(crop) if crop else None, json.dumps(fill, sort_keys=True) if fill else None, tuple(live))
        if key not in self._src_cache:
            path = SHOTS / name
            if not path.exists():
                raise FileNotFoundError(f"screenshot not found: {name} (put it in assets/screenshots)")
            if fill or live:
                img = regions.prepare(name, fill, clear_ids=live)
                self._src_cache[key] = ScreenSource(crop=crop, image=img)
            else:
                self._src_cache[key] = ScreenSource(path, crop=crop)
        return self._src_cache[key]

    def _abs(self, it, frac):
        sc = it["scene"]
        return sc.start + clamp01(frac) * sc.dur

    def _marks(self, it):
        d, fd, taps = Doodle(), Doodle(), []
        live = Doodle()
        it["live_doodle"] = live
        src = it["src"]
        for m in it["shot"].get("marks", []):
            t0 = self._abs(it, m.get("at", 0.4))
            typ = m["type"]
            col = COLORS.get(m.get("color", "ink"), INK)
            frame_space = m.get("space") == "frame"
            tgt = fd if frame_space or src is None else d
            P = (lambda x, y: (x, y)) if tgt is fd else src.src
            sc = 1.0 if tgt is fd else src.scale
            w = m.get("width", 10)
            dur = MARK_DUR.get(typ, 0.5)
            if typ == "circle":
                x, y = P(m["x"], m["y"])
                rx = m.get("rx", m.get("r", 60)) * sc
                ry = m.get("ry", m.get("r", 60)) * sc
                tgt.circle(x, y, rx, ry, t0, dur, width=w, color=col)
            elif typ == "underline":
                a, b = P(m["x0"], m["y"]), P(m["x1"], m["y"])
                tgt.underline(a[0], b[0], a[1], t0, dur, width=w, color=col)
            elif typ == "arrow":
                a, b = P(*m["from"]), P(*m["to"])
                tgt.arrow(a[0], a[1], b[0], b[1], t0, dur, width=w, color=col)
            elif typ == "scribble":
                a, b = P(m["x0"], m["y0"]), P(m["x1"], m["y1"])
                tgt.scribble(a[0], a[1], b[0], b[1], t0, dur, width=m.get("width", 6), color=col)
            elif typ == "sparkle":
                x, y = P(m["x"], m["y"])
                tgt.sparkle(x, y, m.get("r", 34) * sc, t0, dur, width=m.get("width", 8),
                            color=COLORS.get(m.get("color", "yellow")))
            elif typ == "tap":
                taps.append((m["x"], m["y"], t0))
            elif typ == "drawing":
                box = regions.cell(it["screen_name"], m["cell"])["draw"]
                motif = m.get("motif", "auto")
                if motif == "auto":
                    motif = doodlelib.choose(1, m.get("theme", "mixed"), seed=zlib.crc32(m["cell"].encode()) % 9973 + int(t0 * 10))[0]
                bw = min(box[2] - box[0], box[3] - box[1]) * src.scale
                doodlelib.draw_motif(live, motif, box, t0, m.get("dur", 1.6), seed=m.get("seed", 1),
                                     width=max(5.0, bw * 0.045), map_pt=lambda x, y: src.src(x, y))
            else:
                raise ValueError(f"unknown mark type: {typ}")
        return d, taps, fd

    # ---------- camera ----------
    def cam_at(self, it, t):
        keys = it["cam"]
        sc = it["scene"]
        f = (t - sc.start) / max(1e-6, sc.dur)
        if f <= keys[0][0]:
            return keys[0][1:]
        for a, b in zip(keys, keys[1:]):
            if a[0] <= f <= b[0]:
                e = ease_in_out((f - a[0]) / max(1e-6, b[0] - a[0]))
                return [lerp(a[i], b[i], e) for i in (1, 2, 3)]
        return keys[-1][1:]

    def view(self, it, t, with_marks=True):
        src = it["src"]
        z, x, y = self.cam_at(it, t)
        cx, cy = src.src(x, y)
        v = src.view(z, cx, cy)
        off = (SCREEN_W / 2 - cx * z, SCREEN_H / 2 - cy * z)
        # a live drawing behaves like the user's own drawing: it stays visible after its scene and across transitions
        it["live_doodle"].render(v, t, offset=off, scale=z)
        for p in it.get("inherit_live", []):
            p["live_doodle"].render(v, t, offset=off, scale=z)
        if with_marks:
            sc = it["scene"]
            fade = min(1.0, (sc.end - t) / 0.2) if not it["end"] else 1.0
            it["doodle"].render(v, t, offset=(SCREEN_W / 2 - cx * z, SCREEN_H / 2 - cy * z),
                                opacity=max(0.0, fade), scale=z)
            for (mx, my, mt) in it["taps"]:
                sx, sy = src.src(mx, my)
                draw_tap(v, SCREEN_W / 2 + (sx - cx) * z, SCREEN_H / 2 + (sy - cy) * z, t, mt)
        return v

    def item_at(self, t):
        for it in self.items:
            if it["scene"].start <= t < it["scene"].end:
                return it
        return self.items[-1]

    # ---------- frame ----------
    def frame(self, i):
        t = i / FPS
        it = self.item_at(t)
        return self._overlay(self._phone_frame(it, t), t)

    def _phone_frame(self, it, t):
        f = bg_frame()
        cur = it if not it["end"] else self._last_screen_item()
        y, op = PH_Y, 1.0
        if t < 0.75:
            y = lerp(2500, PH_Y, ease_back(t / 0.75, 1.1))
        if self.end_t is not None and t > self.end_t - 0.05:
            e = ease_in_out((t - (self.end_t - 0.05)) / 0.45)
            y, op = lerp(PH_Y, PH_Y + 260, e), 1 - e
        if op > 0.01 and cur is not None:
            v = self.view(cur, t if not it["end"] else cur["scene"].end - 1e-3, with_marks=not it["end"])
            if cur["changed"] and t - cur["scene"].start < XFADE and not it["end"]:
                prev = self.items[self.items.index(cur) - 1]
                pv = self.view(prev, prev["scene"].end - 1e-3, with_marks=False)
                a = clamp01((t - cur["scene"].start) / XFADE)
                v = (pv.astype(np.float32) * (1 - a) + v.astype(np.float32) * a).astype(np.uint8)
            self.phone.draw(f, v, PH_X, y, PH_S, opacity=op)
        return f

    def _overlay(self, f, t):
        for item in self.items:
            if item["scene"].start - 0.5 <= t < item["scene"].end:
                sc = item["scene"]
                fade = min(1.0, (sc.end - t) / 0.2)
                item["frame_doodle"].render(f, t, opacity=max(0.0, fade))
        for item in self.items:
            if item["end"]:
                continue
            s = item["scene"]
            for c in s.captions:
                draw_caption(f, c.text, t, c.start, min(c.end, s.end) - 0.02, c.highlight)
        if self.end_t is not None:
            ec = self.script.get("end_card", {})
            draw_end_card(f, t, self.end_t + 0.15, ec.get("subtitle", ""), ec.get("subtitle_highlight", ""))
        return f

    def _last_screen_item(self):
        for it in reversed(self.items):
            if not it["end"]:
                return it
        return None

    # ---------- scene cache ----------
    def segments(self):
        """Frame range + content hash per scene. A scene with an unchanged hash is not re-rendered."""
        code = hashlib.sha1()
        for f in ("auto.py", "gfx.py", "doodle.py", "core.py", "doodlelib.py", "regions.py", "brand.py"):
            p = Path(__file__).with_name(f)
            if p.exists():
                code.update(p.read_bytes())
        out = []
        last = self._last_screen_item()
        for k, it in enumerate(self.items):
            sc = it["scene"]
            f0, f1 = int(round(sc.start * FPS)), int(round(sc.end * FPS))
            nxt = self.items[k + 1] if k + 1 < len(self.items) else None
            key = {
                "code": code.hexdigest(), "first": k == 0, "shot": it["shot"],
                # the crossfade only needs the previous scene's screen + camera
                "prev": _no_marks(self.items[k - 1]) if k and it["changed"] else None,
                "last_screen": _no_marks(last) if it["end"] and last else None,
                "next_end": bool(nxt and nxt["end"]), "frames": f1 - f0,
                "caps": [(c.text, c.highlight, round(c.start - sc.start, 3), round(c.end - sc.start, 3))
                         for c in sc.captions],
                "end_card": self.script.get("end_card") if it["end"] else None,
            }
            h = hashlib.sha1(json.dumps(key, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
            out.append({"k": k, "id": sc.id, "f0": f0, "f1": f1, "hash": h})
        return out

    # ---------- test frames and audio ----------
    def test_times(self):
        ts = [0.5]
        for it in self.items:
            sc = it["scene"]
            ts.append(sc.start + sc.dur * 0.5)
            for m in it["shot"].get("marks", []):
                ts.append(self._abs(it, m.get("at", 0.4)) + 0.45)
        if self.end_t is not None:
            ts += [self.end_t + 0.4, self.end_t + 1.3]
        return sorted({round(min(t, self.total - 0.05), 2) for t in ts})

    def sfx_cues(self):
        cues = [("whoosh", 0.05, 0.8)]
        for it in self.items:
            if it["end"]:
                cues += [("whoosh", it["scene"].start - 0.05, 0.6), ("pop", it["scene"].start + 0.2, 0.9)]
                continue
            if it["changed"]:
                cues.append(("whoosh", it["scene"].start, 0.4))
            spark = False
            for m in it["shot"].get("marks", []):
                t0 = self._abs(it, m.get("at", 0.4))
                if m["type"] == "tap":
                    cues.append(("click", t0, 0.9))
                elif m["type"] == "drawing":
                    continue
                elif m["type"] == "sparkle":
                    if not spark:
                        cues.append(("sparkle", t0, 0.6))
                        spark = True
                else:
                    cues.append(("pop", t0, 0.6))
        return cues


def _no_marks(it):
    sh = it["shot_screen"] if it.get("shot_screen") else {}
    cur = it["shot"]
    return {"screen": sh.get("screen"), "crop": sh.get("crop"), "fill": sh.get("fill"),
            "live": list(it.get("live", ())), "cam": cur.get("cam") or it.get("cam"),
            "marks": [m for m in cur.get("marks", []) if m.get("type") == "drawing"]}


def load(vdir):
    return AutoVideo(vdir)


def build_audio(vdir):
    from .audio import mix
    from .music import resolve
    v = AutoVideo(vdir)
    voice = [(v.vdir / "voice" / f"{s.id}.wav", s.voice_at) for s in v.scenes if s.voice_at is not None]
    music = resolve(v.script.get("music"), seed=v.script.get("scenario", v.vdir.name))
    return mix(v.total, voice, v.sfx_cues(), v.vdir / "out" / "mix.wav", music=music)


SCENES_SHIM = '''"""Auto-generated: scenes come from the script.json "shots" field (promovideo/auto.py)."""
from pathlib import Path
from promovideo.auto import load
_V = load(Path(__file__).resolve().parent)
N_FRAMES = _V.n
TEST_TIMES = _V.test_times()
SEGMENTS = _V.segments()
frame = _V.frame
'''

AUDIO_SHIM = '''"""Auto-generated: voice-over + automatic SFX + background music (promovideo/auto.py)."""
from pathlib import Path
from promovideo.auto import build_audio


def build():
    return build_audio(Path(__file__).resolve().parent)
'''
