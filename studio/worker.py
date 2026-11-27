"""Production worker: turns approved scenarios into videos one by one. Runs in the background while the panel is open.

  python -m studio.worker --once     # process the waiting ones once and exit
"""
import os
import subprocess
import sys
import threading
import time

from . import store
from .produce import read_progress

LOCK = store.ROOT / "studio" / ".production.lock"
wake = threading.Event()
state = {"current": None}


def _lock_alive():
    if not LOCK.exists():
        return False
    try:
        pid, beat = LOCK.read_text().split()
        return time.time() - float(beat) < 120 and int(pid) != os.getpid()
    except Exception:
        return False


def _beat():
    LOCK.write_text(f"{os.getpid()} {time.time()}")


def queue():
    """To produce: 'produce now' items first, then the oldest approved ones."""
    sc = [s for s in store.all_scenarios() if s["status"] == "approved"]
    sc.sort(key=lambda s: (0 if s.get("priority") else 1, s.get("priority", ""), s.get("updated", "")))
    return sc


def produce_one(s):
    state["current"] = s["id"]
    try:
        p = subprocess.Popen([sys.executable, "-m", "studio.produce", s["id"]], cwd=store.ROOT)
        while p.poll() is None:
            _beat()
            time.sleep(2)
    finally:
        state["current"] = None


def produce_stories():
    """Stories are quick: they are processed before scenario videos."""
    from . import stories
    import datetime as _dt
    n = 0
    for s in stories.all_stories():  # put productions interrupted by a closed panel back in the queue
        if s["status"] == "producing":
            age = (_dt.datetime.now() - _dt.datetime.fromisoformat(s.get("updated", s["created"]))).total_seconds()
            if age > 600:
                s["status"] = "queued"
                stories.save(s)
    while True:
        q = stories.queue()
        if not q:
            return n
        st = q[0]
        state["current"] = st["id"]
        try:
            p = subprocess.Popen([sys.executable, "-m", "studio.stories", "produce", st["id"]], cwd=store.ROOT)
            while p.poll() is None:
                _beat()
                time.sleep(1)
        finally:
            state["current"] = None
        if stories.get(st["id"])["status"] == "queued":  # avoid an endless loop if the subprocess could not start at all
            return n
        n += 1


def run_once():
    if _lock_alive():
        return 0
    _beat()
    n = 0
    try:
        n += produce_stories()
        for s in queue():
            pr = read_progress(s["id"]) or {}
            if pr.get("state") == "error" and not s.get("priority"):
                continue  # do not auto-retry failed ones; use 'retry' in the panel
            n += produce_stories()
            produce_one(s)
            n += 1
    finally:
        LOCK.unlink(missing_ok=True)
    return n


def fill_buffer():
    """Send videos approved into approved/ to Buffer (if there is room in the queue)."""
    subprocess.run([sys.executable, "-m", "publisher", "publish", "--fill", "max"], cwd=store.ROOT,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def collect_stats():
    """Once a day: measure engagement of posts published 3 days ago (studio/stats.py)."""
    from . import stats
    if not stats.due():
        return
    subprocess.run([sys.executable, "-m", "studio.stats", "collect"], cwd=store.ROOT,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=300)


def loop(interval=60):
    last_fill = 0
    while True:
        try:
            run_once()
            if time.time() - last_fill > 3600:
                fill_buffer()
                last_fill = time.time()
                collect_stats()
        except Exception as e:
            print("worker error:", e)
        wake.wait(interval)
        wake.clear()


def start_background():
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if "--once" in sys.argv:
        print(f"{run_once()} videos produced")
        fill_buffer()
        collect_stats()
    else:
        loop()
