"""Build the concise PDF report (title page plus four pages) from the pipeline outputs.

Figures are drawn with matplotlib as inline SVG, the document is laid out in
HTML with print CSS and rendered to PDF with headless Chrome.
"""
from __future__ import annotations

import io
import json
import subprocess
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
OUT = ROOT / "report"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

INK, INK2, INK3, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
BLUE, ORANGE, AQUA, RED, GREEN = "#2a78d6", "#eb6834", "#1baf7a", "#d03b3b", "#0ca30c"
plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Inter", "Helvetica Neue", "Helvetica", "Arial"],
                     "font.size": 8, "axes.edgecolor": "#c3c2b7", "axes.labelcolor": INK2, "xtick.color": INK3,
                     "ytick.color": INK3, "axes.spines.top": False, "axes.spines.right": False, "svg.fonttype": "none",
                     "axes.titlesize": 8.5, "axes.titleweight": "bold", "axes.titlelocation": "left"})


def svg(fig) -> str:
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight", transparent=True)
    plt.close(fig)
    s = buf.getvalue()
    return s[s.index("<svg"):]


def pct(x, d=0):
    return "n/a" if x is None or not np.isfinite(x) else f"{'+' if x > 0 else ''}{x * 100:.{d}f}%"


def load():
    j = lambda n: json.loads((PROC / n).read_text())
    return dict(eof=j("eof_results.json"), tim=j("timing_results.json"), an=j("analysis_results.json"), by=j("bayes_results.json"),
                infra=j("infra_map.json"), eof10=pd.read_parquet(PROC / "eof_10min.parquet"), meta=j("series_meta.json"))


def fig_key(D):
    """Figure 1: measured outage vs OSINT expectation, and Pravda vs its upstream input."""
    t = D["tim"]
    t0 = pd.Timestamp(t["t0"])
    n = len(t["series"]["pravda.total"]["obs"])
    x = pd.date_range(t0, periods=n, freq="10min")
    lo, hi = pd.Timestamp("2026-10-07T12:00Z"), pd.Timestamp("2026-10-12T06:00Z")
    sel = (x >= lo) & (x < hi)
    base = D["eof"]["telemetry_info"]["baseline_slash24"]
    io_ = np.array([np.nan if v is None else max(0, 1 - v / base) * 100 for v in t["series"]["ioda.asn.200350"]["obs"]])
    e = D["eof10"]
    s1 = e[(e.target == "cloud") & (e.stage == "S1")].set_index("t")
    s1 = s1[(s1.index >= lo) & (s1.index < hi)]
    on = {k: pd.Timestamp(v) for k, v in D["an"]["onsets"].items()}

    def ratio(sid):
        o = np.array(t["series"][sid]["obs"], float)
        ex = np.array(t["series"][sid]["exp"], float)
        k = np.ones(6)
        return 100 * np.convolve(o, k)[:n] / np.convolve(ex, k)[:n]

    fig, ax = plt.subplots(2, 1, figsize=(7.1, 4.4), sharex=True, gridspec_kw={"height_ratios": [1, 1.25], "hspace": 0.55})
    a = ax[0]
    a.fill_between(s1.index, s1.q05 * 100, s1.q95 * 100, color=BLUE, alpha=0.13, lw=0, step="post", label="Expected outage, 90% band (open sources only)")
    a.plot(s1.index, s1["mean"] * 100, color=BLUE, lw=1.6, drawstyle="steps-post", label="Expected outage, mean (Stage 1)")
    a.plot(x[sel], io_[sel], color=ORANGE, lw=1.3, label="Measured outage (IODA active probing)")
    a.set_ylim(0, 100); a.set_ylabel("Yandex Cloud offline (%)")
    a.set_title("A  Outage: open-source expectation versus measurement", color=INK)
    a.legend(loc="upper center", bbox_to_anchor=(0.5, -0.06), frameon=False, fontsize=6.8, ncol=3, handlelength=1.6)
    b = ax[1]
    b.axhline(100, color="#c3c2b7", lw=0.8)
    pe = t["results"]["pravda.total"]["events"]["VLA"]
    b.axvspan(pd.Timestamp(pe["tau1_map"]), pd.Timestamp(pe["tau2_map"]), color=RED, alpha=0.08, lw=0)
    b.plot(x[sel], ratio("pravda.total")[sel], color=AQUA, lw=1.5, label="Pravda network output (automated, 88 sites)")
    b.plot(x[sel], ratio("tg.prokremlin.all")[sel], color=INK3, lw=1.0, alpha=0.9, label="Pro-Kremlin Telegram output (its upstream input)")
    b.set_ylim(0, 230); b.set_ylabel("Output, % of expected (1 h rolling)")
    b.set_title("B  Information-operation output relative to the seasonal counterfactual", color=INK)
    b.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), frameon=False, fontsize=6.8, ncol=2, handlelength=1.6)
    b.text(pd.Timestamp(pe["tau2_map"]) + pd.Timedelta(minutes=40), 205,
           f"Pravda {pct(pe['dip_ratio'] - 1)} for {pe['dip_hours']:.0f} h,\nstarts {pe['offset_min']:.0f} min after onset\n(p = {pe['p_scan']:.3f})",
           fontsize=6.6, color=RED, va="top", bbox=dict(facecolor="white", edgecolor="none", alpha=0.9, pad=1.5))
    for axx in ax:
        for k, c in (("SAS", RED), ("KAL", INK3), ("VLA", RED)):
            axx.axvline(on[k], color=c, lw=0.9, ls="-", alpha=0.8)
        axx.grid(axis="y", color=GRID, lw=0.6)
    for k, lab in (("SAS", "Sasovo"), ("KAL", "Kaluga"), ("VLA", "Vladimir")):
        ax[0].text(on[k] + pd.Timedelta(minutes=40), 92, lab, fontsize=6.8, color=INK2)
    import matplotlib.dates as mdates
    b.xaxis.set_major_locator(mdates.DayLocator()); b.xaxis.set_major_formatter(mdates.DateFormatter("%d Oct"))
    return svg(fig)


def fig_groups(D):
    """Figure 2: Bayesian posterior change per platform group, Vladimir 6 h and 24 h."""
    by = D["by"]
    groups = sorted(by["groups"], key=lambda g: (g.startswith("Control"), g))
    fig, ax = plt.subplots(1, 2, figsize=(7.1, 3.3), sharey=True, gridspec_kw={"wspace": 0.06})
    ys = np.arange(len(groups))[::-1]
    for a, wk, title in ((ax[0], "VLA_6h", "Vladimir, first 6 h"), (ax[1], "VLA_24h", "Vladimir, first 24 h")):
        w = by["windows"][wk]["groups"]
        a.axvspan(-0.9, -0.2, color=RED, alpha=0.06, lw=0)
        a.axvline(0, color=INK2, lw=0.8)
        for y, g in zip(ys, groups):
            r = w.get(g)
            if not r:
                continue
            col = RED if r["credible_drop"] else (GREEN if r["ci90"][0] > -0.2 else INK3)
            a.plot([max(r["ci90"][0], -0.6), min(r["ci90"][1], 1.0)], [y, y], color=col, lw=2, solid_capstyle="round")
            a.plot(max(min(r["median"], 1.0), -0.6), y, "o", color=col, ms=4.5, mec="white", mew=1)
        a.set_xlim(-0.6, 1.0); a.set_title(title, color=INK); a.set_xticks([-0.4, -0.2, 0, 0.4, 0.8])
        a.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v * 100:+.0f}%"))
        a.grid(axis="x", color=GRID, lw=0.6)
    ax[0].set_yticks(ys); ax[0].set_yticklabels([g.replace("Control: ", "Control, ") for g in groups], fontsize=7)
    sep = sum(1 for g in groups if g.startswith("Control"))
    for a in ax:
        a.axhline(sep - 0.5, color="#c3c2b7", lw=0.6, ls="-")
    return svg(fig)


def build():
    D = load()
    ev = D["eof"]; v = ev["validation_vs_ioda"]; dt = ev["downtime"]["cloud_S2"]; sh = ev["stages"]["cloud_S2"]["site_share"]
    by = D["by"]; an = D["an"]; tim = D["tim"]["results"]
    pr = tim["pravda.total"]["events"]["VLA"]
    S = an["series"]
    io_ids = [k for k in S if D["meta"][k]["layer"] == "io"]
    verd = pd.Series([S[k]["verdict"] for k in io_ids]).value_counts().to_dict()
    nmem = by["windows"]["VLA_24h"]["n_members"]
    g6, g24 = by["windows"]["VLA_6h"]["groups"], by["windows"]["VLA_24h"]["groups"]
    beta = by["windows"]["VLA_24h"]["beta_yandex_mail"]
    iom = by["windows"]["VLA_24h"]["io_minus_control"]
    dn = [D["meta"][k]["label"] for k in io_ids if S[k]["verdict"] == "Drop detected"]
    drop_names = f" ({'; '.join(dn)})" if dn else ""
    W = lambda sid, k="VLA_24h": S[sid]["windows"][k]["effect"] if sid in S and k in S[sid]["windows"] else None
    beta_pl = by["windows"]["SEP27_24h"]["beta_yandex_mail"]
    stv = tim.get("tg.grp.pro_kremlin_state.all", {}).get("events", {}).get("VLA", {})
    state_note = ""
    if stv and stv.get("p_scan", 1) < 0.05 and (stv.get("naive_ratio") or 0) > 0.85:
        state_note = (f" A {stv['dip_hours']:.0f} h dip that the regression counterfactual flags in state channels falls on an ordinary"
                      f" Sunday: against the same hours on the previous three Sundays, output was {stv['naive_ratio'] * 100:.0f}% of normal.")
    n_tg = sum(1 for k in D["meta"] if k.startswith("tg.ch."))
    n_rd = len({k.split(".")[1] for k in D["meta"] if k.startswith("rd.") and k.endswith(".comments.all") and not k.startswith("rd.grp.")})
    n_tot = len(an["series"])
    ymail = [d["domain"] for d in D["infra"] if d["yandex_mail"] and d["role"] != "positive_control"]

    def grow(g):
        a, b = g6.get(g), g24.get(g)
        f = lambda r: f"{pct(r['median'])} [{pct(r['ci90'][0])}, {pct(r['ci90'][1])}]" if r else "n/a"
        p = lambda r: f"{r['p_drop10'] * 100:.0f}%" if r else "n/a"
        return f"<tr><td>{g}</td><td>{a['k'] if a else ''}</td><td>{f(a)}</td><td>{p(a)}</td><td>{f(b)}</td><td>{'yes' if a and a['credible_drop'] else 'no'}</td></tr>"
    groups = sorted(by["groups"], key=lambda g: (g.startswith("Control"), g))
    gtable = "".join(grow(g) for g in groups)

    waves = """<svg class="waves" viewBox="0 0 800 1130" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
      <defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0b1f45"/><stop offset=".55" stop-color="#143e86"/><stop offset="1" stop-color="#1f6fc9"/></linearGradient>
      <linearGradient id="w1" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#1baf7a" stop-opacity=".55"/><stop offset="1" stop-color="#2a78d6" stop-opacity=".25"/></linearGradient>
      <linearGradient id="w2" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#eb6834" stop-opacity=".35"/><stop offset="1" stop-color="#e87ba4" stop-opacity=".15"/></linearGradient></defs>
      <rect width="800" height="1130" fill="url(#bg)"/>
      <path d="M0 760 C 160 690, 300 830, 470 760 S 700 650, 800 700 L800 1130 L0 1130Z" fill="url(#w1)"/>
      <path d="M0 860 C 200 800, 350 930, 540 860 S 720 780, 800 820 L800 1130 L0 1130Z" fill="url(#w2)"/>
      <path d="M0 950 C 220 900, 420 1010, 620 950 S 760 900, 800 920 L800 1130 L0 1130Z" fill="rgba(255,255,255,.07)"/>
      <path d="M0 700 C 180 640, 330 770, 520 700 S 720 600, 800 640" stroke="rgba(255,255,255,.35)" stroke-width="1.2" fill="none"/>
      <path d="M0 735 C 190 675, 340 800, 530 735 S 730 640, 800 675" stroke="rgba(255,255,255,.18)" stroke-width="1" fill="none"/>
    </svg>"""

    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Yandex Ablation: Outage Attribution Study</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
@page {{ size: A4; margin: 15mm 15mm 14mm 15mm; }}
@page :first {{ margin: 0; }}
* {{ box-sizing: border-box; }}
body {{ font-family: Inter, "Helvetica Neue", Arial, sans-serif; color: #0b0b0b; font-size: 8.6pt; line-height: 1.42; margin: 0; }}
.title {{ position: relative; width: 210mm; height: 297mm; overflow: hidden; color: #fff; page-break-after: always; }}
.title svg.waves {{ position: absolute; inset: 0; width: 100%; height: 100%; }}
.title .in {{ position: relative; padding: 30mm 22mm; height: 100%; display: flex; flex-direction: column; }}
.title .kick {{ font-size: 9pt; letter-spacing: .22em; text-transform: uppercase; opacity: .8; }}
.title h1 {{ font-size: 33pt; line-height: 1.08; margin: 10mm 0 5mm; font-weight: 800; letter-spacing: -.02em; }}
.title .sub {{ font-size: 13.5pt; max-width: 150mm; opacity: .92; line-height: 1.35; }}
.title .meta {{ margin-top: auto; font-size: 9.5pt; line-height: 1.6; }}
.title .meta b {{ font-size: 12pt; display: block; }}
.title .tag {{ display: inline-block; border: 1px solid rgba(255,255,255,.5); border-radius: 20px; padding: 2px 10px; font-size: 8pt; margin-right: 6px; letter-spacing: .05em; }}
h2 {{ font-size: 12.5pt; margin: 0 0 2.5mm; letter-spacing: -.01em; border-bottom: 1.2pt solid #0b0b0b; padding-bottom: 1.2mm; }}
h3 {{ font-size: 9.6pt; margin: 3.5mm 0 1.2mm; }}
p {{ margin: 0 0 2mm; }}
.answer {{ background: linear-gradient(120deg, #0f2b55, #1c5cab); color: #fff; border-radius: 3mm; padding: 4mm 5mm; margin-bottom: 4mm; }}
.answer .k {{ font-size: 7pt; letter-spacing: .15em; text-transform: uppercase; opacity: .75; }}
.answer .t {{ font-size: 12pt; font-weight: 700; line-height: 1.3; margin-top: 1mm; }}
table {{ width: 100%; border-collapse: collapse; font-size: 7.4pt; margin: 1mm 0 2.5mm; }}
th {{ text-align: left; border-bottom: 1pt solid #0b0b0b; padding: 1.2mm 1.5mm; font-weight: 650; }}
td {{ border-bottom: .4pt solid #e1e0d9; padding: .75mm 1.5mm; vertical-align: top; }}
.prob {{ font-weight: 700; white-space: nowrap; font-size: 7.2pt; text-transform: uppercase; letter-spacing: .03em; }}
.fig {{ margin: 2mm 0 1mm; }}
.fig svg {{ width: 100%; height: auto; }}
.cap {{ font-size: 7.4pt; color: #52514e; margin-bottom: 3mm; }}
.cap b {{ color: #0b0b0b; }}
.cols {{ display: grid; grid-template-columns: 1fr 1fr; gap: 6mm; }}
.small {{ font-size: 7.1pt; color: #52514e; line-height: 1.35; }}
.small li {{ margin-bottom: .6mm; }}
.page {{ page-break-after: always; }}
.page:last-child {{ page-break-after: auto; }}
.hl {{ color: #d03b3b; font-weight: 650; }}
ul {{ margin: 0 0 2mm; padding-left: 4mm; }}
.foot {{ font-size: 6.6pt; color: #898781; margin-top: 2mm; }}
</style></head><body>

<section class="title">{waves}<div class="in">
  <div class="kick">Open-source intelligence assessment</div>
  <h1>Yandex Ablation:<br>Did the Data-Center Strikes Silence Russian Information Operations?</h1>
  <div class="sub">A time-resolved attribution of the October 2026 drone strikes on Yandex data centers to Russian influence-operation output across Telegram, Reddit, the web and the Pravda network.</div>
  <div class="meta">
    <span class="tag">INDEPENDENT ANALYSIS</span><span class="tag">OPEN SOURCES ONLY</span><br><br>
    <b>Stijn Van Severen</b>Independent Analyst<br>
    13 October 2026 · Data through 13 October 2026, 12:00 UTC
  </div>
</div></section>

<section class="page">
<h2>1. Bottom line</h2>
<div class="answer"><div class="k">Answer</div><div class="t">No broad reduction in Russian information operations is detectable. One automated pipeline, the Pravda network, stalled for {pr['dip_hours']:.0f} hours immediately after the Vladimir strike.</div></div>
<table><tr><th style="width:21mm">Probability</th><th>Key judgment</th></tr>
<tr><td class="prob">Almost certain</td><td>The strikes on Sasovo (night of 7 to 8 Oct) and Vladimir (11 Oct) removed about {sh['Sasovo'][1]*100:.0f}% and {sh['Vladimir'][1]*100:.0f}% of Yandex Cloud's externally reachable capacity; reachability fell to 22% of normal with no recovery by 13 Oct 12:00 UTC. The Kaluga strike (9 Oct) left no measurable cloud signature.</td></tr>
<tr><td class="prob">Likely</td><td>The Pravda network's publishing pipeline depended on infrastructure lost at Vladimir: output fell to {pr['dip_ratio']*100:.0f}% of expected for {pr['dip_hours']:.1f} h, starting {pr['offset_min']:.0f} min after the measured outage onset (scan p = {pr['p_scan']:.3f}), with only {pr['recovery_ratio']*100:.0f}% of the backlog published later. Its upstream Telegram sources did not dip.</td></tr>
<tr><td class="prob">Very unlikely</td><td>The strikes caused a broad reduction of Russian influence-operation output on social media, as claimed virally ("the bots went silent"). Across {nmem} channels, languages, communities and websites, no other platform group shows a credible drop; relative to controls, IO groups as a whole moved {pct(iom['median'])} (90% credible interval {pct(iom['ci90'][0])} to {pct(iom['ci90'][1])}){', upward with strike news' if iom['median'] > 0 else ''}.</td></tr>
<tr><td class="prob">Almost certain</td><td>The viral "Russian bot traffic collapsed" chart counted automated web requests from Yandex's own network (AS13238), dominated by its search crawler, which stops when the data centers go dark. It is not evidence about social-media bots.</td></tr></table>
<h3>Figure 1. The only time-locked effect</h3>
<div class="fig">{fig_key(D)}</div>
<div class="cap"><b>A.</b> The expected outage function estimated from published sources only (statements, status pages, satellite fire detections, complaint alerts) tracks the independently measured outage: onset errors of {abs(v['S1']['onset_error_min_vs_S2']['SAS']):.0f} min (Sasovo) and {abs(v['S1']['onset_error_min_vs_S2']['VLA']):.0f} min (Vladimir), 90% predictive coverage {v['S1']['predictive_coverage90']*100:.0f}%. <b>B.</b> Pravda network output collapses within the hour after the Vladimir outage and recovers with a catch-up burst; its Telegram input does not. No comparable dip follows Sasovo, where the decline started 7 h before the strike. Shaded: most likely dip interval.</div>
</section>

<section class="page">
<h2>2. Approach</h2>
<div class="cols"><div>
<h3>Question and design</h3>
<p>Do the outages caused by the strikes coincide with a causally attributable reduction in Russian information-operation (IO) output, specifically on the theme of the war in Ukraine? The strikes are treated as a natural experiment with three treated events and one internal placebo (an unexplained Yandex Cloud reachability dip on 27 to 28 September). Each link of the causal chain (strike, capacity loss, dependent services, automated pipelines, social-media output) is measured separately so that a break is visible.</p>
<h3>Expected outage function</h3>
<p>A capacity-weighted damage model: every strike contributes a curve whose timing, onset lag, failure ramp, damage and recovery follow from graded reports. Source grades (Admiralty system) are converted into probabilities and pooled into each strike's credibility. The model is estimated in three nested Bayesian stages with adaptive-tempering sequential Monte Carlo: attack reports only (S0), all published information (S1), and fused with IODA active-probing telemetry (S2). Stage 1 is validated out of sample against the measurement.</p>
<h3>Yandex dependency map</h3>
<p>Public DNS (A, MX, NS) for 51 domains shows that no IO or state-media website is hosted on Yandex. Seven outlets run their mail on Yandex 360 ({", ".join(ymail)}); their channels form a separate exposure stratum.</p>
</div><div>
<h3>Outcomes and inference</h3>
<p>Hourly and 10-minute output of {n_tot} series ({len(io_ids)} IO output series plus controls, services and infrastructure): 806,762 Pravda articles on 88 sites; {n_tg} Telegram channels (state, military bloggers, tabloids, foreign-audience IO, independent, Ukrainian and business controls); web publishing (ukraina.ru against two independent outlets); {n_rd} Reddit communities and an account-level stream of r/UkraineRussiaReport. Each series gets an out-of-sample seasonal counterfactual. Inference combines:</p>
<ul class="small">
<li>placebo-in-time windows (6 h and 24 h) and a seasonal-naive same-weekday check;</li>
<li>a Bayesian hierarchical model pooling {nmem} member series into platform groups, with a Yandex-dependency term and common news-shock variance;</li>
<li>10-minute change-point dating of dips against the outage onset, calibrated with 400 placebo origins, and a backlog test;</li>
<li>dose-response on the expected outage function with HAC errors, theme contrasts (war minus non-war), Benjamini-Hochberg FDR, a 20% equivalence bound, and analysis of competing hypotheses.</li></ul>
<p class="small">A drop counts as credible only if the posterior probability of a drop larger than 10% exceeds 90%, the group placebo p is below 0.05 and the seasonal-naive check agrees. A dip counts as time-locked only if it is significant and starts at or after the onset.</p>
</div></div>
<h2 style="margin-top:3mm">3. Results</h2>
<h3>Figure 2. Bayesian posterior change per platform group after the Vladimir strike</h3>
<div class="fig">{fig_groups(D)}</div>
<div class="cap">Posterior median and 90% credible interval. <span class="hl">Red</span>: credible drop. Green: drops larger than 20% ruled out. Grey: inconclusive. The red band marks drops beyond the 20% smallest effect of interest.</div>
</section>

<section class="page">
<table><tr><th>Platform group</th><th>n</th><th>Vladimir 6 h [90% CrI]</th><th>P(drop &gt;10%)</th><th>Vladimir 24 h [90% CrI]</th><th>Credible drop</th></tr>{gtable}</table>
<div class="cols"><div>
<h3>Infrastructure and services</h3>
<p>Yandex Cloud: {dt['SAS']['onset_utc'][1][11:16]} UTC onset after Sasovo (strike {dt['SAS']['strike_utc'][1][11:16]}, full loss {dt['SAS']['full_loss_utc'][1][11:16]}); {dt['VLA']['onset_utc'][1][11:16]} UTC after Vladimir (strike {dt['VLA']['strike_utc'][1][11:16]}). BGP visibility stayed intact (a data-plane loss). Hosting, access and platform controls (Selectel, Timeweb, Beget, VK, Rostelecom, MTS, MegaFon, Beeline, Yandex Cloud Kazakhstan) show no matching steps. Russian Wikipedia user traffic fell {pct(S['wiki.ru.wikipedia.user']['windows']['VLA_24h']['effect'])} in 24 h after Vladimir, consistent with Yandex Search and app disruption; complaint alerts for Yandex Pay, Go and KinoPoisk surged from 00:47 UTC.</p>
<h3>Where an IO effect is and is not seen</h3>
<ul>
<li><span class="hl">Pravda network:</span> the only credible, time-locked drop (Vladimir 6 h {pct(g6['Pravda network (automated web)']['median'])}). English, German and French sites dip 22 min after onset.</li>
<li>Telegram state media, military bloggers, tabloids and foreign-audience IO (InfoDefense, Strategic Culture, Sputnik Africa, Rybar, Slavyangrad, embassy): no credible drop.{state_note}</li>
<li>Topic substitution, not capacity loss: non-war posts of state ({pct(W('tg.grp.pro_kremlin_state.other'))}) and tabloid channels ({pct(W('tg.grp.pro_kremlin_tabloid.other'))}) fell after Vladimir while their war posts rose ({pct(W('tg.grp.pro_kremlin_state.war'))}, {pct(W('tg.grp.pro_kremlin_tabloid.war'))}) and their totals did not change significantly.</li>
<li>Outlets on Yandex 360 mail: extra effect {pct(beta['median'])} (90% {pct(beta['ci90'][0])} to {pct(beta['ci90'][1])}), no different from the {pct(beta_pl['median'])} seen in the placebo window.</li>
<li>Web (ukraina.ru) and Reddit (pro-Russian, war and the political communities named in viral claims): no drop; war communities rose with strike news. No war-specific reduction anywhere.</li></ul>
</div><div>
<h3>Overall tally (Vladimir, 24 h)</h3>
<p>Of {len(io_ids)} IO series, {verd.get('Large drop ruled out', 0)} rule out a drop larger than 20%, {verd.get('Inconclusive', 0)} are inconclusive, {verd.get('Increase detected', 0)} increased and {verd.get('Drop detected', 0)} show an FDR-significant drop that survives the seasonal-naive check{drop_names}; the Telegram cases are topic substitution (above).</p>
<h3>Analysis of competing hypotheses</h3>
<p>A narrow dependency of specific automated pipelines (H2) carries no weighted inconsistency. A broad IO collapse (H1) is contradicted by every platform-level measurement. "No IO effect" (H3) is contradicted only by the Pravda dip.</p>
<h3>Limitations</h3>
<ul class="small">
<li>X, VK and closed bot infrastructure are not observable with open data; small dedicated networks could go undetected (median single-series minimum detectable drop about 26% over 24 h, 10 to 20% for pooled groups).</li>
<li>The strikes were themselves major news, inflating war-related activity; theme contrasts and controls mitigate but cannot remove this.</li>
<li>Pravda attribution rests on timing. Its sites sit behind Cloudflare, so hosting is not directly observable, and Sasovo, which removed 38% of cloud capacity, produced no time-locked dip.</li>
<li>Sanctioned outlets blocked by the national resolver (RT, Sputnik, RIA) were mapped through public DNS but not crawled. Recovery estimates are right-censored.</li></ul>
</div></div>
<h3>Principal sources</h3>
<p class="small">Yandex Cloud status incidents 2092 and 2136 and incident API (status.yandex.cloud); Yandex Telegram posts 5900 to 5905; Vladimir governor post 10997; IODA raw signals (Georgia Tech); RIPE Stat; NASA FIRMS VIIRS; Cloudflare Radar and NetBlocks posts (Bluesky); Detector404 and Sboy.rf alerts; Wikimedia pageviews API; Pravda network, ukraina.ru, zona.media and theins.ru sitemaps; Telegram public previews; Arctic Shift Reddit archive; public DNS via 1.1.1.1, 8.8.8.8, 9.9.9.9. Methods: Del Moral, Doucet and Jasra (2006); Brodersen et al. (2015); Newey and West (1987); Benjamini and Hochberg (1995); DerSimonian and Laird (1986); Gelman and Rubin (1992); Lakens (2017); Heuer (1999); ICD 203; NATO AJP-2.1. Interactive dashboard, code and pipeline: OSINT_YandexOutage repository.</p>

</section>
</body></html>"""
    (OUT / "report.html").write_text(html)
    pdf = OUT / "REPORT.pdf"
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--virtual-time-budget=8000",
                    f"--print-to-pdf={pdf}", (OUT / "report.html").as_uri()], check=True, capture_output=True, timeout=180)
    from pypdf import PdfReader, PdfWriter
    r = PdfReader(str(pdf))
    w = PdfWriter(clone_from=r)
    w.add_metadata({"/Title": "Yandex Ablation: Outage Attribution Study", "/Author": "Stijn Van Severen",
                    "/Subject": "Open-source intelligence assessment of the October 2026 Yandex data-center strikes"})
    with open(pdf, "wb") as f:
        w.write(f)
    import shutil
    shutil.copy(pdf, ROOT / "REPORT.pdf")
    shutil.copy(pdf, ROOT / "docs" / "REPORT.pdf")
    print("pages:", len(r.pages), pdf)


if __name__ == "__main__":
    build()
