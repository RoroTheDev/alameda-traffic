"""Read-only ArcGIS REST helpers (FeatureServer / MapServer layers).

Features are fetched by object-ID batches rather than resultOffset paging,
which works on both FeatureServer and older MapServer layers and is not
affected by maxRecordCount caps. Only the /query endpoint is ever called.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from .http import get_json

log = logging.getLogger(__name__)


def layer_info(layer_url: str) -> dict:
    info = get_json(layer_url, {"f": "json"})
    if "error" in info:
        raise RuntimeError(f"{layer_url}: {info['error']}")
    return info


def _spatial_params(bbox: tuple[float, float, float, float] | None) -> dict:
    if bbox is None:
        return {}
    return {
        "geometry": ",".join(str(v) for v in bbox),
        "geometryType": "esriGeometryEnvelope",
        "inSR": 4326,
        "spatialRel": "esriSpatialRelIntersects",
    }


def query_all(layer_url: str, where: str = "1=1", *, out_fields: str = "*",
              bbox: tuple[float, float, float, float] | None = None,
              batch: int | None = None) -> dict:
    """Return all matching features as a GeoJSON FeatureCollection in EPSG:4326."""
    info = layer_info(layer_url)
    max_rc = int(info.get("maxRecordCount") or 1000)
    batch = min(batch or max_rc, max_rc, 1000)
    oid_field = info.get("objectIdField") or next(
        (f["name"] for f in info.get("fields", []) if f.get("type") == "esriFieldTypeOID"), "OBJECTID")

    ids_resp = get_json(f"{layer_url}/query", method="POST", data={
        "where": where, "returnIdsOnly": "true", "f": "json", **_spatial_params(bbox)})
    if "error" in ids_resp:
        raise RuntimeError(f"{layer_url}: {ids_resp['error']}")
    ids = sorted(ids_resp.get("objectIds") or [])
    log.info("%s: %d features", layer_url.rsplit("/services/", 1)[-1], len(ids))

    features: list[dict] = []
    for i in range(0, len(ids), batch):
        chunk = ids[i:i + batch]
        resp = get_json(f"{layer_url}/query", method="POST", data={
            "objectIds": ",".join(map(str, chunk)),
            "outFields": out_fields,
            "returnGeometry": "true",
            "outSR": 4326,
            "f": "geojson",
        })
        if "error" in resp:
            raise RuntimeError(f"{layer_url}: {resp['error']}")
        features.extend(resp.get("features", []))
    if len(features) != len(ids):
        raise RuntimeError(f"{layer_url}: expected {len(ids)} features, got {len(features)}")
    return {"type": "FeatureCollection", "features": features,
            "properties": {"source": layer_url, "where": where, "oid_field": oid_field}}


def count(layer_url: str, where: str = "1=1") -> int:
    resp = get_json(f"{layer_url}/query", {"where": where, "returnCountOnly": "true", "f": "json"})
    return int(resp["count"])


def save_geojson(fc: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(fc, fh)
    return path
