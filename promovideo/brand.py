"""Brand settings loaded from brand.json in the project root (app name, colors, end card, voice, story screens).

Edit brand.json to make the videos yours; nothing brand-specific is hard-coded in the engine.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRAND_FILE = ROOT / "brand.json"

DEFAULTS = {
    "app_name": "My App",
    "icon": "assets/app_icon.png",
    "title_color": [45, 70, 50],
    "background_blobs": [[238, 205, 196], [205, 228, 200], [214, 230, 214]],
    "end_card": {"subtitle": "Now on the App Store.", "highlight": "App Store."},
    "language": "en-US",
    "voice": {"provider": "google-tts", "model": "gemini-3.8-flash-lite-tts", "voice": "Kore", "speed": 1.1,
              "instructions": "Cheerful and warm, like telling a friend."},
    "story_screens": {},
    "post_emojis": "",
}


def _load():
    data = json.loads(BRAND_FILE.read_text(encoding="utf-8")) if BRAND_FILE.exists() else {}
    out = {**DEFAULTS, **{k: v for k, v in data.items() if not k.startswith("_")}}
    for k in ("end_card", "voice"):
        out[k] = {**DEFAULTS[k], **(data.get(k) or {})}
    return out


BRAND = _load()


def icon_path():
    p = ROOT / BRAND["icon"] if BRAND.get("icon") else None
    return p if p and p.exists() else None
