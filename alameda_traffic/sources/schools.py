"""Schools: CDE public school sites (one layer per school year), NCES private
school locations, the CDE directory (manual), and school calendars (manual).

Access:
- CDE School Sites: API (ArcGIS REST). Each year's layer lists only schools
  active that year, so match layers to crash years. Nothing before 2021-22.
- NCES private schools: API (NCES EDGE MapServer), biennial.
- CDE public school directory (pubschls.txt; includes closed schools with
  open/closed dates): MANUAL — cde.ca.gov serves it behind a bot-check CAPTCHA.
  Download it in a browser to data/manual/pubschls.txt, then rerun.
- School calendars: MANUAL — fill data/manual/school_calendars.csv from the
  template in data/manual/templates/.
"""
from __future__ import annotations

import logging
import shutil

import pandas as pd

from .. import arcgis
from ..config import MANUAL, PROCESSED, out_dir
from ..http import sha256_file
from ..provenance import log_pull

NAME = "schools"
HELP = "CDE public school sites by year, NCES private schools, CDE directory, calendars"
log = logging.getLogger(__name__)

CDE_SITES = "https://services3.arcgis.com/fdvHcZVgB2QSRNkL/arcgis/rest/services/SchoolSites{sy}/FeatureServer/0"
CDE_YEARS = ["2122", "2223", "2324", "2425", "2526"]
NCES_PRIVATE = ("https://nces.ed.gov/opengis/rest/services/K12_School_Locations/"
                "EDGE_GEOCODE_PRIVATESCH_{sy}/MapServer/0")
NCES_YEARS = ["1920", "2122", "2324"]
DIRECTORY_URL = "https://www.cde.ca.gov/ds/si/ds/pubschls.asp"


def _county_where(layer_url: str, value: str) -> str:
    fields = {f["name"] for f in arcgis.layer_info(layer_url)["fields"]}
    for name in ("CountyName", "County", "COUNTY", "CountyNam", "NMCNTY"):
        if name in fields:
            return f"{name}='{value}'"
    raise RuntimeError(f"no county field in {layer_url}: {sorted(fields)}")


def cde_sites():
    for sy in CDE_YEARS:
        url = CDE_SITES.format(sy=sy)
        where = _county_where(url, "Alameda")
        fc = arcgis.query_all(url, where)
        dest = arcgis.save_geojson(fc, out_dir(PROCESSED, NAME) / f"cde_school_sites_{sy}.geojson")
        log_pull(NAME, f"CDE school sites 20{sy[:2]}-{sy[2:]}", url=url, out_path=dest,
                 rows_out=len(fc["features"]), where=where)


def nces_private():
    for sy in NCES_YEARS:
        url = NCES_PRIVATE.format(sy=sy)
        where = _county_where(url, "Alameda County")
        fc = arcgis.query_all(url, where)
        dest = arcgis.save_geojson(fc, out_dir(PROCESSED, NAME) / f"nces_private_schools_{sy}.geojson")
        log_pull(NAME, f"NCES private school geocodes 20{sy[:2]}-{sy[2:]}", url=url, out_path=dest,
                 rows_out=len(fc["features"]), where=where)


def cde_directory():
    src = MANUAL / "pubschls.txt"
    if not src.exists():
        log.warning("CDE directory not found at %s — download 'Public Schools and Districts' "
                    "(tab-delimited) from %s in a browser (CAPTCHA-protected), save it there, rerun.",
                    src, DIRECTORY_URL)
        return
    df = pd.read_csv(src, sep="\t", dtype=str, encoding="utf-8", encoding_errors="replace")
    df = df[df["County"] == "Alameda"]
    dest = out_dir(PROCESSED, NAME) / "cde_public_schools_directory_alameda.parquet"
    df.to_parquet(dest, index=False)
    log_pull(NAME, "CDE public schools directory (manual download)", url=DIRECTORY_URL,
             out_path=dest, sha256=sha256_file(src), rows_out=len(df))


def calendars():
    src = MANUAL / "school_calendars.csv"
    if not src.exists():
        log.warning("No %s yet — copy data/manual/templates/school_calendars.csv there and fill it in.", src)
        return
    dest = out_dir(PROCESSED, NAME) / "school_calendars.csv"
    shutil.copy2(src, dest)
    log_pull(NAME, "school calendars (hand-collected)", out_path=dest, sha256=sha256_file(src))


def run(args):
    cde_sites()
    nces_private()
    cde_directory()
    calendars()
