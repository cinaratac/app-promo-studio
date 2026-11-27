"""Hand-drawn style: 'strokes' that progress over time, slightly wobbly thick ink,
hatched fills. The drawing layer is 2x supersampled and downscaled."""
import math

import cv2
import numpy as np

from .core import INK, rng, clamp01, ease_out

SS = 2  # supersampling factor


def _jitter(pts, amp, seed):
    """Slightly wobble the points (smooth, low-frequency offset)."""
    pts = np.asarray(pts, dtype=np.float64)
    if amp <= 0 or len(pts) < 2:
        return pts
    r = rng(seed)
    n = len(pts)
    k = max(2, n // 6)
    ctrl = r.normal(0, amp, size=(k, 2))
    xs = np.linspace(0, 1, k)
    xi = np.linspace(0, 1, n)
    off = np.stack([np.interp(xi, xs, ctrl[:, 0]), np.interp(xi, xs, ctrl[:, 1])], 1)
    return pts + off


def _resample(pts, step=4.0):
    pts = np.asarray(pts, dtype=np.float64)
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    L = np.concatenate([[0], np.cumsum(seg)])
    if L[-1] == 0:
        return pts
    n = max(2, int(L[-1] / step))
    s = np.linspace(0, L[-1], n)
    return np.stack([np.interp(s, L, pts[:, 0]), np.interp(s, L, pts[:, 1])], 1)


class Stroke:
    def __init__(self, pts, start, dur, color=INK, width=9, jitter=2.0, seed=0, alpha=1.0):
        p = _resample(pts)
        self.pts = _jitter(p, jitter, seed)
        seg = np.linalg.norm(np.diff(self.pts, axis=0), axis=1)
        self.cum = np.concatenate([[0], np.cumsum(seg)])
        self.start, self.dur = start, dur
        self.color, self.width, self.alpha = color, width, alpha

    def partial(self, t):
        p = ease_out(clamp01((t - self.start) / self.dur)) if self.dur > 0 else float(t >= self.start)
        if p <= 0:
            return None
        if p >= 1:
            return self.pts
        L = self.cum[-1] * p
        k = int(np.searchsorted(self.cum, L))
        return self.pts[: max(2, k + 1)]

    def bbox(self):
        m = self.width + 4
        return (self.pts[:, 0].min() - m, self.pts[:, 1].min() - m,
                self.pts[:, 0].max() + m, self.pts[:, 1].max() + m)


class Doodle:
    """A group of strokes. Add strokes -> render(frame, t)."""

    def __init__(self):
        self.strokes = []
        self._seed = 0

    def _s(self):
        self._seed += 1
        return self._seed * 7919

    def line(self, pts, start, dur, **kw):
        kw.setdefault("seed", self._s())
        self.strokes.append(Stroke(pts, start, dur, **kw))
        return self

    def circle(self, cx, cy, rx, ry, start, dur, turns=1.12, **kw):
        """Hand-drawn loop whose end overshoots slightly."""
        n = 90
        a0 = -math.pi * 0.6
        a = np.linspace(a0, a0 + 2 * math.pi * turns, n)
        grow = np.linspace(1.0, 1.06, n)
        pts = np.stack([cx + rx * grow * np.cos(a), cy + ry * grow * np.sin(a)], 1)
        kw.setdefault("jitter", 3.0)
        return self.line(pts, start, dur, **kw)

    def underline(self, x0, x1, y, start, dur, wave=4, **kw):
        xs = np.linspace(x0, x1, 40)
        ys = y + wave * np.sin(np.linspace(0, 2.2 * math.pi, 40))
        return self.line(np.stack([xs, ys], 1), start, dur, **kw)

    def arrow(self, x0, y0, x1, y1, start, dur, bend=0.25, head=34, **kw):
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        nx, ny = -(y1 - y0) * bend, (x1 - x0) * bend
        tt = np.linspace(0, 1, 40)[:, None]
        p0, p1, c = np.array([x0, y0]), np.array([x1, y1]), np.array([mx + nx, my + ny])
        pts = (1 - tt) ** 2 * p0 + 2 * (1 - tt) * tt * c + tt ** 2 * p1
        self.line(pts, start, dur * 0.75, **kw)
        d = pts[-1] - pts[-4]
        ang = math.atan2(d[1], d[0])
        for s in (+1, -1):
            a = ang + math.pi + s * 0.5
            self.line([p1, p1 + head * np.array([math.cos(a), math.sin(a)])],
                      start + dur * 0.72, dur * 0.28, **kw)
        return self

    def scribble(self, x0, y0, x1, y1, start, dur, gap=16, angle=-0.6, **kw):
        """Fill a rectangle with hatching (zigzag)."""
        w, h = x1 - x0, y1 - y0
        ca, sa = math.cos(angle), math.sin(angle)
        diag = math.hypot(w, h)
        pts = []
        k = 0
        for off in np.arange(-diag / 2, diag / 2, gap):
            a = np.array([off * -sa - diag * ca, off * ca - diag * sa]) + [x0 + w / 2, y0 + h / 2]
            b = np.array([off * -sa + diag * ca, off * ca + diag * sa]) + [x0 + w / 2, y0 + h / 2]
            seg = _clip_seg(a, b, x0, y0, x1, y1)
            if seg is None:
                continue
            pts.extend(seg if k % 2 == 0 else seg[::-1])
            k += 1
        if len(pts) >= 2:
            kw.setdefault("width", 7)
            kw.setdefault("jitter", 1.5)
            self.line(pts, start, dur, **kw)
        return self

    def sparkle(self, cx, cy, r, start, dur, **kw):
        for i, a in enumerate((0, math.pi / 2, math.pi / 4, 3 * math.pi / 4)):
            rr = r if i < 2 else r * 0.55
            self.line([(cx - rr * math.cos(a), cy - rr * math.sin(a)),
                       (cx + rr * math.cos(a), cy + rr * math.sin(a))],
                      start + i * dur * 0.15, dur * 0.4, **kw)
        return self

    # ---------- drawing ----------
    def render(self, frame, t, offset=(0, 0), opacity=1.0, scale=1.0):
        """scale: scales point coordinates (line width stays fixed) -> p*scale + offset."""
        live = [(s, s.partial(t)) for s in self.strokes]
        live = [(s, p * scale) for s, p in live if p is not None]
        if not live or opacity <= 0:
            return frame
        bx = []
        for s, p in live:
            m = s.width + 4
            bx.append((p[:, 0].min() - m, p[:, 1].min() - m, p[:, 0].max() + m, p[:, 1].max() + m))
        ox, oy = offset
        x0 = int(max(0, min(b[0] for b in bx) + ox))
        y0 = int(max(0, min(b[1] for b in bx) + oy))
        x1 = int(min(frame.shape[1], max(b[2] for b in bx) + ox + 1))
        y1 = int(min(frame.shape[0], max(b[3] for b in bx) + oy + 1))
        if x1 <= x0 or y1 <= y0:
            return frame
        lw, lh = (x1 - x0) * SS, (y1 - y0) * SS
        layer = np.zeros((lh, lw, 4), np.uint8)
        for s, p in live:
            q = ((p + [ox - x0, oy - y0]) * SS * 16).astype(np.int32)  # 4-bit subpixel
            c = s.color
            cv2.polylines(layer, [q.reshape(-1, 1, 2)], False,
                          (c[0], c[1], c[2], int(255 * s.alpha)),
                          thickness=int(s.width * SS), lineType=cv2.LINE_AA, shift=4)
            r = int(s.width * SS / 2)
            for e in (q[0], q[-1]):
                cv2.circle(layer, (int(e[0]) >> 4, int(e[1]) >> 4), r,
                           (c[0], c[1], c[2], int(255 * s.alpha)), -1, cv2.LINE_AA)
        small = cv2.resize(layer, (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA)
        a = small[:, :, 3:4].astype(np.float32) / 255.0 * opacity
        roi = frame[y0:y1, x0:x1].astype(np.float32)
        frame[y0:y1, x0:x1] = (roi * (1 - a) + small[:, :, :3].astype(np.float32) * a).astype(np.uint8)
        return frame


def _clip_seg(a, b, x0, y0, x1, y1):
    """Liang-Barsky: clip segment a-b to a rectangle."""
    dx, dy = b - a
    p = [-dx, dx, -dy, dy]
    q = [a[0] - x0, x1 - a[0], a[1] - y0, y1 - a[1]]
    u0, u1 = 0.0, 1.0
    for pi, qi in zip(p, q):
        if pi == 0:
            if qi < 0:
                return None
            continue
        u = qi / pi
        if pi < 0:
            u0 = max(u0, u)
        else:
            u1 = min(u1, u)
    if u0 > u1:
        return None
    return [a + u0 * (b - a), a + u1 * (b - a)]
