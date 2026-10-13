"""Export every analysis product into dashboard/data/*.js (window globals).

The dashboard is static (works from file:// and GitHub Pages), so data are
written as JavaScript assignments rather than fetched JSON.
"""
from __future__ import annotations

import json
import math

import numpy as np
import pandas as pd

from common import BASELINE_END, PROC, ROOT, STUDY_END, STUDY_START

OUT = ROOT / "docs" / "data"
OUT.mkdir(parents=True, exist_ok=True)


def r(x, nd=3):
    if x is None:
        return None
    try:
        if not math.isfinite(float(x)):
            return None
    except (TypeError, ValueError):
        return x
    return round(float(x), nd)


def clean(o, nd=4):
    if isinstance(o, dict):
        return {k: clean(v, nd) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v, nd) for v in o]
    if isinstance(o, (float, np.floating)):
        return r(o, nd)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return o


def write(name, obj):
    txt = json.dumps(clean(obj), ensure_ascii=False, separators=(",", ":"))
    (OUT / f"{name}.js").write_text(f"window.{name.upper()}={txt};\n")
    print(f"{name}.js {len(txt) / 1e6:.2f} MB")


# --------------------------------------------------------------------- sources and events
# Every item below was opened and read for this study (13 Oct 2026). Admiralty
# grades: reliability A to F of the source, credibility 1 to 6 of the item.
SOURCES = [
    dict(id="SRC-YCS-2092", name="Yandex Cloud status page, incident 2092", type="Official operator statement",
         url="https://status.yandex.cloud/ru/incidents/2092", rel="B", cred=1, lang="ru",
         note="Opened 22:31:24 UTC 7 Oct: power interruptions in availability zone ru-central1-b; 12:19 UTC 8 Oct: cause was a fire from a UAV attack on the Sasovo data center, operation fully stopped."),
    dict(id="SRC-YCS-2136", name="Yandex Cloud status page, incident 2136", type="Official operator statement",
         url="https://status.yandex.cloud/ru/incidents/2136", rel="B", cred=1, lang="ru",
         note="Start time 01:00 UTC 11 Oct, unavailability of Yandex Cloud zones; 03:08 UTC: Vladimir data center operation fully stopped after UAV attack, platform in emergency mode."),
    dict(id="SRC-YCS-LIST", name="Yandex Cloud status page, incident list API", type="Official operator statement",
         url="https://status.yandex.cloud/api/incidents", rel="B", cred=2, lang="ru",
         note="Full incident list 1 Sep to 13 Oct. No zone incident for Kaluga (9 Oct). No incident covering the 27 to 28 Sep reachability dip."),
    dict(id="SRC-YTG-5900", name="Yandex official Telegram, post 5900", type="Official operator statement",
         url="https://t.me/yandex/5900", rel="B", cred=1, lang="ru",
         note="08:46 UTC 9 Oct: Sasovo seriously damaged on the night of 7 to 8 Oct, operation completely stopped; Kaluga attacked this morning, part of infrastructure failed."),
    dict(id="SRC-YTG-5901", name="Yandex official Telegram, post 5901", type="Official operator statement",
         url="https://t.me/yandex/5901", rel="B", cred=1, lang="ru",
         note="08:21 UTC 11 Oct: data-center infrastructure damaged, failures in Yandex services possible, support affected."),
    dict(id="SRC-YTG-5903", name="Yandex official Telegram, post 5903 (Yandex Pay)", type="Official operator statement",
         url="https://t.me/yandex/5903", rel="B", cred=2, lang="ru",
         note="18:42 UTC 11 Oct: another data center damaged this morning; many users cannot check balances or pay."),
    dict(id="SRC-YTG-5905", name="Yandex official Telegram, post 5905 (B2B Tech)", type="Official operator statement",
         url="https://t.me/yandex/5905", rel="B", cred=2, lang="ru",
         note="09:27 UTC 13 Oct: fees waived for Yandex Cloud and Yandex 360 customers; services still limited, restoration continuing."),
    dict(id="SRC-GOV-10997", name="Vladimir governor Avdeev, Telegram post 10997", type="Regional official",
         url="https://t.me/avdeev_o_vazhnom/10997", rel="B", cred=2, lang="ru",
         note="04:02 UTC 11 Oct: night drone attack on infrastructure on the outskirts of Vladimir, fire, two substations disconnected."),
    dict(id="SRC-FIRMS", name="NASA FIRMS VIIRS active fire detections", type="Satellite remote sensing",
         url="https://firms.modaps.eosdis.nasa.gov/", rel="A", cred=2, lang="en",
         note="Thermal anomalies at 54.373 N, 41.936 E (Sasovo industrial site): NOAA-20 22:40 UTC, NOAA-21 23:24 UTC (7.3 MW), 00:20 and 01:05 UTC 8 Oct."),
    dict(id="SRC-CFR-BSKY", name="Cloudflare Radar, Bluesky post", type="Third-party telemetry report",
         url="https://bsky.app/profile/radar.cloudflare.com", rel="A", cred=2, lang="en",
         note="09:14 UTC 8 Oct: traffic from Yandex Cloud (AS200350) dropped starting around 22:30 UTC on 7 Oct, about 33 percent below normal."),
    dict(id="SRC-NB-BSKY", name="NetBlocks, Bluesky posts", type="Third-party telemetry report",
         url="https://bsky.app/profile/netblocks.org", rel="B", cred=2, lang="en",
         note="01:22 UTC 8 Oct, 05:30 UTC 11 Oct and 13:44 UTC 12 Oct: disruption, second collapse and no recovery; charts give Yandex Cloud 30 percent and YANDEX LLC 63 percent of normal."),
    dict(id="SRC-IODA", name="IODA, Georgia Tech (raw signals API)", type="Measurement data",
         url="https://ioda.inetintel.cc.gatech.edu/asn/200350", rel="A", cred=1, lang="en",
         note="Active probing, BGP and telescope signals at 5 to 10 minute resolution for 18 networks and regions."),
    dict(id="SRC-RIPE", name="RIPE Stat BGP update activity", type="Measurement data",
         url="https://stat.ripe.net/AS200350", rel="A", cred=1, lang="en", note="Hourly BGP announcements for Yandex and control ASNs."),
    dict(id="SRC-TRK", name="Detector404 and Sboy.rf complaint alert channels", type="Crowdsourced outage tracker",
         url="https://t.me/s/ru_downdetector_su", rel="C", cred=3, lang="ru",
         note="Threshold alerts on user complaints; first Yandex alert of 11 Oct at 00:47 UTC; Yandex Pay alert at 23:14 UTC 7 Oct."),
    dict(id="SRC-PRAVDA", name="Pravda network public sitemaps", type="Measurement data",
         url="https://news-pravda.com/sitemap.xml", rel="A", cred=1, lang="multi",
         note="806,762 article timestamps on 88 subdomains, 1 Sep to 13 Oct; lastmod equals published_time (verified)."),
    dict(id="SRC-TG", name="Telegram public channel previews (54 channels)", type="Measurement data",
         url="https://t.me/s/rybar", rel="A", cred=1, lang="multi", note="Post timestamps and text for pro-Kremlin, IO, independent, Ukrainian and non-political channels."),
    dict(id="SRC-RD", name="Arctic Shift Reddit archive", type="Measurement data",
         url="https://arctic-shift.photon-reddit.com/", rel="A", cred=2, lang="en",
         note="Hourly counts for 18 communities and raw comment stream of r/UkraineRussiaReport; aggregate bucket labels corrected by +2 h (verified)."),
    dict(id="SRC-WIKI", name="Wikimedia pageviews API", type="Measurement data",
         url="https://wikimedia.org/api/rest_v1/", rel="A", cred=1, lang="en", note="Hourly user, spider and automated pageviews."),
    dict(id="SRC-DNS", name="Public DNS records (A, MX, NS) via 1.1.1.1, 8.8.8.8 and 9.9.9.9", type="Measurement data",
         url="https://stat.ripe.net/", rel="A", cred=1, lang="en",
         note="Hosting networks (RIPE Stat network-info), mail exchangers and name servers of 52 IO, state, independent and Yandex domains on 13 Oct 2026, and of 342 domains attributed to influence operations by VIGINUM and the EEAS on 13 to 14 Oct."),
    dict(id="SRC-WEB", name="Web sitemaps of ukraina.ru, zona.media and theins.ru", type="Measurement data",
         url="https://ukraina.ru/sitemap_article_index.xml", rel="A", cred=1, lang="ru",
         note="Article publication timestamps, verified against the published_time of article pages."),
    dict(id="SRC-EEAS", name="EEAS, 4th Report on FIMI Threats (March 2026)", type="Official attribution report",
         url="https://www.eeas.europa.eu/sites/default/files/2026/documents/EEAS%204th%20Threat%20Report_web%20version_1.pdf",
         rel="A", cred=2, lang="en",
         note="Names the Russia-aligned IMS used here: Portal Kombat (Pravda), Storm-1516, Operation Overload, Doppelganger, RRN/Media Brands, African Initiative; sanctioned enablers SDA, Tigerweb, John Mark Dougan."),
    dict(id="SRC-VIGINUM", name="VIGINUM technical report on Storm-1516 (May 2025)", type="Official attribution report",
         url="https://www.sgdsn.gouv.fr/files/files/Publications/20250507_TLP-CLEAR_NP_SGDSN_VIGINUM_Technical%20report_Storm-1516.pdf",
         rel="A", cred=2, lang="en", note="Appendix 6.2 lists 338 domains linked to CopyCop / Storm-1516; all were resolved and tested for Yandex dependency."),
    dict(id="SRC-WP", name="WordPress REST API of African Initiative, RRN and R-FBI sites", type="Measurement data",
         url="https://afrinz.ru/wp-json/wp/v2/posts", rel="A", cred=1, lang="multi",
         note="Exact publication times (date_gmt) of 3,264 articles, 1 Sep to 13 Oct 2026."),
    dict(id="SRC-REUTERS", name="Reuters, 8 Oct 2026", type="Media",
         url="https://www.reuters.com/world/europe/russias-yandex-says-unclear-whether-data-centre-can-be-restored-after-drone-2026-10-08/",
         rel="A", cred=2, lang="en", note="Yandex said it was unclear whether the Sasovo data center could be restored; site housed two of three AI supercomputers."),
]

EVENTS = [
    dict(id="EV-SAS-STRIKE", t="2026-10-07T22:27:00Z", kind="strike", site="Sasovo", title="Sasovo strike (posterior)",
         detail="Posterior impact time from the OSINT-conditioned model: status page 22:31, Cloudflare traffic step about 22:30, FIRMS fire 22:40 UTC.",
         sources=["SRC-YCS-2092", "SRC-CFR-BSKY", "SRC-FIRMS", "SRC-YTG-5900", "SRC-REUTERS"]),
    dict(id="EV-SAS-STATUS", t="2026-10-07T22:31:24Z", kind="statement", site="Sasovo", title="Status page: power interruptions in ru-central1-b",
         detail="Yandex Cloud opens incident 2092 and advises customers to move load to other zones.", sources=["SRC-YCS-2092"]),
    dict(id="EV-SAS-FIRMS", t="2026-10-07T22:40:00Z", kind="telemetry", site="Sasovo", title="FIRMS: first thermal anomaly at the Sasovo site",
         detail="NOAA-20 VIIRS detection 3.6 km from the reference point; NOAA-21 at 23:24 UTC with 7.3 MW radiative power.", sources=["SRC-FIRMS"]),
    dict(id="EV-SAS-IODA", t="2026-10-07T23:05:00Z", kind="telemetry", site="Sasovo", title="IODA: Yandex Cloud reachability starts to fall",
         detail="Responsive /24 blocks fall from 518 to about 340 between 23:20 and 00:40 UTC (34 percent of the zone set).", sources=["SRC-IODA"]),
    dict(id="EV-SAS-NB", t="2026-10-08T01:22:43Z", kind="telemetry", site="Sasovo", title="NetBlocks confirms disruption",
         detail="First public third-party confirmation of the network loss.", sources=["SRC-NB-BSKY"]),
    dict(id="EV-SAS-CAUSE", t="2026-10-08T12:19:19Z", kind="statement", site="Sasovo", title="Status page: fire from UAV attack, data center stopped",
         detail="Yandex Cloud attributes the incident to a fire caused by a UAV attack on the Sasovo data center.", sources=["SRC-YCS-2092"]),
    dict(id="EV-OCT8-WAVE", t="2026-10-08T12:30:00Z", kind="confounder", site="Russia", title="Multi-service complaint burst (non-Yandex)",
         detail="Complaint alerts for many non-Yandex services between about 12:30 and 13:40 UTC 8 Oct; visible in the tracker control series.", sources=["SRC-TRK"]),
    dict(id="EV-KAL-STMT", t="2026-10-09T08:46:48Z", kind="statement", site="Kaluga", title="Yandex: Kaluga attacked, part of infrastructure failed",
         detail="No Yandex Cloud zone incident followed and IODA shows no step: Kaluga damage did not reach externally reachable cloud capacity.", sources=["SRC-YTG-5900", "SRC-YCS-LIST"]),
    dict(id="EV-VLA-TRK", t="2026-10-11T00:47:05Z", kind="telemetry", site="Vladimir", title="Complaint alert: Yandex services",
         detail="First complaint-threshold alert naming Yandex on 11 Oct.", sources=["SRC-TRK"]),
    dict(id="EV-VLA-STATUS", t="2026-10-11T01:00:00Z", kind="statement", site="Vladimir", title="Status page: unavailability of Yandex Cloud zones",
         detail="Yandex Cloud incident 2136 start time.", sources=["SRC-YCS-2136"]),
    dict(id="EV-VLA-IODA", t="2026-10-11T01:38:00Z", kind="telemetry", site="Vladimir", title="IODA: second reachability collapse",
         detail="Responsive /24 blocks fall from about 340 to 112 between 01:40 and 02:00 UTC; 78 percent of the pre-strike set unreachable.", sources=["SRC-IODA"]),
    dict(id="EV-VLA-STOP", t="2026-10-11T03:08:12Z", kind="statement", site="Vladimir", title="Status page: Vladimir data center stopped",
         detail="Platform in emergency mode; remaining configuration considered unstable.", sources=["SRC-YCS-2136"]),
    dict(id="EV-VLA-GOV", t="2026-10-11T04:02:13Z", kind="statement", site="Vladimir", title="Governor: night drone attack, fire, substations off",
         detail="Regional confirmation of the strike on infrastructure on the outskirts of Vladimir.", sources=["SRC-GOV-10997"]),
    dict(id="EV-VLA-NB", t="2026-10-11T05:30:41Z", kind="telemetry", site="Vladimir", title="NetBlocks: second collapse",
         detail="Yandex Cloud about 30 percent and YANDEX LLC about 63 percent of normal connectivity.", sources=["SRC-NB-BSKY"]),
    dict(id="EV-PAY", t="2026-10-11T18:42:45Z", kind="statement", site="Vladimir", title="Yandex Pay still disrupted",
         detail="Payments and balance checks unavailable for many users.", sources=["SRC-YTG-5903"]),
    dict(id="EV-B2B", t="2026-10-13T09:27:06Z", kind="statement", site="Yandex", title="Fees waived; services still limited",
         detail="Yandex B2B Tech waives fees for all Yandex Cloud and Yandex 360 customers.", sources=["SRC-YTG-5905"]),
    dict(id="EV-SEP27", t="2026-09-27T06:00:00Z", kind="confounder", site="Yandex Cloud", title="Unexplained reachability dip (no incident filed)",
         detail="IODA shows Yandex Cloud down to about 300 /24 blocks for 32 hours, with a concurrent Russia-wide dip; no status incident. Used as an internal placebo.",
         sources=["SRC-IODA", "SRC-YCS-LIST"]),
]


def main():
    panel = pd.read_parquet(PROC / "panel.parquet")
    meta = json.loads((PROC / "series_meta.json").read_text())
    an = json.loads((PROC / "analysis_results.json").read_text())
    A = pd.read_parquet(PROC / "anomalies.parquet")
    CF = pd.read_parquet(PROC / "counterfactuals.parquet")
    wide = panel.pivot(index="hour", columns="series_id", values="value").sort_index()
    hours = wide.index
    series = {}
    for sid, m in meta.items():
        if m["layer"] == "exposure" and not sid.startswith("exposure."):
            continue
        rec = dict(m)
        if m.get("hidden"):
            st = an["series"].get(sid)
            if st:
                rec["stats"] = {k: st[k] for k in ("windows", "verdict", "baseline_mean", "mde80_vla24", "completeness")
                                if k in st}
                series[sid] = rec
            continue
        rec["v"] = [r(x, 3) for x in wide[sid].to_numpy()]
        if sid in A:
            rec["cf"] = [r(x, 2) for x in CF[sid].reindex(hours).to_numpy()]
            rec["a"] = [r(x, 3) for x in A[sid].reindex(hours).to_numpy()]
        st = an["series"].get(sid)
        if st:
            rec["stats"] = {k: v for k, v in st.items() if k not in ("series_id",)}
        series[sid] = rec
    write("series", {"t0": str(hours[0]), "n": len(hours), "series": series})

    eof = pd.read_parquet(PROC / "eof_hourly.parquet")
    eof10 = pd.read_parquet(PROC / "eof_10min.parquet")
    res = json.loads((PROC / "eof_results.json").read_text())
    traj = json.loads((PROC / "eof_trajectories.json").read_text())
    pred = pd.read_parquet(PROC / "eof_predictive_hourly.parquet")
    io = pd.read_parquet(PROC / "ioda_cloud_unreachable_hourly.parquet")["ioda_unreachable_frac"]
    E = {"hourly": {}, "hi": {}}
    for (tg, st), g in eof.groupby(["target", "stage"]):
        g = g.set_index("hour").reindex(hours)
        E["hourly"].setdefault(tg, {})[st] = {c: [r(x, 4) for x in g[c]] for c in ("mean", "q05", "q25", "q50", "q75", "q95")}
    for (tg, st), g in eof10.groupby(["target", "stage"]):
        E["hi"].setdefault(tg, {})[st] = {c: [r(x, 4) for x in g[c]] for c in ("mean", "q05", "q25", "q50", "q75", "q95")}
    E["hi_t0"] = str(eof10.t.min())
    for st, g in pred.groupby("stage"):
        g = g.set_index("hour").reindex(hours)
        E.setdefault("pred", {})[st] = {c: [r(x, 4) for x in g[c]] for c in ("p05", "p50", "p95")}
    E["ioda_obs"] = [r(x, 4) for x in io.reindex(hours)]
    E["traj"] = traj
    E["config"] = res["config"]
    E["validation"] = res["validation_vs_ioda"]
    E["downtime"] = res["downtime"]
    E["stages"] = res["stages"]
    E["credibility"] = res["event_credibility"]
    E["telemetry_info"] = res["telemetry_info"]
    write("eof", E)

    tim = json.loads((PROC / "timing_results.json").read_text())
    write("timing", tim)

    fir = pd.read_parquet(PROC / "firms_sites.parquet")
    firms = [dict(t=str(x.t_utc), site=x.site, km=r(x.km, 2), frp=r(x.frp, 2), sensor=x.sensor,
                  lat=r(x.latitude, 4), lon=r(x.longitude, 4)) for x in fir.itertuples() if x.km < 10]
    trk = pd.read_parquet(PROC / "tracker_alerts.parquet")
    trk = trk[(trk.t_utc >= "2026-10-05")]
    alerts = [dict(t=str(x.t_utc), src=x.src, yandex=bool(x.yandex), text=x.text[:160].replace("\u2014", "-").replace("\u2013", "-")) for x in trk.itertuples()]
    actor = json.loads((PROC / "actor_infra.json").read_text())
    verification = json.loads((PROC / "verification.json").read_text())
    infra = json.loads((PROC / "infra_map.json").read_text())
    infra = [{k: d[k] for k in ("domain", "role", "asn_holders", "yandex_hosting", "yandex_mail", "yandex_dns", "mx")} for d in infra]
    quality = json.loads((PROC / "data_quality.json").read_text())
    quality = {k: {"status": v["status"]} for k, v in quality.items()}
    write("bayes", json.loads((PROC / "bayes_results.json").read_text()))
    write("evidence", {"sources": SOURCES, "events": EVENTS, "firms": firms, "alerts": alerts, "infra": infra, "quality": quality,
                       "actor_infra": [{k: d[k] for k in ("domain", "ims", "resolves", "http", "holder", "yandex_hosting", "yandex_mail", "yandex_dns")} for d in actor],
                       "verification": verification,
                       "analysis": {k: an[k] for k in ("onsets", "sesoi", "lags", "event_window", "contrasts", "pooled")},
                       "meta": {"study_start": str(STUDY_START), "study_end": str(STUDY_END),
                                "baseline_end": str(BASELINE_END),
                                "generated": pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M UTC")}})


if __name__ == "__main__":
    main()
