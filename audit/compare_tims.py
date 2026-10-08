"""Compare TIMS (SafeTREC) coordinates with CCRS and with our street-name geocoder.

    python -m audit.compare_tims            # after: python download.py tims --extract-date ...

TIMS crash rows carry two coordinate pairs (per SafeTREC docs):
    LATITUDE / LONGITUDE   officer-reported, passed through from the CHP record
    POINT_X / POINT_Y      SafeTREC's own geocode (WGS84; lon = X, lat = Y)
so three separate questions can be asked, each answering something different:

  A. Join fidelity     – is each CCRS crash found in TIMS? (match rate by agency/year)
  B. Pass-through      – where both have officer coordinates, do CCRS and TIMS agree?
                         Differences mean the SWITRS -> CCRS transition changed the data.
  C. Geocode quality   – TIMS POINT_X/Y vs officer coordinates (how good are officer
                         coordinates / how good is SafeTREC's geocode?), and vs OUR
                         street-name geocode for crashes with no officer coordinates.

STATUS: written against SafeTREC's documented column names but NOT yet run on real
files — the first run will show whether the join keys work. The join is reported
with explicit diagnostics instead of assumed:
  1. CCRS "Report Number" normalised == TIMS CASE_ID (agency case number), plus year
  2. fallback: collision date + time + normalised primary/secondary road
TIMS is built from the same CHP records as CCRS, so agreement is NOT independent
validation of location accuracy — only (C) against street geometry is.
"""
from __future__ import annotations

import glob
import logging
import re

import numpy as np
import pandas as pd

from alameda_traffic.config import PROCESSED
from alameda_traffic.geocode import PROJ
from audit.coordinates import RESULTS, classify_coords, load_crashes
import geopandas as gpd

log = logging.getLogger("audit.compare_tims")


def norm_case(s) -> str:
    return re.sub(r"[^0-9A-Z]", "", str(s).upper()).lstrip("0")


def load_tims() -> pd.DataFrame:
    files = sorted(glob.glob(str(PROCESSED / "tims" / "*.parquet")))
    frames = []
    for f in files:
        d = pd.read_parquet(f)
        d.columns = [c.strip().upper() for c in d.columns]
        if {"CASE_ID", "POINT_X", "POINT_Y"} <= set(d.columns):
            frames.append(d)
        else:
            log.info("skipping %s (no CASE_ID/POINT_X/POINT_Y — probably Parties/Victims)", f)
    if not frames:
        raise SystemExit("No TIMS crash file found in data/processed/tims — run download.py tims first.")
    t = pd.concat(frames, ignore_index=True)
    for c in ("POINT_X", "POINT_Y", "LATITUDE", "LONGITUDE"):
        if c in t:
            t[c] = pd.to_numeric(t[c], errors="coerce")
    return t


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    t = load_tims()
    county = gpd.read_file(PROCESSED / "census" / "tiger_acs2024_county.geojson").to_crs(PROJ).geometry.iloc[0]
    c = classify_coords(load_crashes(), county)
    ours = pd.read_parquet(PROCESSED / "audit" / "ccrs_crash_coordinates.parquet")[["Collision Id", "final_lat", "final_lon", "final_source"]]
    c = c.merge(ours, on="Collision Id", how="left")

    c["_key"] = c["Report Number"].map(norm_case) + "|" + c["year"].astype(str)
    year_col = "ACCIDENT_YEAR" if "ACCIDENT_YEAR" in t else None
    t["_year"] = t[year_col] if year_col else pd.to_datetime(t.get("COLLISION_DATE"), errors="coerce").dt.year
    t["_key"] = t["CASE_ID"].map(norm_case) + "|" + t["_year"].astype(str).str.replace(r"\.0$", "", regex=True)
    dup = t["_key"].duplicated(keep=False).sum()
    m = c.merge(t.drop_duplicates("_key"), on="_key", how="left", suffixes=("", "_tims"), indicator=True)

    # A. join fidelity
    inj = m[m.injury]
    a = inj.groupby(["agency"]).apply(lambda g: pd.Series({"ccrs_injury": len(g), "found_in_tims": (g["_merge"] == "both").mean()}),
                                      include_groups=False)
    a.round(3).to_csv(RESULTS / "tims_join_by_agency.csv")
    print("A. join fidelity (CCRS injury crashes found in TIMS by case number + year):")
    print(a.round(3).to_string(), f"\n   duplicate TIMS keys: {dup}")
    both = m[m["_merge"] == "both"]
    if both.empty:
        print("   NO MATCHES — the case-number key does not line up; inspect a few Report Number vs CASE_ID pairs, "
              "then adjust norm_case() or use the date/time/street fallback.")
        return

    # B. pass-through: officer coords in CCRS vs TIMS LATITUDE/LONGITUDE
    if {"LATITUDE", "LONGITUDE"} <= set(both.columns):
        both = both.assign(lat_t=both["LATITUDE"], lon_t=both["LONGITUDE"])
        both_ok = both[(both.coord_state == "valid") & both.lat_t.notna() & both.lon_t.notna()]
        d = np.hypot((both_ok.lat - both_ok.lat_t) * 111_000,
                     (both_ok.lon - both_ok.lon_t) * 111_000 * np.cos(np.radians(37.7)))
        print(f"\nB. CCRS vs TIMS officer coordinates ({len(both_ok)} crashes with both): "
              f"identical within 1 m: {(d < 1).mean():.3f}; within 25 m: {(d < 25).mean():.3f}; median {d.median():.1f} m")
        # coverage change: coords present in one system but not the other
        print("   present in CCRS but not TIMS officer fields:",
              int(((both.coord_state == "valid") & both.lat_t.isna()).sum()),
              "| present in TIMS but not CCRS:", int(((both.coord_state != "valid") & both.lat_t.notna()).sum()))

    # C. TIMS geocode vs officer coords, and vs our street-name geocode
    tp = both[both["POINT_X"].notna() & both["POINT_Y"].notna()]
    print(f"\nC. TIMS POINT_X/Y present for {len(tp)}/{len(both)} matched crashes "
          f"({len(tp) / max(len(both), 1):.3f})")
    by = (both.assign(has_point=both.POINT_X.notna())
          .groupby("agency")["has_point"].mean().round(3))
    print("   TIMS geocode coverage by agency:\n", by.to_string())
    both_oc = tp[tp.coord_state == "valid"]
    if len(both_oc):
        d = np.hypot((both_oc.lat - both_oc.POINT_Y) * 111_000,
                     (both_oc.lon - both_oc.POINT_X) * 111_000 * np.cos(np.radians(37.7)))
        print(f"   TIMS geocode vs officer coords: median {d.median():.1f} m, within 50 m {(d < 50).mean():.3f}, "
              f"within 250 m {(d < 250).mean():.3f}")
    ours_only = tp[tp.final_source == "geocoded_street_names"]
    if len(ours_only):
        d = np.hypot((ours_only.final_lat - ours_only.POINT_Y) * 111_000,
                     (ours_only.final_lon - ours_only.POINT_X) * 111_000 * np.cos(np.radians(37.7)))
        print(f"   our street-name geocode vs TIMS geocode on crashes with no officer coords "
              f"({len(ours_only)}): median {d.median():.1f} m, within 100 m {(d < 100).mean():.3f}")


if __name__ == "__main__":
    main()
