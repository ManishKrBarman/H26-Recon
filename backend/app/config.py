"""Centralised configuration for ReconAI.

All data/model/database paths derive from these constants so that the
pipeline, API, CLI tools and tests agree on where state lives.  Paths can
be overridden with environment variables:

    RECON_DATA_DIR    – directory for CSV/DB/KB state   (default: <repo>/data)
    RECON_MODELS_DIR  – directory for ML artifacts      (default: <repo>/models)
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = Path(os.environ.get("RECON_DATA_DIR", str(ROOT / "data")))
MODELS_DIR = Path(os.environ.get("RECON_MODELS_DIR", str(ROOT / "models")))
EXTERNAL_DIR = DATA_DIR / "external"
DRIVE_DIR = EXTERNAL_DIR / "drive"

DB_PATH = DATA_DIR / "reconai.db"
KB_PATH = DATA_DIR / "gst_knowledge_base.json"


def reconfigure() -> None:
    """Re-read env overrides (used by tests) and rebind all derived paths.

    Module-level constants (``config.DATA_DIR``, ``config.DB_PATH`` …) are
    rebound to new Path objects so importers that captured the name
    (``from . import config; config.DB_PATH``) always see current values.
    Importers that did ``from .config import DB_PATH`` keep the old object —
    use ``config.X`` form everywhere.
    """
    global DATA_DIR, MODELS_DIR, EXTERNAL_DIR, DRIVE_DIR, DB_PATH, KB_PATH, PIPELINE_LOCK_PATH
    DATA_DIR = Path(os.environ.get("RECON_DATA_DIR", str(ROOT / "data")))
    MODELS_DIR = Path(os.environ.get("RECON_MODELS_DIR", str(ROOT / "models")))
    EXTERNAL_DIR = DATA_DIR / "external"
    DRIVE_DIR = EXTERNAL_DIR / "drive"
    DB_PATH = DATA_DIR / "reconai.db"
    KB_PATH = DATA_DIR / "gst_knowledge_base.json"
    PIPELINE_LOCK_PATH = DATA_DIR / ".pipeline.lock"

# Externally provided evaluation labels (fetched from the Drive folder).
DRIVE_GROUND_TRUTH_PATH = EXTERNAL_DIR / "ground_truth_drive.csv"

# Demo dataset size used when the data directory is empty (README parity).
DEMO_INVOICE_COUNT = int(os.environ.get("RECON_DEMO_INVOICES", "1000"))
DEMO_SEED = int(os.environ.get("RECON_DEMO_SEED", "42"))

# Pipeline lock / runs state
PIPELINE_LOCK_PATH = DATA_DIR / ".pipeline.lock"
LOCK_STALE_SECONDS = int(os.environ.get("RECON_LOCK_STALE_SECONDS", "900"))

# Monetary tolerance constants (₹). Never compare floats for equality.
MONEY_TOLERANCE = 1.00
# GST slabs (percent). The ingestion layer extends this with slabs seen in real data.
GST_SLABS = (0.0, 5.0, 12.0, 18.0, 28.0)


def ensure_dirs() -> None:
    PIPELINE_LOCK_PATH = DATA_DIR / ".pipeline.lock"

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    EXTERNAL_DIR.mkdir(parents=True, exist_ok=True)
