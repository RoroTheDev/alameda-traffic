# Data sources — findings that shape the study

Per-source facts (access, license, what each has and lacks) live in
[`catalog/sources.yaml`](../catalog/sources.yaml). This page records the
findings from the data audit (2026-09-27) that change how the study is done.

## 1. Alameda CTC already built a countywide HIN and a risk network

The **High-Injury Network and Proactive Safety Network Report** (Alameda CTC /
Fehr & Peers, Sept 2024; adopted Oct 2024):

- **HIN 2024** — TIMS 2018–2022, freeways excluded; fatal/serious crashes
  weighted 10, other injury 5; quarter-mile segments; top 20% within
  walking/biking exposure tiers (ACS commute share); smoothed into corridors.
- **Concept PSN 2024** — a points system (not a model). Roadway (8 pts):
  modeled ADT (AlaCC), INRIX speed (May 2024), ≥4 lanes, intersection
  spacing ≤500 ft, ramp terminals. Vulnerable users (4 pts): 10-minute walk
  shed to schools (CDE 2024), frequent transit (GTFS May 2024), affordable
  housing; major bike corridors. Kept segments in the top 10% roadway score
  AND top 50% vulnerable-user score → 261 mi (~6% of streets); 65% overlaps
  the HIN.
- The report says the PSN **"is not a predictive tool"**. It was not
  validated against later crashes, does not use hospitals or senior
  facilities, and does not evaluate countermeasures or budgets.

Implication: frame the paper against it — e.g. test HIN/PSN membership against
2023–2025 crashes, estimate risk weights from data instead of assigning
points, add the school-calendar comparison, hospitals/SNFs, countermeasure
before/after, and budget-constrained allocation.

## 2. Crash coordinates are missing non-randomly

CCRS has `Latitude`/`Longitude`, but in 2024 only 65% of Alameda injury
crashes have them — **Oakland 31% (661 of 2,106)**, unincorporated 100% (CHP
records GPS). Dropping blanks would erase Oakland's hot spots. Fix with TIMS
geocodes (manual download) and/or geocoding `PrimaryRoad` × `SecondaryRoad`
against the county street centerlines.

| Year | Alameda crashes (all, incl. PDO) | with coordinates | on freeways | fatal crashes |
|---|---|---|---|---|
| 2020 | 16,933 | 62% | 41% | 99 |
| 2021 | 19,138 | 68% | 45% | 99 |
| 2022 | 19,542 | 69% | 45% | 106 |
| 2023 | 20,136 | 70% | 46% | 103 |
| 2024 | 20,119 | 71% | 45% | 99 |
| 2025 (provisional) | 18,131 | 73% | 47% | 87 |

## 3. Oakland publishes bikeway install dates

Oakland Bikeway Projects has `YearDone`/`MonthDone` — 245 projects completed
2016–2025 (lanes, buffered, separated, boulevards, paths, sharrows). With CCRS
2016+ this supports a real before/after (comparison-group / Empirical Bayes)
study for bike facilities in Oakland.

## 4. OSM traffic-control coverage is uneven by city

Counts from Overpass, 2026-09-27 (road segments = primary/secondary/tertiary/
residential/unclassified ways):

| City | Stop signs | Signals | Calming | Road segments | % with maxspeed | Stops / 100 segments |
|---|---|---|---|---|---|---|
| Oakland | 4,106 | 1,167 | 2,273 | 10,006 | 20% | 41 |
| Fremont | 527 | 456 | 379 | 7,678 | 44% | 6.9 |
| Hayward | 1,798 | 400 | 1,381 | 4,234 | 22% | 42 |
| Livermore | 719 | 301 | 62 | 3,633 | 13% | 20 |
| Pleasanton | 55 | 398 | 47 | 3,149 | 49% | 1.7 |
| Berkeley | 1,613 | 242 | 364 | 2,938 | 96% | 55 |
| San Leandro | 1,494 | 238 | 622 | 2,523 | 9% | 59 |
| Dublin | 162 | 355 | 16 | 2,379 | 32% | 6.8 |
| Alameda | 544 | 125 | 194 | 1,964 | 16% | 28 |
| Union City | 735 | 184 | 272 | 1,794 | 36% | 41 |
| Newark | 186 | 59 | 130 | 1,520 | 17% | 12 |
| Emeryville | 132 | 69 | 46 | 488 | 41% | 27 |
| Albany | 258 | 27 | 61 | 410 | 56% | 63 |
| Piedmont | 102 | 5 | 42 | 376 | 13% | 27 |

Stop-sign analyses are only defensible in well-mapped cities. Node counts are
not intersection counts (one stop node per approach; several signal nodes per
intersection) — cluster first. Mapillary detections can audit coverage.

## 5. Exposure data is thin

- No public volumes for local streets.
- HPMS (2020, 2022–2024) gives AADT for every freeway-to-major-collector
  section (f_system 1–5) in Alameda. Local-street "AADT" in 2022/2023 is a
  placeholder (405 / 397 on >90% of sections); 2020 has 38k duplicate
  geometries. Treat years separately.
- Caltrans AADT covers state highways only.
- Ped/bike counts: Oakland 2011–2021 (Excel sheets), Caltrans hourly counts at
  ~a dozen state-highway sites 2023–2025, Alameda CTC's ~150-site program
  (request only).
- Alameda CTC used AlaCC model volumes + INRIX speeds (request only).

## 6. Time-varying conditions

- Oakland lowered speed limits in business districts (AB 43) during 2023–2025
  and cut Broadway / International Blvd to 20 mph in late 2025 — a current
  speed-limit snapshot misstates earlier years.
- Oakland Slow Streets (2020) and COVID travel changes make 2020 abnormal.
- School sets change: use the CDE school-site layer for each school year.

## 7. Source quirks handled by the scripts

- CCRS SQL-API copy of 2019 is truncated → scripts stream the CSVs.
- CCRS CSV headers carry stray tabs → column names stripped.
- Oakland bikeway GeoJSON is EPSG:2227 → reprojected to WGS84.
- The Census API requires a key → keyless fallback to table-based summary files.
- CMF Clearinghouse TLS chain is incomplete → verified via the OS trust store.
- cde.ca.gov directory is CAPTCHA-protected → manual step.
- TIGERweb places are fetched by bounding box, so neighbouring-county places
  are included — clip to the county polygon in analysis.
- HPMS county codes are unreliable → spatial filter + clip to the county polygon.
- FARS 2021+ CSVs start with a UTF-8 byte-order mark → stripped.
- One county-wide Overpass query for all roads times out (HTTP 504) → 18 tiles, merged.

## 8. Cross-check: deaths

Fatal crashes in Alameda — FARS crash records vs CCRS crashes with
`NumberKilled` > 0. Small gaps are expected (reporting/coding differences,
late updates); reconcile case-by-case before reporting death counts.

| Year | FARS | CCRS |
|---|---|---|
| 2020 | 101 | 99 |
| 2021 | 96 | 99 |
| 2022 | 106 | 106 |
| 2023 | 92 | 103 |
| 2024 | 93 | 99 |
