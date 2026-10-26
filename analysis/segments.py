"""Quarter-mile street segments with attributes, and a segment x year crash panel.

    python -m analysis.network      # first (builds edges/nodes from OSM)
    python -m analysis.segments

Segments (the HIN's unit): drivable OSM blocks are merged by street name into continuous
chains and cut into equal pieces no longer than 1/4 mile (402 m). Unnamed blocks are cut on
their own. A segment never spans two separate stretches of the same street name.

Attributes are taken at the segment midpoint:
    OSM        class, lanes, posted speed (nearest block; lanes/speed are sparse, see coverage)
    HPMS 2024  AADT, through lanes, speed limit, functional class (arterials/collectors only;
               local-street AADT is not published, and the 2022/23 values are placeholders)
    controls   OSM signals / stop signs at the segment's end intersections, intersection count
               (stop signs are not usable countywide: OSM coverage is very uneven)
    places     schools (CDE 2024-25, in-person), hospitals and nursing homes (HCAI), bus stops
               (OSM): straight-line distance and counts within 400 m
    tracts     equity priority community, CalEnviroScreen percentile, population density
    bikeways   Oakland completed bikeway projects: share of the segment covered, first year, types

Crashes are the surface injury/fatal crashes from analysis/crashes.py, assigned to the nearest
segment within 60 m. Outputs (data/processed/analysis/):
    segments.parquet       one row per segment, with static attributes and crash totals
    segment_year.parquet   segment_id x year (2016-2025), zero-filled, injury/KSI/ped/bike counts
    crash_segment.parquet  tims_case_id -> segment_id
"""
from __future__ import annotations

import logging

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import LineString, MultiLineString
from shapely.ops import substring

from alameda_traffic.config import PROCESSED
from alameda_traffic.geocode import PROJ
from alameda_traffic.provenance import log_pull

log = logging.getLogger("analysis.segments")
SEG_M = 402.3          # a quarter mile
ASSIGN_M = 60.0
NEAR_M = 400.0
YEARS = list(range(2016, 2026))
EXCLUDE_CLASSES = {"motorway_link"}  # ramps


def _lines(geom):
    if isinstance(geom, LineString):
        return [geom]
    if isinstance(geom, MultiLineString):
        return list(geom.geoms)
    return [g for g in getattr(geom, "geoms", []) if isinstance(g, LineString)]


def cut(line: LineString) -> list[LineString]:
    n = max(1, int(round(line.length / SEG_M)))
    if n == 1:
        return [line]
    step = line.length / n
    return [substring(line, i * step, (i + 1) * step) for i in range(n)]


def make_segments(edges: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    edges = edges[~edges.highway.isin(EXCLUDE_CLASSES)]
    named = edges[edges.name.notna()]
    rows = []
    for name, g in named.groupby("name"):
        merged = shapely.line_merge(shapely.union_all(g.geometry.values))
        for chain in _lines(merged):
            for piece in cut(chain):
                rows.append((name, piece))
    for geom in edges[edges.name.isna()].geometry:
        for chain in _lines(geom):
            for piece in cut(chain):
                rows.append((None, piece))
    seg = gpd.GeoDataFrame(rows, columns=["name", "geometry"], geometry="geometry", crs=PROJ)
    seg = seg[seg.length > 5].reset_index(drop=True)
    seg["segment_id"] = np.arange(len(seg))
    seg["length_m"] = seg.length
    return seg


def mid(seg):
    return gpd.GeoDataFrame(seg[["segment_id"]], geometry=seg.geometry.interpolate(0.5, normalized=True), crs=PROJ)


def nearest_attrs(points, layer, cols, max_m, prefix=""):
    j = gpd.sjoin_nearest(points, layer[cols + ["geometry"]], max_distance=max_m, how="left", distance_col=f"{prefix}dist_m")
    j = j.sort_values(f"{prefix}dist_m").drop_duplicates("segment_id")
    return j.drop(columns=["geometry", "index_right"], errors="ignore").set_index("segment_id")


def within_counts(points, targets, radius, value=None):
    """count (and optional sum of `value`) of target points within radius of each point; nearest distance too."""
    tree = shapely.STRtree(targets.geometry.values)
    pi, ti = tree.query(points.geometry.values, predicate="dwithin", distance=radius)
    out = pd.DataFrame(index=points.segment_id.values)
    out["n"] = pd.Series(1, index=pi).groupby(level=0).sum().reindex(range(len(points)), fill_value=0).values
    if value is not None:
        out["sum"] = pd.Series(targets[value].fillna(0).values[ti], index=pi).groupby(level=0).sum().reindex(range(len(points)), fill_value=0).values
    nd = gpd.sjoin_nearest(points, targets[["geometry"]], how="left", distance_col="d").drop_duplicates("segment_id").set_index("segment_id")["d"]
    out["dist_m"] = nd.reindex(out.index).values
    return out


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    A = PROCESSED / "analysis"
    edges = gpd.read_parquet(A / "network_edges.parquet")
    nodes = gpd.read_parquet(A / "network_nodes.parquet")
    seg = make_segments(edges)
    log.info("%d segments, %.0f mi (median %.0f m)", len(seg), seg.length_m.sum() / 1609.344, seg.length_m.median())
    m = mid(seg)

    # ---- OSM
    osm = nearest_attrs(m, edges, ["highway", "lanes", "maxspeed_mph", "oneway"], 25, "osm_")
    seg = seg.join(osm.rename(columns={"highway": "osm_class", "lanes": "osm_lanes", "maxspeed_mph": "osm_speed_mph", "oneway": "osm_oneway"})[
        ["osm_class", "osm_lanes", "osm_speed_mph", "osm_oneway"]], on="segment_id")

    # ---- HPMS 2024 (arterials/collectors with AADT)
    h = gpd.read_file(PROCESSED / "hpms" / "hpms_2024_alameda.geojson").to_crs(PROJ)
    h = h[h.f_system.between(3, 6) & (pd.to_numeric(h.aadt, errors="coerce") > 0)].copy()
    h["aadt"] = pd.to_numeric(h.aadt)
    for c in ("through_lanes", "speed_limit"):
        h[c] = pd.to_numeric(h[c], errors="coerce").replace(0, np.nan)
    hp = nearest_attrs(m, h, ["aadt", "through_lanes", "speed_limit", "f_system"], 20, "hpms_")
    seg = seg.join(hp[["aadt", "through_lanes", "speed_limit", "f_system"]].rename(columns={
        "aadt": "hpms_aadt", "through_lanes": "hpms_lanes", "speed_limit": "hpms_speed_mph", "f_system": "hpms_fsystem"}), on="segment_id")

    # ---- intersections along / at the ends of each segment
    inter = nodes[nodes.street_count >= 3]
    tree = shapely.STRtree(inter.geometry.values)
    pi, ti = tree.query(seg.geometry.values, predicate="dwithin", distance=8)
    seg["n_intersections"] = pd.Series(1, index=pi).groupby(level=0).sum().reindex(range(len(seg)), fill_value=0).values
    ends = pd.concat([gpd.GeoDataFrame({"segment_id": seg.segment_id, "geometry": seg.geometry.apply(lambda g: shapely.Point(g.coords[0]))}, crs=PROJ),
                      gpd.GeoDataFrame({"segment_id": seg.segment_id, "geometry": seg.geometry.apply(lambda g: shapely.Point(g.coords[-1]))}, crs=PROJ)])
    ej = gpd.sjoin_nearest(ends, nodes[["n_signals", "n_stop_signs", "geometry"]], max_distance=15, how="left")
    ej = ej.groupby("segment_id")[["n_signals", "n_stop_signs"]].sum()
    seg = seg.join(ej.rename(columns={"n_signals": "end_signals", "n_stop_signs": "end_stop_signs"}), on="segment_id")

    # ---- destinations
    sch = gpd.read_file(PROCESSED / "schools" / "cde_school_sites_2425.geojson").to_crs(PROJ)
    sch = sch[(sch.Status == "Active") & (sch.Virtual != "V")]
    sc = within_counts(m, sch, NEAR_M, "EnrollTotal")
    seg["schools_400m"], seg["school_enroll_400m"], seg["school_dist_m"] = sc["n"].values, sc["sum"].values, sc["dist_m"].values
    hc = pd.read_parquet(PROCESSED / "health" / "hcai_facilities_alameda.parquet")
    hc = hc[hc.FAC_STATUS_TYPE_CODE == "OPEN"]
    hg = gpd.GeoDataFrame(hc, geometry=gpd.points_from_xy(pd.to_numeric(hc.LONGITUDE), pd.to_numeric(hc.LATITUDE)), crs=4326).to_crs(PROJ)
    seg["hospital_dist_m"] = within_counts(m, hg[hg.FAC_FDR == "GENERAL ACUTE CARE HOSPITAL"], NEAR_M)["dist_m"].values
    snf = within_counts(m, hg[hg.FAC_FDR == "SKILLED NURSING FACILITY"], NEAR_M)
    seg["snf_400m"], seg["snf_dist_m"] = snf["n"].values, snf["dist_m"].values
    pois = gpd.read_file(PROCESSED / "osm" / "pois.geojson").to_crs(PROJ)
    bus = pois[pois.get("highway") == "bus_stop"]
    seg["bus_stops_400m"] = within_counts(m, bus, NEAR_M)["n"].values

    # ---- tract-level equity and density
    tr = gpd.read_file(PROCESSED / "census" / "tiger_acs2024_tracts.geojson").to_crs(PROJ)[["GEOID", "AREALAND", "geometry"]]
    tj = gpd.sjoin(m, tr, how="left", predicate="within").drop_duplicates("segment_id").set_index("segment_id")
    seg["tract"] = tj["GEOID"].reindex(seg.segment_id).values
    epc = pd.read_parquet(PROCESSED / "equity" / "epc_pba2050plus_acs2022_alameda.parquet")
    epc["epc"] = pd.to_numeric(epc["epc_2050p"], errors="coerce").fillna(0).astype(int) == 1
    seg = seg.merge(epc[["tract_geoid", "epc"]].rename(columns={"tract_geoid": "tract"}), on="tract", how="left")
    ces = pd.read_parquet(PROCESSED / "equity" / "calenviroscreen5_alameda.parquet")
    ces["tract"] = ces["tract"].astype(str).str.zfill(11)
    seg = seg.merge(ces[["tract", "CIscoreP"]].rename(columns={"CIscoreP": "ces_pctl"}).assign(ces_pctl=lambda d: pd.to_numeric(d.ces_pctl, errors="coerce")), on="tract", how="left")
    pop = pd.read_parquet(PROCESSED / "census" / "acs2024_5yr_B01001.parquet")
    pop = pop[pop.geo_level == "tract"].assign(tract=lambda d: d.GEOID.str[-11:] if "GEOID" in d else d.GEO_ID.str[-11:])
    pop = pop.assign(pop=pd.to_numeric(pop["B01001_001E"], errors="coerce"))[["tract", "pop"]]
    area = tr.assign(area_km2=pd.to_numeric(tr.AREALAND) / 1e6).rename(columns={"GEOID": "tract"})[["tract", "area_km2"]]
    seg = seg.merge(pop.merge(area, on="tract").assign(pop_density_km2=lambda d: d["pop"] / d.area_km2)[["tract", "pop_density_km2"]], on="tract", how="left")

    # ---- Oakland bikeways (completed projects)
    bp = gpd.read_file(PROCESSED / "oakland" / "bikeway_projects.geojson").to_crs(PROJ)
    bp = bp[bp.status == "Completed"].copy()
    bp["yeardone"] = pd.to_numeric(bp.yeardone, errors="coerce")
    bp = bp[bp.yeardone > 1990]
    bbuf = bp.assign(geometry=bp.geometry.buffer(12))
    sidx = shapely.STRtree(bbuf.geometry.values)
    si, bi = sidx.query(seg.geometry.values, predicate="intersects")
    cover = []
    for s, b in zip(si, bi):
        g = seg.geometry.values[s]
        cover.append((s, b, g.intersection(bbuf.geometry.values[b]).length / g.length))
    cv = pd.DataFrame(cover, columns=["s", "b", "cover"])
    cv = cv[cv.cover >= 0.5]
    cv["year"], cv["type"] = bp.yeardone.values[cv.b], bp.bikeway_ty.values[cv.b]
    agg = cv.groupby("s").agg(bike_projects=("b", "size"), bike_first_year=("year", "min"), bike_last_year=("year", "max"),
                              bike_types=("type", lambda x: ",".join(sorted(set(map(str, x))))))
    seg = seg.merge(agg, left_on="segment_id", right_index=True, how="left")
    seg["bike_projects"] = seg["bike_projects"].fillna(0).astype(int)

    # ---- place (city or unincorporated)
    pl = pd.concat([gpd.read_file(PROCESSED / "census" / f"tiger_acs2024_places_{k}.geojson") for k in ("incorporated", "cdp")]).to_crs(PROJ)
    pj = gpd.sjoin(m, pl[["BASENAME", "LSADC", "geometry"]], how="left", predicate="within").drop_duplicates("segment_id").set_index("segment_id")
    seg["place"] = pj["BASENAME"].reindex(seg.segment_id).values
    seg["incorporated"] = (pj["LSADC"].reindex(seg.segment_id).values == "25")

    # ---- crashes -> segments
    cr = pd.read_parquet(A / "crashes.parquet")
    cr = cr[~cr.freeway & cr.lat.notna()]
    cp = gpd.GeoDataFrame(cr[["tims_case_id", "year", "ksi", "fatal", "ped", "bike"]], geometry=gpd.points_from_xy(cr.lon, cr.lat), crs=4326).to_crs(PROJ)
    cs = gpd.sjoin_nearest(cp, seg[["segment_id", "geometry"]], max_distance=ASSIGN_M, how="left", distance_col="assign_m")
    cs = cs.sort_values("assign_m").drop_duplicates("tims_case_id")
    log.info("crashes assigned to a segment: %.3f (median %.1f m)", cs.segment_id.notna().mean(), cs.assign_m.median())
    cs = cs[cs.segment_id.notna()].assign(segment_id=lambda d: d.segment_id.astype(int))
    cs[["tims_case_id", "segment_id", "assign_m"]].to_parquet(A / "crash_segment.parquet", index=False)

    cs["n_inj"] = 1
    for k, f in (("ksi", cs.ksi), ("fatal", cs.fatal), ("ped_inj", cs.ped), ("bike_inj", cs.bike),
                 ("ped_ksi", cs.ped & cs.ksi), ("bike_ksi", cs.bike & cs.ksi)):
        cs[f"n_{k}"] = f.astype(int)
    cols = ["n_inj", "n_ksi", "n_fatal", "n_ped_inj", "n_bike_inj", "n_ped_ksi", "n_bike_ksi"]
    panel = cs.groupby(["segment_id", "year"])[cols].sum()
    full = pd.MultiIndex.from_product([seg.segment_id, YEARS], names=["segment_id", "year"])
    panel = panel.reindex(full, fill_value=0).reset_index()
    panel.to_parquet(A / "segment_year.parquet", index=False)
    tot = panel.groupby("segment_id")[cols].sum().add_suffix("_total")
    seg = seg.merge(tot, left_on="segment_id", right_index=True, how="left")
    seg.to_parquet(A / "segments.parquet")
    for n in ("segments", "segment_year", "crash_segment"):
        log_pull("analysis", n, out_path=A / f"{n}.parquet", note="built by analysis/segments.py")

    # ---- report
    L = seg.length_m
    print(f"\n{len(seg):,} segments, {L.sum() / 1609.344:,.0f} mi; length median {L.median():.0f} m, 10-90% {L.quantile(.1):.0f}-{L.quantile(.9):.0f} m")
    cov = {c: round(float(seg[c].notna().mean()), 3) for c in ["osm_lanes", "osm_speed_mph", "hpms_aadt", "hpms_lanes", "hpms_speed_mph", "tract", "epc", "ces_pctl", "pop_density_km2", "place"]}
    print("attribute coverage:", cov)
    print("with AADT, by OSM class:", seg.groupby("osm_class").hpms_aadt.apply(lambda s: round(s.notna().mean(), 2)).to_dict())
    print(f"surface injury crashes {int(seg.n_inj_total.sum()):,}; KSI {int(seg.n_ksi_total.sum()):,}; ped KSI {int(seg.n_ped_ksi_total.sum())}; bike KSI {int(seg.n_bike_ksi_total.sum())}")
    print(f"segments with >=1 KSI: {(seg.n_ksi_total > 0).mean():.3f}; >=1 injury crash: {(seg.n_inj_total > 0).mean():.3f}; "
          f"mean KSI/segment {seg.n_ksi_total.mean():.2f}, max {int(seg.n_ksi_total.max())}")
    print(f"KSI on segments with HPMS AADT: {seg.loc[seg.hpms_aadt.notna(), 'n_ksi_total'].sum() / seg.n_ksi_total.sum():.3f} "
          f"(on {seg.hpms_aadt.notna().mean():.3f} of segments, {seg.loc[seg.hpms_aadt.notna(), 'length_m'].sum() / L.sum():.3f} of length)")
    print("bike projects matched:", int((seg.bike_projects > 0).sum()), "segments;", "schools within 400 m:", f"{(seg.schools_400m > 0).mean():.3f}")


if __name__ == "__main__":
    main()
