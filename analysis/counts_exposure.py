"""Part 2/3 exposure check: do crashes at an intersection track how many people walk and bike there?

    python -m analysis.counts_exposure        (needs analysis.counts first)

Data. 121 of the 148 Alameda CTC 2024 count locations (4-6 pm, one weekday each, fall 2024) that the street-name
geocoder placed on a map (see analysis/counts.py), and TIMS-geocoded injury crashes on surface streets.

Design (fixed before looking at results).
    crashes   pedestrian-involved and bicyclist-involved injury crashes within 50 m of the location, 2020-2025
    model     Poisson, log link; predictor log(people counted + 1); controls log(AADT of nearest segment) (+ missing
              flag), road class group; robust (HC1) standard errors
    reading   slope on log(people) below 1 = more people walking means more crashes but fewer per person ("safety
              in numbers"); 1 = crashes proportional to people; above 1 = risk per person rises with volume
    checks    100 m radius; all years 2016-2025; pedestrian count only vs. adding bicyclists
    second    can features we already hold (density, bus stops, schools, jobs, income, class, AADT) predict counts?
              leave-one-out R-squared of a ridge regression for log(ped + 1) and log(bike + 1).

What it does not show. A single two-hour count per site is a noisy index of annual volume; sites were chosen by
Alameda CTC (busy corridors, many near transit and downtown); 27 of 148 sites could not be placed. Causal claims
(more walkers makes streets safer) are not supported: busy places also differ in speeds, signals and design.
"""
from __future__ import annotations

import logging
import warnings

import geopandas as gpd
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from sklearn.linear_model import RidgeCV
from sklearn.model_selection import LeaveOneOut, cross_val_predict
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

from alameda_traffic.config import PROCESSED, REPO_ROOT
from alameda_traffic.geocode import unproject

log = logging.getLogger("analysis.counts_exposure")
RESULTS = REPO_ROOT / "analysis" / "results"
CLASS = {"residential": "local", "living_street": "local", "unclassified": "collector", "tertiary": "collector",
         "tertiary_link": "collector", "secondary": "arterial", "secondary_link": "arterial", "primary": "arterial",
         "primary_link": "arterial", "trunk": "arterial"}


def load():
    d = pd.read_parquet(PROCESSED / "analysis" / "counts_2024.parquet")
    d = d[d.geo_status == "ok"].copy()
    d = d.drop_duplicates(["x", "y"]).reset_index(drop=True)          # two sites share one intersection
    pts = gpd.GeoDataFrame(d, geometry=gpd.points_from_xy(d.x, d.y), crs=26910)
    c = pd.read_parquet(PROCESSED / "analysis" / "crashes.parquet")
    c = c[~c.freeway & c.lat.notna() & (c.ped | c.bike)].copy()
    cg = gpd.GeoDataFrame(c, geometry=gpd.points_from_xy(c.lon, c.lat), crs=4326).to_crs(26910)
    seg = gpd.read_parquet(PROCESSED / "analysis" / "segments.parquet").to_crs(26910)
    feat = pd.read_parquet(PROCESSED / "analysis" / "segment_features.parquet")
    seg = seg.merge(feat, on="segment_id", how="left")
    near = gpd.sjoin_nearest(pts, seg[["segment_id", "osm_class", "hpms_aadt", "hpms_lanes", "pop_density_km2", "bus_stops_400m",
                                       "schools_400m", "jobs_density_km2", "median_income", "poverty_share", "geometry"]],
                             how="left", max_distance=150, distance_col="seg_dist").drop(columns="index_right")
    near = near.drop_duplicates("loc_id")
    return near, cg


def crash_counts(pts, cg, radius, years):
    c = cg[cg.year.between(*years)]
    out = {}
    j = gpd.sjoin(c, gpd.GeoDataFrame(geometry=pts.geometry.buffer(radius), index=pts.index), predicate="within")
    j["ped_inj"] = j.ped
    j["bike_inj"] = j.bike
    j["pb_ksi"] = (j.ped | j.bike) & j.ksi
    g = j.groupby("index_right")[["ped_inj", "bike_inj", "pb_ksi"]].sum()
    return g.reindex(pts.index).fillna(0)


def prep(pts):
    p = pts.copy()
    p["log_ped"], p["log_bike"] = np.log1p(p.ped), np.log1p(p.bike + p.ebike)
    p["aadt_missing"] = p.hpms_aadt.isna().astype(int)
    p["log_aadt"] = np.log(p.hpms_aadt.fillna(1).clip(lower=1))
    p["cls"] = p.osm_class.map(CLASS).fillna("other")
    return p


def fit(p, outcome, rhs, label, term):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = smf.glm(f"{outcome} ~ {rhs}", data=p, family=sm.families.Poisson()).fit(cov_type="HC1")
    b, se = m.params[term], m.bse[term]
    return dict(analysis=label, outcome=outcome, term=term, sites=len(p), crashes=int(p[outcome].sum()), slope=round(b, 2),
                ci_low=round(b - 1.96 * se, 2), ci_high=round(b + 1.96 * se, 2), p=round(float(m.pvalues[term]), 4))


def predict_counts(p):
    feats = ["log_aadt", "aadt_missing", "hpms_lanes", "pop_density_km2", "bus_stops_400m", "schools_400m", "jobs_density_km2",
             "median_income", "poverty_share"]
    X = p[feats].copy()
    X["pop_density_km2"] = np.log1p(X.pop_density_km2)
    X["jobs_density_km2"] = np.log1p(X.jobs_density_km2)
    X = pd.concat([X, pd.get_dummies(p.cls, prefix="cls").astype(float)], axis=1)
    X = X.fillna(X.median(numeric_only=True))
    rows = []
    for y in ("log_ped", "log_bike"):
        yy = p[y].values
        pred = cross_val_predict(make_pipeline(StandardScaler(), RidgeCV(alphas=np.logspace(-1, 3, 20))), X, yy, cv=LeaveOneOut())
        r2 = 1 - ((yy - pred) ** 2).sum() / ((yy - yy.mean()) ** 2).sum()
        rows.append(dict(target=y, sites=len(p), leave_one_out_R2=round(r2, 2), spearman=round(float(pd.Series(pred).corr(pd.Series(yy), method="spearman")), 2)))
    return pd.DataFrame(rows)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    pts, cg = load()
    log.info("count sites used %d; ped+bike injury crashes available %d", len(pts), len(cg))
    rows = []
    ctrl = "log_aadt + aadt_missing + C(cls)"
    for radius, years, tag in ((50, (2020, 2025), "PRIMARY: 50 m, 2020-25"), (100, (2020, 2025), "check: 100 m"), (50, (2016, 2025), "check: 2016-25")):
        cc = crash_counts(pts, cg, radius, years)
        p = prep(pts.join(cc))
        for out, term, extra in (("ped_inj", "log_ped", "log_bike"), ("bike_inj", "log_bike", "log_ped"), ("pb_ksi", "log_ped", "log_bike")):
            rows.append(fit(p, out, f"{term} + {ctrl}", tag + " + controls", term))
            if tag.startswith("PRIMARY"):
                rows.append(fit(p, out, term, tag + ", no controls", term))
                rows.append(fit(p, out, f"{term} + {extra} + {ctrl}", tag + f" + {extra}", term))
        if tag.startswith("PRIMARY"):
            primary = p
    res = pd.DataFrame(rows)
    pd.set_option("display.width", 220, "display.max_columns", 20, "display.max_rows", 200)
    print(res.to_string(index=False))
    res.to_csv(RESULTS / "counts_exposure_results.csv", index=False)

    print("\nSites by count (4-6 pm, 2 h):", primary[["ped", "bike"]].describe().round(0).T.to_string())
    print("\nCrashes within 50 m, 2020-25:", primary[["ped_inj", "bike_inj", "pb_ksi"]].sum().to_dict())
    primary["ped_q"] = pd.qcut(primary.ped.rank(method="first"), 4, labels=["Q1 low", "Q2", "Q3", "Q4 high"])
    raw = primary.groupby("ped_q", observed=True).agg(sites=("ped", "size"), ped_mean=("ped", "mean"), ped_crashes=("ped_inj", "sum"))
    raw["ped_crashes_per_site_yr"] = (raw.ped_crashes / raw.sites / 6).round(2)
    raw["crashes_per_100k_peds_counted"] = (raw.ped_crashes / (raw.ped_mean * raw.sites) * 1e5).round(0)
    print("\nPedestrian crashes by pedestrian-count quartile:\n", raw.round(1).to_string())
    raw.to_csv(RESULTS / "counts_exposure_quartiles.csv")

    pc = predict_counts(primary)
    print("\nCan existing segment features predict the counts? (leave-one-out)\n", pc.to_string(index=False))
    pc.to_csv(RESULTS / "counts_exposure_predictability.csv", index=False)


if __name__ == "__main__":
    main()
