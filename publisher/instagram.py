"""Instagram Reels - Facebook Login for Business route, local file (resumable) upload.

Flow: create a container (media_type=REELS, upload_type=resumable)
      -> send the file to rupload.facebook.com
      -> wait until status_code is FINISHED
      -> media_publish
Required (.env): IG_USER_ID, IG_ACCESS_TOKEN (a System User token is recommended, it does not expire),
                 IG_API_VERSION (default v27.0)
"""
import time

import requests

from .common import env, log

GRAPH = "https://graph.facebook.com"
RUPLOAD = "https://rupload.facebook.com/ig-api-upload"


def _cfg():
    return (env("IG_USER_ID", required=True), env("IG_ACCESS_TOKEN", required=True),
            env("IG_API_VERSION", "v27.0"))


def _check(r):
    if r.status_code >= 400:
        raise RuntimeError(f"Instagram {r.status_code}: {r.text[:500]}")
    return r.json()


def whoami():
    uid, tok, ver = _cfg()
    return _check(requests.get(f"{GRAPH}/{ver}/{uid}", params={
        "fields": "username,name", "access_token": tok}, timeout=30))


def publishing_limit():
    uid, tok, ver = _cfg()
    return _check(requests.get(f"{GRAPH}/{ver}/{uid}/content_publishing_limit", params={
        "fields": "quota_usage,config", "access_token": tok}, timeout=30))


def publish(video, caption, meta):
    uid, tok, ver = _cfg()
    body = {"media_type": "REELS", "upload_type": "resumable", "caption": caption,
            "share_to_feed": "true", "access_token": tok}
    if meta.get("instagram", {}).get("cover_offset_ms") is not None:
        body["thumb_offset"] = str(meta["instagram"]["cover_offset_ms"])
    c = _check(requests.post(f"{GRAPH}/{ver}/{uid}/media", data=body, timeout=60))
    cid = c["id"]
    log(f"instagram: container {cid}")

    data = video.read_bytes()
    up = requests.post(f"{RUPLOAD}/{ver}/{cid}", data=data, timeout=600, headers={
        "Authorization": f"OAuth {tok}", "offset": "0", "file_size": str(len(data))})
    _check(up)
    log("instagram: file uploaded, processing")

    deadline = time.time() + 600
    while True:
        st = _check(requests.get(f"{GRAPH}/{ver}/{cid}", params={
            "fields": "status_code,status", "access_token": tok}, timeout=30))
        code = st.get("status_code")
        if code == "FINISHED":
            break
        if code in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"Instagram processing error: {st}")
        if time.time() > deadline:
            raise RuntimeError("Instagram processing timed out (10 min)")
        time.sleep(20)

    pub = _check(requests.post(f"{GRAPH}/{ver}/{uid}/media_publish", data={
        "creation_id": cid, "access_token": tok}, timeout=60))
    mid = pub["id"]
    link = _check(requests.get(f"{GRAPH}/{ver}/{mid}", params={
        "fields": "permalink", "access_token": tok}, timeout=30)).get("permalink")
    return {"id": mid, "url": link}
