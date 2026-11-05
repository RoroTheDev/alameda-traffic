"""Budget allocation DEMO: which segments get which safety fix to prevent the most serious crashes.

TREAT AS A DEMONSTRATION OF THE METHOD. The treatment costs are planning-level assumptions (no Alameda source),
so dollar amounts, benefit-cost ratios and absolute crashes avoided are not findings. The comparison between
strategies at equal spending is the usable part.

    python -m analysis.allocate

Problem. Given a budget B, choose at most ONE treatment per street segment to maximise the expected
number of killed-or-seriously-injured (KSI) crashes avoided per year, optionally requiring half the
money to go to equity-priority areas. A multiple-choice knapsack solved exactly with HiGHS (scipy).

Benefit of a treatment at a segment (Caltrans method, Local Roadway Safety Manual App. D):
    avoided per year = CRF x expected crashes of the crash type the treatment addresses
    $ benefit        = CRF x (KSI x $3,276,000 + other injuries x $153,413)       (2026 dollars)
"expected crashes" is the model's Empirical Bayes estimate (analysis/model.py), which the manual
endorses; Caltrans itself uses 3-5 years of raw counts.

TREATMENTS (CRF and life from Caltrans LRSM v1.8; COSTS ARE PLANNING-LEVEL ASSUMPTIONS, see docs/ALLOCATION.md)
    road diet (restripe)  R14   all crashes   CRF 35%  20 yr   $40k / mile    4+ lane arterial/collector, AADT <= 25,000, corridor >= 0.5 mi
    RRFB crossing         R38PB ped+bike      CRF 35%  20 yr   $50k / site     arterial/collector with a marked crossing, no signal at the ends
    raised crossing       R37PB ped+bike      CRF 35%  20 yr   $10k / site     collector/local street with a marked crossing, <= 2 lanes
Costs are scaled x0.5 and x2 as a sensitivity check. Bike lanes are left out: no sourced cost was found.

EVALUATION (honest, out of sample). Choices are made with information up to 2022 only (train-period EB
or raw 2016-22 counts); each strategy is then scored on what ACTUALLY happened in 2023-25
(avoided = CRF x observed crashes at the chosen segments). Strategies compared at equal spending:
    optimised (model EB) | optimised on raw history | worst-first by past KSI | HIN-first | PSN-first | random eligible
Alameda CTC's HIN/PSN lines are restricted, so only summary statistics are written out.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import scipy.sparse as sp
import statsmodels.api as sm
from scipy.optimize import Bounds, LinearConstraint, milp

from alameda_traffic.config import PROCESSED, REPO_ROOT, RESTRICTED
from analysis.model import TR_Y, TE_Y, eb_rate, fit_glm, load, matrix, nb_alpha

log = logging.getLogger("analysis.allocate")
RESULTS = REPO_ROOT / "analysis" / "results"
KA, OTHER = 3_276_000.0, 153_413.0          # Caltrans roadway KA cost; mean of B ($213k) and C ($121k) weighted by TIMS mix
PB_KSI_SHARE = 1453 / 10646                   # pedestrian/bicycle KSI share of their injury crashes (surface, 2016-25)
BUDGETS = [1e6, 5e6, 15e6, 50e6]
COST_SCALES = (0.5, 1.0, 2.0)
ARTERIAL = {"primary", "secondary", "tertiary"}

TREATMENTS = [
    dict(id="R14", name="Road diet (restripe)", target="all", crf=0.35, life=20, unit="mile", cost=40_000),
    dict(id="R38PB", name="RRFB crossing", target="pb", crf=0.35, life=20, unit="site", cost=50_000),
    dict(id="R37PB", name="Raised crossing", target="pb", crf=0.35, life=20, unit="site", cost=10_000),
]


def eligibility(s: pd.DataFrame) -> dict[str, np.ndarray]:
    arterial = s.cls.isin(ARTERIAL).values
    lanes_known = (s.lanes_missing == 0).values
    aadt_known = (s.aadt_missing == 0).values
    crossing = (s.n_marked_crossings > 0).values
    no_signal = (s.end_signals == 0).values
    diet = arterial & lanes_known & (s.lanes.values >= 4) & aadt_known & (s.hpms_aadt.fillna(1e9).values <= 25_000)
    # a road diet only makes sense along a corridor: keep it where the eligible length on one street is >= 0.5 mile
    key = s.street.where(~s.name.isna(), "seg" + s.segment_id.astype(str)) + "|" + s.city.astype(str)
    corridor = pd.Series(np.where(diet, s.miles.values, 0.0)).groupby(key.values).transform("sum").values
    diet &= corridor >= 0.5
    rrfb = arterial & crossing & no_signal
    raised = s.cls.isin(["tertiary", "residential", "unclassified"]).values & crossing & no_signal & (~lanes_known | (s.lanes.values <= 2))
    return {"R14": diet, "R38PB": rrfb, "R37PB": raised}


def expected(s: pd.DataFrame, mode: str, ksi_year, inj_year, pb_inj_year) -> dict[str, np.ndarray]:
    """per-segment expected crashes per year by target type."""
    pbk = pb_inj_year * PB_KSI_SHARE
    return {"all": dict(ksi=ksi_year, other=np.maximum(inj_year - ksi_year, 0)),
            "pb": dict(ksi=pbk, other=np.maximum(pb_inj_year - pbk, 0))}


def candidates(s, elig, exp, cost_scale=1.0) -> pd.DataFrame:
    rows = []
    for t in TREATMENTS:
        m = elig[t["id"]]
        idx = np.flatnonzero(m)
        cost = t["cost"] * cost_scale * (s.miles.values[idx] if t["unit"] == "mile" else 1.0)
        e = exp[t["target"]]
        rows.append(pd.DataFrame({"row": idx, "t": t["id"], "cost": cost, "ksi_avoided": t["crf"] * e["ksi"][idx],
                                  "dollar_benefit": t["crf"] * (e["ksi"][idx] * KA + e["other"][idx] * OTHER), "life": t["life"]}))
    return pd.concat(rows, ignore_index=True)


def solve(c: pd.DataFrame, budget: float, objective: str, epc: np.ndarray | None = None, epc_share: float = 0.0) -> np.ndarray:
    n = len(c)
    val = c[objective].values
    A = [sp.csr_matrix(c.cost.values[None, :])]
    lo, hi = [-np.inf], [budget]
    seg = pd.factorize(c.row)[0]
    A.append(sp.csr_matrix((np.ones(n), (seg, np.arange(n))), shape=(seg.max() + 1, n)))
    lo += [-np.inf] * (seg.max() + 1)
    hi += [1.0] * (seg.max() + 1)
    if epc is not None and epc_share > 0:
        # money in equity-priority areas >= share x total money:  sum((share - is_epc) x cost x x) <= 0
        A.append(sp.csr_matrix(((epc_share - epc[c.row.values].astype(float)) * c.cost.values)[None, :]))
        lo.append(-np.inf)
        hi.append(0.0)
    res = milp(c=-val, constraints=LinearConstraint(sp.vstack(A).tocsr(), lo, hi), integrality=np.ones(n), bounds=Bounds(0, 1),
               options={"time_limit": 120, "mip_rel_gap": 1e-4})
    return np.round(res.x).astype(bool) if res.x is not None else np.zeros(n, bool)


def greedy(c: pd.DataFrame, order: np.ndarray, budget: float) -> np.ndarray:
    """take candidates in the given order, at most one per segment, until the money runs out."""
    chosen, used, spent = np.zeros(len(c), bool), set(), 0.0
    for i in order:
        r = c.row.values[i]
        if r in used or spent + c.cost.values[i] > budget:
            continue
        chosen[i] = True
        used.add(r)
        spent += c.cost.values[i]
    return chosen


def score(c, chosen, real) -> dict:
    sel = c[chosen]
    out = {"segments": int(sel.row.nunique()), "spend": float(sel.cost.sum())}
    out["predicted_ksi_avoided_per_yr"] = float(sel.ksi_avoided.sum())
    # realized: apply each chosen treatment's CRF to what actually happened in 2023-25
    crf = sel.t.map({t["id"]: t["crf"] for t in TREATMENTS}).values
    tgt = sel.t.map({t["id"]: t["target"] for t in TREATMENTS}).values
    rk = np.where(tgt == "all", real["all_ksi"][sel.row.values], real["pb_ksi"][sel.row.values])
    ro = np.where(tgt == "all", real["all_other"][sel.row.values], real["pb_other"][sel.row.values])
    out["realized_ksi_avoided_per_yr"] = float((crf * rk).sum())
    out["realized_dollar_benefit_per_yr"] = float((crf * (rk * KA + ro * OTHER)).sum())
    life = sel.life.values
    out["realized_bcr"] = float((crf * (rk * KA + ro * OTHER) * life).sum() / sel.cost.sum()) if sel.cost.sum() else np.nan
    out["cost_per_ksi_avoided"] = float(sel.cost.sum() / ((crf * rk * life).sum())) if (crf * rk * life).sum() > 0 else np.nan
    return out


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    RESULTS.mkdir(parents=True, exist_ok=True)
    s = load()
    elig = eligibility(s)
    log.info("eligible segments: %s", {k: int(v.sum()) for k, v in elig.items()})
    miles = s.miles.values

    # --- information available at the end of 2022 (train-only) -------------------------------
    Xc = matrix(s, True)
    tr = {}
    for o in ("inj", "ksi", "pb"):
        y = s[f"{o}_tr"].values.astype(float)
        expo = miles * TR_Y
        m = fit_glm(Xc, y, expo)
        rate = np.asarray(np.exp(sm.add_constant(Xc, has_constant="add") @ m.params))
        tr[o] = eb_rate(rate, y, miles, nb_alpha(y, rate * expo)) * miles          # EB expected crashes per year
    eb_exp = expected(s, "eb", tr["ksi"], tr["inj"], tr["pb"])
    hist_exp = expected(s, "hist", s.ksi_tr.values / TR_Y, s.inj_tr.values / TR_Y, s.pb_tr.values / TR_Y)
    real = {"all_ksi": s.ksi_te.values / TE_Y, "all_other": (s.inj_te.values - s.ksi_te.values).clip(min=0) / TE_Y,
            "pb_ksi": s.pbksi_te.values / TE_Y, "pb_other": (s.pb_te.values - s.pbksi_te.values).clip(min=0) / TE_Y}
    real["all_other"] = (s.inj_te.values - s.ksi_te.values).clip(min=0) / TE_Y

    net = pd.read_parquet(RESTRICTED / "analysis" / "segment_networks.parquet").set_index("segment_id").reindex(s.segment_id)
    epc = s.epc_i.values.astype(bool)
    rng = np.random.default_rng(0)

    rows = []
    for scale in COST_SCALES:
        ce = candidates(s, elig, eb_exp, scale)           # candidates scored with model EB
        ch = candidates(s, elig, hist_exp, scale)         # same options scored with raw history
        assert (ce.row.values == ch.row.values).all()
        on_hin, on_psn = net.HIN_2024.values[ce.row.values], net.PSN_2024.values[ce.row.values]
        for B in BUDGETS:
            strat = {}
            strat["optimised: model (EB)"] = solve(ce, B, "ksi_avoided")
            strat["optimised: model (EB), $ benefit"] = solve(ce, B, "dollar_benefit")
            strat["optimised: model (EB), >=50% to equity areas"] = solve(ce, B, "ksi_avoided", epc, 0.5)
            strat["optimised: raw past crashes"] = solve(ch, B, "ksi_avoided")
            hist_ksi = ch.ksi_avoided.values
            strat["worst-first by past KSI"] = greedy(ce, np.lexsort((ce.cost.values, -hist_ksi)), B)
            for nm, flag in (("HIN-first (random within)", on_hin), ("PSN-first (random within)", on_psn)):
                vals = [score(ce, greedy(ce, np.lexsort((rng.random(len(ce)), ~flag.astype(bool))), B), real) for _ in range(40)]
                rows.append({"cost_scale": scale, "budget": B, "strategy": nm,
                             **{k: float(np.nanmean([v[k] for v in vals])) for k in vals[0]}})
            for nm, flag in (("optimised within HIN only", on_hin), ("optimised within PSN only", on_psn)):
                sub = ce[flag.astype(bool)].reset_index(drop=True)      # same optimiser, but only streets on the network
                rows.append({"cost_scale": scale, "budget": B, "strategy": nm, **score(sub, solve(sub, B, "ksi_avoided"), real)})
            vals = [score(ce, greedy(ce, rng.permutation(len(ce)), B), real) for _ in range(40)]
            rows.append({"cost_scale": scale, "budget": B, "strategy": "random eligible",
                         **{k: float(np.nanmean([v[k] for v in vals])) for k in vals[0]}})
            for nm, chosen in strat.items():
                rows.append({"cost_scale": scale, "budget": B, "strategy": nm, **score(ce, chosen, real)})
            if scale == 1.0 and B == 5e6:
                sel = ce[strat["optimised: model (EB)"]].copy()
                sel["treatment"] = sel.t.map({t["id"]: t["name"] for t in TREATMENTS})
                sel["street"] = s.name.values[sel.row.values]
                sel["city"] = s.city.values[sel.row.values]
                sel["segment_id"] = s.segment_id.values[sel.row.values]
                sel["realized_2023_25_ksi_per_yr_on_segment"] = real["all_ksi"][sel.row.values]
                sel.drop(columns=["row", "life"]).sort_values("ksi_avoided", ascending=False).to_csv(
                    PROCESSED / "analysis" / "allocation_5M_train_only.csv", index=False)
    res = pd.DataFrame(rows)
    res.round(4).to_csv(RESULTS / "allocation_results.csv", index=False)

    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 20)
    show = ["strategy", "segments", "spend", "predicted_ksi_avoided_per_yr", "realized_ksi_avoided_per_yr", "realized_bcr", "cost_per_ksi_avoided"]
    for B in BUDGETS:
        print(f"\n=== budget ${B / 1e6:.0f}M, base costs: realised = what 2023-25 crashes show would have been avoided ===")
        print(res[(res.budget == B) & (res.cost_scale == 1.0)][show].round(3).to_string(index=False))
    print("\nTreatment mix of the optimised-model solution (base cost):")
    for B in BUDGETS:
        c = candidates(s, elig, eb_exp, 1.0)
        ch = solve(c, B, "ksi_avoided")
        print(f"  ${B / 1e6:.0f}M:", c[ch].t.value_counts().to_dict(), "| eligible options", c.groupby("t").size().to_dict() if B == BUDGETS[0] else "")
    print("\nCost sensitivity (optimised model, realised KSI avoided per year):")
    print(res[res.strategy == "optimised: model (EB)"].pivot(index="budget", columns="cost_scale", values="realized_ksi_avoided_per_yr").round(3).to_string())


if __name__ == "__main__":
    main()
