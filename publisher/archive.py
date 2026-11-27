"""Moves published videos from approved/ to published/.

A video is moved once it is published on ALL enabled platforms:
  - Buffer post: its Buffer status must be 'sent' (waiting/failed ones are not moved)
  - direct API or marked by hand ('manual'): counts as done
The .post.json moves along and the temporary copy on R2 is deleted (Buffer already fetched the video).
Nothing is deleted locally: files in published/ are the archive.
"""
import shutil
import urllib.parse
from pathlib import Path

from . import common as C

PUBLISHED = C.ROOT / "published"


def _platform_done(rec):
    if rec.get("via") != "buffer":
        return True, ""
    from . import buffer
    p = buffer.post_status(rec["id"])
    if p.get("error"):
        return False, f"hata: {p['error']['message']}"
    return p["status"] == "sent", p["status"]


def _r2_key(url):
    base = C.env("R2_PUBLIC_BASE_URL", "").rstrip("/") + "/"
    if url and base != "/" and url.startswith(base):
        return urllib.parse.unquote(url[len(base):])
    return None


def run(dry=False):
    st = C.state()
    moved = 0
    for v in sorted(C.APPROVED.glob("*.mp4")):
        key = C.video_key(v)
        rec = st.get(key, {})
        plats = C.enabled_platforms()
        if not all(p in rec for p in plats):
            continue
        waiting = []
        for p in plats:
            ok, why = _platform_done(rec[p])
            if not ok:
                waiting.append(f"{p}: {why}")
        if waiting:
            C.log(f"archive: {v.name} waiting ({'; '.join(waiting)})")
            continue
        if dry:
            print(f"[DRY] {v.name} -> published/")
            continue
        PUBLISHED.mkdir(exist_ok=True)
        dst = PUBLISHED / v.name
        if dst.exists():
            dst = PUBLISHED / f"{v.stem}_{key.split(':')[1]}{v.suffix}"
        shutil.move(str(v), dst)
        side = v.with_suffix(".post.json")
        if side.exists():
            shutil.move(str(side), dst.with_suffix(".post.json"))
        for url in {rec[p].get("media") for p in plats if rec[p].get("media")}:
            k = _r2_key(url)
            if k:
                try:
                    from . import r2
                    r2.delete(k)
                except Exception as e:
                    C.log(f"archive: could not delete from R2 {k}: {e}")
        C.log(f"archive: {v.name} -> {dst.relative_to(C.ROOT)}")
        moved += 1
    return moved


def mark_manual(names):
    """Mark videos shared outside this system (by hand) as published."""
    files = sorted(C.APPROVED.glob("*.mp4")) if names == ["--all"] else [C.APPROVED / n for n in names]
    st = C.state()
    for v in files:
        if not v.exists():
            print(f"not found: {v.name}")
            continue
        rec = st.get(C.video_key(v), {})
        for p in C.enabled_platforms():
            if p not in rec:
                C.mark(v, p, {"via": "manual", "note": "sistem disinda paylasildi"})
        print(f"marked: {v.name}")
