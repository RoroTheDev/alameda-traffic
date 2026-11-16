# Do crashes track how many people walk and bike? (exposure check, Parts 2-3)

Reproduce: `python -m analysis.counts` then `python -m analysis.counts_exposure`. Tables: `analysis/results/counts_exposure_*.csv`.
Source: Alameda CTC public 2024 Active Transportation count program (manual counts by Wiltec for Kittelson, fall 2024).
The count files themselves are not redistributed here (local `data/manual/`, not in the repo).

## Data and what was lost
- 148 count workbooks (the program says 150 locations; two files are not in the public zip). One two-hour weekday count each.
  Only the 4-6 pm sheet is used: it is the one period every location has. Counts are summed over the four legs and 32 fifteen-minute rows.
- 121 of 148 were placed on the map by the street-name geocoder, 120 after merging two sites at one intersection. 27 were not
  (street names that differ from the county centerlines, such as Union City's Alvarado-Niles Road and several Fremont and
  Livermore sites). One location's city is mislabeled in the workbook (location 91, Oakland streets labeled Dublin) and falls in the unplaced group.
- Sites are chosen by Alameda CTC (busy corridors, many downtown); 37 of 120 are Oakland, 15 Fremont, 11 Hayward, 10 Berkeley.

## Result: crashes rise with people, much more slowly than people
Poisson regression of pedestrian-involved injury crashes within 50 m, 2020-2025, on log(people counted + 1):

| Outcome | Slope on log(count) | 95% CI | Crashes |
|---|---|---|---|
| Pedestrian injury crashes (controls: traffic volume, road class) | **0.41** | 0.24-0.57 | 123 |
| same, adding the bicyclist count | 0.53 | 0.27-0.79 | 123 |
| Bicyclist injury crashes (on bicycle + e-bike count) | 0.24 | 0.00-0.48 | 117 |
| same, adding the pedestrian count | 0.03 | -0.29-0.35 | 117 |
| Pedestrian + bicyclist killed or seriously injured (on pedestrian count) | 0.21 | -0.03-0.45 | 35 |

Checks agree: 100 m radius gives 0.45; 2016-2025 crashes 0.41; no controls 0.38.
A slope of 1 would mean crashes proportional to people. Raw version: sorted into four equal groups by pedestrians counted
(mean 16, 46, 106, 449 in two hours), pedestrian crashes per site per year are 0.08, 0.12, 0.17, 0.32 (14, 22, 30 and 57
crashes at 30 sites each), while crashes per 100,000 pedestrians counted fall from about 3,000 to 420. So the busiest crossings
have roughly 30 times the walkers of the quietest and about 4 times the crashes.

**What this does and does not say.** It is the "safety in numbers" pattern seen in many cities: risk per walker is lower where
more people walk. It does not show that adding walkers makes a street safer; busy places also differ in speeds, signal
timing and design, and the sites are not random. Noise in a single two-hour count pulls the slope toward zero. With the
between-site spread we see (standard deviation 1.4 in log pedestrians) a day-to-day error of 50% would keep about 90% of the
slope and 80% would keep about 79% (that error size is assumed, not measured), so noise cannot explain 0.4 against 1. 120 sites
and 123 crashes give wide intervals, and the bicyclist result is borderline.

**Why it matters for the paper.** Crash counts alone overstate danger at busy crossings and understate it at quiet ones.
Any hot-spot list ranked by crash counts is a ranking of places people walk as much as of risky streets. Per-person
risk is highest at low-volume sites, which are also where few crashes accumulate and where hot-spot methods find nothing.
Exposure-adjusted ranking needs counts at more than 120 places.

## Can we estimate exposure everywhere from data we already have?
Leave-one-out ridge regression on traffic volume, lanes, density, bus stops, schools, jobs, income, poverty, road class:
**pedestrian counts R-squared 0.44** (rank correlation 0.65 between predicted and counted), **bicycle counts 0.08** (rank 0.42).
Pedestrian volume is somewhat predictable from land use; bicycle volume is not. A modeled pedestrian exposure covariate for all
32,462 segments is feasible but would carry large errors (R-squared under one half, on sites that are not a random sample).

## Not done / next
- 2016-2022 count years (not downloaded) would give the same sites at several dates, enough for a before/after check where
  a count site sits on a bikeway project. The sites are too sparse for that to be powerful.
- Appendix C (2024 corridor speeds) is a separate covariate; not yet used (name-matching corridors to segments).
- 27 unplaced sites can be placed by hand if more sites are needed.
