"""TIMS — UC Berkeley SafeTREC Transportation Injury Mapping System.

Access: MANUAL (login required). TIMS geocodes CHP crashes (POINT_X/POINT_Y,
~97% statewide) — the fastest fix for the ~35% of Alameda injury crashes that
lack coordinates in CCRS. Injury crashes only (no property-damage-only).

How:
1. Create a free account at https://tims.berkeley.edu and sign in.
2. SWITRS Query & Map -> County: Alameda -> choose years -> download the
   Crashes, Parties and Victims CSVs. Note the "data current as of" / extract
   date TIMS shows on the query page (see EXTRACT DATE below).
3. Put the CSVs in data/manual/tims/ (any file names) and run
   `python download.py tims --extract-date YYYY-MM-DD`.

Permission: SafeTREC (SangHyouk Oum, TIMS Support, tims_info@berkeley.edu)
confirmed by email 2026-09-28 that SWITRS data accessed via TIMS may be
published in this public repository, on the condition that it carries the
citation in CITATION below. Outputs are stored under data/processed/ (release).

Reproducibility note from SafeTREC: TIMS posts the most recent CHP extract
each quarter, and recent years are provisional until CHP finalizes its
annual report, so crash counts for recent years can change between pulls.
Record the extract date (shown on the TIMS query page) with --extract-date
so results can be tied to the exact snapshot used.
"""
from __future__ import annotations

import logging

import pandas as pd

from ..config import MANUAL, PROCESSED, out_dir
from ..http import sha256_file
from ..provenance import log_pull

NAME = "tims"
HELP = "Ingest manually downloaded TIMS SWITRS CSVs (geocoded crashes)"
log = logging.getLogger(__name__)

CITATION = ("California Highway Patrol, Statewide Integrated Traffic Records System (SWITRS), "
           "accessed via the Transportation Injury Mapping System (TIMS), UC Berkeley Safe "
           "Transportation Research and Education Center, 2026.")


def add_arguments(p):
    p.add_argument("--extract-date", default=None,
                   help="TIMS 'data current as of' date shown on the query page (YYYY-MM-DD). "
                        "Recent years are provisional until CHP finalizes its annual report, so "
                        "recording this pins results to the exact snapshot used.")


def run(args):
    src_dir = MANUAL / "tims"
    files = sorted(src_dir.glob("*.csv")) if src_dir.exists() else []
    if not files:
        log.warning("No TIMS CSVs in %s — see `python download.py tims --help` for the steps.", src_dir)
        return
    if not getattr(args, "extract_date", None):
        log.warning("No --extract-date given — check the 'data current as of' date on the TIMS "
                    "query page and re-run with it; recent-year counts are provisional.")
    for f in files:
        df = pd.read_csv(f, dtype=str, encoding_errors="replace", low_memory=False)
        dest = out_dir(PROCESSED, NAME) / (f.stem + ".parquet")
        df.to_parquet(dest, index=False)
        log_pull(NAME, f.name, url="https://tims.berkeley.edu (manual download)", out_path=dest,
                 sha256=sha256_file(f), rows_out=len(df), citation=CITATION,
                 tims_extract_date=getattr(args, "extract_date", None),
                 permission="SafeTREC (S. Oum, tims_info@berkeley.edu), email 2026-09-28")
