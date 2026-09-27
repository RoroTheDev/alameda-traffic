"""HPMS — FHWA Highway Performance Monitoring System, California, by year.

Access: API (geo.dot.gov ArcGIS REST, HPMS_FULL_CA_<year>). Avoids the
2.6 GB national file geodatabase.

Filtering is SPATIAL (county envelope, then clipped to the Alameda polygon
from TIGERweb): the county attribute can't be trusted — it is `county_code`
in 2020 and `county_id` later, and in 2023 `county_id=1` returns ~265k
sections statewide (e.g. SR 395 in the Eastern Sierra). The log records the
county codes seen after clipping. Sections crossing the county line are kept.

What it gives you: road sections with AADT, through lanes, speed limit,
functional class (f_system), signal/stop-sign counts, pavement etc. AADT is
complete for f_system 1–5 (freeways through major collectors) in every year.
This is the only public source of arterial traffic volumes we found.

Years are NOT interchangeable (checked 2026-09-27):
- 2020: 38,258 of 64,375 sections are exact duplicate geometries — dedupe.
- 2022/2023: local streets (f_system 7) carry a placeholder AADT (405 / 397
  on >90% of sections) — imputed, not counted; don't use as exposure.
- 2024: local streets have no AADT; speed_limit is sparse.
- Field names differ by year (begin_point vs beginpoint, county_code vs county_id).
"""
from __future__ import annotations

import logging
from collections import Counter

import geopandas as gpd
from shapely.geometry import shape

from .. import arcgis
from ..config import BBOX, COUNTY_FIPS, PROCESSED, STATE_FIPS, out_dir
from ..provenance import log_pull

NAME = "hpms"
HELP = "HPMS road sections (AADT, lanes, speed limit) for Alameda, 2020/2022/2023/2024"
log = logging.getLogger(__name__)

SERVICE = "https://geo.dot.gov/server/rest/services/Hosted/{name}/FeatureServer/0"
NAMES = {2020: "HPMS_FULL_CA_2020", 2022: "HPMS_FULL_CA_2022", 2023: "HPMS_FULL_CA_2023",
         2024: "HPMS_FULL_CA_2024"}  # no 2021 service is published
COUNTY_LAYER = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_ACS2024/MapServer/82"


def add_arguments(p):
    p.add_argument("--years", default="2020,2022,2023,2024")


def _county_polygon():
    fc = arcgis.query_all(COUNTY_LAYER, f"STATE='{STATE_FIPS}' AND COUNTY='{COUNTY_FIPS}'")
    return shape(fc["features"][0]["geometry"])


def run(args):
    county = _county_polygon()
    for year in (int(y) for y in args.years.split(",")):
        url = SERVICE.format(name=NAMES[year])
        fc = arcgis.query_all(url, "1=1", bbox=BBOX)
        feats = [f for f in fc["features"] if f.get("geometry")]
        gdf = gpd.GeoDataFrame.from_features(feats, crs=4326)
        gdf = gdf[gdf.intersects(county)]
        dest = out_dir(PROCESSED, NAME) / f"hpms_{year}_alameda.geojson"
        gdf.to_file(dest, driver="GeoJSON")
        county_col = next((c for c in ("county_id", "county_code") if c in gdf.columns), None)
        codes = dict(Counter(gdf[county_col].astype(str)).most_common(5)) if county_col else None
        with_aadt = int((gdf["aadt"].fillna(0) > 0).sum()) if "aadt" in gdf.columns else None
        log.info("HPMS %d: %d sections in Alameda (%s with AADT)", year, len(gdf), with_aadt)
        log_pull(NAME, f"HPMS {year} California (clipped to Alameda)", url=url, out_path=dest,
                 rows_in=len(feats), rows_out=len(gdf), sections_with_aadt=with_aadt,
                 county_codes_seen=codes, dropped_null_geometry=len(fc["features"]) - len(feats))
