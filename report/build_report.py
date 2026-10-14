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

    fig, ax = plt.subplots(2, 1, figsize=(6.7, 3.55), sharex=True, gridspec_kw={"height_ratios": [1, 1.2], "hspace": 0.62})
    a = ax[0]
    a.fill_between(s1.index, s1.q05 * 100, s1.q95 * 100, color=BLUE, alpha=0.13, lw=0, step="post", label="Expected outage, 90% band")
    a.plot(s1.index, s1["mean"] * 100, color=BLUE, lw=1.5, drawstyle="steps-post", label="Expected outage, mean (Stage 1)")
    a.plot(x[sel], io_[sel], color=ORANGE, lw=1.2, label="Measured outage (IODA active probing)")
    a.set_ylim(0, 100); a.set_ylabel("Yandex Cloud offline (%)")
    a.set_title("A   Expected versus measured Yandex Cloud outage", color=INK)
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
           f"Pravda {pct(pe['dip_ratio'] - 1)} for {pe['dip_hours']:.0f} h\n(p = {fp(pe['p_scan'])})",
           fontsize=6.4, color=RED, va="top", bbox=dict(facecolor="white", edgecolor="none", alpha=0.9, pad=1.5))
    for axx in ax:
        for k, c in (("SAS", RED), ("KAL", INK3), ("VLA", RED)):
            axx.axvline(on[k], color=c, lw=0.9, alpha=0.8)
        axx.grid(axis="y", color=GRID, lw=0.6)
    for k, lab in (("SAS", "Sasovo"), ("KAL", "Kaluga"), ("VLA", "Vladimir")):
        ax[0].text(on[k] + pd.Timedelta(minutes=40), 92, f"{lab} {on[k]:%d Oct %H:%M} UTC", fontsize=6.3, color=INK2)
    b.xaxis.set_major_locator(mdates.DayLocator()); b.xaxis.set_major_formatter(mdates.DateFormatter("%d Oct"))
    return svg(fig)


def fig_groups(by):
    """Figure 2: Bayesian posterior change per platform group, Vladimir 6 h and 24 h, with values."""
    groups = sorted(by["groups"], key=lambda g: (g.startswith("Control"), g))
    fig, ax = plt.subplots(1, 2, figsize=(6.7, 2.9), sharey=True, gridspec_kw={"wspace": 0.2})
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


TITLE = "Yandex Cloud Outages as a Natural Experiment on Russian Influence Operations: Bayesian Outage Modelling with Change-Point Attribution"


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
    drop_sentence = (f"{len(dn)} show a drop that survives false-discovery control and the same-weekday check: {drop_txt}." if dn
                     else "no individual series shows a drop that survives false-discovery control and the same-weekday check; the Pravda effect is visible at the group level and in the 10-minute timing analysis.")
    hits = [(k, ev) for k in tim for ev, e in tim[k]["events"].items() if e.get("q_locked", 1) < 0.05]
    other_hits = [(k, ev) for k, ev in hits if not (k.startswith("pravda") and ev == "VLA")]
    nice = {"SAS": "Sasovo", "KAL": "Kaluga", "VLA": "Vladimir", "SEP27": "27 September"}
    lang = {"sr": "Serbian", "ar": "Arabic", "en": "English", "de": "German", "fr": "French", "es": "Spanish"}
    oh = "; ".join(f"the {lang.get(k.split('.')[-1], k)} edition after {nice[ev]}" for k, ev in other_hits if k.startswith("pravda.lang."))
    sep_hit = any(ev == "SEP27" for _, ev in hits)
    locked_note = ((f"Among {sum(len(tim[k]['events']) for k in tim)} onset-locked tests, the only other significant results are single Pravda editions ({oh}); "
                    "the network total shows no onset-locked dip after Sasovo or Kaluga, ") if oh else "No other onset-locked test is significant, ") + \
                  ("and the 27 September control period shows none." if not sep_hit else "although the 27 September control period also shows a hit.")
    stv = tim.get("tg.grp.pro_kremlin_state.all", {}).get("events", {}).get("VLA", {})
    state_note = ""
    if stv and stv.get("p_scan", 1) < 0.05 and (stv.get("naive_ratio") or 0) > 0.85:
        state_note = (f" A {stv['dip_hours']:.0f} h dip that the regression counterfactual flags in state channels falls on an ordinary"
                      f" Sunday: against the same hours on the previous three Sundays, output was {stv['naive_ratio'] * 100:.0f}% of normal.")
    n_tg = sum(1 for k in D["meta"] if k.startswith("tg.ch.") and not str(D["meta"][k].get("role", "")).startswith("control"))
    n_tg_ctl = sum(1 for k in D["meta"] if k.startswith("tg.ch.") and str(D["meta"][k].get("role", "")).startswith("control"))
    n_rd = len({k.split(".")[1] for k in D["meta"] if k.startswith("rd.") and k.endswith(".comments.all") and not k.startswith("rd.grp.")})
    n_tot = sum(1 for k in S if not D["meta"][k].get("hidden"))
    ymail = [d["domain"] for d in D["infra"] if d["yandex_mail"] and d["role"] != "positive_control"]
    # language editions of the Pravda network that dip early and significantly
    langs = {"en": "English", "de": "German", "fr": "French", "es": "Spanish", "ar": "Arabic", "sr": "Serbian"}
    early = [(langs[k], tim[f"pravda.lang.{k}"]["events"]["VLA"]) for k in langs if f"pravda.lang.{k}" in tim]
    early = [(n, e) for n, e in early if e["p_scan"] < 0.05 and 0 <= e["offset_min"] <= 60]
    early_txt = (f"The {', '.join(n for n, _ in early[:-1])} and {early[-1][0]} editions dip {min(e['offset_min'] for _, e in early):.0f} min after onset."
                 if len(early) >= 2 else "")
    ver = D["ver"]; nver = sum(x["n"] for x in ver)
    quality = json.loads((PROC / "data_quality.json").read_text())
    q_bad = {k: v["status"] for k, v in quality.items() if v["status"] != "ok"}
    # half-up rounding, as in the dashboard
    sas_err, vla_err = (int(abs(v["S1"]["onset_error_min_vs_S2"][k]) + 0.5) for k in ("SAS", "VLA"))
    iu = pd.read_parquet(PROC / "ioda_cloud_unreachable_hourly.parquet")["ioda_unreachable_frac"]
    on = {k: pd.Timestamp(t) for k, t in an["onsets"].items()}
    off_now = float(iu.dropna().iloc[-12:].mean())
    off_sas = float(iu[(iu.index >= on["SAS"] + pd.Timedelta(hours=3)) & (iu.index < on["VLA"] - pd.Timedelta(hours=1))].mean())
    n_ch_coll = len(set(pd.read_parquet(PROC / "telegram_posts.parquet").handle))

    # ------------------------------------------------------------ numbered references, in order of first citation
    L = lambda url, text=None: f'<a href="{url}">{text or url.replace("https://", "")}</a>'
    DOI = lambda d: L(f"https://doi.org/{d}", f"https://doi.org/{d}")
    REF = {
        "ycs": f"Yandex Cloud. (2026). <i>Incidents 2092 and 2136</i> [Status page]. {L('https://status.yandex.cloud/ru/incidents/2092')}; {L('https://status.yandex.cloud/ru/incidents/2136')}; incident API {L('https://status.yandex.cloud/api/incidents')}",
        "ytg": f"Yandex. (2026, October 8 to 13). <i>Posts 5900, 5901, 5903 and 5905</i> [Telegram]. {L('https://t.me/yandex/5900')}; {L('https://t.me/yandex/5901')}; {L('https://t.me/yandex/5903')}; {L('https://t.me/yandex/5905')}",
        "gov": f"Avdeev, A. (2026, October 11). <i>Post 10997</i> [Telegram, Governor of Vladimir Oblast]. {L('https://t.me/avdeev_o_vazhnom/10997')}",
        "mt8": f"The Moscow Times. (2026, October 8). <i>Ukrainian drones hit Yandex data center, industrial facilities across Russia.</i> {L('https://www.themoscowtimes.com/2026/10/08/ukrainian-drones-hit-yandex-data-center-after-wave-of-russian-attacks-a93915', 'themoscowtimes.com')}",
        "cnbc": f"CNBC. (2026, October 8). <i>Russia's Yandex halts operations at data center after drone strike.</i> {L('https://www.cnbc.com/2026/10/08/russia-yandex-ukraine-drone-strike-data-center.html', 'cnbc.com')}",
        "mt9": f"The Moscow Times. (2026, October 9). <i>Ukraine drones hit second Yandex data center in two days.</i> {L('https://www.themoscowtimes.com/2026/10/09/ukraine-drones-hit-second-yandex-data-center-in-two-days-a93927', 'themoscowtimes.com')}",
        "aj": f"Al Jazeera. (2026, October 11). <i>Russia's Yandex says data centre in Vladimir shut down after drone attack.</i> {L('https://www.aljazeera.com/news/2026/10/11/russias-yandex-says-data-centre-in-vladimir-shut-down-after-drone-attack', 'aljazeera.com')}",
        "mt11": f"The Moscow Times. (2026, October 11). <i>Russia's Yandex says data center in Vladimir shut down after drone attack.</i> {L('https://www.themoscowtimes.com/2026/10/11/russias-yandex-says-data-center-in-vladimir-shut-down-after-drone-attack-a93942', 'themoscowtimes.com')}",
        "mt12": f"Benson, B. (2026, October 12). Ukraine's strikes on Yandex data centers, explained. <i>The Moscow Times.</i> {L('https://www.themoscowtimes.com/2026/10/12/ukraines-strikes-on-yandex-data-centers-explained-a93953', 'themoscowtimes.com')}",
        "hns": f"Markovic, S. (2026, October 13). Ukrainian drones hit Yandex data centers, sparking claims that Russian troll farms went quiet. <i>Help Net Security.</i> {L('https://www.helpnetsecurity.com/2026/10/13/ukraine-drone-strikes-yandex-data-centers/', 'helpnetsecurity.com')}",
        "statcounter": f"StatCounter. (2026). <i>Search engine market share in the Russian Federation</i> [Data set]. {L('https://gs.statcounter.com/search-engine-market-share/all/russian-federation', 'gs.statcounter.com')}",
        "reuters": f"Reuters. (2026, October 8). <i>Russia's Yandex says unclear whether data centre can be restored after drone attack.</i> {L('https://www.reuters.com/world/europe/russias-yandex-says-unclear-whether-data-centre-can-be-restored-after-drone-2026-10-08/', 'reuters.com')}",
        "firms": f"NASA. (2026). <i>Fire Information for Resource Management System (FIRMS), VIIRS active fire detections.</i> {L('https://firms.modaps.eosdis.nasa.gov/')}",
        "cfr": f"Cloudflare Radar. (2026, October 7 to 11). <i>Posts on Yandex Cloud traffic</i> [Bluesky]. {L('https://bsky.app/profile/radar.cloudflare.com')}",
        "nb": f"NetBlocks. (2026, October 8 and 11). <i>Posts on Yandex connectivity</i> [Bluesky]. {L('https://bsky.app/profile/netblocks.org')}",
        "trk": f"Detector404 and Sboy.rf. (2026). <i>User complaint alerts</i> [Telegram]. {L('https://t.me/s/ru_downdetector_su')}",
        "ioda": f"Internet Outage Detection and Analysis (IODA), Georgia Institute of Technology. (2026). <i>Raw signals API, AS200350 and controls.</i> {L('https://ioda.inetintel.cc.gatech.edu/asn/200350')}",
        "dainotti": f"Dainotti, A., Squarcella, C., Aben, E., Claffy, K. C., Chiesa, M., Russo, M., &amp; Pescapé, A. (2011). Analysis of country-wide internet outages caused by censorship. In <i>Proceedings of the 2011 ACM SIGCOMM Internet Measurement Conference</i> (pp. 1-18). {DOI('10.1145/2068816.2068818')}",
        "quan": f"Quan, L., Heidemann, J., &amp; Pradkin, Y. (2013). Trinocular: Understanding internet reliability through adaptive probing. In <i>Proceedings of the ACM SIGCOMM 2013 Conference</i> (pp. 255-266). {DOI('10.1145/2486001.2486017')}",
        "ripe": f"RIPE NCC. (2026). <i>RIPE Stat: BGP update activity and network information.</i> {L('https://stat.ripe.net/')}",
        "delmoral": f"Del Moral, P., Doucet, A., &amp; Jasra, A. (2006). Sequential Monte Carlo samplers. <i>Journal of the Royal Statistical Society: Series B, 68</i>(3), 411-436. {DOI('10.1111/j.1467-9868.2006.00553.x')}",
        "heuer": f"Heuer, R. J. (1999). <i>Psychology of intelligence analysis.</i> Center for the Study of Intelligence. {L('https://www.cia.gov/resources/csi/books-monographs/psychology-of-intelligence-analysis-2/', 'cia.gov')}",
        "eeas": f"European External Action Service. (2026). <i>4th EEAS report on foreign information manipulation and interference threats.</i> {L('https://www.eeas.europa.eu/sites/default/files/2026/documents/EEAS%204th%20Threat%20Report_web%20version_1.pdf', 'eeas.europa.eu')}",
        "viginum_pk": f"VIGINUM. (2024). <i>Portal Kombat: A structured and coordinated pro-Russian propaganda network.</i> SGDSN. {L('https://www.sgdsn.gouv.fr/files/files/20240212_NP_SGDSN_VIGINUM_PORTAL-KOMBAT-NETWORK_ENG_VF.pdf', 'sgdsn.gouv.fr')}",
        "pravda": f"Pravda network. (2026). <i>Public XML sitemaps of news-pravda.com and its subdomains.</i> {L('https://news-pravda.com/sitemap.xml')}",
        "tg": f"Telegram. (2026). <i>Public channel previews</i> ({n_ch_coll} channels, t.me/s/&lt;channel&gt;). {L('https://t.me/s/rybar', 't.me/s')}",
        "wp": f"African Initiative, RRN and R-FBI. (2026). <i>WordPress REST API post feeds.</i> {L('https://afrinz.ru/wp-json/wp/v2/posts', 'afrinz.ru/wp-json')}; {L('https://rrn.com.tr/wp-json/wp/v2/posts', 'rrn.com.tr/wp-json')}; {L('https://fondfbr.ru/wp-json/wp/v2/posts', 'fondfbr.ru/wp-json')}",
        "web": f"ukraina.ru, zona.media and The Insider. (2026). <i>Article sitemaps.</i> {L('https://ukraina.ru/sitemap_article_index.xml', 'ukraina.ru')}; {L('https://zona.media/sitemap/2026/9/item.xml', 'zona.media')}; {L('https://theins.ru/sitemap-news-ru-1.xml', 'theins.ru')}",
        "arctic": f"Arctic Shift. (2026). <i>Reddit archive API.</i> {L('https://arctic-shift.photon-reddit.com/')}",
        "wiki": f"Wikimedia Foundation. (2026). <i>Pageviews API, hourly aggregates by access method and agent.</i> {L('https://wikimedia.org/api/rest_v1/')}",
        "brodersen": f"Brodersen, K. H., Gallusser, F., Koehler, J., Remy, N., &amp; Scott, S. L. (2015). Inferring causal impact using Bayesian structural time-series models. <i>Annals of Applied Statistics, 9</i>(1), 247-274. {DOI('10.1214/14-AOAS788')}",
        "abadie": f"Abadie, A., Diamond, A., &amp; Hainmueller, J. (2015). Comparative politics and the synthetic control method. <i>American Journal of Political Science, 59</i>(2), 495-510. {DOI('10.1111/ajps.12116')}",
        "dersimonian": f"DerSimonian, R., &amp; Laird, N. (1986). Meta-analysis in clinical trials. <i>Controlled Clinical Trials, 7</i>(3), 177-188. {DOI('10.1016/0197-2456(86)90046-2')}",
        "gelman": f"Gelman, A., &amp; Rubin, D. B. (1992). Inference from iterative simulation using multiple sequences. <i>Statistical Science, 7</i>(4), 457-472. {DOI('10.1214/ss/1177011136')}",
        "newey": f"Newey, W. K., &amp; West, K. D. (1987). A simple, positive semi-definite, heteroskedasticity and autocorrelation consistent covariance matrix. <i>Econometrica, 55</i>(3), 703-708. {DOI('10.2307/1913610')}",
        "bh": f"Benjamini, Y., &amp; Hochberg, Y. (1995). Controlling the false discovery rate: A practical and powerful approach to multiple testing. <i>Journal of the Royal Statistical Society: Series B, 57</i>(1), 289-300. {DOI('10.1111/j.2517-6161.1995.tb02031.x')}",
        "disarm": f"DISARM Foundation. (2026). <i>DISARM Red framework</i> (Version 1.6.1) [Data set]. {L('https://github.com/DISARMFoundation/DISARMframeworks', 'github.com/DISARMFoundation/DISARMframeworks')}",
        "stix": f"OASIS. (2021). <i>STIX Version 2.1</i> (OASIS Standard). {L('https://docs.oasis-open.org/cti/stix/v2.1/os/stix-v2.1-os.html', 'docs.oasis-open.org/cti/stix/v2.1')}",
        "lakens": f"Lakens, D. (2017). Equivalence tests: A practical primer for t tests, correlations, and meta-analyses. <i>Social Psychological and Personality Science, 8</i>(4), 355-362. {DOI('10.1177/1948550617697177')}",
    }
    order = []

    def c(*keys):
        out = []
        for k in keys:
            if k not in order:
                order.append(k)
            n = order.index(k) + 1
            out.append(f'<a class="cite" href="#ref-{n}">{n}</a>')
        return "[" + ", ".join(out) + "]"

    X = lambda href, text: f'<a class="int" href="#{href}">{text}</a>'

    # ------------------------------------------------------------ title page and bottom line
    band = """<svg class="band" viewBox="0 0 800 1130" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">
      <defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#0b1f45"/><stop offset=".55" stop-color="#143e86"/><stop offset="1" stop-color="#1f6fc9"/></linearGradient>
      <linearGradient id="w1" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#1baf7a" stop-opacity=".5"/><stop offset="1" stop-color="#2a78d6" stop-opacity=".25"/></linearGradient>
      <linearGradient id="w2" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#eb6834" stop-opacity=".32"/><stop offset="1" stop-color="#e87ba4" stop-opacity=".14"/></linearGradient></defs>
      <rect width="800" height="1130" fill="url(#bg)"/>
      <path d="M0 880 C 160 820, 300 950, 470 880 S 700 780, 800 830 L800 1130 L0 1130Z" fill="url(#w1)"/>
      <path d="M0 960 C 200 910, 350 1030, 540 960 S 720 890, 800 920 L800 1130 L0 1130Z" fill="url(#w2)"/>
      <path d="M0 1040 C 220 990, 420 1090, 620 1035 S 760 1000, 800 1015 L800 1130 L0 1130Z" fill="rgba(255,255,255,.07)"/>
      <path d="M0 850 C 180 790, 330 910, 520 850 S 720 760, 800 800" stroke="rgba(255,255,255,.32)" stroke-width="1.2" fill="none"/>
    </svg>"""
    abstract = (f"Between 7 and 11 October 2026, Ukrainian forces carried out drone strikes on Yandex data centers in Sasovo, Kaluga and Vladimir, causing a large and sustained outage of Yandex Cloud. "
                f"This study systematically investigates whether the outages reduced the output of Russian information operations (IO). An expected-outage function "
                f"estimated from graded published reports reconstructs the measured outage onsets to within {sas_err} and {vla_err} minutes. The output of {n_tot} series, "
                f"covering the pro-Kremlin amplification network Portal Kombat (the Pravda network), {n_tg} Telegram channels of state media, military bloggers and "
                f"foreign-audience outlets (with {n_tg_ctl} control channels), the websites of Russian state media and of influence operations reported by the European External "
                f"Action Service, and {n_rd} Reddit communities, is compared with out-of-sample seasonal counterfactuals using placebo windows, a Bayesian hierarchical model "
                f"and 10-minute change-point timing; the actors are additionally mapped to DISARM techniques in a STIX 2.1 bundle. Only Portal Kombat shows a reduction "
                f"time-locked to an outage: its output fell to {pr['dip_ratio'] * 100:.0f}% of expected for {pr['dip_hours']:.0f} hours, starting {pr['offset_min']:.0f} minutes "
                f"after the Vladimir outage, consistent with a stalled republishing pipeline. No other platform group shows a credible drop, while Russian Wikipedia traffic, "
                f"a positive control for user-facing disruption, fell as expected. The strikes disrupted Yandex substantially but did not measurably silence Russian "
                f"information operations; the one observed effect was narrow and transient.")

    # ------------------------------------------------------------ body, in document order
    sec1 = f"""<h2 id="s1">1. Introduction</h2>
<p>Between 7 and 11 October 2026, Ukrainian forces carried out drone strikes on three Yandex data centers: in Sasovo, Ryazan Oblast, on the night of 7 to 8 October {c('mt8', 'cnbc')}, in Kaluga on 9 October {c('mt9')}, and near Vladimir on 11 October {c('aj', 'mt11')}. President Zelensky described the attacks as a response to Russian strikes on Ukrainian data centers {c('aj', 'mt12')}. Yandex handles about 70% of web searches in Russia {c('statcounter')}, and its cloud platform serves more than 64,000 customers, including some of the country's largest companies {c('mt12')}. The company reported that operations in Sasovo were completely halted, that part of the Kaluga infrastructure was disabled and that the Vladimir data center was shut down, with Yandex Cloud running in emergency mode {c('ycs', 'ytg', 'hns')}. It stated that it was unclear whether the Sasovo site could be restored, a site reported to house two of its three AI supercomputers {c('reuters', 'hns')}.</p>
<p>Russian information operations (IO) depend on online infrastructure at every stage: content is produced and coordinated by editorial teams and channel operators, republished by automated networks such as the Pravda network (Portal Kombat), and distributed through websites, Telegram and social media. If a meaningful part of that chain ran on Yandex, the strikes should have reduced IO output, either broadly or in specific automated pipelines. Whether they did is relevant for assessing the information effects of strikes on civilian-military digital infrastructure, and for understanding how resilient the Russian information ecosystem is to the loss of a major domestic cloud provider.</p>
<p>This study investigates that question as a natural experiment with three treated events and one internal control period, an unexplained Yandex Cloud reachability dip on 27 September without any strike. Each link of the causal chain, from strike to capacity loss, dependent services, automated pipelines and finally social-media and web output, is measured separately, so that a break in the chain becomes visible rather than being absorbed into a single aggregate. The approach combines an outage model reconstructed from graded public reports with independent network measurements, and tests IO output across platforms, actors and topics against seasonal counterfactuals and placebo periods. {X('s2', 'Section 2')} describes the methodology, {X('s3', 'Section 3')} reports the results, and {X('s4', 'Section 4')} concludes.</p>
"""
    sec2 = f"""<h2 id="s2">2. Methodology</h2>
<h3 id="s21">2.1 Expected Outage Function</h3>
<p>The timing and severity of the outages are first reconstructed from published information alone. Each strike contributes a capacity-weighted damage curve whose timing, onset lag, failure ramp, damage and recovery follow from graded reports: operator status incidents, statements by Yandex and the regional governor, satellite fire detections, third-party telemetry reports and complaint alerts {c('ycs', 'ytg', 'gov', 'firms', 'cfr', 'nb', 'trk')}. Each source is graded with the NATO Admiralty system, the grades are converted into probabilities, and derivative reports are discounted against their originals before being pooled into each strike's credibility. The model is estimated in three nested Bayesian stages with adaptive-tempering sequential Monte Carlo {c('delmoral')} on a 10-minute grid: attack reports only (S0), all published information (S1), and fused with active-probing telemetry from IODA, which measures the share of Yandex Cloud address blocks that still respond (S2) {c('ioda', 'dainotti', 'quan')}. BGP visibility from RIPE Stat {c('ripe')} distinguishes a routing withdrawal from a loss of reachable hosts. Stage 1 is validated out of sample against the measurement ({X('fig1', 'Figure 1A')}), and Stage 2 provides the outage onsets used in all later tests.</p>
<h3 id="s22">2.2 Actors and Outcome Data</h3>
<p>The actor set starts from public attributions: the Pravda network (Portal Kombat) {c('viginum_pk')} and the African Initiative, RRN and R-FBI outlets {c('eeas')}. It is extended with Russian state broadcasters, the Ministry of Defence broadcaster Zvezda, the Channel One Kremlin pool, the Kremlin-linked "War on Fakes" channel, foreign-audience outlets (InfoDefense, Strategic Culture, Sputnik Africa, DD Geopolitics), pro-Kremlin tabloids and the most prominent military bloggers. Output is measured as the number of publications per hour and per 10 minutes from 1 September to 13 October 2026, using Pravda sitemaps {c('pravda')}, Telegram channel previews {c('tg')}, WordPress feeds and sitemaps {c('wp', 'web')} and Reddit {c('arctic')}. Posts are labelled as war-related or other with a multilingual keyword lexicon, so that a dependency specific to war propaganda would show as a larger drop in war content. Independent Russian, Ukrainian, business and non-political sources serve as controls for news-driven fluctuations. Russian Wikipedia pageviews {c('wiki')} are a positive control for user-facing disruption: Yandex Search refers a substantial share of visits while Wikimedia's own infrastructure is unaffected, so a dip there shows that the outage reached ordinary users. Public DNS mail records identify outlets that run their mail on Yandex 360, which form a separate exposure stratum. The actor sets and their behaviours were also mapped to techniques of the DISARM Red framework (v1.6.1) and exported with the findings as a STIX 2.1 bundle, which places the measured actors within the wider landscape of information-operation tactics {c('disarm', 'stix')}.</p>
<h3 id="s23">2.3 Statistical Inference</h3>
<p>Each series receives an out-of-sample seasonal counterfactual: a regression on hour of day, day of week, their weekend interaction and trend, fitted on the pre-strike baseline only {c('brodersen')}. Deviations after each strike are summarised over windows of 6 and 24 hours and compared with every window of the same length in the baseline (placebo-in-time inference {c('abadie')}), and with the same hours on the same weekday in the three preceding weeks, which guards against weekly patterns the regression misses.</p>
<p>A Bayesian hierarchical model pools {nmem} member series into platform groups {c('dersimonian')}. For member <i>i</i> in group <i>g</i>, the observed mean log deviation y<sub>i</sub> in a window is modelled as y<sub>i</sub> ~ N(θ<sub>i</sub>, s<sub>i</sub><sup>2</sup>) with θ<sub>i</sub> = α<sub>g</sub> + β·Z<sub>i</sub> + ε<sub>i</sub> and ε<sub>i</sub> ~ N(0, τ<sup>2</sup>), where s<sub>i</sub> is the member's placebo-calibrated standard error, α<sub>g</sub> the platform-group effect, Z<sub>i</sub> marks outlets on Yandex 360 mail and β their extra effect; α<sub>g</sub> and β have N(0, 0.5<sup>2</sup>) priors on the log scale and τ a half-normal(0.25) prior. The posterior is sampled by Gibbs sampling (four chains of 4,000 iterations after 1,000 burn-in), and convergence is checked with split R-hat {c('gelman')}. Because members of a platform share news shocks that member-level errors do not capture, each group effect is reported with an added common-shock variance estimated from baseline windows, so that a group-level drop is not overstated when all sources move together. The model is run for all posts, for war-related posts, for other posts and for their difference. In parallel, a 10-minute change-point model dates the start, end and depth of the most likely dip in each key stream: for every candidate interval of 30 minutes to 20 hours it compares a quasi-Poisson model in which output falls to a fraction ρ of its expectation with the no-dip model, using an overdispersion factor estimated from baseline residuals. An onset-locked version of the scan only considers dips that start between 30 minutes before and 6 hours after the measured outage onset; both scans are calibrated with 400 placebo origins in the baseline, false-discovery control is applied across all streams and events, and a backlog test measures whether lost output was published later. Dose-response regressions on the expected outage function use HAC standard errors {c('newey')}; false-discovery control {c('bh')}, a 20% equivalence bound {c('lakens')} and an analysis of competing hypotheses {c('heuer')} complete the inference. A drop is credible only if the posterior probability of a drop larger than 10% exceeds 90%, the group placebo p is below 0.05 and the same-weekday check agrees; a dip is time-locked only if the onset-locked test is significant after false-discovery control (q below 0.05), because an outage cannot explain a decline that began before it.</p>

"""
    sec3 = f"""<h2 id="s3">3. Results</h2>
<h3 id="s31">3.1 Infrastructure and Dependent Services</h3>
<p>Yandex Cloud reachability fell from {dt['SAS']['onset_utc'][1][11:16]} UTC after the Sasovo strike (strike {dt['SAS']['strike_utc'][1][11:16]}, full loss {dt['SAS']['full_loss_utc'][1][11:16]}) and from {dt['VLA']['onset_utc'][1][11:16]} UTC after the Vladimir strike (strike {dt['VLA']['strike_utc'][1][11:16]}) ({X('fig1', 'Figure 1A')}). The expected outage function built from published reports alone reproduces these onsets to within {sas_err} and {vla_err} minutes. BGP visibility stayed intact {c('ripe')}, indicating a data-plane loss rather than a routing withdrawal. Hosting, access and platform controls (Selectel, Timeweb, Beget, VK, Rostelecom, MTS, MegaFon, Beeline and Yandex Cloud Kazakhstan) show no matching steps. Russian Wikipedia user traffic fell {pct(W('wiki.ru.wikipedia.user'))} in the 24 h after Vladimir, and complaint alerts for Yandex Pay, Go and KinoPoisk surged from 00:47 UTC {c('trk')}: the outage reached consumers.</p>
"""
    fig1 = f"""<figure id="fig1"><p class="flab">Figure 1</p><p class="ftit">Expected and Measured Yandex Cloud Outage and Pravda Network Output, 7 to 12 October 2026</p>
{fig_key(D)}
<p class="note"><i>Note.</i> (A) The expected outage function estimated from published reports only (statements, status pages, satellite fire detections, complaint alerts) tracks the independently measured outage {c('ioda')}, with {v['S1']['predictive_coverage90'] * 100:.0f}% coverage of the 90% predictive band. (B) Pravda network output {c('pravda')} collapses within the hour after the Vladimir outage and recovers with a partial catch-up; its Telegram input does not dip. No comparable dip follows Sasovo, where a decline started 7 h before the strike. Shading marks the most likely dip interval; vertical lines mark outage onsets (UTC).</p></figure>
"""
    sec32 = f"""<h3 id="s32">3.2 Where an Effect on Information Operations Is and Is Not Seen</h3>
<ul>
<li><span class="hl">Pravda network (Portal Kombat).</span> The only credible and time-locked drop: output fell to {pr['dip_ratio'] * 100:.0f}% of expected for {pr['dip_hours']:.1f} h, starting {pr['offset_min']:.0f} min after the Vladimir onset (onset-locked p = {fp(pr['p_locked'])}, q = {pr['q_locked']:.3f}; first 6 h {pct(g6['Pravda network (automated web)']['median'])}, P(drop &gt; 10%) = {g6['Pravda network (automated web)']['p_drop10'] * 100:.0f}%; {X('fig1', 'Figure 1B')}, {X('fig2', 'Figure 2')}). {early_txt} {locked_note}</li>
<li><i>Telegram.</i> State media, military bloggers, tabloids and foreign-audience channels show no credible drop.{state_note} Non-war posts of state ({pct(W('tg.grp.pro_kremlin_state.other'))}) and tabloid channels ({pct(W('tg.grp.pro_kremlin_tabloid.other'))}) fell while their war posts rose ({pct(W('tg.grp.pro_kremlin_state.war'))} and {pct(W('tg.grp.pro_kremlin_tabloid.war'))}); this is topic substitution toward strike news, not lost capacity.</li>
<li><i>EEAS-named outlets.</i> African Initiative and RRN websites ({pct(g24['Web: EEAS-named IMS outlets']['median'])} over 24 h) and African Initiative's Telegram channels ({pct(g24['Telegram: EEAS-named IMS']['median'])}) show no credible drop and no time-locked dip.</li>
<li><i>Yandex 360 mail.</i> Outlets on Yandex mail show an extra effect of {pct(beta['median'])} (90% {pct(beta['ci90'][0])} to {pct(beta['ci90'][1])}), indistinguishable from the {pct(beta_pl['median'])} seen in the control period.</li>
<li><i>Web and Reddit.</i> The RIA outlet ukraina.ru and the pro-Russian, war and political Reddit communities show no drop; war communities rose with strike news. No war-specific reduction is found on any platform.</li></ul>
<p>Of {len(io_ids)} IO series, {verd.get('Large drop ruled out', 0)} rule out a drop larger than 20% after Vladimir, {verd.get('Inconclusive', 0)} are inconclusive, {verd.get('Increase detected', 0)} increased, and {drop_sentence} In the analysis of competing hypotheses, a narrow dependency of specific automated pipelines carries no weighted inconsistency, whereas a broad collapse of IO output is contradicted by every platform-level measurement.</p>
"""
    fig2 = f"""<figure id="fig2"><p class="flab">Figure 2</p><p class="ftit">Bayesian Posterior Change in Output per Platform Group After the Vladimir Strike</p>
{fig_groups(by)}
<p class="note"><i>Note.</i> Posterior median (value at right) and 90% credible interval, including the common news-shock variance estimated before the strikes. Red: credible drop. Green: drops larger than 20% ruled out. Grey: inconclusive. The shaded band marks drops beyond the 20% smallest effect of interest.</p></figure>
"""
    sec4 = f"""<h2 id="s4">4. Conclusion</h2>
<p>The October 2026 drone strikes by the Ukrainian armed forces on Yandex data centers produced a large and sustained outage of Yandex Cloud, and published reports alone were sufficient to reconstruct its timing to within minutes. The evidence does not support the view that the strikes silenced Russian information operations. Their only measurable effect on IO output was {an_(pr['dip_hours'])} {pr['dip_hours']:.0f}-hour stall of the Pravda network after the Vladimir strike, a pro-Kremlin amplification network that automatically republishes state media and Telegram content rather than producing original disinformation, so the stall reduced the reach of existing narratives rather than their production. This pattern is consistent with a dependency of one republishing pipeline on lost capacity rather than with a broad loss of capability. The human-operated Telegram channels of state media, military bloggers and foreign-audience outlets continued and partly intensified with coverage of the strikes. These conclusions rest on publicly available data and on a broad but not exhaustive set of actors that is representative of the observable Russian information ecosystem; effects on closed or unobserved infrastructure cannot be excluded.</p>
<p>Two implications follow. First, physical strikes on a major domestic cloud provider are unlikely by themselves to degrade Russian information operations, because the producing actors are distributed across platforms and hosting providers and the most visible channels are operated by people rather than by single technical pipelines. Second, automated amplification networks are the most exposed component: the Pravda network's stall shows that such pipelines can be interrupted by infrastructure loss, but also that the effect is brief and that a backlog is partly published once capacity returns. Monitoring the timing of such networks against independent outage measurements, as done here, offers a practical way to detect these dependencies in future incidents.</p>
"""

    refs = "".join(f'<li id="ref-{i + 1}">{REF[k]}</li>' for i, k in enumerate(order))
    missing = [k for k in REF if k not in order]
    assert not missing, f"uncited references: {missing}"

    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{TITLE}</title>
<style>
@page {{ size: A4; margin: 15mm 17mm 14mm 17mm; @bottom-center {{ content: counter(page); font-family: Charter, Georgia, serif; font-size: 8.5pt; }} }}
@page :first {{ margin: 0; @bottom-center {{ content: none; }} }}
* {{ box-sizing: border-box; }}
html {{ font-variant-ligatures: none; font-kerning: normal; }}
body {{ font-family: Charter, "Iowan Old Style", Georgia, "Times New Roman", serif; color: #111; font-size: 9.2pt; line-height: 1.38; margin: 0; }}
a {{ color: #143e86; text-decoration: none; }}
a.cite, a.int {{ color: #143e86; }}
.title {{ position: relative; width: 210mm; height: 297mm; overflow: hidden; page-break-after: always; color: #fff; }}
.title svg.band {{ position: absolute; inset: 0; width: 100%; height: 100%; }}
.title .in {{ position: relative; height: 297mm; padding: 0 15mm 16mm; display: flex; flex-direction: column; }}
.title .top {{ margin-top: 46mm; }}
.title .abs {{ margin-top: 13mm; }}
.title .abs h2 {{ font-size: 13pt; margin: 0 0 2.8mm; color: #fff; }}
.title .kw {{ font-size: 9.6pt; color: rgba(255,255,255,.85); margin-top: 3mm; text-align: left; }}
.title .abs p {{ font-size: 10.6pt; line-height: 1.5; color: rgba(255,255,255,.94); }}
.title h1 {{ font-size: 22.5pt; line-height: 1.22; margin: 0 0 7mm; font-weight: 700; text-align: justify; text-align-last: justify; hyphens: none; }}
.title .sub {{ font-size: 12.5pt; line-height: 1.45; font-style: italic; text-align: left; hyphens: none; opacity: .92; }}
.title .date {{ margin-top: auto; font-family: "Helvetica Neue", Arial, sans-serif; font-size: 11pt; opacity: .9; }}
h2 {{ font-size: 12pt; margin: 5mm 0 2mm; font-weight: 700; break-after: avoid; }}
h3 {{ font-size: 9.8pt; margin: 3.2mm 0 1mm; font-weight: 700; font-style: italic; break-after: avoid; }}
p {{ margin: 0 0 2mm; text-align: justify; hyphens: auto; }}
.bl {{ background: #f1f4f9; border-left: 1.6mm solid #143e86; padding: 3.6mm 4.8mm 3.8mm; margin: 0 0 5mm; break-inside: avoid; }}
.bl .lab {{ font-family: "Helvetica Neue", Arial, sans-serif; font-size: 7.4pt; font-weight: 700; text-transform: uppercase; color: #143e86; margin: 0 0 1.2mm; }}
.bl .txt {{ hyphens: none; font-size: 12pt; font-weight: 700; line-height: 1.3; margin: 0 0 3mm; text-align: left; }}
.bl .grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 4.5mm; border-top: .5pt solid #c9d3e3; padding-top: 2.8mm; }}
.bl .grid div {{ font-size: 8.8pt; line-height: 1.38; }}
.bl .grid b {{ display: block; font-family: "Helvetica Neue", Arial, sans-serif; font-size: 7pt; text-transform: uppercase; margin-bottom: .8mm; }}
.bl .c1 b {{ color: #143e86; }} .bl .c2 b {{ color: #b3261e; }} .bl .c3 b {{ color: #1d7a3a; }}
.kj {{ margin: 0 0 2.8mm; break-inside: avoid; }}
.kj p {{ margin: 0; }}
.kjh {{ display: flex; gap: 2.4mm; text-align: left; }}
.kjn {{ flex: none; width: 5mm; height: 5mm; border-radius: 1mm; background: #143e86; color: #fff; font-family: "Helvetica Neue", Arial, sans-serif; font-size: 7.4pt; font-weight: 700; display: inline-flex; align-items: center; justify-content: center; margin-top: .3mm; }}
.kjm, .kjb {{ padding-left: 7.4mm; }}
.kjm {{ color: #143e86; font-size: 8.8pt; }}
.kjb {{ font-size: 9pt; }}
figure {{ margin: 3mm 0 3.5mm; break-inside: avoid; text-align: left; }}
.flab {{ font-weight: 700; margin: 0; text-align: left; }}
.ftit {{ font-style: italic; margin: .6mm 0 1.6mm; text-align: left; }}
figure svg {{ width: 100%; height: auto; display: block; }}
.note {{ font-size: 8.3pt; line-height: 1.38; margin-top: 1.4mm; text-align: left; }}
ul {{ margin: 0 0 2mm; padding-left: 4.5mm; }}
li {{ margin-bottom: .9mm; text-align: justify; }}
.hl {{ color: #b3261e; font-weight: 700; }}
.page2 {{ page-break-after: always; }}
.refs {{ page-break-before: always; }}
.refs h2 {{ margin-top: 0; }}
.refs ol {{ padding-left: 7mm; margin: 0; }}
.refs li {{ font-size: 8.3pt; line-height: 1.36; margin: 0 0 1.4mm; text-align: left; hyphens: manual; break-inside: avoid; padding-left: 1mm; }}
</style></head><body>

<section class="title">{band}<div class="in">
  <div class="top">
  <h1>Yandex Cloud Outages as a Natural Experiment<br>on Russian Influence Operations: Bayesian<br>Outage Modelling with Change-Point Attribution</h1>
  </div>
  <div class="abs"><h2>Abstract</h2><p>{abstract}</p>
  <p class="kw"><i>Keywords:</i> information operations; foreign information manipulation and interference; Portal Kombat; Yandex Cloud; natural experiment; Bayesian hierarchical model; change-point analysis; DISARM; STIX 2.1</p></div>
  <div class="date">October 2026</div>
</div></section>



<section>
{sec1}{sec2}{sec3}{sec32}{fig1}{fig2}{sec4}
</section>

<section class="refs"><h2 id="refs">References</h2><ol>{refs}</ol></section>
</body></html>"""
    html = re.sub(r'(<a href="[^"]+">)([^<]+)(</a>)', lambda m: m.group(1) + re.sub(r"([/.])", r"\1<wbr>", m.group(2)) + m.group(3), html)
    assert chr(0x2014) not in html, "em dash in report"
    (OUT / "report.html").write_text(html)
    pdf = OUT / "REPORT.pdf"
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--virtual-time-budget=8000",
                    f"--print-to-pdf={pdf}", (OUT / "report.html").as_uri()], check=True, capture_output=True, timeout=180)
    from pypdf import PdfReader, PdfWriter
    r = PdfReader(str(pdf))
    w = PdfWriter(clone_from=r)
    w.add_metadata({"/Title": TITLE,
                    "/Subject": "Assessment of the October 2026 Yandex data-center strikes and Russian information operations"})
    with open(pdf, "wb") as f:
        w.write(f)
    shutil.copy(pdf, ROOT / "REPORT.pdf")
    shutil.copy(pdf, ROOT / "dashboard" / "REPORT.pdf")
    print("pages:", len(r.pages), pdf)


if __name__ == "__main__":
    build()
