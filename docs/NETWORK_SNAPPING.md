# Road network and crash snapping

Reproduce: `python -m analysis.crashes` then `python -m analysis.network` (about 4 minutes,
the OSM graph load is cached after the first run). Outputs are in `data/processed/analysis/`.

## What was built
- **Network:** 108,353 drivable OSM blocks (an "edge" is the street between two intersections),
  4,943 miles; 33,242 intersections (3+ drivable streets). Built from the tiled Overpass pull.
- **Controls:** OSM signals, stop signs and crossings attached to the nearest intersection within 25 m.
  Stop-sign counts are not usable countywide (OSM coverage is very uneven by city; see `DATA_SOURCES.md`).
- **Snapping:** each of the 43,365 surface injury crashes is attached to its nearest block and nearest
  intersection.

## Results
| Check | Result |
|---|---|
| Surface crashes with a coordinate | 99.2% |
| Snapped to a block (within 100 m) | 99.1%; 99.0% within 30 m |
| Median snap distance | 1.1 m (SafeTREC points), 1.3 m (our geocode), 4.2 m (officer coordinates) |
| Within 30 m of an intersection | 79%, but TIMS flags only 51.7% as intersection crashes |
| OSM lane count / speed limit present | 38% / 30% of blocks |

## What this means for the analysis
- **Coordinates are good enough for block-level assignment.** The three sources agree well, and the
  officer points sit slightly farther from the road than the geocoded ones.
- **"Near an intersection" is not "at an intersection."** City blocks are short, so a 30 m radius
  catches many mid-block crashes. Use TIMS's `INTERSECTION` flag to classify, not distance alone.
- **Killed-or-seriously-injured (KSI) crashes are too sparse for single blocks.** 3,371 surface KSI
  crashes sit on 2,842 different blocks, mostly one each (Oakland 2017-2021: 543 KSI on 488 blocks).
  Per-block counts can't be modeled directly; the analysis needs corridors or fixed-length segments
  (the HIN uses quarter-mile segments), or all-injury crashes with KSI as a severity outcome.
- **A block-level "x% of length carries y% of KSI" figure is not comparable** to Oakland's published
  "8% of streets carry 60%". It reflects the unit of measurement, not a finding, so it is printed
  for transparency only and should not be quoted.
- **OSM lane and speed attributes are too incomplete** to use alone. HPMS (arterials), the county
  centerlines and posted-speed records have to fill them in.

## Not done yet
- Comparing the crash data with Oakland's published HIN (45 corridor segments and 20 intersections,
  listed by street name and cross streets) requires geocoding each segment's endpoints.
- Joining HPMS traffic volumes, schools and hospitals, equity layers and bike facilities to blocks.
