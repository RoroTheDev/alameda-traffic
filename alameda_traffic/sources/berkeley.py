"""City of Berkeley open data (Socrata): traffic signal inventory (2018).

Access: API (Socrata SODA). Records look pole/mount-level (mounttype,
poletype), not one row per intersection — cluster before counting.
"""
from __future__ import annotations

import json

from ..config import PROCESSED, out_dir
from ..portals import socrata_rows, socrata_view
from ..provenance import log_pull

NAME = "berkeley"
HELP = "Berkeley traffic signal inventory (2018)"

DOMAIN = "data.cityofberkeley.info"
DATASET = "nxqb-ng9a"


def run(args):
    fc = socrata_rows(DOMAIN, DATASET, fmt="geojson")
    dest = out_dir(PROCESSED, NAME) / "traffic_signals_2018.geojson"
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(fc, fh)
    view = socrata_view(DOMAIN, DATASET)
    log_pull(NAME, "traffic signals", url=f"https://{DOMAIN}/resource/{DATASET}.geojson", out_path=dest,
             rows_out=len(fc["features"]), rows_updated_at=view.get("rowsUpdatedAt"))
