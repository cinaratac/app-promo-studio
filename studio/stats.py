"""Post performance: each post's engagement is measured once, 3 days after it was published.

Every day (panel worker) only posts that reached day 3 and were not measured yet are fetched from Buffer;
old posts are not fetched again and again. Results go to stats/measurements.json, a summary to
studio/performance_notes.md (read when writing scenarios).

  python -m studio.stats collect             # daily measurement (posts that reached day 3)
  python -m studio.stats collect --backfill  # first setup: measure all posts older than 3 days once
  python -m studio.stats summary             # print the summary table
"""
import datetime as dt
import json
import statistics
import sys

from . import store

DIR = store.ROOT / "stats"
DB = DIR / "measurements.json"
NOTES = store.ROOT / "studio" / "performance_notes.md"
MEASURE_DAYS = 3      # measurement day
WINDOW_DAYS = 12      # how far back to look (margin for missed days)
STALE_DAYS = 6        # if Buffer has not refreshed the data, take what is there on this day at the latest
LOCAL_TZ = dt.datetime.now().astimezone().tzinfo   # posting hours are grouped in your local time

FORMATS = ["mini story", "dialogue", "riddle", "before/after", "POV", "challenge", "tip", "other"]
OPENINGS = ["question", "funny reaction", "surprising fact", "POV/moment", "challenge", "confession", "other"]
PLATFORM_NAMES = {"instagram": "Instagram", "tiktok": "TikTok", "youtube": "YouTube"}


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _iso(t):
    return t.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def load():
    if DB.exists():
        return json.loads(DB.read_text(encoding="utf-8"))
    return {"posts": {}, "last_run": None, "backfill_done": False}


def _save(db):
    DIR.mkdir(exist_ok=True)
    store._write(DB, db)


# ---------------- scenario matching ----------------
def _scenario_map():
    """Buffer post id -> (scenario, file). publisher/state.json + the scenarios' video files."""
    st_p = store.ROOT / "publisher" / "state.json"
    st = json.loads(st_p.read_text(encoding="utf-8")) if st_p.exists() else {}
    by_file = {}
    for s in store.all_scenarios():
        f = (s.get("video") or {}).get("file")
        if f:
            by_file[f] = s
    out = {}
    for key, v in st.items():
        f = v.get("file") or key.split(":")[0]
        for plat, x in v.items():
            if isinstance(x, dict) and x.get("id") and x.get("via") == "buffer":
                out[x["id"]] = (by_file.get(f), f)
    return out


def _opening_guess(text):
    t = (text or "").strip().lower()
    if not t:
        return "other"
    if "?" in t:
        return "question"
    if any(w in t for w in ("pov", "tonight", "11 pm", "late at night")):
        return "POV/moment"
    if any(w in t for w in ("challenge", "7 days", "for a week")):
        return "challenge"
    return "surprising fact"


def _attrs(scn, text, sent):
    h = sent.astimezone(LOCAL_TZ).hour
    hour = "morning (05–12)" if 5 <= h < 12 else "afternoon (12–17)" if h < 17 and h >= 12 else \
        "evening (17–22)" if 17 <= h < 22 else "night (22–05)"
    a = {"hour": hour, "source": "studio" if scn else "outside studio"}
    if scn:
        lines = scn.get("lines") or []
        first = lines[0]["text"] if lines else ""
        secs = (scn.get("video") or {}).get("seconds") or scn.get("est_seconds")
        a.update({
            "format": scn.get("format") or "other",
            "opening": scn.get("opening") or _opening_guess(first),
            "opening_text": first,
            "lines": len(lines),
            "length": None if not secs else ("short (<15 s)" if secs < 15 else "medium (15–25 s)" if secs <= 25 else "long (>25 s)"),
            "seconds": secs,
            "angle": scn.get("angle"),
            "title": scn.get("title"),
        })
    else:
        a["opening_text"] = (text or "").strip().split("\n")[0][:120]
    return a


# ---------------- Buffer ----------------
POSTS_Q = '''query($i:PostsInput!, $after:String){ posts(first:100, after:$after, input:$i){
  pageInfo { hasNextPage endCursor }
  edges { node { id status channelService sentAt dueAt text metricsUpdatedAt %s } } } }'''


def _fetch(start, end, with_metrics):
    from publisher import common, buffer
    common.load_env()
    org = buffer.gql("query { account { organizations { id } } }")["account"]["organizations"][0]["id"]
    q = POSTS_Q % ("metrics { type value }" if with_metrics else "")
    inp = {"organizationId": org, "filter": {"status": ["sent"], "dueAt": {"start": _iso(start), "end": _iso(end)}}}
    out, after = [], None
    while True:
        r = buffer.gql(q, {"i": inp, "after": after})["posts"]
        out += [e["node"] for e in r["edges"]]
        if not r["pageInfo"]["hasNextPage"]:
            return out
        after = r["pageInfo"]["endCursor"]


def collect(backfill=False, now=None):
    now = now or _now()
    db = load()
    posts = db["posts"]
    smap = _scenario_map()
    cut = now - dt.timedelta(days=MEASURE_DAYS)
    start = dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc) if backfill else now - dt.timedelta(days=WINDOW_DAYS)
    # 1) posts due for measurement (only ones not measured yet)
    new = 0
    for n in _fetch(start, cut, True):
        old = posts.get(n["id"])
        if old and old.get("status") == "measured":
            continue
        sent = _parse(n.get("sentAt") or n.get("dueAt"))
        if not sent:
            continue
        upd = _parse(n.get("metricsUpdatedAt"))
        age = (now - sent).total_seconds() / 86400
        fresh = upd and (upd - sent).total_seconds() / 86400 >= MEASURE_DAYS - 0.5
        late = backfill and age > MEASURE_DAYS + 1.5
        if not (fresh or late or age >= STALE_DAYS):
            scn, f = smap.get(n["id"], (None, None))
            posts[n["id"]] = {**(old or {}), "id": n["id"], "status": "waiting", "platform": n["channelService"],
                              "sent_at": _iso(sent), "text": (n.get("text") or "")[:300],
                              "scenario": scn["id"] if scn else None, "file": f,
                              "measure_on": _iso(sent + dt.timedelta(days=MEASURE_DAYS)),
                              "note": "Buffer has not refreshed the data to day 3 yet; whatever is there is taken on day 6 at the latest"}
            continue
        scn, f = smap.get(n["id"], (None, None))
        rec = {
            "id": n["id"], "platform": n["channelService"], "sent_at": _iso(sent), "text": (n.get("text") or "")[:300],
            "scenario": scn["id"] if scn else None, "file": f, "status": "measured", "measured_at": _iso(now),
            "metrics_updated_at": n.get("metricsUpdatedAt"),
            "age_days": round(((upd or now) - sent).total_seconds() / 86400, 1),
            "late": bool(late and not fresh) or bool(upd and (upd - sent).days > MEASURE_DAYS + 1),
            "stale": not fresh and not late,
            "metrics": {m["type"]: m["value"] for m in (n.get("metrics") or [])},
            "attrs": _attrs(scn, n.get("text"), sent),
        }
        posts[n["id"]] = rec
        new += 1
    # 2) last 3 days: only listed (no metrics fetched)
    for n in _fetch(cut, now, False):
        if n["id"] in posts:
            continue
        sent = _parse(n.get("sentAt") or n.get("dueAt"))
        scn, f = smap.get(n["id"], (None, None))
        posts[n["id"]] = {"id": n["id"], "platform": n["channelService"], "sent_at": _iso(sent), "status": "waiting",
                          "text": (n.get("text") or "")[:300], "scenario": scn["id"] if scn else None, "file": f,
                          "measure_on": _iso(sent + dt.timedelta(days=MEASURE_DAYS))}
    db["last_run"] = _iso(now)
    if backfill:
        db["backfill_done"] = True
    _save(db)
    write_notes(analysis(db))
    return new


def due(hours=20):
    """Is the daily measurement due?"""
    lr = _parse(load().get("last_run"))
    return not lr or (_now() - lr).total_seconds() > hours * 3600


# ---------------- analysis ----------------
def _score(r, med):
    m = r.get("metrics") or {}
    v = m.get("views") or 0
    inter = sum(m.get(k) or 0 for k in ("reactions", "comments", "shares", "saves"))
    secs = (r.get("attrs") or {}).get("seconds")
    # 0 views but some likes: the platform did not report views (no data; do not count as "weak")
    s = {"views": v, "index": round(v / med, 2) if med and v else None,
         "eng": round(100 * inter / v, 1) if v else None,
         "watch": m.get("averageTimeWatched") or None,
         "ret": round(100 * min(1.0, m["averageTimeWatched"] / secs)) if secs and m.get("averageTimeWatched") else None,
         "interactions": inter}
    ix = s["index"]
    s["label"] = None if ix is None else "great" if ix >= 1.5 else "good" if ix >= 1.0 else "average" if ix >= 0.6 else "weak"
    return s


DIMS = [("format", "Format"), ("opening", "Opening type"), ("length", "Length"),
        ("hour", "Posting time (local)"), ("source", "Source")]


def analysis(db=None):
    db = db or load()
    recs = list(db["posts"].values())
    meas = [r for r in recs if r.get("status") == "measured"]
    # YouTube often reports 0 views: keep zeros out of the median
    med = {}
    for p in {r["platform"] for r in meas}:
        vs = [r["metrics"].get("views") or 0 for r in meas if r["platform"] == p]
        nz = [v for v in vs if v > 0]
        med[p] = round(statistics.median(nz)) if nz else 0
    rows = []
    for r in meas:
        rows.append({**{k: r.get(k) for k in ("id", "platform", "sent_at", "text", "scenario", "late", "stale", "age_days")},
                     "attrs": r.get("attrs") or {}, "metrics": r.get("metrics") or {}, **_score(r, med.get(r["platform"]))})
    rows.sort(key=lambda x: x["sent_at"], reverse=True)
    groups = []
    for key, title in DIMS:
        vals = {}
        for x in rows:
            g = x["attrs"].get(key)
            if g is None or x["index"] is None or not x["views"]:
                continue
            vals.setdefault(g, []).append(x)
        if not vals:
            continue
        items = []
        for g, xs in vals.items():
            # median: a single viral video should not skew the group
            avg = lambda k: round(statistics.median([y[k] for y in xs if y[k] is not None]), 2) if any(y[k] is not None for y in xs) else None
            items.append({"value": g, "n": len(xs), "index": avg("index"), "eng": avg("eng"), "ret": avg("ret"),
                          "views": round(statistics.median([y["views"] for y in xs]))})
        items.sort(key=lambda i: -(i["index"] or 0))
        groups.append({"key": key, "title": title, "items": items})
    platforms = []
    for p, m in med.items():
        xs = [x for x in rows if x["platform"] == p]
        platforms.append({"platform": p, "n": len(xs), "median_views": m,
                          "total_views": sum(x["views"] for x in xs),
                          "eng": round(statistics.median([x["eng"] for x in xs if x["eng"] is not None]), 1)
                          if any(x["eng"] is not None for x in xs) else None})
    waiting = sorted([r for r in recs if r.get("status") == "waiting"], key=lambda r: r.get("sent_at") or "", reverse=True)
    return {"last_run": db.get("last_run"), "measured": len(rows), "platforms": platforms, "rows": rows,
            "groups": groups, "waiting": waiting, "measure_days": MEASURE_DAYS}


def write_notes(a):
    L = ["# Performance notes (automatic)",
         "",
         f"Generated by `python -m studio.stats`; do not edit by hand. Each post is measured once, {MEASURE_DAYS} days after publishing. "
         "View index = the video's views / the median views on the same platform (1.0 = average). Group values are medians.",
         "",
         "**How to use:** These are trends, not rules. Do not decide anything on little data (n<3). Try formats and openings that do well "
         "more often, but keep variety: about a third of the scenarios should use new or rarely tried formats/openings. "
         "Do not drop something that did poorly; try it differently.",
         "",
         f"Last measurement: {a.get('last_run') or '-'} · posts measured: {a['measured']}",
         ""]
    for p in a["platforms"]:
        L.append(f"- {PLATFORM_NAMES.get(p['platform'], p['platform'])}: {p['n']} posts, median views {p['median_views']}, "
                 f"avg. engagement {p['eng'] if p['eng'] is not None else '-'}%")
    L.append("")
    for g in a["groups"]:
        if g["key"] == "source":
            continue
        L += [f"## {g['title']}", "", "| value | n | view index | engagement % | watch-through % |", "|---|---|---|---|---|"]
        for i in g["items"]:
            L.append(f"| {i['value']} | {i['n']}{' (little data)' if i['n'] < 3 else ''} | {i['index']} | {i['eng'] if i['eng'] is not None else '-'} | {i['ret'] if i['ret'] is not None else '-'} |")
        L.append("")
    scored = [x for x in a["rows"] if x["index"] is not None and x["views"]]
    if scored:
        top = sorted(scored, key=lambda x: -x["index"])[:5]
        low = sorted(scored, key=lambda x: x["index"])[:5]
        L += ["## Best performers", ""]
        L += [f"- {PLATFORM_NAMES.get(x['platform'], x['platform'])} · {x['views']} views (index {x['index']}) · "
              f"{x['scenario'] or 'outside studio'} · opening: “{x['attrs'].get('opening_text', '')[:90]}”" for x in top]
        L += ["", "## Weakest performers", ""]
        L += [f"- {PLATFORM_NAMES.get(x['platform'], x['platform'])} · {x['views']} views (index {x['index']}) · "
              f"{x['scenario'] or 'outside studio'} · opening: “{x['attrs'].get('opening_text', '')[:90]}”" for x in low]
        L.append("")
    NOTES.write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    a = sys.argv[1:]
    cmd = a[0] if a else "summary"
    if cmd == "collect":
        print(f"{collect(backfill='--backfill' in a)} posts measured")
    elif cmd == "summary":
        print(NOTES.read_text(encoding="utf-8") if NOTES.exists() else "no measurements yet")
    else:
        print(__doc__)
