# Crash coordinate audit (CCRS, Alameda County, 2016–2025)

Reproduce: `python download.py ccrs` → `python -m audit.coordinates` → (after the TIMS
CSVs are in) `python -m audit.compare_tims`. Result tables: [`audit/results/`](../audit/results/).
Scope: **injury and fatal crashes** (73,927), because that is what the study analyses.
Reporting agency comes from the CCRS `NCIC Code` (93xx = CHP office, 01xx = city/campus police).

## 1. Findings

**The gap is an agency gap, not a city gap.** City/campus police departments record usable
coordinates on 27% of injury crashes; CHP on 93%.

| Reporting agency (NCIC) | Injury crashes | Valid coordinate | Missing | Present but outside county |
|---|---|---|---|---|
| Oakland PD (0109) | 16,645 | **0.02%** | 99.97% | 0.01% |
| Fremont PD (0105) | 4,600 | 0.9% | 68% | **31%** |
| Union City PD (0113) | 1,168 | 0.09% | 99.9% | 0 |
| Pleasanton PD (0111) | 1,818 | 2% | 98% | 0 |
| San Leandro PD (0112) | 2,063 | 23% | 76% | 1% |
| Alameda PD (0101) | 1,732 | 47% | 52% | 0.4% |
| Berkeley PD (0103) | 4,908 | 78% | 21% | 0.7% |
| Hayward PD (0106) | 2,870 | 80% | 20% | 0.4% |
| Livermore PD (0107) | 2,115 | 82% | 18% | 0.5% |
| Newark PD (0108) | 1,051 | 96% | 3% | 1% |
| CHP Dublin/Fremont area (9345) | 10,970 | 99% | 0.05% | 1% |
| CHP Oakland area (9370) | 7,769 | 85% | 0.05% | **15%** |

Oakland PD's rate is ~0% in every year 2016–2025, so Oakland's surface-street crashes have
**no** officer coordinates at all, not a partial gap. Earlier I quoted "31% of Oakland
crashes have coordinates" — that number was the share handled by CHP (freeways), not a
property of Oakland's city streets.

Consequence: dropping crashes with missing coordinates removes Oakland, Union City and
Pleasanton surface streets almost entirely and leaves a freeway- and CHP-heavy sample.

**Two kinds of bad coordinates** (present, so a null check does not catch them):
- **Fremont PD 2016–2018:** 80–87% of records have coordinates, but they land in San
  Diego County (lat ≈ 33.2, lon ≈ −117.7) while the street names are Fremont's (Auto Mall
  Pkwy, Niles Blvd). Systematic, not random. From 2019 Fremont PD mostly stops recording
  them (~1–8% present).
- **CHP Oakland area, 15% outside the county:** on I-80, I-580, I-880 and SR-24, with a
  median position on the Peninsula (lat 37.49, lon −122.17). Not the Bay Bridge. Cause unknown.

## 2. Recovery by street-name geocoding

Method (`alameda_traffic/geocode.py`): parse `PrimaryRoad` and `SecondaryRoad`, find both
streets in the county centerlines (same city), take the point where they meet. Each result
carries a status; ambiguous or unmatched crashes are left empty, not guessed.

Accuracy, measured on **19,833 crashes from city PDs that do have valid officer
coordinates** (surface streets only):

| Error vs officer coordinate | Share |
|---|---|
| within 50 m | 69% |
| within 100 m | 83% |
| within 250 m | 93% |
| median | 17 m |

Result for the 73,927 injury crashes: **56.4% officer coordinate, 33.6% street-name
geocode, 10.0% still none.** Of Oakland PD's 16,641 un-located surface crashes, 89% geocode
to a single place. The 7,419 left include 1,805 Oakland PD crashes (about 1,170 with a street name not found in
the centerlines, the rest ambiguous, unconnected or route names), 593 Pleasanton PD, 1,058
Fremont PD, and ~2,100 CHP crashes (freeway crashes that were never attempted, plus route names).

## 3. Caveats

- **Validation is on other cities.** Oakland PD has only 12 crashes with officer
  coordinates, so its geocoding accuracy is *extrapolated* from Berkeley, Hayward,
  Livermore, Alameda and others. Oakland's grid (numbered avenues vs streets sharing a
  number) may differ. Treat Oakland accuracy as unverified.
- **Officer coordinates are a proxy, not ground truth.** They come from the same reporting
  chain being audited; some departments may geocode to the intersection themselves.
- **"ok" means unique, not correct.** A confidently wrong street match counts as ok. The
  7% of validation crashes beyond 250 m includes those.
- **Offsets not applied.** Moving the point by the reported `SecondaryDistance`/direction
  made agreement *worse* (within 50 m: 55% vs 61% for the bare intersection, same crashes;
  `python -m audit.checks`). If officers already place points at the intersection this would
  flatter the no-offset version, so this is unresolved; TIMS `POINT_X/POINT_Y` can arbitrate.
- **Resolution.** Good for segment-level work (quarter-mile HIN segments). Not for
  assigning a crash to a specific signal or stop sign.
- **Freeways** (`IsFreeway = True`) and route names are not geocoded.
- Year range excludes partial 2026. 2025 is provisional.

## 4. Still to do (needs the TIMS files)

`audit/compare_tims.py` is written but **has never been run**; its join key (CCRS `Report
Number` ↔ TIMS `CASE_ID`) is an assumption. It will report: (A) how many CCRS crashes
are found in TIMS, (B) whether CCRS and TIMS officer coordinates agree, (C) TIMS
`POINT_X/POINT_Y` vs officer coordinates and vs our geocode. TIMS comes from the same CHP
data, so it checks conversion fidelity and SafeTREC's geocoder, not absolute truth.
