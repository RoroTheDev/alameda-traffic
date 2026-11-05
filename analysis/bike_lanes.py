"""Part 3: did Oakland's completed bikeway projects change crashes on the streets they were built on?

    python -m analysis.bike_lanes

Data. Oakland's completed bikeway projects (YearDone) matched to quarter-mile street segments (a segment
counts as treated when a project covers at least half of it), and the 2016-2025 crash panel
(segment_year). Only Oakland: the project layer exists only for Oakland.

PRIMARY analysis (fixed before looking at results):
    treated   Oakland segments whose first (and only) completed project was finished in 2018-2022
    controls  Oakland segments with no completed bikeway project through 2025
    window    3 years before and 3 years after the project year (clipped to 2016-2025); the project year is dropped
    matching  within each project-year cohort, treated and control segments are put in cells of
              road class group x injury crashes in the pre window (0, 1, 2, 3-4, 5+) and each cell's
              controls are re-weighted to the treated count; this stops "built where crashes were high,
              then crashes fell back" from looking like an effect
    effect    ratio of change: (treated after / treated before) / (controls after / controls before),
              per-year rates; 95% interval from a cell-stratified bootstrap over segments (1,000 draws)
Everything else is a labelled check: no matching on prior crashes, controls that are bikeway streets built
later (2023-26), arterials only, dropping 2020-21, project types, and a year-by-year event study.

Reading it. This is a before/after comparison against similar streets, not a trial. Streets get bike lanes
for reasons (often repaving, a street with riders, a planned corridor), and none of those are controlled.
There is no bike-volume data, so more riding after a project would raise bicyclist crashes even if risk per
rider fell. Spillover to nearby streets is ignored.
"""
from __future__ import annotations

import logging

import geopandas as gpd
import numpy as np
import pandas as pd

from alameda_traffic.config import PROCESSED, REPO_ROOT

log = logging.getLogger("analysis.bike_lanes")
RESULTS = REPO_ROOT / "analysis" / "results"
COHORTS = [2018, 2019, 2020, 2021, 2022]
Y0, Y1 = 2016, 2025
BOOT = 1000
CLASS = {"residential": "local", "living_street": "local", "unclassified": "collector", "tertiary": "collector",
         "tertiary_link": "collector", "secondary": "arterial", "secondary_link": "arterial", "primary": "arterial",
         "primary_link": "arterial", "trunk": "arterial"}
OUTCOMES = {"injury": "n_inj", "KSI": "n_ksi", "ped+bike injury": "ped_bike_inj", "bicyclist injury": "n_bike_inj",
            "pedestrian injury": "n_ped_inj", "ped+bike KSI": "ped_bike_ksi"}
RNG = np.random.default_rng(20260504)


def load():
    seg = gpd.read_parquet(PROCESSED / "analysis" / "segments.parquet")
    seg = seg[seg.place == "Oakland"].copy()
    seg["cls"] = seg.osm_class.map(CLASS)
    sy = pd.read_parquet(PROCESSED / "analysis" / "segment_year.parquet")
    sy["ped_bike_inj"] = sy.n_ped_inj + sy.n_bike_inj
    sy["ped_bike_ksi"] = sy.n_ped_ksi + sy.n_bike_ksi
    sy = sy[sy.segment_id.isin(seg.segment_id)]
    panel = {v: sy.pivot(index="segment_id", columns="year", values=v).reindex(seg.segment_id).fillna(0).values
             for v in set(OUTCOMES.values())}
    panel["inj_all"] = panel["n_inj"]
    return seg.reset_index(drop=True), panel


def typ(seg, which):
    t = seg.bike_types.fillna("")
    if which == "protected":
        return t.str.contains("buffered|separated|path")
    if which == "lanes":
        return t.eq("lanes")
    if which == "boulevard":
        return t.eq("boulevard")
    return pd.Series(True, index=seg.index)


def rates(arr, cohort):
    """per-year pre and post rates and the matching years, window cohort-3..cohort-1 / cohort+1..cohort+3."""
    yrs = np.arange(Y0, Y1 + 1)
    pre = (yrs >= cohort - 3) & (yrs < cohort)
    post = (yrs > cohort) & (yrs <= cohort + 3)
    return arr[:, pre].sum(1) / pre.sum(), arr[:, post].sum(1) / post.sum(), pre


def prebin(x, n_years):
    c = np.round(x * n_years)
    return np.select([c == 0, c == 1, c == 2, c <= 4], [0, 1, 2, 3], 4)


def build_cells(seg, panel, outcome, treated_mask, control_mask, *, match_pre=True, later=False, only=None):
    """list of cells: (treated pre, treated post, control pre, control post) arrays per cohort x class x pre-bin."""
    cells = []
    key = OUTCOMES[outcome]
    for c in COHORTS if only is None else only:
        if later:
            if c > 2020:
                continue
            ctrl = (seg.bike_first_year > min(c + 3, Y1)) & (seg.bike_first_year <= 2026) & control_mask
        else:
            ctrl = (seg.bike_projects == 0) & control_mask
        trt = treated_mask & (seg.bike_first_year == c) & (seg.bike_last_year == c)
        pre_inj, _, prew = rates(panel["inj_all"], c)
        npre = prew.sum()
        b = prebin(pre_inj, npre) if match_pre else np.zeros(len(seg), int)
        pre, post, _ = rates(panel[key], c)
        for cl in ("local", "collector", "arterial"):
            for bi in np.unique(b):
                m = (seg.cls == cl).values & (b == bi)
                t, k = np.where(m & trt.values)[0], np.where(m & ctrl.values)[0]
                if len(t) and len(k):
                    cells.append((c, pre[t], post[t], pre[k], post[k]))
    return cells


def estimate(cells):
    tp = sum(x[1].sum() for x in cells); tq = sum(x[2].sum() for x in cells)
    cp = sum(x[3].mean() * len(x[1]) for x in cells); cq = sum(x[4].mean() * len(x[1]) for x in cells)
    return (tq / tp) / (cq / cp) if tp > 0 and cp > 0 and cq > 0 and tq > 0 else np.nan, tp, tq, cp, cq


def boot(cells):
    out = []
    for _ in range(BOOT):
        tp = tq = cp = cq = 0.0
        for _, a, b, c, d in cells:
            i, j = RNG.integers(0, len(a), len(a)), RNG.integers(0, len(c), len(c))
            tp += a[i].sum(); tq += b[i].sum(); cp += c[j].mean() * len(a); cq += d[j].mean() * len(a)
        out.append((tq / tp) / (cq / cp) if min(tp, tq, cp, cq) > 0 else np.nan)
    return np.nanpercentile(out, [2.5, 97.5])


def run(name, seg, panel, outcome, *, treated=None, controls=None, **kw):
    treated = pd.Series(True, index=seg.index) if treated is None else treated
    controls = pd.Series(True, index=seg.index) if controls is None else controls
    cells = build_cells(seg, panel, outcome, treated, controls, **kw)
    if not cells:
        return None
    rr, tp, tq, cp, cq = estimate(cells)
    lo, hi = boot(cells)
    nt = sum(len(x[1]) for x in cells)
    return dict(analysis=name, outcome=outcome, n_treated=nt, treated_pre_per_yr=round(tp, 1), treated_post_per_yr=round(tq, 1),
                matched_control_pre_per_yr=round(cp, 1), matched_control_post_per_yr=round(cq, 1),
                ratio_of_change=round(rr, 2), ci_lo=round(lo, 2), ci_hi=round(hi, 2))


def event_study(seg, panel, outcome, match_pre):
    key, rows = OUTCOMES[outcome], []
    yrs = np.arange(Y0, Y1 + 1)
    acc = {k: [0.0, 0.0] for k in (-3, -2, -1, 1, 2, 3)}
    for c in [2019, 2020, 2021, 2022]:
        trt = ((seg.bike_first_year == c) & (seg.bike_last_year == c)).values
        ctl = (seg.bike_projects == 0).values
        pre_inj, _, prew = rates(panel["inj_all"], c)
        b = prebin(pre_inj, 3) if match_pre else np.zeros(len(seg), int)
        for cl in ("local", "collector", "arterial"):
            for bi in np.unique(b):
                m = (seg.cls == cl).values & (b == bi)
                t, k = np.where(m & trt)[0], np.where(m & ctl)[0]
                if not (len(t) and len(k)):
                    continue
                w = len(t) / len(k)
                for e in acc:
                    col = int(np.where(yrs == c + e)[0][0])
                    acc[e][0] += panel[key][t, col].sum()
                    acc[e][1] += panel[key][k, col].sum() * w
    pre_t = np.mean([acc[e][0] for e in (-3, -2, -1)]); pre_c = np.mean([acc[e][1] for e in (-3, -2, -1)])
    for e, (t, k) in acc.items():
        rows.append(dict(outcome=outcome, matched_on_prior_crashes=match_pre, event_year=e, treated_crashes=t,
                         control_crashes_reweighted=round(k, 1), ratio_vs_pre_mean=round((t / pre_t) / (k / pre_c), 2)))
    return rows


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    seg, panel = load()
    log.info("Oakland segments %d; with completed project 2018-22 (single): %d; never-treated controls %d", len(seg),
             int(((seg.bike_first_year.between(2018, 2022)) & (seg.bike_last_year == seg.bike_first_year)).sum()),
             int((seg.bike_projects == 0).sum()))
    res = []
    for o in OUTCOMES:
        res.append(run("PRIMARY: matched on prior crashes", seg, panel, o))
    for o in ("injury", "ped+bike injury", "KSI"):
        res.append(run("check: not matched on prior crashes", seg, panel, o, match_pre=False))
        res.append(run("check: controls = bikeway streets built later", seg, panel, o, later=True,
                       controls=pd.Series(True, index=seg.index)))
        res.append(run("check: arterials only", seg, panel, o, treated=seg.cls == "arterial", controls=seg.cls == "arterial"))
        res.append(run("check: collectors+locals only", seg, panel, o, treated=seg.cls != "arterial", controls=seg.cls != "arterial"))
        res.append(run("check: cohorts 2018-19 only", seg, panel, o, only=[2018, 2019]))
        res.append(run("check: cohorts 2021-22 only", seg, panel, o, only=[2021, 2022]))
        res.append(run("check: without 2020 cohort", seg, panel, o, only=[2018, 2019, 2021, 2022]))
    for tname in ("protected", "lanes", "boulevard"):
        for o in ("injury", "ped+bike injury"):
            res.append(run(f"type: {tname}", seg, panel, o, treated=typ(seg, tname)))
    res = pd.DataFrame([r for r in res if r])
    RESULTS.mkdir(parents=True, exist_ok=True)
    res.to_csv(RESULTS / "bike_lanes_results.csv", index=False)
    pd.set_option("display.width", 220, "display.max_columns", 20, "display.max_rows", 200)
    print(res.to_string(index=False))

    ev = pd.DataFrame(sum((event_study(seg, panel, o, m) for o in ("injury", "ped+bike injury") for m in (True, False)), []))
    ev.to_csv(RESULTS / "bike_lanes_event_study.csv", index=False)
    print("\nEvent study (ratio vs mean of the 3 pre years; cohorts 2019-22):")
    print(ev.to_string(index=False))


if __name__ == "__main__":
    main()
