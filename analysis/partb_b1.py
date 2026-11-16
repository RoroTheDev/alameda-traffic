"""PART B, H1 (preregistered): do crashes rise more slowly than the number of people walking, in a pooled panel of count years?

    python -m analysis.partb_b1 --selftest     # synthetic data only, checks the code recovers a known slope
    python -m analysis.partb_b1                # real data: THE CONFIRMATORY RUN (run once, after the code tag)

Registered specification (docs/OSF_REGISTRATION.md, B1, and the OSF analysis plan).
    sites       Alameda CTC manual-count sites that the street-name geocoder placed (analysis/counts.py), 4-6 pm period.
                One site per place within a year (first by location id); the same site across years = positions within 30 m.
    outcome     pedestrian-involved injury crashes within 50 m of the site, surface streets, in the three calendar years
                centred on the count year, clipped to 2016-2025; offset log(years in window)
    primary     Poisson GLM: crashes ~ log(pedestrians+1) + log(AADT of nearest segment) + missing-AADT flag
                + road-class group + count-year indicators; standard errors clustered by site
    hypothesis  the 95% interval for the pedestrian slope lies entirely below 1
    secondary   site fixed effects (sites with no crash in any window dropped; slope biased toward 0 by measurement noise in
                one two-hour count, reported with that caveat); bicyclist crashes on log(bicycles+e-bikes+1); both counts together;
                100 m radius; all years 2016-2025 as the window; no controls; dropping the largest-count site
    positive    crash counts should rise with log(AADT) (coefficient > 0)
    control
Count years are read from data/processed/analysis/counts_<year>.parquet (2016, 2017, 2018, 2020, 2022, 2024). Years that are
not present are skipped and listed; nothing else changes.
"""
from __future__ import annotations

import argparse
import logging
import warnings

import geopandas as gpd
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

from alameda_traffic.config import PROCESSED, REPO_ROOT

log = logging.getLogger("analysis.partb_b1")
RESULTS = REPO_ROOT / "analysis" / "results"
YEARS = (2016, 2017, 2018, 2020, 2022, 2024)
SITE_M = 30.0
CLASS = {"residential": "local", "living_street": "local", "unclassified": "collector", "tertiary": "collector",
         "tertiary_link": "collector", "secondary": "arterial", "secondary_link": "arterial", "primary": "arterial",
         "primary_link": "arterial", "trunk": "arterial"}


def assign_sites(xy: np.ndarray) -> np.ndarray:
    """site id = connected component of positions within SITE_M metres."""
    pairs = cKDTree(xy).query_pairs(SITE_M, output_type="ndarray")
    n = len(xy)
    if len(pairs) == 0:
        return np.arange(n)
    g = coo_matrix((np.ones(len(pairs)), (pairs[:, 0], pairs[:, 1])), shape=(n, n))
    return connected_components(g, directed=False)[1]


def load_counts():
    frames, missing = [], []
    for y in YEARS:
        f = PROCESSED / "analysis" / f"counts_{y}.parquet"
        if not f.exists():
            missing.append(y)
            continue
        d = pd.read_parquet(f)
        d = d[d.geo_status == "ok"].sort_values("loc_id").drop_duplicates(["x", "y"]).copy()
        d["count_year"] = y
        frames.append(d)
    if not frames:
        raise SystemExit("no count files found; run analysis.counts for each year first")
    d = pd.concat(frames, ignore_index=True)
    d["site"] = assign_sites(d[["x", "y"]].values)
    # one row per site per year (a second position within 30 m in the same year is dropped: first by location id)
    d = d.sort_values(["count_year", "loc_id"]).drop_duplicates(["site", "count_year"]).reset_index(drop=True)
    return d, missing


def load_crashes():
    c = pd.read_parquet(PROCESSED / "analysis" / "crashes.parquet")
    c = c[~c.freeway & c.lat.notna() & (c.ped | c.bike)].copy()
    return gpd.GeoDataFrame(c, geometry=gpd.points_from_xy(c.lon, c.lat), crs=4326).to_crs(26910)


def attach_segment(d: pd.DataFrame) -> pd.DataFrame:
    seg = gpd.read_parquet(PROCESSED / "analysis" / "segments.parquet").to_crs(26910)
    pts = gpd.GeoDataFrame(d, geometry=gpd.points_from_xy(d.x, d.y), crs=26910)
    near = gpd.sjoin_nearest(pts, seg[["segment_id", "osm_class", "hpms_aadt", "geometry"]], how="left", max_distance=150)
    return pd.DataFrame(near.drop(columns=["geometry", "index_right"]).drop_duplicates(["site", "count_year"]))


def crashes_in_window(d: pd.DataFrame, cg: gpd.GeoDataFrame, radius: float, window: str) -> pd.DataFrame:
    pts = gpd.GeoDataFrame(d[["site", "count_year"]], geometry=gpd.points_from_xy(d.x, d.y), crs=26910)
    pts["geometry"] = pts.geometry.buffer(radius)
    j = gpd.sjoin(cg[["year", "ped", "bike", "ksi", "geometry"]], pts, predicate="within")
    if window == "centred3":
        j = j[(j.year >= j.count_year - 1) & (j.year <= j.count_year + 1)]
        lo = np.maximum(d.count_year.values - 1, 2016)
        hi = np.minimum(d.count_year.values + 1, 2025)
    else:
        lo, hi = np.full(len(d), 2016), np.full(len(d), 2025)
    j = j.assign(ped_inj=j.ped.astype(int), bike_inj=j.bike.astype(int), pb_ksi=((j.ped | j.bike) & j.ksi).astype(int))
    g = j.groupby(["site", "count_year"])[["ped_inj", "bike_inj", "pb_ksi"]].sum()
    out = d.set_index(["site", "count_year"]).join(g).fillna({"ped_inj": 0, "bike_inj": 0, "pb_ksi": 0}).reset_index()
    out["years"] = (hi - lo + 1)
    return out


def prep(p: pd.DataFrame) -> pd.DataFrame:
    p = p.copy()
    p["log_ped"] = np.log1p(p.ped)
    p["log_bike"] = np.log1p(p.bike + p.ebike)
    p["aadt_missing"] = p.hpms_aadt.isna().astype(int)
    p["log_aadt"] = np.log(p.hpms_aadt.fillna(1).clip(lower=1))
    p["cls"] = p.osm_class.map(CLASS).fillna("other")
    p["log_years"] = np.log(p.years)
    p["yr"] = p.count_year.astype(str)
    return p


def fit(p, outcome, rhs, label, term, fe=False):
    p = p.copy()
    if fe:
        keep = p.groupby("site")[outcome].transform("sum") > 0
        p = p[keep]
        rhs = rhs + " + C(site)"
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = smf.glm(f"{outcome} ~ {rhs}", data=p, family=sm.families.Poisson(), offset=p["log_years"]).fit(
            cov_type="cluster", cov_kwds={"groups": pd.factorize(p.site)[0]})
    b, se = m.params[term], m.bse[term]
    return dict(analysis=label, outcome=outcome, term=term, rows=len(p), sites=int(p.site.nunique()), crashes=int(p[outcome].sum()),
                slope=round(float(b), 3), ci_low=round(float(b - 1.96 * se), 3), ci_high=round(float(b + 1.96 * se), 3),
                p=round(float(m.pvalues[term]), 4))


def run(d_raw: pd.DataFrame, cg, label_prefix=""):
    rows = []
    ctrl = "log_aadt + aadt_missing + C(cls) + C(yr)"
    for radius, window, tag in ((50, "centred3", "PRIMARY"), (100, "centred3", "check: 100 m"), (50, "all", "check: all years 2016-25")):
        p = prep(crashes_in_window(d_raw, cg, radius, window))
        if tag == "PRIMARY":
            rows.append(fit(p, "ped_inj", f"log_ped + {ctrl}", "PRIMARY: pooled, controls, year effects", "log_ped"))
            rows.append(fit(p, "ped_inj", "log_ped + C(yr)", "secondary: no controls", "log_ped"))
            rows.append(fit(p, "ped_inj", f"log_ped + log_bike + {ctrl}", "secondary: + bicyclist count", "log_ped"))
            rows.append(fit(p, "ped_inj", f"log_ped + {ctrl}", "secondary: site fixed effects (slope biased toward 0)", "log_ped", fe=True))
            rows.append(fit(p, "bike_inj", f"log_bike + {ctrl}", "secondary: bicyclist crashes on bicycle count", "log_bike"))
            rows.append(fit(p, "bike_inj", f"log_bike + log_ped + {ctrl}", "secondary: bicyclist crashes, both counts", "log_bike"))
            rows.append(fit(p, "pb_ksi", f"log_ped + {ctrl}", "secondary: ped+bike KSI on pedestrian count", "log_ped"))
            top = p.groupby("site").ped.max().idxmax()
            rows.append(fit(p[p.site != top], "ped_inj", f"log_ped + {ctrl}", "secondary: without largest-count site", "log_ped"))
            rows.append(fit(p, "ped_inj", f"log_ped + {ctrl}", "positive control: AADT coefficient > 0", "log_aadt"))
        else:
            rows.append(fit(p, "ped_inj", f"log_ped + {ctrl}", tag, "log_ped"))
    return pd.DataFrame(rows)


def selftest():
    """synthetic: true slope 0.4, check the pooled fit recovers it and the interval machinery runs."""
    rng = np.random.default_rng(1)
    n_sites, years = 150, (2016, 2018, 2020, 2022, 2024)
    base = rng.normal(4.0, 1.3, n_sites)
    aadt = rng.choice([np.nan, 5000.0, 12000.0, 30000.0], n_sites)
    cls = rng.choice(["primary", "residential", "secondary"], n_sites)
    recs = []
    for s in range(n_sites):
        for y in years:
            ped = np.exp(base[s] + rng.normal(0, 0.3))
            mu = 0.05 * ped ** 0.4 * 3
            recs.append(dict(site=s, count_year=y, ped=ped, bike=5, ebike=0, hpms_aadt=aadt[s], osm_class=cls[s],
                             ped_inj=rng.poisson(mu), bike_inj=0, pb_ksi=0, years=3))
    p = prep(pd.DataFrame(recs))
    r = fit(p, "ped_inj", "log_ped + log_aadt + aadt_missing + C(cls) + C(yr)", "selftest", "log_ped")
    print(r)
    assert abs(r["slope"] - 0.4) < 0.12, r
    assert assign_sites(np.array([[0, 0], [10, 0], [500, 0]])).tolist()[0] == assign_sites(np.array([[0, 0], [10, 0], [500, 0]])).tolist()[1]
    print("selftest ok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    if a.selftest:
        return selftest()
    d, missing = load_counts()
    log.info("count years used: %s; not available: %s; site-years %d; sites %d", sorted(d.count_year.unique()), missing, len(d), d.site.nunique())
    d = attach_segment(d)
    cg = load_crashes()
    res = run(d, cg)
    res.to_csv(RESULTS / "partb_b1_results.csv", index=False)
    pd.set_option("display.width", 220, "display.max_columns", 20, "display.max_rows", 100)
    print(res.to_string(index=False))
    pr = res[res.analysis.str.startswith("PRIMARY")].iloc[0]
    print(f"\nH1 {'SUPPORTED' if pr.ci_high < 1 else 'NOT SUPPORTED'}: pedestrian slope {pr.slope} (95% {pr.ci_low} to {pr.ci_high}); years used {sorted(d.count_year.unique())}")


if __name__ == "__main__":
    main()
