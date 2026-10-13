# Yandex Ablation: Outage Attribution Study

This is an independent open-source intelligence assessment. It asks whether the October 2026 Ukrainian drone strikes on Yandex data centers (Sasovo, Kaluga, Vladimir) reduced Russian information-operation output.

**Answer.** No broad reduction is detectable across Telegram, Reddit and the web. One automated pipeline, the Pravda network, stalled for about 11 hours, starting within the hour after the Vladimir outage. The viral "bot traffic collapsed" chart measured Yandex's own web crawler.

| | |
|---|---|
| Report | [`REPORT.pdf`](REPORT.pdf): title page plus a three-page summary of method, results and limitations |
| Dashboard | [`docs/index.html`](docs/index.html): interactive and static, ready for GitHub Pages from `/docs` |
| Pipeline | [`pipeline/`](pipeline): collection, expected outage function, inference, export |
| Model priors and constraints | [`config/outage_model.json`](config/outage_model.json) |

## Method in brief

1. **Expected outage function.** A capacity-weighted damage model with Admiralty-graded source credibility, estimated in three Bayesian stages with sequential Monte Carlo: strike reports, then all published sources, then fused with IODA telemetry. It runs on a 10-minute grid.
2. **Outcomes.** Seasonal counterfactuals for 221 series:
   - Pravda network sitemaps (806,762 articles);
   - 46 Telegram channels;
   - web sitemaps;
   - Reddit (Arctic Shift);
   - Wikimedia;
   - IODA, RIPE and FIRMS controls.
3. **Inference.**
   - Placebo-in-time windows.
   - A seasonal-naive check.
   - A Bayesian hierarchical cross-platform model with a Yandex-dependency term derived from DNS.
   - 10-minute change-point timing.
   - Backlog tests.
   - Dose-response with HAC errors.
   - Theme contrasts.
   - FDR correction and equivalence bounds.
   - Analysis of competing hypotheses.

## Reproduce

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cd pipeline
for s in fetch_ioda fetch_misc fetch_pravda fetch_telegram fetch_web fetch_infra_map; do ../.venv/bin/python $s.py; done
../.venv/bin/python fetch_reddit.py all
for s in build_panel model_outage analysis bayes timing data_quality export_dashboard; do ../.venv/bin/python $s.py; done
cd .. && .venv/bin/python report/build_report.py
python3 -m http.server 8765 --directory docs
```

All times are UTC. Sources are graded with the NATO Admiralty system. Probability language follows ICD 203.
