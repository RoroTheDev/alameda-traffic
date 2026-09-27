"""Countermeasure effects and guidance.

Access: BULK files.
- FHWA CMF Clearinghouse: the full database as CSV plus its data dictionary.
  (Its TLS chain is incomplete; http.py verifies via the OS trust store.)
- Caltrans Local Roadway Safety Manual (2026 final): crash reduction factors,
  service life, HSIP eligibility. No unit costs — source those locally.
- Caltrans HSIP Analyzer manual (BCR applications, 2024 v2): benefit–cost method.
"""
from __future__ import annotations

import pandas as pd

from ..config import PROCESSED, out_dir
from ..http import download
from ..provenance import log_pull

NAME = "countermeasures"
HELP = "FHWA CMF Clearinghouse database, Caltrans LRSM 2026, HSIP analyzer manual"

FILES = {
    "cmf_clearinghouse.csv": "https://cmfclearinghouse.fhwa.dot.gov/cmf_datacsv.php?file=cmfclearinghouse.csv",
    "cmf_clearinghouse_dictionary.pdf": "https://cmfclearinghouse.fhwa.dot.gov/cmf_datapdf.php?file=cmfdictionary.pdf",
    "caltrans_lrsm_2026.pdf": ("https://dot.ca.gov/-/media/dot-media/programs/local-assistance/documents/"
                               "hsip/2026/lrsm2026final.pdf"),
    "caltrans_hsip_analyzer_manual_bcr_2024v2.pdf": ("https://dot.ca.gov/-/media/dot-media/programs/"
                                                     "local-assistance/documents/hsip/2024/"
                                                     "hsip-analyzer-manual-bcr2024-v2.pdf"),
}


def run(args):
    for fname, url in FILES.items():
        info = download(url, out_dir(PROCESSED, NAME) / fname, timeout=600)
        rows = None
        if fname.endswith(".csv"):
            rows = len(pd.read_csv(info["path"], dtype=str, encoding_errors="replace"))
        log_pull(NAME, fname, url=url, out_path=info["path"], sha256=info["sha256"],
                 nbytes=info["bytes"], rows_out=rows)
