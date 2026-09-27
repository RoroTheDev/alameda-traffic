"""Append-only record of every pull: what, from where, when, and its checksum.

Many sources change under us (CCRS files are regenerated daily, OSM changes
constantly), so catalog/pull_log.jsonl is committed to git as the record of
exactly which bytes a given analysis used.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import DATA_DIR, PULL_LOG
from .http import sha256_file


@contextmanager
def _log_lock(timeout: float = 30.0):
    """Cross-process lock so parallel downloads don't interleave log lines."""
    lock = PULL_LOG.with_suffix(".lock")
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if time.monotonic() > deadline:
                raise TimeoutError(f"{lock} held for >{timeout}s — delete it if no download is running")
            time.sleep(0.05)
    try:
        yield
    finally:
        os.close(fd)
        os.unlink(lock)


def _rel(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return Path(path).resolve().relative_to(DATA_DIR.resolve()).as_posix()
    except ValueError:
        return str(path)


def log_pull(source: str, item: str, *, url: str | None = None, out_path: Path | None = None,
             sha256: str | None = None, nbytes: int | None = None, rows_in: int | None = None,
             rows_out: int | None = None, **extra) -> dict:
    """Record one pull. `sha256`/`nbytes` describe the bytes fetched from the
    source; `out_sha256` is computed for the file we wrote."""
    rec = {
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source,
        "item": item,
        "url": url,
        "source_sha256": sha256,
        "source_bytes": nbytes,
        "rows_in": rows_in,
        "rows_out": rows_out,
        "out_path": _rel(out_path),
        "out_sha256": sha256_file(out_path) if out_path and Path(out_path).is_file() else None,
    }
    rec.update({k: v for k, v in extra.items() if v is not None})
    PULL_LOG.parent.mkdir(parents=True, exist_ok=True)
    with _log_lock(), open(PULL_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, default=str) + "\n")
    return rec
