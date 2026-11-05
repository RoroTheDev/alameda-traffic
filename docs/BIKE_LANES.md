# Did Oakland's completed bikeway projects change crashes on their streets? (Part 3)

Reproduce: `python -m analysis.bike_lanes`. Tables: `analysis/results/bike_lanes_results.csv`, `bike_lanes_event_study.csv`.

## Design
- **Treated:** 236 Oakland quarter-mile segments (a project covers at least half of the segment) whose first and only completed
  project was finished in 2018-2022. **Controls:** 4,685 Oakland segments with no completed project through 2025.
- 3 years before and 3 years after the project year (clipped to 2016-2025), project year dropped.
- Within each project-year cohort, treated and control segments are matched on road class (local / collector / arterial) and on
  injury crashes in the pre window (0, 1, 2, 3-4, 5+); controls are re-weighted to the treated count. This keeps "built where
  crashes were high, then crashes fell back" from looking like an effect.
- Effect = (treated after / before) / (controls after / before), per-year rates. Below 1 means treated streets improved
  relative to similar streets. 95% intervals from a cell-stratified bootstrap over segments.

## Result: no sign that crashes fell on treated streets
| Outcome | Treated per yr before -> after | Matched controls before -> after | Ratio of change (95%) |
|---|---|---|---|
| Injury crashes | 141.7 -> 130.3 | 136.5 -> 109.8 | **1.14** (0.96-1.35) |
| Killed or seriously injured | 11.8 -> 10.7 | 8.3 -> 8.4 | 0.89 (0.57-1.35) |
| Pedestrian + bicyclist injury | 41.0 -> 37.0 | 32.5 -> 21.3 | **1.38** (1.04-1.78) |
| Bicyclist injury | 11.8 -> 9.7 | 10.7 -> 6.8 | 1.28 (0.70-2.13) |
| Pedestrian injury | 29.2 -> 27.3 | 21.8 -> 14.5 | 1.41 (1.01-1.98) |
| Pedestrian + bicyclist KSI | 5.2 -> 6.0 | 3.6 -> 3.1 | 1.34 (0.77-2.51) |

Treated streets fell a little; similar streets fell more. Nothing here shows an improvement, and the ped+bike injury result leans
the other way. **I would not read that as "bike lanes cause more crashes"** (see below). The honest summary is: not detectable
either way with this design, and the estimate moves a lot with the check.

## It is not stable
Injury crashes: 1.06 without matching on prior crashes; 1.31 against streets that got a bikeway later; 1.24 arterials only;
0.94 collectors and locals only; **0.94 (0.81-1.09) when the 2020 cohort (114 of the 236 segments) is dropped**, against 1.14
with it. Ped+bike injury ranges 0.89 to 1.68 across the same checks; KSI 0.79 to 2.09. By type, painted lanes 1.21 injury / 1.46
ped+bike, protected (buffered or separated) 1.06 / 1.01 with 46 segments, boulevards 1.22 / 1.24. Year-by-year, treated and
control streets move together before the project (ratios 0.9-1.1), then treated streets sit above controls after it; matching on
prior crashes makes the before years line up by construction, so the cleaner pre-trend evidence is the unmatched event study (0.92
to 1.14 before, injury 0.92-1.13).

## Why this cannot show whether bike lanes work
- **No bicycle or pedestrian volumes.** A new lane brings more riders and more walking; more people exposed means more crashes
  even if risk per rider fell. This is the biggest reason the sign cannot be read as safety.
- **Where lanes go is not random.** Many projects came with repaving or sit on planned corridors with riders. 2020 projects
  coincide with COVID traffic shifts and Slow Streets.
- **Small counts:** 6 to 12 KSI a year on treated streets. Protected lanes, the type most studied, have 46 segments.
- Spillover to nearby streets and the exact month of opening are ignored (the project year is dropped instead).
- Oakland only; crashes are police-reported.

For the paper: report this as an inconclusive observational check, not as evidence for or against bike lanes. The published
crash-modification factors (CMF Clearinghouse, Caltrans LRSM) remain the effect sizes to use, and need exposure data to test
locally.
