"""CCRS — California Crash Reporting System (CHP), via data.ca.gov.

Access: BULK. One statewide CSV per table per year (~160–250 MB each, ~5 GB
total). Each file is streamed, Alameda rows are kept, and the statewide copy
is discarded unless --keep-raw.

Why not the data.ca.gov SQL API: its copy of 2019 is truncated (Jan 1–Apr 8
only; the CSV is complete), and Parties/InjuredWitnessPassengers have no
county column, so they must be filtered by collision ID from the Crashes
file anyway.

Values are kept exactly as published (all strings). Only column names are
cleaned: the CSV headers carry stray tab characters.
"""
from __future__ import annotations

import logging
import warnings

import pandas as pd

from ..config import CHP_COUNTY_CODE, PROCESSED, RAW, out_dir, parse_years
from ..http import download, stream
from ..portals import CKAN_CA, ckan_package
from ..provenance import log_pull

NAME = "ccrs"
HELP = "CHP crash data (Crashes, Parties, Injured) 2016+, filtered to Alameda"
log = logging.getLogger(__name__)

PACKAGE = "ccrs"
TABLES = {  # CKAN resource prefix -> (output stem, collision-id column)
    "Crashes": ("crashes", "Collision Id"),
    "Parties": ("parties", "CollisionId"),
    "InjuredWitnessPassengers": ("injured", "CollisionId"),
}


def add_arguments(p):
    p.add_argument("--years", default="2016-2026", help="e.g. 2016-2025 or 2019,2024")
    p.add_argument("--keep-raw", action="store_true", help="also save the statewide CSVs (~5 GB)")
    p.add_argument("--force", action="store_true", help="re-pull years already on disk")


def _resources() -> tuple[dict, dict]:
    pkg = ckan_package(CKAN_CA, PACKAGE)
    by_key = {}
    template = None
    for res in pkg["resources"]:
        name = res["name"].strip()
        if name == "Raw Data Template":
            template = res
            continue
        prefix, _, year = name.rpartition("_")
        if prefix in TABLES and year.isdigit():
            by_key[(prefix, int(year))] = res
    return by_key, template


def _pull_table(res: dict, table: str, year: int, keep, keep_raw: bool):
    stem, id_col = TABLES[table]
    url = res["url"]
    dest = out_dir(PROCESSED, NAME) / f"{stem}_{year}.parquet"
    tee = RAW / NAME / url.rsplit("/", 1)[-1] if keep_raw else None
    parts, rows_in = [], 0
    log.info("streaming %s %d ...", table, year)
    with stream(url, tee_path=tee, timeout=300) as (fh, hasher), \
            warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", pd.errors.ParserWarning)
        reader = pd.read_csv(fh, dtype=str, chunksize=100_000, encoding="utf-8-sig",
                             encoding_errors="replace", keep_default_na=False, na_values=[""],
                             on_bad_lines="warn", low_memory=False)
        for chunk in reader:
            chunk.columns = [c.strip() for c in chunk.columns]
            rows_in += len(chunk)
            parts.append(chunk.loc[keep(chunk)])
    # Malformed lines are skipped by the parser; count them so the log shows it.
    bad = sum(str(w.message).count("Skipping line") for w in caught)
    if bad:
        log.warning("%s %d: %d malformed lines skipped", table, year, bad)
    df = pd.concat(parts, ignore_index=True)
    df.to_parquet(dest, index=False)
    log.info("%s %d: kept %d of %d rows", table, year, len(df), rows_in)
    log_pull(NAME, f"{table}_{year}", url=url, out_path=dest, sha256=hasher.sha256.hexdigest(),
             nbytes=hasher.nbytes, rows_in=rows_in, rows_out=len(df),
             source_last_modified=res.get("last_modified"), malformed_lines_skipped=bad)
    return set(df[id_col].str.strip())


def run(args):
    resources, template = _resources()
    if template:
        info = download(template["url"], out_dir(RAW, NAME) / "rawdata_template.docx")
        log_pull(NAME, "Raw Data Template (data dictionary)", url=template["url"],
                 out_path=info["path"], sha256=info["sha256"], nbytes=info["bytes"])

    for year in parse_years(args.years):
        if ("Crashes", year) not in resources:
            log.warning("CCRS has no Crashes_%d resource; skipping", year)
            continue
        done = [out_dir(PROCESSED, NAME) / f"{TABLES[t][0]}_{year}.parquet" for t in TABLES]
        if not args.force and all(p.exists() for p in done):
            log.info("CCRS %d already pulled (use --force to refresh)", year)
            continue
        ids = _pull_table(resources[("Crashes", year)], "Crashes", year,
                          lambda d: d["County Code"].str.strip() == CHP_COUNTY_CODE, args.keep_raw)
        for table in ("Parties", "InjuredWitnessPassengers"):
            res = resources.get((table, year))
            if res is None:
                log.warning("CCRS has no %s_%d resource; skipping", table, year)
                continue
            _pull_table(res, table, year,
                        lambda d, col=TABLES[table][1]: d[col].str.strip().isin(ids), args.keep_raw)
