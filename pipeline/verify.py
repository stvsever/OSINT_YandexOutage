"""Live re-verification of stored time series against fresh downloads.

For every source a random sample of stored values is re-requested from the live
origin (bypassing the cache) and compared. Exact agreement is expected for
immutable telemetry (IODA, RIPE, Wikimedia, sitemaps); small differences are
possible where content can be deleted after collection (Telegram, Reddit).
"""
from __future__ import annotations

import json
import random
from datetime import timedelta

import numpy as np
import pandas as pd

from common import PROC, RAW, get, save_json, ts

random.seed(20261014)
OUT = []


def record(source, check, n, diffs, note=""):
    diffs = [abs(d) for d in diffs]
    OUT.append(dict(source=source, check=check, n=n, max_abs_diff=float(max(diffs)) if diffs else None,
                    exact_share=float(np.mean([d == 0 for d in diffs])) if diffs else None, note=note))
    print(f"{source:22s} {check:58s} n={n:3d} exact={OUT[-1]['exact_share']} maxdiff={OUT[-1]['max_abs_diff']}")


def ioda():
    raw = pd.read_parquet(RAW / "ioda_raw.parquet")
    x = raw[(raw.entity_code == "200350") & (raw.datasource == "ping-slash24")].dropna()
    diffs = []
    for _ in range(4):
        r = x.sample(1, random_state=random.randint(0, 10**6)).iloc[0]
        t0 = int(r.epoch) - 3600
        body = get(f"https://api.ioda.inetintel.cc.gatech.edu/v2/signals/raw/asn/200350",
                   {"from": t0, "until": t0 + 7200, "datasource": "ping-slash24"}, cache=False, host_key="ioda", min_interval=1.5)
        s = json.loads(body)["data"][0][0]
        live = {s["from"] + i * s["step"]: v for i, v in enumerate(s["values"])}
        stored = x[(x.epoch >= t0) & (x.epoch < t0 + 7200)].set_index("epoch").value
        diffs += [live[e] - v for e, v in stored.items() if e in live and live[e] is not None]
    record("IODA", "Yandex Cloud responsive /24 blocks, 4 random 2 h windows", len(diffs), diffs)


def wikimedia():
    w = pd.read_parquet(PROC / "wikimedia_agents_hourly.parquet")
    w = w[(w.project == "ru.wikipedia") & (w.agent == "user")]
    diffs = []
    for _, r in w.sample(5, random_state=7).iterrows():
        h = r.hour.strftime("%Y%m%d%H")
        body = get(f"https://wikimedia.org/api/rest_v1/metrics/pageviews/aggregate/ru.wikipedia/all-access/user/hourly/{h}/{h}",
                   cache=False, host_key="wikimedia", min_interval=0.5)
        diffs.append(json.loads(body)["items"][0]["views"] - r.views)
    record("Wikimedia", "ru.wikipedia hourly user pageviews, 5 random hours", len(diffs), diffs)


def pravda():
    a = pd.read_parquet(RAW / "pravda_articles.parquet")
    a = a[a.host == "news-pravda.com"]
    body = get("https://news-pravda.com/sitemap.xml", host_key="pravda", min_interval=1, cache=False,
               headers={"User-Agent": "Mozilla/5.0"})
    import re
    import gzip
    files = re.findall(r"<loc>([^<]+sitemap_news_\d+\.xml\.gz)</loc>", body)
    raw = get(sorted(files, key=lambda u: int(re.search(r"_(\d+)\.xml", u).group(1)))[-2], host_key="pravda",
              min_interval=1, cache=False, binary=True, headers={"User-Agent": "Mozilla/5.0"})
    txt = gzip.decompress(raw).decode()
    live = pd.to_datetime(pd.Series(re.findall(r"<lastmod>([^<]+)</lastmod>", txt)), utc=True)
    live_h = live.dt.floor("h").value_counts()
    st_h = a.t_utc.dt.floor("h").value_counts()
    hours = [h for h in live_h.index if live_h.index.min() + timedelta(days=1) < h < live_h.index.max() - timedelta(days=1)]
    sample = random.sample(hours, min(10, len(hours)))
    diffs = [int(live_h.get(h, 0)) - int(st_h.get(h, 0)) for h in sample]
    record("Pravda network", "news-pravda.com articles per hour, 10 random hours", len(diffs), diffs)


def telegram():
    from fetch_telegram import HDRS, parse_page
    diffs, n = [], 0
    for ch in ("rybar", "tass_agency", "meduzalive"):
        df = pd.read_parquet(RAW / "telegram" / f"{ch}.parquet")
        pid = int(df.sample(1, random_state=3).post_id.iloc[0])
        html = get(f"https://t.me/s/{ch}", {"before": pid + 5}, host_key="telegram", min_interval=1.5, headers=HDRS, cache=False)
        _, posts = parse_page(html)
        st = df.set_index("post_id").t_utc
        for p in posts:
            if p["post_id"] in st.index:
                diffs.append((pd.Timestamp(p["t_utc"]) - st[p["post_id"]]).total_seconds())
                n += 1
    record("Telegram", "post timestamps of 3 channels re-read from t.me/s", n, diffs)


def reddit():
    from fetch_reddit import BASE
    r = pd.read_parquet(PROC / "reddit_hourly.parquet")
    diffs = []
    for sub in ("UkraineRussiaReport", "europe"):
        rr = r[(r.subreddit == sub) & (r.kind == "comments") & (r.theme == "all")]
        for _, row in rr[rr.hour < "2026-10-12"].sample(3, random_state=11).iterrows():
            a = ts(row.hour.to_pydatetime())
            cnt, after = 0, a
            while True:
                body = get(f"{BASE}/comments/search", {"subreddit": sub, "after": after, "before": a + 3600, "limit": 100,
                                                     "sort": "asc", "fields": "created_utc,id"}, host_key="arctic",
                           min_interval=3, cache=False)
                d = json.loads(body).get("data") or []
                cnt += len(d)
                if len(d) < 100:
                    break
                after = d[-1]["created_utc"]
            diffs.append(cnt - row["count"])
    record("Reddit (Arctic Shift)", "hourly comment counts vs raw comments, 6 random hours", len(diffs), diffs,
           "verifies the +2 h bucket correction")


def web():
    w = pd.read_parquet(RAW / "web_articles.parquet")
    a = w[w.site == "afrinz.ru"]
    day = pd.Timestamp("2026-09-20", tz="UTC")
    body = get("https://afrinz.ru/wp-json/wp/v2/posts", {"per_page": 100, "after": "2026-09-20T03:00:00",
                                                       "before": "2026-09-21T03:00:00", "_fields": "date_gmt"},
               host_key="afrinz.ru", min_interval=1, cache=False, headers={"User-Agent": "Mozilla/5.0"})
    live = pd.to_datetime(pd.Series([x["date_gmt"] for x in json.loads(body)]), utc=True)
    live = live[(live >= day) & (live < day + timedelta(days=1))]
    stored = a[(a.t_utc >= day) & (a.t_utc < day + timedelta(days=1))]
    lh, sh = live.dt.floor("h").value_counts(), stored.t_utc.dt.floor("h").value_counts()
    diffs = [int(lh.get(h, 0)) - int(sh.get(h, 0)) for h in pd.date_range(day, periods=24, freq="h")]
    record("Web (WordPress API)", "African Initiative articles per hour on 20 Sep", len(diffs), diffs)


def ripe():
    r = pd.read_parquet(PROC / "ripe_bgp_hourly.parquet")
    x = r[r.asn == "200350"].sample(1, random_state=5).iloc[0]
    t = x.hour
    body = get("https://stat.ripe.net/data/bgp-update-activity/data.json",
               {"resource": "AS200350", "starttime": t.strftime("%Y-%m-%dT%H:%M"),
                "endtime": (t + timedelta(hours=6)).strftime("%Y-%m-%dT%H:%M"), "max_samples": 200,
                "min_sampling_period": 3600}, host_key="ripestat", min_interval=1, cache=False)
    live = {pd.Timestamp(u["starttime"], tz="UTC"): u["announcements"] or 0 for u in json.loads(body)["data"]["updates"]}
    st = r[(r.asn == "200350")].set_index("hour").announcements
    diffs = [live[h] - st[h] for h in live if h in st.index]
    record("RIPE Stat", "AS200350 hourly BGP announcements, random 6 h window", len(diffs), diffs)


def main():
    import sys
    path = PROC / "verification.json"
    prev = {r["source"]: r for r in json.loads(path.read_text())} if path.exists() else {}
    only = set(sys.argv[1:])
    names = {"ioda": "IODA", "wikimedia": "Wikimedia", "pravda": "Pravda network", "telegram": "Telegram",
             "reddit": "Reddit (Arctic Shift)", "web": "Web (WordPress API)", "ripe": "RIPE Stat"}
    for f in (ioda, wikimedia, pravda, telegram, reddit, web, ripe):
        if only and f.__name__ not in only:
            if names[f.__name__] in prev:
                OUT.append(prev[names[f.__name__]])
            continue
        try:
            f()
        except Exception as e:  # keep the last successful check if the service is temporarily unreachable
            print("FAILED", f.__name__, e)
            if names[f.__name__] in prev and prev[names[f.__name__]].get("exact_share") is not None:
                OUT.append(prev[names[f.__name__]])
            else:
                OUT.append(dict(source=names[f.__name__], check="failed", n=0, max_abs_diff=None, exact_share=None, note=str(e)[:120]))
    save_json(OUT, path)


if __name__ == "__main__":
    main()
