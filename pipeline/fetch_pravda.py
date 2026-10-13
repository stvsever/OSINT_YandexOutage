"""Pravda network (Portal Kombat) publication timestamps from public sitemaps.

The network publishes automated re-posts of pro-Kremlin Telegram content on
roughly 90 language and country subdomains of news-pravda.com. Each sitemap
entry's <lastmod> equals the article's published_time (verified against the
article page: sitemap 2026-09-23T18:27:34+01:00 equals published 17:27:34Z).
"""
from __future__ import annotations

import gzip
import re
from datetime import datetime, timedelta

import pandas as pd

from common import PROC, RAW, STUDY_END, STUDY_START, get

ROBOTS = "https://news-pravda.com/robots.txt"
LOC_RE = re.compile(r"<loc>([^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>")
HDRS = {"User-Agent": "Mozilla/5.0 (compatible; OSINT-research/1.0)"}


def subdomain_indexes():
    txt = get(ROBOTS, host_key="pravda", min_interval=1.0, headers=HDRS)
    out = []
    for line in txt.splitlines():
        if line.lower().startswith("sitemap:"):
            u = line.split(":", 1)[1].strip()
            if u.endswith("/sitemap.xml"):
                out.append(u)
    return sorted(set(out))


def parse_xml(raw: bytes) -> str:
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


def main():
    idx_urls = subdomain_indexes()
    print(len(idx_urls), "subdomain sitemap indexes")
    rows = []
    lo = STUDY_START - timedelta(days=1)
    for iu in idx_urls:
        host = iu.split("/")[2]
        raw = get(iu, host_key="pravda", min_interval=1.0, headers=HDRS, binary=True)
        if not raw:
            continue
        entries = [(u, datetime.fromisoformat(m)) for u, m in LOC_RE.findall(parse_xml(raw))
                   if "sitemap_news_" in u]
        if not entries:
            print("  no news sitemaps for", host)
            continue
        # file N covers (lastmod[N-1], lastmod[N]]; keep files whose lastmod >= window start
        entries.sort(key=lambda e: e[1])
        keep = [u for u, m in entries if m >= lo]
        n0 = len(rows)
        for su in keep:
            sraw = get(su, host_key="pravda", min_interval=1.0, headers=HDRS, binary=True,
                       timeout=180)
            if not sraw:
                continue
            for loc, lm in LOC_RE.findall(parse_xml(sraw)):
                t = datetime.fromisoformat(lm)
                if lo <= t <= STUDY_END + timedelta(hours=6):
                    path = loc.split("/", 3)[3] if loc.count("/") >= 3 else ""
                    section = path.split("/")[0] if "/" in path else ""
                    rows.append((host, section, loc, t))
        print(f"{host:40s} files={len(keep)} articles={len(rows) - n0}")
    df = pd.DataFrame(rows, columns=["host", "section", "url", "t"])
    df["t_utc"] = pd.to_datetime(df["t"], utc=True)
    df = df.drop(columns="t").drop_duplicates("url")
    df.to_parquet(RAW / "pravda_articles.parquet")
    df["hour"] = df.t_utc.dt.floor("h")
    hourly = df.groupby(["host", "hour"]).size().rename("count").reset_index()
    hourly.to_parquet(PROC / "pravda_hourly.parquet")
    print("total articles", len(df), "hosts", df.host.nunique())


if __name__ == "__main__":
    main()
