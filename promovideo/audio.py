"""Audio: envelope analysis (timing.json), SFX synthesis with numpy, mixing."""
import json
import wave
from pathlib import Path

import numpy as np
from scipy.signal import fftconvolve, resample_poly, butter, sosfilt

SR = 48000
ENV_WIN = 240
ENV_THR = 0.02
MIN_GAP = 0.15


def read_wav(path):
    with wave.open(str(path), "rb") as w:
        sr, ch, sw = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    assert sw == 2, "16-bit wav bekleniyor"
    x = np.frombuffer(raw, np.int16).astype(np.float32) / 32768
    if ch > 1:
        x = x.reshape(-1, ch).mean(1)
    return x, sr


def write_wav(path, stereo, sr=SR):
    y = np.clip(stereo, -1, 1)
    pcm = (y * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


# ---------------- envelope analysis ----------------
def analyze(path):
    x, sr = read_wav(path)
    env = np.convolve(np.abs(x), np.ones(ENV_WIN) / ENV_WIN, mode="same")
    on = env > ENV_THR
    idx = np.flatnonzero(on)
    dur = len(x) / sr
    if len(idx) == 0:
        return {"dur": dur, "lead": 0.0, "end": dur, "gaps": []}
    lead, end = idx[0] / sr, idx[-1] / sr
    gaps = []
    seg = on[idx[0]:idx[-1] + 1]
    # silent runs
    d = np.diff(np.concatenate([[1], seg.astype(np.int8), [1]]))
    starts, stops = np.flatnonzero(d == -1), np.flatnonzero(d == 1)
    for s, e in zip(starts, stops):
        if (e - s) / sr > MIN_GAP:
            gaps.append([round(float(idx[0] + s) / sr, 3), round(float(idx[0] + e) / sr, 3)])
    return {"dur": round(float(dur), 3), "lead": round(float(lead), 3), "end": round(float(end), 3), "gaps": gaps}


def analyze_dir(voice_dir, out_json):
    voice_dir = Path(voice_dir)
    res = {p.stem: analyze(p) for p in sorted(voice_dir.glob("*.wav"))}
    Path(out_json).write_text(json.dumps(res, indent=2), encoding="utf-8")
    return res


# ---------------- SFX ----------------
def _t(d):
    return np.arange(int(SR * d)) / SR


def sfx_pop():
    t = _t(0.09)
    f = 620 * np.exp(-t * 18) + 220
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * np.exp(-t * 45)


def sfx_click():
    t = _t(0.025)
    n = np.random.default_rng(3).normal(0, 1, len(t))
    sos = butter(4, 2500, "hp", fs=SR, output="sos")
    return sosfilt(sos, n) * np.exp(-t * 260) * 0.6


def sfx_whoosh(d=0.42):
    t = _t(d)
    n = np.random.default_rng(5).normal(0, 1, len(t))
    sos = butter(2, [500, 3500], "bp", fs=SR, output="sos")
    env = np.sin(np.pi * t / d) ** 2
    return sosfilt(sos, n) * env * 0.5


def sfx_sparkle():
    out = np.zeros(int(SR * 0.6))
    for i, f in enumerate((2637, 3136, 3951, 3520)):
        t = _t(0.35)
        s = np.sin(2 * np.pi * f * t) * np.exp(-t * 14) * 0.35
        o = int(SR * 0.06 * i)
        out[o:o + len(s)] += s
    return out


SFX = {"pop": sfx_pop, "click": sfx_click, "whoosh": sfx_whoosh, "sparkle": sfx_sparkle}


# ---------------- mix ----------------
def _reverb(x, wet=0.10):
    t = _t(0.9)
    ir = np.random.default_rng(11).normal(0, 1, len(t)) * np.exp(-t * 6.5)
    ir /= np.abs(ir).sum() / 8
    sos = butter(2, 4500, "lp", fs=SR, output="sos")
    r = sosfilt(sos, fftconvolve(x, ir)[: len(x)])
    r *= (np.abs(x).max() + 1e-9) / (np.abs(r).max() + 1e-9)
    return x * (1 - wet) + r * wet


def _read_stereo(path):
    with wave.open(str(path), "rb") as w:
        sr, ch = w.getframerate(), w.getnchannels()
        x = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    x = x.reshape(-1, ch)
    if ch == 1:
        x = np.repeat(x, 2, 1)
    if sr != SR:
        x = np.stack([resample_poly(x[:, k], SR, sr) for k in range(2)], 1)
    return x


def _music_bed(name, n, voice, level_db=-12.0, duck_db=8.0):
    """Loop/trim the track to the duration and duck it under speech. level_db: music level relative to
    the voice RMS when nobody speaks; while speaking it is lowered by an extra duck_db."""
    from .music import path as music_path
    m = _read_stereo(music_path(name))
    reps = int(np.ceil(n / len(m)))
    m = np.tile(m, (reps, 1))[:n]
    # envelope: fast attack (40 ms), slow release (350 ms)
    env = np.abs(voice[:n])
    a, r = np.exp(-1 / (0.04 * SR)), np.exp(-1 / (0.35 * SR))
    from scipy.signal import lfilter as _lf
    att = _lf([1 - a], [1, -a], env)
    env = np.maximum(att, _lf([1 - r], [1, -r], att))
    act = np.clip(env / (np.percentile(env[env > 1e-4], 75) + 1e-9), 0, 1) if (env > 1e-4).any() else env * 0
    speech = voice[:n][env > 0.02] if (env > 0.02).any() else voice[:n]
    v_rms = np.sqrt(np.mean(speech ** 2)) + 1e-9
    m_rms = np.sqrt(np.mean(m ** 2)) + 1e-9
    g = v_rms / m_rms * 10 ** (level_db / 20)
    duck = 10 ** (-duck_db * act / 20)
    m = m * (g * duck)[:, None]
    fi, fo = int(0.4 * SR), int(1.6 * SR)
    m[:fi] *= np.linspace(0, 1, fi)[:, None]
    m[-fo:] *= np.linspace(1, 0, fo)[:, None]
    return m


def mix(total_dur, voice_clips, sfx_cues, out_path, sfx_gain=0.09, music=None, music_level_db=-12.0):
    """voice_clips: [(wav_path, start_s)]  sfx_cues: [(name, time_s, gain)]
    music: name of a track in assets/music (file name without extension) or None (no music)."""
    n = int(SR * total_dur)
    v = np.zeros(n + SR)
    for path, at in voice_clips:
        x, sr = read_wav(path)
        if sr != SR:
            x = resample_poly(x, SR, sr)
        o = int(at * SR)
        v[o:o + len(x)] += x[: len(v) - o]
    v = _reverb(v)
    s = np.zeros_like(v)
    for name, at, g in sfx_cues:
        x = SFX[name]()
        o = int(at * SR)
        s[o:o + len(x)] += x[: len(s) - o] * g
    y = (v + s * sfx_gain)[:n]
    st = np.stack([y, y], 1)
    if music:
        st = st + _music_bed(music, n, v, music_level_db)
    fi, fo = int(0.1 * SR), int(0.5 * SR)
    st[:fi] *= np.linspace(0, 1, fi)[:, None]
    st[-fo:] *= np.linspace(1, 0, fo)[:, None]
    st *= 0.89 / (np.abs(st).max() + 1e-9)
    write_wav(out_path, st)
    return out_path
