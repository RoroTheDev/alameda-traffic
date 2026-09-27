"""City of Oakland open data (Socrata) + OakDOT High Injury Network files.

Access: API (Socrata SODA) and direct file downloads.
- Bikeway Projects (wsr6-nipq): YearDone/MonthDone for projects since 1996 —
  enables before/after analysis of bike facilities.
- Bikeway Network (6e52-b8q8): existing/proposed class, YearofCurrentClass.
- Slow Streets (vg6t-ire2): 2020 pandemic program (confounder for 2020).
- Traffic Signals (wm75-yhqe): 620 intersections by street NAME only, 2013.
- Multi-modal counts (amtg-eh64): zip of ~387 Excel count sheets, 2011–2021.
- 2024 HIN segment/intersection tables (xlsx).

Gotcha: Socrata serves the two bikeway layers' GeoJSON in California State
Plane zone III feet (EPSG:2227), not WGS84. They are reprojected here.
"""
from __future__ import annotations

import logging

import geopandas as gpd
import pandas as pd

from ..config import BBOX, PROCESSED, out_dir
from ..http import download
from ..portals import socrata_rows, socrata_view
from ..provenance import log_pull

NAME = "oakland"
HELP = "Oakland bikeway projects (install dates), bikeways, signals, counts, 2024 HIN"
log = logging.getLogger(__name__)

DOMAIN = "data.oaklandca.gov"
LAYERS = {  # stem -> (dataset id, CRS the coordinates arrive in)
    "bikeway_projects": ("wsr6-nipq", 2227),
    "bikeway_network": ("6e52-b8q8", 2227),
    "slow_streets_2020": ("vg6t-ire2", 4326),
}
TABLES = {"traffic_signals_2013": "wm75-yhqe"}
FILES = {
    "multimodal_counts_2011_2021.zip": "https://data.oaklandca.gov/download/amtg-eh64/application%2Fzip",
    "HIN_2024_Segments.xlsx": "https://cao-94612.s3.us-west-2.amazonaws.com/documents/HIN_2024_Segments.xlsx",
    "HIN_2024_Intersections.xlsx": "https://cao-94612.s3.us-west-2.amazonaws.com/documents/HIN_2024_Intersections.xlsx",
}


def _meta(dataset_id: str) -> dict:
    v = socrata_view(DOMAIN, dataset_id)
    return {"rows_updated_at": v.get("rowsUpdatedAt"), "license": (v.get("license") or {}).get("name")}


def layers():
    for stem, (dsid, crs) in LAYERS.items():
        fc = socrata_rows(DOMAIN, dsid, fmt="geojson")
        gdf = gpd.GeoDataFrame.from_features(fc["features"], crs=crs).to_crs(4326)
        minx, miny, maxx, maxy = gdf.total_bounds
        if not (BBOX[0] - 0.1 < minx and maxx < BBOX[2] + 0.1 and BBOX[1] - 0.1 < miny and maxy < BBOX[3] + 0.1):
            raise RuntimeError(f"{stem}: reprojected bounds {gdf.total_bounds} outside Alameda — wrong CRS?")
        dest = out_dir(PROCESSED, NAME) / f"{stem}.geojson"
        gdf.to_file(dest, driver="GeoJSON")
        log_pull(NAME, stem, url=f"https://{DOMAIN}/resource/{dsid}.geojson", out_path=dest,
                 rows_out=len(gdf), source_crs=f"EPSG:{crs}", **_meta(dsid))


def tables():
    for stem, dsid in TABLES.items():
        df = pd.DataFrame(socrata_rows(DOMAIN, dsid))
        dest = out_dir(PROCESSED, NAME) / f"{stem}.parquet"
        df.to_parquet(dest, index=False)
        log_pull(NAME, stem, url=f"https://{DOMAIN}/resource/{dsid}.json", out_path=dest,
                 rows_out=len(df), **_meta(dsid))


def files():
    for fname, url in FILES.items():
        info = download(url, out_dir(PROCESSED, NAME) / fname)
        log_pull(NAME, fname, url=url, out_path=info["path"], sha256=info["sha256"], nbytes=info["bytes"])


def run(args):
    layers()
    tables()
    files()
