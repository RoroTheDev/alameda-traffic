# Quarter-mile segments and the segment x year panel

Reproduce: `python -m analysis.crashes` -> `python -m analysis.network` -> `python -m analysis.segments`.
Outputs in `data/processed/analysis/`: `segments.parquet`, `segment_year.parquet`, `crash_segment.parquet`.
Built only from openly licensed sources (OSM, HPMS, CDE, HCAI, Oakland, Census, TIMS with permission),
so these tables can be released. No Alameda CTC data is mixed in.

## What a segment is
Drivable OSM blocks merged by street name into continuous chains, then cut into equal pieces of at
most 1/4 mile (the HIN's unit). 32,462 segments, 4,761 miles. Surface injury crashes are assigned to the
nearest segment within 60 m (99.8% assigned, median 1.1 m): 42,939 crashes, 3,362 killed or seriously
injured (KSI), of which 929 involve a pedestrian and 524 a bicyclist.

## Sparsity at this scale
7.1% of segments have at least one KSI crash and 26.7% have at least one injury crash over ten years;
the busiest segment has 9 KSI. Far better than single blocks, but still mostly zeros, so counts need a
count model (Poisson or negative binomial) with a length or exposure offset.

## Attribute coverage (the main constraint)
| Attribute | Segments with a value | Note |
|---|---|---|
| Traffic volume (HPMS 2024 AADT) | 27% (34% of length) | arterials and collectors only, **but 78% of KSI occur there** |
| OSM lane count | 25% | |
| OSM posted speed | 21% | |
| HPMS posted speed | 4% | effectively unusable |
| Tract (equity, CalEnviroScreen, density) | 99.5% | |
| City or place | 94.7% | the rest is unincorporated land outside any named place |

**Posted speed limit is the biggest gap.** It is a core risk factor, and no public source covers it.
Options: the INRIX / AlaCC speed request to Alameda CTC, or an assumption by road class (California's
default speeds), clearly labeled as an assumption.
Local streets have no traffic volume at all, so models must either restrict to roads with HPMS
volume or use road class as the exposure proxy for the rest.

## Sanity checks passed
- Highest-KSI segments are the expected corridors: International Blvd, San Pablo Ave and Grand Ave
  (Oakland), University and Ashby Ave (Berkeley), West Tennyson Rd (Hayward).
- KSI per mile-year rises with road class (residential 0.03, tertiary 0.12, secondary 0.19, primary 0.23)
  and with traffic volume (0.11 in the lowest AADT fifth, 0.19 in the top three).
- Annual surface KSI is steady at 293-380, with no break at the 2020 or the CCRS/TIMS changes.

## Known limits
- Segment lengths vary: 19% are under 50 m (short courts, chain ends) and 29% are 300-410 m. Always
  model with a length offset.
- Distances to schools, hospitals and bus stops are straight-line, not walking routes. Schools use the
  2024-25 list for every year. Bus stops are OSM, not GTFS.
- Bike-lane data covers Oakland only (completed projects, matched when at least half of the segment is
  within 12 m of a project). Other cities have no install dates.
- Stop-sign counts are not usable countywide (OSM coverage differs by city).
- Equity and density are tract-level, so every segment in a tract shares them.
