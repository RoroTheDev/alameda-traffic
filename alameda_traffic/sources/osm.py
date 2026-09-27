"""OpenStreetMap via the Overpass API (county only — not the 650 MB NorCal extract).

Access: API. County-wide queries time out (HTTP 504) on the public Overpass
servers, so every pull is split into bounding-box tiles (each clipped to the
county area) and merged, de-duplicated by OSM id. Each pull records
Overpass's OSM snapshot time.
- highways.osm.bz2: every highway=* way in the county plus its nodes (drive,
  walk and bike network) as OSM XML. Load with osmnx.graph_from_xml().
- traffic_control.geojson: stop / yield / signals / crossings / traffic calming.
- pois.geojson: schools, childcare, hospitals, clinics, senior facilities,
  parks, transit stations and bus stops.

Coverage is uneven by city (e.g. very few stop signs mapped in Pleasanton,
Fremont, Dublin, Newark) — see docs/DATA_SOURCES.md. OSM edit dates are not
installation dates.

License: ODbL 1.0 — attribute "© OpenStreetMap contributors"; published
derived databases must also be ODbL.
"""
from __future__ import annotations

import bz2
import json
import logging
from xml.sax.saxutils import quoteattr

from ..config import BBOX, PROCESSED, out_dir
from ..http import SESSION
from ..provenance import log_pull

NAME = "osm"
HELP = "OpenStreetMap roads, traffic-control features and POIs for Alameda County"
log = logging.getLogger(__name__)

ENDPOINTS = ["https://overpass-api.de/api/interpreter",
             "https://overpass.private.coffee/api/interpreter"]
AREA = "area(id:3600396499)->.a;"  # relation 396499 = Alameda County, CA (FIPS 06001)

CONTROL = [
    'node["highway"~"^(stop|give_way|traffic_signals|crossing|mini_roundabout|speed_camera)$"]',
    'node["crossing"]',
    'node["traffic_calming"]',
    'way["traffic_calming"]',
    'node["railway"="level_crossing"]',
]
POIS = [
    'nwr["amenity"~"^(school|kindergarten|childcare|college|university|hospital|clinic|doctors|'
    'social_facility|community_centre|library)$"]',
    'nwr["leisure"~"^(park|playground)$"]',
    'nwr["public_transport"="station"]',
    'node["highway"="bus_stop"]',
]


def add_arguments(p):
    p.add_argument("--only", choices=["highways", "control", "pois"])


def _post(query: str):
    last = None
    for url in ENDPOINTS:
        try:
            r = SESSION.post(url, data={"data": query}, stream=True, timeout=1800)
            r.raise_for_status()
            return r, url
        except Exception as exc:  # try the next mirror
            log.warning("Overpass %s failed: %s", url, exc)
            last = exc
    raise RuntimeError(f"all Overpass endpoints failed: {last}")


def _tiles(nx: int, ny: int):
    x0, y0, x1, y1 = BBOX
    dx, dy = (x1 - x0) / nx, (y1 - y0) / ny
    for i in range(nx):
        for j in range(ny):
            yield (y0 + j * dy, x0 + i * dx, y0 + (j + 1) * dy, x0 + (i + 1) * dx)  # s, w, n, e


def _tiled(build_query, nx: int, ny: int, label: str):
    """Run build_query(bbox_str) per tile; return (elements by (type, id), stamps, url)."""
    elements, stamps, url = {}, set(), None
    tiles = list(_tiles(nx, ny))
    for k, (s, w, n, e) in enumerate(tiles, 1):
        r, url = _post(build_query(f"{s:.5f},{w:.5f},{n:.5f},{e:.5f}"))
        with r:
            payload = r.json()
        if payload.get("remark"):
            raise RuntimeError(f"Overpass remark on {label} tile {k}: {payload['remark']}")
        stamps.add(payload.get("osm3s", {}).get("timestamp_osm_base"))
        for el in payload["elements"]:
            elements[(el["type"], el["id"])] = el
        log.info("OSM %s tile %d/%d: %d elements so far", label, k, len(tiles), len(elements))
    return elements, sorted(s for s in stamps if s), url


def _write_osm_xml(path, nodes: dict, ways: dict, osm_base: str):
    with bz2.open(path, "wt", encoding="utf-8") as out:
        out.write('<?xml version="1.0" encoding="UTF-8"?>\n'
                  '<osm version="0.6" generator="alameda-traffic (Overpass tiles)">\n'
                  f'<meta osm_base={quoteattr(osm_base)}/>\n')
        for nid in sorted(nodes):
            n = nodes[nid]
            tags = n.get("tags", {})
            if tags:
                out.write(f'<node id="{nid}" lat="{n["lat"]}" lon="{n["lon"]}">'
                          + "".join(f"<tag k={quoteattr(k)} v={quoteattr(v)}/>" for k, v in tags.items())
                          + "</node>\n")
            else:
                out.write(f'<node id="{nid}" lat="{n["lat"]}" lon="{n["lon"]}"/>\n')
        for wid in sorted(ways):
            w = ways[wid]
            out.write(f'<way id="{wid}">' + "".join(f'<nd ref="{r}"/>' for r in w["nodes"])
                      + "".join(f"<tag k={quoteattr(k)} v={quoteattr(v)}/>" for k, v in w.get("tags", {}).items())
                      + "</way>\n")
        out.write("</osm>\n")


def highways():
    elements, stamps, url = _tiled(
        lambda bb: f'[out:json][timeout:600];{AREA}way["highway"]({bb})(area.a);(._;>;);out body;',
        6, 3, "highways")
    nodes = {i: el for (t, i), el in elements.items() if t == "node"}
    ways = {i: el for (t, i), el in elements.items() if t == "way"}
    missing = {ref for w in ways.values() for ref in w["nodes"]} - nodes.keys()
    if missing:
        raise RuntimeError(f"{len(missing)} way nodes missing from Overpass results")
    dest = out_dir(PROCESSED, NAME) / "highways.osm.bz2"
    tmp = dest.with_suffix(".bz2.part")
    _write_osm_xml(tmp, nodes, ways, stamps[-1])
    tmp.replace(dest)
    log_pull(NAME, "highways (all highway=* ways + nodes, 18 tiles)", url=url, out_path=dest,
             rows_out=len(ways), nodes=len(nodes), osm_timestamp=stamps[-1], osm_timestamps_all=stamps)


def _to_geojson(elements) -> dict:
    feats = []
    for e in elements:
        if e["type"] == "node":
            geom = {"type": "Point", "coordinates": [e["lon"], e["lat"]]}
        elif "center" in e:
            geom = {"type": "Point", "coordinates": [e["center"]["lon"], e["center"]["lat"]]}
        elif "geometry" in e:
            geom = {"type": "LineString", "coordinates": [[p["lon"], p["lat"]] for p in e["geometry"]]}
        else:
            continue
        props = {"osm_type": e["type"], "osm_id": e["id"], **e.get("tags", {})}
        feats.append({"type": "Feature", "geometry": geom, "properties": props})
    return {"type": "FeatureCollection", "features": feats}


def _features(selectors: list[str], out: str, stem: str, label: str):
    elements, stamps, url = _tiled(
        lambda bb: (f"[out:json][timeout:600];{AREA}("
                    + "".join(f"{s}({bb})(area.a);" for s in selectors) + f");{out};"),
        3, 2, stem)
    fc = _to_geojson(elements.values())
    dest = out_dir(PROCESSED, NAME) / f"{stem}.geojson"
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(fc, fh)
    log_pull(NAME, label, url=url, out_path=dest, rows_out=len(fc["features"]),
             osm_timestamp=stamps[-1] if stamps else None, selectors=selectors, tiles=6)


def run(args):
    if args.only in (None, "highways"):
        highways()
    if args.only in (None, "control"):
        _features(CONTROL, "out tags geom", "traffic_control", "traffic-control features")
    if args.only in (None, "pois"):
        _features(POIS, "out tags center", "pois", "destinations / points of interest")
