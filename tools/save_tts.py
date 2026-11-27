"""Writes a Speko audio_synthesize result (JSON: audio_base64 or url) to a wav file.

  python tools/save_tts.py <result.json> <target.wav>
"""
import base64
import json
import sys
import urllib.request

src, dst = sys.argv[1], sys.argv[2]
d = json.load(open(src, encoding="utf-8"))
if d.get("audio_base64"):
    data = base64.b64decode(d["audio_base64"])
else:
    data = urllib.request.urlopen(d["url"]).read()
open(dst, "wb").write(data)
print(f"{dst}: {d.get('duration_seconds')} s, {d.get('sample_rate')} Hz, {d.get('provider')}/{d.get('model')}")
