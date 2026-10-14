/* Attribution graph: sources -> observations -> outage -> exposure channel -> actors and platforms -> findings.
 * Three layouts (left to right, top down, radial), nodes semantically clustered within each layer.
 */
(function () {
  "use strict";
  const LAYERS = ["Sources", "Observations", "Outage estimate", "Exposure channel", "Actors and platforms", "Findings"];
  const SRC_SHORT = { "SRC-YCS-2092": "Status page #2092", "SRC-YCS-2136": "Status page #2136", "SRC-YCS-LIST": "Status page incident API", "SRC-YTG-5900": "Yandex Telegram #5900", "SRC-YTG-5901": "Yandex Telegram #5901", "SRC-YTG-5903": "Yandex Telegram #5903 (Pay)", "SRC-YTG-5905": "Yandex Telegram #5905 (B2B)", "SRC-GOV-10997": "Vladimir governor #10997", "SRC-FIRMS": "NASA FIRMS fire detections", "SRC-CFR-BSKY": "Cloudflare Radar (Bluesky)", "SRC-NB-BSKY": "NetBlocks (Bluesky)", "SRC-IODA": "IODA active probing", "SRC-RIPE": "RIPE Stat BGP", "SRC-TRK": "Detector404, Sboy.rf alerts", "SRC-PRAVDA": "Pravda network sitemaps", "SRC-TG": "Telegram channel previews", "SRC-RD": "Arctic Shift Reddit archive", "SRC-WIKI": "Wikimedia pageviews", "SRC-DNS": "Public DNS (A, MX, NS)", "SRC-WEB": "Web sitemaps", "SRC-EEAS": "EEAS 4th FIMI threat report", "SRC-VIGINUM": "VIGINUM Storm-1516 report", "SRC-VIGINUM-PK": "VIGINUM Portal Kombat report", "SRC-WP": "WordPress REST API", "SRC-REUTERS": "Reuters, 8 Oct" };
  const EV_SHORT = { "EV-SAS-STRIKE": "Sasovo strike", "EV-SAS-STATUS": "Power loss, zone b", "EV-SAS-FIRMS": "FIRMS fire at Sasovo", "EV-SAS-IODA": "IODA: reachability falls", "EV-SAS-NB": "NetBlocks confirms", "EV-SAS-CAUSE": "UAV fire, DC stopped", "EV-OCT8-WAVE": "Complaint burst (non-Yandex)", "EV-KAL-STMT": "Kaluga attacked", "EV-VLA-TRK": "Complaint alert", "EV-VLA-STATUS": "Zones unavailable", "EV-VLA-IODA": "IODA: second collapse", "EV-VLA-STOP": "Vladimir DC stopped", "EV-VLA-GOV": "Governor: drone attack", "EV-VLA-NB": "NetBlocks: second collapse", "EV-PAY": "Yandex Pay disrupted", "EV-B2B": "Fees waived, services limited", "EV-SEP27": "Unexplained dip" };

  function build(ctx) {
    const { EV, BY, TM, SER } = ctx;
    const nodes = [], edges = [];
    const N = (o) => nodes.push(o);
    const E = (a, b, w = 1, kind = "") => edges.push({ a, b, w, kind });
    const srcCluster = (t) => ({ "Official operator statement": "Operator statements", "Regional official": "Regional officials", "Satellite remote sensing": "Satellite", "Third-party telemetry report": "Telemetry reports", "Measurement data": "Measured data", "Crowdsourced outage tracker": "Complaint trackers", "Official attribution report": "Attribution reports", Media: "Media" }[t] || "Other");
    const used = new Set(EV.events.flatMap((e) => e.sources));
    ["SRC-EEAS", "SRC-VIGINUM-PK", "SRC-DNS", "SRC-WP", "SRC-PRAVDA", "SRC-TG", "SRC-RD", "SRC-WEB", "SRC-WIKI"].forEach((s) => used.add(s));
    for (const s of EV.sources) if (used.has(s.id)) N({ id: s.id, layer: 0, cluster: srcCluster(s.type), label: SRC_SHORT[s.id] || s.name, full: s.name, kind: "source", rel: s.rel, ref: { type: "source", id: s.id } });
    const siteOf = (e) => (["Sasovo", "Kaluga", "Vladimir"].includes(e.site) ? e.site : "Other");
    for (const e of EV.events.slice().sort((a, b) => Date.parse(a.t) - Date.parse(b.t))) {
      N({ id: e.id, layer: 1, cluster: siteOf(e), label: `${e.t.slice(8, 10)}/${e.t.slice(5, 7)} ${e.t.slice(11, 16)} ${EV_SHORT[e.id] || e.title}`, full: `${e.t.slice(0, 16).replace("T", " ")} UTC, ${e.title}`, kind: e.kind, ref: { type: "event", id: e.id } });
      for (const s of e.sources) E(s, e.id, 1);
    }
    for (const [k, l, cl] of [["SAS", "Sasovo outage", "Strikes"], ["KAL", "Kaluga strike", "Strikes"], ["VLA", "Vladimir outage", "Strikes"], ["SEP", "27 Sep control (no strike)", "Control period"]]) N({ id: "site." + k, layer: 2, cluster: cl, label: l, kind: "site", ref: k === "SEP" ? { type: "event", id: "EV-SEP27" } : { type: "eof" } });
    for (const e of EV.events) { const k = { Sasovo: "SAS", Kaluga: "KAL", Vladimir: "VLA" }[e.site]; if (k) E(e.id, "site." + k, 1); if (e.id === "EV-SEP27") E(e.id, "site.SEP", 1); }
    const exps = [["exp.cloud", "Yandex Cloud capacity", "Compute"], ["exp.consumer", "Consumer services", "Services"], ["exp.mail", "Yandex 360 mail", "Organisational"], ["exp.none", "No documented dependency", "Organisational"]];
    for (const [id, l, cl] of exps) N({ id, layer: 3, cluster: cl, label: l, kind: "exposure" });
    E("site.SAS", "exp.cloud", 3); E("site.VLA", "exp.cloud", 3); E("site.KAL", "exp.cloud", 0.3); E("site.SEP", "exp.cloud", 1);
    E("site.SAS", "exp.consumer", 2); E("site.VLA", "exp.consumer", 3); E("site.SAS", "exp.mail", 1); E("site.VLA", "exp.mail", 1);
    E("SRC-IODA", "exp.cloud", 1); E("SRC-DNS", "exp.mail", 1); E("SRC-DNS", "exp.none", 1);
    const g = (BY.windows.VLA_24h || {}).groups || {};
    const pr = TM.results["pravda.total"]?.events?.VLA;
    const actors = [
      ["act.pravda", "Pravda network", "EEAS-named IMS", pr ? pr.dip_ratio - 1 : null, ["exp.cloud"], ["SRC-PRAVDA", "SRC-EEAS", "SRC-VIGINUM-PK"], "f.drop", { type: "timing", id: "pravda.total" }],
      ["act.afri", "African Initiative", "EEAS-named IMS", g["Web: EEAS-named IMS outlets"]?.median, ["exp.none"], ["SRC-WP", "SRC-TG", "SRC-EEAS"], "f.none", { type: "group", id: "Web: EEAS-named IMS outlets", win: "VLA_24h" }],
      ["act.rrn", "RRN, R-FBI", "EEAS-named IMS", g["Web: EEAS-named IMS outlets"]?.median, ["exp.none"], ["SRC-WP", "SRC-EEAS"], "f.none", { type: "group", id: "Web: EEAS-named IMS outlets", win: "VLA_24h" }],
      ["act.state", "State media", "Telegram", g["Telegram: state media"]?.median, ["exp.none"], ["SRC-TG"], "f.none", { type: "group", id: "Telegram: state media", win: "VLA_24h" }],
      ["act.milb", "Military bloggers", "Telegram", g["Telegram: military bloggers"]?.median, ["exp.none", "exp.mail"], ["SRC-TG"], "f.none", { type: "group", id: "Telegram: military bloggers", win: "VLA_24h" }],
      ["act.tab", "Tabloids", "Telegram", g["Telegram: pro-Kremlin tabloids"]?.median, ["exp.none"], ["SRC-TG"], "f.none", { type: "group", id: "Telegram: pro-Kremlin tabloids", win: "VLA_24h" }],
      ["act.fio", "Foreign-audience IO", "Telegram", g["Telegram: foreign-audience IO"]?.median, ["exp.none", "exp.mail"], ["SRC-TG"], "f.none", { type: "group", id: "Telegram: foreign-audience IO", win: "VLA_24h" }],
      ["act.web", "ukraina.ru (RIA)", "Web and Reddit", g["Web: state IO outlet"]?.median, ["exp.none"], ["SRC-WEB"], "f.none", { type: "group", id: "Web: state IO outlet", win: "VLA_24h" }],
      ["act.rw", "Reddit war communities", "Web and Reddit", g["Reddit: Ukraine war communities"]?.median, ["exp.none"], ["SRC-RD"], "f.none", { type: "group", id: "Reddit: Ukraine war communities", win: "VLA_24h" }],
      ["act.rp", "Reddit political", "Web and Reddit", g["Reddit: political communities"]?.median, ["exp.none"], ["SRC-RD"], "f.none", { type: "group", id: "Reddit: political communities", win: "VLA_24h" }],
      ["act.wiki", "ru.wikipedia users", "Services", SER["wiki.ru.wikipedia.user"]?.stats?.windows?.VLA_24h?.effect, ["exp.consumer"], ["SRC-WIKI"], "f.small", { type: "series", id: "wiki.ru.wikipedia.user" }],
    ];
    for (const [id, l, cl, eff, ex, srcs, f, ref] of actors) {
      N({ id, layer: 4, cluster: cl, label: l, kind: "actor", effect: eff, ref, finding: f });
      for (const x of ex) E(x, id, x === "exp.none" ? 0.6 : 1.6);
      for (const s of srcs) E(s, id, 0.5, "attr");
      E(id, f, id === "act.pravda" ? 3 : 1);
    }
    for (const [id, l, color] of [["f.drop", "Time-locked drop", "--critical"], ["f.small", "Service-level drop", "--s4"], ["f.none", "No credible drop", "--good"]]) N({ id, layer: 5, cluster: "Findings", label: l, kind: "finding", color });
    const idx = Object.fromEntries(nodes.map((n) => [n.id, n]));
    return { nodes, edges: edges.filter((e) => idx[e.a] && idx[e.b]), idx };
  }

  const TEXT = {
    "exp.cloud": "Loss of Yandex Cloud compute and network capacity measured by IODA: 34% after Sasovo, 78% after Vladimir, none after Kaluga. Any pipeline running in the lost zones is exposed.",
    "exp.consumer": "Yandex consumer services (Search, Pay, Go, Alice, KinoPoisk) were disrupted; Russian Wikipedia visits fell 7%, consistent with lost search and app referrals.",
    "exp.mail": "Public DNS shows seven media and IO outlets on Yandex 360 mail (rt.com, vz.ru, readovka.news, rybar.ru, strategic-culture.su, topcor.ru, eadaily.com). Their channels show no strike-specific effect.",
    "exp.none": "Outlets without a documented Yandex dependency in their public DNS records (website hosting, mail or name servers).",
    "f.drop": "Only the Pravda network shows a significant dip that starts after the outage onset, replicated across its language editions.",
    "f.small": "Consumer-level effects such as fewer Russian Wikipedia visits are consistent with Yandex Search and app disruption.",
    "f.none": "No credible drop: either the interval rules out drops larger than 20%, or any change is matched in controls and placebo windows.",
  };

  function render(box, ctx) {
    box.replaceChildren();
    const G = build(ctx);
    const { css, pct, showTip, hideTip, onFocus, layout } = ctx;
    const W = layout === "radial" ? 1120 : Math.max(layout === "lr" ? 960 : 820, box.clientWidth || 1000);
    const clusterOrder = (layer) => [...new Set(G.nodes.filter((n) => n.layer === layer).map((n) => n.cluster))];
    const relC = { A: "--seq-5", B: "--seq-4", C: "--seq-3", D: "--seq-2", E: "--seq-1", F: "--ink-3" };
    const kindC = { strike: "--critical", statement: "--ink-2", telemetry: "--s3", confounder: "--s4", site: "--critical", exposure: "--s1", service: "--s4" };
    const colorOf = (n) => css(n.kind === "source" ? relC[n.rel] : n.kind === "finding" ? n.color : n.kind === "actor" ? (n.finding === "f.drop" ? "--critical" : n.finding === "f.small" ? "--s4" : "--good") : kindC[n.kind] || "--ink-3");
    let H, pos = {}, clusters = [];
    const byLayer = d3.group(G.nodes, (n) => n.layer);
    for (const [l, arr] of byLayer) { const order = clusterOrder(l); arr.sort((a, b) => order.indexOf(a.cluster) - order.indexOf(b.cluster)); }
    if (layout === "lr") {
      // text-heavy layers get wider columns
      const share = [1.2, 1.3, 0.8, 0.95, 1.15, 0.95], gap = 30, unit = (W - 8 - 5 * gap) / d3.sum(share);
      const colW = share.map((x) => x * unit), colX0 = share.map((_, i) => 4 + d3.sum(colW.slice(0, i)) + i * gap);
      const nodeH = 20, gapC = 16; const colX = (l) => colX0[l]; const nodeWOf = (l) => colW[l];
      pos._colX = colX0; pos._colW = colW;
      let maxH = 0; const hs = {};
      for (const [l, arr] of byLayer) { const nc = new Set(arr.map((n) => n.cluster)).size; hs[l] = arr.length * (nodeH + 4) + nc * gapC; maxH = Math.max(maxH, hs[l]); }
      H = maxH + 50;
      for (const [l, arr] of byLayer) {
        let y = 34 + (maxH - hs[l]) / 2, cur = null, c0 = null;
        for (const n of arr) {
          if (n.cluster !== cur) { if (cur != null) clusters.push({ l, label: cur, x: colX(l), y: c0, w: nodeWOf(l), h: y - c0 - 4 }); y += gapC; cur = n.cluster; c0 = y - 12; }
          pos[n.id] = { x: colX(l), y, w: nodeWOf(l), h: nodeH }; y += nodeH + 4;
        }
        clusters.push({ l, label: cur, x: colX(l), y: c0, w: nodeWOf(l), h: y - c0 - 4 });
      }
    } else if (layout === "td") {
      // each layer is a row of cluster blocks; blocks wrap onto further lines when the row is too wide
      const pw = 150, ph = 22, gx = 6, gy = 5, pad = 9, titleH = 17, bgap = 12, rowGap = 40, headH = 20;
      let y = 6; pos._rowY = [];
      for (let l = 0; l < 6; l++) {
        const arr = byLayer.get(l) || [];
        const blocks = clusterOrder(l).map((c) => { const ns = arr.filter((n) => n.cluster === c); const cols = Math.min(ns.length, 3); const rows = Math.ceil(ns.length / cols); return { c, ns, cols, w: cols * (pw + gx) - gx + 2 * pad, h: titleH + rows * (ph + gy) - gy + pad }; });
        const lines = []; let cur = [], cw = 0;
        for (const bl of blocks) { if (cur.length && cw + bl.w > W - 8) { lines.push(cur); cur = []; cw = 0; } cur.push(bl); cw += bl.w + bgap; }
        if (cur.length) lines.push(cur);
        pos._rowY[l] = y; y += headH;
        for (const ln of lines) {
          const lw = d3.sum(ln, (bl) => bl.w) + bgap * (ln.length - 1); let x = Math.max(4, (W - lw) / 2); const lh = d3.max(ln, (bl) => bl.h);
          for (const bl of ln) {
            clusters.push({ l, label: bl.c, x, y, w: bl.w, h: bl.h });
            bl.ns.forEach((n, i) => { pos[n.id] = { x: x + pad + (i % bl.cols) * (pw + gx), y: y + titleH + Math.floor(i / bl.cols) * (ph + gy), w: pw, h: ph }; });
            x += bl.w + bgap;
          }
          y += lh + 8;
        }
        y += rowGap;
      }
      H = y - rowGap + 10;
    } else {
      // hub layout: outage estimate in the centre, upstream evidence on the left, consequences on the right
      const cx = 505, cy = 520; H = 1040; const deg = Math.PI / 180;
      const RING = { 0: 340, 1: 190, 3: 140, 4: 280, 5: 465 };
      const SPAN = { 0: [252, 108], 1: [248, 112], 3: [-62, 62], 4: [-78, 78], 5: [-40, 40] };
      for (const [l, arr] of byLayer) {
        if (l === 2) { arr.forEach((n, i) => { pos[n.id] = { x: cx, y: cy + (i - (arr.length - 1) / 2) * 56, hub: true }; }); continue; }
        const r = RING[l], [s0, s1] = SPAN[l]; const order = clusterOrder(l); const gapU = 1.4;
        const slots = arr.length - 1 + (order.length - 1) * gapU; const step = slots > 0 ? (s1 - s0) / slots : 0;
        let ang = slots > 0 ? s0 : (s0 + s1) / 2, cur = arr[0]?.cluster, a0 = ang;
        for (const n of arr) {
          if (n.cluster !== cur) { clusters.push({ l, label: cur, a0, a1: ang - step, r }); ang += step * gapU; cur = n.cluster; a0 = ang; }
          pos[n.id] = { x: cx + r * Math.cos(ang * deg), y: cy + r * Math.sin(ang * deg), a: ang, ring: r }; ang += step;
        }
        clusters.push({ l, label: cur, a0, a1: ang - step, r });
      }
      pos._c = { x: cx, y: cy };
    }
    // the whole graph is fitted into a fixed viewport; drag to pan, Ctrl or Cmd + wheel (or the buttons) to zoom
    const vh = Math.round(Math.min(Math.max(520, window.innerHeight * 0.74), 900));
    const svg = d3.select(box).append("svg").attr("viewBox", `0 0 ${W} ${H}`).attr("preserveAspectRatio", "xMidYMid meet").style("width", "100%").style("height", vh + "px").style("cursor", "grab");
    const root = svg.append("g");
    const gC = root.append("g"), gE = root.append("g"), gN = root.append("g");
    // layer and cluster labels
    if (layout === "lr") {
      LAYERS.forEach((l, i) => root.append("text").attr("class", "ag-col").attr("x", pos._colX[i]).attr("y", 14).text(l));
      for (const c of clusters) { gC.append("rect").attr("x", c.x - 3).attr("y", c.y - 2).attr("width", c.w + 6).attr("height", c.h + 4).attr("rx", 7).attr("fill", css("--surface-2")).attr("opacity", 0.6); gC.append("text").attr("class", "ag-cl").attr("x", c.x + 2).attr("y", c.y + 8).text(c.label); }
    } else if (layout === "td") {
      LAYERS.forEach((l, i) => root.append("text").attr("class", "ag-col").attr("x", 6).attr("y", pos._rowY[i] + 12).text(l));
      for (const c of clusters) { gC.append("rect").attr("x", c.x).attr("y", c.y).attr("width", c.w).attr("height", c.h).attr("rx", 8).attr("fill", css("--surface-2")).attr("opacity", 0.75); gC.append("text").attr("class", "ag-cl").attr("x", c.x + 9).attr("y", c.y + 12).text(c.label); }
    } else {
      const { x: cx, y: cy } = pos._c; const deg = Math.PI / 180;
      const pt = (r, a) => [cx + r * Math.cos(a * deg), cy + r * Math.sin(a * deg)];
      let k = 0;
      for (const c of clusters) {
        if (c.l === 5) continue;
        const lo = Math.min(c.a0, c.a1) - 3, hi = Math.max(c.a0, c.a1) + 3;
        const band = d3.arc().innerRadius(c.r - 10).outerRadius(c.r + 10).startAngle((lo + 90) * deg).endAngle((hi + 90) * deg);
        gC.append("path").attr("d", band()).attr("transform", `translate(${cx},${cy})`).attr("fill", css("--surface-2")).attr("opacity", 0.8);
        // cluster name along the inner side of the ring, reading clockwise
        // lower half: run the path anticlockwise so the text stays upright
        const mid = (((lo + hi) / 2) % 360 + 360) % 360, rev = mid > 0 && mid < 180;
        const rr = rev ? c.r - 7 : c.r - 15, [x0, y0] = pt(rr, lo - 10), [x1, y1] = pt(rr, hi + 10), id = "agc" + k++ + Math.random().toString(36).slice(2, 6);
        gC.append("path").attr("id", id).attr("d", rev ? `M${x1},${y1} A${rr},${rr} 0 0 0 ${x0},${y0}` : `M${x0},${y0} A${rr},${rr} 0 0 1 ${x1},${y1}`).attr("fill", "none");
        gC.append("text").attr("class", "ag-cl").append("textPath").attr("href", "#" + id).attr("startOffset", "50%").attr("text-anchor", "middle").text(c.label);
      }
      root.append("text").attr("class", "ag-col").attr("x", 12).attr("y", 18).text("Upstream evidence: sources (outer ring), observations (inner ring)");
      root.append("text").attr("class", "ag-col").attr("x", W - 12).attr("y", 18).attr("text-anchor", "end").text("Consequences: exposure, actors, findings (outer)");
      root.append("text").attr("class", "ag-col").attr("x", cx).attr("y", cy - 128).attr("text-anchor", "middle").text("Outage estimate");
    }
    // edges
    const anchor = (n, side) => { const p = pos[n.id]; if (layout === "lr") return side === "out" ? [p.x + p.w, p.y + p.h / 2] : [p.x, p.y + p.h / 2]; if (layout === "td") return side === "out" ? [p.x + p.w / 2, p.y + p.h] : [p.x + p.w / 2, p.y]; return [p.x, p.y]; };
    const path = (e) => {
      const A = G.idx[e.a], B = G.idx[e.b]; const [x1, y1] = anchor(A, "out"), [x2, y2] = anchor(B, "in");
      if (layout === "lr") { const mx = (x1 + x2) / 2; return `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`; }
      if (layout === "td") { const my = (y1 + y2) / 2; return `M${x1},${y1} C${x1},${my} ${x2},${my} ${x2},${y2}`; }
      const { x: cx, y: cy } = pos._c; const k = 0.55; const qx = cx + ((x1 + x2) / 2 - cx) * k, qy = cy + ((y1 + y2) / 2 - cy) * k; return `M${x1},${y1} Q${qx},${qy} ${x2},${y2}`;
    };
    const hot = (e) => e.a === "act.pravda" || e.b === "act.pravda" || e.b === "f.drop";
    const eSel = gE.selectAll("path").data(G.edges).join("path").attr("class", "ag-edge").attr("d", path)
      .attr("stroke", (e) => (hot(e) ? css("--critical") : css("--axis"))).attr("stroke-width", (e) => 0.6 + e.w * 0.55).attr("stroke-dasharray", (e) => (e.kind === "attr" ? "3 3" : null)).attr("opacity", 0.65);
    const nSel = gN.selectAll("g").data(G.nodes).join("g").attr("class", "ag-node").style("cursor", "pointer")
      .on("mousemove", (ev, n) => showTip(ev, `${LAYERS[n.layer]} · ${n.cluster}`, [{ label: n.full || n.label, value: n.effect != null ? pct(n.effect) : n.rel ? "grade " + n.rel : "" }])).on("mouseleave", hideTip)
      .on("click", (ev, n) => { ev.stopPropagation(); focus(n.id); });
    if (layout === "lr" || layout === "td") {
      nSel.attr("transform", (n) => `translate(${pos[n.id].x},${pos[n.id].y})`);
      const wOf = (n) => pos[n.id].w, hOf = (n) => pos[n.id].h, mc = (n) => Math.max(10, Math.floor((wOf(n) - 14) / 6.0)) - (n.effect != null ? 6 : 0);
      nSel.append("rect").attr("width", wOf).attr("height", hOf).attr("rx", 6).attr("fill", css("--surface-1")).attr("stroke", css("--border"));
      nSel.append("rect").attr("width", 4).attr("height", hOf).attr("rx", 2).attr("fill", colorOf);
      nSel.append("text").attr("x", 10).attr("y", (n) => hOf(n) / 2 + 4).text((n) => (n.label.length > mc(n) ? n.label.slice(0, mc(n) - 1) + "…" : n.label));
      nSel.filter((n) => n.effect != null).append("text").attr("x", (n) => wOf(n) - 6).attr("y", (n) => hOf(n) / 2 + 4).attr("text-anchor", "end").attr("font-weight", 650).text((n) => pct(n.effect));
    } else {
      nSel.attr("transform", (n) => `translate(${pos[n.id].x},${pos[n.id].y})`);
      nSel.append("circle").attr("r", (n) => (n.layer >= 2 ? 8 : 5.5)).attr("fill", colorOf).attr("stroke", css("--surface-1")).attr("stroke-width", 2);
      {
        const lim = { 0: 25, 1: 21, 3: 19, 4: 22, 5: 22 };
        nSel.append("text").attr("class", "ag-lab").attr("transform", (n) => {
          const p = pos[n.id]; if (p.hub) return "translate(0,-13)";
          const flip = p.a > 90 && p.a < 270; return `rotate(${flip ? p.a + 180 : p.a}) translate(${flip ? -12 : 12},3.5)`;
        }).attr("text-anchor", (n) => { const p = pos[n.id]; if (p.hub) return "middle"; return p.a > 90 && p.a < 270 ? "end" : "start"; })
          .text((n) => { const L = lim[n.layer] || 22; const t = n.label.length > L ? n.label.slice(0, L - 1) + "…" : n.label; return n.effect != null ? `${t} ${pct(n.effect)}` : t; });
      }
    }
    const up = (id, acc = new Set()) => { for (const e of G.edges) if (e.b === id && !acc.has(e.a)) { acc.add(e.a); up(e.a, acc); } return acc; };
    const down = (id, acc = new Set()) => { for (const e of G.edges) if (e.a === id && !acc.has(e.b)) { acc.add(e.b); down(e.b, acc); } return acc; };
    function focus(id, silent) {
      ctx.state.focus = id;
      if (!id || !G.idx[id]) { nSel.attr("opacity", 1); eSel.attr("opacity", 0.65); onFocus(null, null); return; }
      const keep = new Set([id, ...up(id), ...down(id)]);
      nSel.attr("opacity", (n) => (keep.has(n.id) ? 1 : 0.1)); eSel.attr("opacity", (e) => (keep.has(e.a) && keep.has(e.b) ? 0.95 : 0.04));
      const path = LAYERS.map((l, i) => [...keep].map((k) => G.idx[k]).filter((n) => n && n.layer === i));
      onFocus(G.idx[id], path, (nid) => focus(nid), TEXT[id], silent);
    }
    svg.on("click", (ev) => { if (!ev.defaultPrevented) focus(null); });
    const zoom = d3.zoom().scaleExtent([0.6, 6]).filter((ev) => (ev.type === "wheel" ? ev.ctrlKey || ev.metaKey : !ev.button))
      .on("start", () => svg.style("cursor", "grabbing")).on("end", () => svg.style("cursor", "grab"))
      .on("zoom", (ev) => root.attr("transform", ev.transform));
    svg.call(zoom).on("dblclick.zoom", null);
    if (ctx.state.zoom) svg.call(zoom.transform, ctx.state.zoom);
    zoom.on("end.store", (ev) => { ctx.state.zoom = ev.transform; svg.style("cursor", "grab"); });
    focus(ctx.state.focus, true);
    return { focus, zoomBy: (k) => svg.transition().duration(250).call(zoom.scaleBy, k), fit: () => { ctx.state.zoom = null; svg.transition().duration(250).call(zoom.transform, d3.zoomIdentity); } };
  }
  window.AttributionGraph = { render, LAYERS };
})();
