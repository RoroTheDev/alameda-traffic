"""Does the Proactive Safety Network (PSN) flag risk on streets with NO crash history?

    python -m analysis.psn_unseen

The PSN uses no crash data (road traits plus who is nearby), and says it exists to find risk before
people are hurt. So the fair test is on segments with zero serious crashes in 2018-2022, asking
whether the PSN-flagged ones go on to have more serious crashes in 2023-2025 than comparable
unflagged ones. "Comparable" = same road class, traffic volume, lane count and city.

PRIMARY analysis (fixed before looking at results):
    sample   quarter-mile segments with 0 killed-or-seriously-injured (KSI) crashes in 2018-2022
    outcome  KSI crashes in 2023-2025
    model    Poisson regression, offset = log(segment miles x 3 years), PSN flag + road class +
             log(AADT) (+ missing flag) + lanes (+ missing flag) + city; standard errors clustered
             by street name (neighbouring segments of one street are not independent)
    effect   incidence rate ratio (IRR) for PSN-flagged vs not
Everything else is a labelled sensitivity check:
    stricter sample (no injury crash of any kind in 2018-2022); outcome = all injury crashes
    (4x the events); all segments while controlling for 2018-2022 KSI history; arterials only;
    kitchen-sink controls that add school/transit proximity, density and equity (PSN uses
    schools and transit as inputs, so those controls partly remove what the PSN is measuring).

Alameda CTC's PSN lines are restricted: only the summary tables below are written out.
"""
from __future__ import annotations

import logging
import warnings

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

from alameda_traffic.config import PROCESSED, REPO_ROOT, RESTRICTED

log = logging.getLogger("analysis.psn_unseen")
RESULTS = REPO_ROOT / "analysis" / "results"
HIST, OUT = (2018, 2022), (2023, 2025)
OUT_YEARS = OUT[1] - OUT[0] + 1
ARTERIAL = ["primary", "secondary", "tertiary", "trunk"]


def load() -> pd.DataFrame:
    A = PROCESSED / "analysis"
    seg = pd.read_parquet(A / "segments.parquet").drop(columns="geometry", errors="ignore")
    net = pd.read_parquet(RESTRICTED / "analysis" / "segment_networks.parquet")[["segment_id", "PSN_2024"]]
    pan = pd.read_parquet(A / "segment_year.parquet")

    def per(cols, yrs, name):
        p = pan[pan.year.between(*yrs)].groupby("segment_id")[cols].sum().sum(axis=1)
        return p.rename(name)
    df = seg.merge(net, on="segment_id").merge(per(["n_ksi"], HIST, "ksi_hist"), on="segment_id").merge(
        per(["n_inj"], HIST, "inj_hist"), on="segment_id").merge(per(["n_ksi"], OUT, "ksi_out"), on="segment_id").merge(
        per(["n_inj"], OUT, "inj_out"), on="segment_id")
    df["psn"] = df.PSN_2024.astype(int)
    df["miles"] = df.length_m / 1609.344
    cls = df.osm_class.fillna("other").replace({"primary_link": "primary", "secondary_link": "secondary", "tertiary_link": "tertiary",
                                                "trunk_link": "trunk", "living_street": "residential"})
    df["cls"] = cls.where(cls.isin(ARTERIAL + ["residential", "unclassified"]), "other")
    df["aadt_missing"] = df.hpms_aadt.isna().astype(int)
    df["log_aadt"] = np.log(df.hpms_aadt.fillna(1).clip(lower=1))
    lanes = df.hpms_lanes.fillna(df.osm_lanes)
    df["lanes_missing"] = lanes.isna().astype(int)
    df["lanes"] = lanes.fillna(0).clip(upper=6)
    top = df.groupby("place").miles.sum().sort_values(ascending=False).head(14).index
    df["city"] = df.place.where(df.place.isin(top), "other").fillna("unincorporated")
    df["street"] = df.name.fillna("seg" + df.segment_id.astype(str))
    df["hist_any"] = (df.ksi_hist > 0).astype(int)
    for c in ("schools_400m", "bus_stops_400m", "n_intersections"):
        df[c] = df[c].fillna(0)
    df["log_density"] = np.log1p(df.pop_density_km2.fillna(0))
    df["epc_i"] = df.epc.fillna(False).astype(int)
    return df


BASE = "psn + C(cls) + log_aadt + aadt_missing + lanes + lanes_missing + C(city)"
KITCHEN = BASE + " + schools_400m + bus_stops_400m + n_intersections + log_density + epc_i"


def fit(df: pd.DataFrame, outcome: str, rhs: str, label: str) -> dict:
    d = df[df.miles > 0].copy()
    d["_off"] = np.log(d.miles * OUT_YEARS)
    groups = pd.factorize(d.street)[0]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        m = smf.glm(f"{outcome} ~ {rhs}", data=d, family=sm.families.Poisson(), offset=d["_off"]).fit(
            cov_type="cluster", cov_kwds={"groups": groups})
    b, se = m.params["psn"], m.bse["psn"]
    return {"analysis": label, "outcome": outcome, "segments": len(d), "psn_segments": int(d.psn.sum()),
            "events_total": int(d[outcome].sum()), "events_on_psn": int(d.loc[d.psn == 1, outcome].sum()),
            "IRR": round(float(np.exp(b)), 2), "ci_low": round(float(np.exp(b - 1.96 * se)), 2),
            "ci_high": round(float(np.exp(b + 1.96 * se)), 2), "p": round(float(m.pvalues["psn"]), 4)}


def rates(d: pd.DataFrame, outcome: str) -> pd.DataFrame:
    g = d.groupby(["cls", "psn"]).agg(segments=("psn", "size"), miles=("miles", "sum"), events=(outcome, "sum"))
    g["per_100_mi_yr"] = 100 * g.events / (g.miles * OUT_YEARS)
    return g.round(2)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    df = load()
    pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
    unseen = df[df.ksi_hist == 0]
    print(f"segments {len(df):,}; with 0 KSI in 2018-22: {len(unseen):,} ({len(unseen) / len(df):.1%}); PSN-flagged among them: "
          f"{int(unseen.psn.sum()):,} ({unseen.loc[unseen.psn == 1, 'miles'].sum():.0f} mi)")
    print(f"KSI 2023-25 on those unseen segments: {int(unseen.ksi_out.sum())} (on PSN-flagged: {int(unseen.loc[unseen.psn == 1, 'ksi_out'].sum())})")
    print("\nPSN-flagged segments by road class (all / unseen):")
    print(pd.DataFrame({"all": df[df.psn == 1].cls.value_counts(), "unseen": unseen[unseen.psn == 1].cls.value_counts()}).fillna(0).astype(int).to_string())
    print("\nRAW KSI rate 2023-25 per 100 mile-years, unseen segments, by class and PSN flag:")
    r = rates(unseen, "ksi_out"); print(r.to_string())

    rows = [fit(unseen, "ksi_out", BASE, "PRIMARY: unseen (0 KSI 2018-22), KSI outcome, base controls")]
    rows += [
        fit(unseen, "ksi_out", "psn", "unadjusted (no controls)"),
        fit(unseen, "inj_out", BASE, "sensitivity: outcome = all injury crashes"),
        fit(df[df.inj_hist == 0], "ksi_out", BASE, "sensitivity: stricter sample, 0 injury crashes 2018-22"),
        fit(df[df.inj_hist == 0], "inj_out", BASE, "sensitivity: stricter sample, injury outcome"),
        fit(unseen[unseen.cls.isin(ARTERIAL)], "ksi_out", BASE.replace("C(cls) + ", "C(cls) + "), "sensitivity: arterials only"),
        fit(unseen, "ksi_out", KITCHEN, "sensitivity: + school/transit/density/equity controls"),
        fit(df, "ksi_out", BASE + " + ksi_hist + hist_any", "sensitivity: ALL segments, controlling for 2018-22 KSI history"),
    ]
    res = pd.DataFrame(rows)
    RESULTS.mkdir(parents=True, exist_ok=True)
    res.to_csv(RESULTS / "psn_unseen_models.csv", index=False)
    r.reset_index().to_csv(RESULTS / "psn_unseen_rates_by_class.csv", index=False)
    print("\nIRR = rate of 2023-25 crashes on PSN-flagged vs unflagged segments, holding the controls fixed (1.00 = no difference):")
    print(res.to_string(index=False))


if __name__ == "__main__":
    main()
