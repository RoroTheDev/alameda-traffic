"""Paths, study-area constants and environment settings."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")

DATA_DIR = Path(os.environ.get("ALAMEDA_DATA_DIR") or REPO_ROOT / "data")
RAW = DATA_DIR / "raw"                # original files we chose to keep (git-ignored)
PROCESSED = DATA_DIR / "processed"    # Alameda-scoped outputs; published as Release assets
RESTRICTED = DATA_DIR / "restricted"  # license-restricted; never committed or released
MANUAL = REPO_ROOT / "data" / "manual"  # files you download by hand (CAPTCHA/login)

CATALOG_DIR = REPO_ROOT / "catalog"
SOURCES_YAML = CATALOG_DIR / "sources.yaml"
PULL_LOG = CATALOG_DIR / "pull_log.jsonl"

# Study area
STATE_FIPS = "06"
COUNTY_FIPS = "001"
COUNTY_GEOID = STATE_FIPS + COUNTY_FIPS
CHP_COUNTY_CODE = "1"  # CHP/CCRS county code for Alameda
# Padded county envelope (lon_min, lat_min, lon_max, lat_max), WGS84
BBOX = (-122.38, 37.45, -121.46, 37.91)

CENSUS_API_KEY = os.environ.get("CENSUS_API_KEY") or None
ACTRANSIT_TOKEN = os.environ.get("ACTRANSIT_TOKEN") or None
API_511_KEY = os.environ.get("API_511_KEY") or None
MAPILLARY_TOKEN = os.environ.get("MAPILLARY_TOKEN") or None


def out_dir(kind: Path, source: str) -> Path:
    path = kind / source
    path.mkdir(parents=True, exist_ok=True)
    return path


def parse_years(spec: str) -> list[int]:
    """'2016-2020,2023' -> [2016, 2017, 2018, 2019, 2020, 2023]"""
    years: list[int] = []
    for part in str(spec).split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-")
            years.extend(range(int(lo), int(hi) + 1))
        else:
            years.append(int(part))
    return sorted(set(years))
