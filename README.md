# Yandex Ablation: Did the Data-Center Strikes Silence Russian Information Operations?

This study systematically investigates whether the October 2026 Ukrainian drone strikes on Yandex data centers in Sasovo, Kaluga and Vladimir reduced the output of Russian information operations. The strikes are treated as a natural experiment: an expected-outage function reconstructed from graded public reports is validated against measured outages, and the output of publicly attributed influence operations, state media and military bloggers is compared with seasonal counterfactuals, control sources and placebo periods.

**Bottom line.** The strikes caused a major Yandex Cloud outage but no broad reduction in Russian information operations. One automated pipeline, the Pravda network, stalled for about 11 hours, starting within the hour after the Vladimir outage. Telegram channels of state media, military bloggers and foreign-audience outlets, Reddit communities and the websites of influence operations named by the EEAS show no credible drop, and none of 342 domains attributed to Russian influence operations by VIGINUM and the EEAS is hosted on Yandex.

## Repository

| Path | Contents |
|---|---|
| [`REPORT.pdf`](REPORT.pdf) | The assessment: abstract, bottom line, key judgments, approach, results, data verification, conclusion and references |
| [`dashboard/`](dashboard) | Interactive dashboard (static HTML and D3); open `dashboard/index.html` |
| [`pipeline/`](pipeline) | Data collection, outage model, statistical analysis, verification and dashboard export |
| [`report/`](report) | Builder for `REPORT.pdf` |
| [`config/study.json`](config/study.json) | Outage-model priors and OSINT constraints, and the VIGINUM Storm-1516 domain list |
| [`.github/workflows/pages.yml`](.github/workflows/pages.yml) | Publishes `dashboard/` to GitHub Pages when the repository is public |

## Data

| Role in the study | Sources |
|---|---|
| Outage measurement | IODA active probing (Georgia Tech), RIPE Stat BGP, NASA FIRMS fire detections, Yandex Cloud status incidents |
| Outage reports (graded) | Yandex and regional-governor Telegram posts, NetBlocks, Cloudflare Radar, complaint trackers, Reuters |
| Information-operation output | Pravda network sitemaps; Telegram channels of state media, the Ministry of Defence broadcaster Zvezda, the Channel One Kremlin pool, military bloggers, foreign-audience outlets (InfoDefense, Strategic Culture, Sputnik Africa, DD Geopolitics) and EEAS-named sets (African Initiative); WordPress feeds of African Initiative, RRN and R-FBI; ukraina.ru sitemaps; Reddit communities (Arctic Shift) |
| Controls | Independent Russian, Ukrainian, business and non-political Telegram channels; independent web outlets; non-political Reddit communities; other Russian hosting and access networks |
| Positive control for user impact | Russian Wikipedia pageviews (Yandex Search refers a substantial share of visits, while Wikimedia's own infrastructure is unaffected) |
| Yandex dependency | Public DNS (A, MX, NS) with RIPE network attribution for state and IO media and for 342 domains attributed by VIGINUM and the EEAS |

## Method

1. **Expected outage function.** A capacity-weighted damage model with Admiralty-graded source credibility, estimated in three Bayesian stages with sequential Monte Carlo (strike reports, all published reports, fusion with IODA telemetry) on a 10-minute grid.
2. **Counterfactuals.** Out-of-sample seasonal regressions per series, fitted on the pre-strike baseline.
3. **Inference.** Placebo-in-time windows and a same-weekday check; a Bayesian hierarchical cross-platform model with a Yandex-dependency term, run for all posts, war posts, non-war posts and their contrast; 10-minute change-point timing with backlog tests; dose-response with HAC errors; false-discovery control; equivalence bounds; analysis of competing hypotheses.
4. **Verification.** `pipeline/verify.py` downloads random samples of every stored source again and compares them value by value.

## Reproduce

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
cd pipeline
for s in fetch_ioda fetch_misc fetch_pravda fetch_telegram fetch_web fetch_infra_map fetch_actor_infra; do ../.venv/bin/python $s.py; done
../.venv/bin/python fetch_reddit.py all
for s in build_panel model_outage analysis bayes timing data_quality verify export_dashboard; do ../.venv/bin/python $s.py; done
cd .. && .venv/bin/python report/build_report.py
python3 -m http.server 8765 --directory dashboard
```

All times are UTC. Sources are graded with the NATO Admiralty system; likelihood language follows ICD 203. Deep links such as `dashboard/index.html#graph:radial` open a dashboard view directly.
