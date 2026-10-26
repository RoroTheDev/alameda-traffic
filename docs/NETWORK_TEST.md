# Do Alameda CTC's HIN and PSN capture later serious crashes?

Reproduce: `python -m analysis.network_test --tol 20` (also `--tol 10`, `--tol 30`). Needs the official
HIN/PSN files in `data/restricted/alamedactc_official/` (Alameda CTC, restricted). Only summary
statistics are published here and in `analysis/results/`; per-segment flags stay in `data/restricted/`.

## Method
A quarter-mile segment is "on" a network if at least half of it lies within 20 m of the network's lines.
For each network: the share of killed-or-seriously-injured (KSI) crashes on the network (captured),
against the share of road length it covers, and against baselines of the **same road length**:
- **history**: segments ranked by a HIN-style severity score on 2018-2022 (10 per KSI crash, 5 per other
  injury crash, same road users as the outcome), tested on 2023-2025;
- **volume**: arterials ranked by HPMS traffic volume (a planner with no crash data).

2023-2025 is out of sample for the HIN (built on 2018-2022 crashes) and for the PSN (uses no crash data).
The HIN is a pedestrian and bicycle network; the PSN is all modes. Intervals: 95% bootstrap over segments.

## Result (2023-2025, tolerance 20 m)
| Network | Crashes tested | Road covered | Captured | Lift | History baseline | Volume baseline | Network minus history (95% CI) |
|---|---|---|---|---|---|---|---|
| HIN, ped+bike KSI | 479 | 10.8% (513 mi) | **52.6%** | 4.9x | 58.9% | 29.6% | -6.3 pts (-10.9, -1.6) |
| PSN, ped+bike KSI | 479 | 9.6% (455 mi) | **35.9%** | 3.8x | 56.4% | 25.9% | -20.5 pts (-26.0, -14.8) |
| PSN, all-mode KSI | 1,066 | 9.6% | 36.4% | 3.8x | 54.8% | 25.8% | -18.4 pts (-22.5, -14.6) |
| HIN, fatal only | 161 | 10.8% | 46.0% | 4.3x | 39.8% | 31.7% | +6.2 pts (-2.6, +14.2) |

Tolerance 10 m and 30 m give the same picture (HIN ped+bike capture 50.3% and 53.0%; PSN 33.4% and 36.3%;
the gaps to the history baseline stay within about 1 point of the 20 m values).

## What it shows
1. **Both networks find real risk.** Each captures 4-5 times its share of road length and clearly beats
   the traffic-volume baseline (HIN +23 points, PSN +10 points).
2. **Neither beats a simple crash-history ranking of the same length on the same crashes.** The HIN
   trails it by about 6 points for pedestrian and bicycle KSI; the PSN trails by about 20.
3. **Fatal crashes (161) are too few to separate any of them.**

## What it does not show
- **It does not show the HIN is poorly designed.** The HIN is smoothed into continuous corridors and edited
  by hand to close gaps and add known problem streets; a raw ranking of single segments is not
  constrained that way. Being a few points behind it is expected.
- **The PSN is built to find risk where there is no crash history,** so capturing less than a history
  ranking is not a failure. The test of that claim is different: does the PSN flag segments with no past
  KSI that go on to have more KSI than comparable unflagged segments of the same road class and
  traffic volume? Not yet tested.
- **Lengths are not the published ones.** Flagged segments cover 513 mi (HIN) and 455 mi (PSN), more than
  the 334 and 260 miles of published lines, because whole segments are flagged and divided roads
  appear twice. Baselines use the same flagged length, so the comparison is like for like, but the
  networks' per-mile performance as published would be somewhat higher.
- Three years of outcomes (2025 provisional). Bootstrap intervals ignore spatial correlation between
  neighbouring segments and are probably too narrow.
