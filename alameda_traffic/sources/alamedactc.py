"""Alameda CTC safety networks — RESTRICTED (stored under data/restricted/, never committed).

Two sources:

1. OFFICIAL files (preferred). Shannon McCarthy (Alameda CTC, Senior Transportation Planner)
   sent two shapefile zips on 2026-10-02 in reply to a data request:
       Final_AT_HIN_1822.zip   2024 Active Transportation High-Injury Network (TIMS 2018-2022)
       Concept_PSN_092724.zip  2024 Concept Proactive Safety Network
   They are SharePoint links that need a signed-in browser, so they are a MANUAL download:
   save both zips in data/restricted/alamedactc_official/ and run `python download.py alamedactc`.
   Geometry + a street-name field only (no scores). Alameda CTC gave no permission to
   redistribute them, so they stay restricted; summary statistics are fine to publish.
   They match the dev-server layers below to within 1 m, so earlier analysis is unaffected.

2. Fehr & Peers development server (API, READ-ONLY). Serves the layers behind Alameda CTC's
   public "Mega Map". Used only for layers not in the official files: HIN 2019, draft
   Countywide Bikeways Network 2022, SR2S schools 2024. Unofficial; this module only calls
   /query and the server advertises edit capabilities, so never send it anything else.

Methodology: the Sept 2024 HIN/PSN report (also downloaded).
"""
from __future__ import annotations

import logging

import geopandas as gpd

from .. import arcgis
from ..config import RESTRICTED, out_dir
from ..http import download, sha256_file
from ..provenance import log_pull

NAME = "alamedactc"
HELP = "Alameda CTC HIN/PSN: official shapefiles (manual) + unofficial dev-server layers (restricted)"
log = logging.getLogger(__name__)

OFFICIAL_DIR = RESTRICTED / "alamedactc_official"
OFFICIAL = {  # zip stem -> output name
    "Final_AT_HIN_1822": "hin_2024",
    "Concept_PSN_092724": "psn_2024_concept",
}
SERVER = "https://devapps.fehrandpeers.com/devgis/rest/services/OK/Alameda_CTC_Mega_Map/FeatureServer"
DEV_LAYERS = {71: "hin_2019", 1: "countywide_bikeways_2022_draft", 12: "sr2s_schools_2024"}
REPORT = "https://www.alamedactc.org/wp-content/uploads/2024/09/HIN_PSN_Report.pdf"


def official():
    for stem, out in OFFICIAL.items():
        z = OFFICIAL_DIR / f"{stem}.zip"
        if not z.exists():
            log.warning("official file missing: %s — open Shannon McCarthy's 2026-10-02 email in a browser, "
                        "download it, and save it there", z)
            continue
        g = gpd.read_file(f"zip://{z}!{stem}.shp")
        src_crs = g.crs.to_string()
        g = g.to_crs(4326)
        dest = out_dir(RESTRICTED, NAME) / f"{out}.geojson"
        g.to_file(dest, driver="GeoJSON")
        log_pull(NAME, f"{out} (official, from Alameda CTC)", url="email from Alameda CTC planning staff, 2026-10-02",
                 out_path=dest, sha256=sha256_file(z), rows_out=len(g), source_crs=src_crs,
                 license="none stated (restricted); received in reply to a research data request")


def dev_server():
    for layer, stem in DEV_LAYERS.items():
        url = f"{SERVER}/{layer}"
        fc = arcgis.query_all(url)
        dest = arcgis.save_geojson(fc, out_dir(RESTRICTED, NAME) / f"{stem}.geojson")
        log_pull(NAME, f"{stem} (unofficial dev server)", url=url, out_path=dest, rows_out=len(fc["features"]),
                 license="none (restricted)")


def run(args):
    official()
    dev_server()
    info = download(REPORT, out_dir(RESTRICTED, NAME) / "HIN_PSN_Report_2024-09.pdf")
    log_pull(NAME, "HIN & PSN methodology report (Sept 2024)", url=REPORT, out_path=info["path"],
             sha256=info["sha256"], nbytes=info["bytes"])
