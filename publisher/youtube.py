"""YouTube Shorts - Data API v3 videos.insert (resumable). Vertical videos <=3 min show up as Shorts.

Required (.env): YT_CLIENT_ID, YT_CLIENT_SECRET (Google Cloud > OAuth client, type: Desktop app)
First time:  python -m publisher auth youtube   (you authorize in the browser, the refresh token is saved)
"""
import http.server
import secrets
import threading
import time
import urllib.parse
import webbrowser

import requests

from .common import env, get_tokens, save_tokens, log

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
SCOPE = "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.readonly"


def _client():
    return env("YT_CLIENT_ID", required=True), env("YT_CLIENT_SECRET", required=True)


def authorize():
    cid, csec = _client()
    state = secrets.token_urlsafe(16)
    got = {}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("Tamam, bu sekmeyi kapatabilirsin.".encode("utf-8"))

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    redirect = f"http://127.0.0.1:{srv.server_address[1]}"
    url = AUTH + "?" + urllib.parse.urlencode({
        "client_id": cid, "redirect_uri": redirect, "response_type": "code", "scope": SCOPE,
        "access_type": "offline", "prompt": "consent", "state": state})
    print("Open this URL in your browser and authorize with the YouTube channel's account:\n" + url)
    webbrowser.open(url)
    t = threading.Thread(target=srv.handle_request)
    t.start()
    t.join(timeout=300)
    srv.server_close()
    if got.get("state") != state or "code" not in got:
        raise RuntimeError(f"YouTube authorization failed: {got}")
    tok = requests.post(TOKEN, data={
        "code": got["code"], "client_id": cid, "client_secret": csec,
        "redirect_uri": redirect, "grant_type": "authorization_code"}, timeout=30).json()
    if "refresh_token" not in tok:
        raise RuntimeError(f"no refresh_token received: {tok}")
    save_tokens("youtube", {"refresh_token": tok["refresh_token"]})
    print("YouTube connected:", whoami())


def _access_token():
    cid, csec = _client()
    rt = get_tokens("youtube").get("refresh_token")
    if not rt:
        raise RuntimeError("YouTube not connected: python -m publisher auth youtube")
    r = requests.post(TOKEN, data={"client_id": cid, "client_secret": csec,
                                   "refresh_token": rt, "grant_type": "refresh_token"}, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"YouTube token refresh error: {r.text[:300]}")
    return r.json()["access_token"]


def whoami():
    at = _access_token()
    r = requests.get("https://www.googleapis.com/youtube/v3/channels",
                     params={"part": "snippet", "mine": "true"},
                     headers={"Authorization": f"Bearer {at}"}, timeout=30).json()
    items = r.get("items") or []
    return items[0]["snippet"]["title"] if items else r


def publish(video, caption, meta):
    at = _access_token()
    y = meta.get("youtube", {})
    title = y.get("title") or meta.get("title") or video.stem
    if "#shorts" not in title.lower() and len(title) <= 90:
        title += " #Shorts"
    body = {
        "snippet": {"title": title[:100], "description": caption[:5000],
                    "tags": [t.lstrip("#") for t in meta.get("hashtags", [])][:15],
                    "categoryId": y.get("category_id", "26"),          # 26 = Howto & Style
                    "defaultLanguage": meta.get("language", "tr"),
                    "defaultAudioLanguage": meta.get("language", "tr")},
        "status": {"privacyStatus": y.get("privacy", env("YT_PRIVACY", "public")),
                   "selfDeclaredMadeForKids": False},
    }
    size = video.stat().st_size
    init = requests.post(UPLOAD, params={"uploadType": "resumable", "part": "snippet,status"},
                         json=body, timeout=60, headers={
                             "Authorization": f"Bearer {at}",
                             "X-Upload-Content-Type": "video/mp4",
                             "X-Upload-Content-Length": str(size)})
    if init.status_code >= 400:
        raise RuntimeError(f"YouTube init {init.status_code}: {init.text[:500]}")
    loc = init.headers["Location"]
    for attempt in range(4):
        r = requests.put(loc, data=video.read_bytes(), timeout=900,
                         headers={"Authorization": f"Bearer {at}", "Content-Type": "video/mp4"})
        if r.status_code in (200, 201):
            vid = r.json()["id"]
            return {"id": vid, "url": f"https://youtube.com/shorts/{vid}"}
        if r.status_code < 500:
            raise RuntimeError(f"YouTube upload {r.status_code}: {r.text[:500]}")
        log(f"youtube: {r.status_code}, retrying")
        time.sleep(10 * (attempt + 1))
    raise RuntimeError("YouTube upload failed (5xx)")
