"""TIMS — UC Berkeley SafeTREC Transportation Injury Mapping System.

Access: MANUAL (login required). TIMS geocodes CHP crashes (POINT_X/POINT_Y,
~97% statewide) — the fastest fix for the ~35% of Alameda injury crashes that
lack coordinates in CCRS. Injury crashes only (no property-damage-only).

How:
1. Create a free account at https://tims.berkeley.edu and sign in.
2. SWITRS Query & Map -> County: Alameda -> choose years -> download the
   Crashes, Parties and Victims CSVs.
3. Put the CSVs in data/manual/tims/ (any file names) and run
   `python download.py tims`.

Terms: cite "Transportation Injury Mapping System (TIMS), Safe
Transportation Research and Education Center, University of California,
Berkeley."; data may not be used in litigation against state/local
agencies; redistribution is not addressed — so outputs go to
data/restricted/ until SafeTREC (tims_info@berkeley.edu) says otherwise.
"""
from __future__ import annotations

import logging

import pandas as pd

from ..config import MANUAL, RESTRICTED, out_dir
from ..http import sha256_file
from ..provenance import log_pull

NAME = "tims"
HELP = "Ingest manually downloaded TIMS SWITRS CSVs (geocoded crashes)"
log = logging.getLogger(__name__)


def run(args):
    src_dir = MANUAL / "tims"
    files = sorted(src_dir.glob("*.csv")) if src_dir.exists() else []
    if not files:
        log.warning("No TIMS CSVs in %s — see `python download.py tims --help` for the steps.", src_dir)
        return
    for f in files:
        df = pd.read_csv(f, dtype=str, encoding_errors="replace", low_memory=False)
        dest = out_dir(RESTRICTED, NAME) / (f.stem + ".parquet")
        df.to_parquet(dest, index=False)
        log_pull(NAME, f.name, url="https://tims.berkeley.edu (manual download)", out_path=dest,
                 sha256=sha256_file(f), rows_out=len(df), license="TIMS terms (restricted)")
