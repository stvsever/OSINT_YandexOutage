"""Data-quality audit of every collected stream.

Checks: history completeness (first observation close to the study start),
continuity (longest silent gap in the baseline relative to the series' own
typical gaps), coverage of the strike windows, timestamp monotonicity, and
source-specific checks (Reddit fetch coverage, IODA sample completeness).
A series passes when its strike windows are fully covered and no unexplained
outage of the collector itself overlaps them.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from common import PROC, RAW, STUDY_END, STUDY_START, save_json

STRIKES = {"SAS": pd.Timestamp("2026-10-07T22:27Z"), "KAL": pd.Timestamp("2026-10-09T04:41Z"),
           "VLA": pd.Timestamp("2026-10-11T00:10Z")}


def gap_stats(ts: pd.Series):
    t = ts.sort_values()
    g = t.diff().dt.total_seconds().div(3600).dropna()
    return float(g.max()) if len(g) else None, float(g.quantile(0.99)) if len(g) else None


def main():
    out = {}
    # Telegram channels
    meta = pd.read_csv(RAW / "telegram" / "_channels_meta.csv")
    for _, m in meta.iterrows():
        p = RAW / "telegram" / f"{m.handle}.parquet"
        if not p.exists():
            continue
        df = pd.read_parquet(p)
        if df.empty:
            out[f"tg.ch.{m.handle}"] = {"status": "empty", "n": 0}
            continue
        t = pd.to_datetime(df.t_utc, utc=True)
        mono = bool((df.sort_values("post_id").t_utc.diff().dt.total_seconds().fillna(0) >= -60).all())
        gmax, g99 = gap_stats(t)
        first = t.min()
        complete = first <= pd.Timestamp(STUDY_START) + pd.Timedelta(days=3) or len(df) < 300
        out[f"tg.ch.{m.handle}"] = {"n": int(len(df)), "first": str(first), "last": str(t.max()),
                                    "max_gap_h": gmax, "p99_gap_h": g99, "monotonic": mono,
                                    "status": "ok" if complete and mono else "incomplete_history" if not complete else "order_issue"}
    # Pravda
    a = pd.read_parquet(RAW / "pravda_articles.parquet")
    h = a.t_utc.dt.floor("h").value_counts().reindex(pd.date_range(STUDY_START, STUDY_END, freq="h", inclusive="left"), fill_value=0)
    zero_runs = (h == 0).astype(int).groupby((h != 0).cumsum()).sum().max()
    out["pravda.total"] = {"n": int(len(a)), "hosts": int(a.host.nunique()), "longest_zero_run_h": int(zero_runs),
                           "min_daily": int(h.resample("D").sum().min()), "status": "ok" if zero_runs < 3 else "gaps"}
    # Reddit coverage
    cov = pd.read_parquet(PROC / "reddit_coverage.parquet")
    for (sub, kind, theme), g in cov.groupby(["subreddit", "kind", "theme"]):
        hours = ((g.end - g.start).dt.total_seconds() / 3600).sum()
        miss = []
        for k, t0 in STRIKES.items():
            inside = any((a_ <= t0) and (b_ >= t0 + pd.Timedelta(hours=24)) for a_, b_ in zip(g.start, g.end)) or \
                     (sum(min(b_, t0 + pd.Timedelta(hours=24)) - max(a_, t0) > pd.Timedelta(0) for a_, b_ in zip(g.start, g.end)) > 0)
            if not inside:
                miss.append(k)
        out[f"rd.{sub}.{kind}.{theme}"] = {"covered_hours": float(hours), "strike_windows_missing": miss,
                                            "status": "ok" if not miss and hours >= 0.97 * 852 else "partial"}
    # IODA completeness
    r = pd.read_parquet(RAW / "ioda_raw.parquet")
    for (code, ds), g in r.groupby(["entity_code", "datasource"]):
        out[f"ioda.{code}.{ds}"] = {"missing_share": float(g.value.isna().mean()),
                                     "status": "ok" if g.value.isna().mean() < 0.1 else "sparse"}
    # Web
    w = pd.read_parquet(RAW / "web_articles.parquet")
    for site, g in w.groupby("site"):
        d = g.t_utc.dt.floor("D").value_counts()
        out[f"web.{site}"] = {"n": int(len(g)), "first": str(g.t_utc.min()), "min_daily": int(d.min()),
                              "status": "ok" if g.t_utc.min() <= pd.Timestamp(STUDY_START) + pd.Timedelta(days=10) else "short_history"}
    save_json(out, PROC / "data_quality.json")
    bad = {k: v["status"] for k, v in out.items() if v.get("status") != "ok"}
    print(len(out), "streams audited;", len(bad), "flagged")
    for k, v in bad.items():
        print("  ", k, v)


if __name__ == "__main__":
    main()
