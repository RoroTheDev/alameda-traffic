"""HTTP helpers: one retrying session, hashed streaming downloads, JSON calls."""
from __future__ import annotations

import hashlib
import io
import logging
import shutil
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

import truststore

# Verify TLS against the OS trust store. Some government sites (e.g. the FHWA
# CMF Clearinghouse) send incomplete certificate chains that certifi rejects
# but Windows/macOS resolve. Verification stays on.
truststore.inject_into_ssl()

import requests  # noqa: E402  (must import after truststore injection)
from requests.adapters import HTTPAdapter  # noqa: E402
from urllib3.util.retry import Retry  # noqa: E402

log = logging.getLogger(__name__)

USER_AGENT = "alameda-traffic-research/0.1 (+https://github.com/RoroTheDev/alameda-traffic)"


def _session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=5,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "POST", "HEAD"}),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    s.headers["User-Agent"] = USER_AGENT
    return s


SESSION = _session()


class HashingReader(io.RawIOBase):
    """Wraps a byte stream; hashes (and optionally tees to disk) what is read."""

    def __init__(self, raw: BinaryIO, tee: BinaryIO | None = None):
        self._raw = raw
        self._tee = tee
        self.sha256 = hashlib.sha256()
        self.nbytes = 0

    def readable(self) -> bool:
        return True

    def readinto(self, buffer) -> int:
        data = self._raw.read(len(buffer))
        n = len(data)
        buffer[:n] = data
        self.sha256.update(data)
        self.nbytes += n
        if self._tee is not None:
            self._tee.write(data)
        return n


@contextmanager
def stream(url: str, *, params: dict | None = None, tee_path: Path | None = None,
           timeout: int = 120) -> Iterator[tuple[io.BufferedReader, HashingReader]]:
    """Open a URL as a buffered byte stream that hashes as it is consumed.

    Yields (buffered_reader, hasher). Read the stream to the end before using
    hasher.sha256 / hasher.nbytes.
    """
    tee = None
    tmp = None
    with SESSION.get(url, params=params, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        r.raw.decode_content = True
        if tee_path is not None:
            tee_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = tee_path.with_suffix(tee_path.suffix + ".part")
            tee = open(tmp, "wb")
        hasher = HashingReader(r.raw, tee)
        try:
            yield io.BufferedReader(hasher, buffer_size=1 << 20), hasher
        except BaseException:
            if tee is not None:
                tee.close()
                tmp.unlink(missing_ok=True)
            raise
        else:
            if tee is not None:
                tee.close()
                tmp.replace(tee_path)


def download(url: str, dest: Path, *, params: dict | None = None, timeout: int = 120) -> dict:
    """Stream url to dest (atomically). Returns {'sha256', 'bytes', 'path'}."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    sha = hashlib.sha256()
    n = 0
    with SESSION.get(url, params=params, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with open(tmp, "wb") as fh:
            for chunk in r.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
                sha.update(chunk)
                n += len(chunk)
    tmp.replace(dest)
    log.info("downloaded %s (%.1f MB)", dest.name, n / 1e6)
    return {"sha256": sha.hexdigest(), "bytes": n, "path": dest}


def get_json(url: str, params: dict | None = None, *, method: str = "GET",
             data: dict | None = None, timeout: int = 120):
    if method == "POST":
        r = SESSION.post(url, params=params, data=data, timeout=timeout)
    else:
        r = SESSION.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def sha256_file(path: Path) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def copy_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
