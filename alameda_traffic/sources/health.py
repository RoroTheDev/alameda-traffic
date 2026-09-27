"""HCAI / CDPH Licensed and Certified Healthcare Facility Listing (data.chhs.ca.gov).

Access: API (CKAN datastore), filtered to Alameda. Includes hospitals, skilled
nursing facilities, clinics, and trauma-center flags (TRAUMA_CTR,
TRAUMA_PED_CTR). Administrator names and contact emails/phones/fax are
dropped before saving — they are personal data we don't need.
"""
from __future__ import annotations

import pandas as pd

from ..config import PROCESSED, out_dir
from ..http import get_json
from ..portals import CKAN_CHHS, ckan_package, ckan_resource
from ..provenance import log_pull

NAME = "health"
HELP = "Licensed healthcare facilities in Alameda (hospitals, SNFs, clinics, trauma flags)"

PACKAGE = "healthcare-facility-locations"
RESOURCE = "Licensed and Certified Healthcare Facility Locations"
PII_COLUMNS = ["FACADMIN", "CONTACT_EMAIL", "CONTACT_FAX", "CONTACT_PHONE_NUMBER"]


def run(args):
    pkg = ckan_package(CKAN_CHHS, PACKAGE)
    res = ckan_resource(pkg, RESOURCE)
    url = CKAN_CHHS + "datastore_search"
    records, offset = [], 0
    while True:
        resp = get_json(url, {"resource_id": res["id"], "filters": '{"COUNTY_NAME": "ALAMEDA"}',
                              "limit": 5000, "offset": offset})["result"]
        records.extend(resp["records"])
        offset += len(resp["records"])
        if not resp["records"] or offset >= resp["total"]:
            break
    df = pd.DataFrame(records).drop(columns=["_id"] + PII_COLUMNS, errors="ignore")
    dest = out_dir(PROCESSED, NAME) / "hcai_facilities_alameda.parquet"
    df.to_parquet(dest, index=False)
    log_pull(NAME, RESOURCE, url=f"{url}?resource_id={res['id']}", out_path=dest, rows_out=len(df),
             source_last_modified=res.get("last_modified"), dropped_columns=PII_COLUMNS)
