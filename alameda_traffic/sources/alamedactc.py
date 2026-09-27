"""Alameda CTC safety networks — RESTRICTED (not openly licensed).

Access: API, READ-ONLY. The layers are served from Fehr & Peers' ArcGIS
development server behind Alameda CTC's public "Mega Map". They are not an
official open-data release, so they are saved under data/restricted/ and must
not be committed or published. Ask Alameda CTC for an official copy and
permission before sharing anything derived from them beyond summary stats.

This module only calls /query. The server advertises edit capabilities —
never send it anything else.

Layers: HIN 2019 (TIMS 2012–2016), HIN 2024 (TIMS 2018–2022), Concept PSN
2024 (points-based "Proactive Safety Network"; not a predictive tool), draft
Countywide Bikeways Network 2022, SR2S schools 2024. Geometry + names only —
no scores. Methodology: the Sept 2024 HIN/PSN report (also downloaded).
"""
from __future__ import annotations

from .. import arcgis
from ..config import RESTRICTED, out_dir
from ..http import download
from ..provenance import log_pull

NAME = "alamedactc"
HELP = "Alameda CTC HIN 2019/2024, PSN 2024, bikeways draft, SR2S schools (restricted)"

SERVER = "https://devapps.fehrandpeers.com/devgis/rest/services/OK/Alameda_CTC_Mega_Map/FeatureServer"
LAYERS = {71: "hin_2019", 9: "hin_2024", 10: "psn_2024_concept", 1: "countywide_bikeways_2022_draft",
          12: "sr2s_schools_2024"}
REPORT = "https://www.alamedactc.org/wp-content/uploads/2024/09/HIN_PSN_Report.pdf"


def run(args):
    for layer, stem in LAYERS.items():
        url = f"{SERVER}/{layer}"
        fc = arcgis.query_all(url)
        dest = arcgis.save_geojson(fc, out_dir(RESTRICTED, NAME) / f"{stem}.geojson")
        log_pull(NAME, stem, url=url, out_path=dest, rows_out=len(fc["features"]), license="none (restricted)")
    info = download(REPORT, out_dir(RESTRICTED, NAME) / "HIN_PSN_Report_2024-09.pdf")
    log_pull(NAME, "HIN & PSN methodology report (Sept 2024)", url=REPORT, out_path=info["path"],
             sha256=info["sha256"], nbytes=info["bytes"])
