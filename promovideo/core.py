"""Shared constants, paths, easing functions and font loading."""
import os
import shutil
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FONTS = ASSETS / "fonts"

W, H, FPS = 1080, 1920, 30
BG = (245, 246, 244)          # cool off-white background (RGB)
INK = (30, 32, 30)            # ink
YELLOW = (240, 214, 90)       # highlight band
ACCENTS = {
    "pink": (232, 170, 165),
    "yellow": (240, 200, 80),
    "blue": (140, 180, 215),
    "green": (140, 185, 140),
    "purple": (195, 160, 225),
    "red": (200, 70, 60),
}

SCREEN_W, SCREEN_H = 935, 1683  # phone screen size


def find_bin(name):
    p = shutil.which(name)
    if p:
        return p
    cand = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft/WinGet/Links" / f"{name}.exe"
    if cand.exists():
        return str(cand)
    raise FileNotFoundError(f"{name} not found (install ffmpeg and make sure it is on PATH)")


FFMPEG = find_bin("ffmpeg")
FFPROBE = find_bin("ffprobe")


@lru_cache(maxsize=64)
def font(size, weight="Bold"):
    p = FONTS / f"Poppins-{weight}.ttf"
    if not p.exists():
        raise FileNotFoundError(f"font missing: {p}. Download Poppins (Regular, SemiBold, Bold, ExtraBold) "
                                "from https://fonts.google.com/specimen/Poppins into assets/fonts/")
    return ImageFont.truetype(str(p), size)


# ---------- easing ----------
def clamp01(x):
    return max(0.0, min(1.0, float(x)))


def prog(t, start, dur):
    """Progress (0..1) of t inside [start, start+dur]."""
    if dur <= 0:
        return 1.0 if t >= start else 0.0
    return clamp01((t - start) / dur)


def ease_in_out(x):
    x = clamp01(x)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def ease_out(x):
    x = clamp01(x)
    return 1 - (1 - x) ** 3


def ease_back(x, s=1.70158):
    x = clamp01(x)
    c3 = s + 1
    return 1 + c3 * (x - 1) ** 3 + s * (x - 1) ** 2


def lerp(a, b, x):
    return a + (b - a) * x


def rng(seed):
    return np.random.default_rng(seed)
