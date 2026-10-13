/* In-browser replica of the Expected Outage Function (Stages 0 and 1).
 * Same generative model as pipeline/model_outage.py: capacity-weighted damage
 * with triangular strike-time priors, gamma onset lags and ramps, beta damage
 * mixtures weighted by Admiralty-derived credibility, log-normal recovery.
 * Stage 1 constraints are applied by self-normalised importance weighting.
 */
(function () {
  const T0 = Date.parse("2026-09-01T00:00:00Z");
  const min = (iso) => (Date.parse(iso) - T0) / 60000;

  function rng(seed) {
    let a = seed >>> 0;
    return function () {
      a |= 0; a = (a + 0x6d2b79f5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
  function normal(u) { let a = 0, b = 0; while (a === 0) a = u(); b = u(); return Math.sqrt(-2 * Math.log(a)) * Math.cos(2 * Math.PI * b); }
  function gamma(u, k, theta) {
    if (k < 1) return gamma(u, k + 1, theta) * Math.pow(u(), 1 / k);
    const d = k - 1 / 3, c = 1 / Math.sqrt(9 * d);
    for (;;) {
      let x, v;
      do { x = normal(u); v = 1 + c * x; } while (v <= 0);
      v = v * v * v;
      const uu = u();
      if (uu < 1 - 0.0331 * x * x * x * x) return d * v * theta;
      if (Math.log(uu) < 0.5 * x * x + d * (1 - v + Math.log(v))) return d * v * theta;
    }
  }
  function beta(u, a, b) { const x = gamma(u, a, 1), y = gamma(u, b, 1); return x / (x + y); }
  function triang(u, lo, mode, hi) {
    const c = (mode - lo) / (hi - lo), r = u();
    return r < c ? lo + Math.sqrt(r * (hi - lo) * (mode - lo)) : hi - Math.sqrt((1 - r) * (hi - lo) * (hi - mode));
  }
  function normcdf(z) { // Abramowitz-Stegun
    const t = 1 / (1 + 0.2316419 * Math.abs(z));
    const d = 0.3989423 * Math.exp(-z * z / 2);
    const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))));
    return z > 0 ? 1 - p : p;
  }
  function logcdf(z) { return Math.log(Math.max(normcdf(z), 1e-300)); }

  function pooled(sources, cfg, opts) {
    if (!opts.credibility) return 0.995;
    let lo = 0;
    for (const s of sources) {
      const r = cfg.admiralty.reliability[s.rel], c = cfg.admiralty.credibility[String(s.cred)];
      let p = r * c + (1 - r) * 0.5;
      p = Math.min(Math.max(p, 0.02), 0.98);
      lo += (s.independent === false ? opts.derivative : 1) * Math.log(p / (1 - p));
    }
    return Math.min(Math.max(1 / (1 + Math.exp(-lo)), 0.01), 0.995);
  }

  /* opts: {target, n, damageScale, recoveryMult, lagMean, rampMean, concentration,
   *        credibility, derivative, events:{SAS:true,...}, stage:1|0, grid:{t0iso, step, len}} */
  function run(cfg, opts) {
    const u = rng(opts.seed || 20261013);
    const tgt = cfg.targets[opts.target];
    const sites = Object.keys(tgt.prior_share);
    const alpha = opts.concentration ?? tgt.concentration;
    const lex = cfg.damage_lexicon;
    const evs = cfg.events.filter((e) => opts.events[e.id] !== false);
    const pri = evs.map((e) => {
      const [a, b] = lex[e.damage_class].beta;
      return {
        id: e.id, site: e.site, lo: min(e.t_min), hi: min(e.t_max), mode: min(e.t_mode || e.t_min),
        da: a * opts.damageScale, db: b, pi: pooled(e.sources, cfg, opts),
        rec: lex[e.damage_class].recovery_median_days * 1440 * opts.recoveryMult,
      };
    });
    const g0 = min(opts.grid.t0iso), step = opts.grid.step, len = opts.grid.len;
    const n = opts.n;
    const paths = new Float32Array(n * len);
    const logw = new Float64Array(n);
    const lagShape = cfg.onset.lag_shape, rampShape = cfg.onset.ramp_shape;
    const cons = (cfg.osint_constraints || []).filter((c) => (c.stage || 1) <= 1 && (c.target || opts.target) === opts.target);
    const onsetsAll = [];
    for (let i = 0; i < n; i++) {
      const g = sites.map((s) => gamma(u, Math.max(alpha * tgt.prior_share[s], 1e-3), 1));
      const gs = g.reduce((a, b) => a + b, 0);
      const w = g.map((x) => x / gs);
      const ev = pri.map((p) => {
        const T = triang(u, p.lo, p.mode, p.hi);
        const L = gamma(u, lagShape, opts.lagMean / lagShape);
        const Q = gamma(u, rampShape, opts.rampMean / rampShape);
        const D = u() < p.pi ? beta(u, p.da, p.db) : beta(u, 1, 60);
        const R = Math.exp(Math.log(p.rec) + cfg.recovery_log_sd * normal(u));
        return { id: p.id, site: p.site, T, L, Q, D, R, onset: T + L, full: T + L + Q };
      });
      const evAt = (tm) => {
        const keep = {};
        for (const s of sites) keep[s] = 1;
        for (const e of ev) {
          let x = Math.min(Math.max((tm - e.onset) / e.Q, 0), 1);
          const after = Math.max(tm - e.onset - e.Q, 0);
          x = x * Math.exp(-after / e.R) * e.D;
          if (keep[e.site] !== undefined) keep[e.site] *= 1 - x;
        }
        let o = 0;
        sites.forEach((s, k) => { o += w[k] * (1 - keep[s]); });
        return o;
      };
      for (let j = 0; j < len; j++) paths[i * len + j] = evAt(g0 + j * step);
      // Stage 1 soft constraints
      let ll = 0;
      if (opts.stage >= 1) {
        const byId = Object.fromEntries(ev.map((e) => [e.id, e]));
        for (const c of cons) {
          const e = c.event ? byId[c.event] : null;
          if (c.event && !e) continue;
          if (c.type === "onset_before") ll += logcdf((min(c.t) - e.onset) / (c.scale_min || 10));
          else if (c.type === "onset_after") ll += logcdf((e.onset - min(c.t)) / (c.scale_min || 10));
          else if (c.type === "strike_before") ll += logcdf((min(c.t) - e.T) / (c.scale_min || 10));
          else if (c.type === "report_delay") {
            const X = c.on === "onset" ? e.onset : e.T, m = c.mean_delay_min, d = min(c.t) - X;
            ll += d >= 0 ? -Math.log(m) - d / m : -Math.log(m) + d / 2;
          } else if (c.type === "increment") {
            const d = evAt(min(c.t1)) - evAt(min(c.t0));
            ll += -0.5 * ((d - c.value) / c.sd) ** 2;
          } else if (c.type === "level") {
            const v = 1 - evAt(min(c.t));
            ll += -0.5 * ((v - c.value) / c.sd) ** 2;
          }
        }
      }
      logw[i] = ll;
      onsetsAll.push(ev);
    }
    let mx = -Infinity;
    for (let i = 0; i < n; i++) mx = Math.max(mx, logw[i]);
    const wts = new Float64Array(n);
    let ws = 0;
    for (let i = 0; i < n; i++) { wts[i] = Math.exp(logw[i] - mx); ws += wts[i]; }
    let w2 = 0;
    for (let i = 0; i < n; i++) { wts[i] /= ws; w2 += wts[i] * wts[i]; }
    const ess = 1 / w2;
    const qs = [0.05, 0.25, 0.5, 0.75, 0.95];
    const out = { mean: [], q05: [], q25: [], q50: [], q75: [], q95: [] };
    const idx = new Array(n);
    for (let j = 0; j < len; j++) {
      let m = 0;
      for (let i = 0; i < n; i++) { idx[i] = i; m += wts[i] * paths[i * len + j]; }
      idx.sort((a, b) => paths[a * len + j] - paths[b * len + j]);
      let acc = 0, k = 0;
      const vals = [];
      for (const q of qs) {
        while (k < n - 1 && acc + wts[idx[k]] < q) { acc += wts[idx[k]]; k++; }
        vals.push(paths[idx[k] * len + j]);
      }
      out.mean.push(m); out.q05.push(vals[0]); out.q25.push(vals[1]); out.q50.push(vals[2]); out.q75.push(vals[3]); out.q95.push(vals[4]);
    }
    // weighted onset summaries
    const onsets = {};
    for (const p of pri) {
      const arr = onsetsAll.map((ev, i) => [ev.find((e) => e.id === p.id).onset, wts[i]]).sort((a, b) => a[0] - b[0]);
      const qv = (q) => { let acc = 0; for (const [v, w] of arr) { acc += w; if (acc >= q) return v; } return arr[arr.length - 1][0]; };
      onsets[p.id] = [qv(0.05), qv(0.5), qv(0.95)].map((m) => new Date(T0 + m * 60000).toISOString());
    }
    return { ...out, ess, onsets, credibility: Object.fromEntries(pri.map((p) => [p.id, p.pi])) };
  }

  window.EOFModel = { run };
})();
