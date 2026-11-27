"""Drawing regions inside your real screenshots: their contents are cleared and refilled with new doodles.

The UI (titles, day numbers, buttons) stays exactly as in the real screenshot; only the inside of
the regions changes. This way every video can show different content without faking the interface.

Regions are defined per screenshot in assets/screenshots/regions.json:

{
  "month.png": {
    "grid": {"xs": [5, 138, 273, 406, 540, 673, 807, 940], "ys": [970, 1105, 1238, 1372, 1506, 1640],
             "count": 31, "start": 3, "id": "d{n}", "pad": [3, 40, 3, 3], "draw_pad": [10, 34, 10, 8]}
  },
  "editor.png": {
    "paper": {"clear": [[32, 300, 414, 670]], "draw": [70, 330, 380, 640]}
  }
}

- A cell: "clear" = list of rectangles painted with the paper color, "draw" = box the motif is drawn into,
  optional "label" = rectangle checked for old ink spilling over (such cells are left untouched).
- "grid" generates calendar-like cells: column edges xs, row edges ys, `count` cells starting at
  slot `start` (e.g. weekday of the 1st), ids built from the "id" pattern ({n} = 1..count).
- If regions.json is missing or a screenshot is not listed, fill/drawing simply cannot be used on it.

Preview a definition:  python -m promovideo.regions month.png '{"seed": 3}' preview.png
"""
import json
from functools import lru_cache

import numpy as np
from PIL import Image

from .core import ASSETS
from .doodle import Doodle
from . import doodlelib as L

SHOTS = ASSETS / "screenshots"
REGIONS_FILE = SHOTS / "regions.json"


def _grid(g):
    xs, ys = g["xs"], g["ys"]
    cols = len(xs) - 1
    px0, py0, px1, py1 = g.get("pad", [3, 3, 3, 3])
    dx0, dy0, dx1, dy1 = g.get("draw_pad", [10, 10, 10, 10])
    lab = g.get("label")   # [w, h] label box at the top-left of each cell, optional
    cells = {}
    for n in range(1, int(g.get("count", cols * (len(ys) - 1))) + 1):
        r, c = divmod(n - 1 + int(g.get("start", 0)), cols)
        if r + 1 >= len(ys):
            break
        x0, x1, y0, y1 = xs[c], xs[c + 1], ys[r], ys[r + 1]
        cell = {"clear": [(x0 + px0, y0 + py0, x1 - px1, y1 - py1)],
                "draw": (x0 + dx0, y0 + dy0, x1 - dx1, y1 - dy1)}
        if lab:
            cell["label"] = (x0 + 3, y0 + 3, x0 + lab[0], y0 + lab[1])
        cells[g.get("id", "c{n}").format(n=n)] = cell
    return cells


@lru_cache(maxsize=1)
def _load(mtime):
    if not REGIONS_FILE.exists():
        return {}
    raw = json.loads(REGIONS_FILE.read_text(encoding="utf-8"))
    out = {}
    for screen, spec in raw.items():
        if screen.startswith("_"):
            continue
        cells = {}
        if "grid" in spec:
            cells.update(_grid(spec["grid"]))
        for cid, c in spec.items():
            if cid == "grid":
                continue
            cells[cid] = {"clear": [tuple(r) for r in c["clear"]], "draw": tuple(c["draw"]),
                          **({"label": tuple(c["label"])} if c.get("label") else {})}
        out[screen] = cells
    return out


def regions():
    return _load(REGIONS_FILE.stat().st_mtime if REGIONS_FILE.exists() else 0)


def has(screen):
    return screen in regions()


def cell(screen, cid):
    try:
        return regions()[screen][cid]
    except KeyError:
        raise KeyError(f"no region '{cid}' on {screen}. Available: {sorted(regions().get(screen, {}))}")


def _paper(arr, rect):
    x0, y0, x1, y1 = [int(v) for v in rect]
    reg = arr[y0:y1, x0:x1].reshape(-1, 3)
    lum = reg.mean(1)
    light = reg[lum > np.percentile(lum, 60)]
    return np.median(light if len(light) else reg, 0).astype(np.uint8)


def _ink_ratio(arr, rect, paper):
    x0, y0, x1, y1 = [int(v) for v in rect]
    reg = arr[y0:y1, x0:x1].astype(np.int16)
    return float((np.abs(reg - paper.astype(np.int16)).sum(2) > 90).mean())


def dirty_cells(screen, arr=None):
    """Cells whose label area (day number/title) has old ink spilling over: these are not cleared, they stay as is."""
    regs = regions()[screen]
    if arr is None:
        arr = np.array(Image.open(SHOTS / screen).convert("RGB"))
    ratios = {}
    for cid, c in regs.items():
        if "label" in c:
            ratios[cid] = _ink_ratio(arr, c["label"], _paper(arr, c["clear"][0]))
    if not ratios:
        return set()
    med = float(np.median(list(ratios.values())))
    return {cid for cid, r in ratios.items() if r > max(0.06, med * 2.0)}


def plan_fill(screen, fill, clear_ids=(), arr=None):
    """Which motif goes into which region for a fill: {region: {"motif", "seed"}} (empty regions omitted)."""
    regs = regions()[screen]
    keep = set(fill.get("keep", []))
    if fill.get("auto_keep", True):
        keep |= dirty_cells(screen, arr) - set(fill.get("only") or [])
    rng = np.random.default_rng(fill.get("seed", 0))
    draw_ids = [i for i in (fill.get("only") or list(regs)) if i not in keep and i not in clear_ids]
    motifs = L.choose(len(draw_ids), fill.get("theme", "mixed"), fill.get("seed", 0))
    dens = fill.get("density", 0.92)
    out = {}
    for k, (cid, m) in enumerate(zip(draw_ids, motifs)):
        if rng.random() > dens:
            continue
        out[cid] = {"motif": m, "seed": int(fill.get("seed", 0)) * 101 + k}
    return out


def center(screen, cid):
    x0, y0, x1, y1 = cell(screen, cid)["draw"]
    return (x0 + x1) / 2, (y0 + y1) / 2


def prepare(screen, fill=None, clear_ids=()):
    """Prepare a screenshot: clear clear_ids + (if fill) all regions, then draw new doodles according to fill.
    fill = {"seed": 3, "theme": "winter", "density": 0.85, "keep": ["d13"], "only": [...]}"""
    im = Image.open(SHOTS / screen).convert("RGB")
    if not fill and not clear_ids:
        return im
    regs = regions().get(screen)
    if regs is None:
        raise KeyError(f"no drawing regions defined for {screen} (fill/drawing cannot be used). "
                       f"Define them in assets/screenshots/regions.json. Defined screens: {sorted(regions())}")
    arr = np.array(im)
    keep = set((fill or {}).get("keep", []))
    if fill and fill.get("auto_keep", True):
        keep |= dirty_cells(screen, arr) - set(fill.get("only") or [])
    targets = set(clear_ids)
    if fill:
        ids = fill.get("only") or list(regs)
        targets |= {i for i in ids if i not in keep}
    for cid in targets:
        for r in cell(screen, cid)["clear"]:
            col = _paper(arr, r)
            x0, y0, x1, y1 = [int(v) for v in r]
            arr[y0:y1, x0:x1] = col
    if fill:
        d = Doodle()
        for k, (cid, m) in enumerate(plan_fill(screen, fill, clear_ids, arr=np.array(im)).items()):
            x0, y0, x1, y1 = cell(screen, cid)["draw"]
            w = max(3.0, min(x1 - x0, y1 - y0) * 0.05)
            L.draw_motif(d, m["motif"], (x0, y0, x1, y1), seed=m["seed"], width=w)
        d.render(arr, 1.0)
    return Image.fromarray(arr)


def preview(screen, fill=None, dst=None):
    """For shot planning: save the prepared screen labeled with region ids and their centers."""
    from PIL import ImageDraw
    im = prepare(screen, fill) if fill else Image.open(SHOTS / screen).convert("RGB")
    d = ImageDraw.Draw(im)
    for cid, c in regions().get(screen, {}).items():
        x0, y0, x1, y1 = c["draw"]
        d.rectangle([x0, y0, x1, y1], outline=(255, 0, 0), width=2)
        d.text((x0 + 4, y1 - 14), f"{cid} ({(x0 + x1) // 2},{(y0 + y1) // 2})", fill=(255, 0, 0))
    im.save(dst or "regions_preview.png")
    return dst


if __name__ == "__main__":
    import sys
    # python -m promovideo.regions <screen> '<fill json>' <output.png>
    preview(sys.argv[1], json.loads(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] else None,
            sys.argv[3] if len(sys.argv) > 3 else None)
