# Crash frequency model: results

Reproduce: `python -m analysis.segments` -> `python -m analysis.features` -> `python -m analysis.model`.
Design and data audit: `docs/MODEL_PLAN.md`. Tables: `analysis/results/model_*.csv`.

## What was built
- **Unit:** 32,462 quarter-mile surface street segments. **Fit on 2016-2022, tested on 2023-2025.**
- **Count models with an exposure offset** (not binary): Poisson regression ("GLM") and gradient boosting
  ("GBM", Poisson loss), each with and without city, predicting crashes per segment-year for injury crashes,
  killed-or-seriously-injured (KSI) crashes, and pedestrian + bicycle injury crashes.
- **Empirical Bayes (EB):** blends each segment's model prediction with its own crash history, weighted by the
  fitted overdispersion (NB alpha 0.9-1.0), which corrects for regression to the mean.
- **Binary severity model** (logistic): P(KSI | injury crash) from segment traits, used for a two-part KSI estimate.
- **Inputs (no crash history):** road class, AADT, lanes, intersections, signals, crossings, traffic calming,
  OSM sidewalk and bike-lane tags, schools, hospitals and nursing homes, bus stops, density, jobs, walk/bike/no-car
  commute shares, income, poverty, equity layers, Oakland bike lanes.
- **Two tests:** forward in time only, and forward in time with whole 5 km grid cells held out (no leakage across
  space or time). Metric: share of 2023-25 crashes on the top 5% or 10% of road **length**, ranked by predicted
  rate (the same yardstick as `docs/NETWORK_TEST.md`). Intervals are paired 95% bootstrap over segments.

## Results: share of 2023-25 KSI crashes on the top 5% / 10% of road length (1,066 crashes)
| Ranking | Forward in time | Cells held out too |
|---|---|---|
| Road class alone | 17.7% / 42.9% | 17.7% / 42.9% |
| Model inputs only (GLM + city) | 30.8% / 47.3% | 29.9% / 46.2% |
| Model inputs only (GBM + city) | 31.3% / 47.7% | 27.0% / 44.3% |
| Past crashes only | 28.0% / 50.8% | 28.0% / 50.8% |
| **EB: model + own history (GBM + city)** | **35.6% / 50.6%** | **33.5% / 48.6%** |

Paired differences (A minus B, 95% interval):
| Comparison | Top 5% | Top 10% |
|---|---|---|
| EB vs past crashes, forward in time | **+7.6 pts (5.1, 10.2)** | -0.3 (-3.2, 2.4) |
| EB vs past crashes, cells held out | **+5.4 pts (2.7, 8.2)** | -2.3 (-5.0, 0.4) |
| Model inputs only vs road class, forward in time | **+13.6 pts (9.6, 17.5)** | +4.9 (1.3, 8.3) |
| GBM vs GLM, forward in time | +0.6 (-2.0, 3.0) | +0.5 (-1.7, 2.7) |
| GBM vs GLM, cells held out | -2.9 (-5.8, -0.2) | -1.9 (-4.6, 0.8) |

Pedestrian + bicycle KSI (479 crashes), top 10% of length: road class 39.2%, model inputs only 56.2%
(GBM + city), past crashes 55.5%, EB 60.1%. EB beats past crashes by +4.6 pts (1.7, 7.5).
Injury crashes (12,195): past crashes 61.5%, model inputs only 51.3%, EB 61.9%, i.e. no gain over history
(+0.5 pts, -0.2 to 1.1).

## What it shows
1. **The inputs carry real signal beyond road class,** most of all at the very top: 31% versus 18% of KSI in
   the worst 5% of road, and it holds with whole neighbourhoods held out (30% vs 18%).
2. **Blending with history beats history alone for serious crashes at tight budgets** (+5 to +8 points in the
   worst 5% of road, clearly above zero). At a 10% budget there is no difference. For ordinary injury
   crashes the history is dense enough that the model adds nothing.
3. **Gradient boosting is no better than the plain regression here.** The differences are within noise, and with
   cells held out GBM is slightly worse. The published ML gains rest mostly on random splits; this test uses
   blocked splits. Use the regression: it is simpler and can be read.
4. **The binary severity model is weak** (AUC 0.557 on 12,195 crashes; base rate 8.7%). Whether an injury crash
   becomes a serious one depends on speed, road user and impact, which segment traits do not capture. The
   two-part estimate is not better than modelling KSI directly or ranking by expected injuries.
5. **A data-fitted model beats the hand-scored network at similar length.** For pedestrian and bicycle KSI the
   model-only ranking captures 56% (52% with cells held out) of crashes on 10% of road, against 53% for the
   HIN and 36% for the PSN (`docs/NETWORK_TEST.md`). The comparison is not strict: different units, and this
   model is fit on the county's own 2016-22 crashes. It does support replacing hand-assigned weights with
   estimated ones.

## Reading the coefficients (`model_irr_inj.csv`, `model_irr_ksi.csv`)
Rate ratios, cluster-robust by street. Clear associations: road class (primary and secondary about 2.5x
residential), number of intersections (about +6% each), bus stops, marked crossings, lower income and higher
poverty, equity-priority areas. **Many of these are signs of how many people are on the street, not
hazards**: bus stops, marked crossings and mapped sidewalks track pedestrian presence. Lane count and
traffic volume are weak once class is in the model. Bike lanes (Oakland and OSM tags) show no
association. Several tract-level shares (bike share) have very wide intervals. None of this is causal.

## Limits
- **Serious crashes are barely predictable block to block** (rank correlation about 0.22); the best top-5%
  capture is about 36%.
- No true speed limits, no pedestrian counts, no land use; speed coverage varies by city.
- Three test years (2025 provisional); 1,066 KSI and 479 pedestrian/bicycle KSI crashes in the test period.
- Surface streets only; hyperparameters fixed, not tuned.
- Predicted totals match observed ones to within about 8% (injury 1.08x, KSI 0.92x), so the scale is usable.

## Output
`data/processed/analysis/model_predictions.parquet` (fit on all ten years): expected injury, KSI and
pedestrian + bicycle injury crashes per segment-year from the GLM and GBM, plus the EB estimate.
It uses only openly licensed inputs, so it can be released. It feeds the allocation step.
