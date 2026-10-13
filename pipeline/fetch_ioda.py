"""Fetch IODA (Georgia Tech Internet Outage Detection and Analysis) raw signals.

Signals: ping-slash24 (active probing, responsive /24 blocks), bgp (visible /24
blocks), merit-nt (network telescope unique sources), gtr (Google traffic,
country level only). Native 5 or 10 minute resolution, stored long-format.
"""
from __future__ import annotations

import json
from datetime import timedelta

import pandas as pd

from common import PROC, RAW, STUDY_END, STUDY_START, get, ts

API = "https://api.ioda.inetintel.cc.gatech.edu/v2/signals/raw/{etype}/{code}"

ENTITIES = [
    # Treated Yandex networks
    ("asn", "200350", "Yandex.Cloud (AS200350)", "treated"),
    ("asn", "13238", "Yandex LLC (AS13238)", "treated"),
    ("asn", "44534", "Yandex office (AS44534)", "treated"),
    # Yandex network outside Russia (should not be hit by Russian DC strikes)
    ("asn", "208795", "Yandex Cloud Kazakhstan (AS208795)", "control_yandex_abroad"),
    # Russian hosting and cloud controls
    ("asn", "49505", "Selectel (AS49505)", "control_hosting"),
    ("asn", "9123", "Timeweb (AS9123)", "control_hosting"),
    ("asn", "198610", "Beget (AS198610)", "control_hosting"),
    ("asn", "47541", "VK (AS47541)", "control_platform"),
    # Russian access networks (mobile shutdown confounder)
    ("asn", "12389", "Rostelecom (AS12389)", "control_access"),
    ("asn", "8359", "MTS (AS8359)", "control_access"),
    ("asn", "31133", "MegaFon (AS31133)", "control_access"),
    ("asn", "3216", "Beeline (AS3216)", "control_access"),
    # Geography
    ("country", "RU", "Russia (national)", "national"),
    ("region", "3447", "Ryazan oblast (Sasovo DC)", "region_treated"),
    ("region", "3449", "Vladimir oblast (Vladimir DC)", "region_treated"),
    ("region", "3434", "Kaluga oblast (Kaluga DC)", "region_treated"),
    ("region", "3438", "Moscow city", "region_control"),
    ("region", "3423", "St. Petersburg", "region_control"),
]


def fetch_entity(etype: str, code: str):
    rows = []
    t = STUDY_START
    while t < STUDY_END:
        t2 = min(t + timedelta(days=7), STUDY_END)
        body = get(API.format(etype=etype, code=code),
                   params={"from": ts(t), "until": ts(t2)},
                   host_key="ioda", min_interval=1.5, timeout=180)
        if body:
            d = json.loads(body)
            for grp in d.get("data") or []:
                for s in grp:
                    ds = s["datasource"]
                    if ds in ("ping-slash24-latency", "upstream-delay-penult-asns",
                              "upstream-delay-penult-e2e-latency"):
                        continue  # nested structures, not needed
                    step, start = s["step"], s["from"]
                    for i, v in enumerate(s["values"]):
                        if isinstance(v, (int, float)) or v is None:
                            rows.append((start + i * step, ds, v))
        t = t2
    return rows


def main():
    frames = []
    for etype, code, label, role in ENTITIES:
        print(f"IODA {etype} {code} {label}")
        rows = fetch_entity(etype, code)
        df = pd.DataFrame(rows, columns=["epoch", "datasource", "value"])
        df["entity_type"], df["entity_code"], df["label"], df["role"] = etype, code, label, role
        frames.append(df)
        print(f"   {len(df)} points, sources: {sorted(df.datasource.unique())}")
    out = pd.concat(frames, ignore_index=True)
    out = out.drop_duplicates(["entity_type", "entity_code", "datasource", "epoch"])
    out.to_parquet(RAW / "ioda_raw.parquet")
    # Hourly aggregation (mean of native samples; coverage = share of non-null samples)
    out["hour"] = pd.to_datetime(out["epoch"], unit="s", utc=True).dt.floor("h")
    g = out.groupby(["entity_type", "entity_code", "label", "role", "datasource", "hour"])
    hourly = g["value"].agg(["mean", "min", "count", "size"]).reset_index()
    hourly["coverage"] = hourly["count"] / hourly["size"]
    hourly.to_parquet(PROC / "ioda_hourly.parquet")
    print("saved", len(hourly), "hourly rows")


if __name__ == "__main__":
    main()
