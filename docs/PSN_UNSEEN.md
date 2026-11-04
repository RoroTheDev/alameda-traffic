# Does the Proactive Safety Network find risk where there is no crash history?

Reproduce: `python -m analysis.psn_unseen`. Needs the official PSN file in
`data/restricted/alamedactc_official/` (restricted); only summary tables are published
(`analysis/results/psn_unseen_*.csv`).

## Why this test
The PSN uses no crash data (road traits plus who is nearby) and exists to find risk *before* people
are hurt. A crash-history ranking beats it on streets that already had crashes
(`docs/NETWORK_TEST.md`), so the fair question is about streets that had none.

## Design (primary analysis fixed before looking at results)
- **Sample:** quarter-mile segments with **zero killed-or-seriously-injured (KSI) crashes in 2018-2022**
  (31,128 of 32,462 segments; 2,486 are PSN-flagged, 371 miles).
- **Outcome:** KSI crashes in 2023-2025 (693 events, 199 on PSN-flagged segments).
- **Model:** Poisson regression with an exposure offset (segment miles x 3 years), PSN flag, road class,
  log traffic volume, lane count and city; standard errors clustered by street name.
- **Effect:** incidence rate ratio (IRR), PSN-flagged vs comparable unflagged. 1.00 means no difference.

## Results
| Analysis | Events (on PSN) | IRR | 95% CI |
|---|---|---|---|
| **Primary: no KSI history, KSI outcome** | 693 (199) | **1.49** | 1.15 - 1.92 |
| Unadjusted, no controls | 693 (199) | 4.42 | 3.66 - 5.33 |
| Outcome = all injury crashes | 8,211 (2,414) | 1.58 | 1.34 - 1.86 |
| Arterials only | 472 (192) | 1.53 | 1.18 - 1.98 |
| All segments, controlling for 2018-22 KSI history | 1,066 (392) | 1.36 | 1.12 - 1.64 |
| Add school, transit, density and equity controls | 693 (199) | 1.17 | 0.90 - 1.53 |
| Stricter sample: **no injury of any kind** in 2018-22, KSI outcome | 181 (22) | 0.88 | 0.49 - 1.58 |
| Stricter sample, injury outcome | 1,747 (183) | 0.99 | 0.74 - 1.33 |

## What it shows
1. **Most of the raw gap is road type and traffic.** Unadjusted, PSN streets have 4.4 times the rate; matched
   on class, volume, lanes and city it falls to about 1.5.
2. **A real signal remains.** On segments with no serious crash in the previous five years, PSN-flagged
   ones go on to have about 50% more serious crashes (CI 1.15-1.92). It holds for injury crashes (1.58,
   with 12 times as many events) and for arterials only.
3. **It is not a large effect, and it is partly the vulnerable-user inputs.** Controlling for school and transit
   proximity, density and equity cuts it to 1.17 (not significant). That fits the PSN's design (schools,
   transit and affordable housing are inputs), but it means the PSN is not adding much beyond those.

## What it does not show
- **No evidence on the quietest streets.** With no injury crash of any kind in 2018-22, the ratio is about 1
  (0.88 and 0.99), though with only 22 serious events on flagged segments the interval (0.49-1.58) cannot
  rule out the primary effect either. Result: inconclusive there, not negative.
- **Not causal, and not a prediction model.** Unmeasured factors (true speeds, pedestrian counts, parking,
  land use) could differ between flagged and unflagged streets.
- **Three years of outcomes** (2025 provisional); many segments, few events. Selecting on zero prior
  crashes keeps some high-risk streets that were lucky, which if anything works against finding a gap.
- Primary analysis was fixed in advance; the rest are sensitivity checks and were not adjusted for
  multiple comparisons.
