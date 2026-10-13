"""Reddit activity via the Arctic Shift archive API (no authentication).

Part A: hourly comment and post counts per subreddit (aggregate endpoint), plus
        hourly counts of posts matching the Ukraine war keyword query.
Part B: raw comment streams (id, author, created_utc, link_id) for the
        war-focused subreddits, and the titles of every thread they touch, used
        for the thread-level theme split and account-level indicators.

Timing note (verified empirically on 2026-10-13): the aggregate endpoint labels
hour buckets in server-local time printed with a Z suffix. During CEST the label
is 2 h behind true UTC (raw comments created 00:00 to 01:00 UTC are labelled
22:00Z of the previous day). Every label is corrected by the Europe/Berlin UTC
offset in force at that moment.

Server-side query timeouts (HTTP 422) occur for windows longer than about two
days on active subreddits, so windows are two days and are halved on failure.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

from common import PROC, RAW, STUDY_END, get, ts

BASE = "https://arctic-shift.photon-reddit.com/api"
BERLIN = ZoneInfo("Europe/Berlin")
REDDIT_START = datetime(2026, 9, 8, tzinfo=timezone.utc)

SUBREDDITS = {
    # Ukraine war focused (theme of national interest)
    "ukraine": "war", "UkraineWarVideoReport": "war", "RussiaUkraineWar2022": "war",
    "UkraineRussiaReport": "war", "worldnews": "war", "europe": "war", "geopolitics": "war",
    "russia": "war",
    # Political publics (Germany, United Kingdom, United States, Canada, Poland)
    "de": "politics", "ukpolitics": "politics", "politics": "politics",
    "Conservative": "politics", "canada": "politics", "Polska": "politics",
    # Controls without a national-interest theme
    "aww": "control", "gardening": "control", "soccer": "control", "movies": "control",
    "personalfinance": "control", "Cooking": "control",
}
WAR_QUERY = ("ukraine OR ukrainian OR russia OR russian OR putin OR zelensky OR kremlin OR "
             "kyiv OR nato OR yandex OR russland OR ukraina OR rosja OR rosji")
THEME_SUBS = [s for s, g in SUBREDDITS.items() if g in ("war", "politics")]
AUTHOR_STREAM_SUBS = ["UkraineRussiaReport", "RussiaUkraineWar2022"]


def label_to_utc(label: str) -> pd.Timestamp:
    naive = datetime.strptime(label[:19], "%Y-%m-%dT%H:%M:%S")
    guess = naive.replace(tzinfo=timezone.utc)
    off = guess.astimezone(BERLIN).utcoffset() or timedelta(0)
    return pd.Timestamp(guess + off)


def aggregate(kind, sub, a, b, theme):
    params = {"aggregate": "created_utc", "frequency": "hour", "subreddit": sub,
              "after": ts(a), "before": ts(b)}
    if theme:
        params["query"] = WAR_QUERY
    body = get(f"{BASE}/{kind}/search/aggregate", params, host_key="arctic",
               min_interval=5.0, timeout=120, retries=2)
    if body is None:
        return None
    d = json.loads(body)
    if d.get("data") is None:
        return None
    return [(label_to_utc(r["created_utc"]), int(r["count"])) for r in d["data"]]


def fetch_range(kind, sub, a, b, theme, depth=0):
    """Return (rows, covered_intervals); failed sub-windows are left uncovered."""
    res = aggregate(kind, sub, a, b, theme)
    if res is not None:
        return res, [(a, b)]
    if depth >= 3:
        return [], []
    mid = a + (b - a) / 2
    r1, c1 = fetch_range(kind, sub, a, mid, theme, depth + 1)
    r2, c2 = fetch_range(kind, sub, mid, b, theme, depth + 1)
    return r1 + r2, c1 + c2


def part_a():
    rows, cover = [], []
    for sub, group in SUBREDDITS.items():
        for kind in ("comments", "posts"):
            if kind == "posts" and group == "control":
                continue  # comment volume suffices for the non-political controls
            themes = (False, True) if (sub in THEME_SUBS and kind == "posts") else (False,)
            for theme in themes:
                t, n = REDDIT_START, 0
                while t < STUDY_END:
                    t2 = min(t + timedelta(days=2), STUDY_END)
                    got, cov = fetch_range(kind, sub, t, t2, theme)
                    for hour, c in got:
                        rows.append((sub, group, kind, "war" if theme else "all", hour, c))
                        n += c
                    for a_, b_ in cov:
                        cover.append((sub, kind, "war" if theme else "all", pd.Timestamp(a_), pd.Timestamp(b_)))
                    t = t2
                print(f"r/{sub:22s} {kind:8s} {'war' if theme else 'all':3s} n={n}", flush=True)
                pd.DataFrame(rows, columns=["subreddit", "group", "kind", "theme", "hour", "count"]) \
                  .to_parquet(PROC / "reddit_hourly.parquet")
                pd.DataFrame(cover, columns=["subreddit", "kind", "theme", "start", "end"]) \
                  .to_parquet(PROC / "reddit_coverage.parquet")


def part_b():
    out = RAW / "reddit_authors"
    out.mkdir(exist_ok=True)
    for sub in AUTHOR_STREAM_SUBS:
        path = out / f"{sub}.parquet"
        if path.exists():
            print("skip", sub)
            continue
        recs, after, end = [], ts(REDDIT_START), ts(STUDY_END)
        while after < end:
            body = get(f"{BASE}/comments/search",
                       {"subreddit": sub, "after": after, "before": end, "limit": "auto",
                        "sort": "asc", "fields": "id,author,created_utc,link_id"},
                       host_key="arctic", min_interval=4.0, timeout=120, cache=False, retries=4)
            if body is None:
                print("  ! stream failed", sub, after)
                break
            d = json.loads(body).get("data") or []
            if not d:
                break
            recs += d
            last = d[-1]["created_utc"]
            after = last if last > after else after + 1
            if len(recs) // 20000 != (len(recs) - len(d)) // 20000:
                print(f"  r/{sub} {len(recs)} comments up to {datetime.fromtimestamp(last, timezone.utc):%m-%d %H:%M}",
                      flush=True)
        df = pd.DataFrame(recs).drop_duplicates("id")
        df.to_parquet(path)
        print(f"r/{sub}: {len(df)} comments saved", flush=True)
    titles()


def titles():
    """Fetch titles of every thread that received streamed comments."""
    out = RAW / "reddit_authors"
    path = out / "_thread_titles.parquet"
    have = set(pd.read_parquet(path).id) if path.exists() else set()
    ids = set()
    for f in out.glob("*.parquet"):
        if f.name.startswith("_"):
            continue
        ids |= set(pd.read_parquet(f, columns=["link_id"]).link_id.str.replace("t3_", "", regex=False))
    todo = sorted(ids - have)
    print(len(todo), "thread titles to fetch", flush=True)
    recs = []
    for i in range(0, len(todo), 400):
        body = get(f"{BASE}/posts/ids", {"ids": ",".join(todo[i:i + 400]),
                                          "fields": "id,title,subreddit,created_utc,author,link_flair_text"},
                   host_key="arctic", min_interval=2.5, timeout=120, retries=4)
        if body:
            recs += json.loads(body).get("data") or []
    df = pd.DataFrame(recs)
    if path.exists():
        df = pd.concat([pd.read_parquet(path), df], ignore_index=True)
    df.drop_duplicates("id").to_parquet(path)
    print("titles saved", len(df), flush=True)


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "a"
    if which in ("a", "all"):
        part_a()
    if which in ("b", "all"):
        part_b()
