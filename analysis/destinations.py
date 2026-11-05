"""Part 2: are serious crashes more common on streets next to hospitals and nursing homes?

    python -m analysis.destinations

Question. Hospitals bring patients, visitors and staff on foot and by ambulance; skilled nursing facilities
house older adults who are more likely to die if hit. Do the quarter-mile street segments within 400 m of
one have more injury or serious-injury crashes than comparable segments elsewhere, and do nursing homes
show more older-adult (65+) pedestrian and bicyclist crashes?

Design (fixed before looking at results).
    data     quarter-mile surface-street segments, crashes 2016-2025 (10 years)
    model    Poisson regression, offset = log(segment miles x 10 years); standard errors clustered by street name
    exposure within 400 m of a general acute care hospital; within 400 m of a skilled nursing facility (both in one model)
    controls road class, log(AADT) (+ missing flag), lanes (+ missing flag), city, population density, bus stops,
             intersections, schools within 400 m, equity-priority tract (hospitals sit in dense centres, so density and
             city matter)
    outcomes injury crashes; killed-or-seriously-injured (KSI); pedestrian + bicyclist KSI;
             older-adult pedestrian/bicyclist injury crashes (a 65+ injured pedestrian or bicyclist, CCRS ages)
Checks: distance bands instead of a single 400 m cut; arterials only; without density, transit and equity controls.

What it does not show. There is no count of people walking, so a higher rate is "more crashes per mile of street",
not more risk per person. Hospitals and nursing homes are not randomly placed.
"""
from __future__ import annotations

import glob
import logging
import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

from alameda_traffic.config import PROCESSED, REPO_ROOT

import geopandas as gpd

log = logging.getLogger("analysis.destinations")
RESULTS = REPO_ROOT / "analysis" / "results"
YEARS = 10
ARTERIAL = ["primary", "secondary", "tertiary", "trunk"]


def older_adult_counts() -> pd.DataFrame:
    inj = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(str(PROCESSED / "ccrs" / "injured_20*.parquet")))], ignore_index=True)
    pb = inj[inj.InjuredPersonType.isin(["Pedestrian", "Bicyclist"])].copy()
    pb["age"] = pd.to_numeric(pb.StatedAge, errors="coerce")
    pb = pb[pb.age >= 65]
    cids = set(pb.CollisionId.astype(str).str.strip())
    c = pd.read_parquet(PROCESSED / "analysis" / "crashes.parquet")
    c = c[c.collision_id.notna() & ~c.freeway].copy()
    c["older"] = c.collision_id.astype(int).astype(str).isin(cids)
    cs = pd.read_parquet(PROCESSED / "analysis" / "crash_segment.parquet")
    m = cs.merge(c[["tims_case_id", "older", "ksi"]], on="tims_case_id")
    m = m[m.older]
    return pd.DataFrame({"older_inj": m.groupby("segment_id").size(), "older_ksi": m[m.ksi].groupby("segment_id").size()}).fillna(0)


def load() -> pd.DataFrame:
    s = gpd.read_parquet(PROCESSED / "analysis" / "segments.parquet").drop(columns="geometry")
    s = s.merge(older_adult_counts(), left_on="segment_id", right_index=True, how="left")
    s[["older_inj", "older_ksi"]] = s[["older_inj", "older_ksi"]].fillna(0)
    s["miles"] = s.length_m / 1609.344
    s["inj"], s["ksi"] = s.n_inj_total, s.n_ksi_total
    s["pb_ksi"] = s.n_ped_ksi_total + s.n_bike_ksi_total
    s["near_hosp"] = (s.hospital_dist_m <= 400).astype(int)
    s["near_snf"] = (s.snf_400m > 0).astype(int)
    s["hosp_band"] = pd.cut(s.hospital_dist_m, [0, 200, 400, 800, 1600, 1e9], labels=["h0_200", "h200_400", "h400_800", "h800_1600", "far"], right=True)
    s["snf_band"] = pd.cut(s.snf_dist_m, [0, 200, 400, 800, 1600, 1e9], labels=["s0_200", "s200_400", "s400_800", "s800_1600", "far"], right=True)
    cls = s.osm_class.str.replace("_link", "", regex=False)
    s["cls"] = cls.where(cls.isin(ARTERIAL + ["residential", "unclassified"]), "other")
    s["aadt_missing"] = s.hpms_aadt.isna().astype(int)
    s["log_aadt"] = np.log(s.hpms_aadt.fillna(1).clip(lower=1))
    lanes = s.hpms_lanes.fillna(s.osm_lanes)
    s["lanes_missing"] = lanes.isna().astype(int)
    s["lanes"] = lanes.fillna(0).clip(upper=6)
    top = s.groupby("place").miles.sum().sort_values(ascending=False).head(14).index
    s["city"] = s.place.where(s.place.isin(top), "other").fillna("unincorporated")
    s["street"] = s.name.fillna("seg" + s.segment_id.astype(str))
    for c in ("schools_400m", "bus_stops_400m", "n_intersections"):
        s[c] = s[c].fillna(0)
    s["log_density"] = np.log1p(s.pop_density_km2.fillna(0))
    s["epc_i"] = s.epc.fillna(False).astype(int)
    return s[s.miles > 0]


ROAD = "C(cls) + log_aadt + aadt_missing + lanes + lanes_missing + C(city)"
FULL = ROAD + " + log_density + bus_stops_400m + n_intersections + schools_400m + epc_i"


def fit(d, outcome, rhs, terms, label):
    d = d.copy()
    d["_off"] = np.log(d.miles * YEARS)
    groups = pd.factorize(d.street)[0]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = smf.glm(f"{outcome} ~ {rhs}", data=d, family=sm.families.Poisson(), offset=d["_off"]).fit(cov_type="cluster", cov_kwds={"groups": groups})
    rows = []
    for t in terms:
        if t in m.params:
            b, se = m.params[t], m.bse[t]
            rows.append({"analysis": label, "outcome": outcome, "term": t, "segments": len(d), "events": int(d[outcome].sum()),
                         "IRR": round(float(np.exp(b)), 2), "ci_low": round(float(np.exp(b - 1.96 * se)), 2),
                         "ci_high": round(float(np.exp(b + 1.96 * se)), 2), "p": round(float(m.pvalues[t]), 4)})
    return rows


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    d = load()
    log.info("segments %d; within 400 m of a hospital %d; of a nursing home %d; older-adult ped/bike injury crashes %d",
             len(d), d.near_hosp.sum(), d.near_snf.sum(), int(d.older_inj.sum()))
    rows = []
    for o in ("inj", "ksi", "pb_ksi", "older_inj"):
        rows += fit(d, o, "near_hosp + near_snf + " + FULL, ["near_hosp", "near_snf"], "PRIMARY: 400 m, full controls")
        rows += fit(d, o, "near_hosp + near_snf + " + ROAD, ["near_hosp", "near_snf"], "check: road controls only")
        a = d[d.cls.isin(ARTERIAL)]
        rows += fit(a, o, "near_hosp + near_snf + " + FULL, ["near_hosp", "near_snf"], "check: arterials only")
        rows += fit(d, o, "C(hosp_band, Treatment('far')) + C(snf_band, Treatment('far')) + " + FULL,
                    [f"C(hosp_band, Treatment('far'))[T.{b}]" for b in ("h0_200", "h200_400", "h400_800", "h800_1600")] +
                    [f"C(snf_band, Treatment('far'))[T.{b}]" for b in ("s0_200", "s200_400", "s400_800", "s800_1600")], "distance bands")
    res = pd.DataFrame(rows)
    res.to_csv(RESULTS / "destinations_results.csv", index=False)
    pd.set_option("display.width", 220, "display.max_columns", 20, "display.max_rows", 300, "display.max_colwidth", 60)
    print(res.to_string(index=False))
    raw = d.groupby(["near_hosp", "near_snf"]).agg(segments=("miles", "size"), miles=("miles", "sum"), inj=("inj", "sum"), ksi=("ksi", "sum"),
                                                   pb_ksi=("pb_ksi", "sum"), older_inj=("older_inj", "sum"))
    for c in ("inj", "ksi", "pb_ksi", "older_inj"):
        raw[c + "_per_mile_yr"] = (raw[c] / (raw.miles * YEARS)).round(3)
    raw.to_csv(RESULTS / "destinations_raw_rates.csv")
    print("\nRaw rates (no adjustment):\n", raw.round(2).to_string())


if __name__ == "__main__":
    main()
