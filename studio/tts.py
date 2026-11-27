"""Voice-over and pronunciation check via the Speko Platform REST API (no Claude/MCP needed).

.env: SPEKO_API_KEY  (platform.speko.ai/agents/keys)
Voice, model, speed, language and style come from brand.json ("voice", "language").
To use another TTS service, replace synthesize() (and optionally transcribe()) in this file.
"""
import io
import json
import re
import subprocess
import unicodedata
import wave
from difflib import SequenceMatcher

import requests

from promovideo.brand import BRAND
from publisher.common import env, load_env

API = "https://api.speko.dev/v1"
TTS = {"voice": "Kore", "model": "gemini-3.8-flash-lite-tts", "speed": 1.1,
       "instructions": "Cheerful and warm, like telling a friend.", "provider": "google-tts",
       **{k: v for k, v in BRAND.get("voice", {}).items() if k in ("voice", "model", "speed", "instructions", "provider")}}
LANG = BRAND.get("language", "en-US")


def _key():
    load_env()
    k = env("SPEKO_API_KEY")
    if not k:
        raise RuntimeError("SPEKO_API_KEY missing (.env). Get a key at platform.speko.ai/agents/keys")
    return k


def synthesize(text, dst, cfg=None):
    """Synthesize text and write it to dst as 16-bit wav."""
    c = {**TTS, **(cfg or {})}
    body = {"text": text, "intent": {"language": LANG}, "voice": c["voice"], "model": c["model"],
            "speed": c["speed"], "instructions": c["instructions"],
            "constraints": {"allowedProviders": {"tts": [c["provider"]]}}}
    r = requests.post(f"{API}/synthesize", json=body, timeout=120,
                      headers={"Authorization": f"Bearer {_key()}"})
    if r.status_code >= 400:
        raise RuntimeError(f"Speko TTS {r.status_code}: {r.text[:300]}")
    ctype = (r.headers.get("X-Speko-Audio-Format") or r.headers.get("Content-Type") or "").lower()
    data = r.content
    if data[:4] == b"RIFF":
        open(dst, "wb").write(data)
    elif "pcm" in ctype or "l16" in ctype:
        m = re.search(r"rate=(\d+)", ctype)
        with wave.open(str(dst), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(int(m.group(1)) if m else 24000)
            w.writeframes(data)
    else:  # mp3/ogg etc. -> wav via ffmpeg
        from promovideo.core import FFMPEG
        subprocess.run([FFMPEG, "-v", "error", "-y", "-i", "-", "-ac", "1", "-ar", "24000",
                        "-c:a", "pcm_s16le", str(dst)], input=data, check=True)
    return dst


def transcribe(wav_path):
    """Transcribe a wav (Speko STT). None on failure."""
    try:
        r = requests.post(f"{API}/transcribe", data=open(wav_path, "rb").read(), timeout=120, stream=True,
                          headers={"Authorization": f"Bearer {_key()}", "Content-Type": "audio/wav",
                                   "x-speko-intent": json.dumps({"language": LANG})})
        if r.status_code >= 400:
            return None
        r.encoding = "utf-8"
        text, parts, event = None, [], None
        for raw in r.iter_lines(decode_unicode=True):
            if not raw:
                continue
            if raw.startswith("event:"):
                event = raw[6:].strip()
            elif raw.startswith("data:"):
                try:
                    d = json.loads(raw[5:].strip())
                except Exception:
                    continue
                t = d.get("text") or d.get("transcript")
                if isinstance(t, str):
                    if event == "done":
                        text = t
                    else:
                        parts.append(t)
        return text if text is not None else (" ".join(parts) if parts else None)
    except Exception:
        return None


def _norm(s):
    s = unicodedata.normalize("NFKD", s.lower().replace("ı", "i"))
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9 ]+", " ", s).split()


def similarity(expected, heard):
    a, b = " ".join(_norm(expected)), " ".join(_norm(heard or ""))
    return SequenceMatcher(None, a, b).ratio() if a else 1.0   # character level: tolerant of small STT mishearings


def check(expected, wav_path, threshold=0.75):
    """(similarity, heard text). (None, None) if STT is unavailable."""
    heard = transcribe(wav_path)
    if heard is None:
        return None, None
    return similarity(expected, heard), heard
