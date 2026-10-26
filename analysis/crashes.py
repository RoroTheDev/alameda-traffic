"""Analysis-ready crash table (injury and fatal crashes, Alameda County, 2016-2025).

    python -m analysis.crashes

Base = TIMS crashes (consistent SWITRS coding: severity, mode flags, victim counts).
Linked in from CCRS (via audit.compare_tims.link): Collision Id, officer coordinates, IsFreeway,
and from the audit: our street-name geocode. All three coordinate sources are kept side by
side so any result can be re-run under a different choice:

    tims_lat/lon     SafeTREC geocode (POINT_Y/POINT_X)           ~99% of crashes
    geo_lat/lon      our PrimaryRoad x SecondaryRoad geocode       surface streets only
    officer_lat/lon  CCRS officer-reported, valid and inside county

`lat`/`lon` = the chosen coordinate, with `coord_source` saying which. Default order:
SafeTREC, then ours, then officer. Whether that is the right order is an analysis choice,
not settled (see docs/COORDINATE_AUDIT.md); `coord_disagree_250m` flags crashes where the
sources differ by more than 250 m so they can be dropped in a sensitivity run.

Severity follows KABCO collapsed to TIMS's four levels: 1 fatal, 2 severe, 3 other visible,
4 complaint of pain. KSI = severity 1 or 2.
"""
from __future__ import annotations

import logging

import geopandas as gpd
import numpy as np
import pandas as pd

from alameda_traffic.config import PROCESSED, out_dir
from alameda_traffic.geocode import PROJ, project
from alameda_traffic.provenance import log_pull
from audit.compare_tims import link, load_tims, meters
from audit.coordinates import classify_coords, load_crashes

log = logging.getLogger("analysis.crashes")


def build() -> pd.DataFrame:
    t = load_tims()
    county = gpd.read_file(PROCESSED / "census" / "tiger_acs2024_county.geojson").to_crs(PROJ).geometry.iloc[0]
    c = link(classify_coords(load_crashes(), county), t)
    ours = pd.read_parquet(PROCESSED / "audit" / "ccrs_crash_coordinates.parquet")
    geo = ours.loc[ours.final_source == "geocoded_street_names", ["Collision Id", "final_lat", "final_lon"]]
    c = c.merge(geo, on="Collision Id", how="left")

    # CCRS rows that link to a TIMS row (injury crashes only; one CCRS row per TIMS row)
    lk = c[c.tims_row.notna()].copy()
    lk["tims_row"] = lk["tims_row"].astype(int)
    dup = lk["tims_row"].duplicated(keep=False)
    if dup.any():
        log.warning("%d CCRS rows claim the same TIMS row; keeping the id-tier link first", int(dup.sum()))
        lk = lk.sort_values("link_tier", key=lambda s: s.eq("composite")).drop_duplicates("tims_row")
    lk = lk.set_index("tims_row")

    out = pd.DataFrame(index=t.index)
    out["tims_case_id"] = t["CASE_ID"]
    out["collision_id"] = lk["Collision Id"].reindex(t.index)
    out["linked_to_ccrs"] = out["collision_id"].notna()
    out["date"] = t["date"]
    out["year"] = pd.to_numeric(t["ACCIDENT_YEAR"])
    out["hhmm"] = t["hhmm"]
    out["dow"] = pd.to_numeric(t["DAY_OF_WEEK"], errors="coerce")
    out["juris"] = t["juris"]
    out["agency"] = np.where(t["juris"].str.startswith("93"), "CHP", np.where(t["juris"].str.startswith("01"), "City/campus PD", "other"))
    out["city"] = t["CITY"]
    out["primary_road"] = t["PRIMARY_RD"]
    out["secondary_road"] = t["SECONDARY_RD"]
    sev = pd.to_numeric(t["COLLISION_SEVERITY"], errors="coerce")
    out["severity"] = sev
    out["ksi"] = sev.isin([1, 2])
    out["fatal"] = sev == 1
    for src, dst in [("PEDESTRIAN_ACCIDENT", "ped"), ("BICYCLE_ACCIDENT", "bike"), ("MOTORCYCLE_ACCIDENT", "moto"),
                     ("TRUCK_ACCIDENT", "truck"), ("ALCOHOL_INVOLVED", "alcohol"), ("HIT_AND_RUN", "hit_run")]:
        out[dst] = t[src].fillna("N").astype(str).str.upper().eq("Y") if src != "HIT_AND_RUN" else t[src].astype(str).str.upper().isin(["Y", "M", "F"])
    out["intersection"] = t["INTERSECTION"].map({"Y": True, "N": False})
    out["state_hwy"] = t["STATE_HWY_IND"].eq("Y")
    out["location_type"] = t["LOCATION_TYPE"]
    ccrs_fwy = lk["IsFreeway"].reindex(t.index).eq("True")
    route = t["PRIMARY_RD"].fillna("").str.upper().str.contains(r"^(?:I-|SR-|RT |US-|HWY)|\bI-\d{2,3}\b|\bFWY\b|\bRAMP\b", regex=True)
    out["freeway"] = ccrs_fwy | t["LOCATION_TYPE"].isin(["H", "R"]) | route
    out["lighting"] = t["LIGHTING"]
    out["control_device"] = t["CONTROL_DEVICE"]
    out["weather"] = t["WEATHER_1"]
    out["pcf_violation"] = t["PCF_VIOLATION"]
    for src, dst in [("NUMBER_KILLED", "n_killed"), ("NUMBER_INJURED", "n_injured"), ("PARTY_COUNT", "n_parties"),
                     ("COUNT_PED_KILLED", "ped_killed"), ("COUNT_PED_INJURED", "ped_injured"),
                     ("COUNT_BICYCLIST_KILLED", "bike_killed"), ("COUNT_BICYCLIST_INJURED", "bike_injured")]:
        out[dst] = pd.to_numeric(t[src], errors="coerce")

    # coordinates, three sources
    inside = lambda lat, lon: pd.Series(project(lat.fillna(0), lon.fillna(0)).within(county).values, index=lat.index) & lat.notna()
    out["tims_lat"], out["tims_lon"] = t["POINT_Y"], t["POINT_X"]
    out.loc[~inside(out.tims_lat, out.tims_lon), ["tims_lat", "tims_lon"]] = np.nan
    out["geo_lat"], out["geo_lon"] = lk["final_lat"].reindex(t.index), lk["final_lon"].reindex(t.index)
    out["officer_lat"] = lk["lat"].where(lk["coord_state"] == "valid").reindex(t.index)
    out["officer_lon"] = lk["lon"].where(lk["coord_state"] == "valid").reindex(t.index)
    pick = [("tims", "tims_lat", "tims_lon"), ("ours", "geo_lat", "geo_lon"), ("officer", "officer_lat", "officer_lon")]
    out["lat"], out["lon"], out["coord_source"] = np.nan, np.nan, "none"
    for name, la, lo in reversed(pick):  # lowest priority first, overwritten by better ones
        m = out[la].notna()
        out.loc[m, ["lat", "lon"]] = out.loc[m, [la, lo]].values
        out.loc[m, "coord_source"] = name
    # disagreement between any two available sources
    dis = np.zeros(len(out), bool)
    for (_, la1, lo1), (_, la2, lo2) in [(pick[0], pick[1]), (pick[0], pick[2]), (pick[1], pick[2])]:
        both = out[la1].notna() & out[la2].notna()
        if both.any():
            d = meters(out.loc[both, la1], out.loc[both, lo1], out.loc[both, la2], out.loc[both, lo2])
            dis[np.flatnonzero(both.values)[d > 250]] = True
    out["coord_disagree_250m"] = dis
    return out.reset_index(drop=True)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    df = build()
    dest = out_dir(PROCESSED, "analysis") / "crashes.parquet"
    df.to_parquet(dest, index=False)
    log_pull("analysis", "crashes (TIMS base + CCRS link + audit geocode)", out_path=dest, rows_out=len(df),
             note="built by analysis/crashes.py")
    print(f"{len(df)} crashes -> {dest}")
    print("\ncoordinate source used:", df.coord_source.value_counts().to_dict())
    print("sources disagree >250 m on", int(df.coord_disagree_250m.sum()), "crashes")
    print("\nseverity:", df.severity.value_counts().sort_index().to_dict(),
          "| ped", int(df.ped.sum()), "| bike", int(df.bike.sum()), "| moto", int(df.moto.sum()))
    print("freeway:", int(df.freeway.sum()), "| surface:", int((~df.freeway).sum()),
          "| surface KSI:", int((~df.freeway & df.ksi).sum()))
    print("\nlinked to CCRS:", round(df.linked_to_ccrs.mean(), 3))
    print("surface crashes with a coordinate:", round(df.loc[~df.freeway, "lat"].notna().mean(), 4))
    print("by agency (surface):", df[~df.freeway].groupby("agency").size().to_dict())


if __name__ == "__main__":
    main()
