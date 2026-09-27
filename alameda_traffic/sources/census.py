"""Census: boundaries (TIGERweb), ACS 5-year tables, LEHD LODES jobs.

Access:
- Boundaries: API (TIGERweb ArcGIS REST), vintage matched to the ACS year.
- ACS: API when CENSUS_API_KEY is set (the Census API now rejects keyless
  requests); otherwise BULK — stream the national table-based summary files
  (18–200 MB each) and keep Alameda tracts/block groups. Column names are
  normalised to API style (B01001_001E / B01001_001M) either way.
- LODES: BULK — statewide gz per year (~6 MB), filtered to Alameda blocks.
"""
from __future__ import annotations

import logging

import pandas as pd
from requests import HTTPError

from .. import arcgis
from ..config import CENSUS_API_KEY, COUNTY_FIPS, PROCESSED, STATE_FIPS, BBOX, out_dir, parse_years
from ..http import get_json, stream
from ..provenance import log_pull

NAME = "census"
HELP = "TIGERweb boundaries, ACS 5-year tables, LODES workplace jobs"
log = logging.getLogger(__name__)

TIGERWEB = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/tigerWMS_ACS{year}/MapServer"
LAYERS = {  # layer id -> (output stem, where clause, use bbox filter)
    82: ("county", f"STATE='{STATE_FIPS}' AND COUNTY='{COUNTY_FIPS}'", False),
    8: ("tracts", f"STATE='{STATE_FIPS}' AND COUNTY='{COUNTY_FIPS}'", False),
    10: ("block_groups", f"STATE='{STATE_FIPS}' AND COUNTY='{COUNTY_FIPS}'", False),
    28: ("places_incorporated", f"STATE='{STATE_FIPS}'", True),  # places carry no county code
    30: ("places_cdp", f"STATE='{STATE_FIPS}'", True),
}

# ACS tables: age/sex, race/ethnicity, commute mode, vehicles, income, poverty
ACS_TABLES = ["B01001", "B03002", "B08301", "B08201", "B19013", "B17001"]
SF_URL = ("https://www2.census.gov/programs-surveys/acs/summary_file/{year}/table-based-SF/"
          "data/5YRData/acsdt5y{year}-{table}.dat")
GEO_PREFIXES = (f"1400000US{STATE_FIPS}{COUNTY_FIPS}", f"1500000US{STATE_FIPS}{COUNTY_FIPS}")

LODES_URL = "https://lehd.ces.census.gov/data/lodes/LODES8/ca/wac/ca_wac_S000_JT00_{year}.csv.gz"


def add_arguments(p):
    p.add_argument("--acs-year", type=int, default=2024, help="ACS 5-year end year (2024 = 2020-2024)")
    p.add_argument("--lodes-years", default="2016-2023")
    p.add_argument("--only", choices=["boundaries", "acs", "lodes"], help="run one part")


def boundaries(year: int):
    base = TIGERWEB.format(year=year)
    for layer, (stem, where, use_bbox) in LAYERS.items():
        url = f"{base}/{layer}"
        fc = arcgis.query_all(url, where, bbox=BBOX if use_bbox else None)
        dest = arcgis.save_geojson(fc, out_dir(PROCESSED, NAME) / f"tiger_acs{year}_{stem}.geojson")
        log_pull(NAME, f"TIGERweb ACS{year} {stem}", url=url, out_path=dest, rows_out=len(fc["features"]),
                 where=where, bbox=list(BBOX) if use_bbox else None)


def _acs_api(year: int, table: str) -> tuple[pd.DataFrame, str]:
    url = f"https://api.census.gov/data/{year}/acs/acs5"
    frames = []
    for level, geo in (("tract", {"for": "tract:*", "in": f"state:{STATE_FIPS} county:{COUNTY_FIPS}"}),
                       ("block group", {"for": "block group:*",
                                        "in": f"state:{STATE_FIPS} county:{COUNTY_FIPS} tract:*"})):
        try:
            rows = get_json(url, {"get": f"group({table})", **geo, "key": CENSUS_API_KEY})
        except (HTTPError, ValueError):
            if level == "tract":
                raise
            log.info("ACS %s not published for block groups; tracts only", table)
            continue
        df = pd.DataFrame(rows[1:], columns=rows[0])
        keep = ["GEO_ID", "NAME"] + [c for c in df.columns if c.startswith(table) and c[-1] in "EM"]
        frames.append(df[keep].assign(geo_level=level))
    return pd.concat(frames, ignore_index=True), url


def _acs_bulk(year: int, table: str) -> tuple[pd.DataFrame, str, dict]:
    url = SF_URL.format(year=year, table=table.lower())
    parts = []
    with stream(url, timeout=300) as (fh, hasher):
        for chunk in pd.read_csv(fh, sep="|", dtype=str, chunksize=200_000):
            parts.append(chunk[chunk["GEO_ID"].str.startswith(GEO_PREFIXES)])
    df = pd.concat(parts, ignore_index=True)
    # B01001_E001 -> B01001_001E (API naming)
    df = df.rename(columns={c: f"{c.split('_')[0]}_{c.split('_')[1][1:]}{c.split('_')[1][0]}"
                            for c in df.columns if c != "GEO_ID"})
    df["geo_level"] = df["GEO_ID"].str[:3].map({"140": "tract", "150": "block group"})
    return df, url, {"sha256": hasher.sha256.hexdigest(), "bytes": hasher.nbytes}


def acs(year: int):
    for table in ACS_TABLES:
        src = {}
        if CENSUS_API_KEY:
            df, url = _acs_api(year, table)
            method = "api"
        else:
            df, url, src = _acs_bulk(year, table)
            method = "table-based summary file"
        value_cols = [c for c in df.columns if c.startswith(table)]
        df[value_cols] = df[value_cols].apply(pd.to_numeric, errors="coerce")
        dest = out_dir(PROCESSED, NAME) / f"acs{year}_5yr_{table}.parquet"
        df.to_parquet(dest, index=False)
        log.info("ACS %s: %d geographies via %s", table, len(df), method)
        log_pull(NAME, f"ACS {year} 5-year {table}", url=url, out_path=dest, rows_out=len(df),
                 method=method, sha256=src.get("sha256"), nbytes=src.get("bytes"))


def lodes(years: list[int]):
    frames = []
    for year in years:
        url = LODES_URL.format(year=year)
        parts = []
        with stream(url) as (fh, hasher):
            for chunk in pd.read_csv(fh, compression="gzip", dtype={"w_geocode": str}, chunksize=200_000):
                parts.append(chunk[chunk["w_geocode"].str.startswith(STATE_FIPS + COUNTY_FIPS)])
        df = pd.concat(parts, ignore_index=True).assign(year=year)
        frames.append(df)
        log_pull(NAME, f"LODES8 WAC S000 JT00 {year}", url=url, sha256=hasher.sha256.hexdigest(),
                 nbytes=hasher.nbytes, rows_out=len(df))
    out = pd.concat(frames, ignore_index=True)
    dest = out_dir(PROCESSED, NAME) / "lodes8_wac_alameda.parquet"
    out.to_parquet(dest, index=False)
    log_pull(NAME, "LODES8 WAC combined", out_path=dest, rows_out=len(out),
             years=f"{years[0]}-{years[-1]}")


def run(args):
    if args.only in (None, "boundaries"):
        boundaries(args.acs_year)
    if args.only in (None, "acs"):
        acs(args.acs_year)
    if args.only in (None, "lodes"):
        lodes(parse_years(args.lodes_years))
