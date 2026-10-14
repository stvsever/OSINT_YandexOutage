"""High-resolution timing attribution (10-minute bins).

For each outcome stream and each outage event we fit a dip change-point model
to 10-minute counts c_i with expected rate lambda_i taken from the hourly
seasonal counterfactual:

    c_i ~ quasi-Poisson(lambda_i * r_i),  r_i = rho inside [tau1, tau2), 1 outside

rho is profiled out, the dispersion phi is estimated on the baseline, and a
flat prior over (tau1, tau2) gives a posterior for the dip start tau1. The
maximum log likelihood ratio is calibrated against the same scan run at 400
random origins in the pre-strike baseline (placebo-in-time), so the p-value
accounts for the search over change points. The timing offset
tau1 - outage onset is the attribution statistic: an outage-driven dip must
start at or shortly after the onset, not before it.

A backlog test measures the deficit inside the dip and the surplus in the six
hours after it. A surplus close to the deficit indicates queued items that
were published late (a stalled pipeline), rather than output that was lost.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from common import BASELINE_END, PROC, RAW, STUDY_END, STUDY_START, save_json

STEP = "10min"
GRID = pd.date_range(STUDY_START, STUDY_END, freq=STEP, inclusive="left")
PRE, POST = pd.Timedelta(hours=12), pd.Timedelta(hours=24)
# onset-locked test: dips that start between 30 min before and 6 h after the outage onset
LOCK = (-3, 36)  # in 10-minute steps relative to the onset


def counts(ts: pd.Series) -> pd.Series:
    return ts.dt.floor(STEP).value_counts().reindex(GRID, fill_value=0).sort_index().astype(float)


def streams():
    out = {}
    pr = pd.read_parquet(RAW / "pravda_articles.parquet")
    langs = json.loads((PROC / "pravda_host_lang.json").read_text())
    pr["lang"] = pr.host.map(langs)
    out["pravda.total"] = ("Pravda network, all subdomains", counts(pr.t_utc), "pravda.total")
    for l in ("en", "de", "fr", "es", "ar", "sr"):
        out[f"pravda.lang.{l}"] = (f"Pravda network, language {l}", counts(pr[pr.lang == l].t_utc), f"pravda.lang.{l}")
    tg = pd.read_parquet(PROC / "telegram_posts.parquet")
    io_roles = {"pro_kremlin_state", "pro_kremlin_milblog", "pro_kremlin_tabloid", "io_foreign_audience"}
    pk = tg[tg.role.isin(io_roles)]
    out["tg.prokremlin.all"] = ("Pro-Kremlin Telegram, all IO-linked channels", counts(pk.t_utc), "tg.prokremlin.all")
    out["tg.prokremlin.war"] = ("Pro-Kremlin Telegram, war-theme posts", counts(pk[pk.war].t_utc), "tg.prokremlin.war")
    fa = tg[tg.role == "io_foreign_audience"]
    out["tg.grp.io_foreign_audience.all"] = ("IO Telegram for foreign audiences", counts(fa.t_utc), "tg.grp.io_foreign_audience.all")
    ymail = {"readovkanews", "readovka_ru", "rybar", "rybar_in_english", "rybar_mena", "strategic_culture"}
    out["tg.yxdep.mail"] = ("IO channels of outlets on Yandex 360 mail", counts(pk[pk.handle.isin(ymail)].t_utc), "tg.yxdep.mail")
    st = tg[tg.role == "pro_kremlin_state"]
    out["tg.grp.pro_kremlin_state.all"] = ("Pro-Kremlin state channels", counts(st.t_utc), "tg.grp.pro_kremlin_state.all")
    w = pd.read_parquet(RAW / "web_articles.parquet")
    out["web.ukraina.ru"] = ("ukraina.ru articles (RIA outlet)", counts(w[w.site == "ukraina.ru"].t_utc), "web.ukraina.ru")
    # outlets of information-manipulation sets named in the EEAS 4th FIMI threat report
    out["web.afrinz.ru"] = ("African Initiative website (EEAS-named)", counts(w[w.site == "afrinz.ru"].t_utc), "web.afrinz.ru")
    out["web.rrn.com.tr"] = ("RRN / Media Brands website (EEAS-named)", counts(w[w.site == "rrn.com.tr"].t_utc), "web.rrn.com.tr")
    ei = tg[tg.role == "io_eeas_ims"]
    out["tg.grp.io_eeas_ims.all"] = ("African Initiative Telegram (EEAS-named)", counts(ei.t_utc), "tg.grp.io_eeas_ims.all")
    ct = tg[tg.role.isin({"control_ru_independent", "control_ukrainian", "control_ru_business"})]
    out["tg.controls.all"] = ("Control Telegram (independent and Ukrainian)", counts(ct.t_utc), "tg.controls.all")
    rd = pd.read_parquet(RAW / "reddit_authors" / "UkraineRussiaReport.parquet")
    rdt = pd.to_datetime(rd.created_utc, unit="s", utc=True)
    out["rd.UkraineRussiaReport.comments.all"] = ("r/UkraineRussiaReport comments", counts(rdt),
                                                 "rd.UkraineRussiaReport.comments.all")
    return out


def expected(cf_hourly: pd.Series, obs: pd.Series) -> pd.Series:
    lam = cf_hourly.reindex(GRID.floor("h")).to_numpy() / 6.0
    lam = pd.Series(lam, GRID)
    base = (GRID < BASELINE_END) & np.isfinite(lam.to_numpy())
    scale = obs[base].sum() / max(lam[base].sum(), 1e-9)  # log-retransformation smearing
    return (lam * scale).clip(lower=0.05)


def scan(c, lam, phi):
    """Profile log-LR over all (tau1, tau2) for a dip; returns grids."""
    n = len(c)
    C = np.concatenate([[0], np.cumsum(c)])
    L = np.concatenate([[0], np.cumsum(lam)])
    best = -np.inf
    llr = np.full((n, n + 1), -np.inf)
    for i in range(6, n - 3):
        js = np.arange(i + 3, min(n, i + 6 * 20) + 1)
        sc = C[js] - C[i]
        sl = L[js] - L[i]
        rho = np.clip(sc / sl, 1e-3, 1.0)
        v = (sc * np.log(rho) - sl * (rho - 1)) / phi
        llr[i, js] = v
        best = max(best, v.max())
    return llr, best


def locked_best(llr, i0):
    """Largest dip log-LR among dips whose start lies in the onset-locked range."""
    a, b = max(0, i0 + LOCK[0]), min(llr.shape[0], i0 + LOCK[1] + 1)
    sub = llr[a:b]
    return float(sub.max()) if sub.size and np.isfinite(sub).any() else -np.inf


def analyse(c, lam, phi, onset, t_index, full=None):
    llr, best = scan(c, lam, phi)
    i0 = int(np.ceil((onset - t_index[0]).total_seconds() / 600))
    lb = locked_best(llr, i0)
    a0 = max(0, i0 + LOCK[0])
    sub = llr[a0:i0 + LOCK[1] + 1]
    li, lj = np.unravel_index(np.argmax(sub), sub.shape)
    li += a0
    locked = dict(locked_llr=lb, locked_ratio=float(c[li:lj].sum() / max(lam[li:lj].sum(), 1e-9)) if lj > li else None,
                  locked_hours=float((lj - li) / 6.0), locked_offset_min=float((t_index[li] - onset).total_seconds() / 60))
    w = np.exp(llr - best)
    w[~np.isfinite(w)] = 0
    p_tau1 = w.sum(1)
    p_tau1 /= p_tau1.sum()
    i_map, j_map = np.unravel_index(np.argmax(llr), llr.shape)
    cdf = np.cumsum(p_tau1)
    lo, hi = np.searchsorted(cdf, 0.05), np.searchsorted(cdf, 0.95)
    rho = c[i_map:j_map].sum() / lam[i_map:j_map].sum()
    naive = None
    if full is not None:
        a_, b_ = t_index[i_map], t_index[min(j_map, len(t_index) - 1)]
        o = full[(full.index >= a_) & (full.index < b_)].sum()
        refs = [full[(full.index >= a_ - pd.Timedelta(weeks=w)) & (full.index < b_ - pd.Timedelta(weeks=w))].sum() for w in (1, 2, 3)]
        refs = [r for r in refs if r > 0]
        naive = float(o / np.mean(refs)) if refs else None
    deficit = float((lam[i_map:j_map] - c[i_map:j_map]).sum())
    k2 = min(len(c), j_map + 36)
    surplus = float((c[j_map:k2] - lam[j_map:k2]).sum())
    return dict(
        max_llr=float(best),
        tau1_map=str(t_index[i_map]), tau2_map=str(t_index[min(j_map, len(t_index) - 1)]),
        tau1_ci90=[str(t_index[min(lo, len(t_index) - 1)]), str(t_index[min(hi, len(t_index) - 1)])],
        offset_min=float((t_index[i_map] - onset).total_seconds() / 60),
        offset_ci90_min=[float((t_index[min(lo, len(t_index) - 1)] - onset).total_seconds() / 60),
                         float((t_index[min(hi, len(t_index) - 1)] - onset).total_seconds() / 60)],
        dip_ratio=float(rho), dip_hours=float((j_map - i_map) / 6.0),
        deficit=deficit, surplus_next6h=surplus, naive_ratio=naive,
        recovery_ratio=float(surplus / deficit) if deficit > 0 else None,
        posterior_tau1=[round(float(x), 5) for x in p_tau1],
        tau1_ci90_offset_min=[float((t_index[min(lo, len(t_index) - 1)] - onset).total_seconds() / 60),
                              float((t_index[min(hi, len(t_index) - 1)] - onset).total_seconds() / 60)],
        **locked,
    )


def main():
    eof = json.loads((PROC / "eof_results.json").read_text())
    on = {k: pd.Timestamp(v) for k, v in eof["validation_vs_ioda"]["S2"]["onset_median_utc"].items()}
    on["SEP27"] = pd.Timestamp("2026-09-27T06:00:00Z")
    cf = pd.read_parquet(PROC / "counterfactuals.parquet")
    rng = np.random.default_rng(11)
    res, hires = {}, {}
    for sid, (label, c, panel_id) in streams().items():
        if panel_id not in cf:
            continue
        lam = expected(cf[panel_id], c)
        base = (GRID < BASELINE_END) & (GRID >= GRID[0] + pd.Timedelta(days=8))
        resid = (c[base] - lam[base]) ** 2 / lam[base]
        phi = float(max(resid.mean(), 1.0))
        # placebo calibration of the change-point scan
        origins = GRID[base & (GRID < BASELINE_END - POST - pd.Timedelta(hours=1))]
        null, null_locked = [], []
        i0 = int(PRE / pd.Timedelta(minutes=10))
        for t0 in rng.choice(origins, 400, replace=False):
            m = (GRID >= t0 - PRE) & (GRID < t0 + POST)
            llr_p, best_p = scan(c[m].to_numpy(), lam[m].to_numpy(), phi)
            null.append(best_p)
            null_locked.append(locked_best(llr_p, i0))
        null, null_locked = np.array(null), np.array(null_locked)
        rec = {"label": label, "phi": phi, "events": {}}
        for k, t0 in on.items():
            m = (GRID >= t0 - PRE) & (GRID < t0 + POST)
            idx = GRID[m]
            a = analyse(c[m].to_numpy(), lam[m].to_numpy(), phi, t0, idx, full=c)
            a["p_scan"] = float((1 + (null >= a["max_llr"]).sum()) / (1 + len(null)))
            a["p_locked"] = float((1 + (null_locked >= a["locked_llr"]).sum()) / (1 + len(null_locked)))
            rec["events"][k] = a
        res[sid] = rec
        sel = GRID >= pd.Timestamp("2026-10-05", tz="UTC")
        hires[sid] = {"label": label, "obs": c[sel].astype(int).tolist(),
                      "exp": np.round(lam[sel].to_numpy(), 2).tolist()}
        v = rec["events"]["VLA"]
        s = rec["events"]["SAS"]
        print(f"{sid:40s} VLA dip x{v['dip_ratio']:.2f} {v['dip_hours']:.1f}h offset {v['offset_min']:+.0f}m "
              f"p={v['p_scan']:.3f} locked x{v['locked_ratio']:.2f} p_locked={v['p_locked']:.3f} backlog={v['recovery_ratio']} | SAS x{s['dip_ratio']:.2f} offset {s['offset_min']:+.0f}m p={s['p_scan']:.3f}")
    # Benjamini-Hochberg q-values across all onset-locked tests (streams x events)
    keys = [(sid, k) for sid in res for k in res[sid]["events"]]
    ps = np.array([res[sid]["events"][k]["p_locked"] for sid, k in keys])
    order = np.argsort(ps)
    q = np.empty_like(ps)
    q[order] = np.minimum.accumulate((ps[order] * len(ps) / np.arange(1, len(ps) + 1))[::-1])[::-1]
    for (sid, k), qq in zip(keys, np.minimum(q, 1)):
        res[sid]["events"][k]["q_locked"] = float(qq)
    # IODA reference at 10 minutes
    r = pd.read_parquet(RAW / "ioda_raw.parquet")
    x = r[(r.entity_code == "200350") & (r.datasource == "ping-slash24")]
    s = pd.Series(x.value.astype(float).to_numpy(), pd.to_datetime(x.epoch, unit="s", utc=True)).groupby(level=0).mean()
    s = s.reindex(GRID)
    sel = GRID >= pd.Timestamp("2026-10-05", tz="UTC")
    hires["ioda.asn.200350"] = {"label": "Yandex Cloud responsive /24 blocks (IODA)",
                                "obs": [None if not np.isfinite(v) else float(v) for v in s[sel]]}
    save_json({"t0": "2026-10-05T00:00:00Z", "step_min": 10, "pre_h": 12, "post_h": 24,
               "onsets": {k: str(v) for k, v in on.items()}, "results": res, "series": hires},
              PROC / "timing_results.json")


if __name__ == "__main__":
    main()
