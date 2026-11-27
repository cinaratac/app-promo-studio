"""Scenario store: scenarios/<id>.json, scenarios/requests.json, studio/style_notes.md

Scenario statuses:
  pending      waiting for your approval
  revise       you asked for changes; Claude writes a new version on its next run -> pending
  approved     approved; waiting for video production
  review       video produced, waiting for your video approval
  video_revise you asked for video changes; Claude fixes the shot plan/text -> approved (re-produced)
  produced     you approved the video; it is in approved/ and in the Buffer queue
  published    published on all platforms
  rejected     rejected (the reason is added to the style notes)
"""
import datetime as dt
import json
import os
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCEN = ROOT / "scenarios"
REQ = SCEN / "requests.json"
NOTES = ROOT / "studio" / "style_notes.md"
STATUSES = ["pending", "revise", "approved", "review", "video_revise", "produced", "published", "rejected"]


def now():
    return dt.datetime.now().isoformat(timespec="seconds")


def _write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    # Windows: os.replace fails with 'access denied' while another process reads the target -> wait briefly and retry
    import time as _t
    for k in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            _t.sleep(0.05 * (k + 1) if k < 10 else 0.5)
    os.unlink(tmp)
    raise PermissionError(f"could not write: {path}")


def all_scenarios():
    SCEN.mkdir(exist_ok=True)
    out = []
    for p in sorted(SCEN.glob("s*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return out


def get(sid):
    return json.loads((SCEN / f"{sid}.json").read_text(encoding="utf-8"))


def save(s):
    s["updated"] = now()
    _write(SCEN / f"{s['id']}.json", s)
    return s


def next_id():
    nums = [int(m.group(1)) for p in SCEN.glob("s*.json") if (m := re.match(r"s(\d+)", p.stem))]
    return f"s{(max(nums) + 1) if nums else 1:03d}"


def add_history(s, by, kind, text=""):
    s.setdefault("history", []).append({"at": now(), "by": by, "type": kind, "text": text})


# ---------------- user actions (panel) ----------------
def approve(sid, edits=None):
    s = get(sid)
    if edits:
        apply_edits(s, edits)
    s["status"] = "approved"
    add_history(s, "user", "approve")
    return save(s)


def reject(sid, note=""):
    s = get(sid)
    s["status"] = "rejected"
    add_history(s, "user", "reject", note)
    return save(s)


def feedback(sid, text, edits=None):
    s = get(sid)
    if edits:
        apply_edits(s, edits)
    s["status"] = "revise"
    add_history(s, "user", "feedback", text)
    return save(s)


def set_music(sid, name):
    """name: track name, 'auto' (picked at production) or 'none' (no music)."""
    s = get(sid)
    s["music"] = name
    add_history(s, "user", "music", name)
    return save(s)


def prioritize(sid):
    s = get(sid)
    s["priority"] = now()
    return save(s)


def approve_video(sid):
    import shutil
    s = get(sid)
    v = s["video"]
    src = ROOT / "videos" / v["folder"] / v["file"]
    dst = ROOT / "approved" / v["file"]
    dst.parent.mkdir(exist_ok=True)
    shutil.copy2(src, dst)
    s["status"] = "produced"
    add_history(s, "user", "video_approve")
    return save(s), dst


def video_feedback(sid, text):
    s = get(sid)
    s["status"] = "video_revise"
    add_history(s, "user", "video_feedback", text)
    return save(s)


def _tags(v):
    if isinstance(v, str):
        v = v.replace(",", " ").split()
    return [t.strip().lstrip("#") for t in (v or []) if t.strip().lstrip("#")]


def update_post(sid, data):
    """Update the post text (during video review / video revision). Does not affect the video.
    Also written to the video folder's script.json, because the publisher reads the text from there."""
    s = get(sid)
    if s["status"] in ("produced", "published"):
        raise ValueError("The video is already in the Buffer queue; edit the text in Buffer instead.")
    post = s.setdefault("post", {})
    if "caption" in data:
        post["caption"] = (data["caption"] or "").strip()
        if not post["caption"]:
            raise ValueError("post text cannot be empty")
    if "title" in data:
        t = (data["title"] or "").strip()
        if len(t) > 100:
            raise ValueError("YouTube title can be at most 100 characters")
        post["title"] = t
        post.setdefault("youtube", {})["title"] = t
    if "hashtags" in data:
        post["hashtags"] = _tags(data["hashtags"])
    if "tiktok_hashtags" in data:
        tt = _tags(data["tiktok_hashtags"])
        if len(tt) > 5:
            raise ValueError("at most 5 hashtags for TikTok")
        post.setdefault("tiktok", {})["hashtags"] = tt
    add_history(s, "user", "post_edit")
    v = s.get("video") or {}
    if v.get("folder"):
        sp = ROOT / "videos" / v["folder"] / "script.json"
        if sp.exists():
            sj = json.loads(sp.read_text(encoding="utf-8"))
            sj["post"] = post
            _write(sp, sj)
    return save(s)


def music_list():
    from promovideo.music import tracks
    return tracks()


def apply_edits(s, edits):
    """Sentence/caption texts edited by hand in the panel."""
    changed = []
    for ln in s.get("lines", []):
        new = edits.get("lines", {}).get(ln["id"])
        if new is not None and new.strip() and new.strip() != ln["text"]:
            changed.append(f"{ln['id']}: '{ln['text']}' -> '{new.strip()}'")
            ln["text"] = new.strip()
            ln.pop("caption_parts", None)   # the parts were based on the old text
            ln.pop("highlight_parts", None)
            if ln.get("highlight") and ln["highlight"].lower() not in ln["text"].lower():
                ln["highlight"] = ""
    cap = edits.get("caption")
    if cap is not None and cap.strip() != s.get("post", {}).get("caption", "").strip():
        s.setdefault("post", {})["caption"] = cap.strip()
        changed.append("post text changed")
    if changed:
        add_history(s, "user", "edit", "; ".join(changed))


def requests():
    return json.loads(REQ.read_text(encoding="utf-8")) if REQ.exists() else []


def add_request(text, count=1):
    """Custom request: text may be empty (then scenarios on various topics). count: how many scenarios."""
    r = requests()
    count = max(1, min(10, int(count or 1)))
    item = {"id": f"r{len(r) + 1:03d}", "at": now(), "text": (text or "").strip(), "count": count,
            "status": "open", "scenarios": []}
    r.append(item)
    _write(REQ, r)
    return item


def add_note(text):
    NOTES.parent.mkdir(exist_ok=True)
    with open(NOTES, "a", encoding="utf-8") as f:
        f.write(f"\n- ({dt.date.today()}) {text.strip()}")


def notes():
    return NOTES.read_text(encoding="utf-8") if NOTES.exists() else ""
