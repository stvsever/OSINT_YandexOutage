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

- **Outage measurement:** IODA active probing (Georgia Tech), RIPE Stat BGP data, NASA FIRMS fire detections and Yandex Cloud status incidents.
- **Outage reports, graded for reliability:** Yandex and regional-governor Telegram posts, NetBlocks, Cloudflare Radar, complaint trackers and Reuters.
- **Information-operation output:**
  - Pravda network sitemaps;
  - Telegram channels of state media, the Ministry of Defence broadcaster Zvezda, the Channel One Kremlin pool, military bloggers, foreign-audience outlets (InfoDefense, Strategic Culture, Sputnik Africa, DD Geopolitics) and EEAS-named sets (African Initiative);
  - WordPress feeds of African Initiative, RRN and R-FBI, and ukraina.ru sitemaps;
  - Reddit communities (Arctic Shift).
- **Controls:** independent Russian, Ukrainian, business and non-political Telegram channels; independent web outlets; non-political Reddit communities; other Russian hosting and access networks.
- **Positive control for user impact:** Russian Wikipedia pageviews. Yandex Search refers a substantial share of visits while Wikimedia's own infrastructure is unaffected, so a dip shows that the outage reached ordinary users.
- **Yandex dependency:** public DNS records (A, MX, NS) with RIPE network attribution for state and IO media and for 342 domains attributed to influence operations by VIGINUM and the EEAS.

## Method

The analysis first reconstructs when and how severely Yandex went offline. An expected-outage function models each strike as a capacity-weighted damage curve whose timing, onset lag, failure ramp, severity and recovery are inferred from the published reports, with each report weighted by its NATO Admiralty reliability grade. The model is estimated with sequential Monte Carlo on a 10-minute grid in three nested stages: strike reports only, all published reports, and finally fused with IODA's direct measurement of Yandex Cloud reachability. Comparing the second stage with the measurement shows how precisely open reporting alone captured the outage.

Each output series is then compared with what would have been expected without the strikes. A seasonal regression on hour of day, day of week and trend is fitted on the pre-strike period only, and deviations after each strike are measured against it out of sample. Whether a deviation is unusual is judged against placebo windows of the same length drawn from the pre-strike period and against the same weekdays in earlier weeks. A Bayesian hierarchical model pools the individual channels, language editions, communities and websites into platform groups, adds a term for outlets that depend on Yandex 360 mail, and accounts for news shocks that move all sources together; it is run for all posts, for war-related posts, for other posts and for their difference. In parallel, a 10-minute change-point analysis dates the start of any dip relative to the measured outage onset, because an outage can only explain a dip that begins after it. Dose-response regressions, false-discovery control, equivalence bounds and an analysis of competing hypotheses complete the inference.

Finally, `pipeline/verify.py` downloads random samples of every stored source again from the original service and compares them value by value, so that the published series can be checked against their origin.

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
