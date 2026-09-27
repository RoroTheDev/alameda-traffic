"""Mapillary traffic-sign detections (stop / yield) — used to audit OSM coverage.

Access: TOKEN — set MAPILLARY_TOKEN (free, mapillary.com/dashboard/developers).
Graph API /map_features limits each request's bbox to < 0.01 square degrees
and 2,000 results, so the county envelope is tiled into 0.05° cells and any
cell that hits the cap is split in four.

A detection means a sign was seen in street imagery between first_seen_at and
last_seen_at — not when it was installed. License: CC BY-SA 4.0.
"""
from __future__ import annotations

import json
import logging

from ..config import BBOX, MAPILLARY_TOKEN, PROCESSED, out_dir
from ..http import get_json
from ..provenance import log_pull

NAME = "mapillary"
HELP = "Mapillary stop/yield sign detections (needs MAPILLARY_TOKEN)"
OPTIONAL = True
log = logging.getLogger(__name__)

URL = "https://graph.mapillary.com/map_features"
OBJECT_VALUES = "regulatory--stop--g1,regulatory--yield--g1,regulatory--all-way--g1"
FIELDS = "id,object_value,geometry,first_seen_at,last_seen_at,aligned_direction"
LIMIT = 2000


def _cells(bbox, step):
    x0, y0, x1, y1 = bbox
    x = x0
    while x < x1:
        y = y0
        while y < y1:
            yield (x, y, min(x + step, x1), min(y + step, y1))
            y += step
        x += step


def _fetch(cell, depth=0):
    resp = get_json(URL, {"access_token": MAPILLARY_TOKEN, "fields": FIELDS, "object_values": OBJECT_VALUES,
                          "bbox": ",".join(f"{v:.6f}" for v in cell), "limit": LIMIT})
    data = resp.get("data", [])
    if len(data) >= LIMIT and depth < 6:  # capped: split the cell
        x0, y0, x1, y1 = cell
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        out = []
        for sub in ((x0, y0, mx, my), (mx, y0, x1, my), (x0, my, mx, y1), (mx, my, x1, y1)):
            out.extend(_fetch(sub, depth + 1))
        return out
    return data


def run(args):
    if not MAPILLARY_TOKEN:
        log.warning("MAPILLARY_TOKEN not set; skipping Mapillary")
        return
    seen, feats = set(), []
    for cell in _cells(BBOX, 0.05):
        for d in _fetch(cell):
            if d["id"] in seen:
                continue
            seen.add(d["id"])
            feats.append({"type": "Feature", "geometry": d["geometry"],
                          "properties": {k: v for k, v in d.items() if k != "geometry"}})
    dest = out_dir(PROCESSED, NAME) / "traffic_signs_stop_yield.geojson"
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump({"type": "FeatureCollection", "features": feats}, fh)
    log_pull(NAME, "map_features stop/yield/all-way signs", url=URL, out_path=dest, rows_out=len(feats),
             object_values=OBJECT_VALUES, bbox=list(BBOX), license="CC BY-SA 4.0")
