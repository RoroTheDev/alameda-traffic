"""Equity layers: MTC/ABAG Equity Priority Communities and CalEnviroScreen 5.0.

Access:
- EPC Plan Bay Area 2050+ (ACS 2018–2022, 2020 tracts): BULK CSV published on
  MTC's GitHub Pages (attributes only — join to TIGER 2020 tracts).
- EPC Plan Bay Area 2050 (ACS 2014–2018, 2010 tracts): API (MTC ArcGIS hub),
  with polygons. PBA 2050+ keeps every tract that was an EPC in 2050, so both
  vintages are needed to reproduce the consolidated map.
- CalEnviroScreen 5.0 (final, July 2026): BULK CSV from data.ca.gov.
"""
from __future__ import annotations

import pandas as pd

from .. import arcgis
from ..config import COUNTY_FIPS, PROCESSED, out_dir
from ..http import download
from ..provenance import log_pull

NAME = "equity"
HELP = "MTC Equity Priority Communities (2050, 2050+) and CalEnviroScreen 5.0"

EPC_2050P_CSV = ("https://bayareametro.github.io/Spatial-Analysis-Mapping-Projects/Project-Documentation/"
                 "Equity-Priority-Communities/Data/epc_acs2022.csv")
EPC_2050_LAYER = ("https://services3.arcgis.com/i2dkYWmb4wHvYPda/arcgis/rest/services/"
                  "communities_of_concern_2020_acs2018/FeatureServer/0")
CES5_CSV = ("https://data.ca.gov/dataset/72b28c84-ceac-4886-9f71-d422470d2223/resource/"
            "c4e277e0-cf23-4a8f-b07e-c8544c5d3d2b/download/calenviroscreen50_070126.csv")


def _csv_filtered(url: str, dest_name: str, label: str, filt, **read_kw):
    tmp = out_dir(PROCESSED, NAME) / (dest_name + ".download")
    info = download(url, tmp)
    df = pd.read_csv(tmp, dtype=str, **read_kw)
    tmp.unlink()
    rows_in = len(df)
    df = df[filt(df)]
    dest = out_dir(PROCESSED, NAME) / dest_name
    df.to_parquet(dest, index=False)
    log_pull(NAME, label, url=url, out_path=dest, sha256=info["sha256"], nbytes=info["bytes"],
             rows_in=rows_in, rows_out=len(df))


def run(args):
    _csv_filtered(EPC_2050P_CSV, "epc_pba2050plus_acs2022_alameda.parquet",
                  "EPC Plan Bay Area 2050+ (ACS 2018-2022)", lambda d: d["county_fip"] == COUNTY_FIPS)

    fc = arcgis.query_all(EPC_2050_LAYER, f"county_fip='{COUNTY_FIPS}'")
    dest = arcgis.save_geojson(fc, out_dir(PROCESSED, NAME) / "epc_pba2050_acs2018_alameda.geojson")
    log_pull(NAME, "EPC Plan Bay Area 2050 (ACS 2014-2018)", url=EPC_2050_LAYER, out_path=dest,
             rows_out=len(fc["features"]))

    # CES tract IDs drop the leading zero (6001400100); keep as string.
    _csv_filtered(CES5_CSV, "calenviroscreen5_alameda.parquet", "CalEnviroScreen 5.0",
                  lambda d: d["county"] == "Alameda")
