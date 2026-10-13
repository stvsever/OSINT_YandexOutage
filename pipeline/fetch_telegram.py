"""Public Telegram channel output via the t.me/s/ web preview (no login).

For each channel we page backwards from the newest post until the study start
and store one row per post: id, UTC timestamp, text length, a text excerpt for
theme classification, forward flag, media flag and the view counter.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime

import pandas as pd
from bs4 import BeautifulSoup

from common import RAW, STUDY_START, get

CHANNELS = [
    # handle, role, language
    ("mod_russia", "pro_kremlin_state", "ru"), ("tass_agency", "pro_kremlin_state", "ru"),
    ("MID_Russia", "pro_kremlin_state", "ru"), ("medvedev_telegram", "pro_kremlin_state", "ru"),
    ("rybar", "pro_kremlin_milblog", "ru"), ("readovkanews", "pro_kremlin_milblog", "ru"),
    ("SolovievLive", "pro_kremlin_milblog", "ru"), ("boris_rozhin", "pro_kremlin_milblog", "ru"),
    ("wargonzo", "pro_kremlin_milblog", "ru"), ("dva_majors", "pro_kremlin_milblog", "ru"),
    ("rusvesnasu", "pro_kremlin_milblog", "ru"), ("voenkorKotenok", "pro_kremlin_milblog", "ru"),
    ("breakingmash", "pro_kremlin_tabloid", "ru"), ("shot_shot", "pro_kremlin_tabloid", "ru"),
    ("intelslava", "io_foreign_audience", "en"), ("neuesausrussland", "io_foreign_audience", "de"),
    ("infodefENGLAND", "io_foreign_audience", "en"), ("infodefGermany", "io_foreign_audience", "de"),
    ("InfoDefenseEN", "io_foreign_audience", "en"), ("InfoDefAll", "io_foreign_audience", "multi"),
    ("meduzalive", "control_ru_independent", "ru"), ("bbcrussian", "control_ru_independent", "ru"),
    ("tvrain", "control_ru_independent", "ru"), ("istories_media", "control_ru_independent", "ru"),
    ("agentstvonews", "control_ru_independent", "ru"),
    ("V_Zelenskiy_official", "control_ukrainian", "uk"), ("ukrpravda_news", "control_ukrainian", "uk"),
    ("suspilnenews", "control_ukrainian", "uk"), ("uniannet", "control_ukrainian", "uk"),
    ("operativnoZSU", "control_ukrainian", "uk"), ("Tsaplienko", "control_ukrainian", "uk"),
    ("strategic_culture", "io_foreign_audience", "en"), ("sputnik_africa", "io_foreign_audience", "en"),
    ("RusEmbUK", "io_foreign_audience", "en"), ("Slavyangrad", "io_foreign_audience", "en"),
    ("rybar_in_english", "io_foreign_audience", "en"), ("southfronteng", "io_foreign_audience", "en"),
    ("infodefSPAIN", "io_foreign_audience", "es"), ("infodefITALY", "io_foreign_audience", "it"),
    ("InfoDefenseESP", "io_foreign_audience", "es"), ("rybar_mena", "pro_kremlin_milblog", "ru"),
    ("izvestia_ru", "pro_kremlin_state", "ru"), ("vestiru24", "pro_kremlin_state", "ru"),
    ("tass_world", "pro_kremlin_state", "ru"), ("aifonline", "pro_kremlin_tabloid", "ru"),
    ("mk_ru", "pro_kremlin_tabloid", "ru"), ("readovka_ru", "pro_kremlin_milblog", "ru"),
    ("rbc_news", "control_ru_business", "ru"), ("kommersant", "control_ru_business", "ru"),
    ("interfaxonline", "control_ru_business", "ru"),
    # IMS and outlets named in the EEAS 4th Report on FIMI Threats (March 2026)
    ("africaninitiative", "io_eeas_ims", "ru"), ("AfricanInitiativeEN", "io_eeas_ims", "en"),
    ("fondfbr", "io_eeas_ims", "ru"), ("rrnmedia", "io_eeas_ims", "multi"), ("gazetaru", "pro_kremlin_state", "ru"),
    ("yandex", "control_ru_nonpolitical", "ru"), ("kinopoisk", "control_ru_nonpolitical", "ru"),
    ("sportsru", "control_ru_nonpolitical", "ru"), ("bazabazon", "control_ru_tabloid", "ru"),
]

HDRS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9"}
VIEWS_RE = re.compile(r"([\d.]+)([KM]?)")


def parse_views(s: str | None):
    if not s:
        return None
    m = VIEWS_RE.match(s.strip())
    if not m:
        return None
    v = float(m.group(1))
    return int(v * {"": 1, "K": 1e3, "M": 1e6}[m.group(2)])


def parse_page(html: str):
    soup = BeautifulSoup(html, "lxml")
    title = soup.select_one(".tgme_channel_info_header_title")
    posts = []
    for m in soup.select("div.tgme_widget_message[data-post]"):
        pid = int(m["data-post"].split("/")[-1])
        t = m.select_one("a.tgme_widget_message_date time[datetime]")
        if t is None:
            continue
        txt = m.select_one(".tgme_widget_message_text")
        text = txt.get_text(" ", strip=True) if txt else ""
        posts.append({
            "post_id": pid,
            "t_utc": t["datetime"],
            "text_len": len(text),
            "text": text[:600],
            "forwarded": m.select_one(".tgme_widget_message_forwarded_from") is not None,
            "media": m.select_one(".tgme_widget_message_photo_wrap, .tgme_widget_message_video_player,"
                                  " .tgme_widget_message_document_wrap") is not None,
            "views": parse_views((m.select_one(".tgme_widget_message_views") or {}).get_text()
                                 if m.select_one(".tgme_widget_message_views") else None),
        })
    return (title.get_text(strip=True) if title else None), posts


def fetch_channel(handle: str):
    url = f"https://t.me/s/{handle}"
    before = None
    allp, title = {}, None
    for _ in range(3000):
        params = {"before": before} if before else None
        html = get(url, params, host_key="telegram", min_interval=1.2, headers=HDRS,
                   cache=before is not None, timeout=60)
        if not html:
            break
        ttl, posts = parse_page(html)
        title = title or ttl
        if not posts:
            break
        new = 0
        for p in posts:
            if p["post_id"] not in allp:
                allp[p["post_id"]] = p
                new += 1
        oldest = min(posts, key=lambda p: p["post_id"])
        if datetime.fromisoformat(oldest["t_utc"]) < STUDY_START or new == 0:
            break
        before = oldest["post_id"]
    return title, list(allp.values())


def main():
    out = RAW / "telegram"
    out.mkdir(exist_ok=True)
    only = set(sys.argv[1:])
    meta = []
    for handle, role, lang in CHANNELS:
        if only and handle not in only:
            continue
        path = out / f"{handle}.parquet"
        title, posts = fetch_channel(handle)
        df = pd.DataFrame(posts)
        if len(df):
            df["t_utc"] = pd.to_datetime(df["t_utc"], utc=True)
            df = df[df.t_utc >= pd.Timestamp(STUDY_START)].sort_values("t_utc")
        df.to_parquet(path)
        meta.append({"handle": handle, "role": role, "lang": lang, "title": title, "n": len(df)})
        print(f"{handle:22s} {role:24s} {str(title)[:40]:40s} n={len(df)}")
        mp = out / "_channels_meta.csv"
        prev = pd.read_csv(mp) if mp.exists() else pd.DataFrame()
        allm = pd.concat([prev, pd.DataFrame(meta)]).drop_duplicates("handle", keep="last")
        allm.to_csv(mp, index=False)


if __name__ == "__main__":
    main()
