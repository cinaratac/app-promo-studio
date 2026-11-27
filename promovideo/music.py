"""Background music: your own tracks in assets/music (wav, 48 kHz recommended).

Put royalty-free tracks you have the rights to into assets/music/ and optionally describe them in
assets/music/music.json so the panel and the scenario writer can pick fitting ones:

{
  "calm_piano": {"title": "Calm piano", "description": "Soft and warm, for nostalgic topics"}
}

A scenario's "music" field may be a track name (file name without extension), "auto" (a random
track, stable per scenario) or "none".
"""
import json
import zlib

from .core import ASSETS

MUSIC_DIR = ASSETS / "music"
EXTS = (".wav",)


def tracks():
    """{name: {"title", "description"}} for every audio file in assets/music."""
    meta = {}
    mj = MUSIC_DIR / "music.json"
    if mj.exists():
        meta = json.loads(mj.read_text(encoding="utf-8"))
    out = {}
    for p in sorted(MUSIC_DIR.glob("*")):
        if p.suffix.lower() in EXTS:
            out[p.stem] = {"title": p.stem.replace("_", " ").capitalize(), "description": "", **meta.get(p.stem, {})}
    return out


def path(name):
    for ext in EXTS:
        p = MUSIC_DIR / f"{name}{ext}"
        if p.exists():
            return p
    raise FileNotFoundError(f"music track not found: {name} (put {name}.wav in assets/music)")


def resolve(choice, seed=""):
    """'auto' -> a track picked deterministically from seed; 'none'/None/missing tracks -> None."""
    names = list(tracks())
    if choice in (None, "", "none") or not names:
        return None
    if choice == "auto":
        return names[zlib.crc32(str(seed).encode()) % len(names)]
    return choice if choice in names else None
