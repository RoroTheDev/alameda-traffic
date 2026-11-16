"""PART B, H2 (preregistered): does model-based allocation beat raw-history allocation on new train/test splits?

    python -m analysis.partb_allocation_splits --validate     # reproduces the ALREADY-SEEN 2022 split (Part A); not confirmatory
    python -m analysis.partb_allocation_splits                # THE CONFIRMATORY RUN: splits 2020/2021 (run once, after the code tag)

Registered design (docs/OSF_REGISTRATION.md, B2).
    splits      train 2016-2020 / test 2021-2023;  train 2016-2021 / test 2022-2024   (the 2016-2022 / 2023-2025 split is Part A)
    budgets     $1M, $5M, $15M, $50M, base treatment costs (assumptions; see analysis/allocate.py)
    strategies  model-based (Empirical Bayes, fitted on the training years only) optimisation; optimisation on raw training-period
                counts; plus exploratory: optimisation within the High-Injury Network only, within the Proactive Safety Network only
    scoring     realised KSI avoided per year in the test years (CRF x observed KSI of the type each treatment addresses)
    uncertainty 2,000 bootstrap draws resampling whole streets; all strategies rescored on each draw (paired); percentile 95% intervals
    H2a         at $15M and $50M, the model / raw-history ratio has its lower bound above 1, in BOTH new splits
    H2b         NOT confirmatory (see below): HIN-only vs unrestricted is reported as exploratory only

Why H2b is exploratory. Alameda CTC's 2024 High-Injury Network was built on crashes from 2018-2022. In the 2020 and 2021 training
splits the test years (2021-23, 2022-24) overlap the years the network was built from, so the network has seen the outcomes it is
scored on. That look-ahead favours the network, so the comparison is not a fair test. The PSN uses no crash data.
Nothing here uses the segment-level HIN or PSN files except as flags in local, restricted storage; only summaries are written.
"""
from __future__ import annotations

import argparse
import logging

import numpy as np
import pandas as pd
import statsmodels.api as sm

from alameda_traffic.config import PROCESSED, REPO_ROOT, RESTRICTED
from analysis.allocate import BUDGETS, TREATMENTS, candidates, eligibility, expected, solve
from analysis.model import fit_glm, load, matrix, nb_alpha

log = logging.getLogger("analysis.partb_allocation_splits")
RESULTS = REPO_ROOT / "analysis" / "results"
DRAWS = 2000
SPLITS = {"2020/2021-23": ((2016, 2020), (2021, 2023)), "2021/2022-24": ((2016, 2021), (2022, 2024))}
VALIDATE = {"2022/2023-25 (Part A, already seen)": ((2016, 2022), (2023, 2025))}


def period_counts(s: pd.DataFrame, years: tuple[int, int]) -> dict[str, np.ndarray]:
    p = pd.read_parquet(PROCESSED / "analysis" / "segment_year.parquet")
    p = p[p.year.between(*years)].copy()
    p["n_pb"] = p.n_ped_inj + p.n_bike_inj
    p["n_pbksi"] = p.n_ped_ksi + p.n_bike_ksi
    g = p.groupby("segment_id")[["n_inj", "n_ksi", "n_pb", "n_pbksi"]].sum().reindex(s.segment_id, fill_value=0)
    return {"inj": g.n_inj.values.astype(float), "ksi": g.n_ksi.values.astype(float), "pb": g.n_pb.values.astype(float),
            "pbksi": g.n_pbksi.values.astype(float)}


def eb_expected(s, train, ty):
    miles = s.miles.values
    Xc = matrix(s, True)
    out = {}
    for o in ("inj", "ksi", "pb"):
        y = train[o]
        expo = miles * ty
        m = fit_glm(Xc, y, expo)
        rate = np.asarray(np.exp(sm.add_constant(Xc, has_constant="add") @ m.params))
        mu = rate * expo
        alpha = nb_alpha(y, mu)
        w = 1 / (1 + alpha * mu)                       # same Empirical Bayes weight as analysis/model.py eb_rate
        out[o] = (w * mu + (1 - w) * y) / ty
    return out


def run_split(s, elig, net, name, tr_years, te_years, rng):
    ty, ey = tr_years[1] - tr_years[0] + 1, te_years[1] - te_years[0] + 1
    tr, te = period_counts(s, tr_years), period_counts(s, te_years)
    eb = eb_expected(s, tr, ty)
    eb_exp = expected(s, "eb", eb["ksi"], eb["inj"], eb["pb"])
    hist_exp = expected(s, "hist", tr["ksi"] / ty, tr["inj"] / ty, tr["pb"] / ty)
    real = {"all_ksi": te["ksi"] / ey, "pb_ksi": te["pbksi"] / ey}
    ce, ch = candidates(s, elig, eb_exp, 1.0), candidates(s, elig, hist_exp, 1.0)
    crf = ce.t.map({t["id"]: t["crf"] for t in TREATMENTS}).values
    tgt = ce.t.map({t["id"]: t["target"] for t in TREATMENTS}).values
    val = crf * np.where(tgt == "all", real["all_ksi"][ce.row.values], real["pb_ksi"][ce.row.values])
    on_hin = net.HIN_2024.values[ce.row.values].astype(bool)
    on_psn = net.PSN_2024.values[ce.row.values].astype(bool)
    key = np.where(s.name.isna(), "seg" + s.segment_id.astype(str), s.street.astype(str) + "|" + s.city.astype(str))
    cl, ncl = pd.factorize(key)[0], pd.factorize(key)[1].size
    cl_c = cl[ce.row.values]
    W = np.vstack([np.bincount(rng.integers(0, ncl, ncl), minlength=ncl)[cl_c].astype(float) for _ in range(DRAWS)])
    rows, ratios = [], []
    for B in BUDGETS:
        sel = {"model (EB)": solve(ce, B, "ksi_avoided").astype(float), "raw history": solve(ch, B, "ksi_avoided").astype(float)}
        for nm, flag in (("HIN-only [exploratory: look-ahead]", on_hin), ("PSN-only [exploratory]", on_psn)):
            x = np.zeros(len(ce))
            sub = ce[flag].reset_index(drop=True)
            x[np.flatnonzero(flag)[solve(sub, B, "ksi_avoided")]] = 1.0
            sel[nm] = x
        point = {k: float((v * val).sum()) for k, v in sel.items()}
        draws = {k: W @ (v * val) for k, v in sel.items()}
        for k, d in draws.items():
            lo, hi = np.percentile(d, [2.5, 97.5])
            rows.append(dict(split=name, budget=B, strategy=k, realised_ksi_avoided_per_yr=round(point[k], 3), ci_low=round(lo, 3), ci_high=round(hi, 3),
                             spend=round(float((sel[k] * ce.cost.values).sum()))))
        for k in sel:
            if k == "model (EB)":
                continue
            r = draws["model (EB)"] / np.where(draws[k] > 0, draws[k], np.nan)
            lo, hi = np.nanpercentile(r, [2.5, 97.5])
            ratios.append(dict(split=name, budget=B, comparison=f"model (EB) / {k}", ratio=round(point["model (EB)"] / point[k], 2) if point[k] > 0 else np.nan,
                               ci_low=round(lo, 2), ci_high=round(hi, 2), draws_with_zero_denominator=int(np.isnan(r).sum())))
        log.info("%s budget %.0fM done", name, B / 1e6)
    return pd.DataFrame(rows), pd.DataFrame(ratios)


def verdict(ratios: pd.DataFrame, splits) -> str:
    """H2a: lower bound > 1 at both $15M and $50M in every new split."""
    ok = True
    lines = []
    for sp in splits:
        for B in (15e6, 50e6):
            r = ratios[(ratios.split == sp) & (ratios.budget == B) & (ratios.comparison == "model (EB) / raw history")].iloc[0]
            lines.append(f"  {sp} ${B/1e6:.0f}M: ratio {r.ratio} (95% {r.ci_low} to {r.ci_high})")
            ok &= bool(r.ci_low > 1)
    return ("H2a SUPPORTED" if ok else "H2a NOT SUPPORTED") + "\n" + "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--validate", action="store_true", help="run only the already-seen 2022 split, to check the code reproduces Part A")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    s = load()
    elig = eligibility(s)
    net = pd.read_parquet(RESTRICTED / "analysis" / "segment_networks.parquet").set_index("segment_id").reindex(s.segment_id)
    rng = np.random.default_rng(20260515)
    splits = VALIDATE if a.validate else SPLITS
    levels, ratios = [], []
    for name, (tr, te) in splits.items():
        lv, rt = run_split(s, elig, net, name, tr, te, rng)
        levels.append(lv)
        ratios.append(rt)
    lv, rt = pd.concat(levels), pd.concat(ratios)
    tag = "validate" if a.validate else "results"
    lv.to_csv(RESULTS / f"partb_allocation_splits_levels_{tag}.csv", index=False)
    rt.to_csv(RESULTS / f"partb_allocation_splits_ratios_{tag}.csv", index=False)
    pd.set_option("display.width", 220, "display.max_columns", 20, "display.max_rows", 200)
    print(lv.to_string(index=False))
    print()
    print(rt.to_string(index=False))
    if not a.validate:
        print("\n" + verdict(rt, list(splits)))


if __name__ == "__main__":
    main()
