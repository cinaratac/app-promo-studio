"""Scheduled publishing via the Buffer GraphQL API (TikTok, Instagram Reels, YouTube Shorts).

Flow: the video is uploaded to R2 -> createPost for each channel (schedulingType=automatic).
Scheduling (.env BUFFER_MODE):
  addToQueue       (default) added to the queue following each channel's Posting Schedule in Buffer
  customScheduled  at BUFFER_TIME (local time of this computer); tomorrow if already past today
  shareNow         right away
Required (.env): BUFFER_API_KEY (+ R2 settings). Channels are found automatically; if you have more
than one channel of a kind, pick one with BUFFER_CHANNEL_TIKTOK / _INSTAGRAM / _YOUTUBE.
"""
import datetime as dt

import requests

from . import r2
from .common import env, log

API = "https://api.buffer.com"
SERVICE = {"tiktok": "tiktok", "instagram": "instagram", "youtube": "youtube"}


def gql(query, variables=None):
    r = requests.post(API, json={"query": query, "variables": variables or {}}, timeout=60,
                      headers={"Authorization": f"Bearer {env('BUFFER_API_KEY', required=True)}"})
    if r.status_code == 429:
        raise RuntimeError(f"Buffer rate limit hit, retry in {r.headers.get('Retry-After')} s")
    if r.status_code >= 400:
        raise RuntimeError(f"Buffer {r.status_code}: {r.text[:400]}")
    d = r.json()
    if d.get("errors"):
        raise RuntimeError(f"Buffer: {d['errors']}")
    return d["data"]


def channels():
    orgs = gql("query { account { organizations { id name } } }")["account"]["organizations"]
    out = []
    for o in orgs:
        chs = gql("""query($input: ChannelsInput!) { channels(input: $input) {
                       id name displayName service isDisconnected isQueuePaused } }""",
                  {"input": {"organizationId": o["id"]}})["channels"]
        out += [{**c, "org": o["name"]} for c in chs]
    return out


_cache = {}


def channel_for(platform):
    override = env(f"BUFFER_CHANNEL_{platform.upper()}")
    if override:
        return override
    if "list" not in _cache:
        _cache["list"] = channels()
    hits = [c for c in _cache["list"] if str(c["service"]).lower() == SERVICE[platform]]
    if not hits:
        raise RuntimeError(f"no {platform} channel connected in Buffer")
    if len(hits) > 1:
        raise RuntimeError(f"more than one {platform} channel; set BUFFER_CHANNEL_{platform.upper()} in .env")
    c = hits[0]
    if c["isDisconnected"]:
        raise RuntimeError(f"Buffer {platform} channel is disconnected; reconnect it in Buffer")
    return c["id"]


def whoami():
    return [f"{c['service']}: {c['displayName'] or c['name']} ({c['id']})"
            f"{' DISCONNECTED' if c['isDisconnected'] else ''}{' QUEUE PAUSED' if c['isQueuePaused'] else ''}"
            for c in channels()]


def _due_at():
    tz = dt.datetime.now().astimezone().tzinfo  # local time of this computer
    hh, mm = map(int, env("BUFFER_TIME", "19:00").split(":"))
    now = dt.datetime.now(tz)
    t = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if t <= now + dt.timedelta(minutes=10):
        t += dt.timedelta(days=1)
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def video_url(video, key_suffix):
    """The same video is uploaded once for all platforms."""
    from .common import key_prefix
    key = f"{key_prefix()}/{video.stem}-{key_suffix}.mp4"
    if key not in _cache:
        _cache[key] = r2.upload(video, key)
        log(f"r2: {_cache[key]}")
    return _cache[key]


CREATE = """mutation($input: CreatePostInput!) { createPost(input: $input) {
  ... on PostActionSuccess { post { id status dueAt schedulingType } }
  ... on MutationError { message } } }"""


def publish(platform, video, caption, meta, url):
    m = meta.get(platform, {})
    ai = env("BUFFER_AI_LABEL", "false").lower() == "true"
    md = {}
    if platform == "youtube":
        md["youtube"] = {"title": (m.get("title") or meta.get("title") or video.stem)[:100],
                         "categoryId": m.get("category_id", "26"),
                         "privacy": m.get("privacy", "public"),
                         "madeForKids": False, "notifySubscribers": True, "isAiGenerated": ai}
    elif platform == "instagram":
        md["instagram"] = {"type": "reel", "shouldShareToFeed": True, "isAiGenerated": ai}
    elif platform == "tiktok":
        md["tiktok"] = {"isAiGenerated": ai}
    mode = env("BUFFER_MODE", "addToQueue")
    # Notification publishing: you get a phone notification at post time, add sound/music in the app and share yourself
    notify = [p.strip() for p in env("BUFFER_NOTIFY_PLATFORMS", "").split(",") if p.strip()]
    sched = "notification" if platform in notify else "automatic"
    inp = {"channelId": channel_for(platform), "text": caption, "schedulingType": sched,
           "mode": mode, "needsApproval": False, "metadata": md,
           "assets": [{"video": {"url": url, "metadata": {"thumbnailOffset": int(m.get("cover_offset_ms", 1000))}}}]}
    if mode == "customScheduled":
        inp["dueAt"] = _due_at()
    res = gql(CREATE, {"input": inp})["createPost"]
    if "post" not in res:
        raise RuntimeError(f"Buffer rejected: {res.get('message', res)}")
    p = res["post"]
    return {"id": p["id"], "status": p["status"], "due": p.get("dueAt"), "via": "buffer", "media": url,
            "scheduling": p.get("schedulingType", sched)}


def post_status(post_id):
    return gql("""query($input: PostInput!) { post(input: $input) {
        id status dueAt sentAt externalLink error { message } } }""", {"input": {"id": post_id}})["post"]


def publish_story(media_url, is_video, text="", mode="addToQueue"):
    """Instagram story: a single image (jpg) or a short video. Stories do not show a caption."""
    asset = {"video": {"url": media_url}} if is_video else {"image": {"url": media_url}}
    inp = {"channelId": channel_for("instagram"), "text": text or "", "schedulingType": "automatic",
           "mode": mode, "needsApproval": False,
           "metadata": {"instagram": {"type": "story", "shouldShareToFeed": False}},
           "assets": [asset]}
    if mode == "customScheduled":
        inp["dueAt"] = _due_at()
    res = gql(CREATE, {"input": inp})["createPost"]
    if "post" not in res:
        raise RuntimeError(f"Buffer rejected: {res.get('message', res)}")
    p = res["post"]
    return {"id": p["id"], "status": p["status"], "due": p.get("dueAt"), "media": media_url}
