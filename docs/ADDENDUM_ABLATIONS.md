# Addendum 1 (2026-11-27): exploratory ablation of the traffic-volume input

**Status: exploratory, not preregistered.** Written and committed before the ablation is run. It adds analyses; it changes nothing in Part B.

## Why
The segment model (`analysis/model.py`) uses HPMS AADT as its traffic volume. The Alameda CTC travel model (cited as "the AlaCC Model";
2020 average-weekday volumes, restricted data) is now matched to segments (`analysis/alacc_volumes.py`, commit d0d855a). The two sources
agree weakly (log correlation 0.39 on 4,896 segments with both), and neither is a measurement on every street. So instead of picking
one, we test which one predicts later crashes better.

## Design (fixed here)
Same model, features, years and metrics as `analysis/model.py` (train 2016-22, test 2023-25; temporal holdout and 5 km spatial blocks;
GLM and GBM, with city; Empirical Bayes). Only the volume input changes:

| Variant | Volume input |
|---|---|
| A | HPMS: log(AADT) + missing flag (the current model) |
| B | AlaCC: log(model daily volume, both directions summed) + missing flag; "missing" = status not `ok` |
| C | both A and B inputs |
| D | no volume input (how much volume matters at all) |
| B-u | as B, but also using matches marked `uncertain` (the matching sensitivity) |

Missing values are filled with the median and flagged, exactly as `model.py` does for HPMS.

**Main comparison:** B vs A, KSI crashes, temporal holdout, EB (GBM + city): share of 2023-25 KSI on the top 5% of road length.
Also reported: top 10%, Poisson deviance on 2023-25 counts (GLM/GBM, not EB), the same on arterial segments only (where the AlaCC
Model has volumes), the ped+bike KSI and injury outcomes, and the spatial evaluation.
Uncertainty: paired bootstrap resampling streets (1,000 draws, seed 0), rankings held fixed, as in `model.py`.

## Reading rule
B is "better" only if the main comparison's 95% interval excludes 0 in B's favour; otherwise "no clear difference", which is a fine
result (it would mean the cheap public HPMS input is as good). Results are reported whatever they show.

## Analysis 2: redo of H1's failed positive control (exploratory)
In the confirmatory H1 run (`partb_b1_results.csv`) the positive control failed: the coefficient on log(HPMS AADT of the nearest
segment) was 0.036 (-0.151 to 0.223), where more traffic should mean more pedestrian crashes. Count sites are intersections, so one
nearest segment is a poor measure of the traffic there. `analysis/explore_positive_control.py` refits the H1 primary model
(same sites, crashes, window, controls and clustered errors; `partb_b1.py` is imported, not changed) with the volume term built as:
1. HPMS, nearest segment (reproduces the confirmatory number);
2. AlaCC Model, nearest segment;
3. AlaCC Model, major street: the largest street volume among segments within 30 m of the site;
4. AlaCC Model, intersection total: the sum over streets within 30 m (per street: the largest two-way volume, or the two largest
   one-way volumes added, for divided roads drawn as two lines);
5. HPMS, built as in 3 and 4 (so the HPMS-vs-model difference is not just the construction).
Reported for each: the volume coefficient (positive control passes if its 95% interval is above 0) and the pedestrian slope.
This does not replace the confirmatory H1 result; it is reported beside it.

## Data handling
Volumes from the AlaCC Model stay in `data/restricted/`. Only aggregate metrics are written to `analysis/results/`.
