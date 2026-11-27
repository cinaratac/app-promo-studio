"""Doodle library: small hand-drawn motifs to place inside screenshot regions (cells, cards, canvases).

Each motif returns a list of strokes defined in a unit box (0..1): [(points, color_name, width_multiplier)].
draw_motif() places them into a Doodle at a given box and time (live stroke-by-stroke drawing or static).
Add your own motif by defining a new m_<name>() function; it is picked up automatically.
"""
import math

import numpy as np

from .core import ACCENTS, INK

COL = {**ACCENTS, "ink": INK, "orange": (230, 140, 60), "brown": (150, 100, 60), "dgreen": (60, 120, 80),
       "sky": (100, 160, 215), "grey": (130, 130, 130)}


# ---------------- primitives (unit box) ----------------
def arc(cx, cy, rx, ry, a0=0, a1=360, n=40):
    a = np.radians(np.linspace(a0, a1, n))
    return np.stack([cx + rx * np.cos(a), cy + ry * np.sin(a)], 1)


def circ(cx, cy, r, n=40):
    return arc(cx, cy, r, r, -100, 268, n)


def seg(*pts):
    return np.array(pts, dtype=float)


def zig(x0, x1, y, amp, n):
    xs = np.linspace(x0, x1, n * 2 + 1)
    ys = [y + (amp if i % 2 else -amp) for i in range(len(xs))]
    return np.stack([xs, ys], 1)


# ---------------- motifs ----------------
def m_sun():
    s = [(circ(.5, .5, .18), "yellow", 1.2)]
    for k in range(8):
        a = math.radians(k * 45)
        s.append((seg((.5 + .26 * math.cos(a), .5 + .26 * math.sin(a)), (.5 + .38 * math.cos(a), .5 + .38 * math.sin(a))), "orange", 1))
    return s


def m_cloud_rain():
    c = np.concatenate([arc(.3, .42, .14, .12, 90, 270), arc(.45, .3, .16, .14, 180, 360), arc(.65, .38, .14, .13, 230, 450),
                        seg((.72, .5), (.28, .54))])
    s = [(c, "ink", 1)]
    for x in (.32, .48, .64):
        s.append((seg((x, .64), (x - .05, .8)), "blue", 1))
    return s


def m_snowflake():
    s = []
    for k in range(3):
        a = math.radians(k * 60)
        s.append((seg((.5 - .36 * math.cos(a), .5 - .36 * math.sin(a)), (.5 + .36 * math.cos(a), .5 + .36 * math.sin(a))), "sky", 1))
    s.append((circ(.5, .5, .06), "sky", 1))
    return s


def m_snowman():
    return [(circ(.5, .66, .2), "ink", 1), (circ(.5, .34, .14), "ink", 1),
            (seg((.5, .34), (.62, .37)), "orange", 1.2), (seg((.44, .3), (.45, .31)), "ink", 1.6),
            (seg((.54, .3), (.55, .31)), "ink", 1.6), (seg((.36, .46), (.64, .46)), "red", 1.3)]


def m_tree():
    return [(seg((.5, .12), (.25, .45), (.38, .45), (.18, .75), (.82, .75), (.62, .45), (.75, .45), (.5, .12)), "dgreen", 1.1),
            (seg((.46, .75), (.46, .88), (.54, .88), (.54, .75)), "brown", 1),
            (circ(.4, .55, .03), "red", 1.4), (circ(.6, .62, .03), "yellow", 1.4), (circ(.5, .38, .03), "red", 1.4)]


def m_heart():
    h = np.concatenate([arc(.36, .38, .16, .15, 180, 360), arc(.64, .38, .16, .15, 180, 360), seg((.8, .42), (.5, .82), (.2, .42))])
    return [(h, "red", 1.2)]


def m_star():
    p = [(.5 + .38 * math.cos(math.radians(-90 + k * 144)), .52 + .38 * math.sin(math.radians(-90 + k * 144))) for k in range(6)]
    return [(np.array(p), "yellow", 1.2)]


def m_moon():
    return [(np.concatenate([arc(.5, .5, .32, .32, 70, 290), arc(.62, .5, .26, .3, 250, 110, 30)]), "yellow", 1.1)]


def m_coffee():
    return [(seg((.25, .35), (.3, .82), (.66, .82), (.71, .35), (.25, .35)), "brown", 1.1),
            (arc(.74, .56, .1, .12, -90, 90), "brown", 1), (seg((.38, .12), (.42, .2), (.38, .28)), "grey", .8),
            (seg((.52, .12), (.56, .2), (.52, .28)), "grey", .8)]


def m_book():
    return [(seg((.5, .25), (.15, .2), (.15, .8), (.5, .85), (.85, .8), (.85, .2), (.5, .25), (.5, .85)), "blue", 1.1),
            (seg((.24, .38), (.42, .4)), "ink", .7), (seg((.24, .52), (.42, .54)), "ink", .7),
            (seg((.58, .4), (.76, .38)), "ink", .7), (seg((.58, .54), (.76, .52)), "ink", .7)]


def m_laptop():
    return [(seg((.22, .22), (.78, .22), (.78, .62), (.22, .62), (.22, .22)), "ink", 1),
            (seg((.12, .72), (.88, .72), (.82, .62), (.18, .62), (.12, .72)), "ink", 1),
            (seg((.32, .34), (.6, .34)), "blue", .8), (seg((.32, .46), (.5, .46)), "blue", .8)]


def m_bus():
    return [(seg((.12, .3), (.88, .3), (.88, .72), (.12, .72), (.12, .3)), "yellow", 1.1),
            (seg((.2, .38), (.36, .38), (.36, .52), (.2, .52), (.2, .38)), "ink", .8),
            (seg((.44, .38), (.6, .38), (.6, .52), (.44, .52), (.44, .38)), "ink", .8),
            (seg((.68, .38), (.8, .38), (.8, .52), (.68, .52), (.68, .38)), "ink", .8),
            (circ(.28, .74, .07), "ink", 1.1), (circ(.72, .74, .07), "ink", 1.1)]


def m_cat():
    head = np.concatenate([seg((.24, .42), (.28, .16), (.42, .3), (.58, .3), (.72, .16), (.76, .42)),
                           arc(.5, .45, .27, .3, 0, 180)])
    return [(head, "ink", 1), (seg((.38, .48), (.4, .5)), "ink", 1.6), (seg((.6, .48), (.62, .5)), "ink", 1.6),
            (seg((.47, .58), (.5, .62), (.53, .58)), "pink", 1), (seg((.18, .6), (.38, .62)), "ink", .6),
            (seg((.62, .62), (.82, .6)), "ink", .6)]


def m_dog():
    return [(circ(.5, .52, .26), "brown", 1), (arc(.24, .42, .08, .18, 90, 270), "brown", 1.1),
            (arc(.76, .42, .08, .18, -90, 90), "brown", 1.1), (seg((.42, .46), (.43, .48)), "ink", 1.6),
            (seg((.58, .46), (.59, .48)), "ink", 1.6), (circ(.5, .6, .04), "ink", 1.3),
            (seg((.5, .64), (.5, .7)), "ink", .8)]


def m_flower():
    s = [(seg((.5, .55), (.5, .9)), "dgreen", 1.1), (arc(.62, .76, .1, .05, 180, 360), "dgreen", 1)]
    for k in range(5):
        a = math.radians(k * 72)
        s.append((circ(.5 + .14 * math.cos(a), .38 + .14 * math.sin(a), .09), "pink", 1))
    s.append((circ(.5, .38, .06), "yellow", 1.2))
    return s


def m_plant():
    return [(seg((.3, .58), (.35, .88), (.65, .88), (.7, .58), (.3, .58)), "orange", 1.1),
            (seg((.5, .58), (.5, .3)), "dgreen", 1), (arc(.38, .34, .12, .07, 0, 360), "green", 1),
            (arc(.62, .26, .12, .07, 0, 360), "green", 1), (arc(.4, .48, .1, .05, 0, 360), "green", 1)]


def m_music():
    return [(seg((.36, .72), (.36, .22), (.72, .14), (.72, .64)), "purple", 1.1),
            (circ(.28, .74, .08), "purple", 1.2), (circ(.64, .66, .08), "purple", 1.2)]


def m_pizza():
    return [(seg((.5, .85), (.15, .25), (.85, .25), (.5, .85)), "orange", 1.1), (arc(.5, .18, .36, .1, 180, 360), "brown", 1.1),
            (circ(.42, .38, .05), "red", 1.2), (circ(.58, .42, .05), "red", 1.2), (circ(.5, .58, .05), "red", 1.2)]


def m_cake():
    return [(seg((.18, .5), (.82, .5), (.82, .85), (.18, .85), (.18, .5)), "pink", 1.1), (zig(.18, .82, .6, .04, 6), "ink", .7),
            (seg((.5, .5), (.5, .3)), "blue", 1), (seg((.5, .24), (.52, .18), (.48, .14)), "orange", 1)]


def m_gift():
    return [(seg((.18, .4), (.82, .4), (.82, .85), (.18, .85), (.18, .4)), "red", 1.1), (seg((.5, .4), (.5, .85)), "yellow", 1.2),
            (seg((.18, .58), (.82, .58)), "yellow", 1.2), (arc(.4, .32, .1, .07, 0, 360), "yellow", 1),
            (arc(.6, .32, .1, .07, 0, 360), "yellow", 1)]


def m_happy():
    return [(circ(.5, .5, .34), "ink", 1), (seg((.38, .42), (.39, .44)), "ink", 1.8), (seg((.61, .42), (.62, .44)), "ink", 1.8),
            (arc(.5, .52, .18, .14, 20, 160), "ink", 1)]


def m_sad():
    return [(circ(.5, .5, .34), "ink", 1), (seg((.38, .42), (.39, .44)), "ink", 1.8), (seg((.61, .42), (.62, .44)), "ink", 1.8),
            (arc(.5, .74, .16, .1, 200, 340), "ink", 1), (seg((.36, .5), (.34, .6)), "blue", 1)]


def m_sleepy():
    return [(circ(.42, .56, .28), "ink", 1), (arc(.33, .52, .06, .03, 0, 180), "ink", 1), (arc(.51, .52, .06, .03, 0, 180), "ink", 1),
            (seg((.66, .14), (.8, .14), (.66, .3), (.8, .3)), "purple", .9), (seg((.82, .36), (.9, .36), (.82, .45), (.9, .45)), "purple", .7)]


def m_house():
    return [(seg((.2, .5), (.5, .2), (.8, .5)), "red", 1.1), (seg((.26, .46), (.26, .85), (.74, .85), (.74, .46)), "ink", 1),
            (seg((.44, .85), (.44, .64), (.56, .64), (.56, .85)), "brown", 1), (seg((.32, .54), (.4, .54), (.4, .62), (.32, .62), (.32, .54)), "blue", .8)]


def m_balloon():
    return [(circ(.5, .38, .24), "red", 1.1), (seg((.5, .62), (.47, .72), (.53, .8), (.49, .9)), "ink", .7)]


def m_icecream():
    return [(seg((.32, .45), (.5, .9), (.68, .45)), "orange", 1.1), (arc(.5, .4, .2, .17, 180, 360), "pink", 1.1),
            (seg((.3, .45), (.7, .45)), "pink", 1.1), (circ(.5, .18, .04), "red", 1.2)]


def m_umbrella():
    return [(np.concatenate([arc(.5, .45, .36, .3, 180, 360), zig(.86, .14, .45, .03, 4)]), "purple", 1.1),
            (seg((.5, .45), (.5, .82), (.44, .86), (.4, .8)), "ink", 1)]


def m_camera():
    return [(seg((.14, .32), (.86, .32), (.86, .78), (.14, .78), (.14, .32)), "ink", 1), (circ(.5, .55, .14), "ink", 1),
            (seg((.36, .32), (.42, .22), (.58, .22), (.64, .32)), "ink", 1), (seg((.74, .4), (.78, .4)), "red", 1.5)]


def m_headphones():
    return [(arc(.5, .52, .3, .32, 180, 360), "ink", 1.1), (seg((.16, .5), (.28, .5), (.28, .78), (.16, .78), (.16, .5)), "blue", 1.1),
            (seg((.72, .5), (.84, .5), (.84, .78), (.72, .78), (.72, .5)), "blue", 1.1)]


def m_apple():
    return [(np.concatenate([arc(.5, .58, .3, .28, -80, 260)]), "red", 1.1), (seg((.5, .3), (.52, .16)), "brown", 1),
            (arc(.62, .2, .08, .04, 0, 360), "green", 1)]


def m_dumbbell():
    return [(seg((.28, .5), (.72, .5)), "ink", 1.2), (seg((.18, .34), (.28, .34), (.28, .66), (.18, .66), (.18, .34)), "grey", 1.1),
            (seg((.72, .34), (.82, .34), (.82, .66), (.72, .66), (.72, .34)), "grey", 1.1)]


def m_plane():
    return [(seg((.1, .6), (.9, .3)), "sky", 1.1), (seg((.42, .5), (.38, .2), (.58, .43)), "sky", 1),
            (seg((.5, .46), (.62, .76), (.66, .4)), "sky", 1), (zig(.08, .3, .78, .02, 4), "grey", .6)]


def m_leaf():
    return [(np.concatenate([arc(.5, .5, .32, .18, 180, 360), arc(.5, .5, .32, .18, 0, 180)]), "orange", 1.1),
            (seg((.18, .5), (.86, .5)), "brown", .8)]


def m_dots():
    return [(seg((.3, .55), (.31, .56)), "ink", 2), (seg((.5, .55), (.51, .56)), "ink", 2), (seg((.7, .55), (.71, .56)), "ink", 2)]


MOTIFS = {k[2:]: v for k, v in globals().items() if k.startswith("m_") and callable(v)}

THEMES = {
    "daily": ["coffee", "book", "laptop", "bus", "cat", "dog", "plant", "music", "pizza", "happy", "sleepy", "house",
               "headphones", "camera", "apple", "dumbbell", "cloud_rain", "sun", "heart", "flower"],
    "winter": ["snowflake", "snowman", "tree", "coffee", "gift", "moon", "star", "book", "heart", "cloud_rain", "sleepy", "cake"],
    "summer": ["sun", "icecream", "flower", "balloon", "camera", "happy", "music", "apple", "umbrella"],
    "emotions": ["happy", "sad", "sleepy", "heart", "star", "sun", "cloud_rain", "dots"],
    "autumn": ["leaf", "umbrella", "cloud_rain", "coffee", "book", "headphones", "moon", "apple", "cat", "plant"],
}
THEMES["mixed"] = sorted(set(sum(THEMES.values(), [])) - {"dots"})


def choose(n, theme="mixed", seed=0, avoid=()):
    pool = [m for m in THEMES.get(theme, THEMES["mixed"]) if m not in avoid] or list(MOTIFS)
    rng = np.random.default_rng(seed)
    out = []
    while len(out) < n:
        rng.shuffle(pool)
        out += [m for m in pool if not out or m != out[-1]]
    return out[:n]


def draw_motif(d, name, box, t0=0.0, dur=0.0, seed=0, width=6.0, map_pt=None):
    """Add a motif to a Doodle. box=(x0,y0,x1,y1) in target coordinates; centered in a square box.
    If dur>0 the strokes are drawn one after another (live drawing)."""
    rng = np.random.default_rng(seed)
    x0, y0, x1, y1 = box
    side = min(x1 - x0, y1 - y0) * rng.uniform(0.82, 0.96)
    cx, cy = (x0 + x1) / 2 + rng.uniform(-.05, .05) * (x1 - x0), (y0 + y1) / 2 + rng.uniform(-.04, .04) * (y1 - y0)
    rot = math.radians(rng.uniform(-9, 9))
    cr, sr = math.cos(rot), math.sin(rot)
    strokes = MOTIFS[name]()
    lens = [max(1e-3, np.linalg.norm(np.diff(p, axis=0), axis=1).sum()) for p, _, _ in strokes]
    tot = sum(lens)
    t = t0
    for (p, col, wm), L in zip(strokes, lens):
        q = (p - .5) * side
        q = np.stack([q[:, 0] * cr - q[:, 1] * sr + cx, q[:, 0] * sr + q[:, 1] * cr + cy], 1)
        if map_pt:
            q = np.array([map_pt(x, y) for x, y in q])
        sd = dur * L / tot if dur > 0 else 0.0
        d.line(q, t, sd, color=COL.get(col, INK), width=max(2.0, width * wm), jitter=max(.6, width * .2),
               seed=int(rng.integers(1 << 30)))
        t += sd
    return t
