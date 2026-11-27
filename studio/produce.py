"""Produces the video from an approved scenario (no Claude needed): voice-over -> timing -> mix -> render -> check.
Progress is written to scenarios/progress/<sid>.json (the panel's progress bar reads it).

  python -m studio.produce <sid>
"""
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

from . import store
from .tts import TTS, LANG, synthesize, check
from promovideo.brand import BRAND

ROOT = store.ROOT
PROG = store.SCEN / "progress"


class NeedsShots(Exception):
    pass


def progress(sid, state, pct, msg="", **extra):
    PROG.mkdir(parents=True, exist_ok=True)
    d = {"state": state, "pct": round(max(0, min(100, pct)), 1), "msg": msg, "at": store.now(), **extra}
    try:
        store._write(PROG / f"{sid}.json", d)
    except PermissionError:
        if state in ("done", "error"):   # the final state must be written
            time.sleep(1)
            store._write(PROG / f"{sid}.json", d)


def read_progress(sid):
    p = PROG / f"{sid}.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    except (OSError, ValueError):
        return None


def _slug(text):
    s = unicodedata.normalize("NFKD", text.lower().replace("ı", "i"))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")[:28] or "video"


def _new_folder(s):
    nums = [int(m.group(1)) for p in (ROOT / "videos").glob("*") if (m := re.match(r"(\d{3})_", p.name))]
    return f"{(max(nums) + 1) if nums else 1:03d}_{_slug(s['title'])}"


def _pick_music(s):
    """Explicit track -> that track; 'auto' -> a track different from the last video's (if you have several)."""
    from promovideo.music import tracks, resolve
    m = s.get("music") or "auto"
    if m != "auto":
        return resolve(m)
    names = list(tracks())
    if not names:
        return None
    last = None
    for x in sorted(store.all_scenarios(), key=lambda x: (x.get("video") or {}).get("made_at", "")):
        if (x.get("video") or {}).get("music"):
            last = x["video"]["music"]
    pool = [n for n in names if n != last] or names
    return resolve("auto", seed=s["id"]) if resolve("auto", seed=s["id"]) in pool else pool[0]


def produce(sid, jobs=4):
    s = store.get(sid)
    if not s.get("shots") or len(s["shots"]) != len(s["lines"]):
        # no plan from Claude (or the line count changed): build an automatic shot plan instead of waiting
        from .autoshots import plan
        why = "was missing" if not s.get("shots") else "did not match the number of lines"
        s["shots"] = plan(s)
        store.add_history(s, "claude", "status", f"shot plan created automatically (plan {why})")
        store.save(s)
        progress(sid, "running", 2, "shot plan created")
    v = s.get("video") or {}
    folder = v.get("folder") or _new_folder(s)
    vdir = ROOT / "videos" / folder
    (vdir / "voice").mkdir(parents=True, exist_ok=True)
    (vdir / "out").mkdir(exist_ok=True)
    music = _pick_music(s)
    ec = BRAND["end_card"]
    script = {"title": s["title"], "language": LANG, "tts": TTS, "lines": s["lines"], "shots": s["shots"],
              "end_card": s.get("end_card") or {"subtitle": ec.get("subtitle", ""), "subtitle_highlight": ec.get("highlight", "")},
              "post": s.get("post", {}), "music": music or "none", "scenario": sid}
    (vdir / "script.json").write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")

    # 1) voice-over (lines whose text did not change are not re-synthesized)
    texts_p = vdir / "voice" / "texts.json"
    texts = json.loads(texts_p.read_text(encoding="utf-8")) if texts_p.exists() else {}
    warnings = []
    lines = s["lines"]
    for k, ln in enumerate(lines):
        wav = vdir / "voice" / f"{ln['id']}.wav"
        progress(sid, "running", 2 + 33 * k / len(lines), f"voice-over {k + 1}/{len(lines)}")
        spoken = ln.get("tts_text") or ln["text"]   # spelling sent to TTS (the caption stays 'text')
        if wav.exists() and texts.get(ln["id"]) == spoken:
            continue
        best = None
        for attempt in range(2):
            synthesize(spoken, wav)
            sim, heard = check(ln["text"], wav)
            if sim is None:            # STT unavailable: skip the check
                break
            if best is None or sim > best[0]:
                best = (sim, heard, wav.read_bytes())
            if sim >= 0.75:
                break
        if best is not None:
            wav.write_bytes(best[2])
            if best[0] < 0.75:
                warnings.append(f"{ln['id']} pronunciation doubtful: heard '{best[1]}'")
        texts[ln["id"]] = spoken
        texts_p.write_text(json.dumps(texts, ensure_ascii=False, indent=2), encoding="utf-8")

    # 2) timing + scene/audio files
    from promovideo import audio as au
    from promovideo.auto import SCENES_SHIM, AUDIO_SHIM, AutoVideo
    progress(sid, "running", 37, "measuring timing")
    for old in (vdir / "voice").glob("*.wav"):
        if old.stem not in {ln["id"] for ln in lines}:
            old.unlink()
    au.analyze_dir(vdir / "voice", vdir / "voice" / "timing.json")
    (vdir / "scenes.py").write_text(SCENES_SHIM, encoding="utf-8")
    (vdir / "audio.py").write_text(AUDIO_SHIM, encoding="utf-8")
    av = AutoVideo(vdir)

    # 3) contact sheet (for review) + render
    from promovideo.render import build_cached, test_frames
    progress(sid, "running", 40, "test frames")
    test_frames(vdir)
    progress(sid, "running", 42, "rendering frames")
    final, ok, redrawn, nseg = build_cached(vdir, jobs, on_progress=lambda r, m: progress(sid, "running", 42 + 55 * r, m))
    if not ok:
        raise RuntimeError("ffprobe check failed")
    progress(sid, "running", 99, "saving")
    s = store.get(sid)
    s["video"] = {"folder": folder, "file": final.name, "seconds": round(av.total, 1), "music": music,
                  "warnings": warnings, "made_at": store.now(), "contact": f"{folder}/out/contact.jpg"}
    s["status"] = "review"
    s.pop("priority", None)
    store.add_history(s, "claude", "produced", f"{final.name} ({av.total:.1f} s)" + (f" · warning: {'; '.join(warnings)}" if warnings else ""))
    store.save(s)
    progress(sid, "done", 100, "video ready, waiting for your approval")
    return final


def run(sid):
    t0 = time.time()
    try:
        progress(sid, "running", 1, "starting")
        f = produce(sid)
        print(f"OK {sid}: {f} ({time.time() - t0:.0f} s)")
        return True
    except NeedsShots as e:
        progress(sid, "waiting", 0, f"Waiting for a shot plan: {e}")
        print(f"WAITING {sid}: {e}")
    except Exception as e:
        progress(sid, "error", 0, str(e)[:300])
        s = store.get(sid)
        store.add_history(s, "claude", "status", f"production error: {str(e)[:200]}")
        store.save(s)
        print(f"ERROR {sid}: {e}")
    return False


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(0 if run(sys.argv[1]) else 1)
