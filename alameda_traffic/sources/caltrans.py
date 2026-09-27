"""Caltrans: AADT on state highways and hourly active-transportation counts.

Access:
- AADT (2023 count year): API (Caltrans ArcGIS REST), CNTY='ALA'. State
  highways only (mostly freeways) — no local streets.
- Active Transportation Count Dataset (2023–2025, hourly ped + bike, state
  highways only): BULK CSVs from data.ca.gov (30–80 MB each), streamed and
  filtered to District 4 sites inside the Alameda bounding box. Some sites
  sit near the Contra Costa line; check the county in analysis.
"""
from __future__ import annotations

import logging

import pandas as pd

from .. import arcgis
from ..config import BBOX, PROCESSED, out_dir
from ..http import download, stream
from ..portals import CKAN_CA, ckan_package
from ..provenance import log_pull

NAME = "caltrans"
HELP = "Caltrans AADT (state highways) and hourly ped/bike counts"
log = logging.getLogger(__name__)

AADT_LAYER = "https://caltrans-gis.dot.ca.gov/arcgis/rest/services/CHhighway/Traffic_AADT/FeatureServer/0"
AT_PACKAGE = "at-count-dataset"


def aadt():
    fc = arcgis.query_all(AADT_LAYER, "CNTY='ALA'")
    dest = arcgis.save_geojson(fc, out_dir(PROCESSED, NAME) / "aadt_state_highways_alameda.geojson")
    log_pull(NAME, "Traffic Volumes AADT (state highways)", url=AADT_LAYER, out_path=dest,
             rows_out=len(fc["features"]))


def at_counts():
    pkg = ckan_package(CKAN_CA, AT_PACKAGE)
    for res in pkg["resources"]:
        name = res["name"].strip()
        if res.get("format", "").upper() == "XLSX" and "Dictionary" in name:
            info = download(res["url"], out_dir(PROCESSED, NAME) / "at_count_data_dictionary.xlsx")
            log_pull(NAME, name, url=res["url"], out_path=info["path"], sha256=info["sha256"])
            continue
        if not (name.endswith(tuple(str(y) for y in range(2020, 2031))) and "Count Dataset" in name):
            continue
        parts, rows_in = [], 0
        with stream(res["url"], timeout=300) as (fh, hasher):
            for chunk in pd.read_csv(fh, dtype=str, chunksize=250_000):
                rows_in += len(chunk)
                lat = pd.to_numeric(chunk["latitude"], errors="coerce")
                lon = pd.to_numeric(chunk["longitude"], errors="coerce")
                inside = lon.between(BBOX[0], BBOX[2]) & lat.between(BBOX[1], BBOX[3])
                parts.append(chunk[(chunk["district"].str.strip() == "4") & inside])
        df = pd.concat(parts, ignore_index=True)
        stem = name.lower().replace(" dataset", "").replace(" ", "_")
        dest = out_dir(PROCESSED, NAME) / f"{stem}_alameda_area.parquet"
        df.to_parquet(dest, index=False)
        log.info("%s: kept %d of %d rows (%d sites)", name, len(df), rows_in, df["loc_id"].nunique())
        log_pull(NAME, name, url=res["url"], out_path=dest, sha256=hasher.sha256.hexdigest(),
                 nbytes=hasher.nbytes, rows_in=rows_in, rows_out=len(df), sites=int(df["loc_id"].nunique()))


def run(args):
    aadt()
    at_counts()
