"""Extra segment inputs for the crash model (the cheap ones).

    python -m analysis.features        # after analysis.segments

Adds to each segment (written to data/processed/analysis/segment_features.parquet):
    OSM way tags   sidewalk_known / sidewalk_yes, bike_known / bike_lane / bike_shared
                   (osmnx discards these tags, so the OSM file is parsed directly; "known" = someone
                   mapped the tag, so the flags are only informative where known)
    OSM nodes      n_crossings, n_marked_crossings, n_unmarked_crossings, n_calming (within 12 m)
    LODES 2023     jobs per km2 in the block group (daytime activity proxy)
    ACS 2020-24    walk, bicycle and transit commute shares, share of households with no vehicle,
                   median household income, poverty share (tract level)

Coverage and the missing-data pattern are printed; OSM tag coverage is much higher on arterials than
on local streets, and varies by city, so models use the "known" flags alongside the values.
"""
from __future__ import annotations

import bz2
import logging
import xml.etree.ElementTree as ET

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import LineString

from alameda_traffic.config import PROCESSED
from alameda_traffic.geocode import PROJ
from alameda_traffic.provenance import log_pull

log = logging.getLogger("analysis.features")
DRIVABLE = {"primary", "secondary", "tertiary", "trunk", "unclassified", "residential", "primary_link", "secondary_link",
            "tertiary_link", "trunk_link", "living_street", "road"}
SW_KEYS = ("sidewalk", "sidewalk:both", "sidewalk:left", "sidewalk:right")
SW_YES = {"both", "left", "right", "yes", "separate"}
LANE = {"lane", "track", "opposite_lane", "opposite_track", "buffered_lane"}
SHARED = {"shared_lane", "share_busway", "shared_busway", "sharrow"}
MARKED = {"marked", "uncontrolled", "zebra", "traffic_signals"}


def osm_ways() -> gpd.GeoDataFrame:
    nodes, rows = {}, []
    with bz2.open(PROCESSED / "osm" / "highways.osm.bz2", "rb") as fh:
        for _, el in ET.iterparse(fh, events=("end",)):
            if el.tag == "node":
                nodes[int(el.get("id"))] = (float(el.get("lon")), float(el.get("lat")))
            elif el.tag == "way":
                tags = {t.get("k"): t.get("v") for t in el.findall("tag")}
                if tags.get("highway") in DRIVABLE:
                    pts = [nodes.get(int(n.get("ref"))) for n in el.findall("nd")]
                    if len(pts) >= 2 and all(pts):
                        sw = [tags[k] for k in SW_KEYS if k in tags]
                        cy = [v for k, v in tags.items() if k.startswith("cycleway")]
                        rows.append({"geometry": LineString(pts), "sidewalk_known": bool(sw),
                                     "sidewalk_yes": any(v in SW_YES for v in sw),
                                     "bike_known": bool(cy), "bike_lane": any(v in LANE for v in cy),
                                     "bike_shared": any(v in SHARED for v in cy)})
            if el.tag in ("node", "way"):
                el.clear()
    return gpd.GeoDataFrame(rows, crs=4326).to_crs(PROJ)


def count_near(seg: gpd.GeoDataFrame, pts: gpd.GeoDataFrame, dist: float) -> np.ndarray:
    tree = shapely.STRtree(pts.geometry.values)
    si, _ = tree.query(seg.geometry.values, predicate="dwithin", distance=dist)
    return pd.Series(1, index=si).groupby(level=0).sum().reindex(range(len(seg)), fill_value=0).values


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    A = PROCESSED / "analysis"
    seg = gpd.read_parquet(A / "segments.parquet")
    mid = gpd.GeoDataFrame(seg[["segment_id", "tract"]], geometry=seg.geometry.interpolate(0.5, normalized=True), crs=PROJ)
    out = pd.DataFrame({"segment_id": seg.segment_id.values})

    log.info("parsing OSM way tags")
    ways = osm_ways()
    j = gpd.sjoin_nearest(mid[["segment_id", "geometry"]], ways, max_distance=25, how="left", distance_col="d")
    j = j.sort_values("d").drop_duplicates("segment_id").set_index("segment_id").reindex(out.segment_id)
    for c in ("sidewalk_known", "sidewalk_yes", "bike_known", "bike_lane", "bike_shared"):
        out[c] = j[c].fillna(False).astype(int).values

    ctl = gpd.read_file(PROCESSED / "osm" / "traffic_control.geojson").to_crs(PROJ)
    ctl = ctl[ctl.geom_type == "Point"]
    cr = ctl[(ctl.highway == "crossing") | ctl.crossing.notna()]
    out["n_crossings"] = count_near(seg, cr, 12)
    out["n_marked_crossings"] = count_near(seg, cr[cr.crossing.isin(MARKED)], 12)
    out["n_unmarked_crossings"] = count_near(seg, cr[cr.crossing == "unmarked"], 12)
    out["n_calming"] = count_near(seg, ctl[ctl.traffic_calming.notna()], 12)

    lo = pd.read_parquet(PROCESSED / "census" / "lodes8_wac_alameda.parquet", columns=["w_geocode", "C000", "year"])
    lo = lo[lo.year == 2023].assign(bg=lambda d: d.w_geocode.astype(str).str[:12]).groupby("bg").C000.sum()
    bgs = gpd.read_file(PROCESSED / "census" / "tiger_acs2024_block_groups.geojson").to_crs(PROJ)[["GEOID", "AREALAND", "geometry"]]
    bgs["jobs_density_km2"] = bgs.GEOID.map(lo).fillna(0) / (pd.to_numeric(bgs.AREALAND) / 1e6)
    bj = gpd.sjoin(mid[["segment_id", "geometry"]], bgs[["jobs_density_km2", "geometry"]], how="left", predicate="within")
    out["jobs_density_km2"] = bj.drop_duplicates("segment_id").set_index("segment_id").reindex(out.segment_id)["jobs_density_km2"].values

    def acs(table, cols):
        d = pd.read_parquet(PROCESSED / "census" / f"acs2024_5yr_{table}.parquet")
        d = d[d.geo_level == "tract"].assign(tract=lambda x: x.GEO_ID.str[-11:])
        return d[["tract"] + cols].apply(lambda s: pd.to_numeric(s, errors="coerce") if s.name != "tract" else s)
    c1 = acs("B08301", ["B08301_001E", "B08301_010E", "B08301_018E", "B08301_019E"]).set_index("tract")
    c2 = acs("B08201", ["B08201_001E", "B08201_002E"]).set_index("tract")
    c3 = acs("B19013", ["B19013_001E"]).set_index("tract")
    c4 = acs("B17001", ["B17001_001E", "B17001_002E"]).set_index("tract")
    tr = pd.DataFrame({
        "walk_share": c1.B08301_019E / c1.B08301_001E, "bike_share": c1.B08301_018E / c1.B08301_001E,
        "transit_share": c1.B08301_010E / c1.B08301_001E, "zero_veh_share": c2.B08201_002E / c2.B08201_001E,
        "median_income": c3.B19013_001E.where(c3.B19013_001E > 0), "poverty_share": c4.B17001_002E / c4.B17001_001E})
    out = out.merge(tr, left_on=seg.tract.values, right_index=True, how="left").drop(columns="key_0", errors="ignore")
    out.to_parquet(A / "segment_features.parquet", index=False)
    log_pull("analysis", "segment_features", out_path=A / "segment_features.parquet", rows_out=len(out), note="built by analysis/features.py")

    s = seg.drop(columns="geometry")
    s["cls"] = s.osm_class.replace({"primary_link": "primary", "secondary_link": "secondary", "tertiary_link": "tertiary", "trunk_link": "trunk"})
    f = out.merge(s[["segment_id", "cls"]], on="segment_id")
    arterial = f.cls.isin(["primary", "secondary", "tertiary", "trunk"])
    print(f"\n{len(out):,} segments. Share with each flag (arterials / local):")
    for c in ("sidewalk_known", "sidewalk_yes", "bike_known", "bike_lane", "bike_shared"):
        print(f"  {c:18} {f.loc[arterial, c].mean():.2f} / {f.loc[~arterial, c].mean():.2f}")
    print(f"  segments with a crossing within 12 m: {(out.n_crossings > 0).mean():.2f}; marked {(out.n_marked_crossings > 0).mean():.2f}; calming {(out.n_calming > 0).mean():.2f}")
    print("  numeric coverage:", {c: round(float(out[c].notna().mean()), 3) for c in ("jobs_density_km2", "walk_share", "bike_share", "zero_veh_share", "median_income", "poverty_share")})
    print("  medians: jobs/km2 %.0f, walk %.3f, bike %.3f, no-car %.3f, income %.0f" % tuple(out[c].median() for c in ("jobs_density_km2", "walk_share", "bike_share", "zero_veh_share", "median_income")))


if __name__ == "__main__":
    main()
