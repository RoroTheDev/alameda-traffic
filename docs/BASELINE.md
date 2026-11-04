# Baseline analysis (Part 1): what happened, who, when, why, where, and who bears it

Reproduce: `python -m analysis.baseline`. Tables: `analysis/results/baseline_*.csv`.
Data: 73,565 injury and fatal crashes in Alameda County, 2016-2025 (TIMS base, `analysis/crashes.py`);
43,365 on surface streets. **KSI** = killed or seriously injured (TIMS severity 1-2). Descriptive only: no
models, no traffic or walking exposure. 2025 is provisional.

## 1. Trends
- **2020 fell and the recovery was partial:** surface-street KSI dropped 21% in 2020 versus 2019, then climbed back
  to 96-103% of 2019 in 2022-24 (2025: 86%, provisional). Average per year 2016-19 -> 2022-25: **334 -> 362 (+8%)**.
- **Pedestrians:** flat (101 -> 95 KSI a year). **Motorcyclists:** flat (63 -> 64).
- **Bicyclists are the one clear increase:** KSI 48 -> 62 a year (+29%) and **deaths 3.2 -> 6.2 a year**
  (2024 alone: 8 killed; 2025: 6).
- Freeway KSI rose over the period (162 in 2016, 202-269 since).

## 2. Deaths cross-check against the federal count (FARS)
TIMS deaths match FARS within 1-4 a year for 2016-2022. In **2023 and 2024 TIMS counts 9 and 11 more** (108 vs 99,
111 vs 100). FARS 2024 is not final and TIMS is provisional, so this is unresolved, not an error to fix yet.

## 3. When (surface streets)
| | Share of injury crashes that are KSI |
|---|---|
| Night (0-5 am) | **13.2%** (12.1-14.4) |
| Late evening (8-11 pm) | **12.0%** (11.2-12.8) |
| Morning, midday | 5.8-5.9% |
| Evening (4-7 pm) | 7.9% |
| Dark | **11.6%** vs daylight **6.2%** |
| Weekend | 9.0% vs weekday 7.5% |

Night and late evening are 22% of injury crashes but **35% of KSI**. Dark conditions: 28% of injury crashes, 41% of KSI.

## 4. Why (officer-recorded main cause of 3,406 surface KSI crashes)
Unsafe speed 16.5%, unsafe turn or lane change 13.6%, driver fails to yield to a pedestrian 11.1%, drunk or drugged
driving 9.7% (11.8% with the injury-causing code), red signal 8.4%, left turn failing to yield 5.7%.
These are the reporting officer's judgement of the primary factor, not a finding of cause, and speed is probably
under-recorded.

## 5. Who
| Road user | Share of injury crashes | Share of KSI | KSI per 100 injury crashes |
|---|---|---|---|
| Pedestrian | 13.7% | **27.6%** | 15.8 (14.9-16.8) |
| Bicyclist | 11.2% | 15.5% | 10.9 (10.0-11.8) |
| Motorcyclist | 6.4% | **18.1%** | **22.2** (20.7-23.8) |
| None of these | 69.0% | 39.3% | 4.5 (4.2-4.7) |
| Alcohol involved | 8.8% | 18.0% | 16.1 (15.0-17.3) |

People on foot, bike or motorcycle are 31% of injury crashes and **61% of KSI**.

## 6. Who bears the burden (surface-street crashes per 100,000 residents per year, by where the crash happened)
| Tracts | KSI | Pedestrian + bicycle KSI |
|---|---|---|
| Equity priority communities (101 tracts, 422k residents) | **28.0** | **12.3** |
| Other tracts (276 tracts, 1.23M residents) | 17.8 | 7.6 |
| Lowest-income fifth of tracts | **30.5** | 14.2 |
| Highest-income fifth of tracts | 15.6 | 5.4 |

KSI rate ratio, equity priority vs other: **1.57 (1.46-1.69)**; pedestrian + bicycle 1.63. The interval ignores
spatial clustering and is too narrow. These are per resident, with no traffic or walking exposure, and they count
crashes by where they happened (not who was hurt), so through traffic in busy commercial tracts inflates them.

## 7. Hot spots (Getis-Ord Gi*, 400 m cells, 1 km neighbourhood, Benjamini-Hochberg at 5%)
- **All-mode KSI:** 391 of 3,612 cells (10.8%) hold **37.6%** of KSI; 63% of them are in Oakland, 29% in Berkeley.
- **Pedestrian + bicycle KSI:** 364 cells (10.1%) hold **44.7%**.
- **They persist:** cells that were hot in 2016-19 hold 35% of 2020-25 KSI, and **80% are still hot** in 2020-25
  (79% for pedestrian + bicycle). History is a stable guide to where serious crashes concentrate.
- Cells are those with at least one injury crash, and the significance test is the normal approximation, which is
  rough for counts this sparse.

## Limits
- Police-reported crashes only; under-reporting is worse for pedestrian, bicycle and minor crashes.
- No exposure data, so a higher count is not necessarily higher risk per person or per trip.
- 2025 is provisional; TIMS counts refresh quarterly.
- All of this is association and description.
