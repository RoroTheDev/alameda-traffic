"""Alameda CTC 2024 manual bike/ped counts -> one row per count location (PM peak, 4-6 pm), geocoded.

    python -m analysis.counts

Input  data/manual/alamedactc_public/raw2024/*.xlsx  (public Alameda CTC 2024 count workbooks, Wiltec/Kittelson)
Output data/processed/analysis/counts_2024.parquet   (location, city, streets, ped, bike, ebike, scooter, x, y)

Every location has a "400-600" sheet pair (non-electric / electric); other periods (midday, school) are only at
some locations, so only 4-6 pm is used: it is the one period that is comparable across all locations.
Counts are summed over the four 15-minute-by-leg tables, so "ped" is people crossing on the four legs in 2 hours.
These are single two-hour counts on one weekday in fall: noisy, a relative index of exposure, not annual volume.
"""
from __future__ import annotations

import glob
import logging
import re
import warnings

import geopandas as gpd
import openpyxl
import pandas as pd

from alameda_traffic.config import PROCESSED, REPO_ROOT
from alameda_traffic.geocode import Geocoder, project

log = logging.getLogger("analysis.counts")
RAW = REPO_ROOT / "data" / "manual" / "alamedactc_public" / "raw2024"
OUT = PROCESSED / "analysis" / "counts_2024.parquet"
TIME = re.compile(r"^\d{3,4}-\d{3,4}$")
LEG = re.compile(r"^(NORTH|SOUTH|EAST|WEST)\s+LEG", re.I)


def meta(ws) -> dict:
    out = {}
    for r in ws.iter_rows(min_row=1, max_row=14, values_only=True):
        v = [x for x in r if x is not None]
        if not v:
            continue
        k = str(v[0]).strip().upper()
        if k.startswith("INTERSECTION") and len(v) >= 3:
            out["ns"] = str(v[2]).strip()
        elif k.startswith("E/W") and len(v) >= 2:
            out["ew"] = str(v[1]).strip()
        elif k.startswith("CITY") and len(v) >= 2:
            out["city"] = str(v[1]).strip()
        elif k.startswith("DATE") and len(v) >= 2:
            out["date"] = str(v[1]).strip()
    return out


def tally(ws, ped_col: int | None) -> dict:
    """sum 15-minute rows (not the hourly-total rows) over all legs."""
    bike = scooter = ped = rows = 0
    legs = set()
    in_hourly = False
    for r in ws.iter_rows(values_only=True):
        a = None if r[0] is None else str(r[0]).strip()
        if a and LEG.match(a):
            legs.add(a.upper().split()[0])
            in_hourly = False
            continue
        if a and a.lower().startswith("hourly"):
            in_hourly = True
            continue
        if a and TIME.match(a) and not in_hourly:
            num = lambda i: float(r[i]) if i < len(r) and isinstance(r[i], (int, float)) else 0.0
            bike += num(1) + num(2) + num(3)
            scooter += num(7) + num(8) + num(9)
            if ped_col is not None:
                ped += num(ped_col)
            rows += 1
    return dict(bike=bike, scooter=scooter, ped=ped, rows=rows, legs=len(legs))


def parse_all() -> pd.DataFrame:
    recs = []
    for f in sorted(glob.glob(str(RAW / "*.xlsx"))):
        m = re.search(r"Loc\s+(\d+)", f)
        if not m:
            continue
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
        if "400-600 (Non-Electric)" not in wb.sheetnames:
            log.warning("no PM sheet: %s", f)
            continue
        ne, el = wb["400-600 (Non-Electric)"], wb["400-600 (Electric)"]
        md = meta(ne)
        a, b = tally(ne, 13), tally(el, None)
        recs.append(dict(loc_id=int(m.group(1)), **md, ped=a["ped"], bike=a["bike"], ebike=b["bike"],
                         scooter=a["scooter"], escooter=b["scooter"], rows=a["rows"], legs=a["legs"], file=f.split("\\")[-1].split("/")[-1]))
    return pd.DataFrame(recs).sort_values("loc_id").reset_index(drop=True)


def ordinal(n: str) -> str:
    k = int(n)
    return "TH" if 10 <= k % 100 <= 20 else {1: "ST", 2: "ND", 3: "RD"}.get(k % 10, "TH")


def clean(street: str) -> list[str]:
    """'MACARTHUR BOULEVARD / CAMDEN STREET' -> both names; fix spacing and typos seen in the workbooks."""
    s = re.sub(r"\([^)]*\)", "", str(street)).upper()
    s = s.replace("MAC ARTHUR", "MACARTHUR").replace("BOULEVAARD", "BOULEVARD").replace("BOULEVERD", "BOULEVARD")
    s = re.sub(r"^(EAST|WEST|NORTH|SOUTH)\s+(?=\d)", lambda m: m.group(1)[0] + " ", s)
    s = re.sub(r"\bBOULEVARD\b", "BLVD", s)
    s = re.sub(r"\bPARKWAY\b", "PKWY", s)
    s = re.sub(r"\bTERRACE\b", "TER", s)
    s = re.sub(r"\bAVENUE AVENUE\b", "AVENUE", s).replace(",", "")
    s = re.sub(r"^(\d+) (?=(AVENUE|STREET)\b)", lambda m: m.group(1) + ordinal(m.group(1)) + " ", s)
    return [re.sub(r"\s+", " ", x).strip() for x in s.split("/") if x.strip()]


def geocode_row(g, ns, ew, city):
    city = str(city).title().replace("Freemont", "Fremont")
    if "Alameda County" in city or "County Of Alameda" in city or "Unincorporated" in city:
        city = "Unincorporated"
    for a in clean(ns):
        for b in clean(ew):
            r = g.geocode(a, b, city)
            if r.status == "ok":
                return r
    return r


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    d = parse_all()
    log.info("locations parsed %d (ids %d..%d); rows per location: %s; legs: %s", len(d), d.loc_id.min(), d.loc_id.max(),
             d.rows.value_counts().to_dict(), d.legs.value_counts().to_dict())
    print(d[["ped", "bike", "ebike", "scooter"]].describe().round(1).to_string())
    cl = gpd.read_file(PROCESSED / "county_gis" / "street_centerlines.geojson")
    g = Geocoder(cl)
    res = [geocode_row(g, r.ns, r.ew, r.city) for r in d.itertuples()]
    d["geo_status"] = [x.status for x in res]
    d["x"] = [x.x for x in res]
    d["y"] = [x.y for x in res]
    print(d.geo_status.value_counts().to_string())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    d.to_parquet(OUT, index=False)
    print(d[d.geo_status != "ok"][["loc_id", "city", "ns", "ew", "geo_status"]].to_string(index=False))


if __name__ == "__main__":
    main()
