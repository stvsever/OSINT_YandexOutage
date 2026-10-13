"""Build the concise PDF report (title page plus four pages) from the pipeline outputs.

Figures are drawn with matplotlib as inline SVG, the document is laid out in
HTML with print CSS (APA-style figure and table captions) and rendered to PDF
with headless Chrome. System fonts are used so that the PDF text layer extracts
cleanly.
"""
from __future__ import annotations

import collections
import io
import json
import re
import shutil
import subprocess
from pathlib import Path

import matplotlib
import numpy as np
import pandas as pd

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
OUT = ROOT / "report"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

INK, INK2, INK3, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
BLUE, ORANGE, AQUA, RED, GREEN = "#2a78d6", "#eb6834", "#1baf7a", "#d03b3b", "#0ca30c"
plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial"],
                     "font.size": 7.6, "axes.edgecolor": "#c3c2b7", "axes.labelcolor": INK2, "xtick.color": INK2,
                     "ytick.color": INK2, "axes.spines.top": False, "axes.spines.right": False, "svg.fonttype": "none",
                     "axes.titlesize": 8, "axes.titleweight": "bold", "axes.titlelocation": "left"})


def svg(fig) -> str:
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight", transparent=True)
    plt.close(fig)
    s = buf.getvalue()
    return s[s.index("<svg"):]


def pct(x, d=0):
    if x is None or not np.isfinite(x):
        return "n/a"
    t = f"{x * 100:.{d}f}"
    return f"{0:.{d}f}%" if float(t) == 0 else f"{'+' if x > 0 else '−'}{abs(float(t)):.{d}f}%"


def load():
    j = lambda n: json.loads((PROC / n).read_text())
    return dict(eof=j("eof_results.json"), tim=j("timing_results.json"), an=j("analysis_results.json"), by=j("bayes_results.json"),
                infra=j("infra_map.json"), actors=j("actor_infra.json"), ver=j("verification.json"),
                eof10=pd.read_parquet(PROC / "eof_10min.parquet"), meta=j("series_meta.json"))


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

    fig, ax = plt.subplots(2, 1, figsize=(6.7, 3.85), sharex=True, gridspec_kw={"height_ratios": [1, 1.2], "hspace": 0.62})
    a = ax[0]
    a.fill_between(s1.index, s1.q05 * 100, s1.q95 * 100, color=BLUE, alpha=0.13, lw=0, step="post", label="Expected outage, 90% band (open sources only)")
    a.plot(s1.index, s1["mean"] * 100, color=BLUE, lw=1.5, drawstyle="steps-post", label="Expected outage, mean (Stage 1)")
    a.plot(x[sel], io_[sel], color=ORANGE, lw=1.2, label="Measured outage (IODA active probing)")
    a.set_ylim(0, 100); a.set_ylabel("Yandex Cloud offline (%)")
    a.set_title("A   Outage: open-source expectation versus measurement", color=INK)
    a.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08), frameon=False, fontsize=6.6, ncol=3, handlelength=1.6)
    b = ax[1]
    b.axhline(100, color="#c3c2b7", lw=0.8)
    pe = t["results"]["pravda.total"]["events"]["VLA"]
    b.axvspan(pd.Timestamp(pe["tau1_map"]), pd.Timestamp(pe["tau2_map"]), color=RED, alpha=0.08, lw=0)
    b.plot(x[sel], ratio("pravda.total")[sel], color=AQUA, lw=1.4, label="Pravda network output (automated, 88 sites)")
    b.plot(x[sel], ratio("tg.prokremlin.all")[sel], color=INK3, lw=0.9, alpha=0.9, label="Pro-Kremlin Telegram output (its upstream input)")
    b.set_ylim(0, 230); b.set_ylabel("Output, % of expected")
    b.set_title("B   Information-operation output relative to the seasonal counterfactual (1 h rolling)", color=INK)
    b.legend(loc="upper center", bbox_to_anchor=(0.5, -0.16), frameon=False, fontsize=6.6, ncol=2, handlelength=1.6)
    b.text(pd.Timestamp(pe["tau2_map"]) + pd.Timedelta(minutes=40), 205,
           f"Pravda {pct(pe['dip_ratio'] - 1)} for {pe['dip_hours']:.0f} h,\nstarting {pe['offset_min']:.0f} min after onset\n(p = {fp(pe['p_scan'])})",
           fontsize=6.4, color=RED, va="top", bbox=dict(facecolor="white", edgecolor="none", alpha=0.9, pad=1.5))
    for axx in ax:
        for k, c in (("SAS", RED), ("KAL", INK3), ("VLA", RED)):
            axx.axvline(on[k], color=c, lw=0.9, alpha=0.8)
        axx.grid(axis="y", color=GRID, lw=0.6)
    for k, lab in (("SAS", "Sasovo"), ("KAL", "Kaluga"), ("VLA", "Vladimir")):
        ax[0].text(on[k] + pd.Timedelta(minutes=40), 92, lab, fontsize=6.6, color=INK2)
    b.xaxis.set_major_locator(mdates.DayLocator()); b.xaxis.set_major_formatter(mdates.DateFormatter("%d Oct"))
    return svg(fig)


def fig_groups(by):
    """Figure 2: Bayesian posterior change per platform group, Vladimir 6 h and 24 h, with values."""
    groups = sorted(by["groups"], key=lambda g: (g.startswith("Control"), g))
    fig, ax = plt.subplots(1, 2, figsize=(6.7, 3.05), sharey=True, gridspec_kw={"wspace": 0.2})
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
            a.plot([max(r["ci90"][0], -0.6), min(r["ci90"][1], 1.0)], [y, y], color=col, lw=1.8, solid_capstyle="round")
            a.plot(max(min(r["median"], 1.0), -0.6), y, "o", color=col, ms=4, mec="white", mew=0.8)
            a.text(1.03, y, pct(r["median"]), transform=a.get_yaxis_transform(), fontsize=6.2, va="center",
                   color=RED if r["credible_drop"] else INK2, fontweight="bold" if r["credible_drop"] else "normal")
        a.set_xlim(-0.6, 1.0); a.set_title(title, color=INK); a.set_xticks([-0.4, -0.2, 0, 0.4, 0.8])
        a.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v * 100:+.0f}%".replace("+0%", "0%").replace("-", "−")))
        a.grid(axis="x", color=GRID, lw=0.6)
    ax[0].set_yticks(ys); ax[0].set_yticklabels([g.replace("Control: ", "Control, ") for g in groups], fontsize=6.8)
    sep = sum(1 for g in groups if g.startswith("Control"))
    for a in ax:
        a.axhline(sep - 0.5, color="#c3c2b7", lw=0.6)
    return svg(fig)


def fp(p):
    """p-value with two significant digits below 0.01, as in the dashboard."""
    return "<0.001" if p < 0.001 else (f"{p:.2g}" if p < 0.01 else f"{p:.3f}")


def an_(n):
    """Indefinite article for a spoken number (an 11-hour, a 7-hour)."""
    return "an" if str(int(round(n))).startswith(("8", "11", "18")) else "a"


TITLE = "Yandex Ablation: Did the Data-Center Strikes Silence Russian Information Operations?"


def build():
    D = load()
    ev = D["eof"]; v = ev["validation_vs_ioda"]; dt = ev["downtime"]["cloud_S2"]
    by = D["by"]["themes"]["all"]; an = D["an"]; tim = D["tim"]["results"]
    pr = tim["pravda.total"]["events"]["VLA"]
    S = an["series"]
    io_ids = [k for k in S if D["meta"][k]["layer"] == "io" and not D["meta"][k].get("hidden")]
    verd = pd.Series([S[k]["verdict"] for k in io_ids]).value_counts().to_dict()
    v24, v6 = by["windows"]["VLA_24h"], by["windows"]["VLA_6h"]
    nmem = v24["n_members"]
    g6, g24 = v6["groups"], v24["groups"]
    beta, iom = v24["beta_yandex_mail"], v24["io_minus_control"]
    beta_pl = by["windows"]["SEP27_24h"]["beta_yandex_mail"]
    W = lambda sid, k="VLA_24h": S[sid]["windows"][k]["effect"] if sid in S and k in S[sid]["windows"] else None
    dn = [k for k in io_ids if S[k]["verdict"] == "Drop detected"]
    dp = [D["meta"][k]["label"].replace("Pravda network: ", "") for k in dn if k.startswith("pravda.")]
    dt_ = [D["meta"][k]["label"].split(" (")[0].replace("Pro-Kremlin ", "").lower() for k in dn if k.endswith(".other")]
    parts = []
    if dp:
        parts.append(f"{'two' if len(dp) == 2 else len(dp)} Pravda editions ({' and '.join(x.replace('language ro', 'Romanian') for x in dp)})")
    if dt_:
        parts.append(f"the non-war posts of {' and '.join(dt_)}, which is topic substitution")
    rest = len(dn) - len(dp) - len(dt_)
    if rest:
        parts.append(f"{rest} other series")
    drop_txt = "; ".join(parts) or "none"
    stv = tim.get("tg.grp.pro_kremlin_state.all", {}).get("events", {}).get("VLA", {})
    state_note = ""
    if stv and stv.get("p_scan", 1) < 0.05 and (stv.get("naive_ratio") or 0) > 0.85:
        state_note = (f" A {stv['dip_hours']:.0f} h dip that the regression counterfactual flags in state channels falls on an ordinary"
                      f" Sunday: against the same hours on the previous three Sundays, output was {stv['naive_ratio'] * 100:.0f}% of normal.")
    n_tg = sum(1 for k in D["meta"] if k.startswith("tg.ch."))
    n_rd = len({k.split(".")[1] for k in D["meta"] if k.startswith("rd.") and k.endswith(".comments.all") and not k.startswith("rd.grp.")})
    n_tot = sum(1 for k in S if not D["meta"][k].get("hidden"))
    ymail = [d["domain"] for d in D["infra"] if d["yandex_mail"] and d["role"] != "positive_control"]
    # language editions of the Pravda network that dip early and significantly
    langs = {"en": "English", "de": "German", "fr": "French", "es": "Spanish", "ar": "Arabic", "sr": "Serbian"}
    early = [(langs[k], tim[f"pravda.lang.{k}"]["events"]["VLA"]) for k in langs if f"pravda.lang.{k}" in tim]
    early = [(n, e) for n, e in early if e["p_scan"] < 0.05 and 0 <= e["offset_min"] <= 60]
    early_txt = (f"The {', '.join(n for n, _ in early[:-1])} and {early[-1][0]} editions dip {min(e['offset_min'] for _, e in early):.0f} min after onset."
                 if len(early) >= 2 else "")
    # infrastructure of attributed operations
    A = D["actors"]
    by_ims = collections.OrderedDict()
    for d in sorted(A, key=lambda d: (not d["ims"].startswith("Storm"), d["ims"])):
        by_ims.setdefault(d["ims"], []).append(d)

    def holder(h):
        h = re.sub(r"^\S+\s+(-\s+)?", "", h or "").replace('"', "")
        h = re.sub(r",? (Inc|LLC|Ltd|Limited|GmbH|SE|SAS)\.?$", "", h).replace("Domain names registrar ", "")
        return h

    arows = ""
    for ims, arr in by_ims.items():
        hold = collections.Counter(holder(d["holder"]) for d in arr if d.get("holder")).most_common(3)
        htxt = ", ".join(f"{h} ({c})" if len(arr) > 1 else h for h, c in hold) or "n/a"
        yx = sum(1 for d in arr if d["yandex_hosting"] or d["yandex_mail"] or d["yandex_dns"])
        name, src = (ims.replace(" (VIGINUM)", ""), "VIGINUM") if "VIGINUM" in ims else (ims, "EEAS")
        arows += (f"<tr><td>{name}</td><td>{src}</td><td class='n'>{len(arr)}</td><td class='n'>{sum(d['resolves'] for d in arr)}</td>"
                  f"<td class='n'>{sum(1 for d in arr if d.get('http') == 200)}</td><td>{htxt}</td><td class='n'>{yx or 'none'}</td></tr>")
    nA = len(A); nAres = sum(d["resolves"] for d in A)
    media_y = sum(1 for d in D["infra"] if d["role"] != "positive_control" and (d["yandex_hosting"] or d["yandex_dns"]))
    arows += (f"<tr><td>State and IO media outlets</td><td>this study</td><td class='n'>{sum(1 for d in D['infra'] if d['role'] != 'positive_control')}</td>"
              f"<td class='n'>n/a</td><td class='n'>n/a</td><td>DDoS-Guard, Rostelecom, Rossiya Segodnya and others</td><td class='n'>{f"{media_y} hosting" if media_y else "mail only (" + str(len(ymail)) + ")"}</td></tr>")
    ver = D["ver"]; nver = sum(x["n"] for x in ver)
    exact = [x["source"] for x in ver if x.get("exact_share") == 1]
    inexact = [x for x in ver if x.get("exact_share") not in (None, 1)]
    ver_txt = (f"Random samples of every stored source ({nver} values in total) were downloaded again from the original services, bypassing the cache. "
               f"{', '.join(exact[:-1])} and {exact[-1]} match exactly"
               + ("".join(f"; {x['source']} matches in {x['exact_share'] * 100:.0f}% of hours (largest difference {x['max_abs_diff']:.0f}, from comments deleted or added after collection)" for x in inexact)) + ".")
    # key numbers for the abstract
    # half-up rounding, as in the dashboard
    sas_err, vla_err = (int(abs(v["S1"]["onset_error_min_vs_S2"][k]) + 0.5) for k in ("SAS", "VLA"))
    iu = pd.read_parquet(PROC / "ioda_cloud_unreachable_hourly.parquet")["ioda_unreachable_frac"]
    on = {k: pd.Timestamp(t) for k, t in an["onsets"].items()}
    off_now = float(iu.dropna().iloc[-12:].mean())
    off_sas = float(iu[(iu.index >= on["SAS"] + pd.Timedelta(hours=3)) & (iu.index < on["VLA"] - pd.Timedelta(hours=1))].mean())

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

    def kj(i, head, lik, conf, body):
        return (f"<div class='kj'><p class='kjh'><span class='kjn'>{i}</span><b>{head}</b></p>"
                f"<p class='kjm'><i>{lik}; {conf} confidence.</i></p><p class='kjb'>{body}</p></div>")

    KJ = "".join([
        kj(1, "The strikes caused a major, sustained loss of Yandex Cloud capacity.", "Almost certain (95 to 99%)", "high",
           f"Measured reachability of Yandex Cloud fell by {off_sas * 100:.0f}% after the Sasovo strike (night of 7 to 8 October) and by {off_now * 100:.0f}% in total after the Vladimir strike (11 October), with no recovery by 13 October, 12:00 UTC. The Kaluga strike (9 October) left no measurable cloud signature. Status pages, IODA, NetBlocks, Cloudflare Radar and NASA FIRMS agree to within minutes."),
        kj(2, "The outage temporarily stalled one automated influence pipeline, the Pravda network.", "Likely (55 to 80%)", "moderate",
           f"Output fell to {pr['dip_ratio'] * 100:.0f}% of expected for {pr['dip_hours']:.1f} h, starting {pr['offset_min']:.0f} min after the measured Vladimir outage (change-point scan p = {fp(pr['p_scan'])}), across its language editions, while the Telegram channels it republishes did not dip; {pr['recovery_ratio'] * 100:.0f}% of the backlog was published later. Confidence is moderate because Sasovo produced no comparable dip and the network's hosting, behind Cloudflare, cannot be observed."),
        kj(3, "Russian information-operation output on the observed platforms continued at expected levels.", "Very likely (80 to 95%)", "moderate",
           f"Across {nmem} channels, language editions, communities and websites, no platform group other than the Pravda network shows a credible drop. This includes Telegram state media, military bloggers, tabloids and foreign-audience channels, outlets on Yandex 360 mail, and the outlets of African Initiative and RRN named by the EEAS. Relative to controls, IO groups moved {pct(iom['median'])} (90% credible interval {pct(iom['ci90'][0])} to {pct(iom['ci90'][1])}) in the 24 h after Vladimir. X, VK and closed bot infrastructure could not be observed."),
        kj(4, "The web infrastructure of attributed influence operations does not run on Yandex.", "Very likely (80 to 95%)", "moderate",
           f"None of {nA} domains attributed to Storm-1516, African Initiative, RRN, R-FBI or the Pravda network by VIGINUM and the EEAS ({nAres} resolving), and none of the state and IO media domains mapped here, is hosted on a Yandex network or uses Yandex name servers. Seven media outlets use Yandex 360 mail; their channels show no strike-specific change. DNS was measured after the strikes, so earlier migrations cannot be excluded."),
    ])

    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{TITLE}</title>
<style>
@page {{ size: A4; margin: 15mm 17mm 14mm 17mm; @bottom-center {{ content: counter(page); }} }}
@page :first {{ margin: 0; }}
* {{ box-sizing: border-box; }}
html {{ font-variant-ligatures: none; font-kerning: normal; }}
body {{ font-family: Charter, "Iowan Old Style", Georgia, "Times New Roman", serif; color: #111; font-size: 9.2pt; line-height: 1.38; margin: 0; }}
.title {{ position: relative; width: 210mm; height: 297mm; overflow: hidden; color: #fff; page-break-after: always; font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; }}
.title svg.waves {{ position: absolute; inset: 0; width: 100%; height: 100%; }}
.title .in {{ position: relative; padding: 32mm 24mm 28mm; height: 100%; display: flex; flex-direction: column; }}
.title .kick {{ font-size: 9.5pt; text-transform: uppercase; opacity: .85; font-weight: 500; }}
.title h1 {{ font-family: Charter, Georgia, serif; font-size: 30pt; line-height: 1.14; margin: 9mm 0 6mm; font-weight: 700; max-width: 160mm; }}
.title .sub {{ font-family: Charter, Georgia, serif; font-size: 13pt; max-width: 150mm; opacity: .93; line-height: 1.4; font-style: italic; }}
.title .meta {{ margin-top: auto; font-size: 9.5pt; line-height: 1.6; }}
.title .meta b {{ font-size: 13pt; display: block; font-weight: 600; }}
.title .tag {{ display: inline-block; border: 1px solid rgba(255,255,255,.55); border-radius: 20px; padding: 2px 10px; font-size: 8pt; margin-right: 6px; }}
h2 {{ font-size: 12pt; margin: 5mm 0 2mm; font-weight: 700; }}
h2.first {{ margin-top: 0; }}
h3 {{ font-size: 9.8pt; margin: 3.2mm 0 1mm; font-weight: 700; font-style: italic; }}
p {{ margin: 0 0 2mm; text-align: justify; hyphens: auto; }}
.abstract {{ margin: 0 0 4mm; }}
.abstract p {{ font-size: 9.1pt; }}
.abstract .lab {{ font-weight: 700; text-align: left; margin-bottom: 1mm; }}
.bl {{ border-top: 1.4pt solid #111; border-bottom: .6pt solid #111; padding: 2.6mm 0 2.4mm; margin: 0 0 4mm; display: grid; grid-template-columns: 27mm 1fr; column-gap: 4mm; align-items: baseline; }}
.bl .lab {{ font-family: "Helvetica Neue", Arial, sans-serif; font-size: 7.6pt; font-weight: 700; text-transform: uppercase; color: #143e86; }}
.bl .txt {{ font-size: 11pt; font-weight: 700; line-height: 1.35; }}
.bl .sub {{ grid-column: 2; font-size: 8.8pt; color: #333; margin-top: 1.2mm; text-align: left; }}
.kj {{ margin: 0 0 2.6mm; break-inside: avoid; }}
.kj p {{ margin: 0; }}
.kjh {{ display: flex; gap: 2.4mm; text-align: left; }}
.kjn {{ flex: none; width: 5mm; height: 5mm; border-radius: 1mm; background: #143e86; color: #fff; font-family: "Helvetica Neue", Arial, sans-serif; font-size: 7.4pt; font-weight: 700; display: inline-flex; align-items: center; justify-content: center; margin-top: .3mm; }}
.kjm, .kjb {{ padding-left: 7.4mm; }}
.kjm {{ color: #143e86; font-size: 8.8pt; }}
.kjb {{ font-size: 9pt; }}
figure, .tbl {{ margin: 3mm 0 3.5mm; break-inside: avoid; text-align: left; }}
.flab {{ font-weight: 700; margin: 0; text-align: left; }}
.ftit {{ font-style: italic; margin: .6mm 0 1.6mm; text-align: left; }}
figure svg {{ width: 100%; height: auto; display: block; }}
.note {{ font-size: 8.3pt; line-height: 1.38; margin-top: 1.4mm; text-align: left; }}
.note i {{ font-style: italic; }}
table {{ border-collapse: collapse; font-size: 8pt; width: 100%; font-family: "Helvetica Neue", Arial, sans-serif; }}
thead th {{ text-align: left; border-top: 1pt solid #111; border-bottom: .6pt solid #111; padding: 1.1mm 1.6mm; font-weight: 600; }}
tbody td {{ padding: .7mm 1.6mm; vertical-align: top; }}
tbody tr:last-child td {{ border-bottom: 1pt solid #111; }}
td.n {{ text-align: right; font-variant-numeric: tabular-nums; }}
ul {{ margin: 0 0 2mm; padding-left: 4.5mm; }}
li {{ margin-bottom: .9mm; text-align: justify; }}
.hl {{ color: #b3261e; font-weight: 700; }}
.page {{ page-break-after: always; }}
.page:last-child {{ page-break-after: auto; }}
.refs p {{ font-size: 7.4pt; line-height: 1.3; padding-left: 5mm; text-indent: -5mm; margin: 0 0 .8mm; text-align: left; }}
.refs {{ columns: 2; column-gap: 7mm; }}
</style></head><body>

<section class="title">{waves}<div class="in">
  <div class="kick">Open-source intelligence assessment</div>
  <h1>{TITLE.replace("Data-Center", '<span style="white-space:nowrap">Data-Center</span>')}</h1>
  <div class="sub">A time-resolved attribution of the October 2026 drone strikes on Yandex data centers to Russian influence-operation output on Telegram, Reddit, the web and the Pravda network</div>
  <div class="meta">
    <span class="tag">Independent analysis</span><span class="tag">Open sources only</span><br><br>
    <b>Stijn Van Severen</b>Independent Analyst<br>
    14 October 2026 · Data through 13 October 2026, 12:00 UTC
  </div>
</div></section>

<section class="page">
<div class="abstract"><p class="lab">Abstract</p>
<p>Between 7 and 11 October 2026, drones struck Yandex data centers in Sasovo, Kaluga and Vladimir. This assessment tests whether the resulting outages reduced Russian information-operation (IO) output. An expected-outage function estimated from graded open sources alone reconstructs the measured outage onsets to within {sas_err:.0f} and {vla_err:.0f} minutes. The output of {n_tot} series, covering the Pravda network, {n_tg} Telegram channels, web outlets including those of influence operations named by the EEAS, and {n_rd} Reddit communities, is compared with out-of-sample seasonal counterfactuals using placebo windows, a Bayesian hierarchical model and 10-minute change-point timing. Only the Pravda network shows a reduction that is time-locked to an outage: its output fell to {pr['dip_ratio'] * 100:.0f}% of expected for {pr['dip_hours']:.0f} hours, starting {pr['offset_min']:.0f} minutes after the Vladimir outage. No other platform group shows a credible drop, and none of {nA} domains attributed to Russian influence operations by VIGINUM and the EEAS is hosted on Yandex. The strikes disrupted Yandex substantially but did not measurably silence Russian information operations.</p></div>

<div class="bl"><div class="lab">Bottom line</div><div class="txt">A major Yandex Cloud outage, but no broad reduction in Russian information operations.</div>
<div class="sub">The single exception is {an_(pr['dip_hours'])} {pr['dip_hours']:.0f}-hour stall of the automated Pravda network immediately after the Vladimir strike.</div></div>

<h2>Key Judgments</h2>
{KJ}
<p class="note"><i>Note.</i> Likelihood follows the estimative scale of Intelligence Community Directive 203; confidence reflects the quality, independence and coverage of the evidence.</p>

<h2>1. Question and Approach</h2>
<p>Do the outages caused by the strikes coincide with a causally attributable reduction in Russian IO output, in particular on the war in Ukraine? The strikes are treated as a natural experiment with three treated events and one internal placebo (an unexplained Yandex Cloud dip on 27 September). Each link of the causal chain, from strike to capacity loss, dependent services, automated pipelines and social-media and web output, is measured separately.</p>
<p><i>Expected outage function.</i> Each strike contributes a capacity-weighted damage curve whose timing, onset lag, failure ramp, damage and recovery follow from graded reports. Admiralty grades are converted into probabilities and pooled into each strike's credibility. The model is estimated in three nested Bayesian stages with adaptive-tempering sequential Monte Carlo on a 10-minute grid: attack reports only (S0), all published information (S1), and fused with IODA active-probing telemetry (S2). Stage 1 is validated out of sample against the measurement (Figure 1A).</p>
<p><i>Outcomes and inference.</i> Each series receives an out-of-sample seasonal counterfactual (hour of day, day of week and trend, fitted on the baseline only). Inference combines placebo-in-time windows of 6 and 24 hours with a same-weekday check; a Bayesian hierarchical model that pools {nmem} member series into platform groups, with a Yandex-dependency term and the common news-shock variance; change-point dating of dips against the outage onset, calibrated with 400 placebo origins; dose-response on the expected outage function with HAC errors; war-minus-non-war theme contrasts; Benjamini-Hochberg false-discovery control; a 20% equivalence bound; and analysis of competing hypotheses. A drop is credible only if the posterior probability of a drop larger than 10% exceeds 90%, the group placebo p is below 0.05 and the same-weekday check agrees. A dip is time-locked only if it is significant and starts at or after the onset.</p>
<p><i>Actors.</i> The actor set follows the EEAS 4th FIMI threat report and the VIGINUM report on Storm-1516: the Pravda network (Portal Kombat), African Initiative, RRN and R-FBI outlets and channels, and 338 Storm-1516 domains, whose hosting was resolved through public DNS.</p>

<figure><p class="flab">Figure 1</p><p class="ftit">Open-Source Outage Expectation, Measured Outage and Pravda Network Output, 7 to 12 October 2026</p>
{fig_key(D)}
<p class="note"><i>Note.</i> (A) The expected outage function estimated from published sources only (statements, status pages, satellite fire detections, complaint alerts) tracks the independently measured outage, with onset errors of {sas_err:.0f} min (Sasovo) and {vla_err:.0f} min (Vladimir) and {v['S1']['predictive_coverage90'] * 100:.0f}% coverage of the 90% predictive band. (B) Pravda network output collapses within the hour after the Vladimir outage and recovers with a partial catch-up; its Telegram input does not dip. No comparable dip follows Sasovo, where a decline started 7 h before the strike. Shading marks the most likely dip interval; vertical lines mark outage onsets (UTC).</p></figure>

<h2>2. Results</h2>
<h3>2.1 Infrastructure and Dependent Services</h3>
<p>Yandex Cloud reachability fell from {dt['SAS']['onset_utc'][1][11:16]} UTC after the Sasovo strike (strike {dt['SAS']['strike_utc'][1][11:16]}, full loss {dt['SAS']['full_loss_utc'][1][11:16]}) and from {dt['VLA']['onset_utc'][1][11:16]} UTC after the Vladimir strike (strike {dt['VLA']['strike_utc'][1][11:16]}). BGP visibility stayed intact, indicating a data-plane loss. Hosting, access and platform controls (Selectel, Timeweb, Beget, VK, Rostelecom, MTS, MegaFon, Beeline and Yandex Cloud Kazakhstan) show no matching steps. Russian Wikipedia user traffic fell {pct(W('wiki.ru.wikipedia.user'))} in the 24 h after Vladimir, consistent with disruption of Yandex Search and apps, and complaint alerts for Yandex Pay, Go and KinoPoisk surged from 00:47 UTC.</p>
<h3>2.2 Where an Effect on Information Operations Is and Is Not Seen</h3>
<ul>
<li><span class="hl">Pravda network.</span> The only credible and time-locked drop (Vladimir, first 6 h: {pct(g6['Pravda network (automated web)']['median'])}, P(drop &gt; 10%) = {g6['Pravda network (automated web)']['p_drop10'] * 100:.0f}%). {early_txt}</li>
<li><i>Telegram.</i> State media, military bloggers, tabloids and foreign-audience channels (including InfoDefense, Strategic Culture, Sputnik Africa, Rybar and Slavyangrad) show no credible drop.{state_note} Non-war posts of state ({pct(W('tg.grp.pro_kremlin_state.other'))}) and tabloid channels ({pct(W('tg.grp.pro_kremlin_tabloid.other'))}) fell while their war posts rose ({pct(W('tg.grp.pro_kremlin_state.war'))} and {pct(W('tg.grp.pro_kremlin_tabloid.war'))}); this is topic substitution toward strike news, not lost capacity.</li>
<li><i>EEAS-named outlets.</i> African Initiative and RRN websites ({pct(g24['Web: EEAS-named IMS outlets']['median'])} over 24 h) and African Initiative's Telegram channels ({pct(g24['Telegram: EEAS-named IMS']['median'])}) show no credible drop and no time-locked dip.</li>
<li><i>Yandex 360 mail.</i> Outlets on Yandex mail show an extra effect of {pct(beta['median'])} (90% {pct(beta['ci90'][0])} to {pct(beta['ci90'][1])}), indistinguishable from the {pct(beta_pl['median'])} seen in the placebo window.</li>
<li><i>Web and Reddit.</i> The RIA outlet ukraina.ru and the pro-Russian, war and political Reddit communities show no drop; war communities rose with strike news. No war-specific reduction is found on any platform.</li></ul>
<p>Of {len(io_ids)} IO series, {verd.get('Large drop ruled out', 0)} rule out a drop larger than 20% after Vladimir, {verd.get('Inconclusive', 0)} are inconclusive, {verd.get('Increase detected', 0)} increased and {verd.get('Drop detected', 0)} show a drop that survives false-discovery control and the same-weekday check: {drop_txt}. In the analysis of competing hypotheses, a narrow dependency of specific automated pipelines carries no weighted inconsistency, whereas a broad collapse of IO output is contradicted by every platform-level measurement.</p>

<figure><p class="flab">Figure 2</p><p class="ftit">Bayesian Posterior Change in Output per Platform Group After the Vladimir Strike</p>
{fig_groups(by)}
<p class="note"><i>Note.</i> Posterior median (value at right) and 90% credible interval, including the common news-shock variance estimated before the strikes. Red: credible drop. Green: drops larger than 20% ruled out. Grey: inconclusive. The shaded band marks drops beyond the 20% smallest effect of interest.</p></figure>

<h3>2.3 Infrastructure of Attributed Influence Operations</h3>
<div class="tbl"><p class="flab">Table 1</p><p class="ftit">Hosting of Domains Attributed to Russian Influence Operations, Public DNS, 13 to 14 October 2026</p>
<table><thead><tr><th>Operation</th><th>Attributed by</th><th style="text-align:right">Domains</th><th style="text-align:right">Resolving</th><th style="text-align:right">Answering</th><th>Main hosting networks</th><th style="text-align:right">On Yandex</th></tr></thead>
<tbody>{arows}</tbody></table>
<p class="note"><i>Note.</i> Domains from VIGINUM's Storm-1516 report (appendix 6.2) and the EEAS 4th FIMI threat report. Hosting networks from RIPE Stat for the A records returned by 1.1.1.1, 8.8.8.8 and 9.9.9.9; "answering" means an HTTP 200 response. "On Yandex" counts domains hosted in a Yandex network or using Yandex name servers or mail. The seven outlets on Yandex 360 mail are {", ".join(ymail)}.</p></div>
<p>Most Storm-1516 domains are dormant or parked, so their output cannot be measured hourly; those that answer sit mainly behind Cloudflare and Amazon. The measurable outlets of these operations are covered in Section 2.2.</p>

<h2>3. Data Verification</h2>
<p>{ver_txt} Arctic Shift aggregate buckets are labelled two hours early and were corrected and checked against the raw comment stream; Reddit group totals are reported only when every member community is observed. Pravda sitemap and WordPress timestamps were checked against article publication times.</p>

<h2>4. Limitations</h2>
<ul>
<li>X, VK and closed bot infrastructure are not observable with open data, so small dedicated networks could go undetected. The median single-series minimum detectable drop is about 26% over 24 h, and 10 to 20% for pooled groups.</li>
<li>The strikes were major news and inflated war-related activity. Theme contrasts and controls mitigate this but cannot remove it.</li>
<li>The Pravda attribution rests on timing. Its sites sit behind Cloudflare, so the dependent component is not directly observable, and Sasovo, which cut reachable capacity by {off_sas * 100:.0f}%, produced no time-locked dip.</li>
<li>DNS was measured after the strikes; an outlet that moved off Yandex earlier would appear independent. Outlets blocked by the national resolver (RT, Sputnik, RIA) were mapped through public DNS but not crawled. Recovery estimates are right-censored at 13 October, 12:00 UTC.</li></ul>

<h2>References</h2>
<div class="refs">
<p>Benjamini, Y., &amp; Hochberg, Y. (1995). Controlling the false discovery rate. <i>Journal of the Royal Statistical Society B, 57</i>(1), 289-300.</p>
<p>Brodersen, K. H., Gallusser, F., Koehler, J., Remy, N., &amp; Scott, S. L. (2015). Inferring causal impact using Bayesian structural time-series models. <i>Annals of Applied Statistics, 9</i>(1), 247-274.</p>
<p>Del Moral, P., Doucet, A., &amp; Jasra, A. (2006). Sequential Monte Carlo samplers. <i>Journal of the Royal Statistical Society B, 68</i>(3), 411-436.</p>
<p>DerSimonian, R., &amp; Laird, N. (1986). Meta-analysis in clinical trials. <i>Controlled Clinical Trials, 7</i>(3), 177-188.</p>
<p>European External Action Service. (2026). <i>4th EEAS report on foreign information manipulation and interference threats.</i> EEAS.</p>
<p>Gelman, A., &amp; Rubin, D. B. (1992). Inference from iterative simulation using multiple sequences. <i>Statistical Science, 7</i>(4), 457-472.</p>
<p>Heuer, R. J. (1999). <i>Psychology of intelligence analysis.</i> Center for the Study of Intelligence.</p>
<p>Lakens, D. (2017). Equivalence tests. <i>Social Psychological and Personality Science, 8</i>(4), 355-362.</p>
<p>Newey, W. K., &amp; West, K. D. (1987). A simple, positive semi-definite, heteroskedasticity and autocorrelation consistent covariance matrix. <i>Econometrica, 55</i>(3), 703-708.</p>
<p>Office of the Director of National Intelligence. (2015). <i>Intelligence Community Directive 203: Analytic standards.</i></p>
<p>VIGINUM. (2025). <i>Storm-1516: Technical and tactical analysis of a Russian information manipulation set.</i> SGDSN.</p>
<p><i>Data sources</i> (all graded and linked in the dashboard): Yandex Cloud status incidents and API; Yandex and Vladimir governor Telegram posts; IODA; RIPE Stat; NASA FIRMS; Cloudflare Radar and NetBlocks; Detector404 and Sboy.rf; Wikimedia pageviews; Pravda, ukraina.ru, zona.media and theins.ru sitemaps; WordPress REST APIs; Telegram previews; Arctic Shift. Code and dashboard: OSINT_YandexOutage repository.</p>
</div>
</section>
</body></html>"""
    assert chr(0x2014) not in html, "em dash in report"
    (OUT / "report.html").write_text(html)
    pdf = OUT / "REPORT.pdf"
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--virtual-time-budget=8000",
                    f"--print-to-pdf={pdf}", (OUT / "report.html").as_uri()], check=True, capture_output=True, timeout=180)
    from pypdf import PdfReader, PdfWriter
    r = PdfReader(str(pdf))
    w = PdfWriter(clone_from=r)
    w.add_metadata({"/Title": TITLE, "/Author": "Stijn Van Severen",
                    "/Subject": "Open-source intelligence assessment of the October 2026 Yandex data-center strikes"})
    with open(pdf, "wb") as f:
        w.write(f)
    shutil.copy(pdf, ROOT / "REPORT.pdf")
    shutil.copy(pdf, ROOT / "docs" / "REPORT.pdf")
    print("pages:", len(r.pages), pdf)


if __name__ == "__main__":
    build()
