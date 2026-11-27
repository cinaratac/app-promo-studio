"""Helper commands used by the scheduled Claude tasks.

  python -m studio.cli status                    # status summary + to-do list
  python -m studio.cli show <sid>                # full scenario (JSON)
  python -m studio.cli set <sid> <status> [note] # change status (+ write history)
  python -m studio.cli req-done <rid> <sid..>    # mark a custom request as fulfilled
  python -m studio.cli next-id                   # next id for a new scenario
  python -m studio.cli sync                      # mark scenarios of published videos as 'published'
  python -m studio.cli validate <sid>            # check a scenario JSON
  python -m studio.cli pending-work              # open requests / revisions? (prints 'NONE', exit code 1 if nothing)
  python -m studio.cli lock|unlock               # prevents hourly runs from overlapping
"""
import json
import sys

from . import store

REQUIRED = ["id", "title", "status", "lines", "post"]


def validate(s):
    errs = [f"missing field: {k}" for k in REQUIRED if k not in s]
    for i, ln in enumerate(s.get("lines", [])):
        if not ln.get("id") or not ln.get("text"):
            errs.append(f"line {i + 1}: id/text missing")
        hl = ln.get("highlight", "")
        if hl and hl.lower() not in ln.get("text", "").lower():
            errs.append(f"{ln.get('id')}: highlight '{hl}' is not in the sentence")
    p = s.get("post", {})
    if not p.get("caption"):
        errs.append("post.caption is empty")
    if len(p.get("title", "")) > 100:
        errs.append("post.title is longer than 100 characters")
    if len(p.get("tiktok", {}).get("hashtags", p.get("hashtags", []))) > 5 and "tiktok" not in p:
        errs.append("at most 5 hashtags for TikTok: add post.tiktok.hashtags")
    shots = s.get("shots") or []
    if shots:
        if len(shots) != len(s.get("lines", [])):
            errs.append(f"shots ({len(shots)}) must match lines ({len(s.get('lines', []))})")
        if not any(x.get("screen") for x in shots):
            errs.append("at least 1 real app screen is required")
        for i, x in enumerate(shots):
            if x.get("screen") and not (store.ROOT / "assets" / "screenshots" / x["screen"]).exists():
                errs.append(f"shot {i + 1}: screenshot not found: {x['screen']}")
    for f in s.get("screenshots", []):
        if not (store.ROOT / "assets" / "screenshots" / f).exists():
            errs.append(f"screenshot not found: {f}")
    return errs


def status():
    sc = store.all_scenarios()
    by = {k: [s for s in sc if s["status"] == k] for k in store.STATUSES}
    print("Status: " + ", ".join(f"{k}={len(v)}" for k, v in by.items()))
    for s in by["revise"]:
        fb = [h for h in s.get("history", []) if h["type"] == "feedback"]
        print(f"  REVISE  {s['id']} '{s['title']}': {fb[-1]['text'] if fb else ''}")
    for r in store.requests():
        if r["status"] == "open":
            print(f"  REQUEST {r['id']}: {r['text']}")
    for s in by["approved"]:
        print(f"  PRODUCE {s['id']} '{s['title']}'")


def sync():
    """Mark scenarios whose videos were moved from approved/ to the published/ archive as 'published'."""
    pub = store.ROOT / "published"
    n = 0
    for s in store.all_scenarios():
        v = s.get("video") or {}
        if s["status"] == "produced" and v.get("file") and (pub / v["file"]).exists():
            s["status"] = "published"
            store.add_history(s, "claude", "published")
            store.save(s)
            n += 1
    print(f"{n} scenarios marked 'published'")


def main(a):
    sys.stdout.reconfigure(encoding="utf-8")
    cmd = a[0] if a else ""
    if cmd == "status":
        status()
    elif cmd == "show":
        print(json.dumps(store.get(a[1]), ensure_ascii=False, indent=2))
    elif cmd == "set":
        s = store.get(a[1])
        assert a[2] in store.STATUSES, f"invalid status {a[2]}"
        s["status"] = a[2]
        store.add_history(s, "claude", a[2] if a[2] in ("produced", "published") else "status", " ".join(a[3:]))
        store.save(s)
        print(f"{a[1]} -> {a[2]}")
    elif cmd == "req-done":
        reqs = store.requests()
        for r in reqs:
            if r["id"] == a[1]:
                r["status"] = "done"
                r["scenarios"] = a[2:]
        store._write(store.REQ, reqs)
        print(f"{a[1]} fulfilled")
    elif cmd == "next-id":
        print(store.next_id())
    elif cmd == "sync":
        sync()
    elif cmd == "pending-work":
        allsc = store.all_scenarios()
        rev = [x["id"] for x in allsc if x["status"] in ("revise", "video_revise")]
        noshots = [x["id"] for x in allsc if x["status"] in ("approved", "pending") and not x.get("shots")]
        req = [r for r in store.requests() if r["status"] == "open"]
        npend = sum(1 for x in allsc if x["status"] == "pending")
        low = npend < 3
        if noshots:
            print(f"shot plan missing: {noshots}")
        if low:
            print(f"low scenario stock: {npend} waiting for approval -> top up to at least 6")
        from .stories import pending_claude
        stw = [x["id"] for x in pending_claude()]
        if stw:
            print(f"stories to write/fix: {stw}  (see studio/TASK_STORY.md)")
        if not rev and not req and not noshots and not low and not stw:
            print("NONE")
            sys.exit(1)
        print(f"revisions: {rev}  requests: {[(r['id'], r.get('count', 1), r['text']) for r in req]}")
    elif cmd == "lock":
        import time
        lk = store.ROOT / "studio" / ".running.lock"
        if lk.exists() and time.time() - lk.stat().st_mtime < 3 * 3600:
            print("BUSY: another run is in progress")
            sys.exit(1)
        lk.write_text(store.now(), encoding="utf-8")
        print("LOCKED")
    elif cmd == "unlock":
        (store.ROOT / "studio" / ".running.lock").unlink(missing_ok=True)
        print("UNLOCKED")
    elif cmd == "validate":
        errs = validate(store.get(a[1]))
        print("\n".join(errs) if errs else "OK")
        sys.exit(1 if errs else 0)
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
