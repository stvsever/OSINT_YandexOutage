"""Cross-platform Bayesian hierarchical estimation of strike effects.

Unit of analysis: disjoint member series (single Telegram channels, single
Pravda languages, single Reddit communities, single websites). For each event
window k, member i has an out-of-sample mean log anomaly y_i and a placebo-
calibrated standard error s_i (standard deviation of same-length baseline
window means of that member).

    y_i     ~ Normal(theta_i, s_i^2)
    theta_i = alpha_g(i) + beta * Z_i + eps_i,   eps_i ~ Normal(0, tau^2)
    alpha_g ~ Normal(0, 0.5^2)          platform-group effect (log scale)
    beta    ~ Normal(0, 0.5^2)          extra effect for Yandex-dependent outlets
    tau     ~ HalfNormal(0.25)

Gibbs sampling (conjugate normal updates, griddy-Gibbs for tau), 4 chains x
4,000 iterations, 1,000 burn-in, split R-hat reported.

Members of a platform share news shocks, which the member-level errors do not
capture. The group effect is therefore reported with an added common-shock
variance sigma_c^2, estimated from the baseline as the variance of the
group-mean placebo windows minus the average member noise. Independently, a
frequentist cross-sectional placebo test is run on the group-mean anomaly
series (robust to any cross-member correlation). An effect is called credible
only if P(drop > 10 %) > 0.9 and the group placebo p < 0.05.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd

from analysis import naive_window, window_stats
from common import BASELINE_END, PROC, save_json

YANDEX_MAIL = {"readovkanews", "readovka_ru", "rybar", "rybar_in_english", "rybar_mena", "strategic_culture"}
WINDOWS = ["SAS_6h", "SAS_24h", "KAL_24h", "VLA_6h", "VLA_24h", "SEP27_24h"]


def platform_of(sid: str, meta: dict) -> str | None:
    m = meta[sid]
    if sid.startswith("pravda.lang."):
        return "Pravda network (automated web)"
    if sid.startswith("tg.ch."):
        return {"pro_kremlin_state": "Telegram: state media", "pro_kremlin_milblog": "Telegram: military bloggers",
                "pro_kremlin_tabloid": "Telegram: pro-Kremlin tabloids", "io_foreign_audience": "Telegram: foreign-audience IO",
                "control_ru_independent": "Control: independent Russian media", "control_ukrainian": "Control: Ukrainian channels",
                "control_ru_business": "Control: Russian business media",
                "control_ru_nonpolitical": "Control: Russian non-political"}.get(m["role"])
    if sid.startswith("rd.") and sid.endswith(".comments.all") and not sid.startswith("rd.grp."):
        return {"reddit_war": "Reddit: Ukraine war communities", "reddit_politics": "Reddit: political communities",
                "reddit_control": "Control: non-political Reddit"}.get(m["role"])
    if sid.startswith("web."):
        return "Web: state IO outlet" if m["role"] == "io_web" else "Control: independent web media"
    return None


def gibbs(y, s, g, z, ngroups, iters=4000, burn=1000, chains=4, seed=1):
    rng = np.random.default_rng(seed)
    taus = np.linspace(0.002, 1.5, 400)
    out_a, out_b, out_t = [], [], []
    for c in range(chains):
        a = rng.normal(0, 0.1, ngroups)
        b, tau = 0.0, 0.1
        A, B, T = [], [], []
        for it in range(iters):
            mu = a[g] + b * z
            prec = 1 / s ** 2 + 1 / tau ** 2
            th = rng.normal((y / s ** 2 + mu / tau ** 2) / prec, 1 / np.sqrt(prec))
            for k in range(ngroups):
                idx = g == k
                p = idx.sum() / tau ** 2 + 1 / 0.25
                a[k] = rng.normal(((th[idx] - b * z[idx]).sum() / tau ** 2) / p, 1 / np.sqrt(p))
            if z.sum() > 0:
                p = z.sum() / tau ** 2 + 1 / 0.25
                b = rng.normal(((z * (th - a[g])).sum() / tau ** 2) / p, 1 / np.sqrt(p))
            r2 = ((th - a[g] - b * z) ** 2).sum()
            lp = -len(y) * np.log(taus) - r2 / (2 * taus ** 2) - taus ** 2 / (2 * 0.25 ** 2)
            w = np.exp(lp - lp.max())
            tau = rng.choice(taus, p=w / w.sum())
            if it >= burn:
                A.append(a.copy()); B.append(b); T.append(tau)
        out_a.append(np.array(A)); out_b.append(np.array(B)); out_t.append(np.array(T))
    return np.array(out_a), np.array(out_b), np.array(out_t)


def rhat(x):  # x: chains x draws
    m, n = x.shape
    h = n // 2
    xs = np.concatenate([x[:, :h], x[:, h:2 * h]])
    W = xs.var(axis=1, ddof=1).mean()
    Bv = h * xs.mean(axis=1).var(ddof=1)
    return float(np.sqrt(((h - 1) / h * W + Bv / h) / W))


def main():
    meta = json.loads((PROC / "series_meta.json").read_text())
    an = json.loads((PROC / "analysis_results.json").read_text())
    A = pd.read_parquet(PROC / "anomalies.parquet")
    global PANEL
    PANEL = pd.read_parquet(PROC / "panel.parquet").pivot(index="hour", columns="series_id", values="value")
    onsets = {k: pd.Timestamp(v) for k, v in an["onsets"].items()}
    members = {}
    for sid, rec in an["series"].items():
        p = platform_of(sid, meta)
        if p:
            members[sid] = p
    groups = sorted(set(members.values()))
    io_groups = [g for g in groups if not g.startswith("Control")]
    results = {"groups": groups, "io_groups": io_groups, "members": members, "windows": {}}
    for wk in WINDOWS:
        ev, L = wk.split("_")[0], int(wk.split("_")[1][:-1])
        rows = [(sid, members[sid], an["series"][sid]["windows"][wk]) for sid in members
                if wk in an["series"][sid]["windows"]]
        y = np.array([r[2]["anomaly"] for r in rows])
        s = np.array([max(r[2]["placebo_sd"], 0.02) for r in rows])
        gi = {g: i for i, g in enumerate(groups)}
        g = np.array([gi[r[1]] for r in rows])
        z = np.array([1.0 if r[0].replace("tg.ch.", "") in YANDEX_MAIL else 0.0 for r in rows])
        Ad, Bd, Td = gibbs(y, s, g, z, len(groups))
        res = {"n_members": len(rows), "beta_yandex_mail": None, "tau": [float(np.percentile(Td, q)) for q in (5, 50, 95)],
               "groups": {}, "members": {}}
        if z.sum() > 0:
            bb = Bd.ravel()
            res["beta_yandex_mail"] = dict(median=float(np.expm1(np.median(bb))),
                                           ci90=[float(np.expm1(np.percentile(bb, 5))), float(np.expm1(np.percentile(bb, 95)))],
                                           p_negative=float((bb < 0).mean()), rhat=rhat(Bd), n_treated=int(z.sum()))
        for name, k in gi.items():
            ids = [r[0] for r in rows if r[1] == name]
            if not ids:
                continue
            # common-shock variance and frequentist test from the group-mean anomaly series
            G = A[ids].mean(axis=1)
            fv = G.first_valid_index()
            ws = window_stats(G, onsets[ev], L, fv)
            nb = A[ids][A.index < BASELINE_END]
            roll = nb.rolling(L).mean()
            v_ind = float(np.nanmean(roll.var()) / len(ids)) if len(ids) else 0.0
            v_tot = float(np.nanvar(roll.mean(axis=1)))
            sc2 = max(0.0, v_tot - v_ind)
            panel = PANEL[ids].sum(axis=1, min_count=len(ids))
            nv = naive_window(panel, onsets[ev], L)
            draws = Ad[:, :, k].ravel()
            draws = draws + np.random.default_rng(k).normal(0, np.sqrt(sc2), draws.size)
            eff = np.expm1(draws)
            res["groups"][name] = dict(
                k=len(ids), median=float(np.median(eff)), ci90=[float(np.percentile(eff, 5)), float(np.percentile(eff, 95))],
                p_drop10=float((eff < -0.10).mean()), p_drop=float((eff < 0).mean()), rhat=rhat(Ad[:, :, k]),
                common_shock_sd=float(np.sqrt(sc2)), placebo_p_drop=ws["p_drop"] if ws else None,
                placebo_effect=ws["effect"] if ws else None, io=not name.startswith("Control"),
                naive_effect=nv["effect"] if nv else None, naive_p_drop=nv["p_drop"] if nv else None,
                credible_drop=bool(ws and (eff < -0.10).mean() > 0.9 and ws["p_drop"] < 0.05
                                   and (nv is None or nv["p_drop"] < 0.10)))
        # IO minus control contrast (average of group effects)
        io_k = [gi[n] for n in io_groups if n in res["groups"]]
        ct_k = [gi[n] for n in groups if n.startswith("Control") and n in res["groups"]]
        diff = Ad[:, :, io_k].mean(axis=2).ravel() - Ad[:, :, ct_k].mean(axis=2).ravel()
        res["io_minus_control"] = dict(median=float(np.expm1(np.median(diff))),
                                       ci90=[float(np.expm1(np.percentile(diff, 5))), float(np.expm1(np.percentile(diff, 95)))],
                                       p_negative=float((diff < 0).mean()))
        for (sid, name, w), ii in zip(rows, range(len(rows))):
            res["members"][sid] = dict(group=name, y=float(np.expm1(w["anomaly"])), s=float(w["placebo_sd"]), yandex_mail=bool(z[ii]))
        results["windows"][wk] = res
        cred = [n for n, r in res["groups"].items() if r["credible_drop"]]
        print(f"{wk:10s} n={len(rows):3d} tau={res['tau'][1]:.3f} IO-control={res['io_minus_control']['median']:+.3f} "
              f"beta_mail={res['beta_yandex_mail']['median'] if res['beta_yandex_mail'] else None} credible drops: {cred}")
    save_json(results, PROC / "bayes_results.json")


if __name__ == "__main__":
    main()
