"""One module per source. Each exposes NAME, HELP, run(args) and optionally
add_arguments(parser) and OPTIONAL = True (skipped by `download.py all`
unless --include-optional)."""
from __future__ import annotations

import importlib

# Order = order `download.py all` runs them (cheap/fast first).
MODULE_NAMES = [
    "census",        # TIGERweb boundaries, ACS, LODES
    "county_gis",    # Alameda County street centerlines, city boundaries
    "osm",           # OpenStreetMap roads + traffic-control features + POIs
    "schools",       # CDE school sites per year, NCES private, CDE directory (manual)
    "health",        # HCAI licensed facilities (hospitals, SNFs, trauma flags)
    "oakland",       # bikeway projects/network, signals, slow streets, counts, HIN
    "berkeley",      # traffic signal inventory
    "equity",        # MTC Equity Priority Communities, CalEnviroScreen 5.0
    "caltrans",      # AADT (state highways), active-transportation counts
    "hpms",          # HPMS road sections w/ AADT, lanes, speed limit
    "countermeasures",  # CMF Clearinghouse, Caltrans LRSM, HSIP analyzer manual
    "fars",          # NHTSA fatal crashes
    "transit",       # GTFS (BART; AC Transit / 511 need tokens)
    "alamedactc",    # HIN 2019/2024, PSN 2024 (restricted)
    "mapillary",     # traffic-sign detections (token)
    "tims",          # SafeTREC TIMS (manual download -> ingest)
    "ccrs",          # CHP crash data (largest; ~5 GB streamed)
]


def load(name: str):
    return importlib.import_module(f"{__name__}.{name}")
