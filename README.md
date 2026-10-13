# Yandex Ablation: Outage Attribution Study

This is an independent open-source intelligence assessment. It asks whether the October 2026 Ukrainian drone strikes on Yandex data centers (Sasovo, Kaluga, Vladimir) reduced Russian information-operation output.

**Bottom line.** The strikes caused a major Yandex Cloud outage but no broad reduction in Russian information operations. One automated pipeline, the Pravda network, stalled for about 11 hours, starting within the hour after the Vladimir outage. Telegram, Reddit and web outlets, including those of influence operations named by the EEAS, show no credible drop. None of 342 domains attributed to Russian influence operations by VIGINUM and the EEAS is hosted on Yandex.

| | |
|---|---|
| Report | [`REPORT.pdf`](REPORT.pdf): title page plus a four-page assessment with key judgments, method, results and limitations |
| Dashboard | [`docs/index.html`](docs/index.html): interactive and static, ready for GitHub Pages from `/docs` |
| Pipeline | [`pipeline/`](pipeline): collection, expected outage function, inference, verification, export |
| Configuration | [`config/study.json`](config/study.json): outage-model priors and OSINT constraints, and the VIGINUM Storm-1516 domain list |

## Method in brief

1. **Expected outage function.** A capacity-weighted damage model with Admiralty-graded source credibility, estimated in three Bayesian stages with sequential Monte Carlo: strike reports, then all published sources, then fused with IODA telemetry. It runs on a 10-minute grid.
2. **Outcomes.** Seasonal counterfactuals for 228 series:
   - Pravda network sitemaps (806,762 articles on 88 sites);
   - 49 Telegram channels, including African Initiative and other outlets named in the EEAS 4th FIMI threat report;
   - web publishing (sitemaps and WordPress APIs of ukraina.ru, African Initiative, RRN, R-FBI and two independent controls);
   - Reddit (Arctic Shift);
   - Wikimedia;
   - IODA, RIPE and FIRMS controls.
3. **Actor infrastructure.** Public DNS and RIPE network attribution for 52 media domains and 342 domains attributed to Storm-1516, African Initiative, RRN, R-FBI and the Pravda network (VIGINUM, EEAS).
4. **Inference.**
   - Placebo-in-time windows and a same-weekday check.
   - A Bayesian hierarchical cross-platform model with a Yandex-dependency term derived from DNS, run for all posts, war posts, non-war posts and their contrast.
   - 10-minute change-point timing and backlog tests.
   - Dose-response with HAC errors.
   - FDR correction and equivalence bounds.
   - Analysis of competing hypotheses.
5. **Verification.** `pipeline/verify.py` downloads random samples of every stored source again and compares them value by value.

## Dashboard

Views: overview, attribution graph (left to right, top down or radial), timeline, timing lab, effects, event study, evidence and method. Each control in the left panel shows which views it affects. Deep links such as `docs/index.html#graph:radial` open a view directly.

## Reproduce

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cd pipeline
for s in fetch_ioda fetch_misc fetch_pravda fetch_telegram fetch_web fetch_infra_map fetch_actor_infra; do ../.venv/bin/python $s.py; done
../.venv/bin/python fetch_reddit.py all
for s in build_panel model_outage analysis bayes timing data_quality verify export_dashboard; do ../.venv/bin/python $s.py; done
cd .. && .venv/bin/python report/build_report.py
python3 -m http.server 8765 --directory docs
```

All times are UTC. Sources are graded with the NATO Admiralty system. Likelihood language follows ICD 203.
