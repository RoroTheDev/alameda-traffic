"""Segment-level crash frequency models, a binary severity model, and an Empirical Bayes ranking.

    python -m analysis.model            # after analysis.segments and analysis.features

INPUTS  one row per quarter-mile segment: road class, traffic volume (HPMS), lanes, intersections,
        signals, crossings, calming, sidewalk/bike tags, schools, hospitals, bus stops, density,
        jobs, commute shares, equity, income, Oakland bike lanes, city (optional). No crash history.
OUTPUTS expected crashes per segment per year for: injury+fatal crashes, killed/seriously injured
        (KSI) crashes, pedestrian+bicycle injury crashes; plus an Empirical Bayes (EB) version that
        blends the model with the segment's own history (the ranking used for allocation).

MODELS  count models with an exposure offset (segment miles x years), not binary:
          GLM    Poisson regression (rate per mile-year); overdispersion handled in EB via NB alpha
          GBM    gradient boosting with a Poisson loss (target = rate, weight = exposure)
        each with and without city as an input. The one binary model is SEVERITY: logistic regression
        for P(KSI | injury crash) on segment traits; two-part expected KSI = injury x P(severe).
        Baselines: past-crash ranking, road class alone.

EVALUATION (outcomes are 2023-2025; training uses 2016-2022 only)
  temporal     fit on all segments, test forward in time
  spatial      5-fold, whole 5 km grid cells held out AND forward in time (no leakage across space or time)
Metric: share of 2023-25 crashes on the top 5% / 10% of road LENGTH ranked by predicted rate (the same
length-matched yardstick as docs/NETWORK_TEST.md), rank correlation, Poisson deviance, calibration.
Hyperparameters are fixed (no tuning on the test years).
"""
from __future__ import annotations

import logging
import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm
import geopandas as gpd
from scipy.stats import spearmanr
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold
from sklearn.preprocessing import StandardScaler

from alameda_traffic.config import PROCESSED, REPO_ROOT
from alameda_traffic.provenance import log_pull

log = logging.getLogger("analysis.model")
RESULTS = REPO_ROOT / "analysis" / "results"
TRAIN, TEST = (2016, 2022), (2023, 2025)
TR_Y, TE_Y = TRAIN[1] - TRAIN[0] + 1, TEST[1] - TEST[0] + 1
FRACS = (0.05, 0.10)
ARTERIAL = {"primary", "secondary", "tertiary", "trunk"}
NUM = ["log_aadt", "lanes", "n_intersections", "end_signals", "log_crossings", "log_marked", "calming", "log_school_enroll",
       "log_school_dist", "log_hospital_dist", "snf_400m", "log_bus", "log_density", "log_jobs", "ces", "epc_i", "walk_share",
       "bike_share", "transit_share", "zero_veh_share", "log_income", "poverty_share"]
FLAGS = ["aadt_missing", "lanes_missing", "sidewalk_known", "sidewalk_yes", "bike_known", "bike_lane", "bike_shared", "oakland_bike"]


def load() -> pd.DataFrame:
    A = PROCESSED / "analysis"
    g = gpd.read_parquet(A / "segments.parquet")
    mid = g.geometry.interpolate(0.5, normalized=True)
    s = pd.DataFrame(g.drop(columns="geometry")).merge(pd.read_parquet(A / "segment_features.parquet"), on="segment_id")
    s["x"], s["y"] = mid.x.values, mid.y.values
    p = pd.read_parquet(A / "segment_year.parquet")

    def per(col, yrs):
        return p[p.year.between(*yrs)].groupby("segment_id")[col].sum().reindex(s.segment_id, fill_value=0).values
    p["n_pb"] = p.n_ped_inj + p.n_bike_inj
    p["n_pbksi"] = p.n_ped_ksi + p.n_bike_ksi
    for tag, yrs in (("tr", TRAIN), ("te", TEST)):
        for c, name in (("n_inj", "inj"), ("n_ksi", "ksi"), ("n_pb", "pb"), ("n_pbksi", "pbksi")):
            s[f"{name}_{tag}"] = per(c, yrs)
    s["miles"] = s.length_m / 1609.344
    cls = s.osm_class.fillna("other").replace({"primary_link": "primary", "secondary_link": "secondary", "tertiary_link": "tertiary",
                                               "trunk_link": "trunk", "living_street": "residential"})
    s["cls"] = cls.where(cls.isin(ARTERIAL | {"residential", "unclassified"}), "other")
    s["aadt_missing"] = s.hpms_aadt.isna().astype(int)
    s["log_aadt"] = np.log(s.hpms_aadt.fillna(s.hpms_aadt.median()).clip(lower=1))
    lanes = s.hpms_lanes.fillna(s.osm_lanes)
    s["lanes_missing"] = lanes.isna().astype(int)
    s["lanes"] = lanes.fillna(lanes.median()).clip(upper=6)
    s["log_crossings"], s["log_marked"] = np.log1p(s.n_crossings), np.log1p(s.n_marked_crossings)
    s["calming"] = (s.n_calming > 0).astype(int)
    s["log_school_enroll"] = np.log1p(s.school_enroll_400m.fillna(0))
    s["log_school_dist"] = np.log(s.school_dist_m.fillna(5000) + 50)
    s["log_hospital_dist"] = np.log(s.hospital_dist_m.fillna(10000) + 50)
    s["log_bus"] = np.log1p(s.bus_stops_400m.fillna(0))
    s["log_density"] = np.log1p(s.pop_density_km2.fillna(s.pop_density_km2.median()))
    s["log_jobs"] = np.log1p(s.jobs_density_km2.fillna(0))
    s["ces"] = s.ces_pctl.fillna(s.ces_pctl.median()) / 100
    s["epc_i"] = s.epc.fillna(False).astype(int)
    s["log_income"] = np.log(s.median_income.fillna(s.median_income.median()).clip(lower=10000))
    for c in ("walk_share", "bike_share", "transit_share", "zero_veh_share", "poverty_share"):
        s[c] = s[c].fillna(s[c].median())
    s["oakland_bike"] = ((s.place == "Oakland") & (s.bike_projects > 0)).astype(int)
    for c in ("n_intersections", "end_signals", "snf_400m"):
        s[c] = s[c].fillna(0)
    top = s.groupby("place").miles.sum().sort_values(ascending=False).head(14).index
    s["city"] = s.place.where(s.place.isin(top), "other").fillna("unincorporated")
    s["street"] = s.name.fillna("seg" + s.segment_id.astype(str))
    s["cell"] = (np.floor(s.x / 5000).astype(int).astype(str) + "_" + np.floor(s.y / 5000).astype(int).astype(str))
    return s


def matrix(s: pd.DataFrame, city: bool) -> pd.DataFrame:
    X = s[NUM + FLAGS].astype(float).copy()
    X = pd.concat([X, pd.get_dummies(s.cls, prefix="cls", dtype=float).drop(columns="cls_residential", errors="ignore")], axis=1)
    if city:
        X = pd.concat([X, pd.get_dummies(s.city, prefix="city", dtype=float).drop(columns="city_other", errors="ignore")], axis=1)
    return X


def fit_glm(X, y, expo):
    Z = sm.add_constant(X, has_constant="add")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return sm.GLM(y, Z, family=sm.families.Poisson(), offset=np.log(expo)).fit(maxiter=200)


def fit_gbm(X, y, expo):
    m = HistGradientBoostingRegressor(loss="poisson", learning_rate=0.05, max_iter=300, max_leaf_nodes=12, min_samples_leaf=60,
                                      l2_regularization=2.0, random_state=0)
    return m.fit(X, y / expo, sample_weight=expo)


def predict_rate(kind, model, X):
    if kind == "glm":
        return np.asarray(np.exp(sm.add_constant(X, has_constant="add") @ model.params))
    return model.predict(X)


def nb_alpha(y, mu):
    return float(max(((y - mu) ** 2 - y).sum() / (mu ** 2).sum(), 0.01))


def eb_rate(rate_pred, y_tr, miles, alpha):
    mu = rate_pred * miles * TR_Y
    w = 1 / (1 + alpha * mu)
    return (w * mu + (1 - w) * y_tr) / (miles * TR_Y)


def capture(score, y, miles, frac, tie=None):
    tie = np.zeros(len(score)) if tie is None else tie
    order = np.lexsort((-tie, -score))
    cum = np.cumsum(miles[order])
    k = int(np.searchsorted(cum, frac * miles.sum())) + 1
    return float(y[order[:k]].sum() / max(y.sum(), 1))


def severity_fit(s, X, train_seg_mask):
    cs = pd.read_parquet(PROCESSED / "analysis" / "crash_segment.parquet")
    cr = pd.read_parquet(PROCESSED / "analysis" / "crashes.parquet", columns=["tims_case_id", "year", "ksi"])
    c = cr.merge(cs, on="tims_case_id")
    idx = pd.Series(np.arange(len(s)), index=s.segment_id)
    c["row"] = idx.reindex(c.segment_id).values
    tr = c[(c.year <= TRAIN[1]) & train_seg_mask[c.row.values]]
    sc = StandardScaler().fit(X)
    lr = LogisticRegression(C=0.5, max_iter=2000).fit(sc.transform(X.iloc[tr.row.values]), tr.ksi.astype(int))
    return lr, sc, c


def run_experiment(s, name, folds):
    """folds: list of (train_mask, test_mask) over segments; returns out-of-sample predictions."""
    n = len(s)
    pred = {}
    for outcome in ("inj", "ksi", "pb"):
        for k in ("glm", "gbm", "glm_city", "gbm_city"):
            pred[(outcome, k)] = np.full(n, np.nan)
    sev_p = np.full(n, np.nan)
    alphas = {}
    Xs = {False: matrix(s, False), True: matrix(s, True)}
    for fi, (trm, tem) in enumerate(folds):
        expo = (s.miles * TR_Y).values
        for outcome in ("inj", "ksi", "pb"):
            y = s[f"{outcome}_tr"].values.astype(float)
            for k in ("glm", "gbm", "glm_city", "gbm_city"):
                X = Xs["city" in k]
                if k.startswith("glm"):
                    m = fit_glm(X[trm], y[trm], expo[trm])
                    pred[(outcome, k)][tem] = predict_rate("glm", m, X[tem])
                    if k == "glm_city":
                        alphas[(outcome, fi)] = nb_alpha(y[trm], np.exp(np.log(expo[trm]) + (sm.add_constant(X[trm], has_constant="add") @ m.params)))
                else:
                    m = fit_gbm(X[trm], y[trm], expo[trm])
                    pred[(outcome, k)][tem] = predict_rate("gbm", m, X[tem])
        lr, sc, _ = severity_fit(s, Xs[True], trm)
        sev_p[tem] = lr.predict_proba(sc.transform(Xs[True][tem]))[:, 1]
    alpha = {o: float(np.mean([v for (oo, _), v in alphas.items() if oo == o])) for o in ("inj", "ksi", "pb")}
    log.info("%s: done (%d folds); NB alpha by outcome %s", name, len(folds), {k: round(v, 2) for k, v in alpha.items()})
    return pred, sev_p, alpha


def evaluate(s, pred, sev_p, alpha, label):
    miles = s.miles.values
    rows, store = [], {}
    hist = {o: s[f"{o}_tr"].values / (miles * TR_Y) for o in ("inj", "ksi", "pb")}
    for outcome, ycol in (("inj", "inj_te"), ("ksi", "ksi_te"), ("pb", "pbksi_te")):
        y = s[ycol].values.astype(float)
        methods = {}
        tie_inj = hist["inj"]
        methods["history (own past crashes)"] = (hist["ksi" if outcome == "ksi" else ("pb" if outcome == "pb" else "inj")], outcome != "pb")
        for k, nm in (("glm", "GLM"), ("gbm", "GBM"), ("glm_city", "GLM + city"), ("gbm_city", "GBM + city")):
            src = "ksi" if outcome == "ksi" else ("pb" if outcome == "pb" else "inj")
            methods[nm] = (pred[(src, k)], outcome != "pb")
        if outcome == "ksi":
            methods["GBM + city, via injury model"] = (pred[("inj", "gbm_city")], False)
            methods["two-part: GBM+city injury x severity"] = (pred[("inj", "gbm_city")] * sev_p, True)
            methods["two-part: GLM+city injury x severity"] = (pred[("inj", "glm_city")] * sev_p, True)
        src = "ksi" if outcome == "ksi" else ("pb" if outcome == "pb" else "inj")
        for k, nm in (("glm_city", "EB (GLM + city)"), ("gbm_city", "EB (GBM + city)")):
            methods[nm] = (eb_rate(pred[(src, k)], s[f"{src}_tr"].values, miles, alpha[src]), outcome != "pb")
        cls_rate = s.groupby("cls")[f"{src}_tr"].transform("sum") / s.groupby("cls")["miles"].transform("sum") / TR_Y
        methods["road class only"] = (cls_rate.values, outcome != "pb")
        for nm, (score, aligned) in methods.items():
            ok = ~np.isnan(score)
            sc, yy, mm = score[ok], y[ok], miles[ok]
            store[(outcome, nm)] = (score, y)
            r = {"evaluation": label, "outcome": {"inj": "injury crashes", "ksi": "KSI crashes", "pb": "ped+bike KSI"}[outcome],
                 "method": nm, "test_crashes": int(yy.sum())}
            for f in FRACS:
                r[f"captured_top{int(f * 100)}pct_length"] = round(capture(sc, yy, mm, f, tie_inj[ok]), 3)
            r["spearman"] = round(float(spearmanr(sc * mm, yy)[0]), 3)
            tot_pred = float((sc * mm * TE_Y).sum())
            r["pred_vs_obs"] = round(tot_pred / yy.sum(), 2) if (yy.sum() and aligned) else np.nan
            rows.append(r)
    return pd.DataFrame(rows), store


def boot_pairs(store, s, label, n=1000, seed=0):
    """Paired bootstrap over segments: difference in captured share between two rankings (rankings held fixed)."""
    miles = s.miles.values
    tie = s.inj_tr.values / (miles * TR_Y)
    pairs = [("ksi", "EB (GBM + city)", "history (own past crashes)"), ("ksi", "GBM + city", "history (own past crashes)"),
             ("ksi", "GBM + city", "GLM + city"), ("ksi", "GBM + city", "road class only"),
             ("pb", "EB (GBM + city)", "history (own past crashes)"), ("pb", "GBM + city", "road class only"),
             ("inj", "GBM + city", "road class only"), ("inj", "EB (GBM + city)", "history (own past crashes)")]
    rng = np.random.default_rng(seed)
    rows = []
    for outcome, a, b in pairs:
        sa, y = store[(outcome, a)]
        sb, _ = store[(outcome, b)]
        for f in FRACS:
            def mask(sc):
                order = np.lexsort((-tie, -sc))
                k = int(np.searchsorted(np.cumsum(miles[order]), f * miles.sum())) + 1
                m = np.zeros(len(sc), bool)
                m[order[:k]] = True
                return m
            ma, mb = mask(sa), mask(sb)
            d = np.empty(n)
            for i in range(n):
                w = np.bincount(rng.integers(0, len(y), len(y)), minlength=len(y)).astype(float)
                d[i] = (w * y * ma).sum() / (w * y).sum() - (w * y * mb).sum() / (w * y).sum()
            lo, hi = np.percentile(d, [2.5, 97.5])
            rows.append({"evaluation": label, "outcome": outcome, "A": a, "B": b, "budget": f"top {int(f * 100)}% of length",
                         "A_minus_B": round((y * ma).sum() / y.sum() - (y * mb).sum() / y.sum(), 3), "ci_low": round(lo, 3), "ci_high": round(hi, 3)})
    return pd.DataFrame(rows)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    RESULTS.mkdir(parents=True, exist_ok=True)
    s = load()
    n = len(s)
    allm = np.ones(n, bool)
    log.info("%d segments; train outcome totals inj %d ksi %d; test inj %d ksi %d", n, s.inj_tr.sum(), s.ksi_tr.sum(), s.inj_te.sum(), s.ksi_te.sum())

    pred_t, sev_t, alpha_t = run_experiment(s, "temporal", [(allm, allm)])
    res_t, store_t = evaluate(s, pred_t, sev_t, alpha_t, "temporal holdout (train 2016-22, test 2023-25)")

    gkf = GroupKFold(n_splits=5)
    folds = []
    for tr_i, te_i in gkf.split(np.zeros(n), groups=s.cell.values):
        trm, tem = np.zeros(n, bool), np.zeros(n, bool)
        trm[tr_i], tem[te_i] = True, True
        folds.append((trm, tem))
    pred_s, sev_s, alpha_s = run_experiment(s, "spatial", folds)
    res_s, store_s = evaluate(s, pred_s, sev_s, alpha_s, "spatial blocks + forward in time")
    boot = pd.concat([boot_pairs(store_t, s, "temporal"), boot_pairs(store_s, s, "spatial + temporal")], ignore_index=True)
    boot.to_csv(RESULTS / "model_bootstrap.csv", index=False)

    res = pd.concat([res_t, res_s], ignore_index=True)
    res.to_csv(RESULTS / "model_metrics.csv", index=False)
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 20); pd.set_option("display.max_rows", 200)
    for ev in res.evaluation.unique():
        print(f"\n=== {ev} ===")
        for oc in res.outcome.unique():
            print(f"\n{oc}:")
            print(res[(res.evaluation == ev) & (res.outcome == oc)].drop(columns=["evaluation", "outcome"]).to_string(index=False))

    print("\nPAIRED COMPARISONS (A minus B, share of 2023-25 crashes; 95% bootstrap interval):")
    print(boot.to_string(index=False))

    # severity model quality (binary): AUC on 2023-25 crashes using the temporal fit
    lr, sc, c = severity_fit(s, matrix(s, True), allm)
    te = c[c.year >= TEST[0]]
    p = lr.predict_proba(sc.transform(matrix(s, True).iloc[te.row.values]))[:, 1]
    print(f"\nSEVERITY (binary): P(KSI | injury crash), 2023-25 crashes {len(te):,}: base rate {te.ksi.mean():.3f}; AUC {roc_auc_score(te.ksi, p):.3f}")

    # coefficient tables (full-period fit, cluster-robust SEs by street)
    X = matrix(s, False)
    for outcome in ("inj", "ksi"):
        y = (s[f"{outcome}_tr"] + s[f"{outcome}_te"]).values.astype(float)
        expo = (s.miles * (TR_Y + TE_Y)).values
        Z = sm.add_constant(X, has_constant="add")
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            mc = sm.GLM(y, Z, family=sm.families.Poisson(), offset=np.log(expo)).fit(cov_type="cluster", cov_kwds={"groups": pd.factorize(s.street)[0]})
        t = pd.DataFrame({"IRR": np.exp(mc.params), "ci_low": np.exp(mc.params - 1.96 * mc.bse), "ci_high": np.exp(mc.params + 1.96 * mc.bse), "p": mc.pvalues}).round(3)
        t.to_csv(RESULTS / f"model_irr_{outcome}.csv")

    # final predictions for ranking/allocation: fit on all ten years
    expo = (s.miles * (TR_Y + TE_Y)).values
    Xc = matrix(s, True)
    out = pd.DataFrame({"segment_id": s.segment_id.values})
    for outcome in ("inj", "ksi", "pb"):
        y = (s[f"{outcome}_tr"] + s[f"{outcome}_te"]).values.astype(float)
        mg = fit_glm(Xc, y, expo)
        glm_rate = np.asarray(np.exp(sm.add_constant(Xc, has_constant="add") @ mg.params))
        gb_rate = fit_gbm(Xc, y, expo).predict(Xc)
        alpha = nb_alpha(y, glm_rate * expo)
        out[f"{outcome}_per_yr_glm"], out[f"{outcome}_per_yr_gbm"] = glm_rate * s.miles.values, gb_rate * s.miles.values
        w = 1 / (1 + alpha * glm_rate * expo)
        out[f"{outcome}_per_yr_eb"] = (w * glm_rate * expo + (1 - w) * y) / (TR_Y + TE_Y)
    out.to_parquet(PROCESSED / "analysis" / "model_predictions.parquet", index=False)
    log_pull("analysis", "model_predictions", out_path=PROCESSED / "analysis" / "model_predictions.parquet", rows_out=len(out),
             note="expected crashes per segment-year, fit on 2016-2025; built by analysis/model.py")


if __name__ == "__main__":
    main()
