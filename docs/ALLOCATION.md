# Budget allocation: a demonstration, not a finding

Reproduce: `python -m analysis.allocate` (about 10 minutes). Table: `analysis/results/allocation_results.csv`.
The 5M-dollar project list is local only (`data/processed/analysis/allocation_5M_train_only.csv`).

## What it does
Chooses at most one treatment per quarter-mile segment to maximise expected killed-or-seriously-injured (KSI) crashes avoided
per year under a budget ($1M, $5M, $15M, $50M), an exact multiple-choice knapsack (HiGHS). Treatments and crash-reduction
factors come from Caltrans LRSM v1.8: road diet (restripe) 35%, RRFB crossing 35%, raised crossing 35%. Choices use data through
2022 only; each strategy is then scored on what actually happened in 2023-25 (CRF x observed crashes at the chosen segments).

## The costs are assumptions, so the dollar results are not findings
No Alameda source for treatment costs was found (Caltrans docs and Alameda CTC bikeway files have none). Planning figures from
other agencies are used: $40k per mile restripe, $50k per RRFB site, $10k per raised crossing, with x0.5 and x2 as sensitivity.
These leave out design, signal and drainage work, outreach and staff time. Consequently:
- Benefit-cost ratios in the hundreds and costs of $6k to $12k per KSI avoided are artifacts of the cheap restripe and should not
  be quoted. Doubling costs cuts crashes avoided at $5M from 20.7 to 14.5 a year; halving raises it to 29.2.
- Cheap road-diet restriping dominates every solution (424 of 525 segments at $5M).
- Benefits assume the CRFs apply in full at every location and ignore corridor continuity and any crash migration.

## What is usable: strategy comparison at equal spending (base costs, realised KSI avoided per year, 2023-25)
| Strategy | $1M | $5M | $15M | $50M |
|---|---|---|---|---|
| Optimised, model (EB) estimates | 7.8 | 20.7 | 34.5 | 50.2 |
| Optimised, raw 2016-22 crash counts | 6.4 | 19.7 | 27.4 | 38.0 |
| Worst-first by past KSI | 4.6 | 16.9 | 26.4 | 38.3 |
| Optimised, only streets on the HIN | 7.6 | 20.3 | 30.0 | 32.9 |
| Optimised, only streets on the PSN | 6.5 | 17.2 | 25.0 | 26.7 |
| Random eligible segment | 0.3 | 1.4 | 4.0 | 13.3 |

- Using the model's estimates instead of raw counts is worth about 5% to 32% more crashes avoided depending on budget (no
  intervals yet; one train/test split).
- Restricting to the HIN costs little at small budgets (20.3 vs 20.7 at $5M) because it contains plenty of cost-effective
  sites, and costs a third at $50M (32.9 vs 50.2) as the network runs out. The PSN loses more (17.2 at $5M).
- An earlier HIN-first and PSN-first comparison picked options at random within the network and so mostly measured cost-picking;
  it is kept in the table output only as "random within", and should not be compared with the optimised rows.
- Requiring half the money to go to equity-priority areas costs about 2% at $5M (20.2 vs 20.7).

## Limits
One split (train 2016-22, test 2023-25); the realised numbers have Poisson noise from few KSI per segment. Eligibility rules
(lanes, AADT, marked crossings) rest on OSM and HPMS tags. Bike lanes are not a treatment option because no sourced cost was
found. Restricted HIN and PSN lines are never written out, only these summaries.
