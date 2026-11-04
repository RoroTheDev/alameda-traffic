"""Part 1 baseline analysis: what happened, who, when, why, where, and who bears the burden.

    python -m analysis.baseline

Descriptive statistics for injury and fatal crashes in Alameda County, 2016-2025 (TIMS base,
analysis/crashes.py). No models. Tables are written to analysis/results/baseline_*.csv.

  1 trends       crashes, killed-or-seriously-injured (KSI), deaths by year, surface vs freeway, by road user
  2 deaths check TIMS deaths vs the federal count (FARS)
  3 when         hour of day, weekend, lighting: counts and the share of injury crashes that are KSI
  4 why          main cause (vehicle-code violation) of KSI crashes
  5 who          road-user mix and how severe each is
  6 burden       KSI per 100,000 residents by equity-priority-community status and income quintile (surface streets)
  7 hot spots    Getis-Ord Gi* on a 400 m grid (own implementation, binary distance weights, Benjamini-Hochberg),
                 and whether hot spots in 2016-19 still hold the crashes in 2020-25

Severity: KSI = killed or seriously injured (TIMS severity 1-2). Rates have no traffic-volume or walking
exposure; they are per resident. Intervals ignore spatial clustering and are therefore too narrow.
"""
from __future__ import annotations

import logging

import geopandas as gpd
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from scipy.stats import norm

from alameda_traffic.config import PROCESSED, REPO_ROOT
from alameda_traffic.geocode import PROJ

log = logging.getLogger("analysis.baseline")
RESULTS = REPO_ROOT / "analysis" / "results"
PCF = {"22350": "unsafe speed", "22107": "unsafe turn / lane change", "21950": "driver fails to yield to pedestrian",
       "23152": "drunk or drugged driving", "21453": "red signal", "21801": "left turn, failure to yield",
       "21954": "pedestrian fails to yield to vehicle", "21802": "stop sign, failure to yield", "22450": "stop sign",
       "21804": "entering road, failure to yield", "23153": "drunk/drugged driving causing injury",
       "21955": "pedestrian crosses outside crosswalk", "21460": "double yellow line", "21456": "pedestrian signal"}
DARK = {"C", "D", "E"}


def wilson(k, n, z=1.96):
    if n == 0:
        return (np.nan, np.nan)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - h) / d, (c + h) / d)


def gi_star(xy: np.ndarray, x: np.ndarray, d: float):
    tree = cKDTree(xy)
    nb = tree.query_ball_point(xy, r=d)
    n = len(x)
    xbar, s = x.mean(), np.sqrt((x ** 2).mean() - x.mean() ** 2)
    k = np.array([len(i) for i in nb], float)
    num = np.array([x[i].sum() for i in nb]) - xbar * k
    z = num / (s * np.sqrt((n * k - k ** 2) / (n - 1)))
    p = 2 * (1 - norm.cdf(np.abs(z)))
    order = np.argsort(p)
    q = np.empty(n)
    q[order] = np.minimum.accumulate((p[order] * n / (np.arange(n) + 1))[::-1])[::-1]
    return z, np.minimum(q, 1.0)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    RESULTS.mkdir(parents=True, exist_ok=True)
    c = pd.read_parquet(PROCESSED / "analysis" / "crashes.parquet")
    c["road"] = np.where(c.freeway, "freeway", "surface")
    c["hour"] = c.hhmm.astype(int) // 100
    pd.set_option("display.width", 220); pd.set_option("display.max_columns", 30)

    # 1 ---- trends
    t = c.groupby(["year", "road"]).agg(injury=("ksi", "size"), ksi=("ksi", "sum"), killed=("n_killed", "sum")).unstack("road")
    t.columns = [f"{a}_{b}" for a, b in t.columns]
    sf = c[~c.freeway]  # road-user rows are surface streets only, like the later tables
    t["ksi_ped"] = sf[sf.ped & sf.ksi].groupby("year").size()
    t["ksi_bike"] = sf[sf.bike & sf.ksi].groupby("year").size()
    t["ksi_moto"] = sf[sf.moto & sf.ksi].groupby("year").size()
    t["ped_killed"] = sf.groupby("year").ped_killed.sum()
    t["bike_killed"] = sf.groupby("year").bike_killed.sum()
    t.to_csv(RESULTS / "baseline_trends.csv")
    print("1) TRENDS by year\n", t.to_string())
    surf = t[["injury_surface", "ksi_surface"]]
    print("\n   surface KSI vs 2019: ", (surf.ksi_surface / surf.ksi_surface.loc[2019]).round(2).to_dict())
    early, late = t.loc[2016:2019], t.loc[2022:2025]
    print("   2016-19 -> 2022-25 mean per year, surface: KSI %.0f -> %.0f; pedestrian KSI %.0f -> %.0f; bicyclist KSI %.0f -> %.0f; motorcyclist KSI %.0f -> %.0f" % (
        early.ksi_surface.mean(), late.ksi_surface.mean(), early.ksi_ped.mean(), late.ksi_ped.mean(), early.ksi_bike.mean(), late.ksi_bike.mean(),
        early.ksi_moto.mean(), late.ksi_moto.mean()))
    print("   bicyclists killed per year 2016-19 vs 2022-25: %.1f vs %.1f; pedestrians killed: %.1f vs %.1f" % (
        early.bike_killed.mean(), late.bike_killed.mean(), early.ped_killed.mean(), late.ped_killed.mean()))

    # 2 ---- deaths vs FARS
    far = pd.concat([pd.read_parquet(f) for f in sorted((PROCESSED / "fars").glob("accident_20*.parquet"))])
    far["FATALS"] = pd.to_numeric(far.FATALS, errors="coerce")
    fy = far.groupby(pd.to_numeric(far.YEAR)).FATALS.sum()
    d = pd.DataFrame({"TIMS_deaths": c.groupby("year").n_killed.sum(), "FARS_deaths": fy}).dropna()
    d["TIMS_minus_FARS"] = d.TIMS_deaths - d.FARS_deaths
    d.to_csv(RESULTS / "baseline_deaths_vs_fars.csv")
    print("\n2) DEATHS: TIMS vs FARS (FARS 2024 is not final)\n", d.to_string())

    # 3 ---- when
    inj = c[~c.freeway].copy()
    inj["period"] = pd.cut(inj.hour, [-1, 5, 9, 15, 19, 23], labels=["night 0-5", "morning 6-9", "midday 10-15", "evening 16-19", "late 20-23"])
    inj["weekend"] = inj.dow.isin([6, 7])
    inj["lighting_g"] = inj.lighting.map(lambda v: "dark" if v in DARK else ("dusk/dawn" if v == "B" else ("daylight" if v == "A" else "unknown")))
    rows = []
    for col in ("period", "weekend", "lighting_g"):
        g = inj.groupby(col, observed=True).agg(injury=("ksi", "size"), ksi=("ksi", "sum"))
        g["pct_of_ksi"] = (100 * g.ksi / g.ksi.sum()).round(1)
        g["pct_of_injury"] = (100 * g.injury / g.injury.sum()).round(1)
        ci = [wilson(k, n) for k, n in zip(g.ksi, g.injury)]
        g["ksi_per_100_injury"] = (100 * g.ksi / g.injury).round(1)
        g["ci_low"] = [round(100 * a, 1) for a, _ in ci]
        g["ci_high"] = [round(100 * b, 1) for _, b in ci]
        g.insert(0, "dimension", col)
        rows.append(g.reset_index().rename(columns={col: "group"}))
    when = pd.concat(rows)
    when.to_csv(RESULTS / "baseline_when.csv", index=False)
    print("\n3) WHEN (surface streets): share of injury crashes that are KSI\n", when.to_string(index=False))

    # 4 ---- why
    k = inj[inj.ksi]
    why = k.pcf_violation.astype(str).str.extract(r"(\d{5})")[0].value_counts().head(12)
    why = pd.DataFrame({"code": why.index, "ksi": why.values, "share_pct": (100 * why.values / len(k)).round(1)})
    why["meaning"] = why.code.map(PCF).fillna("(see vehicle code)")
    why.to_csv(RESULTS / "baseline_causes.csv", index=False)
    print(f"\n4) WHY: primary collision factor of {len(k):,} surface KSI crashes\n", why.to_string(index=False))

    # 5 ---- who
    rows = []
    for name, m in (("pedestrian", inj.ped), ("bicyclist", inj.bike), ("motorcyclist", inj.moto), ("alcohol involved", inj.alcohol),
                    ("hit and run", inj.hit_run), ("truck involved", inj.truck), ("none of ped/bike/moto", ~(inj.ped | inj.bike | inj.moto))):
        n, kk = int(m.sum()), int(inj.ksi[m].sum())
        lo, hi = wilson(kk, n)
        rows.append({"group": name, "injury_crashes": n, "ksi": kk, "pct_of_all_ksi": round(100 * kk / inj.ksi.sum(), 1),
                     "pct_of_injury_crashes": round(100 * n / len(inj), 1), "ksi_per_100_injury": round(100 * kk / n, 1),
                     "ci_low": round(100 * lo, 1), "ci_high": round(100 * hi, 1)})
    who = pd.DataFrame(rows)
    who.to_csv(RESULTS / "baseline_who.csv", index=False)
    print("\n5) WHO (surface streets)\n", who.to_string(index=False))

    # 6 ---- burden: per-resident rates by equity status and income
    tr = gpd.read_file(PROCESSED / "census" / "tiger_acs2024_tracts.geojson").to_crs(PROJ)[["GEOID", "geometry"]]
    pts = gpd.GeoDataFrame(inj[["ksi", "ped", "bike", "year"]], geometry=gpd.points_from_xy(inj.lon, inj.lat), crs=4326).to_crs(PROJ)
    pts = gpd.sjoin(pts[inj.lat.notna().values], tr, how="left", predicate="within")
    pts = pts[~pts.index.duplicated()]
    pop = pd.read_parquet(PROCESSED / "census" / "acs2024_5yr_B01001.parquet")
    pop = pop[pop.geo_level == "tract"].assign(GEOID=lambda x: x.GEO_ID.str[-11:])[["GEOID", "B01001_001E"]].rename(columns={"B01001_001E": "pop"})
    inc = pd.read_parquet(PROCESSED / "census" / "acs2024_5yr_B19013.parquet")
    inc = inc[inc.geo_level == "tract"].assign(GEOID=lambda x: x.GEO_ID.str[-11:], income=lambda x: pd.to_numeric(x.B19013_001E, errors="coerce"))[["GEOID", "income"]]
    epc = pd.read_parquet(PROCESSED / "equity" / "epc_pba2050plus_acs2022_alameda.parquet")[["tract_geoid", "epc_2050p"]].rename(columns={"tract_geoid": "GEOID"})
    T = pop.merge(inc, on="GEOID", how="left").merge(epc, on="GEOID", how="left")
    T["epc"] = pd.to_numeric(T.epc_2050p, errors="coerce").fillna(0).astype(int) == 1
    T = T[T["pop"] > 0]
    T["ksi"] = T.GEOID.map(pts[pts.ksi].groupby("GEOID").size()).fillna(0)
    T["injury"] = T.GEOID.map(pts.groupby("GEOID").size()).fillna(0)
    T["ped_bike_ksi"] = T.GEOID.map(pts[pts.ksi & (pts.ped | pts.bike)].groupby("GEOID").size()).fillna(0)
    T["income_q"] = pd.qcut(T.income, 5, labels=["Q1 lowest", "Q2", "Q3", "Q4", "Q5 highest"])
    rows = []
    for label, keycol in (("equity priority community", "epc"), ("income quintile", "income_q")):
        g = T.dropna(subset=[keycol]).groupby(keycol, observed=True).agg(tracts=("GEOID", "size"), residents=("pop", "sum"), injury=("injury", "sum"),
                                                                         ksi=("ksi", "sum"), ped_bike_ksi=("ped_bike_ksi", "sum"))
        for col in ("injury", "ksi", "ped_bike_ksi"):
            g[f"{col}_per_100k_yr"] = (1e5 * g[col] / g.residents / 10).round(1)
        g.insert(0, "dimension", label)
        rows.append(g.reset_index().rename(columns={keycol: "group"}))
    burden = pd.concat(rows)
    burden.to_csv(RESULTS / "baseline_burden.csv", index=False)
    print("\n6) BURDEN: surface-street crashes per 100,000 residents per year, by where the crash happened\n", burden.to_string(index=False))
    a, b = burden[(burden.dimension == "equity priority community") & (burden.group == True)].iloc[0], burden[(burden.dimension == "equity priority community") & (burden.group == False)].iloc[0]
    rr = (a.ksi / a.residents) / (b.ksi / b.residents)
    se = np.sqrt(1 / a.ksi + 1 / b.ksi)
    print(f"   KSI rate ratio, equity-priority vs other tracts: {rr:.2f} ({np.exp(np.log(rr) - 1.96 * se):.2f}-{np.exp(np.log(rr) + 1.96 * se):.2f}); "
          f"ped+bike KSI: {((a.ped_bike_ksi / a.residents) / (b.ped_bike_ksi / b.residents)):.2f}")
    r2 = burden[burden.dimension == "income quintile"]
    print(f"   lowest vs highest income quintile KSI per 100k: {r2.ksi_per_100k_yr.iloc[0]} vs {r2.ksi_per_100k_yr.iloc[-1]}")

    # 7 ---- hot spots
    s = inj[inj.lat.notna()]
    xy = gpd.GeoSeries(gpd.points_from_xy(s.lon, s.lat), crs=4326).to_crs(PROJ)
    cell = pd.DataFrame({"cx": (xy.x // 400).astype(int).values, "cy": (xy.y // 400).astype(int).values, "ksi": s.ksi.values, "year": s.year.values,
                         "pb": (s.ped | s.bike).values, "city": s.city.values})
    keyf = lambda d: d.cx.astype(str) + "_" + d.cy.astype(str)
    cell["key"] = keyf(cell)
    cells = cell.groupby("key").agg(cx=("cx", "first"), cy=("cy", "first")).reset_index()
    cxy = np.c_[(cells.cx + 0.5) * 400, (cells.cy + 0.5) * 400]

    def counts(mask):
        return cell[mask].groupby("key").size().reindex(cells.key, fill_value=0).values.astype(float)

    rows = []
    for label, kmask in (("all-mode KSI", cell.ksi), ("pedestrian + bicycle KSI", cell.ksi & cell.pb)):
        x = counts(kmask.values)
        z, q = gi_star(cxy, x, 1000.0)
        hot = (z > 0) & (q < 0.05)
        share = x[hot].sum() / x.sum()
        rows.append({"analysis": f"hot spots, {label}, 2016-25", "cells_with_injury_crash": len(cells), "hot_cells": int(hot.sum()),
                     "pct_of_cells": round(100 * hot.mean(), 1), "pct_of_ksi_in_hot_cells": round(100 * share, 1)})
        top = cell[kmask].merge(cells.assign(hot=hot)[["key", "hot"]], on="key")
        top = top[top.hot].city.value_counts(normalize=True).head(5).round(3).to_dict()
        print(f"\n7) HOT SPOTS ({label}): {int(hot.sum())} of {len(cells)} cells ({100 * hot.mean():.1f}%) hold {100 * share:.1f}% of KSI. Cities: {top}")
        # stability: hot in 2016-19 -> share of 2020-25 KSI
        early, late = counts((kmask & (cell.year <= 2019)).values), counts((kmask & (cell.year >= 2020)).values)
        ze, qe = gi_star(cxy, early, 1000.0)
        he = (ze > 0) & (qe < 0.05)
        zl, ql = gi_star(cxy, late, 1000.0)
        hl = (zl > 0) & (ql < 0.05)
        rows.append({"analysis": f"hot in 2016-19 -> {label} 2020-25", "cells_with_injury_crash": len(cells), "hot_cells": int(he.sum()),
                     "pct_of_cells": round(100 * he.mean(), 1), "pct_of_ksi_in_hot_cells": round(100 * late[he].sum() / late.sum(), 1),
                     "overlap_with_2020-25_hot_cells_pct": round(100 * (he & hl).sum() / max(he.sum(), 1), 1)})
        print(f"   hot in 2016-19: {int(he.sum())} cells; they hold {100 * late[he].sum() / late.sum():.1f}% of 2020-25 KSI; "
              f"{100 * (he & hl).sum() / max(he.sum(), 1):.0f}% are still hot in 2020-25")
    pd.DataFrame(rows).to_csv(RESULTS / "baseline_hotspots.csv", index=False)


if __name__ == "__main__":
    main()
