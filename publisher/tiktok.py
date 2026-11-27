"""TikTok - Content Posting API, local file (FILE_UPLOAD).

Two modes (.env TIKTOK_MODE):
  inbox  (default) : the video lands in your TikTok inbox as a draft; tap the notification on your phone
                     and share it. The only way to post publicly with an unaudited app.
                     Scope: video.upload. At most 5 pending drafts per 24 hours.
  direct           : direct publishing. Scope: video.publish. Until the app passes TikTok's audit
                     it can only post privately (SELF_ONLY).
Required (.env): TIKTOK_CLIENT_KEY, TIKTOK_CLIENT_SECRET, TIKTOK_REDIRECT_URI (an https URL registered in your app)
First time:  python -m publisher auth tiktok
"""
import math
import secrets
import time
import urllib.parse
import webbrowser

import requests

from .common import env, get_tokens, save_tokens, log

API = "https://open.tiktokapis.com/v2"
AUTH = "https://www.tiktok.com/v2/auth/authorize/"
MB = 1024 * 1024


def _mode():
    return env("TIKTOK_MODE", "inbox")


def _client():
    return (env("TIKTOK_CLIENT_KEY", required=True), env("TIKTOK_CLIENT_SECRET", required=True),
            env("TIKTOK_REDIRECT_URI", required=True))


def authorize():
    ck, cs, redirect = _client()
    state = secrets.token_urlsafe(16)
    scope = "user.info.basic," + ("video.publish" if _mode() == "direct" else "video.upload")
    url = AUTH + "?" + urllib.parse.urlencode({
        "client_key": ck, "scope": scope, "response_type": "code",
        "redirect_uri": redirect, "state": state})
    print("Open this URL in your browser and authorize with your TikTok account:\n" + url)
    webbrowser.open(url)
    back = input("\nAfter authorizing, paste the FULL URL of the page you were redirected to:\n> ").strip()
    q = urllib.parse.parse_qs(urllib.parse.urlparse(back).query)
    if q.get("state", [""])[0] != state or "code" not in q:
        raise RuntimeError(f"TikTok authorization failed: {q}")
    tok = requests.post(f"{API}/oauth/token/", timeout=30, data={
        "client_key": ck, "client_secret": cs, "code": q["code"][0],
        "grant_type": "authorization_code", "redirect_uri": redirect}).json()
    _save(tok)
    print("TikTok connected.")


def _save(tok):
    if "access_token" not in tok:
        raise RuntimeError(f"TikTok token error: {tok}")
    save_tokens("tiktok", {"access_token": tok["access_token"],
                           "refresh_token": tok["refresh_token"],
                           "expires_at": time.time() + int(tok.get("expires_in", 0)) - 120,
                           "open_id": tok.get("open_id")})


def _access_token():
    t = get_tokens("tiktok")
    if not t.get("refresh_token"):
        raise RuntimeError("TikTok not connected: python -m publisher auth tiktok")
    if time.time() < t.get("expires_at", 0):
        return t["access_token"]
    ck, cs, _ = _client()
    tok = requests.post(f"{API}/oauth/token/", timeout=30, data={
        "client_key": ck, "client_secret": cs, "grant_type": "refresh_token",
        "refresh_token": t["refresh_token"]}).json()
    _save(tok)
    return tok["access_token"]


def _h(at):
    return {"Authorization": f"Bearer {at}", "Content-Type": "application/json; charset=UTF-8"}


def _ok(r):
    d = r.json()
    err = d.get("error", {})
    if r.status_code >= 400 or (err.get("code") not in (None, "ok")):
        raise RuntimeError(f"TikTok {r.status_code}: {err or r.text[:400]}")
    return d.get("data", {})


def _chunks(size):
    if size < 5 * MB:
        return size, 1
    chunk = 10 * MB if size > 10 * MB else size
    return chunk, max(1, size // chunk)


def whoami():
    at = _access_token()
    if _mode() != "direct":
        return {"mode": "inbox", "open_id": get_tokens("tiktok").get("open_id")}
    return _ok(requests.post(f"{API}/post/publish/creator_info/query/", headers=_h(at), timeout=30))


def publish(video, caption, meta):
    at = _access_token()
    size = video.stat().st_size
    chunk, n = _chunks(size)
    src = {"source": "FILE_UPLOAD", "video_size": size, "chunk_size": chunk, "total_chunk_count": n}
    if _mode() == "direct":
        info = whoami()
        opts = info.get("privacy_level_options", [])
        want = env("TIKTOK_PRIVACY", "PUBLIC_TO_EVERYONE")
        privacy = want if want in opts else "SELF_ONLY"
        if privacy != want:
            log(f"tiktok: {want} not allowed ({opts}), using SELF_ONLY")
        body = {"post_info": {"title": caption[:2200], "privacy_level": privacy,
                              "disable_duet": False, "disable_stitch": False,
                              "disable_comment": False, "video_cover_timestamp_ms": 1000},
                "source_info": src}
        init = _ok(requests.post(f"{API}/post/publish/video/init/", json=body, headers=_h(at), timeout=60))
    else:
        init = _ok(requests.post(f"{API}/post/publish/inbox/video/init/", json={"source_info": src},
                                 headers=_h(at), timeout=60))
    pid, url = init["publish_id"], init["upload_url"]
    log(f"tiktok: publish_id {pid}, {n} chunks")

    with open(video, "rb") as f:
        for i in range(n):
            start = i * chunk
            end = size - 1 if i == n - 1 else start + chunk - 1
            f.seek(start)
            part = f.read(end - start + 1)
            for attempt in range(3):
                r = requests.put(url, data=part, timeout=600, headers={
                    "Content-Type": "video/mp4", "Content-Length": str(len(part)),
                    "Content-Range": f"bytes {start}-{end}/{size}"})
                if r.status_code in (201, 206):
                    break
                if r.status_code < 500:
                    raise RuntimeError(f"TikTok chunk upload {r.status_code}: {r.text[:300]}")
                time.sleep(5 * (attempt + 1))
            else:
                raise RuntimeError("TikTok chunk upload failed (5xx)")

    deadline = time.time() + 600
    while time.time() < deadline:
        st = _ok(requests.post(f"{API}/post/publish/status/fetch/", json={"publish_id": pid},
                               headers=_h(at), timeout=30))
        s = st.get("status")
        if s in ("SEND_TO_USER_INBOX", "PUBLISH_COMPLETE"):
            ids = st.get("publicaly_available_post_id") or st.get("publicly_available_post_id") or []
            return {"id": str(ids[0]) if ids else pid, "status": s,
                    "note": "TikTok uygulamasindaki bildirime dokunup paylas" if s == "SEND_TO_USER_INBOX" else ""}
        if s == "FAILED":
            raise RuntimeError(f"TikTok processing error: {st}")
        time.sleep(10)
    raise RuntimeError("TikTok status timed out")
