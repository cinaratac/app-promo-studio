"""script.json + voice/timing.json -> scene timeline.

Rule: speech onset = scene_start + 0.25
      scene duration = max(speech + 0.35, min_animation_duration)
If caption_parts are given, the caption is split at the longest pauses inside the clip.
"""
import json
import math
from dataclasses import dataclass, field
from pathlib import Path

PRE, POST = 0.25, 0.35


@dataclass
class Caption:
    text: str
    highlight: str
    start: float
    end: float


@dataclass
class Scene:
    id: str
    start: float
    dur: float
    voice_at: float | None        # where the clip starts on the timeline
    onset: float | None           # moment speech starts
    speech_end: float | None
    captions: list = field(default_factory=list)
    stretched: bool = False       # stretched because the animation is longer than the speech

    @property
    def end(self):
        return self.start + self.dur

    def local(self, t):
        return t - self.start


FPS_Q = 30


def _q(d):
    """Round scene duration up to a whole frame so scene boundaries land on frames and scenes can be cached separately."""
    return math.ceil(d * FPS_Q - 1e-6) / FPS_Q


def load_script(vdir):
    return json.loads((Path(vdir) / "script.json").read_text(encoding="utf-8"))


def build(vdir):
    vdir = Path(vdir)
    script = load_script(vdir)
    timing = json.loads((vdir / "voice" / "timing.json").read_text(encoding="utf-8"))
    scenes, t = [], 0.0
    for ln in script["lines"]:
        sid = ln["id"]
        min_dur = ln.get("min_dur", 0.0)
        if sid in timing:
            tm = timing[sid]
            speech = tm["end"] - tm["lead"]
            dur = _q(max(PRE + speech + POST, min_dur))
            onset = t + PRE
            voice_at = onset - tm["lead"]
            sp_end = onset + speech
            parts = ln.get("caption_parts") or [ln.get("caption", ln["text"])]
            hls = ln.get("highlight_parts") or [ln.get("highlight", "")] * len(parts)
            # split at the len(parts)-1 longest gaps
            gaps = sorted(tm["gaps"], key=lambda g: g[1] - g[0], reverse=True)[: len(parts) - 1]
            cuts = sorted(voice_at + (g[0] + g[1]) / 2 for g in gaps)
            if len(cuts) < len(parts) - 1:   # not enough gaps: split evenly
                cuts = [onset + speech * (i + 1) / len(parts) for i in range(len(parts) - 1)]
            bounds = [t + 0.12] + cuts + [t + dur]
            caps = [Caption(p, h, bounds[i], bounds[i + 1]) for i, (p, h) in enumerate(zip(parts, hls))]
            sc = Scene(sid, t, dur, voice_at, onset, sp_end, caps, stretched=min_dur > PRE + speech + POST)
        else:
            dur = _q(min_dur or 1.5)
            sc = Scene(sid, t, dur, None, None, None, [])
        scenes.append(sc)
        t += dur
    return script, scenes, t


def report(scenes, total):
    lines = []
    for s in scenes:
        flag = "  (stretched for animation)" if s.stretched else ""
        lines.append(f"{s.id:>8}: {s.start:6.2f} -> {s.end:6.2f}  ({s.dur:.2f} s){flag}")
    lines.append(f"  TOTAL: {total:.2f} s")
    return "\n".join(lines)
