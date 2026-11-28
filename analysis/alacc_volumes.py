"""AlaCC travel-model link volumes (2020 base year) -> daily volume per road segment, plus a separate freeway layer.

    python -m analysis.alacc_volumes

Input   data/restricted/alacc_2020/AlaCC_2020_Volumes/avgload{EA,AM,MD,PM,EV}.shp   (Fehr & Peers for Alameda CTC; restricted)
Output  data/restricted/analysis/segment_alacc.parquet        one row per surface segment (restricted: model-derived)
        data/restricted/analysis/alacc_freeway_links.parquet  freeway + ramp links with daily volume (restricted)
        analysis/results/alacc_match_summary.csv              counts and agreement statistics only (public)
Cite as "the AlaCC Model". The model data must never be committed or published; only summaries are.

Facts checked on the files themselves (2026-11-26):
  * Coordinates are NAD83 California zone 6, US feet (EPSG:2230). The cover email said zone III, which puts the links in
    the Pacific; zone 6 lands the Alameda links on our OpenStreetMap segments (median offset 0.3 m).
  * Facility type FT, read from link names, OSM class (ROADWAY), lanes and free-flow speed:
      1 freeway | 2 expressway | 3 ramp | 4-6 arterial/collector | 7 local | 8 zone/managed-lane connector (not real) | 99 service
  * Two-way streets are two links (one per direction, A->B and B->A); one-way streets are one link.
  * The five periods (EA 3-6, AM 6-10, MD 10-15, PM 15-19, EV 19-3) do not overlap and sum to a day.
  * Local streets (FT 7) carry a median model volume of 0: the model routes trips between zone centroids, so local-street
    volumes are not meaningful. They are flagged, not trusted.

Layers (the user's design): every link gets a layer, surface (FT 2, 4-7) or freeway (FT 1, 3). Surface links are matched only
to our surface segments; freeway links are kept as separate objects. FT 8 and 99 are dropped (not real roads / not in our map).

Matching, surface links -> segments:
  1. candidates: segments within MATCH_M of the link midpoint whose direction at that point is within ANGLE_DEG of the link's
     (either way round, so both directions of a two-way street match the same segment; cross streets do not)
  2. the nearest candidate wins, unless a second candidate is within TIE_M of it: then a name match decides; if names cannot
     decide, the link is "uncertain"
  3. segment daily volume = for each travel direction, the length-weighted mean daily volume of its confident links; the two
     directions are added (no double counting: each vehicle is on one direction's link only)
  Status per segment: ok | uncertain (some links uncertain, none confident) | local_unreliable (FT 7 only) | none.
"""
from __future__ import annotations

import logging
import re
import warnings

import geopandas as gpd
import numpy as np
import pandas as pd

from alameda_traffic.config import PROCESSED, REPO_ROOT, RESTRICTED

log = logging.getLogger("analysis.alacc_volumes")
SRC = RESTRICTED / "alacc_2020" / "AlaCC_2020_Volumes"
OUT = RESTRICTED / "analysis"
RESULTS = REPO_ROOT / "analysis" / "results"
CRS_SRC, CRS_M = 2230, 26910
PERIODS = ("EA", "AM", "MD", "PM", "EV")
SURFACE_FT, FREEWAY_FT = {2, 4, 5, 6, 7}, {1, 3}
MATCH_M, ANGLE_DEG, TIE_M = 15.0, 30.0, 3.0
ABBR = {"BOULEVARD": "BLVD", "AVENUE": "AVE", "STREET": "ST", "ROAD": "RD", "DRIVE": "DR", "PARKWAY": "PKWY", "WAY": "WAY",
        "LANE": "LN", "COURT": "CT", "PLACE": "PL", "HIGHWAY": "HWY", "EXPRESSWAY": "EXPY", "TERRACE": "TER", "CIRCLE": "CIR",
        "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W", "JUNIOR": "JR", "SAINT": "ST"}


def norm(name) -> str:
    if name is None or (isinstance(name, float) and np.isnan(name)):
        return ""
    words = re.sub(r"[^A-Z0-9 ]", " ", str(name).upper()).split()
    return " ".join(ABBR.get(w, w) for w in words)


def load_links() -> gpd.GeoDataFrame:
    """one row per directed link (A,B) with daily volumes summed over the five periods."""
    base, vols = None, []
    for p in PERIODS:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            g = gpd.read_file(SRC / f"avgload{p}.shp", columns=["A", "B", "FT", "NAME", "COUNTY", "CNTYPE", "LANES", "FFS", "VOL", "VOLT", "VOL_HV"])
        g = g.set_crs(CRS_SRC, allow_override=True)
        if base is None:
            base = g[["A", "B", "FT", "NAME", "COUNTY", "CNTYPE", "LANES", "FFS", "geometry"]].copy()
        vols.append(g[["A", "B", "VOL", "VOLT", "VOL_HV"]].rename(columns={"VOL": f"vol_{p}", "VOLT": f"volt_{p}", "VOL_HV": f"hv_{p}"}))
    for v in vols:
        if v.duplicated(["A", "B"]).any():
            raise SystemExit("duplicate (A,B) links: cannot join periods safely")
        base = base.merge(v, on=["A", "B"], how="left", validate="one_to_one")
    base["vol_day"] = base[[f"vol_{p}" for p in PERIODS]].sum(axis=1)
    base["volt_day"] = base[[f"volt_{p}" for p in PERIODS]].sum(axis=1)
    base["hv_day"] = base[[f"hv_{p}" for p in PERIODS]].sum(axis=1)
    base["layer"] = np.where(base.FT.isin(SURFACE_FT), "surface", np.where(base.FT.isin(FREEWAY_FT), "freeway", "drop"))
    return base


def bearing(line, at=None) -> float:
    """direction in degrees [0,180) of a line, or of its piece around distance `at` (metres along it)."""
    if at is None:
        a, b = line.coords[0], line.coords[-1]
    else:
        L = line.length
        a, b = line.interpolate(max(0, at - 5)).coords[0], line.interpolate(min(L, at + 5)).coords[0]
    return float(np.degrees(np.arctan2(b[1] - a[1], b[0] - a[0])) % 180)


def match(links: gpd.GeoDataFrame, seg: gpd.GeoDataFrame) -> pd.DataFrame:
    mid = links.geometry.interpolate(0.5, normalized=True)
    pts = gpd.GeoDataFrame({"li": links.index.values}, geometry=mid.values, crs=CRS_M)
    cand = gpd.sjoin(pts, seg[["segment_id", "seg_name", "geometry"]].assign(geometry=seg.geometry.buffer(MATCH_M)), predicate="within")
    cand = cand.drop(columns="index_right")
    sg = seg.set_index("segment_id").geometry
    lg = links.geometry
    cand["dist"] = [sg[s].distance(p) for s, p in zip(cand.segment_id, cand.geometry)]
    lb = np.array([bearing(lg[i]) for i in cand.li])
    sb = np.array([bearing(sg[s], sg[s].project(p)) for s, p in zip(cand.segment_id, cand.geometry)])
    d = np.abs(lb - sb)
    cand["angle"] = np.minimum(d, 180 - d)
    cand = cand[cand.angle <= ANGLE_DEG].copy()
    cand["link_name"] = links.loc[cand.li, "name_n"].values
    cand["name_match"] = (cand.link_name != "") & (cand.link_name == cand.seg_name)
    cand = cand.sort_values(["li", "dist"])
    out = []
    for li, g in cand.groupby("li", sort=False):
        best = g.iloc[0]
        close = g[g.dist <= best.dist + TIE_M]
        if close.segment_id.nunique() == 1:
            out.append((li, best.segment_id, "ok", best.dist, best.name_match))
            continue
        nm = close[close.name_match]
        if nm.segment_id.nunique() == 1:
            out.append((li, nm.iloc[0].segment_id, "ok_by_name", nm.iloc[0].dist, True))
        else:
            out.append((li, best.segment_id, "uncertain", best.dist, bool(best.name_match)))
    return pd.DataFrame(out, columns=["li", "segment_id", "link_status", "dist", "name_match"])


def aggregate(links: gpd.GeoDataFrame, m: pd.DataFrame, seg: gpd.GeoDataFrame, field: str, use_uncertain: bool) -> pd.Series:
    """two-way daily volume per segment: per direction, length-weighted mean over links; directions added."""
    j = m.merge(links[["FT", "len_m", "dir_sign", field]], left_on="li", right_index=True)
    j = j[(j.FT != 7)]
    if not use_uncertain:
        j = j[j.link_status != "uncertain"]
    j["w"] = j.len_m * j[field]
    per_dir = j.groupby(["segment_id", "dir_sign"]).agg(w=("w", "sum"), L=("len_m", "sum"))
    per_dir["v"] = per_dir.w / per_dir.L
    return per_dir.v.groupby(level=0).sum()


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    seg = gpd.read_parquet(PROCESSED / "analysis" / "segments.parquet").to_crs(CRS_M)
    seg["seg_name"] = seg.name.map(norm)
    links = load_links()
    log.info("links (all Bay Area) %d; layers %s", len(links), links.layer.value_counts().to_dict())
    links = links.to_crs(CRS_M)
    box = seg.total_bounds
    links = links.cx[box[0] - 500:box[2] + 500, box[1] - 500:box[3] + 500].copy()
    links["name_n"] = links.NAME.map(norm)
    links["len_m"] = links.length

    fw = links[links.layer == "freeway"]
    OUT.mkdir(parents=True, exist_ok=True)
    fw[["A", "B", "FT", "NAME", "COUNTY", "LANES", "vol_day", "volt_day", "hv_day", "geometry"]].to_parquet(OUT / "alacc_freeway_links.parquet")
    log.info("freeway layer: %d links (FT 1 freeway %d, FT 3 ramp %d) saved separately", len(fw), int((fw.FT == 1).sum()), int((fw.FT == 3).sum()))

    sl = links[links.layer == "surface"].copy()
    m = match(sl, seg)
    log.info("surface links in area %d; matched %d; status %s", len(sl), len(m), m.link_status.value_counts().to_dict())
    # direction of each matched link relative to its segment's digitised direction: +1 same way, -1 opposite
    sg = seg.set_index("segment_id").geometry
    sgn = []
    for li, s in zip(m.li, m.segment_id):
        lgeom, sgeom = sl.geometry[li], sg[s]
        a, b = sgeom.project(lgeom.interpolate(0)), sgeom.project(lgeom.interpolate(lgeom.length))
        sgn.append(1 if b >= a else -1)
    sl["dir_sign"] = 0
    sl.loc[m.li.values, "dir_sign"] = sgn
    m = m.drop_duplicates("li")

    res = seg[["segment_id", "osm_class", "hpms_aadt", "length_m"]].copy().set_index("segment_id")
    for field in ("vol_day", "volt_day", "hv_day"):
        res[f"alacc_{field}"] = aggregate(sl, m, seg, field, use_uncertain=False)
        res[f"alacc_{field}_incl_uncertain"] = aggregate(sl, m, seg, field, use_uncertain=True)
    st = m.merge(sl[["FT"]], left_on="li", right_index=True).groupby("segment_id").agg(
        n_links=("li", "size"), n_uncertain=("link_status", lambda s: int((s == "uncertain").sum())),
        only_local=("FT", lambda s: bool((s == 7).all())), name_share=("name_match", "mean"), med_dist=("dist", "median"))
    res = res.join(st)
    res["alacc_status"] = np.select(
        [res.alacc_vol_day.notna(), res.alacc_vol_day_incl_uncertain.notna(), res.only_local.fillna(False).astype(bool)],
        ["ok", "uncertain", "local_unreliable"], "none")
    res = res.reset_index()
    res.to_parquet(OUT / "segment_alacc.parquet", index=False)

    # validation against measured traffic (HPMS AADT) where both exist; which volume field is total daily vehicles?
    rows = []
    both = res[(res.alacc_status == "ok") & res.hpms_aadt.notna() & (res.hpms_aadt > 0)]
    for field in ("alacc_vol_day", "alacc_volt_day"):
        b = both[both[field] > 0]
        lr = np.log(b[field] / b.hpms_aadt)
        rows.append(dict(item=f"{field} vs HPMS AADT", n=len(b), log_corr=round(float(np.corrcoef(np.log(b[field]), np.log(b.hpms_aadt))[0, 1]), 3),
                         median_ratio_model_over_aadt=round(float(np.exp(lr.median())), 3), share_within_factor_2=round(float((lr.abs() < np.log(2)).mean()), 3)))
    for s, n in res.alacc_status.value_counts().items():
        rows.append(dict(item=f"segments status {s}", n=int(n)))
    for c, g in res.groupby("osm_class"):
        rows.append(dict(item=f"class {c}: share of segments with a volume (ok)", n=len(g), share=round(float((g.alacc_status == "ok").mean()), 3)))
    rows.append(dict(item="matched links: median distance link midpoint to segment (m)", n=len(m), value=round(float(m.dist.median()), 2)))
    rows.append(dict(item="matched links: share with name agreement (both named)", n=int(((sl.loc[m.li, 'name_n'] != '').values).sum()),
                     value=round(float(m.name_match[(sl.loc[m.li, 'name_n'] != '').values].mean()), 3)))
    summ = pd.DataFrame(rows)
    summ.to_csv(RESULTS / "alacc_match_summary.csv", index=False)
    pd.set_option("display.width", 200, "display.max_rows", 100)
    print(summ.to_string(index=False))


if __name__ == "__main__":
    main()
