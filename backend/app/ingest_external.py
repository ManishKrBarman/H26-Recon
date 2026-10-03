"""CLI: ingest external source files (Drive snapshot / inbox drop) into the live data dir.

Usage (from backend/):
    python -m app.ingest_external                 # ingest data/external/inbox, then drive/data
    python -m app.ingest_external --run-pipeline  # ...and run the full pipeline afterwards
    python -m app.ingest_external --source /path  # ingest a specific directory

Files are identified by their *columns* (alias mapping), not just filenames, so
differently named exports (``Purchase Register.xlsx``-style headers, ``GSTR-2B``
exports …) still land on the right canonical table. Only CSV is read here; the
Drive snapshot and inbox convention is CSV-in / CSV-out.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config
from .ingest import BundleResult, ingest_bundle, write_bundle

SOURCE_ORDER = ("invoices", "ledger", "gst_records", "vendors")


def find_source_files(directories: list[Path]) -> dict[str, Path]:
    """Scan directories and classify CSVs by their header columns."""
    found: dict[str, Path] = {}
    for directory in directories:
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.csv")):
            from .ingest import REQUIRED_COLUMNS, map_columns
            import pandas as pd

            try:
                header = pd.read_csv(path, nrows=0)
            except Exception:
                continue
            best, best_hits = None, 0
            for source, required in REQUIRED_COLUMNS.items():
                _, _, _, missing = map_columns(header, source)
                hits = len(required) - len(missing)
                if hits > best_hits:
                    best, best_hits = source, hits
            if best and best_hits >= 3 and best not in found:
                found[best] = path
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest external CSVs into ReconAI's data dir.")
    parser.add_argument("--source", type=Path, default=None,
                        help="Specific directory to ingest (default: inbox, then Drive snapshot).")
    parser.add_argument("--run-pipeline", action="store_true", help="Run the full pipeline after ingestion.")
    parser.add_argument("--no-backup", action="store_true", help="Skip timestamped backup of existing CSVs.")
    args = parser.parse_args(argv)

    config.ensure_dirs()
    directories = [args.source] if args.source else [
        config.EXTERNAL_DIR / "inbox",
        config.DRIVE_DIR / "data",
    ]
    found = find_source_files(directories)
    if not found:
        print(f"No CSV sources found in: {[str(d) for d in directories]}")
        print("Drop files into data/external/inbox/ (or data/external/drive/data/) and rerun.")
        return 1

    print("Classified source files:")
    for source, path in found.items():
        print(f"  {source:12s} ← {path}")

    bundle: BundleResult = ingest_bundle(found)
    print(bundle.preview())
    if not bundle.ok:
        print("\nIngestion FAILED — live data untouched.", file=sys.stderr)
        return 2

    backup_dir = write_bundle(bundle, backup=not args.no_backup)
    print(f"\nWrote {sorted(bundle.sources)} to {config.DATA_DIR}"
          + (f" (previous files backed up to {backup_dir})" if backup_dir else ""))
    if "vendors" in bundle.sources:
        print("Vendor master ingested; GSTINs validated at ingest time.")

    if args.run_pipeline:
        from .pipeline import run_pipeline
        result = run_pipeline()
        print(f"\nPipeline {'OK' if result.ok else 'FAILED'} in {result.total_elapsed_s}s")
        if not result.ok:
            return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
