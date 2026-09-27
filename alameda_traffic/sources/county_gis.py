"""County and regional GIS layers.

Access: API (ArcGIS REST).
- Alameda County street centerlines (data.acgov.org): street-name parts and
  left/right address ranges — the key input for geocoding CCRS crashes that
  have no coordinates (about a third of Alameda injury crashes).
- Alameda County city boundaries (data.acgov.org).
- MTC Regional Bike Facilities: kept for completeness, but weak — only
  objectid/class/length, last edited May 2021, no install dates or names.
"""
from __future__ import annotations

from .. import arcgis
from ..config import BBOX, PROCESSED, out_dir
from ..provenance import log_pull

NAME = "county_gis"
HELP = "County street centerlines (address ranges), city boundaries, MTC bike facilities"

LAYERS = {  # stem -> (url, where, bbox filter)
    "street_centerlines": ("https://services5.arcgis.com/ROBnTHSNjoZ2Wm1P/arcgis/rest/services/"
                           "Street_Centerlines/FeatureServer/0", "1=1", None),
    "cities": ("https://services7.arcgis.com/6Yz0DcWQc1LtdRPC/arcgis/rest/services/Cities/FeatureServer/0",
               "1=1", None),
    "mtc_regional_bike_facilities_2021": ("https://services3.arcgis.com/i2dkYWmb4wHvYPda/arcgis/rest/"
                                          "services/regional_bike_facilities/FeatureServer/0", "1=1", BBOX),
}


def run(args):
    for stem, (url, where, bbox) in LAYERS.items():
        fc = arcgis.query_all(url, where, bbox=bbox)
        dest = arcgis.save_geojson(fc, out_dir(PROCESSED, NAME) / f"{stem}.geojson")
        log_pull(NAME, stem, url=url, out_path=dest, rows_out=len(fc["features"]),
                 bbox=list(bbox) if bbox else None)
