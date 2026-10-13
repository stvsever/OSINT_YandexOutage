"""Expected Outage Function (EOF) for Yandex infrastructure.

A generative, capacity-weighted damage model whose priors come from graded
open-source reporting, estimated in three nested Bayesian stages:

  Stage 0  Attack prior: strike timing windows, damage descriptors and source
           credibility (Admiralty grades) only.
  Stage 1  OSINT-conditioned: Stage 0 plus soft constraints from published
           statements, status pages and third-party outage reports.
  Stage 2  Telemetry-fused nowcast: Stage 1 plus the IODA active-probing
           likelihood for Yandex.Cloud (AS200350) at 10-minute resolution.

Stages 1 and 2 are sampled with an adaptive-tempering Sequential Monte Carlo
sampler (likelihood tempering, systematic resampling, random-walk Metropolis
moves with particle-covariance proposals; Del Moral, Doucet and Jasra 2006).

Outputs: hourly mean and quantiles of O(t) for each stage and target, posterior
parameter summaries, and validation metrics of the OSINT-only stages against
the measured telemetry.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import special, stats

from common import PROC, RAW, ROOT, STUDY_END, STUDY_START, save_json

CONFIG = ROOT / "config" / "outage_model.json"
STEP_MIN = 10
T0 = pd.Timestamp(STUDY_START)
GRID = pd.date_range(STUDY_START, STUDY_END, freq=f"{STEP_MIN}min", inclusive="left")
TM = ((GRID - T0).total_seconds() / 60.0).to_numpy()  # minutes since study start


def minutes(ts: str) -> float:
    return (pd.Timestamp(ts) - T0).total_seconds() / 60.0


# ------------------------------------------------------------------ evidence grading
def admiralty_prob(rel: str, cred: int, cfg) -> float:
    r = cfg["admiralty"]["reliability"][rel]
    c = cfg["admiralty"]["credibility"][str(cred)]
    return r * c + (1 - r) * 0.5


def pooled_probability(sources, cfg) -> float:
    """Log-odds pooling of graded sources with a discount for derivative reports."""
    lo = 0.0
    for s in sources:
        p = min(max(admiralty_prob(s["rel"], s["cred"], cfg), 0.02), 0.98)
        lo += (1.0 if s.get("independent", True) else cfg["derivative_discount"]) * math.log(p / (1 - p))
    return float(min(max(1 / (1 + math.exp(-lo)), 0.01), 0.995))


# ------------------------------------------------------------------ parameter layout
@dataclass
class Layout:
    names: list
    sites: list
    events: list

    @property
    def d(self):
        return len(self.names)


def build_layout(cfg, target):
    sites = list(cfg["targets"][target]["prior_share"].keys())
    names = [f"g_{s}" for s in sites]
    for e in cfg["events"]:
        k = e["id"]
        names += [f"T_{k}", f"L_{k}", f"Q_{k}", f"D_{k}", f"R_{k}"]
    names += ["kappa"]
    return Layout(names, sites, cfg["events"])


def event_priors(cfg):
    pri = {}
    lex = cfg["damage_lexicon"]
    for e in cfg["events"]:
        a, b = lex[e["damage_class"]]["beta"]
        pri[e["id"]] = dict(
            site=e["site"],
            tmin=minutes(e["t_min"]), tmax=minutes(e["t_max"]),
            tmode=minutes(e.get("t_mode", e["t_min"])),
            lag_mean=cfg["onset"]["lag_mean_min"], lag_shape=cfg["onset"]["lag_shape"],
            ramp_mean=cfg["onset"]["ramp_mean_min"], ramp_shape=cfg["onset"]["ramp_shape"],
            da=a * cfg["damage_scale"], db=b,
            pi=pooled_probability(e["sources"], cfg),
            rec_med=lex[e["damage_class"]]["recovery_median_days"] * 1440 * cfg["recovery_multiplier"],
            rec_sd=cfg["recovery_log_sd"],
        )
    return pri


# ------------------------------------------------------------------ prior: sample + density
def sample_prior(n, cfg, target, rng):
    lay = build_layout(cfg, target)
    pri = event_priors(cfg)
    share = cfg["targets"][target]["prior_share"]
    alpha = cfg["targets"][target]["concentration"]
    th = np.zeros((n, lay.d))
    j = 0
    for s in lay.sites:
        th[:, j] = np.log(rng.gamma(alpha * share[s], 1.0, n) + 1e-300)
        j += 1
    for e in lay.events:
        p = pri[e["id"]]
        lo, hi, md = p["tmin"], p["tmax"], p["tmode"]
        c = (md - lo) / (hi - lo) if hi > lo else 0.5
        T = stats.triang.rvs(c, loc=lo, scale=hi - lo, size=n, random_state=rng)
        u = np.clip((T - lo) / (hi - lo), 1e-6, 1 - 1e-6)
        th[:, j] = special.logit(u)
        th[:, j + 1] = np.log(rng.gamma(p["lag_shape"], p["lag_mean"] / p["lag_shape"], n))
        th[:, j + 2] = np.log(rng.gamma(p["ramp_shape"], p["ramp_mean"] / p["ramp_shape"], n))
        hit = rng.random(n) < p["pi"]
        D = np.where(hit, rng.beta(p["da"], p["db"], n), rng.beta(1.0, 60.0, n))
        th[:, j + 3] = special.logit(np.clip(D, 1e-6, 1 - 1e-6))
        th[:, j + 4] = rng.normal(np.log(p["rec_med"]), p["rec_sd"], n)
        j += 5
    th[:, j] = rng.normal(1.0, cfg["kappa_sd"], n)
    return th, lay, pri


def log_prior(th, cfg, target, lay, pri):
    share = cfg["targets"][target]["prior_share"]
    alpha = cfg["targets"][target]["concentration"]
    lp = np.zeros(th.shape[0])
    j = 0
    for s in lay.sites:
        a = alpha * share[s]
        u = th[:, j]
        lp += a * u - np.exp(u) - special.gammaln(a)
        j += 1
    for e in lay.events:
        p = pri[e["id"]]
        lo, hi, md = p["tmin"], p["tmax"], p["tmode"]
        c = (md - lo) / (hi - lo) if hi > lo else 0.5
        q = special.expit(th[:, j])
        T = lo + q * (hi - lo)
        lp += stats.triang.logpdf(T, c, loc=lo, scale=hi - lo) + np.log(hi - lo) + np.log(q * (1 - q) + 1e-300)
        for k, (shape, mean) in ((1, (p["lag_shape"], p["lag_mean"])), (2, (p["ramp_shape"], p["ramp_mean"]))):
            u = th[:, j + k]
            lp += stats.gamma.logpdf(np.exp(u), shape, scale=mean / shape) + u
        D = special.expit(th[:, j + 3])
        mix = p["pi"] * stats.beta.pdf(D, p["da"], p["db"]) + (1 - p["pi"]) * stats.beta.pdf(D, 1.0, 60.0)
        lp += np.log(mix + 1e-300) + np.log(D * (1 - D) + 1e-300)
        lp += stats.norm.logpdf(th[:, j + 4], np.log(p["rec_med"]), p["rec_sd"])
        j += 5
    lp += stats.norm.logpdf(th[:, j], 1.0, cfg["kappa_sd"])
    return np.where(np.isfinite(lp), lp, -np.inf)


# ------------------------------------------------------------------ forward model
def unpack(th, lay):
    g = np.exp(th[:, :len(lay.sites)])
    w = g / g.sum(1, keepdims=True)
    ev = []
    j = len(lay.sites)
    for e in lay.events:
        ev.append(dict(site=e["site"], Tq=th[:, j], L=np.exp(th[:, j + 1]), Q=np.exp(th[:, j + 2]),
                       D=special.expit(th[:, j + 3]), R=np.exp(th[:, j + 4])))
        j += 5
    return w, ev, th[:, j]


def forward(th, lay, pri, tm=TM):
    """Return O(t) for each particle on the minute grid tm (n x len(tm))."""
    w, ev, _ = unpack(th, lay)
    n = th.shape[0]
    keep = {s: np.ones((n, len(tm))) for s in lay.sites}
    for e, spec in zip(ev, lay.events):
        p = pri[spec["id"]]
        T = p["tmin"] + special.expit(e["Tq"]) * (p["tmax"] - p["tmin"])
        start = (T + e["L"])[:, None]
        x = np.clip((tm[None, :] - start) / e["Q"][:, None], 0.0, 1.0)
        after = np.clip(tm[None, :] - start - e["Q"][:, None], 0.0, None)
        x = x * np.exp(-after / e["R"][:, None]) * e["D"][:, None]
        if spec["site"] in keep:
            keep[spec["site"]] *= (1.0 - x)
    out = np.zeros((n, len(tm)))
    for i, s in enumerate(lay.sites):
        out += w[:, [i]] * (1.0 - keep[s])
    return out


def onset_times(th, lay, pri):
    _, ev, _ = unpack(th, lay)
    res = {}
    for e, spec in zip(ev, lay.events):
        p = pri[spec["id"]]
        T = p["tmin"] + special.expit(e["Tq"]) * (p["tmax"] - p["tmin"])
        res[spec["id"]] = dict(strike=T, onset=T + e["L"], full=T + e["L"] + e["Q"], damage=e["D"])
    return res


# ------------------------------------------------------------------ likelihoods
def osint_loglik(th, lay, pri, cfg, target, max_stage=1):
    """Soft constraints from published statements and reported outage figures."""
    ll = np.zeros(th.shape[0])
    ons = onset_times(th, lay, pri)
    for c in cfg["osint_constraints"]:
        if c.get("stage", 1) > max_stage:
            continue
        if c.get("target", target) != target:
            continue
        if c["type"] == "onset_before":
            o = ons[c["event"]]["onset"]
            ll += stats.norm.logcdf((minutes(c["t"]) - o) / c.get("scale_min", 10.0))
        elif c["type"] == "onset_after":
            o = ons[c["event"]]["onset"]
            ll += stats.norm.logcdf((o - minutes(c["t"])) / c.get("scale_min", 10.0))
        elif c["type"] == "strike_before":
            T = ons[c["event"]]["strike"]
            ll += stats.norm.logcdf((minutes(c["t"]) - T) / c.get("scale_min", 10.0))
        elif c["type"] == "report_delay":
            # first-report time t_r follows the event (strike or onset) after an
            # exponential reporting delay with the given mean
            X = ons[c["event"]][c.get("on", "strike")]
            m = c["mean_delay_min"]
            d = minutes(c["t"]) - X
            ll += np.where(d >= 0, -np.log(m) - d / m, -np.log(m) + d / 2.0)
        elif c["type"] == "increment":
            tm = np.array([minutes(c["t0"]), minutes(c["t1"])])
            o = forward(th, lay, pri, tm)
            ll += stats.norm.logpdf(o[:, 1] - o[:, 0], c["value"], c["sd"])
        elif c["type"] == "level":
            tm = np.array([minutes(c["t"])])
            o = forward(th, lay, pri, tm)[:, 0]
            ll += stats.norm.logpdf(1.0 - o, c["value"], c["sd"])
    return ll


def telemetry_series():
    """IODA AS200350 responsive /24 count as a fraction of the pre-strike median."""
    r = pd.read_parquet(RAW / "ioda_raw.parquet")
    x = r[(r.entity_code == "200350") & (r.datasource == "ping-slash24")].copy()
    x["t"] = pd.to_datetime(x.epoch, unit="s", utc=True)
    s = x.set_index("t")["value"].astype(float).sort_index()
    s = s.groupby(level=0).mean().reindex(GRID)
    # Clean reference window: after the unexplained 27 to 28 September reachability
    # dip (treated separately as a precedent event) and before the first strike.
    ref = (s.index >= "2026-09-29") & (s.index < "2026-10-07 18:00")
    base = s[ref].median()
    frac = s / base
    resid = (frac[ref] - frac[ref].median()).dropna()
    sd = 1.4826 * float((resid - resid.median()).abs().median())  # robust (MAD) scale
    rho = float(resid.autocorr(1))
    return frac, sd, rho, float(base)


def make_telemetry_loglik(cfg):
    frac, sd, rho, base = telemetry_series()
    mask = (frac.index >= cfg["telemetry"]["fit_from"]) & frac.notna().to_numpy()
    y = frac.to_numpy()[mask]
    tm = TM[mask]
    sigma = max(sd * cfg["telemetry"]["sigma_inflation"], cfg["telemetry"]["sigma_floor"])
    cl = (1 - rho) / (1 + rho) if rho > 0 else 1.0

    def ll(th, lay, pri):
        _, _, kappa = unpack(th, lay)
        o = forward(th, lay, pri, tm)
        mu = 1.0 - kappa[:, None] * o
        return cl * stats.norm.logpdf(y[None, :], mu, sigma).sum(1)

    info = dict(baseline_slash24=base, resid_sd=sd, rho=rho, sigma=sigma, composite_weight=cl, n_obs=int(mask.sum()))
    return ll, info, frac


# ------------------------------------------------------------------ SMC sampler
def smc(n, cfg, target, loglik, rng, n_moves=6, label=""):
    th, lay, pri = sample_prior(n, cfg, target, rng)
    lp = log_prior(th, cfg, target, lay, pri)
    ll = loglik(th, lay, pri)
    lam, it = 0.0, 0
    logw = np.zeros(n)
    while lam < 1.0 and it < 200:
        it += 1

        def ess(dl):
            lw = logw + dl * ll
            lw = lw - lw.max()
            w = np.exp(lw)
            return w.sum() ** 2 / (w ** 2).sum()

        lo_, hi_ = 0.0, 1.0 - lam
        if ess(hi_) >= n / 2:
            dl = hi_
        else:
            for _ in range(50):
                mid = (lo_ + hi_) / 2
                if ess(mid) >= n / 2:
                    lo_ = mid
                else:
                    hi_ = mid
            dl = max(lo_, 1e-6)
        logw = logw + dl * ll
        lam = min(1.0, lam + dl)
        # systematic resampling
        w = np.exp(logw - logw.max())
        w /= w.sum()
        pos = (rng.random() + np.arange(n)) / n
        idx = np.searchsorted(np.cumsum(w), pos)
        idx = np.minimum(idx, n - 1)
        th, lp, ll = th[idx], lp[idx], ll[idx]
        logw = np.zeros(n)
        # Metropolis moves targeting prior * lik^lam
        cov = np.cov(th.T) + 1e-8 * np.eye(th.shape[1])
        chol = np.linalg.cholesky(cov * (2.38 ** 2 / th.shape[1]) * 0.5)
        acc = 0
        for _ in range(n_moves):
            prop = th + rng.standard_normal(th.shape) @ chol.T
            lp2 = log_prior(prop, cfg, target, lay, pri)
            ok = np.isfinite(lp2)
            ll2 = np.full(n, -np.inf)
            if ok.any():
                ll2[ok] = loglik(prop[ok], lay, pri)
            a = (lp2 + lam * ll2) - (lp + lam * ll)
            accept = np.log(rng.random(n)) < a
            th[accept], lp[accept], ll[accept] = prop[accept], lp2[accept], ll2[accept]
            acc += accept.mean()
        print(f"  SMC{label} it={it:2d} lambda={lam:.4f} accept={acc / n_moves:.2f}")
    return th, lay, pri


# ------------------------------------------------------------------ summaries
QS = [0.05, 0.25, 0.5, 0.75, 0.95]


def hourly_summary(paths):
    df = pd.DataFrame(paths.T, index=GRID)
    h = df.groupby(df.index.floor("h")).mean()
    q = h.quantile(QS, axis=1).T
    q.columns = [f"q{int(x * 100):02d}" for x in QS]
    q["mean"] = h.mean(axis=1)
    return q


def param_summary(th, lay, pri):
    w, ev, kappa = unpack(th, lay)
    ons = onset_times(th, lay, pri)
    out = {"site_share": {}, "events": {}, "kappa": [float(np.percentile(kappa, x)) for x in (5, 50, 95)]}
    for i, s in enumerate(lay.sites):
        out["site_share"][s] = [float(np.percentile(w[:, i], x)) for x in (5, 50, 95)]
    for k, o in ons.items():
        out["events"][k] = {
            key: [str(T0 + pd.Timedelta(minutes=float(np.percentile(v, x)))) if key != "damage"
                  else float(np.percentile(v, x)) for x in (5, 50, 95)]
            for key, v in o.items()}
    return out


def predictive_hourly(th, lay, pri, sigma, rng):
    """Posterior predictive of the IODA unreachable fraction: kappa * O(t) + noise."""
    _, _, kappa = unpack(th, lay)
    o = forward(th, lay, pri) * kappa[:, None]
    df = pd.DataFrame(o.T, index=GRID)
    h = df.groupby(df.index.floor("h")).mean()
    # hourly means of six 10-minute observations: noise sd shrinks accordingly
    noisy = h.to_numpy() + rng.normal(0, sigma / np.sqrt(6), h.shape)
    q = np.quantile(noisy, [0.05, 0.5, 0.95], axis=1).T
    return pd.DataFrame(q, index=h.index, columns=["p05", "p50", "p95"])


def main():
    cfg = json.loads(CONFIG.read_text())
    rng = np.random.default_rng(cfg.get("seed", 20261013))
    n = cfg["particles"]
    results = {"config": cfg, "grid_step_min": STEP_MIN, "stages": {}, "event_credibility": {}}
    pri0 = event_priors(cfg)
    results["event_credibility"] = {k: round(v["pi"], 4) for k, v in pri0.items()}

    tel_ll, tel_info, frac = make_telemetry_loglik(cfg)
    results["telemetry_info"] = tel_info
    out_rows, particles = [], {}
    for target in cfg["targets"]:
        th0, lay, pri = sample_prior(n, cfg, target, rng)
        stages = {"S0": th0}
        stages["S1"], _, _ = smc(n, cfg, target, lambda t, l, p: osint_loglik(t, l, p, cfg, target), rng,
                                 label=f"[{target} S1]")
        if target == "cloud":
            stages["S2"], _, _ = smc(n, cfg, target,
                                     lambda t, l, p: osint_loglik(t, l, p, cfg, target, 2) + tel_ll(t, l, p),
                                     rng, label=f"[{target} S2]")
        for st, th in stages.items():
            d = hourly_summary(forward(th, lay, pri))
            d["target"], d["stage"] = target, st
            out_rows.append(d.reset_index(names="hour"))
            results["stages"][f"{target}_{st}"] = param_summary(th, lay, pri)
            particles[(target, st)] = (th, lay, pri)

    eof = pd.concat(out_rows, ignore_index=True)
    eof.to_parquet(PROC / "eof_hourly.parquet")

    # High-resolution (10 minute) quantiles, sample trajectories and downtime analysis
    hi_rows, traj, downtime = [], {}, {}
    sel = GRID >= pd.Timestamp("2026-10-05", tz="UTC")
    for (target, st), (th, lay, pri) in particles.items():
        o = forward(th, lay, pri)
        q = np.quantile(o, QS, axis=0)
        d = pd.DataFrame({f"q{int(x * 100):02d}": q[i] for i, x in enumerate(QS)}, index=GRID)
        d["mean"] = o.mean(0)
        d["target"], d["stage"] = target, st
        hi_rows.append(d[sel].reset_index(names="t"))
        idx = np.random.default_rng(7).choice(len(o), 40, replace=False)
        traj[f"{target}_{st}"] = np.round(o[idx][:, sel][:, ::1], 4).tolist()
        ons = onset_times(th, lay, pri)
        _, ev, _ = unpack(th, lay)
        dt = {}
        end_min = minutes(str(STUDY_END))
        for e, spec in zip(ev, lay.events):
            k = spec["id"]
            o_ = ons[k]
            R_days = e["R"] / 1440.0
            elapsed_h = (end_min - o_["onset"]) / 60.0
            dt[k] = dict(
                onset_utc=[str(T0 + pd.Timedelta(minutes=float(np.percentile(o_["onset"], x)))) for x in (5, 50, 95)],
                strike_utc=[str(T0 + pd.Timedelta(minutes=float(np.percentile(o_["strike"], x)))) for x in (5, 50, 95)],
                full_loss_utc=[str(T0 + pd.Timedelta(minutes=float(np.percentile(o_["full"], x)))) for x in (5, 50, 95)],
                strike_to_onset_min=[float(np.percentile(o_["onset"] - o_["strike"], x)) for x in (5, 50, 95)],
                ramp_min=[float(np.percentile(o_["full"] - o_["onset"], x)) for x in (5, 50, 95)],
                damage=[float(np.percentile(o_["damage"], x)) for x in (5, 50, 95)],
                elapsed_downtime_h_at_study_end=[float(np.percentile(elapsed_h, x)) for x in (5, 50, 95)],
                recovery_timescale_days=[float(np.percentile(R_days, x)) for x in (5, 50, 95)],
                p_half_restored_7d=float(np.mean(R_days * np.log(2) <= 7)),
                p_half_restored_30d=float(np.mean(R_days * np.log(2) <= 30)),
            )
        downtime[f"{target}_{st}"] = dt
    pd.concat(hi_rows, ignore_index=True).to_parquet(PROC / "eof_10min.parquet")
    results["downtime"] = downtime
    save_json({"t0": "2026-10-05T00:00:00Z", "step_min": STEP_MIN, "paths": traj}, PROC / "eof_trajectories.json")

    # Validation of each stage against measured Yandex.Cloud unreachability (IODA)
    obs = (1 - frac).groupby(frac.index.floor("h")).mean()
    val, pred_rows = {}, []
    for st in ("S0", "S1", "S2"):
        th, lay, pri = particles[("cloud", st)]
        e = eof[(eof.target == "cloud") & (eof.stage == st)].set_index("hour")
        pp = predictive_hourly(th, lay, pri, tel_info["sigma"], rng)
        j = pd.concat([e, pp, obs.rename("obs")], axis=1).dropna()
        j = j[j.index >= "2026-10-05"]
        resid = j["obs"] - j["mean"]
        ons = onset_times(th, lay, pri)
        val[st] = dict(
            r=float(np.corrcoef(j["mean"], j["obs"])[0, 1]),
            r2=float(1 - (resid ** 2).sum() / ((j["obs"] - j["obs"].mean()) ** 2).sum()),
            mae=float(resid.abs().mean()),
            predictive_coverage90=float(((j["obs"] >= j["p05"]) & (j["obs"] <= j["p95"])).mean()),
            n_hours=int(len(j)),
            onset_median_utc={k: str(T0 + pd.Timedelta(minutes=float(np.median(v["onset"])))) for k, v in ons.items()},
            in_sample=(st == "S2"))
        pp["stage"] = st
        pred_rows.append(pp.reset_index(names="hour"))
    s2 = val["S2"]["onset_median_utc"]
    for st in ("S0", "S1"):
        val[st]["onset_error_min_vs_S2"] = {
            k: round((pd.Timestamp(v) - pd.Timestamp(s2[k])).total_seconds() / 60, 1)
            for k, v in val[st]["onset_median_utc"].items()}
    pd.concat(pred_rows).to_parquet(PROC / "eof_predictive_hourly.parquet")
    obs.rename("ioda_unreachable_frac").to_frame().to_parquet(PROC / "ioda_cloud_unreachable_hourly.parquet")
    results["validation_vs_ioda"] = val
    save_json(results, PROC / "eof_results.json")
    print(json.dumps(val, indent=1))


if __name__ == "__main__":
    main()
