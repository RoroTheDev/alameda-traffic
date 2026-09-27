"""Bundle data/processed/ into per-source zips and publish them as a GitHub
Release (data never enters git history).

    python publish_release.py                 # build dist/ + create release data-YYYY-MM-DD
    python publish_release.py --dry-run       # build dist/ only
    python publish_release.py --tag data-2026-10-01

Restricted data (data/restricted/) is never included. Requires the GitHub CLI
(`gh`) logged in with push access. Each asset must be < 2 GiB.

To fetch a release elsewhere:
    gh release download <tag> -R RoroTheDev/alameda-traffic -D dist
    then unzip each dist/*.zip into data/processed/
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import zipfile
from datetime import date
from pathlib import Path

from alameda_traffic.config import PROCESSED, PULL_LOG, REPO_ROOT
from alameda_traffic.http import sha256_file

DIST = REPO_ROOT / "dist"
MAX_ASSET = 2 * 1024**3


def build() -> list[Path]:
    DIST.mkdir(exist_ok=True)
    assets = []
    for src in sorted(p for p in PROCESSED.iterdir() if p.is_dir()):
        files = sorted(f for f in src.rglob("*") if f.is_file())
        if not files:
            continue
        out = DIST / f"{src.name}.zip"
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                zf.write(f, f.relative_to(PROCESSED).as_posix())
        if out.stat().st_size >= MAX_ASSET:
            sys.exit(f"{out.name} is over 2 GiB — split it before publishing")
        assets.append(out)
        print(f"{out.name}: {len(files)} files, {out.stat().st_size / 1e6:.1f} MB")
    log_copy = DIST / "pull_log.jsonl"
    log_copy.write_bytes(PULL_LOG.read_bytes())
    assets.append(log_copy)
    sums = DIST / "SHA256SUMS.txt"
    sums.write_text("".join(f"{sha256_file(a)}  {a.name}\n" for a in assets))
    assets.append(sums)
    return assets


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", default=f"data-{date.today().isoformat()}")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    assets = build()
    if args.dry_run:
        return 0
    notes = ("Alameda-scoped processed data. Provenance (source URLs, pull times, SHA-256 of every "
             "source file) is in pull_log.jsonl. Licenses and attribution: see README and "
             "catalog/sources.yaml — OSM data © OpenStreetMap contributors (ODbL).")
    cmd = ["gh", "release", "create", args.tag, *map(str, assets), "--title", args.tag, "--notes", notes]
    return subprocess.call(cmd, cwd=REPO_ROOT)


if __name__ == "__main__":
    sys.exit(main())
