"""Alameda CTC manual bike/ped counts -> one row per count location (PM peak, 4-6 pm), geocoded.

    python -m analysis.counts                 # 2024 (default)
    python -m analysis.counts --year 2018     # any of 2016, 2017, 2018, 2020, 2022, 2024

Input  data/manual/alamedactc_public/raw<year>/*.xlsx  (public Alameda CTC count workbooks, Wiltec)
Output data/processed/analysis/counts_<year>.parquet   (location, city, streets, ped, bike, ebike, scooter, x, y)

Every location has a 4-6 pm sheet ("400-600"; in 2024 a non-electric / electric pair); other periods (midday,
school) are only at some locations, so only 4-6 pm is used: it is the one period comparable across all locations.
Counts are summed over the four 15-minute-by-leg tables, so "ped" is people crossing on the four legs in 2 hours.
These are single two-hour counts on one weekday in fall: noisy, a relative index of exposure, not annual volume.

Year differences (checked on every workbook by the header checks below; see docs/tasks/COUNT_PARSERS_TASK.md):
    2016-2018  groups BICYCLES | PEDS              (pedestrian TOTAL COUNT in column 7)
    2020-2022  groups BICYCLES | SCOOTERS | PEDS   (pedestrians in column 13; 2020 adds summary columns at 15+)
    2024       NON-ELECTRIC BIKES | NON-ELECTRIC SCOOTERS | PEDS, plus a separate Electric sheet
Columns are located from each leg's group-header row, never hard-coded, and each leg's "15-min Counts" row is
checked (movement codes under the bike group, TOTAL COUNT under PEDS). E-bikes and e-scooters were not counted
separately before 2024, so ebike = escooter = 0 there (any e-bikes are inside "bike").
File naming: "Loc N" (any case, optional a/b suffix = two nearby intersections, both kept); 2017 uses
"ALAMEDA NN-..." where NN is the location number; when a location has an original and a "(Revised)" file the
revised one is used.
"""
from __future__ import annotations

import argparse
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
YEARS = (2016, 2017, 2018, 2020, 2022, 2024)
TIME = re.compile(r"^\d{3,4}-\d{3,4}$")
LEG = re.compile(r"^(NORTH|SOUTH|EAST|WEST)\s+LEG", re.I)
MOVES = re.compile(r"^([NSEW]B(RT|TH|LT)|[A-D])$")       # A-D: movements of a fifth, diagonal leg (2024 Loc 62)
LOC_ID = (re.compile(r"\bLoc\s*(\d+)\s*([AB])?\b", re.I), re.compile(r"^ALAMEDA\s+(\d+)-", re.I))


def raw_dir(year: int):
    return REPO_ROOT / "data" / "manual" / "alamedactc_public" / f"raw{year}"


def out_path(year: int):
    return PROCESSED / "analysis" / f"counts_{year}.parquet"


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


def groups(r) -> dict:
    """leg header row -> {'bike': col, 'scooter': col or None, 'ped': col or None} from the group labels."""
    cols = [(j, str(v).strip().upper()) for j, v in enumerate(r) if j > 0 and v is not None and str(v).strip()]
    ped = next((j for j, v in cols if v == "PEDS"), None)
    other = [j for j, v in cols if v != "PEDS"]
    return {"bike": other[0] if other else None, "scooter": other[1] if len(other) > 1 else None, "ped": ped}


def tally(ws, use_ped: bool) -> dict:
    """sum 15-minute rows (not the hourly-total rows) over all legs.

    Each leg block = a group-header row (BICYCLES / SCOOTERS / PEDS labels), a movement-number row, a "15-min Counts"
    row, eight 15-minute rows, then hourly totals. Every "15-min Counts" row starts a block (so an unusual leg label
    such as "SOUTH EAST" cannot silently drop rows); movement columns are the consecutive cells reading NBRT/SBTH/...
    after the group's first column (most legs have 3; some have 4, e.g. two through lanes)."""
    bike = scooter = ped = rows = blocks = 0
    problems = []
    in_hourly, g, prev, cols = True, None, None, None
    for r in ws.iter_rows(values_only=True):
        if not r:
            continue
        a = None if r[0] is None else str(r[0]).strip()
        if (a and re.search(r"\bLEG\b", a, re.I)) or any(v is not None and str(v).strip().upper() == "PEDS" for v in r[1:]):  # leg header
            g = groups(r)
            continue
        if a and a.lower().startswith("15-min"):
            blocks += 1
            in_hourly = False
            cell = lambda i: str(r[i]).strip().upper() if i is not None and i < len(r) and r[i] is not None else ""
            if g is None:
                problems.append("15-min block without a leg header")
                cols = None
                continue
            run = lambda s: [j for j in range(s, s + 6) if MOVES.match(cell(j))] if s is not None else []
            bc, sc = run(g["bike"]), run(g["scooter"])
            bc = [j for j in bc if all(MOVES.match(cell(k)) for k in range(g["bike"], j + 1))]
            sc = [j for j in sc if all(MOVES.match(cell(k)) for k in range(g["scooter"], j + 1))] if g["scooter"] is not None else []
            if len(bc) < 3:
                problems.append(f"bike movement columns from {g['bike']}: {bc}")
            if g["scooter"] is not None and len(sc) < 3:
                problems.append(f"scooter movement columns from {g['scooter']}: {sc}")
            if use_ped and (g["ped"] is None or cell(g["ped"]) != "TOTAL COUNT"):
                problems.append(f"PEDS column {g['ped']} is not TOTAL COUNT")
            cols = (bc, sc, g["ped"])
            continue
        if a and a.lower().startswith("hourly"):
            in_hourly = True
            continue
        if a and TIME.match(a) and not in_hourly and cols is not None:
            num = lambda i: float(r[i]) if i is not None and i < len(r) and isinstance(r[i], (int, float)) else 0.0
            bike += sum(num(j) for j in cols[0])
            scooter += sum(num(j) for j in cols[1])
            if use_ped:
                ped += num(cols[2])
            rows += 1
    if rows != 8 * blocks:
        problems.append(f"{rows} fifteen-minute rows for {blocks} leg blocks")
    return dict(bike=bike, scooter=scooter, ped=ped, rows=rows, legs=blocks, problems=problems)


def location(fname: str):
    """file name -> (loc_id int, loc_label, revised flag), or None."""
    for rx in LOC_ID:
        m = rx.search(fname)
        if m:
            sfx = (m.group(2) or "").lower() if m.lastindex and m.lastindex >= 2 else ""
            return int(m.group(1)), f"{int(m.group(1))}{sfx}", "revised" in fname.lower()
    return None


def pick_files(year: int):
    """one file per location label; prefer '(Revised)'. Returns (list of (path, id, label), notes)."""
    best, notes = {}, []
    for f in sorted(glob.glob(str(raw_dir(year) / "**" / "*.xlsx"), recursive=True)):
        name = f.replace("\\", "/").split("/")[-1]
        if name.startswith("~$"):
            continue
        loc = location(name)
        if loc is None:
            notes.append(f"skipped (no location number): {name}")
            continue
        lid, label, rev = loc
        if label in best:
            keep, drop = ((f, name), best[label][:2]) if rev and not best[label][3] else (best[label][:2], (f, name))
            notes.append(f"location {label}: two files, used '{keep[1]}', dropped '{drop[1]}'")
            if keep[0] == f:
                best[label] = (f, name, lid, rev)
            continue
        best[label] = (f, name, lid, rev)
    return [(v[0], v[2], k) for k, v in best.items()], notes


def parse_all(year: int) -> tuple[pd.DataFrame, list[str]]:
    recs = []
    files, notes = pick_files(year)
    for f, lid, label in files:
        name = f.replace("\\", "/").split("/")[-1]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
        if "400-600 (Non-Electric)" in wb.sheetnames:
            ne, el = wb["400-600 (Non-Electric)"], wb["400-600 (Electric)"]
        elif any(s.startswith("400-600") for s in wb.sheetnames):
            sh = [s for s in wb.sheetnames if s.startswith("400-600")]
            if len(sh) > 1 or sh[0] != "400-600":
                notes.append(f"4-6 pm sheet named {sh} in {name}; used '{sh[0]}'")
            ne, el = wb[sh[0]], None
        else:
            notes.append(f"skipped (no 4-6 pm sheet): {name}")
            continue
        md = meta(ne)
        a = tally(ne, True)
        b = tally(el, False) if el is not None else dict(bike=0.0, scooter=0.0, problems=[])
        for p in a["problems"] + b["problems"]:
            notes.append(f"header check failed in {name}: {p}")
        recs.append(dict(loc_id=lid, loc_label=label, **md, ped=a["ped"], bike=a["bike"], ebike=b["bike"],
                         scooter=a["scooter"], escooter=b["scooter"], rows=a["rows"], legs=a["legs"],
                         header_ok=not (a["problems"] or b["problems"]), file=name))
    d = pd.DataFrame(recs).sort_values(["loc_id", "loc_label"]).reset_index(drop=True)
    return d, notes


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
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2024, choices=YEARS)
    ap.add_argument("--no-geocode", action="store_true", help="parse and check only (no street map needed)")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    d, notes = parse_all(a.year)
    log.info("%d: locations parsed %d; rows per location: %s; legs: %s; header checks failed at %d locations", a.year, len(d),
             d.rows.value_counts().to_dict(), d.legs.value_counts().to_dict(), int((~d.header_ok).sum()))
    for n in notes:
        log.info("note: %s", n)
    print(d[["ped", "bike", "ebike", "scooter"]].describe().round(1).to_string())
    print("totals:", d[["ped", "bike", "ebike", "scooter", "escooter"]].sum().to_dict())
    if a.no_geocode:
        return d
    cl = gpd.read_file(PROCESSED / "county_gis" / "street_centerlines.geojson")
    g = Geocoder(cl)
    res = [geocode_row(g, r.ns, r.ew, r.city) for r in d.itertuples()]
    d["geo_status"] = [x.status for x in res]
    d["x"] = [x.x for x in res]
    d["y"] = [x.y for x in res]
    print(d.geo_status.value_counts().to_string())
    out = out_path(a.year)
    out.parent.mkdir(parents=True, exist_ok=True)
    d.to_parquet(out, index=False)
    print(d[d.geo_status != "ok"][["loc_label", "city", "ns", "ew", "geo_status"]].to_string(index=False))


if __name__ == "__main__":
    main()
