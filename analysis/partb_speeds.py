"""PART B, Q3 (preregistered, two-sided): do Alameda CTC's 2024 corridor speeds improve out-of-sample serious-crash prediction?

    python -m analysis.partb_speeds --match-only    # parse Appendix C and match to segments; prints match rates, NO crash outcomes
    python -m analysis.partb_speeds --selftest      # synthetic data only
    python -m analysis.partb_speeds                 # THE CONFIRMATORY RUN (run once, after the code tag)

Registered design (docs/OSF_REGISTRATION.md, Q3).
    speed       2024 "Sample Speed" (mph) from Alameda CTC 2024 CMP Appendix C, PM-peak tables (C-8 Tier 1 and C-10 Tier 2) as the
                primary measure; AM-peak tables (C-9, C-11) secondary. Each segment gets the length-weighted mean speed over all
                Appendix C rows with the same normalised street name and the same jurisdiction. No match = segment left out of Q3.
    sample      arterial segments (OSM primary, secondary, tertiary, trunk) with a speed value
    models      the existing segment Poisson model (analysis/model.py matrix(s, True), exposure offset, KSI outcome), fitted on the
                matched arterial segments, 2016-2022, without and with log(speed). Columns with no variation in the sample are dropped.
    test        2023-2025: (a) Poisson deviance, PRIMARY; (b) share of KSI on the top 5% of road length ranked by predicted rate.
                Also 5-fold spatial-block cross-validation (5 km cells held out) with the same two metrics.
    inference   street-resampled bootstrap, 2,000 draws, 95% percentile interval for (without minus with) deviance and (with minus without)
                capture. "Improves" = the primary interval excludes zero in the favourable direction. Two-sided: no direction is predicted.
Corridor names are normalised by dropping directions, street-type words, state-route labels and punctuation; both the parenthesised
alias ("SR 185 (International Blvd)") and each dash-separated name are used. No hand matching.
"""
from __future__ import annotations

import argparse
import logging
import re
import warnings

import numpy as np
import pandas as pd
import pymupdf
import statsmodels.api as sm
from sklearn.model_selection import GroupKFold

from alameda_traffic.config import REPO_ROOT

log = logging.getLogger("analysis.partb_speeds")
RESULTS = REPO_ROOT / "analysis" / "results"
PDF = REPO_ROOT / "data" / "manual" / "alamedactc_public" / "Appendix_C_LOS_Tables.pdf"
PAGES = {"PM": list(range(24, 33)) + list(range(42, 59)), "AM": list(range(33, 42)) + list(range(59, 76))}
DRAWS = 2000
ARTERIAL = {"primary", "secondary", "tertiary", "trunk"}
JURIS = {"DUB": "Dublin", "HAY": "Hayward", "UNI CTY": "Union City", "UNICTY": "Union City", "UNINC": "Unincorporated", "ALA": "Alameda",
         "ALB": "Albany", "BERK": "Berkeley", "EMERY": "Emeryville", "LIV": "Livermore", "FRE": "Fremont", "NEW": "Newark",
         "OAK": "Oakland", "PLEA": "Pleasanton", "SAN L": "San Leandro", "SANL": "San Leandro", "PIED": "Piedmont"}
INCORPORATED = {"Dublin", "Hayward", "Union City", "Alameda", "Albany", "Berkeley", "Emeryville", "Livermore", "Fremont", "Newark",
                "Oakland", "Pleasanton", "San Leandro", "Piedmont"}
DROP = {"ST", "STREET", "AVE", "AV", "AVENUE", "BLVD", "BL", "BOULEVARD", "RD", "ROAD", "DR", "DRIVE", "WAY", "PKWY", "PARKWAY", "HWY",
        "HIGHWAY", "LN", "LANE", "CT", "COURT", "PL", "PLACE", "EXPY", "EXPRESSWAY", "CIR", "CIRCLE", "TER", "TERRACE", "SR", "US", "I",
        "NB", "SB", "EB", "WB", "N", "S", "E", "W", "NORTH", "SOUTH", "EAST", "WEST", "NORTHBOUND", "SOUTHBOUND", "EASTBOUND", "WESTBOUND"}


def norm_name(raw: str) -> str:
    s = re.sub(r"[.,'’]", " ", str(raw).upper())
    s = re.sub(r"\b(SR|I|US|ROUTE|HWY)[\s-]*\d+[A-Z]?\b", " ", s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    toks = [t for t in s.split() if t not in DROP]
    return " ".join(toks)


def route_aliases(route: str) -> set[str]:
    r = re.sub(r"\s+", " ", str(route).upper().replace("–", "-")).strip()
    names = re.findall(r"\(([^)]*)\)", r)
    r = re.sub(r"\([^)]*\)", " ", r)
    names += re.split(r"\s*-\s*|\s*/\s*", r)
    out = {norm_name(n) for n in names}
    return {n for n in out if len(n) >= 2}


def parse_appendix_c(period: str = "PM") -> pd.DataFrame:
    d = pymupdf.open(PDF)
    rows = []
    for pn in PAGES[period]:
        p = d[pn - 1]
        for t in p.find_tables().tables:
            for row in t.rows:
                cells = [p.get_text("text", clip=c).strip().replace("\n", " ") if c else "" for c in row.cells]
                if not cells or not re.match(r"^[AT]\d+$", cells[0]):
                    continue
                nz = [c for c in cells if c != ""]
                try:
                    speed = float(nz[-2])
                    length = float(cells[5])
                except (ValueError, IndexError):
                    continue
                j = JURIS.get(re.sub(r"\s+", " ", cells[4].upper()).strip())
                if j is None:
                    continue
                rows.append(dict(cmp_id=cells[0], route=cells[1], jurisdiction=j, length_mi=length, speed_2024=speed, period=period))
    return pd.DataFrame(rows)


def speed_table(period: str = "PM") -> pd.DataFrame:
    """(jurisdiction, normalised name) -> length-weighted mean 2024 sample speed."""
    t = parse_appendix_c(period)
    recs = []
    for r in t.itertuples():
        for a in route_aliases(r.route):
            recs.append((r.jurisdiction, a, r.length_mi, r.speed_2024 * r.length_mi))
    g = pd.DataFrame(recs, columns=["jurisdiction", "name_norm", "len", "wspeed"]).groupby(["jurisdiction", "name_norm"], as_index=False).sum()
    g["speed"] = g.wspeed / g.len
    return g[["jurisdiction", "name_norm", "speed", "len"]]


def attach_speed(s: pd.DataFrame, period: str = "PM") -> pd.DataFrame:
    tab = speed_table(period)
    s = s.copy()
    s["name_norm"] = s.name.fillna("").map(norm_name)
    s["jurisdiction"] = np.where(s.place.isin(INCORPORATED), s.place, "Unincorporated")
    s = s.merge(tab[["jurisdiction", "name_norm", "speed"]], on=["jurisdiction", "name_norm"], how="left")
    return s


# --------------------------------------------------------------------------- evaluation
def deviance_terms(y, mu):
    y = np.asarray(y, float)
    mu = np.maximum(np.asarray(mu, float), 1e-9)
    with np.errstate(divide="ignore", invalid="ignore"):
        t = np.where(y > 0, y * np.log(y / mu), 0.0)
    return 2 * (t - (y - mu))


def capture_w(score, y, miles, w, frac=0.05):
    order = np.argsort(-score, kind="stable")
    cum = np.cumsum((w * miles)[order])
    k = int(np.searchsorted(cum, frac * cum[-1])) + 1
    return float((w * y)[order[:k]].sum() / max((w * y).sum(), 1e-9))


def fit_rate(X, y, expo, Xnew):
    Z = sm.add_constant(X, has_constant="add")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = sm.GLM(y, Z, family=sm.families.Poisson(), offset=np.log(expo)).fit(maxiter=200)
    Zn = sm.add_constant(Xnew, has_constant="add")
    return np.exp(np.asarray(Zn) @ np.asarray(m.params))


def compare(X, speed, y_tr, y_te, miles, ty, ey, cell, street, rng, draws=DRAWS):
    """X: base features (DataFrame), speed: mph array. Returns table of metrics with and without log speed."""
    X = X.loc[:, X.nunique() > 1].astype(float)
    XB = X.assign(log_speed=np.log(speed))
    out = {}
    for tag, XX in (("without", X), ("with", XB)):
        out[tag] = {"temporal": fit_rate(XX, y_tr, miles * ty, XX)}
        rate_cv = np.zeros(len(XX))
        for tr_i, te_i in GroupKFold(5).split(XX, groups=cell):
            rate_cv[te_i] = fit_rate(XX.iloc[tr_i], y_tr[tr_i], miles[tr_i] * ty, XX.iloc[te_i])
        out[tag]["spatial"] = rate_cv
    cl, ncl = pd.factorize(street)[0], pd.factorize(street)[1].size
    W = [np.bincount(rng.integers(0, ncl, ncl), minlength=ncl)[cl].astype(float) for _ in range(draws)]
    W = np.vstack([np.ones(len(miles))] + W)                       # row 0 = point estimate
    rows = []
    for kind in ("temporal", "spatial"):
        mu = {t: out[t][kind] * miles * ey for t in out}
        dev = {t: W @ deviance_terms(y_te, mu[t]) for t in out}
        cap = {t: np.array([capture_w(out[t][kind], y_te, miles, w) for w in W]) for t in out}
        dd = dev["without"] - dev["with"]                         # positive = speed helps
        dc = cap["with"] - cap["without"]
        for metric, arr, w_, wo_ in (("Poisson deviance (without - with; >0 means speed helps)", dd, dev["with"][0], dev["without"][0]),
                                      ("share of KSI on top 5% of length (with - without; >0 means speed helps)", dc, cap["with"][0], cap["without"][0])):
            lo, hi = np.percentile(arr[1:], [2.5, 97.5])
            rows.append(dict(evaluation=kind, metric=metric, without_speed=round(float(wo_), 4), with_speed=round(float(w_), 4),
                             difference=round(float(arr[0]), 4), ci_low=round(float(lo), 4), ci_high=round(float(hi), 4)))
    return pd.DataFrame(rows)


def selftest():
    rng = np.random.default_rng(3)
    n = 3000
    X = pd.DataFrame({"a": rng.normal(size=n), "b": rng.normal(size=n), "const": 1.0})
    speed = rng.uniform(15, 40, n)
    miles = rng.uniform(0.1, 0.3, n)
    mu = miles * np.exp(-1.0 + 0.3 * X.a + 0.04 * (speed - 27))        # speed truly matters
    y_tr, y_te = rng.poisson(mu * 7), rng.poisson(mu * 3)
    street = rng.integers(0, 600, n).astype(str)
    cell = rng.integers(0, 40, n).astype(str)
    r = compare(X, speed, y_tr.astype(float), y_te.astype(float), miles, 7, 3, cell, street, rng, draws=200)
    print(r.to_string(index=False))
    assert r.iloc[0].difference > 0, "speed should help the deviance in the synthetic data"
    assert "INTERNATIONAL" in route_aliases("SR 185 (International Blvd) - NB")
    assert "GRAND" in route_aliases("W.Grand Ave - Grand Ave -EB")
    print("selftest ok")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--match-only", action="store_true")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    if a.selftest:
        return selftest()
    from analysis.model import TE_Y, TR_Y, load, matrix
    s = load()
    for period in ("PM", "AM"):
        t = parse_appendix_c(period)
        log.info("%s: Appendix C rows parsed %d (%d routes)", period, len(t), t.route.nunique())
    s = attach_speed(s, "PM")
    arterial = s.cls.isin(ARTERIAL)
    matched = arterial & s.speed.notna()
    log.info("arterial segments %d; matched to a PM-peak speed %d (%.1f%%); arterial miles matched %.1f%%", arterial.sum(), matched.sum(),
             100 * matched.sum() / arterial.sum(), 100 * s.miles[matched].sum() / s.miles[arterial].sum())
    log.info("matched by jurisdiction:\n%s", s[matched].jurisdiction.value_counts().to_string())
    s[matched][["segment_id", "name", "jurisdiction", "speed"]].to_csv(RESULTS / "partb_speeds_matched_segments.csv", index=False)
    if a.match_only:
        return
    sub = s[matched].reset_index(drop=True)
    X = matrix(sub, True)
    res = compare(X, sub.speed.values, sub.ksi_tr.values.astype(float), sub.ksi_te.values.astype(float), sub.miles.values, TR_Y, TE_Y,
                  sub.cell.values, sub.street.values, np.random.default_rng(20260516))
    res.insert(0, "sample", f"{len(sub)} matched arterial segments, PM-peak 2024 speed")
    res.to_csv(RESULTS / "partb_speeds_results.csv", index=False)
    pd.set_option("display.width", 250, "display.max_columns", 20, "display.max_colwidth", 80)
    print(res.to_string(index=False))
    pr = res[(res.evaluation == "temporal")].iloc[0]
    print(f"\nQ3 primary (temporal deviance, without - with): {pr.difference} (95% {pr.ci_low} to {pr.ci_high}) -> "
          f"{'speed improves prediction' if pr.ci_low > 0 else ('speed worsens prediction' if pr.ci_high < 0 else 'no detectable difference')}")


if __name__ == "__main__":
    main()
