"""Part 2: is child pedestrian/bicyclist injury near schools tied to school being in session?

    python -m analysis.school_test

Question. Near schools, how much more often are children on foot or bike hurt on school days at school
travel times, compared with the same places in summer, and compared with times of day when school
should not matter?

Data. Crashes in which a child aged 5-17 on foot or bike was injured (CCRS injured-person ages linked to
TIMS crashes), surface streets, within 400 m of a school (public CDE 2024-25 + private NCES 2023-24).

Calendar. Exact district calendars are NOT used (only Fremont 2024-25 was available). Instead only core
windows that fall inside every Alameda district's school year or summer break are compared:
    in session   weekdays Sep 16 - Nov 15 and Jan 20 - Mar 10, minus federal holidays
    summer       weekdays Jun 20 - Aug 5, minus July 4
First and last weeks, all breaks, and 2020-21 (remote learning) are excluded; 2019-20 counts for Jan-Mar
2020 only. The Fremont calendar (school Aug 14 - May 30; breaks Nov 27-29, Dec 23 - Jan 3, Apr 21-25)
fits these windows. Tightening them by a week on each side is a sensitivity check.

Design. Within the near-school crashes, compare in-session vs summer rates per day:
    commute      weekdays 7-9 am and 2-5 pm  (where school should matter)
    placebos     weekdays 10 am-2 pm, weekdays 5-8 pm, weekends 7 am-8 pm  (where it should not)
    effect       commute x in-session interaction (rate ratio), Poisson with year effects and a days offset
A school effect that also shows up in the placebos would mean seasonality, not school.

What it measures, and what it does not. More children are walking and biking at school times, so more are
hurt. This measures the BURDEN tied to the school day, not the risk per trip (no counts of children
travelling). It supports "time the protection to school hours"; it does not show roads near schools are
more dangerous per child.
"""
from __future__ import annotations

import glob
import logging
import warnings
from datetime import date, timedelta

import geopandas as gpd
import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy.spatial import cKDTree

from alameda_traffic.config import PROCESSED, REPO_ROOT
from alameda_traffic.geocode import PROJ

log = logging.getLogger("analysis.school_test")
RESULTS = REPO_ROOT / "analysis" / "results"
YEARS = [2016, 2017, 2018, 2019, 2022, 2023, 2024, 2025]
NEAR_M = 400.0
PLACEBOS = ("midday", "evening", "weekend")


def nth_monday(year, month, n):
    d = date(year, month, 1)
    d += timedelta(days=(0 - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def holidays(year):
    h = {nth_monday(year, 1, 3), nth_monday(year, 2, 3), date(year, 11, 11), date(year, 7, 4)}
    for m, d in ((11, 11), (7, 4)):
        dd = date(year, m, d)
        if dd.weekday() == 5:
            h.add(dd - timedelta(days=1))
        if dd.weekday() == 6:
            h.add(dd + timedelta(days=1))
    return h


HOL = set().union(*[holidays(y) for y in YEARS + [2020]])


def season(d: date, shift: int = 0):
    """'SY' (in session) / 'SU' (summer) / None. shift (days) tightens each window on both sides."""
    md = (d.month, d.day)
    sy = ((9, 16 + shift) <= md <= (11, 15 - shift)) or ((1, 20 + shift) <= md <= (3, 10 - shift))
    su = (6, 20 + shift) <= md <= (8, 5 - shift)
    if d.year == 2020 and d > date(2020, 3, 10):
        return None
    return "SY" if sy else ("SU" if su else None)


def calendar(shift: int = 0) -> pd.DataFrame:
    rows = []
    for y in YEARS + [2020]:
        d = date(y, 1, 1)
        while d.year == y:
            s = season(d, shift)
            if s and d not in HOL:
                rows.append((d, y, s, d.weekday() >= 5))
            d += timedelta(days=1)
    return pd.DataFrame(rows, columns=["date", "year", "season", "weekend"])


def group_of(hour: pd.Series, weekend: pd.Series) -> pd.Series:
    g = pd.Series("other", index=hour.index)
    g[weekend & hour.between(7, 19)] = "weekend"
    wk = ~weekend
    g[wk & (hour.between(7, 8) | hour.between(14, 16))] = "commute"
    g[wk & hour.between(10, 13)] = "midday"
    g[wk & hour.between(17, 19)] = "evening"
    return g


def child_events() -> pd.DataFrame:
    inj = pd.concat([pd.read_parquet(f) for f in sorted(glob.glob(str(PROCESSED / "ccrs" / "injured_20*.parquet")))], ignore_index=True)
    pb = inj[inj.InjuredPersonType.isin(["Pedestrian", "Bicyclist"])].copy()
    pb["age"] = pd.to_numeric(pb.StatedAge, errors="coerce")
    pb = pb[pb.age.between(5, 17)]
    pb["cid"] = pb.CollisionId.astype(str).str.strip()
    pb = pb.groupby("cid").agg(age_min=("age", "min"), age_max=("age", "max"), mode=("InjuredPersonType", "first")).reset_index()
    c = pd.read_parquet(PROCESSED / "analysis" / "crashes.parquet")
    c = c[c.collision_id.notna() & ~c.freeway & c.lat.notna()].copy()
    c["cid"] = c.collision_id.astype(int).astype(str)
    e = pb.merge(c[["cid", "date", "hhmm", "lat", "lon", "year"]], on="cid")
    e["dt"] = pd.to_datetime(e.date)
    e["hour"] = e.hhmm.astype(int) // 100
    e["weekend"] = e.dt.dt.dayofweek >= 5
    return e


def school_distance(lat, lon):
    pub = gpd.read_file(PROCESSED / "schools" / "cde_school_sites_2425.geojson")
    pub = pub[(pub.Status == "Active") & (pub.Virtual != "V")]
    prv = gpd.read_file(PROCESSED / "schools" / "nces_private_schools_2324.geojson")
    pts = pd.concat([gpd.GeoSeries(pub.geometry.values, crs=4326), gpd.GeoSeries(prv.geometry.values, crs=4326)]).to_crs(PROJ)
    tree = cKDTree(np.c_[pts.x, pts.y])
    p = gpd.GeoSeries(gpd.points_from_xy(lon, lat), crs=4326).to_crs(PROJ)
    return tree.query(np.c_[p.x, p.y])[0], len(pts)


def classify(ev: pd.DataFrame, shift: int) -> pd.DataFrame:
    ev = ev.copy()
    ev["season"] = [season(d.date(), shift) for d in ev.dt]
    ev = ev[ev.season.notna() & ev.year.isin(YEARS + [2020]) & ~ev.dt.dt.date.isin(HOL)]
    ev["group"] = group_of(ev.hour, ev.weekend)
    return ev[ev.group != "other"]


def cells(ev, cal) -> pd.DataFrame:
    days = cal.groupby(["year", "season", "weekend"]).size().rename("days").reset_index()
    rows = []
    for g in ("commute", "midday", "evening", "weekend"):
        wk = g == "weekend"
        y = ev[ev.group == g].groupby(["year", "season"]).size().rename("y").reset_index()
        full = pd.MultiIndex.from_product([sorted(days.year.unique()), ["SY", "SU"]], names=["year", "season"]).to_frame(index=False)
        d = full.merge(y, how="left", on=["year", "season"]).fillna({"y": 0}).merge(days[days.weekend == wk][["year", "season", "days"]], on=["year", "season"], how="left")
        d["group"] = g
        rows.append(d.dropna(subset=["days"]))
    c = pd.concat(rows, ignore_index=True)
    return c[c.days > 0]


def fit(c: pd.DataFrame, control=PLACEBOS) -> dict:
    d = c[c.group.isin(("commute",) + tuple(control))].copy()
    d["sy"] = (d.season == "SY").astype(float)
    d["com"] = (d.group == "commute").astype(float)
    d["com_sy"] = d.com * d.sy
    X = pd.concat([d[["sy", "com", "com_sy"]], pd.get_dummies(d.group, prefix="g", drop_first=True, dtype=float).drop(columns="g_commute", errors="ignore"),
                   pd.get_dummies(d.year.astype(str), prefix="y", drop_first=True, dtype=float)], axis=1)
    X = sm.add_constant(X.drop(columns=[x for x in X.columns if x == "com"], errors="ignore"))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = sm.GLM(d.y, X, family=sm.families.Poisson(), offset=np.log(d.days)).fit(cov_type="HC1")
    sy, inter = m.params["sy"], m.params["com_sy"]
    tot = lambda g, s: float(c[(c.group == g) & (c.season == s)].y.sum())
    days = lambda g, s: float(c[(c.group == g) & (c.season == s)].days.sum())
    com_ratio = (tot("commute", "SY") / days("commute", "SY")) / max(tot("commute", "SU") / days("commute", "SU"), 1e-9)
    return {"commute_in_session": int(tot("commute", "SY")), "commute_summer": int(tot("commute", "SU")),
            "commute_rate_ratio": round(com_ratio, 1),
            "placebo_in_session": int(sum(tot(g, "SY") for g in control)), "placebo_summer": int(sum(tot(g, "SU") for g in control)),
            "placebo_rate_ratio": round(float(np.exp(sy)), 2),
            "commute_vs_placebo_ratio": round(float(np.exp(inter)), 2),
            "ci_low": round(float(np.exp(inter - 1.96 * m.bse["com_sy"])), 2), "ci_high": round(float(np.exp(inter + 1.96 * m.bse["com_sy"])), 2),
            "p": float(m.pvalues["com_sy"])}


def run(ev, shift=0, near=NEAR_M, control=PLACEBOS, label="") -> dict:
    e = classify(ev[ev.dist_m <= near], shift)
    r = fit(cells(e, calendar(shift)), control)
    return {"analysis": label, "near_m": near, **r}


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    RESULTS.mkdir(parents=True, exist_ok=True)
    ev = child_events()
    ev["dist_m"], n_schools = school_distance(ev.lat.values, ev.lon.values)
    log.info("%d child ped/bike injury crashes (surface); %d schools; %d within 400 m", len(ev), n_schools, int((ev.dist_m <= NEAR_M).sum()))
    cal = calendar(0)
    wd = cal[~cal.weekend].groupby("season").size().to_dict()
    print(f"eligible weekdays across the included years: in session {wd.get('SY')}, summer {wd.get('SU')}")
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)

    # per-group table (primary sample): counts and crashes per 100 days
    e = classify(ev[ev.dist_m <= NEAR_M], 0)
    c = cells(e, cal)
    t = c.groupby(["group", "season"]).agg(crashes=("y", "sum"), days=("days", "sum"))
    t["per_100_days"] = (100 * t.crashes / t.days).round(1)
    t = t.unstack("season")
    t.columns = [f"{a}_{b}" for a, b in t.columns]
    t["rate_ratio_session_vs_summer"] = (t.per_100_days_SY / t.per_100_days_SU).round(2)
    t.reset_index().to_csv(RESULTS / "school_test_rates.csv", index=False)
    print("\nNEAR-SCHOOL child pedestrian/bicyclist injury crashes (<=400 m), by time of day:\n", t.to_string())

    rows = [run(ev, label="PRIMARY: ages 5-17, <=400 m, all placebo hours")]
    rows += [run(ev, 7, label="sensitivity: windows tightened by 1 week each side"),
             run(ev, near=300, label="sensitivity: <= 300 m"), run(ev, near=600, label="sensitivity: <= 600 m"),
             run(ev[ev.age_max <= 11], label="sensitivity: ages 5-11"), run(ev[ev.age_min >= 12], label="sensitivity: ages 12-17"),
             run(ev[ev["mode"] == "Pedestrian"], label="sensitivity: pedestrians only"), run(ev[ev["mode"] == "Bicyclist"], label="sensitivity: bicyclists only"),
             run(ev[ev.year != 2022], label="sensitivity: drop 2022"), run(ev[ev.year != 2025], label="sensitivity: drop 2025 (provisional)"),
             run(ev[ev.year <= 2019], label="sensitivity: 2016-2020 only"), run(ev[ev.year >= 2022], label="sensitivity: 2022-2025 only"),
             run(ev, control=("midday",), label="control hours = midday only"), run(ev, control=("evening",), label="control hours = evening only"),
             run(ev, control=("weekend",), label="control hours = weekends only")]
    out = pd.DataFrame(rows)
    out.to_csv(RESULTS / "school_test_estimates.csv", index=False)
    print("\nCOMMUTE vs PLACEBO HOURS (ratio of the in-session/summer rate ratios):\n",
          out.drop(columns=["p"]).to_string(index=False))

    # dose-response by distance to the nearest school (commute hours only)
    bands = [(0, 200), (200, 400), (400, 800), (800, 1600), (1600, 1e9)]
    rows = []
    for lo, hi in bands:
        s = ev[(ev.dist_m > lo) & (ev.dist_m <= hi)] if lo else ev[ev.dist_m <= hi]
        ee = classify(s, 0)
        cc = cells(ee, cal)
        for g in ("commute", "midday"):
            x = cc[cc.group == g]
            sy, su = x[x.season == "SY"], x[x.season == "SU"]
            rows.append({"band_m": f"{lo}-{int(hi) if hi < 1e8 else 'more'}", "group": g, "in_session": int(sy.y.sum()), "summer": int(su.y.sum()),
                         "rate_ratio": round((sy.y.sum() / sy.days.sum()) / max(su.y.sum() / su.days.sum(), 1e-9), 1) if su.y.sum() else np.nan})
    dr = pd.DataFrame(rows)
    dr.to_csv(RESULTS / "school_test_by_distance.csv", index=False)
    print("\nBY DISTANCE TO NEAREST SCHOOL (crashes in session / in summer; rate ratio per day):\n", dr.to_string(index=False))

    # how many commute-hour crashes near schools are tied to the school day?
    cm = c[c.group == "commute"]
    sy_n, su_n, sy_d, su_d = cm[cm.season == "SY"].y.sum(), cm[cm.season == "SU"].y.sum(), cm[cm.season == "SY"].days.sum(), cm[cm.season == "SU"].days.sum()
    pl = c[c.group.isin(PLACEBOS)]
    seas = (pl[pl.season == "SY"].y.sum() / pl[pl.season == "SY"].days.sum()) / (pl[pl.season == "SU"].y.sum() / pl[pl.season == "SU"].days.sum())
    expected = su_n / su_d * sy_d * seas
    print(f"\nNear-school commute-hour crashes in session: {int(sy_n)}. At summer rates, scaled by the placebo-hours seasonal change ({seas:.2f}x), "
          f"about {expected:.0f} would be expected, so roughly {int(round(sy_n - expected))} ({100 * (sy_n - expected) / sy_n:.0f}%) are tied to the school day.")


if __name__ == "__main__":
    main()
