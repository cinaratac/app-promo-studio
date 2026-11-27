"""Cloudflare R2 (S3 compatible) uploader - no extra library needed (AWS SigV4 is signed by hand).

The Buffer API does not accept file uploads; it fetches the video from a public, persistent https URL.
Required (.env): R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET,
                 R2_PUBLIC_BASE_URL (the bucket's public URL: https://pub-xxxx.r2.dev or your own domain)
"""
import datetime as dt
import hashlib
import hmac
import urllib.parse

import requests

from .common import env


def _cfg():
    return {k: env(k, required=True) for k in
            ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET", "R2_PUBLIC_BASE_URL")}


def _sign(key, msg):
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _request(method, key, body=b"", content_type=None):
    c = _cfg()
    host = f"{c['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com"
    path = "/" + c["R2_BUCKET"] + "/" + urllib.parse.quote(key)
    now = dt.datetime.now(dt.timezone.utc)
    amz_date, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    payload_hash = hashlib.sha256(body).hexdigest()
    headers = {"host": host, "x-amz-content-sha256": payload_hash, "x-amz-date": amz_date}
    if content_type:
        headers["content-type"] = content_type
    signed = ";".join(sorted(headers))
    canonical = "\n".join([method, path, "",
                           "".join(f"{k}:{headers[k]}\n" for k in sorted(headers)),
                           signed, payload_hash])
    scope = f"{day}/auto/s3/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope,
                         hashlib.sha256(canonical.encode()).hexdigest()])
    k = _sign(("AWS4" + c["R2_SECRET_ACCESS_KEY"]).encode(), day)
    for part in ("auto", "s3", "aws4_request"):
        k = _sign(k, part)
    sig = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
    headers["Authorization"] = (f"AWS4-HMAC-SHA256 Credential={c['R2_ACCESS_KEY_ID']}/{scope}, "
                                f"SignedHeaders={signed}, Signature={sig}")
    r = requests.request(method, f"https://{host}{path}", data=body, headers=headers, timeout=600)
    if r.status_code >= 300:
        raise RuntimeError(f"R2 {method} {r.status_code}: {r.text[:300]}")
    return r


def public_url(key):
    return _cfg()["R2_PUBLIC_BASE_URL"].rstrip("/") + "/" + urllib.parse.quote(key)


def upload(video, key, content_type=None):
    """Upload the file, return its public URL and verify that it is really reachable."""
    if not content_type:
        content_type = "image/jpeg" if str(video).lower().endswith((".jpg", ".jpeg")) else "video/mp4"
    _request("PUT", key, video.read_bytes(), content_type)
    url = public_url(key)
    h = requests.head(url, timeout=30)
    if h.status_code != 200:
        raise RuntimeError(f"R2 upload worked but the public URL does not ({h.status_code}): {url} "
                           "- bucket'ta Public access (r2.dev) acik mi?")
    return url


def delete(key):
    _request("DELETE", key)
