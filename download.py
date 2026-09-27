"""Download every data source for the Alameda County traffic-safety study.

    python download.py list                 # catalog: every source + how it's accessed
    python download.py manual               # checklist of things only you can do
    python download.py ccrs --years 2024    # one source (see each source's --help)
    python download.py all                  # every scriptable source
    python download.py all --skip ccrs,hpms

Outputs go to $ALAMEDA_DATA_DIR (default ./data); every pull is recorded in
catalog/pull_log.jsonl.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time

import yaml

from alameda_traffic import sources
from alameda_traffic.config import DATA_DIR, SOURCES_YAML


def _catalog() -> list[dict]:
    with open(SOURCES_YAML, encoding="utf-8") as fh:
        return yaml.safe_load(fh)["sources"]


def cmd_list(_args) -> int:
    rows = _catalog()
    w = max(len(s["id"]) for s in rows)
    print(f"{'id':{w}} {'access':8} {'storage':10} name")
    for s in rows:
        print(f"{s['id']:{w}} {s['access']:8} {s['storage']:10} {s['name']}")
    print(f"\n{len(rows)} sources. Details: catalog/sources.yaml")
    return 0


def cmd_manual(_args) -> int:
    todo = [s for s in _catalog() if s["access"] in ("manual", "request", "token")]
    print("Steps only you can do (see catalog/sources.yaml for details):\n")
    for s in todo:
        print(f"[{s['access']}] {s['name']}")
        print(f"    {s.get('how', '').strip()}\n")
    return 0


def _module_parser(sub, mod):
    p = sub.add_parser(mod.NAME, help=mod.HELP, description=mod.__doc__,
                       formatter_class=argparse.RawDescriptionHelpFormatter)
    if hasattr(mod, "add_arguments"):
        mod.add_arguments(p)
    p.set_defaults(func=lambda a, m=mod: m.run(a))
    return p


def _defaults(mod) -> argparse.Namespace:
    p = argparse.ArgumentParser()
    if hasattr(mod, "add_arguments"):
        mod.add_arguments(p)
    return p.parse_args([])


def cmd_all(args) -> int:
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}
    failures = []
    for name in sources.MODULE_NAMES:
        if name in skip:
            continue
        mod = sources.load(name)
        if getattr(mod, "OPTIONAL", False) and not args.include_optional:
            logging.info("skipping optional source %s (use --include-optional)", name)
            continue
        logging.info("==== %s ====", name)
        t0 = time.time()
        try:
            mod.run(_defaults(mod))
        except Exception as exc:  # keep going; report at the end
            logging.exception("%s failed", name)
            failures.append((name, exc))
        logging.info("%s finished in %.0fs", name, time.time() - t0)
    if failures:
        print("\nFAILED:", ", ".join(f"{n} ({type(e).__name__}: {e})" for n, e in failures))
        return 1
    return 0


def main(argv=None) -> int:
    for stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list all sources").set_defaults(func=cmd_list)
    sub.add_parser("manual", help="checklist of manual/request/token steps").set_defaults(func=cmd_manual)
    p_all = sub.add_parser("all", help="run every scriptable source")
    p_all.add_argument("--skip", default="", help="comma-separated source names to skip")
    p_all.add_argument("--include-optional", action="store_true",
                       help="also run optional sources (large or token-gated)")
    p_all.set_defaults(func=cmd_all)
    for name in sources.MODULE_NAMES:
        _module_parser(sub, sources.load(name))
    args = parser.parse_args(argv)
    logging.info("data dir: %s", DATA_DIR)
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
