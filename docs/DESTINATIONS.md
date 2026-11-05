# Are serious crashes more common on streets next to hospitals and nursing homes? (Part 2)

Reproduce: `python -m analysis.destinations`. Tables: `analysis/results/destinations_results.csv`, `destinations_raw_rates.csv`.

## Design
32,462 quarter-mile surface-street segments, crashes 2016-2025. Poisson regression with a miles-times-10-years offset,
standard errors clustered by street name. Exposure: within 400 m of a general acute care hospital (406 segments) and within
400 m of a skilled nursing facility (1,426 segments), both in one model. Controls: road class, log(AADT), lanes, city,
population density, bus stops, intersections, schools within 400 m, equity-priority tract. Outcomes: injury crashes, KSI,
pedestrian + bicyclist KSI, and injury crashes with a 65+ pedestrian or bicyclist (1,203 crashes, from CCRS ages).

## Result
Raw rates look high: segments near a hospital have 2.3 injury crashes per mile per year against 0.85 elsewhere; near a nursing
home 1.7. Most of that is where these facilities sit (busy, dense, arterial streets).

| Outcome (rate ratio, 95%) | Near hospital | Near nursing home |
|---|---|---|
| Injury crashes | 0.99 (0.83-1.18) | **1.19** (1.06-1.33) |
| KSI | 0.91 (0.68-1.21) | 1.12 (0.94-1.33) |
| Pedestrian + bicyclist KSI | 0.97 (0.65-1.45) | 1.04 (0.82-1.32) |
| Older-adult (65+) ped/bike injury crashes | 0.99 (0.65-1.52) | 1.20 (0.96-1.51) |

- **Hospitals: no extra crashes** once the street's traits are accounted for. With road controls only, injury crashes are 1.23
  (1.00-1.50); adding density, transit and equity removes it. Arterials only: 0.89 (0.74-1.09).
- **Nursing homes: a modest rise for all injury crashes (about 19%), none that is clearly there for serious or older-adult
  crashes.** The distance bands do not fade: injury 1.52 within 200 m, 1.40 at 200-400 m, 1.32 at 400-800 m, 1.26 at 800-1,600 m;
  older-adult crashes 1.30, 1.62, 1.37, 1.32. A local effect would shrink with distance; this looks like "nursing homes are in
  busier parts of town" that the controls do not fully capture.

## What it means for the paper
- Do not weight hot spots up because a hospital is nearby on the strength of crash rates: nothing here shows more crashes per
  mile there. If hospitals and nursing homes get extra weight, the reason has to be the people (patients, older adults, ambulance
  access, severity if hit), not that the street is already worse.
- This tests crash frequency only. It does not test severity given a crash, ambulance delay, or risk per older pedestrian.

## Limits
- No walking or traffic counts beyond AADT where it exists (many local streets have none; missing-AADT flag used).
- Facility locations are one current list (HCAI), applied to all ten years.
- Older-adult crashes link through CCRS ages; about 4% of crashes do not link.
- The nursing-home gradient is not separated from area-level confounding.
