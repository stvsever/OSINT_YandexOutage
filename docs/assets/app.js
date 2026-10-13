/* Yandex Ablation: outage attribution dashboard.
 * Static single-page app on D3 v7. Data globals: SERIES, EOF, TIMING, EVIDENCE, BAYES.
 */
(function () {
  "use strict";
  const SER = window.SERIES.series, H0 = Date.parse(window.SERIES.t0), NH = window.SERIES.n;
  const EV = window.EVIDENCE, TM = window.TIMING, E = window.EOF, BY = window.BAYES;
  const HOUR = 3600e3, MIN10 = 600e3;
  const ONSETS = Object.fromEntries(Object.entries(EV.analysis.onsets).map(([k, v]) => [k, new Date(v)]));
  const EVN = { SAS: "Sasovo", KAL: "Kaluga", VLA: "Vladimir", SEP27: "27 Sep placebo" };
  const HI_T0 = Date.parse(E.hi_t0), STUDY_END = Date.parse(EV.meta.study_end), BASE_END = Date.parse(EV.meta.baseline_end);
  const hourTimes = d3.range(NH).map((i) => new Date(H0 + i * HOUR));
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const SLOT = ["--s1", "--s2", "--s3", "--s4", "--s5", "--s6", "--s7", "--s8"];
  const store = { get(k, d) { try { const v = localStorage.getItem("ya." + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem("ya." + k, JSON.stringify(v)); } catch (e) { /* storage unavailable */ } } };

  // ------------------------------------------------------------------ glossary
  const GLOSS = {
    eof: ["Expected outage function (EOF)", "A time-varying estimate of the share of Yandex capacity that is offline, computed from open sources. Each strike contributes a capacity-weighted damage curve whose timing, severity, credibility and recovery come from graded reports. It has three stages: S0 uses strike reports only, S1 adds published statements, status pages, satellite fire detections and complaint alerts, and S2 also fuses direct network measurements."],
    stages: ["Estimation stages", "S0 attack prior: strike windows and damage wording only. S1 OSINT-conditioned: S0 plus everything published (status pages, statements, FIRMS, NetBlocks, Cloudflare, complaint alerts). S2 telemetry-fused: S1 plus the IODA active-probing measurement. Comparing S1 with the measurement validates the open-source method."],
    ioda: ["IODA active probing", "Georgia Tech's Internet Outage Detection and Analysis pings address blocks (/24) in each network every 10 minutes. The share of blocks that stop answering is the measured outage."],
    admiralty: ["Admiralty grading", "NATO source grading. Reliability of the source from A (completely reliable) to F (cannot be judged); credibility of the item from 1 (confirmed) to 6 (cannot be judged). Grades are converted to probabilities and pooled into each strike's credibility."],
    counterfactual: ["Seasonal counterfactual", "For each series the expected value had nothing happened: a regression on hour-of-day, day-of-week, weekend-by-hour and trend, fitted on the pre-strike baseline only. Deviations are measured against it out of sample."],
    placebo: ["Placebo-in-time test", "The same statistic is computed for every comparable window before the strikes. If the post-strike value is more extreme than almost all placebo windows, the change is unusual; the share of placebo windows at least as extreme is the p-value."],
    mde: ["Minimum detectable effect (MDE)", "The smallest drop a series could reliably detect (80 % power, one-sided 5 % level) given its own noise. Noisy series with a large MDE cannot rule out moderate effects and can be hidden with the uncertainty filter."],
    sesoi: ["Smallest effect of interest", "A 20 % drop. A series rules out a meaningful reduction when the whole 90 % interval of its estimated change lies above -20 %."],
    fdr: ["False discovery rate (FDR)", "With many series some look significant by chance. Benjamini-Hochberg q-values control the expected share of false positives among flagged series."],
    bayes: ["Bayesian hierarchical model", "Effects of individual channels, languages, communities and websites are partially pooled within their platform group, with an extra term for outlets that depend on Yandex 360 mail. Group effects include the common news-shock variance measured before the strikes. A credible drop needs a posterior probability above 90 % of a drop larger than 10 % and a group placebo p below 0.05."],
    timing: ["Change-point timing test", "A 10-minute dip model finds the most likely start, end and depth of a drop. An outage-driven dip must begin at or shortly after the measured outage onset; one that starts hours before cannot be caused by it. The scan is calibrated with 400 placebo origins."],
    backlog: ["Backlog recovery", "Surplus output in the 6 hours after a dip divided by the deficit inside it. Near 100 % means items were queued and published late (a stalled pipeline); near 0 % means output was lost."],
    theme: ["Theme conditioning", "Posts and threads are labelled Ukraine-war or other with a multilingual keyword lexicon. A dependency specific to war propaganda would show as a larger drop in war content than in other content."],
    ach: ["Analysis of competing hypotheses (ACH)", "Each piece of evidence is rated consistent, inconsistent or not diagnostic with each hypothesis. The hypothesis with the least weighted inconsistency is preferred (Heuer)."],
    icd: ["Estimative language (ICD 203)", "Almost certain 95 to 99 %, very likely 80 to 95 %, likely 55 to 80 %, roughly even 45 to 55 %, unlikely 20 to 45 %, very unlikely 5 to 20 %."],
    yxdep: ["Yandex dependency (DNS)", "Public DNS records of each outlet show where its website is hosted, who runs its mail (MX) and its name servers (NS). No IO website is hosted on Yandex; seven outlets, including RT, Readovka, Rybar and Strategic Culture, run their mail on Yandex 360."],
    pravda: ["Pravda network (Portal Kombat)", "An automated network of sites in dozens of languages that republishes and machine-translates pro-Kremlin Telegram content. Its public sitemaps give the exact publication time of every article."],
  };
  const pop = document.getElementById("pop");
  function info(key) {
    const b = document.createElement("button"); b.className = "info"; b.textContent = "i"; b.type = "button"; b.setAttribute("aria-label", "Explain " + (GLOSS[key]?.[0] || key));
    b.addEventListener("click", (ev) => {
      ev.stopPropagation(); ev.preventDefault();
      const g = GLOSS[key]; if (!g) return;
      pop.replaceChildren(el("h4", { text: g[0] }), el("p", { text: g[1] }));
      pop.style.display = "block";
      const r = b.getBoundingClientRect(); const w = pop.offsetWidth, h = pop.offsetHeight;
      let x = r.left; if (x + w > innerWidth - 10) x = innerWidth - w - 10;
      let y = r.bottom + 6; if (y + h > innerHeight - 10) y = r.top - h - 6;
      pop.style.left = Math.max(10, x) + "px"; pop.style.top = y + "px";
    });
    return b;
  }
  document.addEventListener("click", () => { pop.style.display = "none"; });

  // ------------------------------------------------------------------ state
  const S = {
    view: store.get("view", "overview"),
    win: [new Date("2026-10-05T00:00:00Z"), new Date(STUDY_END)], preset: "week", res: "1h", tz: "UTC",
    eof: { target: "cloud", stage: "S1", bands: true, traj: false, ioda: true, custom: null,
      opts: { damageScale: 1, recoveryMult: 1, lagMean: 45, rampMean: 30, concentration: 6, credibility: true, derivative: 0.3, events: { SAS: true, KAL: true, VLA: true }, n: 1200 } },
    sel: {
      infrastructure: ["ioda.asn.200350.ping-slash24", "ioda.asn.208795.ping-slash24", "ioda.asn.49505.ping-slash24", "ioda.country.RU.ping-slash24"],
      services: ["wiki.ru.wikipedia.user", "wiki.ru.wikipedia.user.mobile-web", "wiki.uk.wikipedia.user"],
      io: ["pravda.total", "tg.prokremlin.all", "tg.grp.io_foreign_audience.all", "tg.yxdep.mail", "web.ukraina.ru", "rd.grp.politics.comments"],
      control: ["tg.controls.all", "rd.grp.control.comments", "web.zona.media"],
    },
    theme: "all", norm: "index",
    unc: { maxMDE: 0.6, minCompl: 0.8, minRel: "C", hideInconclusive: false, bandMax: 1.0 },
    ann: { strike: true, statement: true, telemetry: true, claim: false, confounder: true, firms: false, alerts: false },
    layersOn: { eof: true, infrastructure: true, services: true, io: true, control: true },
    inspect: null, tEvent: "VLA", tStream: "pravda.total",
    attr: { metric: "VLA_24h", layer: "io" }, esSeries: "pravda.total", esSmooth: 3, emapWin: "VLA_6h",
    agFocus: null, search: "",
  };
  const slotMaps = {};
  function colorFor(panel, id) {
    const m = (slotMaps[panel] ||= new Map()); const live = new Set(S.sel[panel] || []);
    for (const k of [...m.keys()]) if (!live.has(k)) m.delete(k);
    if (!m.has(id)) { const used = new Set(m.values()); let s = 0; while (used.has(s) && s < 8) s++; m.set(id, s % 8); }
    return css(SLOT[m.get(id)]);
  }

  // ------------------------------------------------------------------ helpers
  const pad = (n) => String(n).padStart(2, "0");
  const MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const shift = (t) => new Date(+t + (S.tz === "MSK" ? 3 * HOUR : 0));
  function fmtT(t, withTz = true) { const d = shift(t); return `${pad(d.getUTCDate())} ${MON[d.getUTCMonth()]} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}${withTz ? " " + S.tz : ""}`; }
  const pct = (x, d = 0) => (x == null || !isFinite(x) ? "n/a" : (x > 0 ? "+" : "") + (x * 100).toFixed(d) + "%");
  const pctu = (x, d = 0) => (x == null || !isFinite(x) ? "n/a" : (x * 100).toFixed(d) + "%");
  const num = (x, d = 0) => (x == null || !isFinite(x) ? "n/a" : d3.format(`,.${d}f`)(x));
  const pv = (p) => (p == null ? "n/a" : p < 0.001 ? "<0.001" : p.toFixed(3));
  function el(tag, attrs = {}, ...kids) {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") n.className = v; else if (k === "text") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v); else if (v !== null && v !== undefined && v !== false) n.setAttribute(k, v);
    }
    for (const k of kids) if (k != null && k !== "") n.append(k.nodeType ? k : document.createTextNode(k));
    return n;
  }
  const REL = ["A", "B", "C", "D", "E", "F"];
  function seriesPasses(id) {
    const s = SER[id]; if (!s) return false; const st = s.stats;
    if (!st) return ["infrastructure", "exposure", "services"].includes(s.layer);
    if (st.completeness != null && st.completeness < S.unc.minCompl) return false;
    if (st.mde80_vla24 != null && st.mde80_vla24 > S.unc.maxMDE) return false;
    if (S.unc.hideInconclusive && st.verdict === "Inconclusive") return false;
    return true;
  }
  function failReason(id) { const st = SER[id]?.stats; if (!st) return ""; if (st.completeness < S.unc.minCompl) return `completeness ${pctu(st.completeness)}`; if (st.mde80_vla24 > S.unc.maxMDE) return `MDE ${Math.round(st.mde80_vla24 * 100)}%`; if (S.unc.hideInconclusive && st.verdict === "Inconclusive") return "inconclusive"; return ""; }
  function themed(id) { if (S.theme === "all" || S.theme === "diff") return id; const base = id.replace(/\.(all|war|other)$/, ""); const c = `${base}.${S.theme}`; return SER[c] ? c : id; }
  const sourceOk = (ids) => ids.some((sid) => { const s = EV.sources.find((x) => x.id === sid); return s && REL.indexOf(s.rel) <= REL.indexOf(S.unc.minRel); });
  function baselineMedian(arr) { const nb = Math.floor((BASE_END - H0) / HOUR); return d3.median(arr.slice(0, nb).filter((x) => x != null && isFinite(x) && x > 0)) || 1; }
  function agg(xs, ys, how, unit) {
    if (S.res !== "6h") return { xs, ys, unit };
    const ox = [], oy = [];
    for (let i = 0; i < xs.length; i += 6) { const seg = ys.slice(i, i + 6).filter((v) => v != null && isFinite(v)); ox.push(xs[i]); oy.push(seg.length ? (how === "sum" ? d3.sum(seg) : d3.mean(seg)) : null); }
    return { xs: ox, ys: oy, unit };
  }
  function seriesXY(id) {
    const t = SER[themed(id)] || SER[id];
    if (S.theme === "diff") {
      const base = id.replace(/\.(all|war|other)$/, ""); const w = SER[`${base}.war`], o = SER[`${base}.other`];
      if (w?.a && o?.a) return agg(hourTimes, w.a.map((x, i) => (x == null || o.a[i] == null ? null : (Math.exp(x - o.a[i]) - 1) * 100)), "mean", "% war minus non-war");
    }
    const isCount = (t.transform || "count") === "count"; let ys;
    if (S.norm === "raw") ys = t.v.slice();
    else if (S.norm === "index") {
      if (t.cf && isCount) ys = t.v.map((v, i) => (v == null || t.cf[i] == null ? null : (100 * (v + 1)) / (t.cf[i] + 1)));
      else { const b = baselineMedian(t.v); ys = t.v.map((v) => (v == null ? null : (100 * v) / b)); }
    } else if (S.norm === "anom") {
      if (t.a) ys = t.a.map((x) => (x == null ? null : (Math.exp(x) - 1) * 100));
      else { const b = baselineMedian(t.v); ys = t.v.map((v) => (v == null ? null : (100 * v) / b - 100)); }
    } else { const sg = t.stats?.sigma_log || 1; ys = t.a ? t.a.map((x) => (x == null ? null : x / sg)) : t.v.map(() => null); }
    return agg(hourTimes, ys, isCount && S.norm === "raw" ? "sum" : "mean", { raw: t.unit || "", index: "index, 100 = expected", anom: "% vs expected", z: "z-score" }[S.norm]);
  }

  // ------------------------------------------------------------------ tooltip
  const tip = document.getElementById("tip");
  function showTip(ev, head, rows) {
    tip.replaceChildren(el("div", { class: "t-h", text: head }));
    for (const r of rows) { const nm = el("span", { class: "nm" }); if (r.color) nm.append(el("span", { class: "swatch", style: `background:${r.color}` })); nm.append(document.createTextNode(r.label)); tip.append(el("div", { class: "t-r" }, nm, el("b", { text: r.value }))); }
    tip.style.display = "block";
    const w = tip.offsetWidth, h = tip.offsetHeight; let x = ev.clientX + 14, y = ev.clientY + 12;
    if (x + w > innerWidth - 8) x = ev.clientX - w - 14; if (y + h > innerHeight - 8) y = ev.clientY - h - 12;
    tip.style.left = x + "px"; tip.style.top = y + "px";
  }
  const hideTip = () => { tip.style.display = "none"; };

  // ------------------------------------------------------------------ time chart
  const charts = [];
  const tickFmt = (d) => { const s = shift(d); return s.getUTCHours() === 0 && s.getUTCMinutes() === 0 ? `${pad(s.getUTCDate())} ${MON[s.getUTCMonth()]}` : `${pad(s.getUTCHours())}:${pad(s.getUTCMinutes())}`; };
  function drawEvents(g, x, h, win) {
    const evs = EV.events.filter((e) => S.ann[e.kind] !== false && sourceOk(e.sources)).filter((e) => { const t = Date.parse(e.t); return t >= +win[0] && t <= +win[1]; });
    for (const e of evs) {
      const xx = x(new Date(e.t));
      const gg = g.append("g").attr("class", "evmark").on("click", () => inspect({ type: "event", id: e.id })).on("mousemove", (ev) => showTip(ev, fmtT(new Date(e.t)), [{ label: e.title, value: e.kind }])).on("mouseleave", hideTip);
      gg.append("line").attr("class", `evline ${e.kind}`).attr("x1", xx).attr("x2", xx).attr("y1", 0).attr("y2", h).attr("stroke-opacity", 0.6);
      gg.append("rect").attr("x", xx - 5).attr("width", 10).attr("y", 0).attr("height", h).attr("fill", "transparent");
    }
    if (S.ann.firms) for (const f of EV.firms) { const t = Date.parse(f.t); if (t < +win[0] || t > +win[1]) continue; g.append("path").attr("d", d3.symbol(d3.symbolTriangle, 34)()).attr("transform", `translate(${x(new Date(t))},${h - 6})`).attr("fill", css("--serious")).on("mousemove", (ev) => showTip(ev, fmtT(new Date(t)), [{ label: `FIRMS ${f.sensor}, ${f.km} km from ${f.site}`, value: `${f.frp} MW` }])).on("mouseleave", hideTip); }
    if (S.ann.alerts) for (const a of EV.alerts) { if (!a.yandex) continue; const t = Date.parse(a.t); if (t < +win[0] || t > +win[1]) continue; g.append("circle").attr("cx", x(new Date(t))).attr("cy", 6).attr("r", 3).attr("fill", css("--s4")).on("mousemove", (ev) => showTip(ev, fmtT(new Date(t)), [{ label: a.text.slice(0, 80), value: "alert" }])).on("mouseleave", hideTip); }
  }
  function timeChart(container, cfg) {
    const W = Math.max(320, container.clientWidth || 800), H = cfg.height || 180;
    const m = { l: 50, r: 14, t: cfg.title ? 24 : 8, b: cfg.xAxis === false ? 6 : 22 };
    const svg = d3.select(container).append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("height", H);
    const win = cfg.win || S.win;
    const x = d3.scaleUtc().domain(win).range([m.l, W - m.r]);
    const allY = [];
    for (const s of cfg.series) s.ys.forEach((v, i) => { const t = +s.xs[i]; if (v != null && isFinite(v) && t >= +win[0] && t <= +win[1]) allY.push(v); });
    for (const b of cfg.bands || []) b.lo.forEach((v, i) => { const t = +b.xs[i]; if (t >= +win[0] && t <= +win[1]) { if (v != null) allY.push(v); if (b.hi[i] != null) allY.push(b.hi[i]); } });
    let yd = cfg.yDomain || d3.extent(allY.length ? allY : [0, 1]);
    if (!cfg.yDomain) { const pd = (yd[1] - yd[0]) * 0.08 || 1; yd = [yd[0] - pd, yd[1] + pd]; }
    const y = d3.scaleLinear().domain(yd).nice().range([H - m.b, m.t]);
    svg.append("g").attr("class", "gridline").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(4).tickSize(-(W - m.l - m.r)).tickFormat(""));
    svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(4).tickFormat(cfg.yFmt || d3.format("~s"))).call((g) => g.select(".domain").remove());
    if (cfg.xAxis !== false) svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.b})`).call(d3.axisBottom(x).ticks(Math.max(3, Math.floor(W / 110))).tickFormat(tickFmt));
    if (cfg.title) { svg.append("text").attr("class", "plab").attr("x", m.l).attr("y", 14).text(cfg.title); if (cfg.unit) svg.append("text").attr("class", "plab-sub").attr("x", W - m.r).attr("y", 14).attr("text-anchor", "end").text(cfg.unit); }
    const clipId = "c" + Math.random().toString(36).slice(2);
    svg.append("clipPath").attr("id", clipId).append("rect").attr("x", m.l).attr("y", 0).attr("width", W - m.l - m.r).attr("height", H);
    const body = svg.append("g").attr("clip-path", `url(#${clipId})`);
    if (cfg.shadePost) body.append("rect").attr("x", x(new Date(BASE_END))).attr("width", Math.max(0, x(win[1]) - x(new Date(BASE_END)))).attr("y", m.t).attr("height", H - m.t - m.b).attr("fill", css("--surface-2")).attr("opacity", 0.7);
    if (cfg.refLine != null) body.append("line").attr("x1", m.l).attr("x2", W - m.r).attr("y1", y(cfg.refLine)).attr("y2", y(cfg.refLine)).attr("stroke", css("--axis"));
    for (const sh of cfg.shades || []) body.append("rect").attr("x", x(sh[0])).attr("width", Math.max(1, x(sh[1]) - x(sh[0]))).attr("y", m.t).attr("height", H - m.t - m.b).attr("fill", sh[2] || css("--band"));
    for (const b of cfg.bands || []) body.append("path").datum(b.xs).attr("d", d3.area().defined((d, i) => b.lo[i] != null && b.hi[i] != null).x((d, i) => x(b.xs[i])).y0((d, i) => y(b.lo[i])).y1((d, i) => y(b.hi[i])).curve(d3.curveStepAfter)).attr("fill", b.fill);
    for (const s of cfg.lines2 || []) body.append("path").datum(s.xs).attr("d", d3.line().defined((d, i) => s.ys[i] != null).x((d, i) => x(s.xs[i])).y((d, i) => y(s.ys[i]))).attr("fill", "none").attr("stroke", s.color).attr("stroke-width", 0.8).attr("opacity", s.opacity ?? 0.2);
    for (const s of cfg.series) body.append("path").datum(s.xs).attr("d", d3.line().defined((d, i) => s.ys[i] != null && isFinite(s.ys[i])).x((d, i) => x(s.xs[i])).y((d, i) => y(s.ys[i])).curve(s.curve || d3.curveStepAfter))
      .attr("fill", "none").attr("stroke", s.color).attr("stroke-width", s.width || 1.6).attr("stroke-dasharray", s.dash || null).attr("opacity", s.faded ? 0.4 : 1).style("cursor", s.id ? "pointer" : null).on("click", () => s.id && inspect({ type: "series", id: s.id }));
    for (const lab of cfg.marks || []) { const xx = x(lab.t); body.append("line").attr("x1", xx).attr("x2", xx).attr("y1", m.t).attr("y2", H - m.b).attr("stroke", lab.color || css("--critical")).attr("stroke-width", 1.5); body.append("text").attr("class", "evlabel").attr("x", xx + 4).attr("y", m.t + 11).text(lab.text); }
    if (cfg.events !== false) drawEvents(body, x, H - m.b, win);
    const cross = svg.append("line").attr("class", "crosshair").attr("y1", m.t).attr("y2", H - m.b).style("display", "none");
    svg.append("rect").attr("x", m.l).attr("y", m.t).attr("width", W - m.l - m.r).attr("height", H - m.t - m.b).attr("fill", "transparent").style("pointer-events", "all")
      .on("mousemove", (ev) => {
        const t = x.invert(d3.pointer(ev)[0]); charts.forEach((c) => c.move(t));
        const rows = cfg.series.map((s) => { const i = d3.bisectRight(s.xs, t) - 1; const v = i >= 0 ? s.ys[i] : null; return { label: s.label, color: s.color, value: v == null || !isFinite(v) ? "n/a" : (cfg.tipFmt || d3.format(",.1f"))(v) }; });
        showTip(ev, fmtT(t), rows);
      })
      .on("mouseleave", () => { charts.forEach((c) => c.move(null)); hideTip(); })
      .on("click", (ev) => { if (ev.shiftKey) { const t = x.invert(d3.pointer(ev)[0]); setWindow([new Date(+t - 12 * HOUR), new Date(+t + 12 * HOUR)], "custom"); } });
    charts.push({ move: (t) => { if (!t || t < win[0] || t > win[1]) cross.style("display", "none"); else cross.style("display", null).attr("x1", x(t)).attr("x2", x(t)); } });
    if (cfg.legend !== false && cfg.series.length > 1) {
      const lg = el("div", { class: "legend" });
      for (const s of cfg.series) lg.append(el("span", { onclick: () => s.id && inspect({ type: "series", id: s.id }) }, el("span", { class: "swatch", style: `background:${s.color}` }), s.label));
      container.append(lg);
    }
    return { x, y, svg };
  }

  // ------------------------------------------------------------------ EOF
  function eofData(hi) {
    const tg = S.eof.target, st = S.eof.stage;
    if (st === "custom" && S.eof.custom) return { xs: S.eof.custom.mean.map((_, j) => new Date(HI_T0 + j * MIN10)), ...S.eof.custom };
    if (hi && E.hi[tg]?.[st]) { const d = E.hi[tg][st]; return { xs: d.mean.map((_, j) => new Date(HI_T0 + j * MIN10)), ...d }; }
    const d = E.hourly[tg][st] || E.hourly[tg].S1; return { xs: hourTimes, ...d };
  }
  function iodaSeries(hi) {
    if (hi) { const s = TM.series["ioda.asn.200350"]; const base = E.telemetry_info.baseline_slash24; return { xs: s.obs.map((_, j) => new Date(Date.parse(TM.t0) + j * MIN10)), ys: s.obs.map((v) => (v == null ? null : Math.max(0, 1 - v / base) * 100)) }; }
    return { xs: hourTimes, ys: E.ioda_obs.map((v) => (v == null ? null : Math.max(0, v) * 100)) };
  }
  function eofChart(container, opt = {}) {
    const win = opt.win || S.win;
    const hi = opt.hi || S.res === "10m" || (+win[1] - +win[0] < 4 * 86400e3 && +win[0] >= HI_T0);
    const d = eofData(hi); const sc = (a) => a.map((v) => (v == null ? null : v * 100));
    const bands = S.eof.bands ? [{ xs: d.xs, lo: sc(d.q05), hi: sc(d.q95), fill: css("--band") }, { xs: d.xs, lo: sc(d.q25), hi: sc(d.q75), fill: css("--band-strong") }] : [];
    const wide = d.q95.map((v, i) => v - d.q05[i] > S.unc.bandMax);
    const m = sc(d.mean);
    const series = [{ label: `Expected outage (${{ S0: "S0 prior", S1: "S1 OSINT", S2: "S2 fused", custom: "what-if" }[S.eof.stage]})`, color: css("--s1"), xs: d.xs, ys: m.map((v, i) => (wide[i] ? null : v)), width: 2.2 }];
    if (wide.some(Boolean)) series.push({ label: "Expected outage, band above filter", color: css("--s1"), xs: d.xs, ys: m.map((v, i) => (wide[i] ? v : null)), dash: "3 3", faded: true });
    if (S.eof.ioda && S.eof.target === "cloud") { const io = iodaSeries(hi); series.push({ label: "Measured outage (IODA)", color: css("--s2"), xs: io.xs, ys: io.ys, width: 1.5 }); }
    const lines2 = [];
    if (S.eof.traj && S.eof.stage !== "custom") { const tr = E.traj.paths[`${S.eof.target}_${S.eof.stage}`] || []; const t0 = Date.parse(E.traj.t0); for (const p of tr) lines2.push({ xs: p.map((_, j) => new Date(t0 + j * MIN10)), ys: p.map((v) => v * 100), color: css("--s1") }); }
    return timeChart(container, { win, title: opt.title === false ? null : `Expected outage of ${S.eof.target === "cloud" ? "Yandex Cloud" : "Yandex LLC compute"} vs measured`, unit: "% of capacity offline", series, bands, lines2, yDomain: [0, 100], height: opt.height || 210, yFmt: (v) => v + "%", tipFmt: (v) => v.toFixed(1) + "%" });
  }
  function runCustom() { const len = Math.round((STUDY_END - HI_T0) / MIN10); S.eof.custom = window.EOFModel.run(E.config, { ...S.eof.opts, target: S.eof.target, stage: 1, grid: { t0iso: E.hi_t0, step: 10, len } }); }

  // ------------------------------------------------------------------ panels: collapse and resize
  const bodyEl = document.getElementById("body");
  const LP = document.getElementById("leftp"), RP = document.getElementById("rightp");
  const PW = store.get("pw", { l: 300, r: 340, lc: innerWidth < 760, rc: innerWidth < 1100 });
  const narrow = () => innerWidth < 1100;
  document.getElementById("mainwrap").addEventListener("pointerdown", () => {
    // on small screens the panels are overlays: tapping the content closes them
    let ch = false;
    if (innerWidth < 760 && !PW.lc) { PW.lc = true; ch = true; }
    if (narrow() && !PW.rc) { PW.rc = true; ch = true; }
    if (ch) applyPanels();
  });
  function applyPanels() {
    bodyEl.style.setProperty("--lw", PW.lc ? "44px" : PW.l + "px");
    bodyEl.style.setProperty("--rw", PW.rc ? "44px" : PW.r + "px");
    LP.classList.toggle("collapsed", PW.lc); RP.classList.toggle("collapsed", PW.rc);
    document.getElementById("rzL").classList.toggle("off", PW.lc); document.getElementById("rzR").classList.toggle("off", PW.rc);
    document.querySelector("#tl svg path").setAttribute("d", PW.lc ? "M6 3l5 5-5 5" : "M10 3 5 8l5 5");
    document.querySelector("#tr svg path").setAttribute("d", PW.rc ? "M10 3 5 8l5 5" : "M6 3l5 5-5 5");
    document.getElementById("tl").title = PW.lc ? "Expand controls" : "Collapse controls";
    document.getElementById("tr").title = PW.rc ? "Expand inspector" : "Collapse inspector";
    store.set("pw", PW);
  }
  function togglePanel(side, force) { if (side === "l") PW.lc = force ?? !PW.lc; else PW.rc = force ?? !PW.rc; applyPanels(); rerender(); }
  document.getElementById("tl").addEventListener("click", () => togglePanel("l"));
  document.getElementById("tr").addEventListener("click", () => togglePanel("r"));
  document.getElementById("railL").addEventListener("click", () => togglePanel("l", false));
  document.getElementById("railR").addEventListener("click", () => togglePanel("r", false));
  for (const [id, side] of [["rzL", "l"], ["rzR", "r"]]) {
    const rz = document.getElementById(id);
    rz.addEventListener("pointerdown", (ev) => {
      ev.preventDefault(); rz.classList.add("drag"); rz.setPointerCapture(ev.pointerId);
      const x0 = ev.clientX, w0 = side === "l" ? PW.l : PW.r;
      const move = (e) => { const dx = e.clientX - x0; const w = Math.max(240, Math.min(560, side === "l" ? w0 + dx : w0 - dx)); if (side === "l") PW.l = w; else PW.r = w; bodyEl.style.setProperty(side === "l" ? "--lw" : "--rw", w + "px"); };
      const up = () => { rz.classList.remove("drag"); rz.removeEventListener("pointermove", move); rz.removeEventListener("pointerup", up); applyPanels(); rerender(); };
      rz.addEventListener("pointermove", move); rz.addEventListener("pointerup", up);
    });
    rz.addEventListener("dblclick", () => { if (side === "l") PW.l = 300; else PW.r = 340; applyPanels(); rerender(); });
  }

  // ------------------------------------------------------------------ inspector
  function inspect(obj) { S.inspect = obj; if (PW.rc) { PW.rc = false; applyPanels(); rerender(); } renderInspector(); }
  const kv = (pairs) => { const g = el("div", { class: "kv" }); for (const [k, v] of pairs) { g.append(el("div", { text: k })); g.append(v && v.nodeType ? v : el("div", { text: v ?? "n/a" })); } return g; };
  function verdictTag(v) {
    const map = { "Drop detected": "--critical", "Increase detected": "--s1", "Large drop ruled out": "--good", Inconclusive: "--ink-3" };
    const ic = { "Drop detected": "▼", "Increase detected": "▲", "Large drop ruled out": "✓", Inconclusive: "?" }[v] || "·";
    return el("span", { class: "tag" }, el("span", { style: `color:${css(map[v] || "--ink-3")};font-weight:700`, text: ic }), v || "n/a");
  }
  function renderInspector() {
    const root = document.getElementById("insp"); root.replaceChildren(); const o = S.inspect;
    if (!o) { root.append(el("div", { class: "empty" }, el("b", { text: "Nothing selected" }), "Click a chart line, table row, effect-map cell, graph node, event marker or source to see its data, method and sources here. The i buttons explain terms.")); return; }
    ({ series: inspSeries, event: inspEvent, source: inspSource, eof: inspEOF, timing: inspTiming, group: inspGroup, node: inspNode })[o.type]?.(root, o.id, o);
  }
  function inspSeries(root, id) {
    const s = SER[id]; if (!s) return; const st = s.stats || {};
    root.append(el("h3", { text: s.label }), el("div", { class: "note", text: s.group }));
    const link = s.source_url ? el("a", { href: s.source_url, target: "_blank", rel: "noopener", text: s.source }) : el("span", { text: s.source });
    root.append(kv([["Source", link], ["Method", s.method], ["Baseline mean", st.baseline_mean != null ? num(st.baseline_mean, 1) + " per hour" : "n/a"], ["Completeness", pctu(st.completeness)], ["Min. detectable drop", st.mde80_vla24 != null ? Math.round(st.mde80_vla24 * 100) + "% (24 h)" : "n/a"], ["Verdict", verdictTag(st.verdict)], ["FDR q, Vladimir 24 h", pv(st.q_vla24)]]));
    if (st.windows) {
      const t = el("table", { class: "tbl" }); t.append(el("tr", {}, ...["Window", "Change", "90% interval", "p (drop)"].map((h) => el("th", { text: h }))));
      for (const k of ["SAS_6h", "SAS_24h", "KAL_24h", "VLA_6h", "VLA_24h", "SEP27_24h"]) { const w = st.windows[k]; if (!w) continue; t.append(el("tr", {}, el("td", { text: k.replace("_", " ").replace("SEP27", "27 Sep").replace("SAS", "Sasovo").replace("VLA", "Vladimir").replace("KAL", "Kaluga") }), el("td", { class: "num", text: pct(w.effect) }), el("td", { class: "num", text: `${pct(w.ci90[0])} to ${pct(w.ci90[1])}` }), el("td", { class: "num", text: pv(w.p_drop) }))); }
      root.append(el("div", { class: "lbl" }, "Event windows ", info("placebo")), t);
    }
    if (st.event_study) { const box = el("div"); root.append(el("hr"), el("div", { class: "lbl", text: "Event study, % vs expected (band: placebo 5 to 95%)" }), box); requestAnimationFrame(() => eventStudyChart(box, id, 170, true)); }
    if (st.dose?.S1) { const d = st.dose.S1; root.append(el("hr"), el("div", { class: "lbl" }, "Dose-response on the expected outage (S1) ", info("eof")), el("div", { class: "note", text: `Change at full outage ${pct(d.effect_at_max)} (90%: ${pct(d.ci90[0])} to ${pct(d.ci90[1])}), placebo p ${pv(d.p_placebo_drop)}.` })); }
  }
  function inspEvent(root, id) {
    const e = EV.events.find((x) => x.id === id); if (!e) return;
    const msk = new Date(Date.parse(e.t) + 3 * HOUR);
    root.append(el("h3", { text: e.title }), kv([["Time", `${e.t.slice(0, 16).replace("T", " ")} UTC (${pad(msk.getUTCHours())}:${pad(msk.getUTCMinutes())} MSK)`], ["Kind", e.kind], ["Site", e.site]]), el("p", { class: "note", text: e.detail }));
    root.append(el("div", { class: "lbl" }, "Sources ", info("admiralty")));
    for (const sid of e.sources) { const s = EV.sources.find((x) => x.id === sid); if (s) root.append(el("div", { style: "margin:6px 0;cursor:pointer", onclick: () => inspect({ type: "source", id: s.id }) }, el("span", { class: "adm", text: s.rel + s.cred }), " ", s.name)); }
    const cons = (E.config.osint_constraints || []).filter((c) => Math.abs(Date.parse(c.t || c.t0) - Date.parse(e.t)) < 20 * 60e3);
    if (cons.length) { root.append(el("hr"), el("div", { class: "lbl" }, "Used in the expected outage function ", info("stages"))); for (const c of cons) root.append(el("div", { class: "note", style: "margin:4px 0" }, el("span", { class: "adm", text: `S${c.stage || 1}` }), ` ${c.type.replace("_", " ")}${c.event ? " for " + EVN[c.event] : ""}`)); }
  }
  function inspSource(root, id) {
    const s = EV.sources.find((x) => x.id === id); if (!s) return;
    root.append(el("h3", { text: s.name }), kv([["Type", s.type], ["Grade", el("span", {}, el("span", { class: "adm", text: s.rel + s.cred }), " ", info("admiralty"))], ["Language", s.lang], ["Link", el("a", { href: s.url, target: "_blank", rel: "noopener", text: s.url.replace(/^https?:\/\//, "").slice(0, 44) })]]), el("p", { class: "note", text: s.note }), el("div", { class: "lbl", text: "Supports" }));
    for (const e of EV.events.filter((x) => x.sources.includes(id))) root.append(el("div", { style: "margin:5px 0;cursor:pointer", onclick: () => inspect({ type: "event", id: e.id }), text: `${fmtT(new Date(e.t))} · ${e.title}` }));
  }
  function inspEOF(root) {
    root.append(el("h3", {}, "Expected outage function ", info("eof")), el("p", { class: "note", text: "Capacity-weighted damage model estimated in three stages with sequential Monte Carlo. Validation against the measured IODA outage, 5 to 13 Oct:" }));
    const t = el("table", { class: "tbl" }); t.append(el("tr", {}, ...["Stage", "R²", "MAE", "90% cover", "Onset error"].map((h) => el("th", { text: h }))));
    for (const st of ["S0", "S1", "S2"]) { const x = E.validation[st]; const oe = x.onset_error_min_vs_S2; t.append(el("tr", {}, el("td", { text: st }), el("td", { class: "num", text: x.r2.toFixed(3) }), el("td", { class: "num", text: x.mae.toFixed(3) }), el("td", { class: "num", text: pctu(x.predictive_coverage90) }), el("td", { class: "num", text: oe ? `${oe.SAS > 0 ? "+" : ""}${oe.SAS.toFixed(0)} / ${oe.VLA > 0 ? "+" : ""}${oe.VLA.toFixed(0)} min` : "in sample" }))); }
    root.append(t);
    const dt = E.downtime.cloud_S2; const t2 = el("table", { class: "tbl" }); t2.append(el("tr", {}, ...["Site", "Strike", "Onset", "Full loss", "Damage"].map((h) => el("th", { text: h }))));
    for (const [k, d] of Object.entries(dt)) t2.append(el("tr", {}, el("td", { text: EVN[k] }), el("td", { class: "num", text: d.strike_utc[1].slice(11, 16) }), el("td", { class: "num", text: k === "KAL" ? "n/a" : d.onset_utc[1].slice(11, 16) }), el("td", { class: "num", text: k === "KAL" ? "n/a" : d.full_loss_utc[1].slice(11, 16) }), el("td", { class: "num", text: pctu(d.damage[1]) })));
    root.append(el("hr"), el("div", { class: "lbl", text: "Downtime estimation (S2 posterior medians, UTC)" }), t2);
    const sh = E.stages.cloud_S2.site_share; root.append(el("div", { class: "lbl", style: "margin-top:12px", text: "Share of Yandex Cloud capacity per site (90% interval)" }));
    for (const [k, q] of Object.entries(sh)) if (q[1] > 0.01) root.append(el("div", { class: "note", text: `${k}: ${pctu(q[1])} (${pctu(q[0])} to ${pctu(q[2])})` }));
  }
  function inspTiming(root, sid) {
    const r = TM.results[sid]; if (!r) return;
    root.append(el("h3", { text: r.label }), el("div", { class: "lbl", style: "margin:6px 0" }, "Change-point dip per event ", info("timing")));
    const t = el("table", { class: "tbl" }); t.append(el("tr", {}, ...["Event", "Dip", "Hours", "Start", "p"].map((h) => el("th", { text: h }))));
    for (const [k, e] of Object.entries(r.events)) t.append(el("tr", {}, el("td", { text: EVN[k] }), el("td", { class: "num", text: pct(e.dip_ratio - 1) }), el("td", { class: "num", text: e.dip_hours.toFixed(1) }), el("td", { class: "num", text: `${e.offset_min > 0 ? "+" : ""}${e.offset_min.toFixed(0)}m` }), el("td", { class: "num", text: pv(e.p_scan) })));
    root.append(t, el("p", { class: "note", text: "Start is relative to the measured outage onset. Attribution requires p < 0.05 and a start at or after the onset." }));
  }
  function inspGroup(root, name, o) {
    const w = BY.windows[o.win]; const g = w?.groups[name]; if (!g) return;
    root.append(el("h3", { text: name }), el("div", { class: "note" }, `${o.win.replace("_", " ").replace("SAS", "Sasovo").replace("VLA", "Vladimir").replace("KAL", "Kaluga").replace("SEP27", "27 Sep placebo")}, ${g.k} member series `, info("bayes")));
    root.append(kv([["Posterior median", pct(g.median, 1)], ["90% credible", `${pct(g.ci90[0])} to ${pct(g.ci90[1])}`], ["P(drop > 10%)", pctu(g.p_drop10)], ["Group placebo p", pv(g.placebo_p_drop)], ["Common shock sd", (g.common_shock_sd * 100).toFixed(1) + "%"], ["R-hat", g.rhat.toFixed(3)], ["Credible drop", g.credible_drop ? "yes" : "no"]]));
    const mem = Object.entries(w.members).filter(([, m]) => m.group === name).sort((a, b) => a[1].y - b[1].y);
    const t = el("table", { class: "tbl" }); t.append(el("tr", {}, el("th", { text: "Member" }), el("th", { text: "Change" })));
    for (const [sid, m] of mem) t.append(el("tr", { class: "click", onclick: () => inspect({ type: "series", id: sid }) }, el("td", { text: (SER[sid]?.label || sid) + (m.yandex_mail ? " (Yandex mail)" : "") }), el("td", { class: "num", text: pct(m.y) })));
    root.append(el("div", { class: "lbl", text: "Members (raw window change)" }), t);
  }
  function inspNode(root, id, o) { const n = o.node; root.append(el("h3", { text: n.label }), el("div", { class: "note", text: n.colLabel })); if (n.html) root.append(n.html()); }

  // ------------------------------------------------------------------ left panel
  const ctl = (label, node) => el("div", { class: "ctl" }, label.nodeType ? el("label", {}, label) : el("label", { text: label }), node);
  function seg(vals, cur, on, labels = {}) { const s = el("div", { class: "seg" }); vals.forEach((v) => s.append(el("button", { class: v === cur ? "on" : "", onclick: () => on(v), title: labels[v] || v }, labels[v] || String(v)))); return s; }
  function chk(label, val, on) { const i = el("input", { type: "checkbox" }); i.checked = !!val; i.addEventListener("change", () => on(i.checked)); return el("label", { class: "check" }, i, label); }
  let dT; const debounced = () => { clearTimeout(dT); dT = setTimeout(() => { render(); updateFiltCount(); }, 140); };
  function slider(label, mn, mx, st, val, on, fmt, live) { const out = el("span", { class: "val", text: fmt(val) }); const i = el("input", { type: "range", min: mn, max: mx, step: st, value: val }); i.addEventListener("input", () => { out.textContent = fmt(+i.value); on(+i.value); if (live) debounced(); }); return el("div", { class: "ctl" }, el("label", { text: label }), el("div", { class: "row" }, i, out)); }
  function buildLeft() {
    const L = document.getElementById("left"); L.replaceChildren();
    const sec = (title, open, key, ...kids) => { const d = el("details", { class: "sec" }); d.open = store.get("sec." + title, open); d.addEventListener("toggle", () => store.set("sec." + title, d.open)); const sm = el("summary", {}, title); if (key) sm.append(" ", info(key)); sm.append(el("span", { class: "chev" })); d.append(sm, el("div", { class: "in" }, ...kids)); return d; };
    const gb = (items, cur, on) => { const g = el("div", { class: "grid-btns" }); for (const [k, l] of items) g.append(el("button", { class: k === cur ? "on" : "", onclick: () => on(k), title: l }, l)); return g; };
    L.append(sec("Time window", true, null,
      gb([["full", "Full study"], ["week", "Strike week"], ["sep", "27 Sep"], ["sas", "Sasovo ±24h"], ["kal", "Kaluga ±24h"], ["vla", "Vladimir ±24h"]], S.preset, setPreset),
      ctl("Resolution", seg(["10m", "1h", "6h"], S.res, (v) => { S.res = v; buildLeft(); render(); }, { "10m": "10 min", "1h": "1 hour", "6h": "6 hours" })),
      ctl("Clock", seg(["UTC", "MSK"], S.tz, (v) => { S.tz = v; buildLeft(); render(); renderInspector(); })),
      el("div", { class: "hint", text: "10 minute resolution applies to the outage function, IODA and timing streams. Shift-click a chart to zoom to ±12 h." })));
    const eb = [
      ctl("Target", seg(["cloud", "core"], S.eof.target, (v) => { S.eof.target = v; if (v === "core" && S.eof.stage === "S2") S.eof.stage = "S1"; S.eof.custom = null; buildLeft(); render(); }, { cloud: "Yandex Cloud", core: "Yandex LLC" })),
      ctl(el("span", {}, "Stage ", info("stages")), seg(S.eof.target === "cloud" ? ["S0", "S1", "S2", "custom"] : ["S0", "S1", "custom"], S.eof.stage, (v) => { S.eof.stage = v; if (v === "custom" && !S.eof.custom) runCustom(); buildLeft(); render(); }, { S0: "Prior", S1: "OSINT", S2: "Fused", custom: "What-if" })),
      chk("Uncertainty bands (50 and 90%)", S.eof.bands, (v) => { S.eof.bands = v; render(); }),
      chk("Posterior sample paths", S.eof.traj, (v) => { S.eof.traj = v; render(); }),
      chk("Overlay measured outage (IODA)", S.eof.ioda, (v) => { S.eof.ioda = v; render(); }),
    ];
    if (S.eof.stage === "custom") {
      const o = S.eof.opts;
      eb.push(slider("Damage severity", 0.3, 2, 0.05, o.damageScale, (v) => { o.damageScale = v; }, (v) => v.toFixed(2) + "x"), slider("Recovery time", 0.1, 3, 0.05, o.recoveryMult, (v) => { o.recoveryMult = v; }, (v) => v.toFixed(2) + "x"),
        slider("Strike to outage lag", 5, 180, 5, o.lagMean, (v) => { o.lagMean = v; }, (v) => v + " min"), slider("Failure ramp", 5, 180, 5, o.rampMean, (v) => { o.rampMean = v; }, (v) => v + " min"),
        slider("Site share concentration", 1, 60, 1, o.concentration, (v) => { o.concentration = v; }, (v) => v.toFixed(0)), slider("Derivative source discount", 0, 1, 0.05, o.derivative, (v) => { o.derivative = v; }, (v) => v.toFixed(2)),
        chk("Weight strikes by Admiralty credibility", o.credibility, (v) => { o.credibility = v; }),
        ctl("Strikes included", gb([["SAS", "Sasovo"], ["KAL", "Kaluga"], ["VLA", "Vladimir"]].map(([k, l]) => [k, (o.events[k] ? "✓ " : "") + l]), null, (k) => { o.events[k] = !o.events[k]; buildLeft(); })),
        el("button", { class: "btn primary", onclick: () => { runCustom(); buildLeft(); render(); } }, "Recompute"));
      if (S.eof.custom) eb.push(el("div", { class: "hint", text: `${S.eof.opts.n} draws, effective sample size ${S.eof.custom.ess.toFixed(0)}.` }));
    }
    eb.push(el("button", { class: "btn sm", onclick: () => inspect({ type: "eof" }) }, "Validation and downtime"));
    L.append(sec("Expected outage function", true, "eof", ...eb));
    L.append(sec("Display", true, null,
      ctl(el("span", {}, "Theme ", info("theme")), seg(["all", "war", "other", "diff"], S.theme, (v) => { S.theme = v; if (v === "diff") S.norm = "anom"; buildLeft(); render(); }, { all: "All", war: "War", other: "Non-war", diff: "War vs other" })),
      ctl(el("span", {}, "Normalisation ", info("counterfactual")), seg(["index", "anom", "z", "raw"], S.norm, (v) => { S.norm = v; buildLeft(); render(); }, { index: "Obs/exp", anom: "% dev.", z: "z-score", raw: "Raw" })),
      ...Object.entries({ eof: "Expected outage", infrastructure: "Infrastructure", services: "Dependent services", io: "IO output", control: "Controls" }).map(([k, l]) => chk(l + " panel", S.layersOn[k], (v) => { S.layersOn[k] = v; render(); }))));
    L.append(sec("Series", false, null, seriesPicker()));
    L.append(sec("Uncertainty filter", true, "mde",
      slider("Hide series that cannot detect a drop of", 0.05, 1, 0.05, S.unc.maxMDE, (v) => { S.unc.maxMDE = v; }, (v) => Math.round(v * 100) + "%", true),
      slider("Minimum completeness", 0, 1, 0.05, S.unc.minCompl, (v) => { S.unc.minCompl = v; }, (v) => Math.round(v * 100) + "%", true),
      slider("Grey out outage where 90% band exceeds", 0.05, 1, 0.05, S.unc.bandMax, (v) => { S.unc.bandMax = v; }, (v) => Math.round(v * 100) + " pts", true),
      ctl(el("span", {}, "Minimum source grade ", info("admiralty")), seg(["A", "B", "C", "D", "F"], S.unc.minRel, (v) => { S.unc.minRel = v; buildLeft(); render(); })),
      chk("Hide inconclusive estimates", S.unc.hideInconclusive, (v) => { S.unc.hideInconclusive = v; render(); buildLeft(); }),
      el("div", { class: "hint", id: "filtcount" })));
    L.append(sec("Annotations", false, null, ...[["strike", "Strikes"], ["statement", "Official statements"], ["telemetry", "Telemetry reports"], ["claim", "Viral claims"], ["confounder", "Confounders and placebo"], ["firms", "NASA FIRMS fire detections"], ["alerts", "Complaint alerts naming Yandex"]].map(([k, l]) => chk(l, S.ann[k], (v) => { S.ann[k] = v; render(); }))));
    updateFiltCount();
  }
  function updateFiltCount() { const n = Object.keys(SER).filter((id) => SER[id].stats); const f = n.filter((id) => !seriesPasses(id)).length; const e = document.getElementById("filtcount"); if (e) e.textContent = `${f} of ${n.length} analysed series filtered out.`; }
  function seriesPicker() {
    const wrap = el("div", { class: "ctl" }); const q = el("input", { class: "search", placeholder: "Search series", value: S.search }); const list = el("div", { class: "serieslist" });
    const fill = () => {
      list.replaceChildren();
      const groups = d3.group(Object.entries(SER).filter(([id, s]) => ["infrastructure", "services", "io", "control"].includes(s.layer) && (!S.search || (s.label + id).toLowerCase().includes(S.search.toLowerCase()))), ([, s]) => s.group);
      for (const [g, items] of [...groups].sort()) {
        list.append(el("div", { class: "grp", text: g }));
        for (const [id, s] of items) {
          const panel = s.layer; const on = S.sel[panel].includes(id); const ok = seriesPasses(id);
          const i = el("input", { type: "checkbox" }); i.checked = on; i.disabled = !ok && !on;
          i.addEventListener("change", () => { const arr = S.sel[panel]; if (i.checked) { if (arr.length >= 8) { i.checked = false; return; } arr.push(id); } else arr.splice(arr.indexOf(id), 1); render(); fill(); });
          list.append(el("label", { class: "check", title: ok ? s.method || "" : `Filtered: ${failReason(id)}` }, i, el("span", { class: "swatch", style: on ? `background:${colorFor(panel, id)}` : "" }), el("span", { style: ok ? "" : "color:var(--ink-3)", text: s.label + (ok ? "" : ` (${failReason(id)})`) })));
        }
      }
    };
    q.addEventListener("input", () => { S.search = q.value; fill(); }); fill();
    wrap.append(q, list, el("div", { class: "hint", text: "Up to 8 series per panel; a series keeps its colour while selected." }));
    return wrap;
  }
  function setPreset(k) { S.preset = k; const around = (t, h = 24) => [new Date(+t - h * HOUR), new Date(+t + h * HOUR)]; S.win = { full: [new Date(H0), new Date(STUDY_END)], week: [new Date("2026-10-05T00:00:00Z"), new Date(STUDY_END)], sas: around(ONSETS.SAS), vla: around(ONSETS.VLA), kal: around(ONSETS.KAL), sep: around(ONSETS.SEP27, 36) }[k]; buildLeft(); render(); }
  function setWindow(w, p) { S.win = w; S.preset = p; buildLeft(); render(); }

  // ------------------------------------------------------------------ views
  const VIEWS = [["overview", "Overview"], ["graph", "Attribution graph"], ["timeline", "Timeline"], ["timing", "Timing lab"], ["effects", "Effects"], ["eventstudy", "Event study"], ["evidence", "Evidence"], ["method", "Method"]];
  function go(v) { S.view = v; store.set("view", v); buildTabs(); render(); document.getElementById("mainwrap").scrollTop = 0; }
  function buildTabs() { const T = document.getElementById("tabs"); T.replaceChildren(); for (const [k, l] of VIEWS) T.append(el("button", { class: S.view === k ? "on" : "", onclick: () => go(k) }, l)); }
  function render() { charts.length = 0; hideTip(); const M = document.getElementById("main"); M.replaceChildren(); ({ overview: vOverview, graph: vGraph, timeline: vTimeline, timing: vTiming, effects: vEffects, eventstudy: vEventStudy, evidence: vEvidence, method: vMethod }[S.view] || vOverview)(M); }
  let rT; function rerender() { clearTimeout(rT); rT = setTimeout(render, 60); }
  const header = (M, title, desc, key) => M.append(el("div", { class: "view-h" }, el("h2", {}, title, key ? " " : "", key ? info(key) : null), desc ? el("div", { class: "desc", text: desc }) : null));
  function card(M, title, cap, key) { const c = el("div", { class: "card" }); if (title) c.append(el("div", { class: "card-h" }, el("div", {}, el("h3", {}, title, key ? " " : "", key ? info(key) : null), cap ? el("div", { class: "cap", text: cap }) : null))); M.append(c); return c; }
  function wavesSVG() { const s = document.createElementNS("http://www.w3.org/2000/svg", "svg"); s.setAttribute("class", "waves"); s.setAttribute("viewBox", "0 0 1200 200"); s.setAttribute("preserveAspectRatio", "none"); s.innerHTML = '<path d="M0 140 C 200 90, 400 190, 600 130 S 1000 70, 1200 120 L1200 200 L0 200Z" fill="rgba(255,255,255,0.10)"/><path d="M0 165 C 250 120, 450 210, 700 160 S 1050 110, 1200 150 L1200 200 L0 200Z" fill="rgba(255,255,255,0.08)"/><path d="M0 110 C 300 60, 500 160, 800 100 S 1100 40, 1200 80" stroke="rgba(255,255,255,0.25)" fill="none" stroke-width="1.5"/>'; return s; }

  // ---- overview
  function vOverview(M) {
    const pr = TM.results["pravda.total"].events.VLA; const bw = BY.windows;
    const hero = el("div", { class: "hero" }); hero.append(wavesSVG());
    hero.append(el("div", { class: "k", text: "Answer" }), el("h2", { text: "No broad reduction in Russian information operations. One automated pipeline, the Pravda network, stalled for 11 hours after the Vladimir strike." }),
      el("p", { text: `The strikes knocked out 78% of Yandex Cloud's reachable capacity, and open sources alone reconstruct the outage to within minutes. Across ${Object.keys(bw.VLA_24h.members).length} individual channels, languages, communities and websites on Telegram, Reddit and the web, only the Pravda network shows a drop that is time-locked to an outage.` }));
    const vd = el("div", { class: "verd" });
    const chipv = (c, t, on) => vd.append(el("span", { class: "vchip", onclick: on }, el("i", { style: `background:${c}` }), t));
    chipv(css("--critical"), `Effect seen: Pravda network ${pct(pr.dip_ratio - 1)} for ${pr.dip_hours.toFixed(0)} h`, () => { S.tStream = "pravda.total"; S.tEvent = "VLA"; go("timing"); });
    chipv(css("--good"), "No effect: Telegram, Reddit, web outlets", () => go("effects"));
    chipv("#ffffff", "The viral 'bot collapse' chart measured Yandex's crawler", () => inspect({ type: "event", id: "EV-CLAIM-CHART" }));
    hero.append(vd); M.append(hero);
    const kp = el("div", { class: "kpis" });
    const kpi = (l, key, v, d, on) => kp.append(el("div", { class: "kpi", onclick: on }, el("div", { class: "k-l" }, l, key ? " " : "", key ? info(key) : null), el("div", { class: "k-v", text: v }), el("div", { class: "k-d", text: d })));
    const ioNow = E.ioda_obs.filter((x) => x != null).slice(-12);
    kpi("Yandex Cloud offline now", "ioda", pctu(d3.mean(ioNow)), "Measured by IODA; no recovery since 11 Oct", () => go("timeline"));
    kpi("Open-source timing error", "stages", `${Math.abs(E.validation.S1.onset_error_min_vs_S2.SAS).toFixed(0)} and ${Math.abs(E.validation.S1.onset_error_min_vs_S2.VLA).toFixed(0)} min`, "Onset from published sources only vs measured (Sasovo, Vladimir)", () => inspect({ type: "eof" }));
    kpi("Pravda network after Vladimir", "pravda", pct(pr.dip_ratio - 1), `${pr.dip_hours.toFixed(1)} h dip starting ${pr.offset_min.toFixed(0)} min after the outage (p ${pv(pr.p_scan)})`, () => { S.tStream = "pravda.total"; S.tEvent = "VLA"; go("timing"); });
    const io = bw.VLA_24h.io_minus_control;
    kpi("IO output relative to controls", "bayes", pct(io.median), `24 h after Vladimir (Bayesian, 90% ${pct(io.ci90[0])} to ${pct(io.ci90[1])}); ${io.median > 0 ? "up with strike news, not down" : "no drop"}`, () => go("effects"));
    M.append(kp);
    const sp = el("div", { class: "split" }); M.append(sp);
    const c1 = el("div", { class: "card", style: "margin:0" }); sp.append(c1);
    c1.append(el("div", { class: "card-h" }, el("div", {}, el("h3", {}, "Where is an effect seen? ", info("bayes")), el("div", { class: "cap", text: "Bayesian posterior change per platform group in the hours after each strike. A red outline marks a credible drop. Click a cell to see its members." }))));
    effectMap(c1);
    const c2 = el("div", { class: "card", style: "margin:0" }); sp.append(c2);
    c2.append(el("div", { class: "card-h" }, el("div", {}, el("h3", {}, "The one time-locked disruption ", info("timing")), el("div", { class: "cap", text: "Pravda network output relative to its seasonal expectation (top) against the measured Yandex Cloud outage (bottom), 10 to 12 Oct UTC." }))));
    const b1 = el("div", { class: "chart" }), b2 = el("div", { class: "chart" }); c2.append(b1, b2);
    requestAnimationFrame(() => {
      const w = [new Date("2026-10-10T12:00:00Z"), new Date("2026-10-12T00:00:00Z")]; const t = TM.series["pravda.total"]; const t0 = Date.parse(TM.t0);
      const xs = t.obs.map((_, j) => new Date(t0 + j * MIN10)); const roll = (a) => a.map((_, i) => d3.sum(a.slice(Math.max(0, i - 5), i + 1)));
      const o6 = roll(t.obs), e6 = roll(t.exp);
      timeChart(b1, { win: w, title: "Pravda output, % of expected (1 h rolling)", series: [{ label: "Pravda output", color: css("--s3"), xs, ys: o6.map((v, i) => (100 * v) / e6[i]), width: 1.8, id: "pravda.total" }], refLine: 100, height: 180, yFmt: (v) => v, tipFmt: (v) => v.toFixed(0) + "%", shades: [[new Date(pr.tau1_map), new Date(pr.tau2_map), css("--band")]], marks: [{ t: ONSETS.VLA, text: "outage onset" }], events: false, legend: false });
      const io2 = iodaSeries(true);
      timeChart(b2, { win: w, title: "Yandex Cloud offline (IODA)", series: [{ label: "Offline share", color: css("--s2"), xs: io2.xs, ys: io2.ys, width: 1.8 }], yDomain: [0, 100], height: 130, yFmt: (v) => v + "%", tipFmt: (v) => v.toFixed(0) + "%", events: false, legend: false, marks: [{ t: ONSETS.VLA, text: "" }] });
    });
    M.append(el("div", { style: "height:16px" }));
    const jc = card(M, "Key judgments", "Estimative probability per ICD 203.", "icd");
    const J = [
      ["Almost certain", 0.97, "The strikes on Sasovo (night of 7 to 8 Oct) and Vladimir (11 Oct) knocked out about 38% and 53% of Yandex Cloud's reachable capacity; reachability fell to 22% of normal with no recovery by 13 Oct 12:00 UTC. Kaluga left no measurable cloud signature.", "Status pages, IODA, NetBlocks, Cloudflare and NASA FIRMS agree within minutes."],
      ["Likely", 0.7, `The Pravda network's publishing pipeline depended on infrastructure lost at Vladimir: output fell to ${Math.round(pr.dip_ratio * 100)}% of expected for ${pr.dip_hours.toFixed(0)} h, starting ${pr.offset_min.toFixed(0)} min after the outage, while its upstream Telegram sources did not dip.`, "Tight timing and placebo p 0.002; no Sasovo replication; hosting hidden behind Cloudflare."],
      ["Very unlikely", 0.1, "The strikes caused a broad reduction of Russian influence-operation output ('the bots went silent'). State, military-blogger, tabloid and foreign-audience Telegram channels, Yandex-mail-dependent outlets, the RIA web outlet ukraina.ru and Reddit communities show no credible drop.", "Coverage of X, VK and closed bot infrastructure is missing."],
      ["Almost certain", 0.97, "The viral 'Russian bot traffic collapsed' chart counted automated web requests from Yandex's own network, dominated by its search crawler, which stops when its data centers go dark.", "Metric definition and timing match the outage exactly."],
    ];
    const jg = el("div", { class: "judg" }); for (const [p, v, t, c] of J) jg.append(el("div", { class: "prob" }, p, el("div", { class: "bar" }, el("i", { style: `width:${v * 100}%` }))), el("div", {}, el("p", { text: t }), el("div", { class: "conf", text: c })));
    jc.append(jg);
    const cc = card(M, "Causal chain under test", "Strength of evidence per link. Red marks the only link where an IO effect is established.");
    const links = [["Strike", "Drones hit Sasovo, Kaluga, Vladimir", 5, "event", "EV-SAS-STRIKE"], ["Power and fire", "Status page 22:31, FIRMS 22:40 UTC", 5, "event", "EV-SAS-FIRMS"], ["Capacity loss", "Yandex Cloud -34% then -78%", 5, "series", "ioda.asn.200350.ping-slash24"], ["Dependent services", "Pay, Go, KinoPoisk; ru.wikipedia -7%", 4, "series", "wiki.ru.wikipedia.user"], ["Automated IO", `Pravda ${pct(pr.dip_ratio - 1)} for ${pr.dip_hours.toFixed(0)} h`, 3, "timing", "pravda.total"], ["Social-media IO", "No credible drop", 1, "series", "tg.prokremlin.war"]];
    const fl = el("div", { class: "flow" });
    for (const [t, d, s, ty, id] of links) { const st = el("span", { class: "strength" }); for (let i = 1; i <= 5; i++) st.append(el("i", { class: i <= s ? "on" : "" })); fl.append(el("div", { class: "node" + (t === "Automated IO" ? " hit" : ""), onclick: () => inspect({ type: ty, id }) }, el("div", { class: "t", text: t }), el("div", { class: "d", text: d }), el("div", { class: "s" }, st, ["", "none", "weak", "moderate", "strong", "conclusive"][s]))); }
    cc.append(fl);
  }
  function effectMap(box) {
    const cols = [["SAS_6h", "Sasovo 6 h"], ["SAS_24h", "Sasovo 24 h"], ["VLA_6h", "Vladimir 6 h"], ["VLA_24h", "Vladimir 24 h"], ["SEP27_24h", "Placebo"]];
    const col = d3.scaleLinear().domain([-0.4, 0, 0.4]).range([css("--div-neg"), css("--div-mid"), css("--div-pos")]).clamp(true);
    const t = el("table", { class: "emap" });
    t.append(el("tr", {}, el("th", { class: "rowh", text: "Platform group" }), ...cols.map(([, l]) => el("th", { text: l }))));
    const order = BY.groups.slice().sort((a, b) => (a.startsWith("Control") - b.startsWith("Control")) || a.localeCompare(b));
    let sep = false;
    for (const g of order) {
      if (g.startsWith("Control") && !sep) { sep = true; t.append(el("tr", { class: "sep" }, el("td", { class: "lab", text: "Controls" }))); }
      const k = BY.windows.VLA_24h.groups[g]?.k;
      const tr = el("tr", {}, el("td", { class: "lab" }, g.replace("Control: ", ""), el("span", { class: "sub", text: k ? `n=${k}` : "" })));
      for (const [w] of cols) {
        const r = BY.windows[w]?.groups[g];
        if (!r) { tr.append(el("td", { class: "cell" })); continue; }
        const c = col(r.median); const lum = d3.hsl(c).l;
        const td = el("td", { class: "cell" + (r.credible_drop ? " cred" : ""), style: `background:${c};color:${lum < 0.55 ? "#fff" : "#0b0b0b"}`, text: pct(r.median) + (r.credible_drop ? " ▼" : ""), onclick: (ev) => { ev.stopPropagation(); inspect({ type: "group", id: g, win: w }); } });
        td.addEventListener("mousemove", (ev) => showTip(ev, `${g}, ${w.replace("_", " ")}`, [{ label: "Posterior median", value: pct(r.median, 1) }, { label: "90% credible", value: `${pct(r.ci90[0])} to ${pct(r.ci90[1])}` }, { label: "P(drop > 10%)", value: pctu(r.p_drop10) }, { label: "Group placebo p", value: pv(r.placebo_p_drop) }]));
        td.addEventListener("mouseleave", hideTip); tr.append(td);
      }
      t.append(tr);
    }
    box.append(t, el("div", { class: "scale" }, "-40%", el("span", { class: "bar", style: `background:linear-gradient(90deg, ${css("--div-neg")}, ${css("--div-mid")}, ${css("--div-pos")})` }), "+40%", el("span", { style: "margin-left:12px" }, "▼ red outline: credible drop")));
  }

  // ---- attribution graph
  function buildGraph() {
    const nodes = [], edges = [];
    const N = (id, col, label, kind, extra = {}) => nodes.push({ id, col, label, kind, ...extra });
    const cols = ["Sources", "Observations", "Outage", "Exposure channel", "Platform", "Finding"];
    for (const s of EV.sources) if (EV.events.some((e) => e.sources.includes(s.id))) N(s.id, 0, s.name.replace("Yandex Cloud status page, ", "Status page ").replace("Yandex official Telegram, ", "Yandex TG "), "source", { rel: s.rel, ref: { type: "source", id: s.id } });
    for (const e of EV.events.slice().sort((a, b) => Date.parse(a.t) - Date.parse(b.t))) { N(e.id, 1, `${e.t.slice(8, 10)}/${e.t.slice(5, 7)} ${e.t.slice(11, 16)} ${e.title}`, e.kind, { ref: { type: "event", id: e.id } }); for (const s of e.sources) edges.push([s, e.id, 1]); }
    for (const [k, l] of Object.entries({ SAS: "Sasovo outage", KAL: "Kaluga strike", VLA: "Vladimir outage", SEP: "27 Sep dip, no strike" })) N("site." + k, 2, l, "site", { ref: k === "SEP" ? { type: "event", id: "EV-SEP27" } : { type: "eof" } });
    for (const e of EV.events) { const k = { Sasovo: "SAS", Kaluga: "KAL", Vladimir: "VLA" }[e.site]; if (k) edges.push([e.id, "site." + k, 1]); if (e.id === "EV-SEP27") edges.push([e.id, "site.SEP", 1]); }
    for (const [id, l, sub] of [["exp.cloud", "Yandex Cloud capacity", "-78% measured"], ["exp.consumer", "Yandex consumer services", "Pay, Go, Search"], ["exp.mail", "Yandex 360 mail", "7 IO outlets"], ["exp.none", "No Yandex dependency", "per DNS"]]) N(id, 3, l, "exposure", { sub });
    edges.push(["site.SAS", "exp.cloud", 3], ["site.VLA", "exp.cloud", 3], ["site.KAL", "exp.cloud", 0.3], ["site.SAS", "exp.consumer", 2], ["site.VLA", "exp.consumer", 3], ["site.VLA", "exp.mail", 1], ["site.SAS", "exp.mail", 1], ["site.SEP", "exp.cloud", 1]);
    const g24 = BY.windows.VLA_24h.groups;
    const plat = [["pl.pravda", "Pravda network", "Pravda network (automated web)", ["exp.cloud"]], ["pl.state", "Telegram: state media", "Telegram: state media", ["exp.none"]], ["pl.milb", "Telegram: military bloggers", "Telegram: military bloggers", ["exp.none", "exp.mail"]], ["pl.tab", "Telegram: tabloids", "Telegram: pro-Kremlin tabloids", ["exp.none"]], ["pl.fio", "Telegram: foreign-audience IO", "Telegram: foreign-audience IO", ["exp.none", "exp.mail"]], ["pl.web", "Web: ukraina.ru (RIA)", "Web: state IO outlet", ["exp.none"]], ["pl.rw", "Reddit: war communities", "Reddit: Ukraine war communities", ["exp.none"]], ["pl.rp", "Reddit: political", "Reddit: political communities", ["exp.none"]], ["pl.wiki", "ru.wikipedia users", null, ["exp.consumer"]]];
    for (const [id, l, gname, ex] of plat) {
      const effect = id === "pl.pravda" ? TM.results["pravda.total"].events.VLA.dip_ratio - 1 : id === "pl.wiki" ? SER["wiki.ru.wikipedia.user"]?.stats?.windows?.VLA_24h?.effect : g24[gname]?.median;
      N(id, 4, l, "platform", { effect, ref: gname ? { type: "group", id: gname, win: id === "pl.pravda" ? "VLA_6h" : "VLA_24h" } : { type: "series", id: "wiki.ru.wikipedia.user" } });
      for (const e of ex) edges.push([e, id, e === "exp.none" ? 0.5 : 1.5]);
    }
    N("f.drop", 5, "Time-locked drop", "finding", { color: "--critical" }); N("f.small", 5, "Small service-level drop", "finding", { color: "--s4" }); N("f.none", 5, "No credible drop", "finding", { color: "--good" });
    for (const [id] of plat) edges.push([id, id === "pl.pravda" ? "f.drop" : id === "pl.wiki" ? "f.small" : "f.none", id === "pl.pravda" ? 3 : 1]);
    return { nodes, edges, cols };
  }
  function vGraph(M) {
    header(M, "Attribution graph: from sources to findings", "Every finding traces back to graded sources: dated observations, the outage estimate for each site, the channel through which Yandex could matter, and the measured platform outcome. Click a node to highlight its upstream evidence and downstream consequences; the inspector explains it.", "admiralty");
    const G = buildGraph();
    const tools = el("div", { class: "ag-tools" }); const crumbs = el("div", { class: "ag-crumbs" });
    const c = card(M); c.append(tools, crumbs); const box = el("div", { class: "chart", style: "overflow-x:auto" }); c.append(box);
    c.append(el("div", { class: "legend" }, ...[["--seq-5", "Source grade A"], ["--seq-4", "Grade B"], ["--seq-3", "Grade C"], ["--critical", "Strike, outage or effect"], ["--s3", "Telemetry"], ["--s4", "Confounder"], ["--s7", "Claim"], ["--good", "No effect"]].map(([v, l]) => el("span", {}, el("span", { class: "swatch", style: `background:${css(v)};height:8px;width:8px;border-radius:2px` }), l))));
    requestAnimationFrame(() => {
      const W = Math.max(760, box.clientWidth || 1100), nodeW = Math.min(196, (W - 5 * 26 - 8) / 6), nodeH = 22;
      const colX = (i) => 4 + i * ((W - 8 - nodeW) / 5);
      const byCol = d3.group(G.nodes, (n) => n.col); const maxN = d3.max([...byCol.values()].map((a) => a.length));
      const H = 36 + maxN * (nodeH + 5);
      for (const [ci, arr] of byCol) { const gap = (H - 36) / arr.length; arr.forEach((n, i) => { n.x = colX(ci); n.y = 30 + i * gap + (gap - nodeH) / 2; }); }
      const idx = Object.fromEntries(G.nodes.map((n) => [n.id, n]));
      const svg = d3.select(box).append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("height", H).style("min-width", W + "px");
      G.cols.forEach((l, i) => svg.append("text").attr("class", "ag-col").attr("x", colX(i)).attr("y", 14).text(l));
      const eg = svg.append("g"), ng = svg.append("g");
      const edgeSel = eg.selectAll("path").data(G.edges.filter(([a, b]) => idx[a] && idx[b])).join("path").attr("class", "ag-edge")
        .attr("d", ([a, b]) => { const A = idx[a], B = idx[b]; const x1 = A.x + nodeW, y1 = A.y + nodeH / 2, x2 = B.x, y2 = B.y + nodeH / 2; const mx = (x1 + x2) / 2; return `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`; })
        .attr("stroke", ([a, b]) => (b === "pl.pravda" || a === "pl.pravda" || (a === "exp.cloud" && b === "pl.pravda") ? css("--critical") : css("--axis"))).attr("stroke-width", ([, , w]) => 0.6 + w * 0.6).attr("opacity", 0.7);
      const relC = { A: "--seq-5", B: "--seq-4", C: "--seq-3", D: "--seq-2", E: "--seq-1", F: "--ink-3" };
      const kindC = { strike: "--critical", statement: "--ink-2", telemetry: "--s3", confounder: "--s4", claim: "--s7", site: "--critical", exposure: "--s1" };
      const maxc = Math.max(8, Math.floor((nodeW - 14) / 6.1));
      const nodeSel = ng.selectAll("g").data(G.nodes).join("g").attr("class", "ag-node").attr("transform", (n) => `translate(${n.x},${n.y})`)
        .on("click", (ev, n) => { ev.stopPropagation(); focusNode(n.id); })
        .on("mousemove", (ev, n) => showTip(ev, G.cols[n.col], [{ label: n.label, value: n.effect != null ? pct(n.effect) : n.rel ? "grade " + n.rel : n.sub || "" }])).on("mouseleave", hideTip);
      nodeSel.append("rect").attr("width", nodeW).attr("height", nodeH).attr("rx", 6).attr("fill", css("--surface-2")).attr("stroke", css("--border"));
      nodeSel.append("rect").attr("width", 4).attr("height", nodeH).attr("rx", 2).attr("fill", (n) => css(n.kind === "source" ? relC[n.rel] : n.kind === "finding" ? n.color : n.kind === "platform" ? (n.id === "pl.pravda" ? "--critical" : n.id === "pl.wiki" ? "--s4" : "--good") : kindC[n.kind] || "--ink-3"));
      const hasEff = (n) => n.effect != null;
      nodeSel.append("text").attr("x", 10).attr("y", 15).text((n) => { const mc = hasEff(n) ? maxc - 6 : maxc; return n.label.length > mc ? n.label.slice(0, mc - 1) + "…" : n.label; });
      nodeSel.filter(hasEff).append("text").attr("x", nodeW - 6).attr("y", 15).attr("text-anchor", "end").attr("font-weight", 650).text((n) => pct(n.effect));
      const up = (id, acc = new Set()) => { for (const [a, b] of G.edges) if (b === id && !acc.has(a)) { acc.add(a); up(a, acc); } return acc; };
      const down = (id, acc = new Set()) => { for (const [a, b] of G.edges) if (a === id && !acc.has(b)) { acc.add(b); down(b, acc); } return acc; };
      function focusNode(id) {
        S.agFocus = id;
        if (!id || !idx[id]) { nodeSel.attr("opacity", 1); edgeSel.attr("opacity", 0.7); crumbs.replaceChildren(el("span", { class: "muted", text: "Select a node, or use a shortcut above, to trace an evidence path." })); return; }
        const keep = new Set([id, ...up(id), ...down(id)]);
        nodeSel.attr("opacity", (n) => (keep.has(n.id) ? 1 : 0.12)); edgeSel.attr("opacity", ([a, b]) => (keep.has(a) && keep.has(b) ? 0.95 : 0.05));
        const path = [...keep].map((k) => idx[k]).filter(Boolean);
        crumbs.replaceChildren(...G.cols.map((cl, i) => { const ns = path.filter((p) => p.col === i); return ns.length ? el("span", {}, el("b", { text: cl + " " }), ...ns.slice(0, 2).map((p) => el("span", { class: "c", onclick: () => focusNode(p.id), text: p.label.slice(0, 26) })), ns.length > 2 ? ` +${ns.length - 2}` : "", i < 5 ? "  ›" : "") : null; }).filter(Boolean));
        const n = idx[id];
        if (n.ref) inspect(n.ref); else inspect({ type: "node", id: n.id, node: { ...n, colLabel: G.cols[n.col], html: () => el("p", { class: "note", text: GRAPHTXT[n.id] || n.label }) } });
      }
      tools.append(el("button", { class: "btn sm", onclick: () => focusNode("pl.pravda") }, "Trace the Pravda effect"), el("button", { class: "btn sm", onclick: () => focusNode("site.VLA") }, "Trace the Vladimir outage"), el("button", { class: "btn sm", onclick: () => focusNode("exp.mail") }, "Trace Yandex 360 dependency"), el("button", { class: "btn sm", onclick: () => focusNode("pl.fio") }, "Trace foreign-audience IO"), el("button", { class: "btn sm ghost", onclick: () => focusNode(null) }, "Reset"));
      svg.on("click", () => focusNode(null));
      focusNode(S.agFocus);
    });
  }
  const GRAPHTXT = {
    "exp.cloud": "Loss of Yandex Cloud compute and network capacity, measured by IODA active probing: 34% after Sasovo, 78% after Vladimir, none after Kaluga. Any IO pipeline running on Yandex Cloud would be exposed.",
    "exp.consumer": "Yandex consumer services (Search, Pay, Go, Alice, KinoPoisk) were disrupted, shown by complaint alerts, Yandex statements and a 7% drop in Russian Wikipedia visits.",
    "exp.mail": "DNS MX records show seven IO and state outlets using Yandex 360 mail: rt.com, vz.ru, readovka.news, rybar.ru, strategic-culture.su, topcor.ru and eadaily.com. Their Telegram output is tested as a separate stratum; it shows no extra effect.",
    "exp.none": "No IO website resolves to a Yandex network. Pravda sites sit behind Cloudflare; state media use their own or other Russian hosting.",
    "f.drop": "Only the Pravda network shows a significant dip that starts after the outage onset (p 0.002), with partial backlog catch-up.",
    "f.small": "Consumer-level effects such as fewer Russian Wikipedia visits are consistent with Yandex Search and app disruption.",
    "f.none": "All other platform groups show no credible drop; most rule out drops larger than 20%.",
  };

  // ---- timeline
  function vTimeline(M) {
    header(M, "Timeline: expected outage against measured outage and output", "Synchronised panels share the time axis and crosshair. Output series are relative to their seasonal counterfactual (100 = expected) unless another normalisation is chosen in Controls. Shaded: post-strike period.", "counterfactual");
    if (S.layersOn.eof) { const c = card(M); const b = el("div", { class: "chart" }); c.append(b); requestAnimationFrame(() => eofChart(b)); }
    for (const [k, t] of [["infrastructure", "Infrastructure telemetry"], ["services", "Dependent services"], ["io", "Information-operation output"], ["control", "Controls"]]) {
      if (!S.layersOn[k]) continue;
      const ids = S.sel[k].filter((id) => SER[id] && seriesPasses(themed(id)));
      const c = card(M); const b = el("div", { class: "chart" }); c.append(b);
      if (!ids.length) { c.append(el("div", { class: "hint", text: `${t}: no series selected (Controls › Series) or all filtered by the uncertainty filter.` })); continue; }
      requestAnimationFrame(() => {
        const series = ids.map((id) => { const d = seriesXY(id); return { id, label: SER[themed(id)].label, color: colorFor(k, id), xs: d.xs, ys: d.ys, unit: d.unit }; });
        if (S.res === "10m") for (const id of ids.filter((x) => TM.series[x])) { const s = TM.series[id]; const t0 = Date.parse(TM.t0); const k6 = (a, i) => d3.sum(a.slice(Math.max(0, i - 5), i + 1)); const ser = series.find((x) => x.id === id); ser.xs = s.obs.map((_, j) => new Date(t0 + j * MIN10)); ser.ys = s.obs.map((_, i) => (100 * k6(s.obs, i)) / k6(s.exp, i)); }
        timeChart(b, { title: t, unit: series[0].unit, series, height: 200, refLine: S.norm === "index" ? 100 : S.norm === "raw" ? null : 0, shadePost: true });
      });
    }
  }

  // ---- timing lab
  function vTiming(M) {
    header(M, "Timing lab: does output dip exactly when Yandex goes dark?", "A dip caused by the outage must start at or shortly after the measured onset. Each stream is scanned with a 10-minute change-point model and calibrated against 400 placebo origins.", "timing");
    const ctlc = card(M);
    const ss = el("select", { class: "sel" }); for (const [k, r] of Object.entries(TM.results)) { const o = el("option", { value: k, text: r.label }); if (k === S.tStream) o.selected = true; ss.append(o); } ss.addEventListener("change", () => { S.tStream = ss.value; render(); });
    const evs = el("div", { class: "seg inline" }); for (const k of ["SAS", "KAL", "VLA"]) evs.append(el("button", { class: S.tEvent === k ? "on" : "", onclick: () => { S.tEvent = k; render(); } }, EVN[k]));
    ctlc.append(el("div", { style: "display:flex;gap:14px;flex-wrap:wrap;align-items:center" }, el("span", { class: "lbl", text: "Event" }), evs, el("span", { class: "lbl", text: "Stream" }), ss, info("backlog")));
    const r = TM.results[S.tStream], e = r.events[S.tEvent], on = ONSETS[S.tEvent];
    const ok = e.p_scan < 0.05 && e.offset_min >= -30;
    const c1 = card(M, `${r.label}: ${EVN[S.tEvent]} (onset ${fmtT(on)})`, `${ok ? "Time-locked dip" : "No time-locked dip"}. Most likely dip ${pct(e.dip_ratio - 1)} over ${e.dip_hours.toFixed(1)} h, starting ${e.offset_min > 0 ? "+" : ""}${e.offset_min.toFixed(0)} min vs onset (90%: ${e.offset_ci90_min[0].toFixed(0)} to ${e.offset_ci90_min[1].toFixed(0)}), scan p ${pv(e.p_scan)}, backlog recovered ${e.recovery_ratio == null ? "n/a" : pctu(e.recovery_ratio)}.`);
    const box = el("div", { class: "chart" }); c1.append(box); requestAnimationFrame(() => timingChart(box, S.tStream, S.tEvent));
    const c2 = card(M, "Posterior of the dip start relative to the outage onset"); const b2 = el("div", { class: "chart" }); c2.append(b2); requestAnimationFrame(() => posteriorChart(b2, e));
    const c3 = card(M, "All streams", "Bold p-values mark dips that are significant and start at or after the onset.");
    const t = el("table", { class: "tbl" }); t.append(el("tr", {}, ...["Stream", "Event", "Dip", "Duration", "Start vs onset", "p (scan)", "Backlog"].map((h) => el("th", { text: h }))));
    for (const [sid, rr] of Object.entries(TM.results)) for (const k of ["SAS", "KAL", "VLA", "SEP27"]) { const ee = rr.events[k]; if (!ee) continue; const strong = ee.p_scan < 0.05 && ee.offset_min >= -30;
      t.append(el("tr", { class: "click" + (sid === S.tStream && k === S.tEvent ? " sel" : ""), onclick: () => { if (k !== "SEP27") { S.tStream = sid; S.tEvent = k; render(); } inspect({ type: "timing", id: sid }); } }, el("td", { text: rr.label }), el("td", { text: EVN[k] }), el("td", { class: "num", text: pct(ee.dip_ratio - 1) }), el("td", { class: "num", text: ee.dip_hours.toFixed(1) + " h" }), el("td", { class: "num", text: `${ee.offset_min > 0 ? "+" : ""}${ee.offset_min.toFixed(0)} min` }), el("td", { class: "num", style: strong ? "font-weight:750" : "", text: pv(ee.p_scan) }), el("td", { class: "num", text: ee.recovery_ratio == null ? "n/a" : pctu(ee.recovery_ratio) }))); }
    c3.append(el("div", { class: "tblwrap" }, t));
  }
  function timingChart(box, sid, ek) {
    const s = TM.series[sid]; const t0 = Date.parse(TM.t0); const on = ONSETS[ek]; const e = TM.results[sid].events[ek];
    const W = Math.max(320, box.clientWidth || 900), H = 300, m = { l: 50, r: 14, t: 76, b: 24 };
    const xs = s.obs.map((_, j) => new Date(t0 + j * MIN10)), obs = s.obs, exp = s.exp;
    const lo = +on - 12 * HOUR, hi = +on + 24 * HOUR; const idx = xs.map((x, i) => i).filter((i) => +xs[i] >= lo && +xs[i] < hi);
    const svg = d3.select(box).append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("height", H);
    const x = d3.scaleUtc().domain([lo, hi]).range([m.l, W - m.r]);
    const y = d3.scaleLinear().domain([0, d3.max(idx, (i) => Math.max(obs[i], exp[i])) * 1.08 || 1]).nice().range([H - m.b, m.t]);
    svg.append("g").attr("class", "gridline").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(4).tickSize(-(W - m.l - m.r)).tickFormat(""));
    svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(4)).call((g) => g.select(".domain").remove());
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.b})`).call(d3.axisBottom(x).ticks(8).tickFormat(tickFmt));
    const a = Date.parse(e.tau1_map), b = Date.parse(e.tau2_map);
    svg.append("rect").attr("x", x(a)).attr("width", Math.max(1, x(b) - x(a))).attr("y", m.t).attr("height", H - m.t - m.b).attr("fill", css("--band"));
    const bw = Math.max(1, (W - m.l - m.r) / idx.length - 1);
    svg.selectAll("rect.o").data(idx).join("rect").attr("x", (i) => x(xs[i])).attr("width", bw).attr("y", (i) => y(obs[i])).attr("height", (i) => y(0) - y(obs[i])).attr("fill", css("--s3")).attr("opacity", 0.85);
    svg.append("path").datum(idx).attr("d", d3.line().x((i) => x(xs[i]) + bw / 2).y((i) => y(exp[i])).curve(d3.curveStepAfter)).attr("fill", "none").attr("stroke", css("--ink-1")).attr("stroke-width", 1.5);
    svg.append("line").attr("x1", x(on)).attr("x2", x(on)).attr("y1", 8).attr("y2", H - m.b).attr("stroke", css("--critical")).attr("stroke-width", 1.5);
    svg.append("text").attr("class", "evlabel").attr("x", x(on) + 4).attr("y", m.t + 10).text("outage onset");
    const io = TM.series["ioda.asn.200350"].obs; const yi = d3.scaleLinear().domain([0, 560]).range([m.t - 16, 12]);
    const ii = io.map((v, i) => i).filter((i) => +xs[i] >= lo && +xs[i] < hi);
    svg.append("path").datum(ii).attr("d", d3.line().defined((i) => io[i] != null).x((i) => x(xs[i])).y((i) => yi(io[i]))).attr("fill", "none").attr("stroke", css("--s2")).attr("stroke-width", 1.6);
    svg.append("text").attr("class", "plab-sub").attr("x", m.l).attr("y", 9).text("Yandex Cloud responsive address blocks (IODA)");
    svg.append("rect").attr("x", m.l).attr("y", 0).attr("width", W - m.l - m.r).attr("height", H - m.b).attr("fill", "transparent")
      .on("mousemove", (ev) => { const t = x.invert(d3.pointer(ev)[0]); const i = Math.min(xs.length - 1, Math.max(0, Math.floor((+t - t0) / MIN10))); showTip(ev, fmtT(xs[i]), [{ label: "Observed", value: num(obs[i]), color: css("--s3") }, { label: "Expected", value: num(exp[i], 1) }, { label: "IODA blocks responding", value: io[i] == null ? "n/a" : num(io[i]), color: css("--s2") }]); }).on("mouseleave", hideTip);
    box.append(el("div", { class: "legend" }, el("span", {}, el("span", { class: "swatch", style: `background:${css("--s3")};height:8px` }), "Observed per 10 min"), el("span", {}, el("span", { class: "swatch", style: `background:${css("--ink-1")}` }), "Expected"), el("span", {}, el("span", { class: "swatch", style: `background:${css("--s2")}` }), "IODA reachability"), el("span", {}, el("span", { class: "swatch", style: `background:${css("--band-strong")};height:8px` }), "Most likely dip")));
  }
  function posteriorChart(box, e) {
    const p = e.posterior_tau1; const W = Math.max(320, box.clientWidth || 900), H = 140, m = { l: 50, r: 14, t: 8, b: 24 };
    const rel = p.map((_, i) => -720 + i * 10);
    const svg = d3.select(box).append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("height", H);
    const x = d3.scaleLinear().domain([-720, 1440]).range([m.l, W - m.r]); const y = d3.scaleLinear().domain([0, d3.max(p) || 1]).range([H - m.b, m.t]);
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.b})`).call(d3.axisBottom(x).ticks(12).tickFormat((d) => (d > 0 ? "+" : "") + (d / 60).toFixed(0) + " h"));
    svg.append("path").datum(p).attr("d", d3.area().x((d, i) => x(rel[i])).y0(y(0)).y1((d) => y(d)).curve(d3.curveStepAfter)).attr("fill", css("--band-strong"));
    svg.append("path").datum(p).attr("d", d3.line().x((d, i) => x(rel[i])).y((d) => y(d)).curve(d3.curveStepAfter)).attr("fill", "none").attr("stroke", css("--s1")).attr("stroke-width", 1.5);
    svg.append("line").attr("x1", x(0)).attr("x2", x(0)).attr("y1", m.t).attr("y2", H - m.b).attr("stroke", css("--critical")).attr("stroke-width", 1.5);
    svg.append("text").attr("class", "evlabel").attr("x", x(0) + 4).attr("y", m.t + 10).text("outage onset");
  }

  // ---- effects
  function vEffects(M) {
    header(M, "Effects: cross-platform estimates", "Platform-group Bayesian estimates first, then every individual series with its placebo-calibrated interval. The red band marks drops larger than the 20% smallest effect of interest.", "bayes");
    const bc = card(M, "Bayesian hierarchical estimates by platform group", "Posterior median and 90% credible interval of the change, including common news shocks. Credible drop: P(drop > 10%) > 90% and group placebo p < 0.05.");
    const ws = el("div", { class: "seg inline", style: "margin-bottom:10px;flex-wrap:wrap" }); for (const [k, l] of [["SAS_6h", "Sasovo 6 h"], ["SAS_24h", "Sasovo 24 h"], ["VLA_6h", "Vladimir 6 h"], ["VLA_24h", "Vladimir 24 h"], ["KAL_24h", "Kaluga 24 h"], ["SEP27_24h", "Placebo"]]) ws.append(el("button", { class: S.emapWin === k ? "on" : "", onclick: () => { S.emapWin = k; render(); } }, l));
    bc.append(ws); const bb = el("div", { class: "chart" }); bc.append(bb);
    const w = BY.windows[S.emapWin];
    const grows = BY.groups.slice().sort((a, b) => (a.startsWith("Control") - b.startsWith("Control")) || a.localeCompare(b)).map((g) => ({ id: g, label: g, eff: w.groups[g]?.median, lo: w.groups[g]?.ci90[0], hi: w.groups[g]?.ci90[1], p: w.groups[g]?.p_drop10, verdict: w.groups[g]?.credible_drop ? "Drop detected" : (w.groups[g]?.ci90[0] ?? -1) > -0.2 ? "Large drop ruled out" : "Inconclusive", group: true })).filter((r) => r.eff != null);
    requestAnimationFrame(() => forest(bb, grows, "P(drop >10%)"));
    const io = w.io_minus_control, beta = w.beta_yandex_mail;
    bc.append(el("p", { class: "note", style: "margin:10px 0 0" }, `IO groups minus controls: ${pct(io.median)} (90% ${pct(io.ci90[0])} to ${pct(io.ci90[1])}). `, beta ? `Extra effect for outlets on Yandex 360 mail: ${pct(beta.median)} (90% ${pct(beta.ci90[0])} to ${pct(beta.ci90[1])}, ${beta.n_treated} channels).` : ""));
    const ctlc = card(M, "Individual series");
    const metSel = el("select", { class: "sel" });
    for (const [k, l] of [["SAS_6h", "Sasovo, 6 h"], ["SAS_24h", "Sasovo, 24 h"], ["KAL_24h", "Kaluga, 24 h"], ["VLA_6h", "Vladimir, 6 h"], ["VLA_24h", "Vladimir, 24 h"], ["SEP27_24h", "27 Sep placebo, 24 h"], ["dose:S1", "Dose-response on EOF Stage 1"], ["dose:S2", "Dose-response on EOF Stage 2"], ["dose:IODA", "Dose-response on measured outage"], ["dose:custom", "Dose-response on what-if EOF"]]) { const o = el("option", { value: k, text: l }); if (k === S.attr.metric) o.selected = true; metSel.append(o); }
    metSel.addEventListener("change", () => { S.attr.metric = metSel.value; if (metSel.value === "dose:custom" && !S.eof.custom) runCustom(); render(); });
    const lay = el("div", { class: "seg inline" }); for (const [k, l] of [["io", "IO output"], ["control", "Controls"], ["services", "Services"], ["all", "All"]]) lay.append(el("button", { class: S.attr.layer === k ? "on" : "", onclick: () => { S.attr.layer = k; render(); } }, l));
    ctlc.append(el("div", { style: "display:flex;gap:12px;flex-wrap:wrap;align-items:center;margin-bottom:10px" }, el("span", { class: "lbl", text: "Estimate" }), metSel, el("span", { class: "lbl", text: "Layer" }), lay, info("placebo"), info("fdr"), info("sesoi")));
    const rows = attrRows(); const fb = el("div", { class: "chart" }); ctlc.append(fb); requestAnimationFrame(() => forest(fb, rows, "p (drop)"));
    const tc = card(M, "Theme contrasts: Ukraine-war content minus other content", "A dependency specific to war propaganda would appear as a negative contrast.", "theme");
    const t2 = el("table", { class: "tbl" }); t2.append(el("tr", {}, ...["Series", "Sasovo 24 h", "Vladimir 24 h", "p (drop)"].map((h) => el("th", { text: h }))));
    for (const [k, d] of Object.entries(EV.analysis.contrasts)) { const a = d.windows.SAS_24h, b = d.windows.VLA_24h; t2.append(el("tr", { class: "click", onclick: () => inspect({ type: "series", id: d.war }) }, el("td", { text: (SER[d.war]?.label || k).replace(" (war posts)", "") }), el("td", { class: "num", text: a ? pct(a.effect) : "n/a" }), el("td", { class: "num", text: b ? pct(b.effect) : "n/a" }), el("td", { class: "num", text: b ? pv(b.p_drop) : "n/a" }))); }
    tc.append(t2);
  }
  function attrRows() {
    const met = S.attr.metric; const rows = [];
    for (const [id, s] of Object.entries(SER)) {
      if (!s.stats || (S.attr.layer !== "all" && s.layer !== S.attr.layer) || !seriesPasses(id)) continue;
      let eff, lo, hi, p;
      if (met.startsWith("dose:")) { const k = met.slice(5); if (k === "custom") { const d = customDose(id); if (!d) continue; ({ eff, lo, hi, p } = d); } else { const d = s.stats.dose?.[k]; if (!d) continue; eff = d.effect_at_max; [lo, hi] = d.ci90; p = d.p_placebo_drop; } }
      else { const w = s.stats.windows?.[met]; if (!w) continue; eff = w.effect; [lo, hi] = w.ci90; p = w.p_drop; }
      rows.push({ id, label: s.label, eff, lo, hi, p, verdict: s.stats.verdict });
    }
    return rows.sort((a, b) => a.eff - b.eff);
  }
  function customDose(id) {
    const c = S.eof.custom; const a = SER[id].a; if (!c || !a) return null;
    const ex = new Array(NH).fill(0); const off = Math.round((HI_T0 - H0) / HOUR);
    for (let h = 0; h < NH - off; h++) ex[off + h] = d3.mean(c.mean.slice(h * 6, h * 6 + 6)) || 0;
    const X = [], Y = []; for (let i = 0; i < NH; i++) if (a[i] != null) { X.push(ex[i]); Y.push(a[i]); }
    const n = X.length, mx = d3.mean(X), my = d3.mean(Y); let sxx = 0, sxy = 0; for (let i = 0; i < n; i++) { sxx += (X[i] - mx) ** 2; sxy += (X[i] - mx) * (Y[i] - my); }
    const b = sxy / sxx, u = Y.map((yv, i) => yv - my - b * (X[i] - mx)), z = X.map((xv) => xv - mx);
    let S0 = 0; for (let i = 0; i < n; i++) S0 += (z[i] * u[i]) ** 2; for (let l = 1; l <= 24; l++) { let g = 0; for (let i = l; i < n; i++) g += z[i] * u[i] * z[i - l] * u[i - l]; S0 += 2 * (1 - l / 25) * g; }
    const se = Math.sqrt(S0) / sxx, emax = d3.max(ex);
    return { eff: Math.exp(b * emax) - 1, lo: Math.exp((b - 1.645 * se) * emax) - 1, hi: Math.exp((b + 1.645 * se) * emax) - 1, p: 0.5 * (1 + erf(b / se / Math.SQRT2)) };
  }
  function erf(x) { const t = 1 / (1 + 0.3275911 * Math.abs(x)); const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x); return x >= 0 ? y : -y; }
  function forest(box, rows, pLabel) {
    const W = Math.max(520, box.clientWidth || 900), rh = 21, m = { l: Math.min(340, W * 0.36), r: 140, t: 24, b: 10 };
    const H = m.t + m.b + rows.length * rh;
    const svg = d3.select(box).append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("height", H);
    const lo = Math.max(-0.9, d3.min(rows, (r) => r.lo) ?? -0.5), hi = Math.min(2, d3.max(rows, (r) => r.hi) ?? 0.5);
    const x = d3.scaleLinear().domain([Math.min(lo, -0.3), Math.max(hi, 0.3)]).nice().range([m.l, W - m.r]);
    svg.append("rect").attr("x", x(x.domain()[0])).attr("width", Math.max(0, x(-0.2) - x(x.domain()[0]))).attr("y", m.t).attr("height", H - m.t - m.b).attr("fill", css("--critical")).attr("opacity", 0.07);
    svg.append("g").attr("class", "gridline").attr("transform", `translate(0,${m.t})`).call(d3.axisTop(x).ticks(8).tickSize(-(H - m.t - m.b)).tickFormat(""));
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${m.t})`).call(d3.axisTop(x).ticks(8).tickFormat((d) => (d > 0 ? "+" : "") + Math.round(d * 100) + "%"));
    svg.append("line").attr("x1", x(0)).attr("x2", x(0)).attr("y1", m.t).attr("y2", H - m.b).attr("stroke", css("--ink-2"));
    const vc = { "Drop detected": css("--critical"), "Increase detected": css("--s1"), "Large drop ruled out": css("--good"), Inconclusive: css("--ink-3") };
    const ic = { "Drop detected": "▼", "Increase detected": "▲", "Large drop ruled out": "✓", Inconclusive: "?" };
    rows.forEach((r, i) => {
      const yy = m.t + i * rh + rh / 2;
      const g = svg.append("g").style("cursor", "pointer").on("click", () => inspect(r.group ? { type: "group", id: r.id, win: S.emapWin } : { type: "series", id: r.id }))
        .on("mousemove", (ev) => showTip(ev, r.label, [{ label: "Estimate", value: pct(r.eff, 1) }, { label: "90% interval", value: `${pct(r.lo, 1)} to ${pct(r.hi, 1)}` }, { label: pLabel, value: r.group ? pctu(r.p) : pv(r.p) }, { label: "Verdict", value: r.verdict }])).on("mouseleave", hideTip);
      g.append("rect").attr("x", 0).attr("width", W).attr("y", yy - rh / 2).attr("height", rh).attr("fill", i % 2 ? "transparent" : css("--surface-2")).attr("opacity", 0.55);
      const maxc = Math.floor(m.l / 6.4);
      g.append("text").attr("x", m.l - 8).attr("y", yy + 4).attr("text-anchor", "end").attr("fill", css("--ink-1")).attr("font-size", 11.5).text(r.label.length > maxc ? r.label.slice(0, maxc - 1) + "…" : r.label);
      g.append("line").attr("x1", x(Math.max(r.lo, x.domain()[0]))).attr("x2", x(Math.min(r.hi, x.domain()[1]))).attr("y1", yy).attr("y2", yy).attr("stroke", vc[r.verdict] || css("--ink-3")).attr("stroke-width", 2.2);
      g.append("circle").attr("cx", x(Math.max(Math.min(r.eff, x.domain()[1]), x.domain()[0]))).attr("cy", yy).attr("r", 4.5).attr("fill", vc[r.verdict] || css("--ink-3")).attr("stroke", css("--surface-1")).attr("stroke-width", 2);
      g.append("text").attr("x", W - m.r + 10).attr("y", yy + 4).attr("fill", css("--ink-2")).attr("font-size", 11.5).text(`${ic[r.verdict] || "·"} ${pct(r.eff)}   ${r.group ? "P " + pctu(r.p) : "p " + pv(r.p)}`);
    });
  }

  // ---- event study
  function eventStudyChart(box, id, height = 260, compact = false) {
    let st = SER[id]?.stats?.event_study; if (!st) return;
    const a0 = EV.analysis.event_window[0]; const rel = st.placebo_q50 ? st.placebo_q50.map((_, i) => a0 + i) : [];
    const W = Math.max(260, box.clientWidth || (compact ? 300 : 900)), H = height, m = { l: 42, r: 10, t: 8, b: 22 };
    const k = S.esSmooth || 1; const sm = (a) => (k <= 1 || !a ? a : a.map((_, i) => { const w = a.slice(Math.max(0, i - k + 1), i + 1).filter((v) => v != null); return w.length ? d3.mean(w) : null; }));
    st = Object.fromEntries(Object.entries(st).map(([kk, v]) => [kk, kk.startsWith("placebo") ? v : sm(v)]));
    const svg = d3.select(box).append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("height", H);
    const x = d3.scaleLinear().domain([a0, EV.analysis.event_window[1]]).range([m.l, W - m.r]); const tf = (v) => (v == null ? null : (Math.exp(v) - 1) * 100);
    const all = [...(st.placebo_q05 || []), ...(st.placebo_q95 || []), ...["SAS", "KAL", "VLA"].flatMap((q) => st[q] || [])].filter((v) => v != null).map(tf);
    const y = d3.scaleLinear().domain(d3.extent(all.length ? all : [-10, 10])).nice().range([H - m.b, m.t]);
    svg.append("g").attr("class", "gridline").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(4).tickSize(-(W - m.l - m.r)).tickFormat(""));
    svg.append("g").attr("class", "axis").attr("transform", `translate(${m.l},0)`).call(d3.axisLeft(y).ticks(4).tickFormat((d) => d + "%")).call((g) => g.select(".domain").remove());
    svg.append("g").attr("class", "axis").attr("transform", `translate(0,${H - m.b})`).call(d3.axisBottom(x).ticks(compact ? 5 : 10).tickFormat((d) => (d > 0 ? "+" : "") + d + "h"));
    if (st.placebo_q05) svg.append("path").datum(rel).attr("d", d3.area().x((d) => x(d)).y0((d, i) => y(tf(st.placebo_q05[i]))).y1((d, i) => y(tf(st.placebo_q95[i])))).attr("fill", css("--band"));
    svg.append("line").attr("x1", x(0)).attr("x2", x(0)).attr("y1", m.t).attr("y2", H - m.b).attr("stroke", css("--critical"));
    svg.append("line").attr("x1", m.l).attr("x2", W - m.r).attr("y1", y(0)).attr("y2", y(0)).attr("stroke", css("--axis"));
    const cols = { SAS: css("--s1"), KAL: css("--s4"), VLA: css("--s2") };
    for (const q of ["SAS", "KAL", "VLA"]) { const v = st[q]; if (v) svg.append("path").datum(v).attr("d", d3.line().defined((d) => d != null).x((d, i) => x(a0 + i)).y((d) => y(tf(d)))).attr("fill", "none").attr("stroke", cols[q]).attr("stroke-width", 1.6); }
    if (!compact) box.append(el("div", { class: "legend" }, ...["SAS", "KAL", "VLA"].map((q) => el("span", {}, el("span", { class: "swatch", style: `background:${cols[q]}` }), EVN[q])), el("span", {}, el("span", { class: "swatch", style: `background:${css("--band-strong")};height:8px` }), k > 1 ? "Placebo 5 to 95% (hourly, conservative)" : "Placebo 5 to 95%")));
  }
  function vEventStudy(M) {
    header(M, "Event study: superposed epochs around each strike", "Out-of-sample deviation from the seasonal expectation, 48 h before to 72 h after each outage onset, against the envelope of the same trajectory started at random baseline times.", "placebo");
    const ctlc = card(M); const sel = el("select", { class: "sel", style: "max-width:520px" });
    const ids = Object.keys(SER).filter((id) => SER[id].stats?.event_study && seriesPasses(id)).sort((a, b) => SER[a].group.localeCompare(SER[b].group));
    for (const id of ids) { const o = el("option", { value: id, text: `${SER[id].group}: ${SER[id].label}` }); if (id === S.esSeries) o.selected = true; sel.append(o); }
    sel.addEventListener("change", () => { S.esSeries = sel.value; render(); });
    ctlc.append(el("div", { style: "display:flex;gap:12px;align-items:center;flex-wrap:wrap" }, el("span", { class: "lbl", text: "Series" }), sel, el("span", { class: "lbl", text: "Smoothing" }), (() => { const s = seg([1, 3, 6], S.esSmooth, (v) => { S.esSmooth = v; render(); }, { 1: "None", 3: "3 h", 6: "6 h" }); s.classList.add("inline"); return s; })()));
    const c = card(M, SER[S.esSeries]?.label); const b = el("div", { class: "chart" }); c.append(b); requestAnimationFrame(() => eventStudyChart(b, S.esSeries, 300));
    const grid = el("div", { class: "grid3" }); M.append(grid);
    for (const id of ["pravda.total", "tg.prokremlin.war", "tg.grp.io_foreign_audience.all", "tg.yxdep.mail", "web.ukraina.ru", "rd.grp.politics.comments"]) {
      if (!SER[id]?.stats) continue;
      const cc = el("div", { class: "card", style: "cursor:pointer;margin:0", onclick: () => { S.esSeries = id; render(); } }, el("h3", { text: SER[id].label })); const bb = el("div", { class: "chart" }); cc.append(bb); grid.append(cc); requestAnimationFrame(() => eventStudyChart(bb, id, 170, true));
    }
  }

  // ---- evidence
  function vEvidence(M) {
    header(M, "Evidence: competing hypotheses, sources and data quality", "Every source was opened for this study and graded. The ACH matrix scores each evidence item against four hypotheses.", "ach");
    const pr = TM.results["pravda.total"].events; const W = (id, k = "VLA_24h") => SER[id]?.stats?.windows?.[k]; const g24 = BY.windows.VLA_24h.groups;
    const H = ["H1 Broad IO collapse", "H2 Narrow pipeline dependency", "H3 No IO effect", "H4 Artefact or confounder"];
    const evid = [
      ["IODA: Yandex Cloud 78% unreachable; onsets match status pages within minutes", "A1", ["C", "C", "C", "C"]],
      [`Pravda dip ${pct(pr.VLA.dip_ratio - 1)} for ${pr.VLA.dip_hours.toFixed(0)} h, starting ${pr.VLA.offset_min.toFixed(0)} min after the Vladimir onset, p ${pv(pr.VLA.p_scan)}`, "A1", ["C", "C", "I", "I"]],
      ["No Pravda dip time-locked to Sasovo (decline began 7 h before the strike)", "A1", ["I", "N", "C", "N"]],
      ["Upstream pro-Kremlin Telegram input shows no dip at Vladimir", "A1", ["I", "C", "C", "N"]],
      [`Telegram state media ${pct(g24["Telegram: state media"]?.median)}, military bloggers ${pct(g24["Telegram: military bloggers"]?.median)}, foreign-audience IO ${pct(g24["Telegram: foreign-audience IO"]?.median)} (Bayesian, 24 h)`, "A1", ["I", "C", "C", "N"]],
      [`Outlets on Yandex 360 mail: no extra effect (${pct(BY.windows.VLA_24h.beta_yandex_mail?.median)})`, "A2", ["I", "C", "C", "N"]],
      [`Web IO outlet ukraina.ru ${pct(W("web.ukraina.ru")?.effect)}; Reddit political communities ${pct(g24["Reddit: political communities"]?.median)}`, "A2", ["I", "C", "C", "N"]],
      ["War-theme minus non-war contrasts show no war-specific drop", "A2", ["I", "C", "C", "N"]],
      ["Viral 'bot traffic' chart is crawler-dominated Cloudflare data for AS13238", "B2", ["N", "N", "C", "C"]],
      [`ru.wikipedia user traffic ${pct(W("wiki.ru.wikipedia.user")?.effect)}; Yandex complaint alerts surge`, "A2", ["N", "C", "C", "N"]],
      ["27 Sep unexplained Yandex Cloud dip: no Pravda dip", "A1", ["N", "N", "C", "C"]],
    ];
    const relW = { A1: 1, A2: 0.9, B1: 0.85, B2: 0.75 }; const score = H.map((_, h) => d3.sum(evid, (e) => (e[2][h] === "I" ? relW[e[1]] || 0.5 : 0)));
    const c = card(M, "Analysis of competing hypotheses", "C consistent, I inconsistent, N not diagnostic. Lower weighted inconsistency is better.", "ach");
    const t = el("table", { class: "tbl ach" }); t.append(el("tr", {}, el("th", { text: "Evidence" }), el("th", { text: "Grade" }), ...H.map((h) => el("th", { text: h }))));
    for (const e of evid) t.append(el("tr", {}, el("td", { text: e[0] }), el("td", {}, el("span", { class: "adm", text: e[1] })), ...e[2].map((v) => el("td", { class: v.toLowerCase(), text: v }))));
    t.append(el("tr", {}, el("td", { style: "font-weight:650", text: "Weighted inconsistency" }), el("td"), ...score.map((s) => el("td", { class: "num", style: `font-weight:750;${s === d3.min(score) ? `color:${css("--good")}` : ""}`, text: s.toFixed(2) }))));
    c.append(t);
    const sc = card(M, "Source registry", "Click a row to inspect; links open the original.", "admiralty");
    const st = el("table", { class: "tbl" }); st.append(el("tr", {}, ...["Grade", "Source", "Type", "Content"].map((h) => el("th", { text: h }))));
    for (const s of EV.sources.slice().sort((a, b) => (a.rel + a.cred).localeCompare(b.rel + b.cred))) { if (REL.indexOf(s.rel) > REL.indexOf(S.unc.minRel)) continue; st.append(el("tr", { class: "click", onclick: () => inspect({ type: "source", id: s.id }) }, el("td", {}, el("span", { class: "adm", text: s.rel + s.cred })), el("td", {}, el("a", { href: s.url, target: "_blank", rel: "noopener", text: s.name, onclick: (e) => e.stopPropagation() })), el("td", { text: s.type }), el("td", { class: "muted", text: s.note }))); }
    sc.append(el("div", { class: "tblwrap" }, st));
    const dc = card(M, "Yandex dependency of IO and media outlets (public DNS, 13 Oct 2026)", "Hosting network of the website, mail exchanger and name servers. Only Yandex's own domains are hosted on Yandex.", "yxdep");
    const dt = el("table", { class: "tbl" }); dt.append(el("tr", {}, ...["Domain", "Role", "Hosting", "Mail at Yandex", "DNS at Yandex"].map((h) => el("th", { text: h }))));
    for (const d of EV.infra || []) dt.append(el("tr", {}, el("td", { text: d.domain }), el("td", { class: "muted", text: d.role.replace(/_/g, " ") }), el("td", { text: (d.asn_holders || []).join(", ").slice(0, 48) }), el("td", { text: d.yandex_mail ? "yes" : "" }), el("td", { text: d.yandex_dns ? "yes" : "" })));
    dc.append(el("div", { class: "tblwrap" }, dt));
    const qc = card(M, "Data quality audit", "Collector completeness and continuity for every stream.");
    const q = Object.entries(EV.quality || {}).filter(([, v]) => v.status !== "ok");
    qc.append(el("p", { class: "note", text: `${Object.keys(EV.quality || {}).length} streams audited; ${q.length} flagged and excluded from inference: ${q.map(([k, v]) => `${k} (${v.status.replace("_", " ")})`).join("; ") || "none"}.` }));
  }

  // ---- method
  function vMethod(M) {
    header(M, "Method", "The full methodology, results and sources are in the report (Report PDF in the top bar). This page summarises the pipeline and defines every term used in the dashboard.");
    const c = card(M, "Pipeline");
    const fl = el("div", { class: "flow" });
    for (const [t, d] of [["Collect", "IODA, RIPE, FIRMS, Wikimedia, status API, DNS, Telegram, Pravda and web sitemaps, Reddit"], ["Grade", "Admiralty grades pooled into strike credibility"], ["Model outage", "Three-stage Bayesian EOF (SMC), 10 minute grid"], ["Counterfactual", "Seasonal regression, leave-one-day-out"], ["Test", "Placebo windows, change points, dose-response, Bayesian pooling"], ["Decide", "FDR, equivalence, ACH, ICD 203"]]) fl.append(el("div", { class: "node" }, el("div", { class: "t", text: t }), el("div", { class: "d", text: d })));
    c.append(fl);
    const g = card(M, "Glossary"); const dl = el("dl", { class: "gloss" }); for (const [, [t, d]] of Object.entries(GLOSS)) dl.append(el("dt", { text: t }), el("dd", { text: d })); g.append(dl);
  }

  // ------------------------------------------------------------------ init
  function init() {
    document.getElementById("gen").textContent = `Data to ${EV.meta.study_end.slice(8, 10)} Oct ${EV.meta.study_end.slice(11, 16)} UTC`;
    document.getElementById("theme").addEventListener("click", () => { const r = document.documentElement; const dark = r.dataset.theme ? r.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches; r.dataset.theme = dark ? "light" : "dark"; store.set("theme", r.dataset.theme); buildLeft(); render(); renderInspector(); });
    const th = store.get("theme", null); if (th) document.documentElement.dataset.theme = th;
    applyPanels(); buildTabs(); buildLeft(); render(); renderInspector();
    let rt; addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(render, 150); });
  }
  init();
})();
