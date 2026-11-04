# Is child pedestrian and bicyclist injury near schools tied to the school day?

Reproduce: `python -m analysis.school_test`. Tables: `analysis/results/school_test_*.csv`.

## Question and data
Near schools, are children on foot or bike hurt more often at school travel times on school days than in summer,
and than at times of day when school should not matter? Outcome: crashes in which a **child aged 5-17 on foot or
bike was injured** (CCRS injured-person ages linked to TIMS crashes), surface streets. 1,354 such crashes in
2016-2025, 749 within 400 m of a school (public CDE 2024-25 and private NCES 2023-24 locations, 492 schools).

## Calendar assumption (read this first)
Only one district calendar was available (**Fremont Unified 2024-25**: school about Aug 14 - May 30; no school Nov 27-29,
Dec 23 - Jan 3, Apr 21-25). Calendars for other districts and years are **not** used. Instead the test compares only
core windows that sit inside every Alameda district's school year or summer, whatever the exact calendar:
- **In session:** weekdays Sep 16 - Nov 15 and Jan 20 - Mar 10, minus federal holidays (653 weekdays across the included years).
- **Summer:** weekdays Jun 20 - Aug 5, minus July 4 (262 weekdays).
- Dropped: first and last weeks of school, all breaks, and 2020-21 (remote learning); 2019-20 counts for Jan-Mar 2020 only.
Tightening each window by a week gives the same answer (below). Replacing these windows with real district calendars
would remove the remaining uncertainty.

## Result: near-school crashes (within 400 m) per 100 weekdays
| Time of day | In session | Summer | Ratio |
|---|---|---|---|
| **Commute (7-9 am, 2-5 pm)** | **26.5** (173 crashes) | 4.6 (12) | **5.8x** |
| Midday (10 am - 2 pm) | 3.1 (20) | 2.7 (7) | 1.15x |
| Evening (5-8 pm) | 5.2 (34) | 4.6 (12) | 1.13x |
| Weekends (per 100 weekend days) | 10.2 (27) | 7.5 (8) | 1.36x |

Commute hours rise **4.8 times more** than the placebo hours (95% interval **2.9 to 8.0**), and the commute-hour ratio
does not show up where school should not matter. About **79% (137 of 173)** of the in-session near-school commute-hour
crashes are tied to the school day, after allowing for the seasonal change seen in the placebo hours (1.2x).

**It holds in every check** (commute vs placebo ratio, interval always above 1): windows tightened a week 3.7 (2.0-6.8);
within 300 m 3.9 (2.0-7.6); within 600 m 4.6 (3.0-7.1); ages 5-11 6.7 (2.2-21); ages 12-17 4.2 (2.1-8.3); pedestrians
3.8 (1.7-8.5); bicyclists 7.5 (3.6-15.7); without 2022 5.6 (3.3-9.6); without 2025 4.8 (2.8-8.2); 2016-2020 only
5.3 (3.2-8.8); 2022-2025 only 3.9 (1.4-10.8); using only midday, only evening or only weekends as the comparison
5.1, 5.1 and 4.4.

**It fades with distance:** the commute-hour in-session/summer ratio is 4.9 within 200 m, 6.7 at 200-400 m, 5.2 at
400-800 m and 1.9 at 800-1,600 m (14 vs 3 crashes), with almost nothing beyond that.

## What it shows and does not show
- **Shows:** child pedestrian and bicycle injuries near schools are strongly concentrated in school travel times on school
  days. Protection (crossing guards, signal timing, speed enforcement or traffic calming) timed to those hours targets most
  of the burden.
- **Does not show that roads near schools are more dangerous per child.** More children are walking and biking at those
  times; there are no counts of children travelling, so this is burden, not risk per trip. Reading it as risk would
  need exposure data.
- Summer baseline is small (12 commute-hour crashes), so the ratio rests on it; the intervals reflect that.
- Child age is missing for about 11% of injured pedestrians and bicyclists and 4% of crashes do not link to the age
  file; this undercounts, and matters only if the gaps differ by season.
- School locations are 2024-25 for all years; police-reported crashes only; 2025 is provisional.
- The 2022-25 estimate is the least certain (3.9, 1.4-10.8; 68 vs 4 commute crashes).

## An earlier version that did not work
The first design compared near-school crashes with an 800-1,600 m "far" ring. That ring is mostly industrial, hilly or
low-density places (almost everywhere in the county is within 800 m of some school), so it held only 14 commute-hour
crashes in session, and children also walk to school from beyond 800 m. The intervals were too wide to say anything
(commute x session 3.1, 0.8-11.6). Using time of day as the control instead of distance fixed it.
