"""FARS — NHTSA Fatality Analysis Reporting System.

Access: BULK. One national CSV zip per year (~27–33 MB). Kept: accident,
person and vehicle tables for Alameda (STATE=6, COUNTY=1). The zip is deleted
unless --keep-raw. File names/casing inside the zips vary by year.

Use: independent check on CCRS death counts. The newest year is usually an
"Annual Report File" (not final) — the log records which years were pulled.
"""
from __future__ import annotations

import logging
import zipfile

import pandas as pd

from ..config import PROCESSED, RAW, out_dir, parse_years
from ..http import SESSION, download
from ..provenance import log_pull

NAME = "fars"
HELP = "NHTSA fatal crashes (accident/person/vehicle) for Alameda, 2016+"
log = logging.getLogger(__name__)

URL = "https://static.nhtsa.gov/nhtsa/downloads/FARS/{y}/National/FARS{y}NationalCSV.zip"
TABLES = ("accident", "person", "vehicle")


def add_arguments(p):
    p.add_argument("--years", default="2016-2025", help="years not yet published are skipped")
    p.add_argument("--keep-raw", action="store_true")


def _read(zf: zipfile.ZipFile, table: str) -> pd.DataFrame:
    with zf.open(_member(zf, table)) as fh:
        df = pd.read_csv(fh, dtype=str, encoding="latin-1")
    # Some years start with a UTF-8 byte-order mark, which latin-1 decodes as "ï»¿".
    df.columns = [c.replace("﻿", "").replace("ï»¿", "").strip() for c in df.columns]
    return df


def _member(zf: zipfile.ZipFile, table: str) -> str:
    for n in zf.namelist():
        if n.rsplit("/", 1)[-1].lower() == f"{table}.csv":
            return n
    raise KeyError(f"{table}.csv not in zip")


def run(args):
    for year in parse_years(args.years):
        url = URL.format(y=year)
        if SESSION.head(url, timeout=60).status_code != 200:
            log.info("FARS %d not published; skipping", year)
            continue
        zpath = RAW / NAME / f"FARS{year}NationalCSV.zip"
        info = download(url, zpath)
        with zipfile.ZipFile(zpath) as zf:
            acc = _read(zf, "accident")
            acc = acc[(acc["STATE"].str.strip() == "6") & (acc["COUNTY"].str.strip() == "1")]
            cases = set(acc["ST_CASE"])
            frames = {"accident": acc}
            for table in ("person", "vehicle"):
                df = _read(zf, table)
                frames[table] = df[df["ST_CASE"].isin(cases)]
        for table, df in frames.items():
            dest = out_dir(PROCESSED, NAME) / f"{table}_{year}.parquet"
            df.to_parquet(dest, index=False)
            log_pull(NAME, f"{table} {year}", url=url, out_path=dest, sha256=info["sha256"],
                     nbytes=info["bytes"], rows_out=len(df))
        log.info("FARS %d: %d fatal crashes in Alameda", year, len(acc))
        if not args.keep_raw:
            zpath.unlink()
