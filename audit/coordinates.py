"""Coordinate audit of CCRS crashes (2016-2025, Alameda County).

    python -m audit.coordinates

Questions answered, with tables written to audit/results/:
  1. Who records usable coordinates?  (by reporting agency, year, injury, severity)
  2. How are the unusable ones broken?  (missing / present but outside the county)
  3. Can street names recover them?  (geocode PrimaryRoad x SecondaryRoad against the
     county centerlines; error measured against officer coordinates where we have them)

The reporting agency comes from NCIC Code: 93xx = CHP office, 01xx = city/campus police.
Officer coordinates are treated as a *proxy* for truth, not truth: they come from the
same reporting chain we are auditing. See docs/COORDINATE_AUDIT.md for the caveats.
"""
from __future__ import annotations

import glob
import logging

import geopandas as gpd
import numpy as np
import pandas as pd

from alameda_traffic.config import PROCESSED, REPO_ROOT, out_dir
from alameda_traffic.geocode import PROJ, Geocoder, project, unproject
from alameda_traffic.provenance import log_pull

log = logging.getLogger("audit.coordinates")
RESULTS = REPO_ROOT / "audit" / "results"
YEARS = range(2016, 2026)  # 2026 is partial
# Offsets (SecondaryDistance/Direction) are NOT applied: against officer coordinates they were
# worse than the bare intersection (see audit/checks.py), so the final point is the intersection.
USE_OFFSET = False


def load_crashes() -> pd.DataFrame:
    files = sorted(glob.glob(str(PROCESSED / "ccrs" / "crashes_20*.parquet")))
    df = pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)
    df["year"] = pd.to_datetime(df["Crash Date Time"], format="mixed").dt.year
    df = df[df["year"].isin(YEARS)].copy()
    df["lat"] = pd.to_numeric(df["Latitude"], errors="coerce")
    df["lon"] = pd.to_numeric(df["Longitude"], errors="coerce")
    ncic = df["NCIC Code"].fillna("")
    df["agency"] = np.where(ncic.str.startswith("93"), "CHP", np.where(ncic.str.startswith("01"), "City/campus PD", "other"))
    killed = df["NumberKilled"].fillna("0").astype(str).str.strip() != "0"
    df["injury"] = (pd.to_numeric(df["NumberInjured"], errors="coerce").fillna(0) > 0) | killed
    return df


def classify_coords(df: pd.DataFrame, county) -> pd.DataFrame:
    present = df["lat"].notna() & df["lon"].notna() & (df["lat"] != 0) & (df["lon"] != 0)
    pts = project(df["lat"].where(present, 0), df["lon"].where(present, 0))
    inside = pd.Series(pts.within(county).values, index=df.index) & present
    df["coord_state"] = np.select([~present, inside], ["missing", "valid"], default="outside_county")
    df["x"] = np.where(inside, pts.x.values, np.nan)
    df["y"] = np.where(inside, pts.y.values, np.nan)
    return df


def completeness_tables(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    def share(g):
        n = len(g)
        return pd.Series({"crashes": n, "valid": (g.coord_state == "valid").mean(),
                          "missing": (g.coord_state == "missing").mean(),
                          "outside_county": (g.coord_state == "outside_county").mean()})
    inj = df[df.injury]
    t = {}
    t["by_agency"] = inj.groupby("agency").apply(share, include_groups=False)
    ncic = inj.groupby("NCIC Code").apply(share, include_groups=False)
    ncic["main_city"] = inj.groupby("NCIC Code")["City Name"].agg(lambda s: s.value_counts().index[0])
    t["by_ncic"] = ncic.sort_values("crashes", ascending=False)
    t["by_year"] = inj.groupby("year").apply(share, include_groups=False)
    t["by_ncic_year_valid"] = (inj.assign(v=inj.coord_state == "valid")
                               .pivot_table(index="NCIC Code", columns="year", values="v", aggfunc="mean")
                               .loc[ncic.index[:15]])
    t["by_city_name"] = inj.groupby("City Name").apply(share, include_groups=False).sort_values("crashes", ascending=False)
    return t


def run_geocoder(df: pd.DataFrame, gc: Geocoder) -> pd.DataFrame:
    cand = df[(df["IsFreeway"].fillna("False") != "True")].copy()
    log.info("geocoding %d surface-street crashes", len(cand))
    rows = []
    for rec in cand[["Collision Id", "PrimaryRoad", "SecondaryRoad", "City Name",
                     "SecondaryDistance", "SecondaryDirection", "SecondaryUnitOfMeasure"]].itertuples(index=False):
        r = (gc.geocode(rec[1], rec[2], rec[3], rec[4], rec[5], rec[6]) if USE_OFFSET
             else gc.geocode(rec[1], rec[2], rec[3]))
        rows.append((rec[0], r.status, r.method, r.n_places, r.x, r.y))
    g = pd.DataFrame(rows, columns=["Collision Id", "geo_status", "geo_method", "geo_places", "geo_x", "geo_y"])
    return df.merge(g, on="Collision Id", how="left")


def validation(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Compare geocoded points with trusted officer coordinates (city PD, valid, surface)."""
    v = df[(df.coord_state == "valid") & df.geo_x.notna() & (df.agency == "City/campus PD")].copy()
    # Fremont PD 2016-2018 coordinates were systematically wrong (San Diego County), already
    # excluded by coord_state; nothing else to drop.
    v["err_m"] = np.hypot(v.geo_x - v.x, v.geo_y - v.y)
    def summ(g):
        e = g["err_m"]
        return pd.Series({"n": len(g), "median_m": e.median(), "p75_m": e.quantile(.75), "p90_m": e.quantile(.9),
                          "within_50m": (e <= 50).mean(), "within_100m": (e <= 100).mean(), "within_250m": (e <= 250).mean()})
    out = {"overall": summ(v).to_frame("all").T,
           "by_method": v.groupby("geo_method").apply(summ, include_groups=False),
           "by_ncic": v.groupby("NCIC Code").apply(summ, include_groups=False).sort_values("n", ascending=False)}
    return out, v


def coverage_tables(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    need = df[df.injury & (df.coord_state != "valid")]
    surface = need[need["IsFreeway"].fillna("False") != "True"]
    t = {}
    t["status_for_missing_surface"] = surface.groupby(["agency", "geo_status"], dropna=False).size().unstack(fill_value=0)
    t["status_by_ncic_missing_surface"] = (surface.groupby("NCIC Code")["geo_status"].value_counts(normalize=True)
                                           .unstack(fill_value=0).join(surface.groupby("NCIC Code").size().rename("n"))
                                           .sort_values("n", ascending=False).head(15))
    return t


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    RESULTS.mkdir(parents=True, exist_ok=True)
    county = gpd.read_file(PROCESSED / "census" / "tiger_acs2024_county.geojson").to_crs(PROJ).geometry.iloc[0]
    df = classify_coords(load_crashes(), county)
    for name, tab in completeness_tables(df).items():
        tab.round(4).to_csv(RESULTS / f"completeness_{name}.csv")
    cl = gpd.read_file(PROCESSED / "county_gis" / "street_centerlines.geojson")
    df = run_geocoder(df, Geocoder(cl))
    vt, v = validation(df)
    for name, tab in vt.items():
        tab.round(3).to_csv(RESULTS / f"geocode_validation_{name}.csv")
    for name, tab in coverage_tables(df).items():
        tab.round(4).to_csv(RESULTS / f"geocode_{name}.csv")

    # best available coordinate per crash: officer if valid, else geocoded (flagged)
    use_geo = (df.coord_state != "valid") & (df.geo_status == "ok")
    df["final_x"] = np.where(df.coord_state == "valid", df.x, np.where(use_geo, df.geo_x, np.nan))
    df["final_y"] = np.where(df.coord_state == "valid", df.y, np.where(use_geo, df.geo_y, np.nan))
    df["final_source"] = np.select([df.coord_state == "valid", use_geo], ["officer", "geocoded_street_names"], default="none")
    ok = df.final_x.notna()
    lat, lon = unproject(df.loc[ok, "final_x"].values, df.loc[ok, "final_y"].values)
    df["final_lat"] = np.nan
    df["final_lon"] = np.nan
    df.loc[ok, "final_lat"], df.loc[ok, "final_lon"] = lat, lon
    keep = ["Collision Id", "Report Number", "Crash Date Time", "year", "NCIC Code", "agency", "City Name", "injury",
            "coord_state", "geo_status", "geo_method", "final_source", "final_lat", "final_lon"]
    dest = out_dir(PROCESSED, "audit") / "ccrs_crash_coordinates.parquet"
    df[keep].to_parquet(dest, index=False)
    log_pull("audit", "ccrs_crash_coordinates (officer + geocoded)", out_path=dest, rows_out=len(df),
             note="derived by audit/coordinates.py from ccrs + county centerlines; geocoded rows are estimates")

    inj = df[df.injury]
    print("\n=== injury crashes 2016-2025 ===")
    print(inj.groupby("final_source").size().rename("n").to_frame().assign(share=lambda d: (d.n / d.n.sum()).round(3)))
    print("\nvalidation (geocode vs officer coords, city PD):")
    print(vt["overall"].round(2).to_string())
    print(vt["by_method"].round(2).to_string())


if __name__ == "__main__":
    main()
