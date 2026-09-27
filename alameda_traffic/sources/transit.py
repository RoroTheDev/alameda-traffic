"""Transit schedules (GTFS) — stop locations and service frequency.

Access:
- BART: BULK, direct download (no key).
- AC Transit: TOKEN — set ACTRANSIT_TOKEN (register at api.actransit.org).
- 511 regional feed (all Bay Area operators): TOKEN — set API_511_KEY.

Stored under data/restricted/ because each feed has its own terms of use;
publish only derived facts (stop points, headways), with attribution.
Current feeds only — historical (2020–2024) feeds must come from an archive.
"""
from __future__ import annotations

import logging

from ..config import ACTRANSIT_TOKEN, API_511_KEY, RESTRICTED, out_dir
from ..http import download
from ..provenance import log_pull

NAME = "transit"
HELP = "GTFS: BART (open), AC Transit and 511 regional (need tokens)"
log = logging.getLogger(__name__)

BART = "https://www.bart.gov/dev/schedules/google_transit.zip"
ACTRANSIT = "https://api.actransit.org/transit/gtfs/download"
REGIONAL_511 = "https://api.511.org/transit/datafeeds"


def _get(label: str, url: str, fname: str, params: dict | None = None, log_url: str | None = None):
    info = download(url, out_dir(RESTRICTED, NAME) / fname, params=params)
    log_pull(NAME, label, url=log_url or url, out_path=info["path"], sha256=info["sha256"],
             nbytes=info["bytes"])


def run(args):
    _get("BART GTFS", BART, "bart_gtfs.zip")
    if ACTRANSIT_TOKEN:
        _get("AC Transit GTFS", ACTRANSIT, "actransit_gtfs.zip", {"token": ACTRANSIT_TOKEN}, ACTRANSIT)
    else:
        log.warning("ACTRANSIT_TOKEN not set; skipping AC Transit GTFS")
    if API_511_KEY:
        _get("511 regional GTFS", REGIONAL_511, "511_regional_gtfs.zip",
             {"api_key": API_511_KEY, "operator_id": "RG"}, REGIONAL_511 + "?operator_id=RG")
    else:
        log.warning("API_511_KEY not set; skipping 511 regional GTFS")
