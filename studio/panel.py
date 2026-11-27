"""Scenario approval panel: http://127.0.0.1:8765  (reachable only from this computer)

  python -m studio.panel
"""
import json
import mimetypes

mimetypes.add_type("image/jpeg", ".jfif")
import sys
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import subprocess

from . import store, worker, stories, stats
from .produce import read_progress
from promovideo.brand import BRAND

import os
PORT = int(os.environ.get("STUDIO_PORT", "8765"))  # change if another panel already uses 8765
HERE = Path(__file__).resolve().parent
ROOT = store.ROOT
SERVE_DIRS = {"shots": ROOT / "assets" / "screenshots", "fonts": ROOT / "assets" / "fonts",
              "videos": ROOT / "videos", "assets": ROOT / "assets", "stories": ROOT / "stories" / "out"}


def publish_overview():
    p = ROOT / "publisher" / "state.json"
    st = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    approved = sorted(x.name for x in (ROOT / "approved").glob("*.mp4"))
    return {"queue": approved, "published": len(st)}


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path in ("/", "/index.html"):
            return self._send(200, (HERE / "panel.html").read_bytes(), "text/html; charset=utf-8")
        if path == "/api/state":
            sc = store.all_scenarios()
            for x in sc:
                if x["status"] in ("approved", "review", "video_revise"):
                    x["progress"] = read_progress(x["id"])
            return self._send(200, {"scenarios": sc, "requests": store.requests(), "current": worker.state["current"],
                                    "notes": store.notes(), "publish": publish_overview(),
                                    "music": store.music_list(), "stories": stories.all_stories(),
                                    "story_opts": {"screens": stories.screens_list(), "themes": stories.THEMES},
                                    "brand": {"app_name": BRAND["app_name"]}})
        if path == "/api/stats":
            a = stats.analysis()
            titles = {x["id"]: x.get("title") for x in store.all_scenarios()}
            for r in a["rows"] + a["waiting"]:
                r["title"] = titles.get(r.get("scenario"))
            return self._send(200, a)
        parts = path.strip("/").split("/", 1)
        if len(parts) == 2 and parts[0] in SERVE_DIRS:
            base = SERVE_DIRS[parts[0]].resolve()
            f = (base / urllib.parse.unquote(parts[1])).resolve()
            if base in f.parents and f.is_file():
                return self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "application/octet-stream")
        self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.headers.get("Origin") not in (None, f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}"):
            return self._send(403, {"error": "forbidden"})
        n = int(self.headers.get("Content-Length") or 0)
        data = json.loads(self.rfile.read(n) or b"{}")
        parts = urllib.parse.urlparse(self.path).path.strip("/").split("/")
        try:
            if parts[:2] == ["api", "scenario"] and len(parts) == 4:
                sid, act = parts[2], parts[3]
                if act == "approve":
                    res = store.approve(sid, data.get("edits"))
                    worker.wake.set()          # start producing the approved scenario right away
                    return self._send(200, res)
                if act == "reject":
                    if data.get("note"):
                        store.add_note(f"Rejected ({sid}): {data['note']}")
                    return self._send(200, store.reject(sid, data.get("note", "")))
                if act == "post":
                    try:
                        return self._send(200, store.update_post(sid, data))
                    except ValueError as e:
                        return self._send(400, {"error": str(e)})
                if act == "music":
                    name = data.get("music", "auto")
                    if name not in ("auto", "none") and name not in store.music_list():
                        return self._send(400, {"error": "unknown music track"})
                    return self._send(200, store.set_music(sid, name))
                if act == "feedback":
                    if not data.get("text", "").strip():
                        return self._send(400, {"error": "feedback is empty"})
                    return self._send(200, store.feedback(sid, data["text"], data.get("edits")))
            if parts[:2] == ["api", "produce"] and len(parts) == 3:
                s = store.prioritize(parts[2])
                pr = store.SCEN / "progress" / f"{parts[2]}.json"
                if pr.exists() and (read_progress(parts[2]) or {}).get("state") in ("error", "waiting"):
                    pr.unlink()
                worker.wake.set()
                return self._send(200, s)
            if parts[:2] == ["api", "video"] and len(parts) == 4:
                sid, act = parts[2], parts[3]
                if act == "approve":
                    s, dst = store.approve_video(sid)
                    r = subprocess.run([sys.executable, "-m", "publisher", "publish", "--file", dst.name],
                                       cwd=store.ROOT, capture_output=True, text=True, encoding="utf-8")
                    queued = ": OK" in (r.stdout or "")
                    store.add_history(s, "claude", "status", "added to the Buffer queue" if queued else
                                      "could not add to Buffer (the queue may be full); it will be added automatically when there is room")
                    store.save(s)
                    return self._send(200, {"ok": True, "queued": queued, "log": (r.stdout or "")[-600:]})
                if act == "feedback":
                    if not data.get("text", "").strip():
                        return self._send(400, {"error": "feedback is empty"})
                    return self._send(200, store.video_feedback(sid, data["text"]))
            if parts == ["api", "story"]:
                try:
                    made = stories.create(data)
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                worker.wake.set()
                return self._send(200, made)
            if parts[:2] == ["api", "story"] and len(parts) == 4:
                sid, act = parts[2], parts[3]
                try:
                    if act == "edit":
                        r = stories.edit(sid, data)
                    elif act == "regenerate":
                        r = stories.regenerate(sid)
                    elif act == "feedback":
                        if not data.get("text", "").strip():
                            return self._send(400, {"error": "feedback is empty"})
                        r = stories.feedback(sid, data["text"])
                    elif act == "reject":
                        r = stories.reject(sid)
                    elif act == "send":
                        r = stories.send(sid, data.get("mode", "queue"))
                    else:
                        return self._send(404, {"error": "unknown request"})
                except ValueError as e:
                    return self._send(400, {"error": str(e)})
                except RuntimeError as e:
                    return self._send(502, {"error": str(e)[:400]})
                worker.wake.set()
                return self._send(200, r)
            if parts == ["api", "stats", "collect"]:
                try:
                    n = stats.collect()
                except Exception as e:
                    return self._send(502, {"error": f"Buffer: {e}"[:400]})
                return self._send(200, {"measured": n})
            if parts == ["api", "request"]:
                return self._send(200, store.add_request(data.get("text", ""), data.get("count", 1)))
            if parts == ["api", "note"]:
                if not data.get("text", "").strip():
                    return self._send(400, {"error": "note is empty"})
                store.add_note(data["text"])
                return self._send(200, {"ok": True})
        except FileNotFoundError:
            return self._send(404, {"error": "scenario not found"})
        self._send(404, {"error": "unknown request"})


class Server(ThreadingHTTPServer):
    allow_reuse_address = False  # on Windows, stop a second panel from silently sharing the same port


def main():
    try:
        srv = Server(("127.0.0.1", PORT), H)
    except OSError:
        print(f"Panel already running: http://127.0.0.1:{PORT}")
        if "--no-browser" not in sys.argv:
            webbrowser.open(f"http://127.0.0.1:{PORT}")
        return
    url = f"http://127.0.0.1:{PORT}"
    worker.start_background()
    print(f"Scenario panel: {url}  (Ctrl+C to stop) - automatic production is on")
    if "--no-browser" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
