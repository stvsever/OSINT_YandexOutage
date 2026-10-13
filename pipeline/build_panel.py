"""Assemble every collected source into one hourly UTC panel with metadata.

Output
  data/processed/panel.parquet   long format: series_id, hour, value
  data/processed/series_meta.json  one record per series (layer, group, role,
                                   theme, unit, source, method notes)
"""
from __future__ import annotations

import json
import re

import numpy as np
import pandas as pd

from common import PROC, RAW, STUDY_END, STUDY_START, get, save_json

HOURS = pd.date_range(STUDY_START, STUDY_END, freq="h", inclusive="left")

# Ukraine war theme lexicon (Russian, Ukrainian, English, German stems), applied
# case-insensitively to Telegram post text.
WAR_RE = re.compile(
    r"(?:украин|україн|киев|київ|зеленск|зеленськ|всу\b|зсу\b|сво\b|спецоперац|фронт|"
    r"донбас|донецк|луганск|херсон|запорож|харьков|харків|курск|белгород|бпла|беспилот|"
    r"дрон|ракет|обстрел|удар|атак|наступлен|минобороны|генштаб|нато\b|"
    r"ukrain|kyiv|kiev|zelensk|nato\b|drone|missile|front ?line|donbas|crimea|krieg|"
    r"russland|selenskyj|kreml|kremlin|putin|путин)", re.I)

META: dict[str, dict] = {}
FRAMES: list[pd.DataFrame] = []


FRAMES_BY_ID: dict[str, pd.Series] = {}


def add(sid: str, s: pd.Series, **meta):
    s = s.reindex(HOURS)
    FRAMES_BY_ID[sid] = s
    FRAMES.append(pd.DataFrame({"series_id": sid, "hour": HOURS, "value": s.to_numpy(dtype=float)}))
    meta.setdefault("unit", "count per hour")
    META[sid] = meta


# ------------------------------------------------------------------ infrastructure
def infra():
    h = pd.read_parquet(PROC / "ioda_hourly.parquet")
    names = {"ping-slash24": "responsive /24 blocks (active probing)",
             "bgp": "BGP-visible /24 blocks", "merit-nt": "telescope unique sources",
             "gtr": "Google traffic (normalised)"}
    for (etype, code, label, role, ds), g in h.groupby(["entity_type", "entity_code", "label", "role", "datasource"]):
        if ds not in names:
            continue
        s = g.set_index("hour")["mean"]
        if s.notna().sum() < 200 or s.fillna(0).abs().sum() == 0:
            continue
        grp = {"treated": "Yandex networks", "control_yandex_abroad": "Yandex abroad (control)",
               "control_hosting": "Russian hosting (control)", "control_platform": "Russian platforms (control)",
               "control_access": "Russian access ISPs", "national": "Russia national",
               "region_treated": "Data-center regions", "region_control": "Control regions"}[role]
        add(f"ioda.{etype}.{code}.{ds}", s, layer="infrastructure", group=grp, role=role,
            label=f"{label}: {names[ds]}", unit=names[ds], source="IODA (Georgia Tech)",
            source_url=f"https://ioda.inetintel.cc.gatech.edu/{'asn' if etype == 'asn' else etype}/{code}",
            method="IODA raw signal, hourly mean of native 5 or 10 minute samples", transform="level")
    r = pd.read_parquet(PROC / "ripe_bgp_hourly.parquet")
    for (asn, name), g in r.groupby(["asn", "name"]):
        s = g.set_index("hour")["announcements"].astype(float)
        add(f"ripe.bgp.AS{asn}", s, layer="infrastructure", group="BGP routing activity",
            role="treated" if asn in ("200350", "13238") else "control",
            label=f"{name} (AS{asn}): BGP announcements", unit="BGP announcements per hour",
            source="RIPE Stat bgp-update-activity", source_url=f"https://stat.ripe.net/AS{asn}",
            method="Hourly count of BGP update announcements for the ASN's prefixes", transform="count")
    io = pd.read_parquet(PROC / "ioda_cloud_unreachable_hourly.parquet")["ioda_unreachable_frac"]
    add("exposure.ioda_cloud_unreachable", io, layer="exposure", group="Measured outage", role="exposure",
        label="Measured: Yandex Cloud unreachable share (IODA)", unit="fraction of baseline /24 blocks",
        source="IODA active probing, AS200350", source_url="https://ioda.inetintel.cc.gatech.edu/asn/200350",
        method="1 minus responsive /24 count divided by the 29 Sep to 7 Oct median", transform="level")


# ------------------------------------------------------------------ dependent services / crawler exposure
def services():
    w = pd.read_parquet(PROC / "wikimedia_agents_hourly.parquet")
    for (proj, agent), g in w.groupby(["project", "agent"]):
        s = g.set_index("hour")["views"].astype(float)
        role = "treated" if proj.startswith("ru.") else "control"
        add(f"wiki.{proj}.{agent}", s, layer="services", group=f"Wikimedia {agent} traffic", role=role,
            label=f"{proj} pageviews, agent={agent}", unit="pageviews per hour",
            source="Wikimedia REST pageviews API", source_url="https://wikimedia.org/api/rest_v1/",
            method="Hourly aggregate pageviews; spider = self-identified crawlers (includes YandexBot); "
                   "automated = undeclared bots flagged by Wikimedia heuristics", transform="count")
    w2 = pd.read_parquet(PROC / "wikimedia_hourly.parquet")
    for (proj, access), g in w2[w2.project == "ru.wikipedia"].groupby(["project", "access"]):
        if access == "all-access":
            continue
        s = g.set_index("hour")["views"].astype(float)
        add(f"wiki.{proj}.user.{access}", s, layer="services", group="Wikimedia user traffic", role="treated",
            label=f"{proj} user pageviews, {access}", unit="pageviews per hour",
            source="Wikimedia REST pageviews API", source_url="https://wikimedia.org/api/rest_v1/",
            method="Hourly user pageviews by access method (mobile shutdown confounder check)", transform="count")


# ------------------------------------------------------------------ Pravda network
def pravda_languages(hosts):
    """Read <html lang> of each subdomain homepage (cached) to tag language."""
    out = {}
    for h in hosts:
        html = get(f"https://{h}/", host_key="pravda", min_interval=1.0,
                   headers={"User-Agent": "Mozilla/5.0 (compatible; OSINT-research/1.0)"})
        m = re.search(r"<html[^>]*\blang=\"([a-zA-Z-]+)\"", html or "")
        out[h] = (m.group(1).split("-")[0].lower() if m else "unknown")
    return out


def pravda():
    a = pd.read_parquet(RAW / "pravda_articles.parquet")
    a["hour"] = a.t_utc.dt.floor("h")
    langs = pravda_languages(sorted(a.host.unique()))
    a["lang"] = a.host.map(langs)
    save_json(langs, PROC / "pravda_host_lang.json")
    tot = a.groupby("hour").size().astype(float)
    common = dict(layer="io", group="Pravda network (Portal Kombat)", role="io_automated",
                  source="news-pravda.com public sitemaps", source_url="https://news-pravda.com/sitemap.xml",
                  method="Article publication timestamps (sitemap lastmod equals published_time)", transform="count")
    add("pravda.total", tot.reindex(HOURS, fill_value=0), label="Pravda network: all subdomains", **common)
    for lang, g in a.groupby("lang"):
        if len(g) < 15000:
            continue
        add(f"pravda.lang.{lang}", g.groupby("hour").size().reindex(HOURS, fill_value=0).astype(float),
            label=f"Pravda network: language {lang}", **common)
    for host, g in a.groupby("host"):
        if len(g) < 25000:
            continue
        add(f"pravda.host.{host}", g.groupby("hour").size().reindex(HOURS, fill_value=0).astype(float),
            label=f"Pravda network: {host}", **common)


# ------------------------------------------------------------------ Telegram
TG_GROUP_LABEL = {
    "pro_kremlin_state": "Pro-Kremlin state channels", "pro_kremlin_milblog": "Pro-Kremlin military bloggers",
    "pro_kremlin_tabloid": "Pro-Kremlin tabloids", "io_foreign_audience": "IO channels for foreign audiences",
    "control_ru_independent": "Russian independent media (control)", "control_ukrainian": "Ukrainian channels (control)",
    "control_ru_nonpolitical": "Russian non-political (control)", "control_ru_tabloid": "Russian tabloid (control)",
    "control_ru_business": "Russian business media (control)",
}
# IO channels whose parent outlet uses Yandex 360 mail (MX records at Yandex, resolved 13 Oct 2026)
YANDEX_MAIL_CHANNELS = {"readovkanews", "readovka_ru", "rybar", "rybar_in_english", "rybar_mena", "strategic_culture"}


def telegram():
    meta = pd.read_csv(RAW / "telegram" / "_channels_meta.csv") if (RAW / "telegram" / "_channels_meta.csv").exists() else None
    from fetch_telegram import CHANNELS
    rows = []
    for handle, role, lang in CHANNELS:
        p = RAW / "telegram" / f"{handle}.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        if df.empty:
            continue
        df["handle"], df["role"], df["lang"] = handle, role, lang
        df["war"] = df["text"].fillna("").str.contains(WAR_RE)
        rows.append(df)
    if not rows:
        return
    tg = pd.concat(rows, ignore_index=True)
    tg["hour"] = tg.t_utc.dt.floor("h")
    tg.to_parquet(PROC / "telegram_posts.parquet")
    io_roles = {"pro_kremlin_state", "pro_kremlin_milblog", "pro_kremlin_tabloid", "io_foreign_audience"}
    for (handle, role), g in tg.groupby(["handle", "role"]):
        if len(g) < 150:
            continue
        add(f"tg.ch.{handle}", g.groupby("hour").size().reindex(HOURS, fill_value=0).astype(float),
            layer="io" if role in io_roles else "control", group=TG_GROUP_LABEL[role], role=role,
            label=f"Telegram @{handle}", source="Telegram public web preview (t.me/s)",
            source_url=f"https://t.me/s/{handle}", method="Posts per hour from the public channel preview",
            transform="count")
    for role, g in tg.groupby("role"):
        for theme, sub in (("all", g), ("war", g[g.war]), ("other", g[~g.war])):
            if len(sub) < 200:
                continue
            add(f"tg.grp.{role}.{theme}", sub.groupby("hour").size().reindex(HOURS, fill_value=0).astype(float),
                layer="io" if role in io_roles else "control", group=TG_GROUP_LABEL[role], role=role,
                theme=theme, label=f"{TG_GROUP_LABEL[role]} ({theme} posts)",
                source="Telegram public web preview (t.me/s)", source_url="https://t.me/",
                method="Sum of posts per hour over channels in the group; theme by keyword lexicon",
                transform="count")
    pk = tg[tg.role.isin(io_roles)]
    for theme, sub in (("all", pk), ("war", pk[pk.war]), ("other", pk[~pk.war])):
        add(f"tg.prokremlin.{theme}", sub.groupby("hour").size().reindex(HOURS, fill_value=0).astype(float),
            layer="io", group="Pro-Kremlin Telegram (all IO-linked channels)", role="io_channels", theme=theme,
            label=f"Pro-Kremlin Telegram, all IO-linked channels ({theme} posts)",
            source="Telegram public web preview (t.me/s)", source_url="https://t.me/",
            method="Sum over state, milblogger, tabloid and foreign-audience channels", transform="count")
    for dep, sub in (("mail", pk[pk.handle.isin(YANDEX_MAIL_CHANNELS)]), ("none", pk[~pk.handle.isin(YANDEX_MAIL_CHANNELS)])):
        add(f"tg.yxdep.{dep}", sub.groupby("hour").size().reindex(HOURS, fill_value=0).astype(float),
            layer="io", group="Yandex-dependency strata (Telegram IO)", role="io_channels", theme="all",
            label=("IO channels of outlets on Yandex 360 mail" if dep == "mail" else "IO channels without a documented Yandex dependency"),
            source="Telegram public web preview; dependency from MX records", source_url="https://t.me/",
            method="Sum over channels; dependency stratum from DNS MX records of the parent outlet", transform="count")
    ctl = tg[tg.role.isin({"control_ru_independent", "control_ukrainian", "control_ru_business"})]
    for theme, sub in (("all", ctl), ("war", ctl[ctl.war])):
        add(f"tg.controls.{theme}", sub.groupby("hour").size().reindex(HOURS, fill_value=0).astype(float),
            layer="control", group="Control Telegram (independent and Ukrainian)", role="control", theme=theme,
            label=f"Control Telegram: Russian independent and Ukrainian channels ({theme} posts)",
            source="Telegram public web preview (t.me/s)", source_url="https://t.me/",
            method="Sum over control channels", transform="count")


# ------------------------------------------------------------------ Reddit
DEFAULT_NAME = re.compile(r"^[A-Z][a-z]+[-_]?[A-Z]?[a-z]+[-_]?\d{1,4}$")
WAR_TITLE = re.compile(r"(?:ukrain|russia|putin|zelensk|kremlin|kyiv|kiev|nato|donbas|crimea|drone|missile|"
                       r"front|offensive|kursk|belgorod|kherson|zaporizh|kharkiv|pokrovsk|kupiansk|"
                       r"yandex|moscow|wagner|shahed|geran)", re.I)


def reddit():
    p = PROC / "reddit_hourly.parquet"
    if not p.exists():
        return
    r = pd.read_parquet(p)
    r = r.groupby(["subreddit", "group", "kind", "theme", "hour"], as_index=False)["count"].sum()
    glabel = {"war": "Reddit: Ukraine war communities", "politics": "Reddit: political communities named in claims",
              "control": "Reddit: non-political controls"}
    totals = r.groupby("subreddit")["count"].sum()
    r = r[r.subreddit.isin(totals[totals >= 2000].index)]
    for (sub, grp, kind, theme), g in r.groupby(["subreddit", "group", "kind", "theme"]):
        s = g.set_index("hour")["count"].astype(float).reindex(HOURS)
        # zero-fill only inside windows that were fetched successfully; failed
        # windows stay missing instead of masquerading as zero activity
        cov_p = PROC / "reddit_coverage.parquet"
        if cov_p.exists():
            cov = pd.read_parquet(cov_p)
            cov = cov[(cov.subreddit == sub) & (cov.kind == kind) & (cov.theme == theme)]
            inside = np.zeros(len(HOURS), dtype=bool)
            for a_, b_ in zip(cov.start, cov.end):
                inside |= (HOURS >= a_) & (HOURS < b_)
            s[inside & s.isna()] = 0.0
            s[~inside] = np.nan
        add(f"rd.{sub}.{kind}.{theme}", s, layer="io" if grp != "control" else "control", group=glabel[grp],
            role=f"reddit_{grp}", theme=theme, label=f"r/{sub} {kind}" + (" (war-keyword posts)" if theme == "war" else ""),
            source="Arctic Shift Reddit archive API", source_url=f"https://www.reddit.com/r/{sub}/",
            method="Hourly counts from the aggregate endpoint, bucket labels corrected to UTC", transform="count")
    for (grp, kind), g in r[r.theme == "all"].groupby(["group", "kind"]):
        # a group total is only defined where every member community is observed
        members = [f"rd.{sub}.{kind}.all" for sub in g.subreddit.unique()]
        mat = pd.concat([FRAMES_BY_ID[m] for m in members if m in FRAMES_BY_ID], axis=1)
        s = mat.sum(axis=1, skipna=False)
        add(f"rd.grp.{grp}.{kind}", s, layer="io" if grp != "control" else "control", group=glabel[grp],
            role=f"reddit_{grp}", theme="all", label=f"{glabel[grp]}: all {kind}",
            source="Arctic Shift Reddit archive API", source_url="https://arctic-shift.photon-reddit.com/",
            method="Sum over subreddits in the group", transform="count")
    # account-level indicators from the raw comment streams
    ad = RAW / "reddit_authors"
    titles = pd.read_parquet(ad / "_thread_titles.parquet") if (ad / "_thread_titles.parquet").exists() else None
    for f in sorted(ad.glob("*.parquet")):
        if f.name.startswith("_"):
            continue
        c = pd.read_parquet(f)
        if c.empty:
            continue
        sub = f.stem
        c["hour"] = pd.to_datetime(c.created_utc, unit="s", utc=True).dt.floor("h")
        c = c[c.author.notna()]
        live = c[~c.author.isin(["[deleted]", "AutoModerator"])]
        if len(live) < 2000:
            continue
        first_seen = live.groupby("author").hour.transform("min")
        burn = pd.Timestamp("2026-09-22", tz="UTC")
        live = live.assign(new_after_burn=(live.hour == first_seen) & (live.hour >= burn))
        live["default_name"] = live.author.str.match(DEFAULT_NAME)
        per_author = live.groupby("author").size()
        heavy = set(per_author[per_author >= per_author.quantile(0.99)].index)
        live["heavy"] = live.author.isin(heavy)
        base = dict(layer="io", group="Reddit: account-level indicators", role="reddit_accounts",
                    source="Arctic Shift Reddit archive API (raw comment stream)",
                    source_url=f"https://www.reddit.com/r/{sub}/", transform="count")
        add(f"rd.acc.{sub}.default_names", live[live.default_name].groupby("hour").size().reindex(HOURS).astype(float),
            label=f"r/{sub}: comments by default-pattern usernames",
            method="Reddit auto-generated username pattern (Word_Word1234); weak inauthenticity proxy", **base)
        add(f"rd.acc.{sub}.heavy", live[live.heavy].groupby("hour").size().reindex(HOURS).astype(float),
            label=f"r/{sub}: comments by top-1% most active accounts",
            method="Accounts in the top percentile of comment volume over the window", **base)
        add(f"rd.acc.{sub}.new_accounts", live[live.new_after_burn].groupby("hour").size().reindex(HOURS).astype(float),
            label=f"r/{sub}: first comments by previously unseen accounts",
            method="First observed comment of an account in this community after a 14-day burn-in", **base)
        add(f"rd.acc.{sub}.unique_authors", live.groupby("hour").author.nunique().reindex(HOURS).astype(float),
            label=f"r/{sub}: unique commenting accounts", method="Distinct authors per hour", **base)
        if titles is not None and len(titles):
            tmap = titles.set_index("id")["title"]
            c2 = live.assign(title=live.link_id.str.replace("t3_", "", regex=False).map(tmap))
            war = c2.title.fillna("").str.contains(WAR_TITLE)
            for theme, sub_df in (("war", c2[war]), ("other", c2[~war & c2.title.notna()])):
                add(f"rd.thr.{sub}.{theme}", sub_df.groupby("hour").size().reindex(HOURS).astype(float),
                    layer="io", group="Reddit: thread-theme split", role="reddit_threads", theme=theme,
                    label=f"r/{sub}: comments in {theme}-themed threads",
                    source="Arctic Shift Reddit archive API", source_url=f"https://www.reddit.com/r/{sub}/",
                    method="Thread theme from post title keywords", transform="count")


# ------------------------------------------------------------------ web publishing
def web():
    p = RAW / "web_articles.parquet"
    if not p.exists():
        return
    w = pd.read_parquet(p)
    w["hour"] = w.t_utc.dt.floor("h")
    lab = {"ukraina.ru": "ukraina.ru articles (RIA Novosti outlet for Ukrainian audiences)",
           "zona.media": "Mediazona articles (independent control)", "theins.ru": "The Insider articles (independent control)"}
    for (site, role), g in w.groupby(["site", "role"]):
        add(f"web.{site}", g.groupby("hour").size().reindex(HOURS, fill_value=0).astype(float),
            layer="io" if role == "io_web" else "control",
            group="Web publishing (state IO)" if role == "io_web" else "Web publishing (independent control)",
            role=role, label=lab.get(site, site), source=f"{site} public sitemaps", source_url=f"https://{site}/",
            method="Article publication timestamps from sitemaps, verified against article pages", transform="count")


# ------------------------------------------------------------------ outage trackers
YANDEX_RE = re.compile(r"(?:Яндекс|Yandex|Кинопоиск|Алиса|Алисы)", re.I)


def trackers():
    rows = []
    for h in ("sboyRF", "ru_downdetector_su"):
        p = RAW / "telegram" / f"_tracker_{h}.parquet"
        if p.exists():
            d = pd.read_parquet(p)
            d["src"] = h
            rows.append(d)
    if not rows:
        return
    d = pd.concat(rows)
    d["hour"] = d.t_utc.dt.floor("h")
    y = d.text.fillna("").str.contains(YANDEX_RE)
    base = dict(layer="services", group="Outage complaint trackers", unit="alerts per hour",
                source="Detector404 and Sboy.rf public Telegram alert channels",
                source_url="https://t.me/s/ru_downdetector_su", transform="count")
    add("trk.yandex", d[y].groupby("hour").size().reindex(HOURS, fill_value=0).astype(float), role="treated",
        label="Complaint alerts naming Yandex services", method="Threshold alerts whose text names a Yandex service", **base)
    add("trk.other", d[~y].groupby("hour").size().reindex(HOURS, fill_value=0).astype(float), role="control",
        label="Complaint alerts for non-Yandex services", method="All other threshold alerts", **base)
    d[["src", "t_utc", "text"]].assign(yandex=y).to_parquet(PROC / "tracker_alerts.parquet")


# ------------------------------------------------------------------ exposures
def exposures():
    e = pd.read_parquet(PROC / "eof_hourly.parquet")
    names = {"S0": "Stage 0 attack prior", "S1": "Stage 1 OSINT-conditioned", "S2": "Stage 2 telemetry-fused"}
    for (target, stage), g in e.groupby(["target", "stage"]):
        s = g.set_index("hour")
        for col in ("mean", "q05", "q25", "q50", "q75", "q95"):
            add(f"eof.{target}.{stage}.{col}", s[col], layer="exposure", group="Expected outage function",
                role="exposure", label=f"EOF {target} {names[stage]} ({col})", unit="expected capacity loss fraction",
                source="This study (model_outage.py)", source_url="", method=names[stage], transform="level")


def main():
    for fn in (infra, services, trackers, pravda, telegram, web, reddit, exposures):
        try:
            fn()
            print("ok", fn.__name__, len(META))
        except FileNotFoundError as e:
            print("skip", fn.__name__, e)
    panel = pd.concat(FRAMES, ignore_index=True)
    panel.to_parquet(PROC / "panel.parquet")
    save_json(META, PROC / "series_meta.json")
    print("series", len(META), "rows", len(panel))


if __name__ == "__main__":
    main()
