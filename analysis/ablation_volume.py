"""EXPLORATORY ablation of the traffic-volume input (design: docs/ADDENDUM_ABLATIONS.md, written before running).

    python -m analysis.ablation_volume

Variants of analysis/model.py that differ only in the volume input:
  A  HPMS log(AADT) + missing flag (current)     B  AlaCC Model log(daily volume) + missing flag
  C  both                                        D  no volume              B-u  B incl. uncertain matches
Outputs (aggregate only; AlaCC volumes stay in data/restricted/):
  analysis/results/ablation_volume_metrics.csv, analysis/results/ablation_volume_boot.csv
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd
from sklearn.model_selection import GroupKFold

import analysis.model as M
from alameda_traffic.config import REPO_ROOT

log = logging.getLogger("analysis.ablation_volume")
RESTRICTED = REPO_ROOT / "data" / "restricted" / "analysis"
BASE_NUM = [c for c in M.NUM if c != "log_aadt"]
BASE_FLAGS = [c for c in M.FLAGS if c != "aadt_missing"]
VARIANTS = {
    "A: HPMS": (["log_aadt"], ["aadt_missing"]),
    "B: AlaCC": (["log_alacc"], ["alacc_missing"]),
    "C: both": (["log_aadt", "log_alacc"], ["aadt_missing", "alacc_missing"]),
    "D: no volume": ([], []),
    "B-u: AlaCC incl. uncertain": (["log_alacc_u"], ["alacc_u_missing"]),
}
FOCUS = ["GLM + city", "GBM + city", "EB (GLM + city)", "EB (GBM + city)"]
N_BOOT, SEED = 1000, 0


def add_alacc(s: pd.DataFrame) -> pd.DataFrame:
    a = pd.read_parquet(RESTRICTED / "segment_alacc.parquet",
                        columns=["segment_id", "alacc_vol_day", "alacc_vol_day_incl_uncertain", "alacc_status"])
    s = s.merge(a, on="segment_id", how="left", validate="one_to_one")
    v = s.alacc_vol_day.where(s.alacc_status == "ok")
    vu = s.alacc_vol_day_incl_uncertain.where(s.alacc_status.isin(["ok", "uncertain"]))
    for name, x in (("alacc", v), ("alacc_u", vu)):
        x = x.where(x > 0)
        s[f"{name}_missing"] = x.isna().astype(int)
        s[f"log_{name}"] = np.log(x.fillna(x.median()).clip(lower=1))
    return s


def deviance(score, y, miles):
    mu = np.clip(score * miles * M.TE_Y, 1e-9, None)
    t = np.where(y > 0, y * np.log(np.where(y > 0, y, 1) / mu), 0.0)
    return float(2 * (t - (y - mu)).sum())


def top_mask(score, miles, tie, frac):
    order = np.lexsort((-tie, -score))
    k = int(np.searchsorted(np.cumsum(miles[order]), frac * miles.sum())) + 1
    m = np.zeros(len(score), bool)
    m[order[:k]] = True
    return m


def extra_metrics(s, store, variant, label):
    miles, tie = s.miles.values, (s.inj_tr / (s.miles * M.TR_Y)).values
    art = s.cls.isin(M.ARTERIAL).values
    rows = []
    for (outcome, nm), (score, y) in store.items():
        if nm not in FOCUS:
            continue
        r = {"variant": variant, "evaluation": label, "outcome": outcome, "method": nm}
        if not nm.startswith("EB"):
            r["poisson_deviance"] = round(deviance(score, y, miles), 1)
            r["poisson_deviance_arterial"] = round(deviance(score[art], y[art], miles[art]), 1)
        for f in M.FRACS:
            r[f"arterial_captured_top{int(f * 100)}pct"] = round(M.capture(score[art], y[art], miles[art], f, tie[art]), 3)
        rows.append(r)
    return rows


def boot(s, stores, label):
    """Street-resampled paired differences vs variant A (rankings held fixed)."""
    miles, tie = s.miles.values, (s.inj_tr / (s.miles * M.TR_Y)).values
    street = pd.factorize(s.street)[0]
    ns = street.max() + 1
    rng = np.random.default_rng(SEED)
    W = np.stack([np.bincount(rng.integers(0, ns, ns), minlength=ns)[street].astype(float) for _ in range(N_BOOT)])
    rows = []
    for outcome in ("ksi", "pb", "inj"):
        for nm in ("EB (GBM + city)", "GBM + city", "EB (GLM + city)", "GLM + city"):
            sa, y = stores["A: HPMS"][(outcome, nm)]
            for v in VARIANTS:
                if v == "A: HPMS":
                    continue
                sb, _ = stores[v][(outcome, nm)]
                for f in M.FRACS:
                    ma, mb = top_mask(sa, miles, tie, f), top_mask(sb, miles, tie, f)
                    tot = W @ y
                    d = (W @ (y * mb) - W @ (y * ma)) / tot
                    lo, hi = np.percentile(d, [2.5, 97.5])
                    rows.append({"evaluation": label, "outcome": outcome, "method": nm, "variant_minus_A": v,
                                 "metric": f"captured top {int(f * 100)}% of length",
                                 "diff": round(((y * mb).sum() - (y * ma).sum()) / y.sum(), 4),
                                 "ci_low": round(lo, 4), "ci_high": round(hi, 4)})
                if not nm.startswith("EB"):
                    def segdev(sc):
                        mu = np.clip(sc * miles * M.TE_Y, 1e-9, None)
                        return 2 * (np.where(y > 0, y * np.log(np.where(y > 0, y, 1) / mu), 0.0) - (y - mu))
                    dd = segdev(sb) - segdev(sa)
                    bd = W @ dd
                    lo, hi = np.percentile(bd, [2.5, 97.5])
                    rows.append({"evaluation": label, "outcome": outcome, "method": nm, "variant_minus_A": v,
                                 "metric": "Poisson deviance (lower is better)", "diff": round(float(dd.sum()), 1),
                                 "ci_low": round(lo, 1), "ci_high": round(hi, 1)})
    return pd.DataFrame(rows)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    s = add_alacc(M.load())
    n = len(s)
    log.info("segments %d; HPMS present %.3f; AlaCC ok %.3f; AlaCC ok+uncertain %.3f; both %.3f", n, 1 - s.aadt_missing.mean(),
             1 - s.alacc_missing.mean(), 1 - s.alacc_u_missing.mean(), ((s.aadt_missing == 0) & (s.alacc_missing == 0)).mean())
    allm = np.ones(n, bool)
    folds = []
    for tr_i, te_i in GroupKFold(n_splits=5).split(np.zeros(n), groups=s.cell.values):
        trm, tem = np.zeros(n, bool), np.zeros(n, bool)
        trm[tr_i], tem[te_i] = True, True
        folds.append((trm, tem))
    evals = {"temporal": [(allm, allm)], "spatial + temporal": folds}

    metrics, extra, stores = [], [], {lab: {} for lab in evals}
    for v, (num, flags) in VARIANTS.items():
        M.NUM, M.FLAGS = BASE_NUM + num, BASE_FLAGS + flags
        for lab, fl in evals.items():
            pred, sev, alpha = M.run_experiment(s, f"{v} / {lab}", fl)
            res, store = M.evaluate(s, pred, sev, alpha, lab)
            res.insert(0, "variant", v)
            metrics.append(res[res.method.isin(FOCUS + ["history (own past crashes)", "road class only"])])
            extra += extra_metrics(s, store, v, lab)
            stores[lab][v] = store
    met = pd.concat(metrics, ignore_index=True)
    oc = {"injury crashes": "inj", "KSI crashes": "ksi", "ped+bike KSI": "pb"}
    met["outcome"] = met.outcome.map(oc)
    met = met.merge(pd.DataFrame(extra), on=["variant", "evaluation", "outcome", "method"], how="left")
    met.to_csv(M.RESULTS / "ablation_volume_metrics.csv", index=False)
    b = pd.concat([boot(s, stores[lab], lab) for lab in evals], ignore_index=True)
    b.to_csv(M.RESULTS / "ablation_volume_boot.csv", index=False)

    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 20); pd.set_option("display.max_rows", 400)
    cols = ["variant", "method", "captured_top5pct_length", "captured_top10pct_length", "arterial_captured_top5pct",
            "poisson_deviance", "poisson_deviance_arterial"]
    for lab in evals:
        for o in ("ksi", "pb", "inj"):
            print(f"\n=== {lab} / {o} ===")
            print(met[(met.evaluation == lab) & (met.outcome == o) & met.method.isin(FOCUS)][cols].to_string(index=False))
    print("\nPAIRED DIFFERENCES vs A (positive capture = better; negative deviance = better):")
    print(b.to_string(index=False))
    main_row = b[(b.evaluation == "temporal") & (b.outcome == "ksi") & (b.method == "EB (GBM + city)") &
                 (b.variant_minus_A == "B: AlaCC") & (b.metric == "captured top 5% of length")].iloc[0]
    verdict = "B better" if main_row.ci_low > 0 else ("A better" if main_row.ci_high < 0 else "no clear difference")
    print(f"\nMAIN COMPARISON (B - A, KSI, temporal, EB GBM+city, top 5%): {main_row['diff']:+.4f} "
          f"({main_row.ci_low:+.4f} to {main_row.ci_high:+.4f}) -> {verdict}")


if __name__ == "__main__":
    main()
