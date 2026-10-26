"""Road network for the study: drivable OSM edges and intersections, with crashes snapped on.

    python -m analysis.network

Segment = an OSM edge (the street between two intersections, after osmnx simplification),
undirected. Intersection = a node where 3+ streets meet. Neither is a fixed length, so rates
should use length or exposure offsets; HIN-style quarter-mile segments are a later variant.

Outputs (data/processed/analysis/):
    network_edges.parquet     edge_id, u, v, osm class, lanes, maxspeed_mph, length_m, name, geometry
    network_nodes.parquet     node_id, street_count, n_signals, n_stop_signs, n_crossings
    crash_network.parquet     tims_case_id, edge_id, snap_m, node_id, node_m, at_node (<=30 m)

Controls (signals, stop signs, crossings) come from the separate Overpass pull
(traffic_control.geojson), attached to the nearest intersection within 25 m. Stop-sign
coverage in OSM is very uneven by city (docs/DATA_SOURCES.md), so stop-sign counts are not
usable countywide.
"""
from __future__ import annotations

import logging
import re

import geopandas as gpd
import numpy as np
import osmnx as ox
import pandas as pd

from alameda_traffic.config import PROCESSED, out_dir
from alameda_traffic.geocode import PROJ
from alameda_traffic.provenance import log_pull

log = logging.getLogger("analysis.network")
DRIVABLE = {"motorway_link", "trunk", "trunk_link", "primary", "primary_link", "secondary", "secondary_link",
            "tertiary", "tertiary_link", "unclassified", "residential", "living_street", "road"}
SNAP_MAX_M = 100.0
NODE_NEAR_M = 30.0
CONTROL_NEAR_M = 25.0


def _first(v):
    return v[0] if isinstance(v, list) else v


def _mph(v) -> float:
    v = _first(v)
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return np.nan
    m = re.match(r"\s*(\d+(?:\.\d+)?)\s*(mph|km/h|kph)?", str(v))
    if not m:
        return np.nan
    x = float(m.group(1))
    return x if (m.group(2) or "mph") == "mph" else round(x * 0.621371, 1)


def build_network() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    log.info("loading OSM graph (takes a few minutes)")
    G = ox.graph_from_xml(PROCESSED / "osm" / "highways.osm.bz2", simplify=True, retain_all=True)
    G = ox.convert.to_undirected(G)
    nodes, edges = ox.graph_to_gdfs(G)
    edges = edges.reset_index()
    edges["highway"] = edges["highway"].map(_first)
    edges = edges[edges["highway"].isin(DRIVABLE)].copy()
    edges["edge_id"] = np.arange(len(edges))
    edges["lanes"] = pd.to_numeric(edges.get("lanes", pd.Series(index=edges.index)).map(_first), errors="coerce")
    edges["maxspeed_mph"] = edges.get("maxspeed", pd.Series(index=edges.index)).map(_mph)
    edges["name"] = edges.get("name", pd.Series(index=edges.index)).map(_first)
    edges["oneway"] = edges.get("oneway", pd.Series(False, index=edges.index)).map(lambda x: str(_first(x)).lower() in ("true", "yes", "1"))
    keep = ["edge_id", "u", "v", "highway", "name", "lanes", "maxspeed_mph", "oneway", "length", "geometry"]
    edges = edges[keep].rename(columns={"length": "length_m"}).to_crs(PROJ)

    used = set(edges.u) | set(edges.v)
    nodes = nodes[nodes.index.isin(used)].copy()
    nodes["node_id"] = nodes.index
    nodes = nodes[["node_id", "street_count", "geometry"]].reset_index(drop=True).to_crs(PROJ)

    ctrl = gpd.read_file(PROCESSED / "osm" / "traffic_control.geojson").to_crs(PROJ)
    ctrl = ctrl[ctrl.geom_type == "Point"]
    inter = nodes[nodes.street_count >= 3]
    j = gpd.sjoin_nearest(ctrl, inter[["node_id", "geometry"]], max_distance=CONTROL_NEAR_M, how="inner")
    hw = j["highway"].fillna("")
    cnt = pd.DataFrame({"node_id": j["node_id"],
                        "n_signals": (hw == "traffic_signals").astype(int),
                        "n_stop_signs": (hw == "stop").astype(int),
                        "n_crossings": hw.isin(["crossing"]).astype(int)}).groupby("node_id").sum()
    nodes = nodes.merge(cnt, left_on="node_id", right_index=True, how="left")
    for c in ("n_signals", "n_stop_signs", "n_crossings"):
        nodes[c] = nodes[c].fillna(0).astype(int)
    return edges, nodes


def snap(crashes: pd.DataFrame, edges: gpd.GeoDataFrame, nodes: gpd.GeoDataFrame) -> pd.DataFrame:
    c = crashes[crashes.lat.notna() & ~crashes.freeway].copy()
    pts = gpd.GeoDataFrame(c[["tims_case_id"]], geometry=gpd.points_from_xy(c.lon, c.lat), crs=4326).to_crs(PROJ)
    e = gpd.sjoin_nearest(pts, edges[["edge_id", "geometry"]], max_distance=SNAP_MAX_M, how="left", distance_col="snap_m")
    e = e.sort_values("snap_m").drop_duplicates("tims_case_id")[["tims_case_id", "edge_id", "snap_m"]]
    inter = nodes[nodes.street_count >= 3][["node_id", "geometry"]]
    n = gpd.sjoin_nearest(pts, inter, max_distance=NODE_NEAR_M * 4, how="left", distance_col="node_m")
    n = n.sort_values("node_m").drop_duplicates("tims_case_id")[["tims_case_id", "node_id", "node_m"]]
    out = e.merge(n, on="tims_case_id", how="outer")
    out["at_node"] = out["node_m"] <= NODE_NEAR_M
    return out


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    edges, nodes = build_network()
    crashes = pd.read_parquet(PROCESSED / "analysis" / "crashes.parquet")
    cn = snap(crashes, edges, nodes)
    d = out_dir(PROCESSED, "analysis")
    edges.to_parquet(d / "network_edges.parquet")
    nodes.to_parquet(d / "network_nodes.parquet")
    cn.to_parquet(d / "crash_network.parquet", index=False)
    for name in ("network_edges", "network_nodes", "crash_network"):
        log_pull("analysis", name, out_path=d / f"{name}.parquet", note="built by analysis/network.py from OSM pull + crashes table")

    surf = crashes[~crashes.freeway]
    print(f"\nedges: {len(edges):,} drivable ({edges.length_m.sum() / 1609.344:,.0f} mi)   intersections (3+ streets): "
          f"{int((nodes.street_count >= 3).sum()):,}")
    print("edge class mi:", (edges.groupby('highway').length_m.sum() / 1609.344).round(0).sort_values(ascending=False).head(6).to_dict())
    print(f"attribute coverage: lanes {edges.lanes.notna().mean():.2f}, maxspeed {edges.maxspeed_mph.notna().mean():.2f}, name {edges.name.notna().mean():.2f}")
    m = surf.merge(cn, on="tims_case_id", how="left")
    print(f"\nsurface crashes {len(surf):,}: with coordinate {m.lat.notna().mean():.3f}; snapped to an edge "
          f"{m.edge_id.notna().mean():.3f}; within 30 m {(m.snap_m <= 30).mean():.3f}; within 50 m {(m.snap_m <= 50).mean():.3f}")
    print("snap distance by coord source (median m):", m.groupby("coord_source").snap_m.median().round(1).to_dict())
    print(f"at an intersection node (<=30 m): {m.at_node.mean():.3f}; TIMS says intersection: {m.intersection.mean():.3f}")
    k = m[m.ksi & m.edge_id.notna()]
    per = k.groupby("edge_id").size().reindex(edges.edge_id, fill_value=0).values
    order = np.argsort(-per)
    length = edges.length_m.values[order]
    cum_k = np.cumsum(per[order]) / per.sum()
    cum_l = np.cumsum(length) / length.sum()
    for share in (0.5, 0.6, 0.8):
        i = int(np.searchsorted(cum_k, share))
        print(f"  {share:.0%} of surface KSI fall on the worst {cum_l[i]:.1%} of drivable road length")


if __name__ == "__main__":
    main()
