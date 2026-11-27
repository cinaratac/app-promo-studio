"""Instagram story store and production: stories/<id>.json, output stories/out/<id>.jpg|mp4

Statuses:
  plan       request saved; the story text waits for Claude's hourly run (if the headline was left empty)
  revise     you asked for changes; Claude fixes the text/settings -> queued
  queued     in the production queue (the panel worker produces it without Claude)
  producing  being produced
  review     ready, waiting for your approval (approve = send to Instagram)
  sent       sent to Buffer (right away or into the queue)
  rejected   dropped
  error      production/sending error (regenerate to retry)

  python -m studio.stories list
  python -m studio.stories show st003
  python -m studio.stories set st003 '{"headline": "...", "highlight": "...", "sub": "..."}'   # -> queued
  python -m studio.stories produce st003
"""
import hashlib
import json
import re
import sys
import zlib

from . import store

DIR = store.ROOT / "stories"
OUT = DIR / "out"
THEMES = ["daily", "winter", "summer", "autumn", "emotions", "mixed"]


def screens_list():
    """Story screens configured in brand.json ("story_screens")."""
    from promovideo.story import screens
    return list(screens())
EDITABLE = ["kind", "headline", "highlight", "sub", "screen", "theme", "motif", "duration", "music", "seed"]


def all_stories():
    DIR.mkdir(exist_ok=True)
    out = []
    for p in sorted(DIR.glob("st*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return out


def get(sid):
    return json.loads((DIR / f"{sid}.json").read_text(encoding="utf-8"))


def save(s):
    s["updated"] = store.now()
    store._write(DIR / f"{s['id']}.json", s)
    return s


def _next_id():
    nums = [int(m.group(1)) for p in DIR.glob("st*.json") if (m := re.match(r"st(\d+)", p.stem))]
    return f"st{(max(nums) + 1) if nums else 1:03d}"


def _hist(s, by, kind, text=""):
    s.setdefault("history", []).append({"at": store.now(), "by": by, "type": kind, "text": text})


def _clean(d):
    out = {}
    for k in EDITABLE:
        if k not in d or d[k] in (None, ""):
            continue
        v = d[k]
        if k == "kind" and v not in ("photo", "video"):
            raise ValueError("kind must be photo or video")
        if k == "screen" and v not in screens_list() + ["auto"]:
            raise ValueError(f"screen options: {screens_list()}")
        if k == "theme" and v not in THEMES:
            raise ValueError(f"theme options: {THEMES}")
        if k == "duration":
            v = max(5, min(15, int(v)))
        if k == "seed":
            v = int(v)
        out[k] = v.strip() if isinstance(v, str) else v
    return out


def create(data):
    """New request from the panel. count stories; with a headline they go straight to production, otherwise to Claude."""
    DIR.mkdir(exist_ok=True)
    count = max(1, min(10, int(data.get("count") or 1)))
    base = _clean(data)
    base.setdefault("kind", "photo")
    req = (data.get("request") or "").strip()
    if not base.get("headline") and not req:
        raise ValueError("describe what you want or fill in the story text")
    made = []
    for k in range(count):
        sid = _next_id()
        s = {"id": sid, "created": store.now(), "request": req, **base}
        s.setdefault("seed", zlib.crc32(f"{sid}{req}".encode()) % 99991)
        if not s.get("screen") or s["screen"] == "auto":
            scr = screens_list()
            if not scr:
                raise ValueError('no story screens configured: add "story_screens" to brand.json')
            s["screen"] = scr[(zlib.crc32(sid.encode()) + k) % len(scr)]
        s.setdefault("theme", "daily")
        s.setdefault("music", "auto")
        if s["kind"] == "video":
            s.setdefault("duration", 8)
        s["status"] = "queued" if s.get("headline") else "plan"
        _hist(s, "user", "request", req or s.get("headline", ""))
        save(s)
        made.append(s)
    return made


def edit(sid, data):
    """The user changes fields -> re-production."""
    s = get(sid)
    if s["status"] in ("producing", "sent"):
        raise ValueError("cannot be changed at this stage")
    ch = _clean(data)
    s.update(ch)
    if not s.get("headline"):
        raise ValueError("story text cannot be empty")
    s["status"] = "queued"
    s.pop("error", None)
    _hist(s, "user", "edit", ", ".join(f"{k}" for k in ch))
    return save(s)


def regenerate(sid):
    """Same text, different doodles."""
    s = get(sid)
    s["seed"] = (int(s.get("seed", 0)) * 31 + 7) % 99991
    s["status"] = "queued" if s.get("headline") else "plan"
    s.pop("error", None)
    _hist(s, "user", "regenerate", "again with different doodles")
    return save(s)


def feedback(sid, text):
    s = get(sid)
    s["status"] = "revise"
    s["feedback"] = text
    _hist(s, "user", "feedback", text)
    return save(s)


def reject(sid):
    s = get(sid)
    s["status"] = "rejected"
    _hist(s, "user", "reject")
    return save(s)


def claude_set(sid, data):
    """Claude's hourly run: plan/revise -> queued."""
    s = get(sid)
    s.update(_clean(data))
    if not s.get("headline"):
        raise ValueError("headline is required")
    s["status"] = "queued"
    s.pop("feedback", None)
    _hist(s, "claude", "write", s["headline"])
    return save(s)


def queue():
    return [s for s in all_stories() if s["status"] == "queued"]


def produce(sid):
    from promovideo import story as S
    s = get(sid)
    s["status"] = "producing"
    s["progress"] = 0
    save(s)
    OUT.mkdir(parents=True, exist_ok=True)
    spec = {k: s[k] for k in EDITABLE if k in s}
    try:
        last = [0]

        def prog(p):
            if p - last[0] >= 10:
                last[0] = p
                x = get(sid)
                x["progress"] = int(p)
                save(x)
        for old in OUT.glob(f"{sid}*"):
            old.unlink()
        tag = hashlib.md5(json.dumps(spec, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:6]
        out = S.render(spec, OUT / f"{sid}_{tag}", on_progress=prog)
        s = get(sid)
        s["file"] = out.name
        s.pop("poster", None)
        if out.suffix == ".mp4":  # preview frame for the panel (the first video frame is an empty background)
            from promovideo.core import find_bin
            import subprocess
            pst = out.with_name(out.stem + "_poster.jpg")
            subprocess.run([find_bin("ffmpeg"), "-v", "error", "-y", "-ss", "3.8", "-i", str(out), "-frames:v", "1",
                            "-vf", "scale=540:-2", "-q:v", "3", str(pst)])
            if pst.exists():
                s["poster"] = pst.name
        if spec.get("_music_used"):
            s["music_used"] = spec["_music_used"]
        s["status"] = "review"
        s["progress"] = 100
        _hist(s, "claude", "produced", out.name)
    except Exception as e:
        s = get(sid)
        s["status"] = "error"
        s["error"] = f"production: {e}"
        _hist(s, "claude", "error", str(e))
    return save(s)


def send(sid, mode="addToQueue"):
    """Approval: upload to R2, share as an Instagram story via Buffer (right away or into the queue)."""
    from publisher import common, buffer, r2
    common.load_env()
    s = get(sid)
    if s["status"] != "review" or not s.get("file"):
        raise ValueError("story is not ready")
    f = OUT / s["file"]
    try:
        url = r2.upload(f, f"{common.key_prefix()}/stories/{f.name}")
        res = buffer.publish_story(url, f.suffix == ".mp4", s.get("headline", ""),
                                   "shareNow" if mode == "now" else "addToQueue")
    except Exception as e:
        s["error"] = f"sending: {e}"
        _hist(s, "claude", "error", str(e))
        save(s)
        raise
    s["status"] = "sent"
    s["buffer"] = res
    s.pop("error", None)
    _hist(s, "user", "send", "shared right away" if mode == "now" else "added to the Buffer queue")
    common.log(f"story {sid}: buffer {res['id']} {res['status']}")
    return save(s)


def pending_claude():
    return [s for s in all_stories() if s["status"] in ("plan", "revise")]


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    a = sys.argv[1:]
    cmd = a[0] if a else "list"
    if cmd == "list":
        for s in all_stories():
            print(f"{s['id']}  {s['status']:<9} {s.get('kind', ''):<5}  {s.get('headline') or '(no text)'}  "
                  f"| request: {s.get('request', '')}{'  | REVISE: ' + s['feedback'] if s.get('feedback') else ''}")
    elif cmd == "show":
        print(json.dumps(get(a[1]), ensure_ascii=False, indent=2))
    elif cmd == "set":
        print(claude_set(a[1], json.loads(a[2]))["status"])
    elif cmd == "produce":
        print(produce(a[1])["status"])
    else:
        print(__doc__)
