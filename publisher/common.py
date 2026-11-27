"""Shared: .env, token store, publishing state, post text, log, video checks."""
import datetime as dt
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPROVED = Path(os.environ.get("PUBLISH_DIR", ROOT / "approved"))
PUBDIR = ROOT / "publisher"
STATE = PUBDIR / "state.json"
TOKENS = PUBDIR / "tokens.json"
LOG = PUBDIR / "publish.log"
PLATFORMS = ("instagram", "youtube", "tiktok")


# ---------------- .env ----------------
def load_env():
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def env(key, default=None, required=False):
    v = os.environ.get(key, default)
    if required and not v:
        raise RuntimeError(f"{key} missing in .env")
    return v


def key_prefix():
    """Folder prefix for files on R2: R2_PREFIX in .env, else a slug of the app name from brand.json."""
    import re
    p = env("R2_PREFIX")
    if p:
        return p.strip("/")
    try:
        name = json.loads((ROOT / "brand.json").read_text(encoding="utf-8")).get("app_name", "")
    except (OSError, ValueError):
        name = ""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "promo-videos"


def enabled_platforms():
    raw = env("PUBLISH_PLATFORMS", ",".join(PLATFORMS))
    return [p.strip() for p in raw.split(",") if p.strip() in PLATFORMS]


# ---------------- json stores ----------------
def _read(p):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def _write(p, d):
    p.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")


def get_tokens(platform):
    return _read(TOKENS).get(platform, {})


def save_tokens(platform, data):
    d = _read(TOKENS)
    d[platform] = {**d.get(platform, {}), **data}
    _write(TOKENS, d)


def state():
    return _read(STATE)


def mark(video, platform, result):
    d = _read(STATE)
    d.setdefault(video_key(video), {"file": video.name})[platform] = {
        **result, "at": dt.datetime.now().isoformat(timespec="seconds")}
    _write(STATE, d)


def video_key(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return f"{path.name}:{h.hexdigest()[:12]}"


def log(msg):
    line = f"{dt.datetime.now().isoformat(timespec='seconds')}  {msg}"
    print(line)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ---------------- post text ----------------
def post_meta(video):
    """approved/<name>.post.json  >  videos/<name>/script.json["post"].  None if neither exists (not published)."""
    side = video.with_suffix(".post.json")
    if side.exists():
        return json.loads(side.read_text(encoding="utf-8"))
    sj = ROOT / "videos" / video.stem / "script.json"
    if sj.exists():
        return json.loads(sj.read_text(encoding="utf-8")).get("post")
    return None


def caption_for(meta, platform):
    """Platform-specific text if present, otherwise the shared caption + hashtags."""
    over = meta.get(platform, {})
    cap = over.get("caption", meta.get("caption", "")).strip()
    tags = over.get("hashtags", meta.get("hashtags", []))
    if platform == "tiktok":
        tags = tags[:5]  # TikTok/Buffer: at most 5 hashtags
    tag_str = " ".join(t if t.startswith("#") else f"#{t}" for t in tags)
    return (cap + ("\n\n" + tag_str if tag_str else "")).strip()


# ---------------- video checks ----------------
def probe(video):
    from promovideo.core import FFPROBE
    r = subprocess.run([FFPROBE, "-v", "error", "-show_entries",
                        "stream=codec_type,codec_name,width,height:format=duration",
                        "-of", "json", str(video)], capture_output=True, text=True, check=True)
    d = json.loads(r.stdout)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    return {"w": v["width"], "h": v["height"], "codec": v["codec_name"],
            "dur": float(d["format"]["duration"]),
            "audio": any(s["codec_type"] == "audio" for s in d["streams"]),
            "size": video.stat().st_size}


def check_video(video):
    p = probe(video)
    errs = []
    if p["codec"] != "h264":
        errs.append(f"codec {p['codec']} (must be h264)")
    if p["h"] <= p["w"]:
        errs.append("not vertical")
    if not 3 <= p["dur"] <= 180:
        errs.append(f"duration {p['dur']:.1f} s (must be 3-180 s; the Shorts limit is 3 min)")
    if not p["audio"]:
        errs.append("no audio")
    return p, errs
