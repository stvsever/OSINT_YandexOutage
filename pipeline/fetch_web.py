"""Web publication timestamps from public sitemaps (sites reachable without
circumventing national DNS filtering). Timestamp semantics were verified by
comparing sitemap entries with the article page's published_time:
ukraina.ru lastmod, zona.media lastmod and theins.ru news:publication_date all
equal the publication time.
"""
from __future__ import annotations

import json
import re

import pandas as pd

from common import RAW, STUDY_END, STUDY_START, get

H = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
SITES = {
    # RIA Novosti (Rossiya Segodnya) outlet aimed at Ukrainian audiences
    "ukraina.ru": ("io_web", ["https://ukraina.ru/sitemap_article.xml?date_start=20260901&date_end=20260930",
                              "https://ukraina.ru/sitemap_article.xml?date_start=20261001&date_end=20261014"], "lastmod"),
    # Independent controls
    "zona.media": ("control_web", ["https://zona.media/sitemap/2026/8/item.xml",
                                   "https://zona.media/sitemap/2026/9/item.xml"], "lastmod"),
    "theins.ru": ("control_web", ["https://theins.ru/sitemap-news-ru-1.xml", "https://theins.ru/sitemap-news-ru-2.xml"],
                  "news"),
}


# Outlets of information-manipulation sets named by the EEAS (WordPress REST API,
# exact publication time date_gmt)
WP_SITES = {"afrinz.ru": "African Initiative", "rrn.com.tr": "RRN / Media Brands (SDA)", "fondfbr.ru": "R-FBI"}


def wordpress(site):
    rows, page = [], 1
    while True:
        body = get(f"https://{site}/wp-json/wp/v2/posts", {"per_page": 100, "page": page, "after": "2026-09-01T00:00:00",
                                                           "before": "2026-10-13T16:00:00", "_fields": "date_gmt,link",
                                                           "orderby": "date", "order": "asc"},
                   host_key=site, min_interval=1.0, headers=H, timeout=60, accept_status=(200, 400))
        try:
            d = json.loads(body) if body else []
        except json.JSONDecodeError:
            break
        if not isinstance(d, list) or not d:
            break
        rows += [(site, "io_eeas_web", x["link"], x["date_gmt"] + "Z") for x in d]
        if len(d) < 100:
            break
        page += 1
    print(site, len(rows))
    return rows


def main():
    rows = []
    for site in WP_SITES:
        rows += wordpress(site)
    for site, (role, urls, field) in SITES.items():
        for u in urls:
            t = get(u, host_key=site, min_interval=1.5, headers=H, timeout=90) or ""
            for block in re.findall(r"<url>(.*?)</url>", t, re.S):
                loc = re.search(r"<loc>\s*([^<\s]+)", block)
                pat = r"<news:publication_date>([^<]+)<" if field == "news" else r"<lastmod>([^<]+)<"
                ts = re.search(pat, block)
                if loc and ts:
                    rows.append((site, role, loc.group(1), ts.group(1)))
    df = pd.DataFrame(rows, columns=["site", "role", "url", "ts"])
    df["t_utc"] = pd.to_datetime(df.ts, utc=True, format="mixed", errors="coerce")
    df = df.dropna(subset=["t_utc"]).drop_duplicates("url")
    df = df[(df.t_utc >= pd.Timestamp(STUDY_START)) & (df.t_utc < pd.Timestamp(STUDY_END))]
    df.to_parquet(RAW / "web_articles.parquet")
    print(df.groupby("site").t_utc.agg(["count", "min", "max"]))


if __name__ == "__main__":
    main()
