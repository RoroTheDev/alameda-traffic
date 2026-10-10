"""Compare TIMS (SafeTREC) coordinates with CCRS and with our street-name geocoder.

    python -m audit.compare_tims            # after: python download.py tims

TIMS crash rows carry two coordinate pairs:
    LATITUDE / LONGITUDE   officer-reported, passed through from the CHP record
    POINT_X / POINT_Y      SafeTREC's own geocode (WGS84; lon = X, lat = Y)

Linking CCRS crashes to TIMS rows (found by testing on real files, 2026-10-09):
  tier 1  CHP reports: TIMS CASE_ID = "9" (or "8") + 7-digit zero-padded CCRS Collision Id.
          Matches 99% of CHP injury crashes, with identical dates.
  tier 2  City/campus PD reports use a different CASE_ID, so link on
          (agency code, date, HHMM, first 8 letters of primary road), accepted only when the
          key is unique on both sides. Tier 2 is self-checked on the tier-1 crashes, where
          the right answer is known.
TIMS comes from the same CHP records as CCRS, so agreement is not independent proof of
location accuracy; it shows what changed between systems and how SafeTREC's geocode behaves.
"""
from __future__ import annotations

import logging

import geopandas as gpd
import numpy as np
import pandas as pd

from alameda_traffic.config import PROCESSED
from alameda_traffic.geocode import PROJ, project
from audit.coordinates import RESULTS, classify_coords, load_crashes

log = logging.getLogger("audit.compare_tims")
KEY2 = ["juris", "date", "hhmm", "road"]


def _road(s: pd.Series) -> pd.Series:
    return s.fillna("").astype(str).str.upper().str.replace(r"[^A-Z0-9]", "", regex=True).str[:8]


def load_tims() -> pd.DataFrame:
    frames = []
    for f in sorted((PROCESSED / "tims").glob("*.parquet")):
        d = pd.read_parquet(f)
        d.columns = [c.strip().upper() for c in d.columns]
        if {"CASE_ID", "POINT_X", "POINT_Y"} <= set(d.columns):
            frames.append(d)
        else:
            log.info("skipping %s (no CASE_ID/POINT_X/POINT_Y: Parties/Victims)", f.name)
    if not frames:
        raise SystemExit("No TIMS crash file in data/processed/tims — run download.py tims first.")
    t = pd.concat(frames, ignore_index=True)
    for col in ("POINT_X", "POINT_Y", "LATITUDE", "LONGITUDE"):
        t[col] = pd.to_numeric(t[col], errors="coerce")
    t["CASE_ID"] = t["CASE_ID"].astype(str)
    t["date"] = pd.to_datetime(t["COLLISION_DATE"]).dt.strftime("%Y-%m-%d")
    t["hhmm"] = t["COLLISION_TIME"].astype(str).str.zfill(4)
    t["juris"] = t["JURIS"].astype(str).str.zfill(4)
    t["road"] = _road(t["PRIMARY_RD"])
    return t


def link(c: pd.DataFrame, t: pd.DataFrame) -> pd.DataFrame:
    dt = pd.to_datetime(c["Crash Date Time"], format="mixed")
    c["date"], c["hhmm"] = dt.dt.strftime("%Y-%m-%d"), dt.dt.strftime("%H%M")
    c["juris"] = c["NCIC Code"].astype(str).str.zfill(4)
    c["road"] = _road(c["PrimaryRoad"])
    cid = c["Collision Id"].astype(str).str.zfill(7)
    by_case = pd.Series(t.index.values, index=t["CASE_ID"])
    row1 = ("9" + cid).map(by_case).fillna(("8" + cid).map(by_case))
    # tier 2 on every CCRS row (used for self-check) and on rows tier 1 missed
    tk = t.groupby(KEY2).filter(lambda g: len(g) == 1).set_index(KEY2).index
    t_unique = pd.Series(t.index.values, index=t.set_index(KEY2).index)[t.set_index(KEY2).index.isin(tk)]
    ck = c.groupby(KEY2)["Collision Id"].transform("size") == 1
    keys = pd.MultiIndex.from_frame(c[KEY2])
    row2 = pd.Series(keys.map(lambda k: t_unique.get(k, np.nan)), index=c.index).where(ck)
    c["tims_row"] = row1.fillna(row2)
    c["link_tier"] = np.where(row1.notna(), "id", np.where(row2.notna(), "composite", None))
    # self-check: where tier 1 is known, does tier 2 pick the same TIMS row?
    both = row1.notna() & row2.notna()
    agree = (row1[both] == row2[both]).mean()
    avail = row2[row1.notna()].notna().mean()
    log.info("tier-2 self-check on %d tier-1 crashes: key available for %.3f, picks the same row %.3f",
             int(row1.notna().sum()), avail, agree)
    c.attrs["tier2_agree"], c.attrs["tier2_avail"] = float(agree), float(avail)
    return c


def meters(lat1, lon1, lat2, lon2) -> np.ndarray:
    a, b = project(lat1, lon1), project(lat2, lon2)
    return np.hypot(a.x.values - b.x.values, a.y.values - b.y.values)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    t = load_tims()
    county = gpd.read_file(PROCESSED / "census" / "tiger_acs2024_county.geojson").to_crs(PROJ).geometry.iloc[0]
    c = classify_coords(load_crashes(), county)
    ours = pd.read_parquet(PROCESSED / "audit" / "ccrs_crash_coordinates.parquet")
    c = c.merge(ours[["Collision Id", "final_lat", "final_lon", "final_source"]], on="Collision Id", how="left")
    c = link(c, t)
    inj = c[c.injury].copy()

    # A. link rates
    a = inj.groupby("agency").apply(lambda g: pd.Series({
        "ccrs_injury": len(g), "linked": g.tims_row.notna().mean(),
        "via_id": (g.link_tier == "id").mean(), "via_composite": (g.link_tier == "composite").mean()}), include_groups=False)
    a.round(3).to_csv(RESULTS / "tims_link_by_agency.csv")
    used = set(inj.tims_row.dropna().astype(int))
    print("A. CCRS injury crashes found in TIMS")
    print(a.round(3).to_string())
    print(f"   tier-2 self-check on CHP crashes: key available {c.attrs['tier2_avail']:.3f}, "
          f"picks the same TIMS row {c.attrs['tier2_agree']:.3f}")
    print(f"   TIMS crashes with no CCRS injury match: {len(t) - len(used)} of {len(t)}")

    m = inj[inj.tims_row.notna()].copy()
    tm = t.loc[m.tims_row.astype(int)].reset_index(drop=True)
    m = m.reset_index(drop=True)
    m["t_lat"], m["t_lon"] = tm["LATITUDE"].values, tm["LONGITUDE"].values
    m["p_lat"], m["p_lon"] = tm["POINT_Y"].values, tm["POINT_X"].values

    # B. what each system has (coverage), by agency
    cov = m.groupby("agency").apply(lambda g: pd.Series({
        "linked": len(g), "ccrs_valid": (g.coord_state == "valid").mean(),
        "tims_officer_latlon": g.t_lat.notna().mean(), "tims_point_xy": g.p_lat.notna().mean()}), include_groups=False)
    cov.round(3).to_csv(RESULTS / "tims_coverage_by_agency.csv")
    print("\nB. coordinate coverage among linked crashes:")
    print(cov.round(3).to_string())
    o = m[(m.coord_state == "valid") & m.t_lat.notna()]
    d = meters(o.lat, o.lon, o.t_lat, o.t_lon)
    print(f"   CCRS vs TIMS officer coordinates, {len(o)} crashes with both: identical within 1 m {np.mean(d < 1):.3f}, "
          f"within 25 m {np.mean(d < 25):.3f}, median {np.median(d):.2f} m")

    # C. SafeTREC geocode quality
    def dist_table(sub, a_lat, a_lon, label):
        dd = meters(sub[a_lat], sub[a_lon], sub.p_lat, sub.p_lon)
        return pd.Series({"n": len(sub), "median_m": np.median(dd), "p90_m": np.quantile(dd, .9),
                          "within_50m": np.mean(dd <= 50), "within_100m": np.mean(dd <= 100), "within_250m": np.mean(dd <= 250)}, name=label)
    ok = m[m.p_lat.notna()]
    rows = []
    v = ok[ok.coord_state == "valid"]
    rows.append(dist_table(v, "lat", "lon", "TIMS POINT vs CCRS officer coords (all agencies)"))
    for ag, g in v.groupby("agency"):
        rows.append(dist_table(g, "lat", "lon", f"  TIMS POINT vs officer coords: {ag}"))
    g = ok[(ok.final_source == "geocoded_street_names")]
    rows.append(dist_table(g, "final_lat", "final_lon", "OUR street-name geocode vs TIMS POINT (crashes with no officer coords)"))
    for nc, gg in g.groupby("NCIC Code"):
        if len(gg) >= 500:
            rows.append(dist_table(gg, "final_lat", "final_lon", f"  ours vs TIMS POINT: NCIC {nc}"))
    ct = pd.DataFrame(rows)
    ct.round(3).to_csv(RESULTS / "tims_geocode_comparison.csv")
    print("\nC. distances to TIMS POINT_X/Y (SafeTREC geocode):")
    print(ct.round(3).to_string())

    # D. do TIMS points fix the records CCRS has wrong?
    bad = m[m.coord_state == "outside_county"].copy()
    inside = project(bad.p_lat.fillna(0), bad.p_lon.fillna(0)).within(county).values
    bad["tims_in_county"] = inside & bad.p_lat.notna().values
    dx = bad.groupby(["NCIC Code"]).agg(n=("tims_in_county", "size"), tims_point_in_county=("tims_in_county", "mean"))
    dx = dx[dx.n >= 50].sort_values("n", ascending=False)
    dx.round(3).to_csv(RESULTS / "tims_fixes_outside_county.csv")
    print("\nD. CCRS coordinates outside the county: is the TIMS POINT inside it?")
    print(dx.round(3).to_string())


if __name__ == "__main__":
    main()
