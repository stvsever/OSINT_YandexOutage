"""Auxiliary open sources: RIPE Stat BGP activity, NASA FIRMS thermal anomalies,
Wikimedia hourly pageviews.
"""
from __future__ import annotations

import io
import json
import math
from datetime import timedelta

import pandas as pd

from common import PROC, RAW, STUDY_END, STUDY_START, get

# ---------------------------------------------------------------- RIPE Stat
RIPE_ASNS = {"200350": "Yandex.Cloud", "13238": "Yandex LLC", "208795": "Yandex Cloud KZ",
             "49505": "Selectel", "47541": "VK"}


def ripe_bgp():
    rows = []
    for asn, name in RIPE_ASNS.items():
        t = STUDY_START
        while t < STUDY_END:
            t2 = min(t + timedelta(days=4), STUDY_END)
            body = get("https://stat.ripe.net/data/bgp-update-activity/data.json",
                       {"resource": f"AS{asn}", "starttime": t.strftime("%Y-%m-%dT%H:%M"),
                        "endtime": t2.strftime("%Y-%m-%dT%H:%M"), "max_samples": 200,
                        "min_sampling_period": 3600, "hide_empty_samples": "false"},
                       host_key="ripestat", min_interval=1.0)
            if body:
                d = json.loads(body)["data"]
                for u in d.get("updates", []):
                    rows.append((asn, name, u["starttime"], u.get("announcements") or 0,
                                 u.get("withdrawals") or 0, d.get("sampling_period")))
            t = t2
        print("RIPE", asn, name, sum(1 for r in rows if r[0] == asn), "bins")
    df = pd.DataFrame(rows, columns=["asn", "name", "start", "announcements", "withdrawals", "period_s"])
    df["hour"] = pd.to_datetime(df["start"], utc=True)
    df.to_parquet(PROC / "ripe_bgp_hourly.parquet")


# ---------------------------------------------------------------- NASA FIRMS
FIRMS = {
    "VIIRS_SNPP": "https://firms.modaps.eosdis.nasa.gov/data/active_fire/suomi-npp-viirs-c2/csv/SUOMI_VIIRS_C2_Russia_Asia_7d.csv",
    "VIIRS_NOAA20": "https://firms.modaps.eosdis.nasa.gov/data/active_fire/noaa-20-viirs-c2/csv/J1_VIIRS_C2_Russia_Asia_7d.csv",
    "VIIRS_NOAA21": "https://firms.modaps.eosdis.nasa.gov/data/active_fire/noaa-21-viirs-c2/csv/J2_VIIRS_C2_Russia_Asia_7d.csv",
    "MODIS": "https://firms.modaps.eosdis.nasa.gov/data/active_fire/modis-c6.1/csv/MODIS_C6_1_Russia_Asia_7d.csv",
}
# Approximate site coordinates; refined from the event catalog when available.
SITES = {"Sasovo": (54.342, 41.918), "Vladimir": (56.141, 40.388), "Kaluga": (54.514, 36.262)}


def haversine(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def firms(sites=SITES):
    out = []
    for sensor, url in FIRMS.items():
        raw = get(url, host_key="firms", min_interval=1.0, binary=True, timeout=300)
        if not raw:
            continue
        (RAW / "firms").mkdir(exist_ok=True)
        (RAW / "firms" / f"{sensor}.csv").write_bytes(raw)
        df = pd.read_csv(io.BytesIO(raw))
        for site, (la, lo) in sites.items():
            box = df[(df.latitude.between(la - 0.6, la + 0.6)) & (df.longitude.between(lo - 1.0, lo + 1.0))].copy()
            if box.empty:
                continue
            box["km"] = [haversine(la, lo, a, b) for a, b in zip(box.latitude, box.longitude)]
            box = box[box.km <= 25]
            box["site"], box["sensor"] = site, sensor
            out.append(box)
        print("FIRMS", sensor, len(df), "rows")
    if out:
        res = pd.concat(out, ignore_index=True)
        res["t_utc"] = pd.to_datetime(res.acq_date + " " + res.acq_time.astype(str).str.zfill(4),
                                      format="%Y-%m-%d %H%M", utc=True)
        res.to_parquet(PROC / "firms_sites.parquet")
        print(res[["site", "sensor", "t_utc", "km", "frp", "confidence"]].sort_values("t_utc").to_string())


# ---------------------------------------------------------------- Wikimedia
WIKI = [("ru.wikipedia", "all-access"), ("ru.wikipedia", "desktop"), ("ru.wikipedia", "mobile-web"),
        ("ru.wikipedia", "mobile-app"), ("uk.wikipedia", "all-access"), ("de.wikipedia", "all-access"),
        ("en.wikipedia", "all-access"), ("kk.wikipedia", "all-access")]


def wikimedia():
    rows = []
    a = STUDY_START.strftime("%Y%m%d%H")
    b = STUDY_END.strftime("%Y%m%d%H")
    for proj, access in WIKI:
        body = get(f"https://wikimedia.org/api/rest_v1/metrics/pageviews/aggregate/{proj}/{access}/user/hourly/{a}/{b}",
                   host_key="wikimedia", min_interval=0.5)
        if not body:
            continue
        for it in json.loads(body).get("items", []):
            rows.append((proj, access, pd.to_datetime(it["timestamp"], format="%Y%m%d%H", utc=True),
                         it["views"]))
        print("WIKI", proj, access, "ok")
    pd.DataFrame(rows, columns=["project", "access", "hour", "views"]).to_parquet(PROC / "wikimedia_hourly.parquet")


if __name__ == "__main__":
    ripe_bgp()
    wikimedia()
    firms()
