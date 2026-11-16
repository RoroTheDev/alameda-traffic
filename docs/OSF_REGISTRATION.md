# OSF registration draft (secondary data analysis)

Draft for the OSF "Secondary Data Analysis" registration template. Paste each section into the matching OSF field.
**Two parts, kept separate on purpose.** Part A records analyses that were already run before this registration, with the
design stated in each script's header. Those are *not* preregistered and are labelled that way. Part B is analyses not yet run, which
are preregistered. Items in [brackets] are for you to fill in or confirm before submitting.

## Title
Where serious crashes concentrate in Alameda County, who bears them, and where safety money prevents the most: an out-of-sample study with exposure checks

## Authors / affiliation
[names, affiliation]. Analysis code was written with AI assistance (Claude Code, Anthropic) and reviewed by the author(s) [keep or edit this line].

## Description
Police-reported injury and fatal crashes in Alameda County, CA, 2016-2025, are used to (1) describe the baseline, (2) test which
places and destinations carry serious-crash burden (Alameda CTC's High-Injury and Proactive Safety Networks, schools, hospitals,
nursing homes, pedestrian and bicycle exposure), (3) look for effects of countermeasures, (4) predict serious crashes by street segment,
and (5) compare ways to allocate a fixed safety budget, scored on crashes that happened after the choices were made.
Public repository with all code and a git history that timestamps each analysis: https://github.com/RoroTheDev/alameda-traffic

## Data (all secondary, already collected by others)
- Crashes: CHP SWITRS via UC Berkeley TIMS (geocodes, severity), linked to CCRS person and party records. [TIMS extract date: fill in.]
- Roads and context: OpenStreetMap, HPMS traffic volume, county centerlines, Census, CDE/NCES schools, hospitals and nursing homes, GTFS stops, Oakland bikeway projects.
- Alameda CTC High-Injury Network (2024), Proactive Safety Network (concept), and 2024 manual bicycle/pedestrian counts, Appendix C 2024 corridor speeds.
- Not available to this registration and never posted: Alameda CTC travel-model volumes (restricted by agreement). No data are uploaded to OSF.

## Disclosure of what was already known (required for secondary data)
All crash data 2016-2025 had been downloaded and examined by the analysis team before registration. Specifically, the analyses in
Part A were run and their results seen (commit dates in the repository: 2026-10-25 to 2026-11-15). Part B analyses had not been run.
The registration is therefore confirmatory only for Part B. For Part A it is a time-stamped record of design and results, and any
reading of Part A as hypothesis testing should be discounted accordingly.

## Part A: analyses already run (not preregistered; designs from the script headers)
| Analysis | Question | Design (fixed in code before results) | Result summary |
|---|---|---|---|
| Baseline (`analysis/baseline.py`) | trends, when, who, burden, hot-spot persistence | descriptive; Gi* on a 400 m grid | KSI up 8%; night 35% of KSI; equity tracts rate ratio 1.57 |
| HIN/PSN out-of-sample (`network_test.py`) | do official networks capture 2023-25 serious crashes vs equal-length history and volume baselines | share of KSI on network vs length share, bootstrap by segment | HIN 52.6% of ped/bike KSI on 10.8% of length |
| PSN unseen risk (`psn_unseen.py`) | does PSN flag risk where there is no crash history | Poisson IRR on segments with 0 KSI in 2018-22, street-clustered | IRR 1.49 unadjusted, about 1.17 adjusted, not significant |
| Schools (`school_test.py`) | child ped/bike injuries near schools, in session vs summer | commute-hour x in-session interaction with placebo hours | 5.8x at commute hours vs placebos 1.1-1.4x |
| Model (`model.py`) | predict segment crashes | Poisson GLM and GBM, Empirical Bayes, temporal and 5 km spatial holdout, no tuning on test years | model beats road class and raw history |
| Bike lanes (`bike_lanes.py`) | Oakland bikeway before/after | matched stacked difference-in-differences, cell bootstrap | inconclusive (1.14, 0.96-1.35) |
| Hospitals, nursing homes (`destinations.py`) | excess crashes near destinations | Poisson IRR, 400 m, street-clustered | hospitals 0.99; nursing homes 1.19 |
| Allocation demo (`allocate.py`) | which strategy avoids most KSI at equal spend | knapsack, Caltrans CRFs, scored on 2023-25 | model-based beats raw-history by 5-32% (clear only at $15M and $50M, see bootstrap row) |
| Allocation bootstrap (`allocate_bootstrap.py`) | uncertainty for the strategy comparison | resample streets, paired differences, 2,000 draws | model/raw-history ratio 1.22 (0.94-1.65), 1.05 (0.92-1.17), 1.26 (1.14-1.41), 1.32 (1.23-1.43) at $1M, $5M, $15M, $50M |
| Counts exposure (`counts.py`, `counts_exposure.py`) | do crashes track pedestrians and bicyclists counted | Poisson slope on log(count), 50 m, 2020-25 | ped slope 0.41 (0.24-0.57) |

**Known things changed after seeing results (be explicit):**
- The first allocation comparison of "HIN-first" and "PSN-first" was unfair to those networks and was replaced by the current
  design (random choice within the network, plus optimising within the network only).
- School calendars: only the Fremont 2024-25 calendar was found; the core-window approach was chosen because of that.
- [add any others you remember: extra robustness checks added after seeing a first result, dropped or reworded outcomes.]
Costs of treatments in the allocation are assumptions, not estimates; results in dollars are not findings.

## Part B: preregistered analyses (not yet run)

**B1. Exposure replication across count years.** Alameda CTC counts for 2016, 2018, 2020, 2022 (2017 if usable) at the same sites.
- Hypothesis: the slope of pedestrian injury crashes on log(pedestrians counted) is below 1 in a pooled panel (site and year fixed effects), as in the 2024-only estimate of 0.41.
- Model: Poisson, crashes within 50 m in the 3 calendar years centred on each count year, offset log(years), predictors log(pedestrians + 1), log(bicycles + e-bikes + 1), count year; standard errors clustered by site.
- Supports hypothesis if the pooled 95% interval for the pedestrian slope lies below 1; bicyclist slope reported as secondary. Sites unplaced by the geocoder are listed, not hand-placed after seeing outcomes.

**B2. Allocation under rolling origins.** Two additional splits: train through 2020 / test 2021-23; train through 2021 / test 2022-24 (plus the original 2022 / 2023-25).
- Hypotheses: (i) at $15M and $50M, model-based (Empirical Bayes) optimisation realises more KSI avoided per year than optimisation on raw history; at $1M and $5M no direction is predicted (the 2022 split's intervals include 1 there); (ii) optimising only on the High-Injury Network realises less than unrestricted optimisation at $50M. **Note: the choice of budgets in (i) was informed by the already-seen 2022 split (Part A), so B2 is confirmatory only for the two new splits.**
- Method as in `allocate.py` and `allocate_bootstrap.py` (base costs; ratios with street-resampled 95% intervals). Result for (i) is "supported" if the lower interval bound of the model/raw-history ratio is above 1 at both $15M and $50M in each of the two new splits; otherwise "not supported". (ii) is supported if the lower bound of the unrestricted/HIN-only ratio is above 1 at $50M in both new splits.

**B3. Corridor speeds as a covariate.** 2024 Appendix C sample speeds (PM and AM peak, Tier 1 and 2 arterials), matched to segments by street name and jurisdiction.
- Question (two-sided, direction not predicted since congestion lowers speed): on matched arterial segments, does adding log(speed) improve out-of-sample 2023-25 KSI prediction over the current model (Poisson deviance and share of KSI on the top 5% of length)?
- Match rate and unmatched corridors are reported; no hand matching after seeing outcomes.

**B4. Stop signs and signals: conditional.** Only if a city inventory with installation dates is obtained before outcomes are examined.
- Design copied from `bike_lanes.py`: matched stacked difference-in-differences (cohort x road class x prior-crash bin, 3 years before/after, treatment year dropped, cell bootstrap), outcomes injury crashes and KSI; the 2020 cohort and a "later-treated controls" check reported as pre-specified checks.
- If no usable inventory exists, this part is dropped and the paper says so.

## Analysis conventions for all Part B work
- Segments are quarter-mile surface-street segments; KSI = TIMS severity 1-2; surface streets only.
- Inference: 95% intervals from street-clustered or street-resampled bootstrap or robust standard errors; no adjustment across the small number of pre-specified outcomes, results labelled by status.
- No change to primary outcomes after seeing results. Additional analyses will be labelled exploratory.
- Null or imprecise results are reported as such, and not as evidence of no effect.

## Reporting and deviations
Any departure from Part B will be listed in the paper and added as a dated note to this registration.
