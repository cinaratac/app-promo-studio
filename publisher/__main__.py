"""Publishing CLI.

  python -m publisher queue                      # videos waiting in approved/ + missing post texts
  python -m publisher publish --dry-run          # show what would happen, send nothing
  python -m publisher publish [--max 1] [--only instagram,youtube]
  python -m publisher publish --fill max         # fill the Buffer queue up to the allowed limit (BUFFER_MAX_QUEUE, 10)
  python -m publisher queued                     # number of posts waiting in Buffer
  python -m publisher publish --file <name.mp4>  # queue only this video
  python -m publisher check                      # Buffer channels + R2 connection test
  python -m publisher status                     # publishing history (with the current Buffer status)
  python -m publisher archive [--dry-run]        # move videos published on all platforms to published/
  python -m publisher mark-manual <name.mp4..|--all>  # mark videos you shared by hand as published
  python -m publisher auth youtube|tiktok        # only for PUBLISH_BACKEND=direct

Only videos in approved/ are published. Each video goes to each platform once (state.json).
Every publish run archives first.
"""
import sys

from . import common as C


def backend():
    """buffer (default) or direct (platform APIs directly)."""
    return C.env("PUBLISH_BACKEND", "buffer")


def _mods():
    from . import instagram, youtube, tiktok
    return {"instagram": instagram, "youtube": youtube, "tiktok": tiktok}


def pending():
    st = C.state()
    out = []
    for v in sorted(C.APPROVED.glob("*.mp4"), key=lambda p: p.stat().st_mtime):
        done = st.get(C.video_key(v), {})
        todo = [p for p in C.enabled_platforms() if p not in done]
        if todo:
            out.append((v, todo))
    return out


def cmd_queue():
    rows = pending()
    if not rows:
        print("Queue is empty.")
    for v, todo in rows:
        meta = C.post_meta(v)
        note = "" if meta else "   <- no post text, will be skipped (add approved/<name>.post.json)"
        print(f"{v.name:45s} -> {', '.join(todo)}{note}")


def buffer_max():
    """Scheduled posts Buffer allows per channel (free plan 10; raise it in .env on a paid plan)."""
    return int(C.env("BUFFER_MAX_QUEUE", "10"))


def queued_counts():
    """Posts in Buffer not yet shared (scheduled/sending), per platform."""
    from . import buffer
    st = C.state()
    counts = {p: 0 for p in C.enabled_platforms()}
    for v in C.APPROVED.glob("*.mp4"):
        rec = st.get(C.video_key(v), {})
        for p in counts:
            r = rec.get(p)
            if r and r.get("via") == "buffer":
                try:
                    s = buffer.post_status(r["id"])["status"]
                except Exception:
                    s = "scheduled"
                if s in ("scheduled", "sending", "needs_approval", "draft"):
                    counts[p] += 1
    return counts


def cmd_publish(args):
    dry = "--dry-run" in args
    mx = int(args[args.index("--max") + 1]) if "--max" in args else 1
    only = args[args.index("--only") + 1].split(",") if "--only" in args else None
    only_file = args[args.index("--file") + 1] if "--file" in args else None
    mods = _mods()
    if not dry:
        from . import archive
        try:
            archive.run()
        except Exception as e:
            C.log(f"archive error: {e}")
    if "--fill" in args:
        nxt = args[args.index("--fill") + 1] if args.index("--fill") + 1 < len(args) else "max"
        target = buffer_max() if nxt in ("max", "") or nxt.startswith("--") else int(nxt)
        q = queued_counts()
        have = min(q.values()) if q else 0
        mx = max(0, target - have)
        C.log(f"Buffer queue: {q} -> target {target}, adding at most {mx}")
    done_videos, failures = 0, 0
    for v, todo in pending():
        if only_file and v.name != only_file:
            continue
        if done_videos >= mx:
            break
        meta = C.post_meta(v)
        if not meta:
            C.log(f"SKIP {v.name}: no post text")
            continue
        p, errs = C.check_video(v)
        if errs:
            C.log(f"SKIP {v.name}: {'; '.join(errs)}")
            continue
        targets = [t for t in todo if not only or t in only]
        C.log(f"{'[DRY] ' if dry else ''}{v.name} ({p['dur']:.1f} s, {p['w']}x{p['h']}, "
              f"{p['size'] / 1e6:.1f} MB) -> {', '.join(targets)}")
        for plat in targets:
            cap = C.caption_for(meta, plat)
            if dry:
                print(f"  --- {plat} ---\n  " + cap.replace("\n", "\n  "))
                continue
            try:
                if backend() == "buffer":
                    from . import buffer
                    url = buffer.video_url(v, C.video_key(v).split(":")[1])
                    res = buffer.publish(plat, v, cap, meta, url)
                else:
                    res = mods[plat].publish(v, cap, meta)
                C.mark(v, plat, res)
                C.log(f"  {plat}: OK {res}")
            except Exception as e:  # an error on one platform should not stop the others
                failures += 1
                C.log(f"  {plat}: ERROR {e}")
        done_videos += 1
    if not done_videos:
        print("No video ready to publish.")
    return 1 if failures else 0


def cmd_check():
    if backend() == "buffer":
        from . import buffer, r2
        try:
            print("Buffer channels:")
            for line in buffer.whoami():
                print("   " + line)
            for plat in C.enabled_platforms():
                try:
                    print(f"   {plat:10s} -> {buffer.channel_for(plat)}")
                except Exception as e:
                    print(f"   {plat:10s} -- {e}")
        except Exception as e:
            print(f"Buffer -- {e}")
        try:
            r2._request("PUT", f"{C.key_prefix()}/_connection_test.txt", b"ok", "text/plain")
            import requests
            code = requests.head(r2.public_url(f"{C.key_prefix()}/_connection_test.txt"), timeout=30).status_code
            r2.delete(f"{C.key_prefix()}/_connection_test.txt")
            print(f"R2         {'OK' if code == 200 else f'-- upload worked but the public URL returned {code}'}")
        except Exception as e:
            print(f"R2         -- {e}")
        return
    for name, m in _mods().items():
        if name not in C.enabled_platforms():
            continue
        try:
            print(f"{name:10s} OK  {m.whoami()}")
        except Exception as e:
            print(f"{name:10s} --  {e}")


def cmd_status():
    for k, d in C.state().items():
        print(d.get("file", k))
        for plat in C.PLATFORMS:
            if plat in d:
                r = d[plat]
                extra = ""
                if r.get("via") == "buffer":
                    try:
                        from . import buffer
                        p = buffer.post_status(r["id"])
                        extra = f"[{p['status']}] {p.get('externalLink') or p.get('dueAt') or ''}"
                        if p.get("error"):
                            extra += f"  ERROR: {p['error']['message']}"
                    except Exception as e:
                        extra = f"(durum alinamadi: {e})"
                print(f"   {plat:10s} {r.get('at')}  {r.get('url') or r.get('id')}  {r.get('note', '')} {extra}")


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    C.load_env()
    if not argv:
        print(__doc__)
        return 0
    cmd = argv[0]
    if cmd == "queue":
        cmd_queue()
    elif cmd == "publish":
        return cmd_publish(argv[1:])
    elif cmd == "queued":
        q = queued_counts()
        cap = buffer_max()
        waiting = len(pending())
        free = max(0, cap - (max(q.values()) if q else 0) - waiting)
        print("Waiting in Buffer: " + ", ".join(f"{k}={v}" for k, v in q.items()))
        print(f"videos in approved/ not yet sent to Buffer: {waiting}")
        print(f"Buffer limit (per channel): {cap}")
        print(f"CAN PRODUCE: {free}")
    elif cmd == "archive":
        from . import archive
        n = archive.run(dry="--dry-run" in argv)
        print(f"{n} videos archived.")
    elif cmd == "mark-manual":
        from . import archive
        archive.mark_manual(argv[1:])
    elif cmd == "auth":
        _mods()[argv[1]].authorize()
    elif cmd == "check":
        cmd_check()
    elif cmd == "status":
        cmd_status()
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
