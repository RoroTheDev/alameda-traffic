"""Uncertainty for the allocation comparison (analysis/allocate.py), base costs only.

    python -m analysis.allocate_bootstrap

What is resampled. Each strategy's treatment list is chosen once, from information through 2022 (same as allocate.py).
What the bootstrap varies is the evaluation: the 2023-25 outcomes are resampled by street (a street and its segments
are drawn together, 2,000 draws), and every strategy is rescored on the same draw. So differences between strategies are
paired: "model-based optimisation avoids X% more KSI than raw-history optimisation" gets an interval that reflects how
few serious crashes there are in three years.
What it does not capture. Noise in the 2016-22 training data and the choice of split year (one split only); the treatment
costs and crash reduction factors (assumed inputs, not estimated). Random and network-first strategies are summarised by
how often each option was picked over 40 random orderings (their expected score).
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import statsmodels.api as sm

from alameda_traffic.config import RESTRICTED, REPO_ROOT
from analysis.allocate import (BUDGETS, TREATMENTS, candidates, eligibility, expected, greedy, solve)
from analysis.model import TE_Y, TR_Y, eb_rate, fit_glm, load, matrix, nb_alpha

log = logging.getLogger("analysis.allocate_bootstrap")
RESULTS = REPO_ROOT / "analysis" / "results"
DRAWS = 2000


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    s = load()
    elig = eligibility(s)
    miles = s.miles.values
    Xc = matrix(s, True)
    tr = {}
    for o in ("inj", "ksi", "pb"):
        y = s[f"{o}_tr"].values.astype(float)
        expo = miles * TR_Y
        m = fit_glm(Xc, y, expo)
        rate = np.asarray(np.exp(sm.add_constant(Xc, has_constant="add") @ m.params))
        tr[o] = eb_rate(rate, y, miles, nb_alpha(y, rate * expo)) * miles
    eb_exp = expected(s, "eb", tr["ksi"], tr["inj"], tr["pb"])
    hist_exp = expected(s, "hist", s.ksi_tr.values / TR_Y, s.inj_tr.values / TR_Y, s.pb_tr.values / TR_Y)
    real = {"all_ksi": s.ksi_te.values / TE_Y, "pb_ksi": s.pbksi_te.values / TE_Y}
    net = pd.read_parquet(RESTRICTED / "analysis" / "segment_networks.parquet").set_index("segment_id").reindex(s.segment_id)
    epc = s.epc_i.values.astype(bool)
    rng = np.random.default_rng(0)

    ce, ch = candidates(s, elig, eb_exp, 1.0), candidates(s, elig, hist_exp, 1.0)
    crf = ce.t.map({t["id"]: t["crf"] for t in TREATMENTS}).values
    tgt = ce.t.map({t["id"]: t["target"] for t in TREATMENTS}).values
    # realised KSI avoided per year, per candidate option
    val = crf * np.where(tgt == "all", real["all_ksi"][ce.row.values], real["pb_ksi"][ce.row.values])
    on_hin, on_psn = net.HIN_2024.values[ce.row.values].astype(bool), net.PSN_2024.values[ce.row.values].astype(bool)

    # clusters = streets (unnamed segments are their own cluster)
    key = np.where(s.name.isna(), "seg" + s.segment_id.astype(str), s.street.astype(str) + "|" + s.city.astype(str))
    cl, n_cl = pd.factorize(key)[0], pd.factorize(key)[1].size
    log.info("candidates %d; street clusters %d", len(ce), n_cl)
    cl_of_cand = cl[ce.row.values]

    def draw_weights():
        cnt = np.bincount(rng.integers(0, n_cl, n_cl), minlength=n_cl)
        return cnt[cl_of_cand].astype(float)

    W = np.vstack([draw_weights() for _ in range(DRAWS)])            # draws x candidates
    rows, paired = [], []
    for B in BUDGETS:
        sel = {}                                                       # strategy -> selection frequency per candidate
        sel["optimised: model (EB)"] = solve(ce, B, "ksi_avoided").astype(float)
        sel["optimised: model (EB), >=50% to equity areas"] = solve(ce, B, "ksi_avoided", epc, 0.5).astype(float)
        sel["optimised: raw past crashes"] = solve(ch, B, "ksi_avoided").astype(float)
        sel["worst-first by past KSI"] = greedy(ce, np.lexsort((ce.cost.values, -ch.ksi_avoided.values)), B).astype(float)
        for nm, flag in (("optimised within HIN only", on_hin), ("optimised within PSN only", on_psn)):
            x = np.zeros(len(ce))
            sub = ce[flag].reset_index(drop=True)
            x[np.flatnonzero(flag)[solve(sub, B, "ksi_avoided")]] = 1.0
            sel[nm] = x
        for nm, flag in (("HIN-first (random within)", on_hin), ("PSN-first (random within)", on_psn)):
            sel[nm] = np.mean([greedy(ce, np.lexsort((rng.random(len(ce)), ~flag)), B) for _ in range(40)], axis=0)
        sel["random eligible"] = np.mean([greedy(ce, rng.permutation(len(ce)), B) for _ in range(40)], axis=0)
        log.info("budget %.0fM solved", B / 1e6)
        point = {k: float((v * val).sum()) for k, v in sel.items()}
        draws = {k: W @ (v * val) for k, v in sel.items()}
        for k, d in draws.items():
            lo, hi = np.percentile(d, [2.5, 97.5])
            rows.append(dict(budget=B, strategy=k, realised_ksi_avoided_per_yr=round(point[k], 3), ci_low=round(lo, 3), ci_high=round(hi, 3),
                             spend=round(float((sel[k] * ce.cost.values).sum()), 0)))
        base = "optimised: model (EB)"
        for k in sel:
            if k == base:
                continue
            r = draws[base] / np.where(draws[k] > 0, draws[k], np.nan)
            lo, hi = np.nanpercentile(r, [2.5, 97.5])
            paired.append(dict(budget=B, comparison=f"{base} / {k}", ratio=round(point[base] / point[k], 2) if point[k] > 0 else np.nan,
                               ci_low=round(lo, 2), ci_high=round(hi, 2), share_of_draws_above_1=round(float(np.nanmean(r > 1)), 3)))
    res, pr = pd.DataFrame(rows), pd.DataFrame(paired)
    res.to_csv(RESULTS / "allocation_bootstrap_levels.csv", index=False)
    pr.to_csv(RESULTS / "allocation_bootstrap_ratios.csv", index=False)
    pd.set_option("display.width", 220, "display.max_columns", 20, "display.max_rows", 200)
    print(res.to_string(index=False))
    print()
    print(pr.to_string(index=False))


if __name__ == "__main__":
    main()
