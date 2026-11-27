"""Background, phone mockup, camera, captions, tap effect, end card.
All frames are RGB uint8 numpy arrays (H, W, 3)."""
from functools import lru_cache

import cv2
import numpy as np
from PIL import Image, ImageDraw

from .brand import BRAND, icon_path
from .core import (ASSETS, BG, INK, W, H, YELLOW, SCREEN_W, SCREEN_H, font,
                   clamp01, ease_back, ease_out)


# ---------------- helpers ----------------
def paste_rgba(frame, rgba, x, y, opacity=1.0):
    """Paste an rgba (h,w,4) image onto frame with its top-left corner at (x,y)."""
    if opacity <= 0:
        return frame
    h, w = rgba.shape[:2]
    x, y = int(round(x)), int(round(y))
    fx0, fy0 = max(0, x), max(0, y)
    fx1, fy1 = min(frame.shape[1], x + w), min(frame.shape[0], y + h)
    if fx1 <= fx0 or fy1 <= fy0:
        return frame
    src = rgba[fy0 - y:fy1 - y, fx0 - x:fx1 - x]
    a = src[:, :, 3:4].astype(np.float32) / 255.0 * opacity
    roi = frame[fy0:fy1, fx0:fx1].astype(np.float32)
    frame[fy0:fy1, fx0:fx1] = (roi * (1 - a) + src[:, :, :3] * a).astype(np.uint8)
    return frame


def scale_rgba(rgba, s):
    if abs(s - 1) < 1e-3:
        return rgba
    h, w = rgba.shape[:2]
    nw, nh = max(1, int(w * s)), max(1, int(h * s))
    return cv2.resize(rgba, (nw, nh), interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)


def paste_center(frame, rgba, cx, cy, scale=1.0, opacity=1.0):
    im = scale_rgba(rgba, scale)
    h, w = im.shape[:2]
    return paste_rgba(frame, im, cx - w / 2, cy - h / 2, opacity)


def load_rgb(path):
    return np.array(Image.open(path).convert("RGB"))


def load_rgba(path):
    return np.array(Image.open(path).convert("RGBA"))


def rounded_mask(w, h, r, ss=3):
    im = Image.new("L", (w * ss, h * ss), 0)
    ImageDraw.Draw(im).rounded_rectangle([0, 0, w * ss - 1, h * ss - 1], r * ss, fill=255)
    return np.array(im.resize((w, h), Image.LANCZOS))


# ---------------- background ----------------
@lru_cache(maxsize=4)
def background(blobs=True):
    """Off-white background + soft colored blobs (colors from brand.json)."""
    bg = np.full((H, W, 3), BG, np.float32)
    if blobs:
        b1, b2, b3 = [tuple(c) for c in BRAND["background_blobs"]]
        for (cx, cy, r, col, a) in [(120, 260, 420, b1, 0.55),
                                    (980, 1650, 480, b2, 0.6),
                                    (1000, 420, 260, b3, 0.35)]:
            m = np.zeros((H, W), np.float32)
            cv2.circle(m, (cx, cy), r, 1.0, -1)
            m = cv2.GaussianBlur(m, (0, 0), r * 0.45)[..., None] * a
            bg = bg * (1 - m) + np.array(col, np.float32) * m
    return bg.astype(np.uint8)


def bg_frame():
    return background().copy()


# ---------------- phone + camera ----------------
class Phone:
    """Rounded body + shadow. The 935x1683 screen is passed in as a separate image."""
    BEZEL = 18
    R_OUT = 118

    def __init__(self):
        b = self.BEZEL
        self.w, self.h = SCREEN_W + 2 * b, SCREEN_H + 2 * b
        pad = 70
        self.pad = pad
        tw, th = self.w + 2 * pad, self.h + 2 * pad
        body = rounded_mask(self.w, self.h, self.R_OUT)
        self.screen_mask = rounded_mask(SCREEN_W, SCREEN_H, self.R_OUT - b).astype(np.float32) / 255
        tmpl = np.zeros((th, tw, 4), np.float32)
        # shadow
        sh = np.zeros((th, tw), np.float32)
        sh[pad + 26:pad + 26 + self.h, pad + 6:pad + 6 + self.w] = body / 255.0
        sh = cv2.GaussianBlur(sh, (0, 0), 26) * 0.28
        tmpl[..., 3] = sh * 255
        # body (dark ink)
        bm = body.astype(np.float32) / 255
        reg = tmpl[pad:pad + self.h, pad:pad + self.w]
        a = reg[..., 3:4] / 255
        col = np.array([38, 44, 40], np.float32)
        reg[..., :3] = col * bm[..., None] + reg[..., :3] * (1 - bm[..., None])
        reg[..., 3] = np.maximum(reg[..., 3], bm * 255)
        self.tmpl = tmpl

    def compose(self, screen_rgb):
        """Place the screen inside the body -> RGBA phone image."""
        t = self.tmpl.copy()
        b, p = self.BEZEL, self.pad
        reg = t[p + b:p + b + SCREEN_H, p + b:p + b + SCREEN_W]
        m = self.screen_mask[..., None]
        reg[..., :3] = screen_rgb.astype(np.float32) * m + reg[..., :3] * (1 - m)
        return t.astype(np.uint8)

    def draw(self, frame, screen_rgb, cx, cy, scale=1.0, angle=0.0, opacity=1.0):
        ph = self.compose(screen_rgb)
        h, w = ph.shape[:2]
        M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, scale)
        M[0, 2] += cx - w / 2
        M[1, 2] += cy - h / 2
        warped = cv2.warpAffine(ph, M, (W, H), flags=cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_CONSTANT, borderValue=(0, 0, 0, 0))
        return paste_rgba(frame, warped, 0, 0, opacity)

    def screen_to_frame(self, sx, sy, cx, cy, scale=1.0):
        """Convert a screen coordinate (0..935, 0..1683) to a frame coordinate (assumes angle=0)."""
        return (cx + (sx - SCREEN_W / 2) * scale, cy + (sy - SCREEN_H / 2) * scale)


class ScreenSource:
    """A screenshot fitted to a width of 935. Camera = zoom + center (in source coordinates).
    crop=(x0, y0, x1, y1): area to keep from the original image (e.g. to drop a phone frame or background)."""

    def __init__(self, path=None, crop_top=0, crop=None, image=None):
        im = image.convert("RGB") if image is not None else Image.open(path).convert("RGB")
        if crop:
            x0, y0, x1, y1 = [int(v) for v in crop]
        else:
            x0, y0, x1, y1 = 0, crop_top, im.width, im.height
        im = im.crop((x0, y0, x1, y1))
        s = SCREEN_W / im.width
        self.scale = s
        self.ox, self.oy = x0, y0
        self.crop_top = y0
        self.img = np.array(im.resize((SCREEN_W, int(im.height * s)), Image.LANCZOS))
        self.h = self.img.shape[0]

    def src(self, x, y):
        """Convert an original screenshot pixel to this source's coordinates."""
        return (x - self.ox) * self.scale, (y - self.oy) * self.scale

    def view(self, zoom, cx, cy):
        """Render a zoomed 935x1683 view with (cx,cy) at the center of the screen."""
        M = np.float32([[zoom, 0, SCREEN_W / 2 - cx * zoom],
                        [0, zoom, SCREEN_H / 2 - cy * zoom]])
        return cv2.warpAffine(self.img, M, (SCREEN_W, SCREEN_H), flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_CONSTANT, borderValue=BG)

    def to_screen(self, x, y, zoom, cx, cy):
        """Convert a source coordinate to a screen (935x1683) coordinate."""
        return (SCREEN_W / 2 + (x - cx) * zoom, SCREEN_H / 2 + (y - cy) * zoom)


# ---------------- captions ----------------
CAPTION_Y = 1290


@lru_cache(maxsize=64)
def caption_image(text, highlight="", size=66, max_w=900, plate=True, color=INK):
    """Draw the sentence as a centered, word-wrapped RGBA image. Highlighted word(s) get a yellow band."""
    f = font(size, "Bold")
    words = text.split()
    hl = set(highlight.split()) if highlight else set()
    hl_lower = [w.strip(".,!?:;'\"").lower() for w in hl]
    lines, cur = [], []
    for w_ in words:
        test = " ".join(cur + [w_])
        if cur and f.getlength(test) > max_w:
            lines.append(cur)
            cur = [w_]
        else:
            cur.append(w_)
    if cur:
        lines.append(cur)
    lh = int(size * 1.28)
    pad_x, pad_y = 34, 22
    tw = int(max(f.getlength(" ".join(l)) for l in lines))
    iw, ih = tw + 2 * pad_x, lh * len(lines) + 2 * pad_y
    ss = 2
    im = Image.new("RGBA", (iw * ss, ih * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    fs = font(size * ss, "Bold")
    if plate:
        d.rounded_rectangle([0, 0, iw * ss - 1, ih * ss - 1], 26 * ss, fill=(255, 255, 255, 205))
    space = fs.getlength(" ")
    for li, line in enumerate(lines):
        lw_ = fs.getlength(" ".join(line))
        x = (iw * ss - lw_) / 2
        y = (pad_y + li * lh) * ss
        for w_ in line:
            ww = fs.getlength(w_)
            if w_.strip(".,!?:;'\"").lower() in hl_lower:
                d.rectangle([x - 6 * ss, y + lh * ss * 0.48, x + ww + 6 * ss, y + lh * ss * 0.86],
                            fill=YELLOW + (235,))
            x += ww + space
        x = (iw * ss - lw_) / 2
        d.text((x, y), " ".join(line), font=fs, fill=color + (255,))
    im = im.resize((iw, ih), Image.LANCZOS)
    return np.array(im)


def draw_caption(frame, text, t, start, end, highlight="", y=CAPTION_Y, plate=True, fade=0.12):
    """The sentence appears at once (small pop) and fades out at the end."""
    if not (start <= t < end):
        return frame
    a_in = clamp01((t - start) / fade)
    a_out = clamp01((end - t) / fade)
    op = min(a_in, a_out)
    sc = 0.94 + 0.06 * ease_back(clamp01((t - start) / 0.22))
    im = caption_image(text, highlight, plate=plate)
    return paste_center(frame, im, W / 2, y, sc, op)


# ---------------- tap ----------------
def draw_tap(frame, x, y, t, start, dur=0.55):
    """Semi-transparent dot + expanding ring."""
    p = (t - start) / dur
    if p < 0 or p > 1:
        return frame
    ov = frame.copy()
    dot_a = 0.45 * (1 - clamp01((p - 0.5) / 0.5))
    r_dot = int(30 * (0.85 + 0.15 * ease_out(clamp01(p / 0.2))))
    cv2.circle(ov, (int(x), int(y)), r_dot, (90, 90, 90), -1, cv2.LINE_AA)
    frame[:] = cv2.addWeighted(ov, dot_a, frame, 1 - dot_a, 0)
    ov = frame.copy()
    r = int(30 + 70 * ease_out(p))
    ring_a = 0.6 * (1 - p)
    cv2.circle(ov, (int(x), int(y)), r, (70, 70, 70), 5, cv2.LINE_AA)
    frame[:] = cv2.addWeighted(ov, ring_a, frame, 1 - ring_a, 0)
    return frame


# ---------------- end card ----------------
@lru_cache(maxsize=2)
def _placeholder_icon(size):
    """Used when assets/app_icon.png is missing: rounded square with the app's first letter."""
    im = Image.new("RGBA", (size, size), tuple(BRAND["title_color"]) + (255,))
    d = ImageDraw.Draw(im)
    letter = (BRAND["app_name"] or "?")[0].upper()
    f = font(int(size * 0.55), "ExtraBold")
    d.text((size / 2, size / 2), letter, font=f, fill=(255, 255, 255, 255), anchor="mm")
    return im


def app_icon(size=300):
    p = icon_path()
    im = Image.open(p).convert("RGBA") if p else _placeholder_icon(size)
    im = im.resize((size, size), Image.LANCZOS)
    m = Image.fromarray(rounded_mask(size, size, int(size * 0.22)))
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(im, (0, 0), Image.fromarray(np.minimum(np.array(im)[..., 3], np.array(m))))
    # shadow
    pad = 40
    sh = np.zeros((size + 2 * pad, size + 2 * pad, 4), np.uint8)
    a = np.zeros(sh.shape[:2], np.float32)
    a[pad + 14:pad + 14 + size, pad:pad + size] = np.array(m) / 255
    sh[..., 3] = (cv2.GaussianBlur(a, (0, 0), 16) * 70).astype(np.uint8)
    o = np.array(out)
    res = sh.copy()
    oa = o[..., 3:4].astype(np.float32) / 255
    reg = res[pad:pad + size, pad:pad + size].astype(np.float32)
    reg[..., :3] = o[..., :3] * oa + reg[..., :3] * (1 - oa)
    reg[..., 3:4] = np.maximum(reg[..., 3:4], o[..., 3:4])
    res[pad:pad + size, pad:pad + size] = reg.astype(np.uint8)
    return res


@lru_cache(maxsize=8)
def title_image(text=None, size=104, color=None):
    text = BRAND["app_name"] if text is None else text
    color = tuple(BRAND["title_color"]) if color is None else color
    f = font(size * 2, "ExtraBold")
    tw = int(f.getlength(text))
    asc, desc = f.getmetrics()
    im = Image.new("RGBA", (tw + 60, asc + desc + 30), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    hgt = asc + desc
    d.rectangle([16, hgt * 0.52, tw + 44, hgt * 0.9], fill=YELLOW + (235,))
    d.text((30, 10), text, font=f, fill=color + (255,))
    return np.array(im.resize((im.width // 2, im.height // 2), Image.LANCZOS))


def draw_end_card(frame, t, start, subtitle="", sub_hl=""):
    """Logo + app name + subtitle line. The app logo closes every video."""
    if t < start:
        return frame
    lt = t - start
    ic = app_icon()
    s = 0.2 + 0.8 * ease_back(clamp01(lt / 0.5))
    paste_center(frame, ic, W / 2, 760, s, clamp01(lt / 0.2))
    ti = title_image()
    paste_center(frame, ti, W / 2, 1010 + 30 * (1 - ease_out(clamp01((lt - 0.25) / 0.4))),
                 1.0, clamp01((lt - 0.25) / 0.3))
    if subtitle:
        sub = caption_image(subtitle, sub_hl, size=52, plate=False, color=(80, 100, 130))
        paste_center(frame, sub, W / 2, 1140, 1.0, clamp01((lt - 0.55) / 0.3))
    return frame
