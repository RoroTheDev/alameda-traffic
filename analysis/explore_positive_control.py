"""EXPLORATORY redo of H1's positive control with better intersection volumes (docs/ADDENDUM_ABLATIONS.md, Analysis 2).

    python -m analysis.explore_positive_control

Imports analysis/partb_b1.py unchanged; only the volume column fed to its primary model differs.
Output (aggregate only): analysis/results/explore_positive_control.csv
"""
from __future__ import annotations

import logging

import geopandas as gpd
import numpy as np
import pandas as pd

import analysis.partb_b1 as B
from alameda_traffic.config import PROCESSED, REPO_ROOT

log = logging.getLogger("analysis.explore_positive_control")
RESTRICTED = REPO_ROOT / "data" / "restricted" / "analysis"
NEAR_M = 30.0


def segments():
    g = gpd.read_parquet(PROCESSED / "analysis" / "segments.parquet").to_crs(26910)
    a = pd.read_parquet(RESTRICTED / "segment_alacc.parquet", columns=["segment_id", "alacc_vol_day", "alacc_status"])
    g = g[["segment_id", "name", "osm_oneway", "hpms_aadt", "geometry"]].merge(a, on="segment_id", how="left")
    g["alacc"] = g.alacc_vol_day.where((g.alacc_status == "ok") & (g.alacc_vol_day > 0))
    g["street"] = g.name.fillna("").str.lower().str.strip()
    g.loc[g.street == "", "street"] = "seg" + g.segment_id.astype(str)
    g["oneway"] = g.osm_oneway.fillna(False).astype(str).str.lower().isin(["true", "yes", "1"])
    return g


def street_volume(grp: pd.DataFrame, col: str) -> float:
    two = grp.loc[~grp.oneway, col].dropna()
    one = grp.loc[grp.oneway, col].dropna().sort_values(ascending=False)
    cands = []
    if len(two):
        cands.append(two.max())
    if len(one):
        cands.append(one.iloc[:2].sum())
    return max(cands) if cands else np.nan


def site_volumes(d: pd.DataFrame, g: gpd.GeoDataFrame) -> pd.DataFrame:
    pts = gpd.GeoDataFrame(d[["site", "count_year"]], geometry=gpd.points_from_xy(d.x, d.y), crs=26910)
    pts["geometry"] = pts.geometry.buffer(NEAR_M)
    j = gpd.sjoin(g, pts, predicate="intersects")
    out = []
    for (site, yr), grp in j.groupby(["site", "count_year"]):
        r = {"site": site, "count_year": yr}
        for col in ("alacc", "hpms_aadt"):
            sv = grp.groupby("street").apply(lambda x: street_volume(x, col), include_groups=False).dropna()
            r[f"{col}_major"] = sv.max() if len(sv) else np.nan
            r[f"{col}_total"] = sv.sum() if len(sv) else np.nan
        out.append(r)
    return pd.DataFrame(out)


def fit_both(p, vol_col, label):
    p = p.copy()
    p["vol_missing"] = p[vol_col].isna().astype(int)
    p["log_vol"] = np.log(p[vol_col].fillna(1).clip(lower=1))
    rhs = "log_ped + log_vol + C(cls) + C(yr)" + (" + vol_missing" if p.vol_missing.nunique() > 1 else "")
    v = B.fit(p, "ped_inj", rhs, label, "log_vol")
    s = B.fit(p, "ped_inj", rhs, label, "log_ped")
    return {"volume_measure": label, "site_years": v["rows"], "sites": v["sites"], "crashes": v["crashes"],
            "share_missing": round(float(p.vol_missing.mean()), 3),
            "volume_coef": v["slope"], "volume_ci_low": v["ci_low"], "volume_ci_high": v["ci_high"],
            "positive_control": "pass" if v["ci_low"] > 0 else "fail",
            "ped_slope": s["slope"], "ped_ci_low": s["ci_low"], "ped_ci_high": s["ci_high"]}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    d, _ = B.load_counts()
    d = B.attach_segment(d)
    g = segments()
    d = d.merge(g[["segment_id", "alacc"]], on="segment_id", how="left").rename(columns={"alacc": "alacc_nearest"})
    d = d.merge(site_volumes(d, g), on=["site", "count_year"], how="left")
    p = B.prep(B.crashes_in_window(d, B.load_crashes(), 50, "centred3"))
    rows = [fit_both(p, "hpms_aadt", "1. HPMS, nearest segment (confirmatory construction)"),
            fit_both(p, "alacc_nearest", "2. AlaCC, nearest segment"),
            fit_both(p, "alacc_major", "3. AlaCC, major street within 30 m"),
            fit_both(p, "alacc_total", "4. AlaCC, intersection total within 30 m"),
            fit_both(p, "hpms_aadt_major", "5a. HPMS, major street within 30 m"),
            fit_both(p, "hpms_aadt_total", "5b. HPMS, intersection total within 30 m")]
    both = p.dropna(subset=["alacc_total", "hpms_aadt_total"])
    rows.append(fit_both(both, "alacc_total", "4'. AlaCC total, sites with both sources"))
    rows.append(fit_both(both, "hpms_aadt_total", "5b'. HPMS total, sites with both sources"))
    res = pd.DataFrame(rows)
    res.to_csv(B.RESULTS / "explore_positive_control.csv", index=False)
    pd.set_option("display.width", 250, "display.max_columns", 20)
    print(res.to_string(index=False))
    print(f"\nlog corr AlaCC vs HPMS intersection totals at sites with both: "
          f"{np.corrcoef(np.log(both.alacc_total), np.log(both.hpms_aadt_total))[0, 1]:.3f} (n={len(both)})")


if __name__ == "__main__":
    main()
