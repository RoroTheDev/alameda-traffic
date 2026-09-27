"""Open-data portal helpers: CKAN (data.ca.gov, data.chhs.ca.gov) and Socrata."""
from __future__ import annotations

from .http import get_json

CKAN_CA = "https://data.ca.gov/api/3/action/"
CKAN_CHHS = "https://data.chhs.ca.gov/api/3/action/"


def ckan_package(base: str, package_id: str) -> dict:
    resp = get_json(base + "package_show", {"id": package_id})
    if not resp.get("success"):
        raise RuntimeError(f"CKAN package {package_id}: {resp.get('error')}")
    return resp["result"]


def ckan_resource(pkg: dict, name: str) -> dict:
    for res in pkg["resources"]:
        if res["name"].strip() == name:
            return res
    raise KeyError(f"resource {name!r} not in package {pkg['name']!r}")


def socrata_view(domain: str, dataset_id: str) -> dict:
    return get_json(f"https://{domain}/api/views/{dataset_id}.json")


def socrata_rows(domain: str, dataset_id: str, *, page: int = 50000, fmt: str = "json"):
    """All rows via SODA, paged in stable :id order. fmt='json' -> list of dicts,
    fmt='geojson' -> FeatureCollection."""
    rows: list = []
    offset = 0
    while True:
        params = {"$limit": page, "$offset": offset, "$order": ":id"}
        resp = get_json(f"https://{domain}/resource/{dataset_id}.{fmt}", params)
        batch = resp["features"] if fmt == "geojson" else resp
        rows.extend(batch)
        if len(batch) < page:
            break
        offset += page
    if fmt == "geojson":
        return {"type": "FeatureCollection", "features": rows}
    return rows
