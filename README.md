# alameda-traffic

Traffic crashes, deaths and injuries in Alameda County, CA — where they
concentrate, how risk changes near schools, hospitals and other vulnerable
destinations, what countermeasures (bike lanes, signals, stop signs, speed
limits) are associated with, and how to allocate a safety budget efficiently.

This repository currently holds the **data acquisition layer**: one script per
source, a catalog of every source (including the ones that can't be
scripted), and a provenance log of every pull.

- [`catalog/sources.yaml`](catalog/sources.yaml) — every source: access method, license, what it has/lacks, gotchas
- [`docs/DATA_SOURCES.md`](docs/DATA_SOURCES.md) — audit findings that shape the study
- [`catalog/pull_log.jsonl`](catalog/pull_log.jsonl) — when each file was pulled, from where, with SHA-256

## Setup

```bash
python -m venv .venv            # or a venv outside OneDrive/Dropbox
.venv/Scripts/activate          # Windows;  source .venv/bin/activate on macOS/Linux
pip install -r requirements.txt
cp .env.example .env            # optional: API keys, ALAMEDA_DATA_DIR
```

Python 3.12 recommended (geopandas/osmnx wheels).

## Downloading

```bash
python download.py list                  # all 42 catalogued sources
python download.py manual                # steps only a human can do (keys, CAPTCHA, requests)
python download.py all                   # every scriptable source (~6 GB streamed, ~0.6 GB kept; ~1 h)
python download.py ccrs --years 2020-2025
python download.py <source> --help       # details for one source
```

Scripted sources: `census`, `county_gis`, `osm`, `schools`, `health`, `oakland`,
`berkeley`, `equity`, `caltrans`, `hpms`, `countermeasures`, `fars`, `transit`,
`alamedactc`, `ccrs`, plus `mapillary` (token, optional) and `tims` (ingests a
manual download — publishing permitted with citation, see Attribution below).

**APIs vs bulk files.** Where a server can filter to Alameda for us
(ArcGIS REST, Socrata, CKAN, Overpass, Census API) the scripts query it. Where
the full file is the only complete copy (CCRS, FARS, LODES, ACS without a key,
Caltrans counts) the scripts *stream* the statewide/national file and keep only
Alameda rows, so multi-GB files never sit on disk unless you pass `--keep-raw`.

## Coordinate audit

About a third of Alameda's injury crashes have no usable location in CCRS, almost all from a few
city police departments (Oakland PD records none). `python -m audit.coordinates` measures this
and recovers locations by geocoding street names; results and caveats in
[`docs/COORDINATE_AUDIT.md`](docs/COORDINATE_AUDIT.md). `audit/compare_tims.py` (written, not yet
run) compares against TIMS once its CSVs are in `data/manual/tims/`.

## Analysis table

`python -m analysis.crashes` builds `data/processed/analysis/crashes.parquet`: 73,565 injury and fatal
crashes (2016-2025) on a TIMS base, with CCRS fields linked in, three coordinate sources side by
side (SafeTREC, our geocode, officer), and a freeway/surface flag. Surface streets: 43,365 crashes,
3,406 killed-or-seriously-injured.

## Storage policy

| What | Where |
|---|---|
| Code, catalog, pull log, docs | git |
| Downloaded data (`data/raw`, `data/processed`) | git-ignored; `data/processed` is published as **GitHub Release** assets via `python publish_release.py` |
| License-restricted data (`data/restricted`: Alameda CTC HIN/PSN layers, GTFS) | local only — never committed or published |
| Manual drops (`data/manual`) | git-ignored except templates |

GitHub blocks files >100 MB in git; release assets can be up to 2 GiB each.
Because sources change (CCRS is regenerated daily; OSM constantly), cite the
release tag + `pull_log.jsonl` for any result.

## Attribution

- Map data © OpenStreetMap contributors, ODbL 1.0 (derived OSM data is published under ODbL).
- Mapillary detections: CC BY-SA 4.0.
- TIMS/SWITRS: "California Highway Patrol, Statewide Integrated Traffic Records System (SWITRS), accessed via the Transportation Injury Mapping System (TIMS), UC Berkeley Safe Transportation Research and Education Center, 2026." Publishing permission confirmed by SafeTREC (tims_info@berkeley.edu), email 2026-09-28.
- Crash data: California Highway Patrol (CCRS); NHTSA (FARS).
- Other sources and their terms: `catalog/sources.yaml`.
