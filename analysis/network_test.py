"""Does Alameda CTC's High-Injury Network (HIN) or Proactive Safety Network (PSN) capture later crashes?

    python -m analysis.network_test [--tol 20]

Method. A segment is "on" a network if at least half of its length lies within `tol` metres of
the network's lines. For each network we report the share of killed-or-seriously-injured (KSI)
crashes that fall on it, against the share of road length it covers, and against baselines that
cover the SAME road length (measured as the length of the flagged segments):

    history     segments ranked by a HIN-style severity score on the earlier period
                (10 per KSI crash, 5 per other injury crash), same modes as the outcome
    volume      arterials ranked by HPMS traffic volume (what a planner could do with no crash data)

Periods. HIN 2024 was built on TIMS 2018-2022 crashes, so 2023-2025 is out of sample for it
(2018-2022 is shown only as an in-sample check). The PSN uses no crash data, so both periods are
out of sample for it. The "history" baseline is always scored on 2018-2022 and tested on 2023-2025.
HIN is an *active transportation* network (pedestrian and bicycle crashes); the PSN is all modes.
Intervals are 95% bootstrap over segments. Networks are Alameda CTC's restricted files, so only
summary statistics are written to analysis/results/; per-segment flags stay in data/restricted/.
"""
from __future__ import annotations

import argparse
import logging

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely

from alameda_traffic.config import PROCESSED, REPO_ROOT, RESTRICTED, out_dir
from alameda_traffic.geocode import PROJ

log = logging.getLogger("analysis.network_test")
RESULTS = REPO_ROOT / "analysis" / "results"
IN_SAMPLE, HOLDOUT = (2018, 2022), (2023, 2025)
OUTCOMES = {  # label -> (segment_year column(s), description)
    "ped+bike KSI": ["n_ped_ksi", "n_bike_ksi"],
    "all-mode KSI": ["n_ksi"],
    "fatal": ["n_fatal"],
}


def flag_on(seg: gpd.GeoDataFrame, net: gpd.GeoDataFrame, tol: float, min_share: float = 0.5) -> np.ndarray:
    buf = shapely.union_all(net.to_crs(PROJ).geometry.buffer(tol).values)
    tree = shapely.STRtree(seg.geometry.values)
    cand = tree.query(buf, predicate="intersects")
    share = np.zeros(len(seg))
    inter = shapely.intersection(seg.geometry.values[cand], buf)
    share[cand] = shapely.length(inter) / seg.length_m.values[cand]
    return share >= min_share


def period_sum(panel: pd.DataFrame, cols: list[str], years: tuple[int, int]) -> pd.Series:
    p = panel[panel.year.between(*years)]
    return p.groupby("segment_id")[cols].sum().sum(axis=1)


def rank_until(score: np.ndarray, length: np.ndarray, target: float, tiebreak: np.ndarray) -> np.ndarray:
    order = np.lexsort((-tiebreak, -score))  # primary: score desc, then tiebreak desc
    keep = np.zeros(len(score), bool)
    cum = np.cumsum(length[order])
    keep[order[: int(np.searchsorted(cum, target)) + 1]] = True
    return keep


def capture(mask: np.ndarray, y: np.ndarray, w: np.ndarray | None = None) -> float:
    w = np.ones(len(y)) if w is None else w
    return float((w * y * mask).sum() / (w * y).sum())


def boot_diff(mask_a, mask_b, y, length, n=1000, seed=0):
    rng = np.random.default_rng(seed)
    out = np.empty((n, 3))
    for i in range(n):
        w = np.bincount(rng.integers(0, len(y), len(y)), minlength=len(y)).astype(float)
        out[i] = (capture(mask_a, y, w), capture(mask_b, y, w), capture(mask_a, y, w) - capture(mask_b, y, w))
    return np.percentile(out, [2.5, 97.5], axis=0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tol", type=float, default=20.0)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    A = PROCESSED / "analysis"
    seg = gpd.read_parquet(A / "segments.parquet")
    panel = pd.read_parquet(A / "segment_year.parquet")
    R = RESTRICTED / "alamedactc"
    nets = {"HIN 2024": gpd.read_file(R / "hin_2024.geojson"), "PSN 2024": gpd.read_file(R / "psn_2024_concept.geojson")}
    flags = {k: flag_on(seg, v, args.tol) for k, v in nets.items()}
    flags["HIN or PSN"] = flags["HIN 2024"] | flags["PSN 2024"]
    flags["HIN and PSN"] = flags["HIN 2024"] & flags["PSN 2024"]
    out_dir(RESTRICTED, "analysis")
    pd.DataFrame({"segment_id": seg.segment_id.values, **{k.replace(" ", "_"): v for k, v in flags.items()}}).to_parquet(
        RESTRICTED / "analysis" / "segment_networks.parquet", index=False)

    L = seg.length_m.values
    total_len = L.sum()
    aadt = seg.hpms_aadt.fillna(0).values
    rows = []
    for net, mask in flags.items():
        target = L[mask].sum()
        log.info("%s: %d segments, %.0f mi flagged (%.1f%% of road length)", net, mask.sum(), target / 1609.344, 100 * target / total_len)
        for oname, cols in OUTCOMES.items():
            mode = [c for c in cols]
            # history score on the earlier period, same modes as the outcome
            ksi_cols = cols
            inj_cols = {"n_ped_ksi": "n_ped_inj", "n_bike_ksi": "n_bike_inj", "n_ksi": "n_inj", "n_fatal": "n_ksi"}
            ksi_h = period_sum(panel, ksi_cols, IN_SAMPLE).reindex(seg.segment_id, fill_value=0).values
            inj_h = period_sum(panel, [inj_cols[c] for c in cols], IN_SAMPLE).reindex(seg.segment_id, fill_value=0).values
            hist_score = 10 * ksi_h + 5 * np.maximum(inj_h - ksi_h, 0)
            hist = rank_until(hist_score, L, target, aadt)
            vol = rank_until(np.where(seg.osm_class.isin(["primary", "secondary", "tertiary", "trunk"]), aadt, 0), L, target, aadt)
            for period, years in (("2023-2025 (out of sample)", HOLDOUT), ("2018-2022 (in sample for HIN)", IN_SAMPLE)):
                y = period_sum(panel, mode, years).reindex(seg.segment_id, fill_value=0).values.astype(float)
                if y.sum() == 0:
                    continue
                cap_net, cap_h, cap_v = capture(mask, y), capture(hist, y), capture(vol, y)
                holdout = years == HOLDOUT
                lo, hi = boot_diff(mask, hist, y, L) if holdout else (np.full(3, np.nan), np.full(3, np.nan))
                if not holdout:  # history ranks the same years it is scored on: trivially ~100%, not a comparison
                    cap_h = np.nan
                rows.append({"network": net, "outcome": oname, "period": period, "crashes": int(y.sum()),
                             "network_mi": round(target / 1609.344), "length_share": round(target / total_len, 4),
                             "captured": round(cap_net, 3), "lift": round(cap_net / (target / total_len), 1),
                             "history_baseline": round(cap_h, 3), "volume_baseline": round(cap_v, 3),
                             "net_minus_history": round(cap_net - cap_h, 3) if holdout else np.nan,
                             "diff_ci_low": round(lo[2], 3), "diff_ci_high": round(hi[2], 3)})
    res = pd.DataFrame(rows)
    RESULTS.mkdir(parents=True, exist_ok=True)
    res.to_csv(RESULTS / f"network_test_tol{int(args.tol)}m.csv", index=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    show = res[res.period.str.startswith("2023")]
    print(f"\nHOLDOUT 2023-2025, tolerance {args.tol:.0f} m (captured = share of that period's crashes on the network):")
    print(show.drop(columns=["period"]).to_string(index=False))
    print("\nIN-SAMPLE 2018-2022 (HIN was built on these years):")
    print(res[~res.period.str.startswith("2023")].drop(columns=["period"]).query("network != 'HIN and PSN'").to_string(index=False))


if __name__ == "__main__":
    main()
