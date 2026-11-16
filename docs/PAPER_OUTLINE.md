# Paper outline (working): where serious crashes concentrate in Alameda County, who bears them, and where money prevents the most

Every number below is copied from a committed doc (linked) and carries that doc's caveats. Nothing here is new analysis.
Status tags: **solid** (holds across checks), **moderate** (one design or one split), **weak/inconclusive**, **demo** (assumed inputs).

## 1. Baseline (Part 1) - [BASELINE.md](BASELINE.md) - solid, descriptive
- 73,565 injury and fatal crashes 2016-2025; 43,365 on surface streets. Surface KSI 334 -> 362 a year (2016-19 vs 2022-25).
- Bicyclist KSI +29%, bicyclist deaths 3.2 -> 6.2 a year; pedestrians and motorcyclists flat.
- Night and late evening are 22% of injury crashes but 35% of KSI. People on foot, bike or motorcycle are 31% of injury crashes, 61% of KSI.
- Equity-priority tracts: KSI 28.0 vs 17.8 per 100k per year (RR 1.57). 10.8% of 400 m cells hold 37.6% of KSI; 80% of hot cells stay hot.
- Data contribution: coordinate audit shows the CCRS gap is by reporting agency (Oakland PD ~0% coords), fixed by TIMS geocodes ([COORDINATE_AUDIT.md](COORDINATE_AUDIT.md)); TIMS deaths exceed FARS by 9-11 in 2023-24 (unresolved).

## 2. Hot spots and vulnerable destinations (Part 2)
- **Official networks vs history** - [NETWORK_TEST.md](NETWORK_TEST.md), [PSN_UNSEEN.md](PSN_UNSEEN.md) - moderate. HIN holds 52.6% of ped+bike KSI on 10.8% of length against 58.9% for simple crash history; PSN 35.9%; both beat a volume baseline. PSN on streets with no past serious crash: IRR 1.49 (1.15-1.92) unadjusted, ~1.17 and not significant with school/transit controls; inconclusive.
- **Schools** - [SCHOOL_TEST.md](SCHOOL_TEST.md) - solid for burden. Child ped/bike commute-hour crashes near schools are 5.8x higher in session than summer; placebo hours 1.1-1.4x; commute-vs-placebo 4.8 (2.9-8.0); about 79% tied to the school day. Burden, not per-trip risk. Only one district calendar used.
- **Hospitals and nursing homes** - [DESTINATIONS.md](DESTINATIONS.md) - moderate. No excess near hospitals once road traits are controlled (RR 0.99); nursing homes +19% injury crashes with no distance fade (area effect). So weight destinations by who is there, not by crash rates.

## 3. Countermeasures (Part 3)
- **Oakland bike lanes** - [BIKE_LANES.md](BIKE_LANES.md) - inconclusive. Ratio of change 1.14 (0.96-1.35) for injuries, 0.94 without the 2020 cohort; no bike counts, so riding volume is confounded.
- **Stop signs, signals** - not done; OSM stop signs are unevenly mapped and the signal inventory is Oakland-only 2013. Needs a data decision (below).
- Planned reading: published CMFs (Caltrans LRSM, CMF Clearinghouse) are the effect sizes; local data cannot yet confirm them.

## 4. Prediction (Part 4) - [MODEL_RESULTS.md](MODEL_RESULTS.md) - moderate
- Road/exposure inputs beat road class alone: 31% vs 18% of KSI in the top 5% of length. Empirical Bayes beats raw history at the top 5% by 5-8 points; GBM ~ GLM. Severity (binary) AUC 0.557: severity given a crash is not predictable from these inputs.
- Temporal holdout (train 2016-22, test 2023-25) plus 5 km spatial-block CV.

## 5. Allocation (Part 5) - [ALLOCATION.md](ALLOCATION.md) - demo
- Method: exact multiple-choice knapsack, Caltrans CRFs, out-of-sample scoring. Costs are assumptions, so dollars and BCRs are not findings.
- Usable result: model-based optimisation beats raw-history optimisation by 5-32% more KSI avoided at equal spending; restricting to the HIN costs little at small budgets and a third at $50M; an equity floor costs ~2%.

## Gaps that decide whether this is a paper or a report
1. **Exposure.** Partly closed: 2024 counts downloaded and used at 120 placed sites ([EXPOSURE_COUNTS.md](EXPOSURE_COUNTS.md)): crashes rise with people at slope ~0.4 (safety in numbers), pedestrian volume is only partly predictable (R2 0.44) from land use, bicycle volume is not (0.08). Still open: other count years, Appendix C speeds (downloaded, not yet matched), exposure for all 32k segments.
2. AlaCC model volumes from Jennifer Ziebarth: pending, restricted data.
3. Real treatment costs (ask OakDOT or Alameda CTC for a unit-cost table; none found).
4. Stop-sign/signal evaluation: pick a city with good inventory data or drop it and say why.
5. Uncertainty for the headline allocation comparison (bootstrap over segments, several splits).
6. District school calendars beyond Fremont 2024-25.

## Suggested contributions (what is new vs Alameda CTC's HIN/PSN report)
Out-of-sample test of the HIN/PSN against 2023-25 crashes; school-day burden estimate with placebo hours; EB prediction with spatial CV; budget allocation scored on realised crashes; reproducible public pipeline.
