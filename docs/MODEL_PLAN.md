# Model plan and readiness audit (written before any predictive model was built)

Audit run 2026-11-04 on `data/processed/analysis/segments.parquet` and `segment_year.parquet`
(32,462 quarter-mile surface segments, 2016-2025). Status: **no predictive model exists yet.** The only
regression so far is the PSN test (`docs/PSN_UNSEEN.md`).

## 1. What we predict (outputs)
Per segment, per year: the **expected number** of crashes, for three outcomes:
- injury and fatal crashes (about 4,300 a year on surface streets: the dense signal),
- killed-or-seriously-injured (KSI) crashes (about 336 a year: sparse),
- pedestrian and bicycle KSI (929 + 524 in ten years: very sparse).
Used for: ranking segments, comparing against the HIN, PSN and a history ranking, and the budget
allocation (expected crashes avoided = expected crashes x treatment effect).

## 2. Binary or count?
**Count (Poisson or negative binomial, plus gradient boosting with a Poisson loss), not binary.**
- Binary asks "did at least one KSI crash happen?". For KSI that loses little: 99.0% of segment-years are 0 and the
  maximum is 3. But it ignores segment length and the number of years, which are different for every
  segment, and it fails for injury crashes (many per segment).
- Safety research standardises on counts with an exposure offset (a "safety performance function"), and the
  allocation step needs an expected number of crashes, not a yes/no.
- Overdispersion is modest but real (variance is 2.0x the mean over 10-year totals; 92.9% of segments have no KSI
  versus 90.2% a Poisson would predict).
- Binary does have a place at the **crash** level: given an injury crash, is it severe? (logistic regression on
  speed class, road user, lighting, alcohol). Expected KSI = expected injury crashes x P(severe | crash). We will
  compare that two-part version against modelling KSI directly.

## 3. How predictable is this at all? (the ceiling)
Ranking segments by their own history and testing on the next period:

| History -> outcome | Spearman | Top 5% of segments capture | Top 10% |
|---|---|---|---|
| KSI 2016-19 -> KSI 2020-22 | 0.17 | 29.6% | 34.7% |
| KSI 2016-22 -> KSI 2023-25 | 0.25 | 38.6% | 46.2% |
| **Injury** 2016-22 -> KSI 2023-25 | 0.28 | **50.9%** | n/a |

Two lessons: serious crashes are mostly unpredictable block to block (even a perfect history ranking misses
about half), and **injury history predicts KSI better than KSI history does** because it is a denser signal. So the
model should be fit on injury crashes, with severity handled separately.

## 3b. Inputs now (what each segment has) and what is missing
| Input | Coverage | Status |
|---|---|---|
| Length, road class, intersections, signals at ends | 100% | have (stop signs unusable: OSM uneven) |
| Traffic volume (HPMS AADT) | 27% of segments (90% of arterials, 8% of local) | have; local streets need a class stand-in |
| Lane count | 25% | have, thin |
| **Posted speed** | 21% (Berkeley 93%, San Leandro 5%) | **biggest gap**; coverage varies by city, so never impute by class in the main model |
| Density, equity, CalEnviroScreen | 99.5% | have (tract level) |
| Distance to school / hospital / nursing home, bus stops | 100% | have (straight-line) |
| Oakland bike lanes with install year | Oakland only | have |
| Sidewalk / bike-lane tags (OSM) | arterials 55% / 63%, local 31% / 13% | **cheap: already downloaded, not yet extracted** |
| Street lighting, parking, road width (OSM) | 3-7% / 0% | not usable |
| Crossings, traffic calming (OSM nodes) | 39k / 6.7k nodes pulled | cheap: count per segment |
| Jobs per block (LODES), walk/bike/zero-car commute (ACS) | downloaded | cheap: join to tracts or blocks (activity proxy) |
| Pedestrian and bicycle counts | not joined | Oakland 2011-21 Excel sheets and Caltrans sites exist; parse |
| Land use / commercial frontage | none | needs parcel data or OSM shops; moderate |
| True speeds (INRIX), model volumes (AlaCC) | requested | waiting on Alameda CTC |
| Intersection control, sidewalks, lighting inventories | none | needs agencies |
| Alcohol outlets, transit boardings | none | public sources exist; optional |

Moderate overlap between inputs (Spearman): AADT-lanes 0.47, bus stops-density 0.61, intersections-density 0.40.
Fine for count models, but coefficients on correlated inputs must not be over-read.

## 4. Evaluation design
- **Split by time:** fit on 2016-2022, test on 2023-2025 (2025 provisional). Year effects for 2020 (COVID).
- **Split by space too:** neighbouring segments share conditions, so random folds leak. Use spatial blocks (tract or
  grid cells) for tuning. Published gradient-boosting gains over negative binomial mostly come from random
  splits, so the comparison has to be re-run on blocked folds before any claim.
- **Baselines every model must beat:** past-injury ranking, HIN, PSN, road class alone.
- **Metrics:** share of next-period KSI in the top 5%/10% of ranked segments, rank correlation, calibration by
  decile, Poisson deviance. Count-model effects also reported as rate ratios.
- **Empirical Bayes:** combine each segment's model prediction with its own history (shrinkage) for ranking,
  which corrects for regression to the mean. This is the version the allocation step should use.

## 5. Known limits
- Surface-street model only (freeways excluded); about 3,400 KSI over ten years, 99% of segment-years are zero.
- Pedestrian and bicycle KSI are too sparse for segment models; analyse at corridor level or with proxies.
- Under-reporting of minor, pedestrian and bicycle crashes in police data; 2024-25 provisional; Oakland PD
  coordinates were recovered by geocoding (`docs/COORDINATE_AUDIT.md`).
- Association, not cause: treatments cannot be evaluated from cross-sectional coefficients (placement bias);
  use before/after studies (Oakland bike lanes) and published crash modification factors.

## References checked
- Safety performance function form and exposure offsets: Tennessee SPF study, https://arxiv.org/pdf/1803.05074
- Negative binomial and overdispersion: https://arxiv.org/pdf/2506.16485
- GLMM + XGBoost SPF on urban arterials: https://www.nature.com/articles/s41598-026-56168-3
- Semi-parametric spatial negative binomial with non-linear AADT effects: https://www.sciencedirect.com/science/article/abs/pii/S0001457525004178
- Interpretable ML hurdle model for zero-inflated crash counts: https://www.mdpi.com/2076-3417/14/23/10790
- Not found in this search: empirical Bayes ranking procedure (Highway Safety Manual) and spatial-block validation for crash models.
