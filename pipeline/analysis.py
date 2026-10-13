"""Attribution analysis: do IO output series move with the expected outage?

For every hourly series y(t):
  1. Seasonal counterfactual. OLS on log1p(y) with trend, hour-of-day,
     day-of-week and weekend-by-hour terms, fitted on the pre-strike baseline.
     Baseline anomalies are cross-validated (leave-one-day-out refits), post-
     period anomalies are forecasts from the full-baseline fit, so every
     anomaly A(t) is out of sample.
  2. Event windows. Mean anomaly in the 6 h and 24 h after each outage onset,
     compared with every same-length window in the baseline (placebo-in-time
     randomisation), giving one-sided p-values for a drop, an empirical 90 %
     interval for the effect, and the minimum detectable effect.
  3. Dose-response. A(t) regressed on the expected outage function E(t)
     (Stage 1 OSINT-only, Stage 2 telemetry-fused, measured IODA), Newey-West
     HAC errors, plus a placebo distribution from time-shifted exposure and a
     lag profile from -48 h to +48 h (a causal effect peaks at lags >= 0).
  4. Equivalence (TOST style). The smallest effect of interest is a 20 % drop;
     a series "rules out" such a drop when the 90 % interval excludes it.
  5. Multiple testing. Benjamini-Hochberg across IO outcome series.
  6. Theme contrasts. War minus non-war anomalies for paired series.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
from scipy import stats

from common import BASELINE_END, PROC, save_json

SESOI = 0.20
LAGS = list(range(-48, 49, 2))
EVENT_WIN = (-48, 72)


def design(index: pd.DatetimeIndex) -> np.ndarray:
    hod = index.hour.to_numpy()
    dow = index.dayofweek.to_numpy()
    wk = (dow >= 5).astype(float)
    t = (index - index[0]).total_seconds().to_numpy() / 86400.0
    cols = [np.ones(len(index)), t / 30.0]
    cols += [(hod == h).astype(float) for h in range(1, 24)]
    cols += [(dow == d).astype(float) for d in range(1, 7)]
    cols += [((hod == h) & (wk == 1)).astype(float) for h in range(1, 24)]
    return np.column_stack(cols)


def fit(X, y, ridge=1e-3):
    XtX = X.T @ X + ridge * np.eye(X.shape[1])
    return np.linalg.solve(XtX, X.T @ y)


def anomalies(y: pd.Series, onsets):
    """Out-of-sample log anomalies and counterfactual for one hourly series."""
    idx = y.index
    ly = np.log1p(y.to_numpy(dtype=float))
    valid = np.isfinite(ly)
    X = design(idx)
    base = valid & (idx < BASELINE_END)
    if base.sum() < 24 * 10:
        return None
    b = fit(X[base], ly[base])
    pred = X @ b
    A = ly - pred
    # leave-one-day-out cross-validated residuals for baseline days
    days = idx.floor("D")
    bdays = np.unique(days[base])
    A_cv = np.full(len(idx), np.nan)
    for d in bdays:
        m = days == d
        train = base & ~m
        if train.sum() < 24 * 7:
            continue
        bd = fit(X[train], ly[train])
        A_cv[m & base] = ly[m & base] - X[m & base] @ bd
    A_out = np.where(base, A_cv, A)
    A_out[~valid] = np.nan
    cf = np.expm1(pred)
    return pd.Series(A_out, idx), pd.Series(cf, idx), float(np.nanstd(A_cv[base]))


def window_stats(A: pd.Series, onset: pd.Timestamp, L: int, first_valid: pd.Timestamp):
    idx = A.index
    obs_mask = (idx >= onset) & (idx < onset + pd.Timedelta(hours=L))
    obs = A[obs_mask].mean()
    # placebo windows wholly inside the baseline, after a 10-day warm-up
    a = A[(idx < BASELINE_END) & (idx >= first_valid + pd.Timedelta(days=10))].dropna()
    if len(a) < L * 4 or not np.isfinite(obs):
        return None
    roll = a.rolling(L).mean().dropna().to_numpy()
    p_drop = (1 + (roll <= obs).sum()) / (1 + len(roll))
    p_two = (1 + (np.abs(roll - np.median(roll)) >= abs(obs - np.median(roll))).sum()) / (1 + len(roll))
    q05, q95 = np.quantile(roll, [0.05, 0.95])
    sd = roll.std()
    mde = (stats.norm.ppf(0.95) + stats.norm.ppf(0.80)) * sd
    eff = float(np.expm1(obs))
    lo, hi = float(np.expm1(obs - q95)), float(np.expm1(obs - q05))
    return dict(L=L, anomaly=float(obs), effect=eff, ci90=[lo, hi], p_drop=float(p_drop),
                p_two=float(p_two), placebo_sd=float(sd), mde80=float(-np.expm1(-mde)),
                rules_out_sesoi_drop=bool(lo > -SESOI), n_placebo=int(len(roll)))


def naive_window(y: pd.Series, onset: pd.Timestamp, L: int, weeks=(1, 2, 3)):
    """Seasonal-naive check: window total vs the same hours 1 to 3 weeks earlier,
    calibrated against the same statistic for every baseline window."""
    idx = y.index

    def ratio(t0):
        m = (idx >= t0) & (idx < t0 + pd.Timedelta(hours=L))
        o = y[m].sum(min_count=L)
        refs = []
        for w in weeks:
            mm = (idx >= t0 - pd.Timedelta(weeks=w)) & (idx < t0 - pd.Timedelta(weeks=w) + pd.Timedelta(hours=L))
            refs.append(y[mm].sum(min_count=L))
        refs = [r for r in refs if np.isfinite(r)]
        if not np.isfinite(o) or len(refs) < 2 or np.mean(refs) <= 0:
            return np.nan
        return np.log((o + 1) / (np.mean(refs) + 1))
    obs = ratio(onset.floor("h"))
    starts = idx[(idx >= idx[0] + pd.Timedelta(weeks=3)) & (idx <= BASELINE_END - pd.Timedelta(hours=L))][::2]
    null = np.array([ratio(t) for t in starts])
    null = null[np.isfinite(null)]
    if not np.isfinite(obs) or len(null) < 30:
        return None
    return dict(effect=float(np.expm1(obs)), p_drop=float((1 + (null <= obs).sum()) / (1 + len(null))),
                ci90=[float(np.expm1(obs - np.quantile(null, 0.95))), float(np.expm1(obs - np.quantile(null, 0.05)))])


def hac_slope(x, y, lags=24):
    m = np.isfinite(x) & np.isfinite(y)
    x, y = x[m], y[m]
    if len(x) < 50 or np.var(x) == 0:
        return None
    X = np.column_stack([np.ones(len(x)), x])
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    u = y - X @ b
    n = len(y)
    S = (X * u[:, None]).T @ (X * u[:, None]) / n
    for l in range(1, lags + 1):
        w = 1 - l / (lags + 1)
        G = (X[l:] * u[l:, None]).T @ (X[:-l] * u[:-l, None]) / n
        S += w * (G + G.T)
    Q = np.linalg.inv(X.T @ X / n)
    V = Q @ S @ Q / n
    se = float(np.sqrt(max(V[1, 1], 1e-18)))
    return float(b[1]), se


def dose_response(A: pd.Series, E: pd.Series, first_valid):
    a = A.to_numpy()
    e = E.reindex(A.index).fillna(0).to_numpy()
    res = hac_slope(e, a)
    if res is None:
        return None
    beta, se = res
    emax = float(np.nanmax(e))
    win = A.index >= pd.Timestamp("2026-10-01", tz="UTC")
    mm = win & np.isfinite(a)
    r = float(np.corrcoef(e[mm], a[mm])[0, 1]) if mm.sum() > 20 and np.std(e[mm]) > 0 else float("nan")
    # placebo: map the post-period exposure pattern into the baseline
    base = (A.index < BASELINE_END) & (A.index >= first_valid + pd.Timedelta(days=3))
    betas = []
    for shift_h in range(24 * 6, 24 * 34, 6):
        ep = E.shift(-shift_h).reindex(A.index).fillna(0).to_numpy()
        if ep[base].std() == 0 or ep[base].max() < 0.5 * emax:
            continue
        rr = hac_slope(ep[base], a[base], lags=0)
        if rr:
            betas.append(rr[0])
    betas = np.array(betas)
    p_plac = float((1 + (np.abs(betas) >= abs(beta)).sum()) / (1 + len(betas))) if len(betas) else float("nan")
    p_plac_drop = float((1 + (betas <= beta).sum()) / (1 + len(betas))) if len(betas) else float("nan")
    lag_prof = []
    for l in LAGS:
        el = E.shift(l).reindex(A.index).fillna(0).to_numpy()
        rr = hac_slope(el, a, lags=0)
        lag_prof.append(round(rr[0], 4) if rr else None)
    eff = float(np.expm1(beta * emax))
    ci = [float(np.expm1((beta - 1.645 * se) * emax)), float(np.expm1((beta + 1.645 * se) * emax))]
    p_hac = float(2 * stats.norm.sf(abs(beta / se)))
    valid_l = [(l, v) for l, v in zip(LAGS, lag_prof) if v is not None]
    peak_lag = min(valid_l, key=lambda t: t[1])[0] if valid_l else None
    return dict(beta=beta, se=se, p_hac=p_hac, effect_at_max=eff, ci90=ci, emax=emax, r_oct=r,
                p_placebo=p_plac, p_placebo_drop=p_plac_drop, n_placebo=int(len(betas)),
                lag_profile=lag_prof, most_negative_lag=peak_lag)


def event_study(A: pd.Series, onsets, first_valid):
    rel = np.arange(EVENT_WIN[0], EVENT_WIN[1] + 1)
    out = {}
    for k, t0 in onsets.items():
        t0h = t0.floor("h")
        vals = A.reindex([t0h + pd.Timedelta(hours=int(h)) for h in rel]).to_numpy()
        out[k] = [None if not np.isfinite(v) else round(float(v), 4) for v in vals]
    a = A[(A.index < BASELINE_END - pd.Timedelta(hours=EVENT_WIN[1])) &
          (A.index >= first_valid + pd.Timedelta(days=10) - pd.Timedelta(hours=EVENT_WIN[0]))]
    origins = a.index[::3]
    traj = []
    for t0 in origins:
        v = A.reindex([t0 + pd.Timedelta(hours=int(h)) for h in rel]).to_numpy()
        if np.isfinite(v).mean() > 0.9:
            traj.append(v)
    if traj:
        T = np.array(traj)
        out["placebo_q05"] = [round(float(x), 4) for x in np.nanquantile(T, 0.05, axis=0)]
        out["placebo_q50"] = [round(float(x), 4) for x in np.nanquantile(T, 0.50, axis=0)]
        out["placebo_q95"] = [round(float(x), 4) for x in np.nanquantile(T, 0.95, axis=0)]
    return out


def bh(pvals):
    p = np.array([np.nan if v is None else v for v in pvals], dtype=float)
    q = np.full(len(p), np.nan)
    ok = np.isfinite(p)
    if ok.sum() == 0:
        return q
    pv = p[ok]
    order = np.argsort(pv)
    ranked = pv[order] * len(pv) / (np.arange(len(pv)) + 1)
    ranked = np.minimum.accumulate(ranked[::-1])[::-1]
    qq = np.empty(len(pv))
    qq[order] = np.minimum(ranked, 1)
    q[ok] = qq
    return q


def verdict(rec):
    w = (rec.get("windows") or {}).get("VLA_24h")
    d = (rec.get("dose") or {}).get("S1")
    if not w:
        return "Insufficient data"
    q = rec.get("q_vla24")
    nv = w.get("naive")
    if w["effect"] < -0.15 and q is not None and q < 0.10 and (nv is None or nv["p_drop"] < 0.10):
        return "Drop detected"
    if w["effect"] > 0.15 and w["p_two"] < 0.05:
        return "Increase detected"
    if w["rules_out_sesoi_drop"]:
        return "Large drop ruled out"
    return "Inconclusive"


def main():
    panel = pd.read_parquet(PROC / "panel.parquet")
    meta = json.loads((PROC / "series_meta.json").read_text())
    eof = json.loads((PROC / "eof_results.json").read_text())
    on = eof["validation_vs_ioda"]["S2"]["onset_median_utc"]
    onsets = {k: pd.Timestamp(v).tz_convert("UTC") for k, v in on.items()}
    # unexplained Yandex Cloud reachability dip inside the baseline (IODA, no status incident)
    onsets["SEP27"] = pd.Timestamp("2026-09-27T06:00:00Z")
    wide = panel.pivot(index="hour", columns="series_id", values="value").sort_index()
    exposures = {"S1": wide["eof.cloud.S1.mean"], "S2": wide["eof.cloud.S2.mean"],
                 "IODA": wide["exposure.ioda_cloud_unreachable"].clip(lower=0).fillna(0),
                 "core_S1": wide["eof.core.S1.mean"]}
    results, anomaly_cols, cf_cols = {}, {}, {}
    for sid, m in meta.items():
        if m["layer"] == "exposure":
            continue
        y = wide[sid]
        if y.notna().sum() < 24 * 14:
            continue
        yb = y[y.index < BASELINE_END]
        if not np.isfinite(yb.mean()) or yb.mean() <= 0.2 or yb.std() == 0:
            continue
        if m.get("transform") == "level":
            y = y.where(y > 0)
        first_valid = y.first_valid_index()
        res = anomalies(y, onsets)
        if res is None:
            continue
        A, cf, sig = res
        anomaly_cols[sid], cf_cols[sid] = A, cf
        base_mean = float(y[(y.index < BASELINE_END)].mean())
        rec = dict(series_id=sid, baseline_mean=base_mean, sigma_log=sig,
                   completeness=float(y.notna().mean()), windows={}, dose={})
        for k, t0 in onsets.items():
            for L in (6, 24):
                ws = window_stats(A, t0, L, first_valid)
                if ws:
                    if m.get("transform") != "level":
                        ws["naive"] = naive_window(y, t0, L)
                    rec["windows"][f"{k}_{L}h"] = ws
        for name, E in exposures.items():
            dr = dose_response(A, E, first_valid)
            if dr:
                rec["dose"][name] = dr
        rec["event_study"] = event_study(A, onsets, first_valid)
        w24 = rec["windows"].get("VLA_24h")
        rec["mde80_vla24"] = w24["mde80"] if w24 else None
        results[sid] = rec
        print(f"{sid:55s} VLA24 {w24['effect'] if w24 else float('nan'):+.3f} p={w24['p_drop'] if w24 else float('nan'):.3f}"
              f"  MDE={w24['mde80'] if w24 else float('nan'):.2f}")

    # Benjamini-Hochberg across IO outcome series
    io_ids = [s for s in results if meta[s]["layer"] == "io"]
    for key, getter in (("q_vla24", lambda r: (r["windows"].get("VLA_24h") or {}).get("p_drop")),
                        ("q_sas24", lambda r: (r["windows"].get("SAS_24h") or {}).get("p_drop")),
                        ("q_dose_s1", lambda r: (r["dose"].get("S1") or {}).get("p_placebo_drop"))):
        qs = bh([getter(results[s]) for s in io_ids])
        for s, q in zip(io_ids, qs):
            results[s][key] = None if not np.isfinite(q) else float(q)
    for s in results:
        results[s]["verdict"] = verdict(results[s])

    # theme contrasts (war minus other) for paired series
    contrasts = {}
    pairs = []
    for sid in results:
        if sid.endswith(".war"):
            other = sid[:-4] + ".other"
            if other in results:
                pairs.append((sid, other))
    for w_id, o_id in pairs:
        D = anomaly_cols[w_id] - anomaly_cols[o_id]
        fv = D.first_valid_index()
        rec = {"war": w_id, "other": o_id, "windows": {}, "dose": {}}
        for k, t0 in onsets.items():
            ws = window_stats(D, t0, 24, fv)
            if ws:
                rec["windows"][f"{k}_24h"] = ws
        dr = dose_response(D, exposures["S1"], fv)
        if dr:
            rec["dose"]["S1"] = dr
        contrasts[w_id[:-4]] = rec

    # random-effects pooling (DerSimonian-Laird) of window effects within groups
    pooled = {}
    groups = {}
    for sid, rec in results.items():
        m = meta[sid]
        # disjoint members only: single channels, single languages, single communities
        if m["layer"] not in ("io", "control"):
            continue
        if not (sid.startswith(("tg.ch.", "pravda.lang.")) or (sid.startswith("rd.") and sid.endswith(".comments.all")
                                                               and not sid.startswith("rd.grp."))):
            continue
        groups.setdefault(m["group"], []).append(sid)
    for g, ids in groups.items():
        pooled[g] = {"n_series": len(ids)}
        for wk in ("SAS_6h", "SAS_24h", "VLA_6h", "VLA_24h", "KAL_24h", "SEP27_24h"):
            ys, vs = [], []
            for sid in ids:
                w = results[sid]["windows"].get(wk)
                if w and w["placebo_sd"] > 0:
                    ys.append(w["anomaly"]); vs.append(w["placebo_sd"] ** 2)
            if len(ys) < 2:
                continue
            ys, vs = np.array(ys), np.array(vs)
            wf = 1 / vs
            mu_f = (wf * ys).sum() / wf.sum()
            Q = (wf * (ys - mu_f) ** 2).sum()
            tau2 = max(0.0, (Q - (len(ys) - 1)) / (wf.sum() - (wf ** 2).sum() / wf.sum()))
            wr = 1 / (vs + tau2)
            mu = (wr * ys).sum() / wr.sum()
            se = np.sqrt(1 / wr.sum())
            pooled[g][wk] = dict(effect=float(np.expm1(mu)), ci90=[float(np.expm1(mu - 1.645 * se)), float(np.expm1(mu + 1.645 * se))],
                                 p_drop=float(stats.norm.cdf(mu / se)), tau2=float(tau2), k=int(len(ys)),
                                 I2=float(max(0.0, (Q - (len(ys) - 1)) / Q)) if Q > 0 else 0.0)

    pd.DataFrame(anomaly_cols).to_parquet(PROC / "anomalies.parquet")
    pd.DataFrame(cf_cols).to_parquet(PROC / "counterfactuals.parquet")
    save_json({"onsets": {k: str(v) for k, v in onsets.items()}, "sesoi": SESOI, "lags": LAGS,
               "event_window": EVENT_WIN, "series": results, "contrasts": contrasts, "pooled": pooled},
              PROC / "analysis_results.json")
    print("analysed", len(results), "series;", len(contrasts), "theme contrasts")


if __name__ == "__main__":
    main()
