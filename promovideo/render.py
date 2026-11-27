"""Render pipeline.

Kullanim (proje kokunden):
  python -m promovideo.render <video_dir> timing          # voice/*.wav -> voice/timing.json
  python -m promovideo.render <video_dir> plan            # print the scene timeline
  python -m promovideo.render <video_dir> test [t1 t2..]  # test frames at key moments + contact sheet
  python -m promovideo.render <video_dir> render A B      # render frame range [A,B) to part_A.mp4
  python -m promovideo.render <video_dir> build [--jobs 2] # audio + parallel render + concat + mux + ffprobe

Video klasoru: script.json, scenes.py (frame(i), N_FRAMES, TEST_TIMES), audio.py (build()), voice/, out/
"""
import importlib.util
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

from .core import FFMPEG, FFPROBE, FPS, W, H, ROOT
from . import audio as au


def load_module(vdir, name):
    p = Path(vdir) / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"{Path(vdir).name}_{name}", p)
    m = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT))
    spec.loader.exec_module(m)
    return m


def render_range(vdir, a, b, dst=None):
    sc = load_module(vdir, "scenes")
    out = Path(vdir) / "out"
    out.mkdir(exist_ok=True)
    dst = Path(dst) if dst else out / f"part_{a:06d}.mp4"
    cmd = [FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
           "-pix_fmt", "yuv420p", "-colorspace", "bt709", "-color_primaries", "bt709",
           "-color_trc", "bt709", "-color_range", "tv", "-movflags", "+faststart", str(dst)]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    prog = dst.parent / f"progress_{a:06d}.txt"
    for k, i in enumerate(range(a, b)):
        f = sc.frame(i)
        assert f.shape == (H, W, 3) and f.dtype == np.uint8
        p.stdin.write(f.tobytes())
        if k % 10 == 0 or i == b - 1:
            prog.write_text(f"{k + 1}/{b - a}", encoding="utf-8")
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError(f"ffmpeg error: {dst}")
    return dst


def test_frames(vdir, times=None):
    sc = load_module(vdir, "scenes")
    times = times or sc.TEST_TIMES
    tdir = Path(vdir) / "out" / "test"
    tdir.mkdir(parents=True, exist_ok=True)
    thumbs = []
    for t in times:
        i = min(int(round(t * FPS)), sc.N_FRAMES - 1)
        im = Image.fromarray(sc.frame(i))
        im.save(tdir / f"t_{t:05.2f}.jpg", quality=92)
        thumbs.append(im.resize((W // 4, H // 4), Image.LANCZOS))
    cols = min(6, len(thumbs))
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * W // 4, rows * H // 4), (255, 255, 255))
    for k, th in enumerate(thumbs):
        sheet.paste(th, ((k % cols) * W // 4, (k // cols) * H // 4))
    path = Path(vdir) / "out" / "contact.jpg"
    sheet.save(path, quality=90)
    print(f"contact sheet: {path}")
    return path


def probe(path):
    r = subprocess.run([FFPROBE, "-v", "error", "-count_frames", "-show_entries",
                        "stream=codec_type,codec_name,width,height,r_frame_rate,nb_read_frames:format=duration",
                        "-of", "json", str(path)], capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def _render_progress(out, bounds):
    done = 0
    for k in range(len(bounds) - 1):
        f = out / f"progress_{bounds[k]:06d}.txt"
        try:
            done += int(f.read_text(encoding="utf-8").split("/")[0])
        except Exception:
            pass
    return done


def build(vdir, jobs=2, on_progress=None):
    """on_progress(ratio 0..1, message) - reports render progress."""
    vdir = Path(vdir)
    out = vdir / "out"
    out.mkdir(exist_ok=True)
    for old in list(out.glob("part_*.mp4")) + list(out.glob("progress_*.txt")):
        old.unlink()
    t0 = time.time()
    am = load_module(vdir, "audio")
    mix_path = am.build()
    sc = load_module(vdir, "scenes")
    n = sc.N_FRAMES
    bounds = [round(n * k / jobs) for k in range(jobs + 1)]
    procs = [subprocess.Popen([sys.executable, "-m", "promovideo.render", str(vdir), "render",
                               str(bounds[k]), str(bounds[k + 1])], cwd=ROOT)
             for k in range(jobs)]
    while any(p.poll() is None for p in procs):
        if on_progress:
            on_progress(_render_progress(out, bounds) / n, "kareler ciziliyor")
        time.sleep(1.0)
    if any(p.returncode for p in procs):
        raise RuntimeError("parallel render failed")
    if on_progress:
        on_progress(1.0, "birlestiriliyor")
    lst = out / "parts.txt"
    lst.write_text("".join(f"file 'part_{bounds[k]:06d}.mp4'\n" for k in range(jobs)), encoding="utf-8")
    silent = out / "video_silent.mp4"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(silent)], check=True)
    final = vdir / f"{vdir.name}.mp4"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(silent), "-i", str(mix_path),
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "48000",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
                    str(final)], check=True)
    info = probe(final)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    a = next(s for s in info["streams"] if s["codec_type"] == "audio")
    dur = float(info["format"]["duration"])
    ok = (v["width"], v["height"]) == (W, H) and v["r_frame_rate"] == f"{FPS}/1" \
        and int(v["nb_read_frames"]) == n
    print(f"\n== {final.name} ==")
    print(f"  resolution : {v['width']}x{v['height']}  fps: {v['r_frame_rate']}  codec: {v['codec_name']}/{a['codec_name']}")
    print(f"  frames     : {v['nb_read_frames']} (expected {n})")
    print(f"  duration   : {dur:.2f} s (expected {n / FPS:.2f})")
    print(f"  check      : {'OK' if ok else 'MISMATCH!'}   render time: {time.time() - t0:.0f} s")
    dst = ROOT / "out" / final.name
    dst.parent.mkdir(exist_ok=True)
    shutil.copy2(final, dst)
    print(f"  copied to  : {dst}")
    return final, ok


def build_cached(vdir, jobs=4, on_progress=None):
    """Scene-cached render: each scene is stored as its own mp4 (keyed by a content hash).
    After a small fix only the changed scene(s) are re-rendered; audio is re-mixed every time."""
    vdir = Path(vdir)
    out = vdir / "out"
    segdir = out / "segs"
    segdir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    am = load_module(vdir, "audio")
    mix_path = am.build()
    sc = load_module(vdir, "scenes")
    segs = sc.SEGMENTS
    files = [segdir / f"seg_{s['hash']}.mp4" for s in segs]
    todo = [(s, f) for s, f in zip(segs, files) if not f.exists()]
    for old in segdir.glob("progress_*.txt"):
        old.unlink()
    total = sum(s["f1"] - s["f0"] for s, _ in todo) or 1
    running = []
    queue = list(todo)
    while queue or running:
        while queue and len(running) < jobs:
            s, f = queue.pop(0)
            tmp = segdir / f"tmp_{s['hash']}.mp4"
            p = subprocess.Popen([sys.executable, "-m", "promovideo.render", str(vdir), "render",
                                  str(s["f0"]), str(s["f1"]), str(tmp)], cwd=ROOT)
            running.append((p, tmp, f))
        for item in list(running):
            p, tmp, f = item
            if p.poll() is not None:
                if p.returncode:
                    raise RuntimeError("scene render failed")
                tmp.replace(f)
                running.remove(item)
        if on_progress:
            done = 0
            for pf in segdir.glob("progress_*.txt"):
                try:
                    done += int(pf.read_text(encoding="utf-8").split("/")[0])
                except Exception:
                    pass
            on_progress(min(1.0, done / total), f"rendering frames ({len(todo)}/{len(segs)} scenes re-rendered)")
        time.sleep(0.5)
    if on_progress:
        on_progress(1.0, "joining scenes")
    keep = {f.name for f in files}
    for old in segdir.glob("seg_*.mp4"):
        if old.name not in keep:
            old.unlink()
    lst = out / "parts.txt"
    lst.write_text("".join(f"file 'segs/{f.name}'\n" for f in files), encoding="utf-8")
    silent = out / "video_silent.mp4"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst),
                    "-c", "copy", str(silent)], check=True)
    final = vdir / f"{vdir.name}.mp4"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", str(silent), "-i", str(mix_path),
                    "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "48000",
                    "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart",
                    str(final)], check=True)
    n = sc.N_FRAMES
    info = probe(final)
    v = next(s for s in info["streams"] if s["codec_type"] == "video")
    ok = (v["width"], v["height"]) == (W, H) and v["r_frame_rate"] == f"{FPS}/1" \
        and int(v["nb_read_frames"]) == n
    print(f"{final.name}: {v['nb_read_frames']}/{n} frames, {len(todo)}/{len(segs)} scenes re-rendered, "
          f"{time.time() - t0:.0f} s, {'OK' if ok else 'MISMATCH'}")
    dst = ROOT / "out" / final.name
    dst.parent.mkdir(exist_ok=True)
    shutil.copy2(final, dst)
    return final, ok, len(todo), len(segs)


def main(argv):
    vdir, cmd = Path(argv[0]).resolve(), argv[1]
    if cmd == "timing":
        res = au.analyze_dir(vdir / "voice", vdir / "voice" / "timing.json")
        for k, v in res.items():
            print(f"{k}: dur {v['dur']}  lead {v['lead']}  end {v['end']}  gaps {v['gaps']}")
    elif cmd == "plan":
        from .timeline import build as tb, report
        _, scenes, total = tb(vdir)
        print(report(scenes, total))
    elif cmd == "test":
        test_frames(vdir, [float(x) for x in argv[2:]] or None)
    elif cmd == "render":
        render_range(vdir, int(argv[2]), int(argv[3]), argv[4] if len(argv) > 4 else None)
    elif cmd == "build":
        jobs = int(argv[argv.index("--jobs") + 1]) if "--jobs" in argv else 2
        build(vdir, jobs)
    else:
        print(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
