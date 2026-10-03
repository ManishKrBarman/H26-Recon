"""Ingestion layer: alias mapping, normalisation and validation for source files.

Accepts CSVs (or DataFrames) from users or external sources whose column
names may be free-form (``Invoice No``, ``GSTIN of Supplier``,
``Taxable Value``, ``IGST Amount`` …), maps them onto the canonical ReconAI
schemas, normalises dates/numbers/rates, and reports row-level rejections
with clear reasons.

Design rules
------------
* Nothing is written until every source in a bundle validates; callers get a
  preview first (``ingest_bundle``), then commit with ``write_bundle``.
* Monetary values are normalised to plain float rupees; comparisons later use
  the tolerance constants from ``config``.
* Extended columns (GSTIN, HSN, place of supply, CGST/SGST/IGST split, period)
  are carried through when present but never required.
"""
from __future__ import annotations

import io
import re
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Union

import pandas as pd

from . import config

# ── Canonical schemas ─────────────────────────────────────────────────

REQUIRED_COLUMNS: Dict[str, List[str]] = {
    "invoices": ["invoice_id", "vendor_code", "invoice_date", "taxable_amount", "tax_rate", "tax_amount", "total_amount"],
    "ledger": ["ledger_ref", "invoice_id", "vendor_code", "entry_date", "taxable_amount", "tax_amount", "total_amount"],
    "gst_records": ["gst_ref", "invoice_id", "vendor_code", "filing_date", "taxable_amount", "tax_rate", "tax_amount"],
    "vendors": ["vendor_code", "vendor_name"],
}

# Optional columns carried through when present (extended schema).
OPTIONAL_COLUMNS: Dict[str, List[str]] = {
    "invoices": ["gstin", "hsn_code", "place_of_supply", "period", "cgst_amount", "sgst_amount", "igst_amount", "supplier_name"],
    "ledger": ["period", "narration"],
    "gst_records": ["period", "gstr_type", "cgst_amount", "sgst_amount", "igst_amount"],
    "vendors": ["gstin", "state_code"],
}

# Case-insensitive aliases → canonical column name. First match wins.
COLUMN_ALIASES: Dict[str, List[str]] = {
    "invoice_id": ["invoice_id", "invoice no", "invoice number", "invoice #", "inv no", "invno", "bill no", "bill number", "document number", "doc no", "voucher no"],
    "vendor_code": ["vendor_code", "vendor", "vendor id", "supplier code", "supplier", "supplier id", "party code", "party"],
    "invoice_date": ["invoice_date", "invoice date", "inv date", "bill date", "document date", "doc date"],
    "entry_date": ["entry_date", "entry date", "posting date", "post date", "ledger date", "gl date"],
    "filing_date": ["filing_date", "filing date", "gst date", "return date", "period date"],
    "taxable_amount": ["taxable_amount", "taxable value", "taxable amt", "taxable", "net amount", "base amount", "assessable value"],
    "tax_rate": ["tax_rate", "tax rate", "gst rate", "rate", "gst %", "tax %", "rate %"],
    "tax_amount": ["tax_amount", "tax amount", "gst amount", "total tax", "tax amt", "gst amt", "igst", "igst amount", "cgst+sgst"],
    "total_amount": ["total_amount", "total amount", "invoice total", "invoice value", "gross amount", "gross value", "total value", "grand total"],
    "ledger_ref": ["ledger_ref", "ledger ref", "ledger id", "journal ref", "entry ref", "voucher id", "gl ref"],
    "gst_ref": ["gst_ref", "gst ref", "gst id", "return ref", "ack no", "acknowledgement no", "gstr ref"],
    "vendor_name": ["vendor_name", "vendor name", "supplier name", "party name", "legal name", "trade name"],
    "gstin": ["gstin", "gstin of supplier", "supplier gstin", "gst number", "gst no", "gst identification number", "vendor gstin", "recipient gstin"],
    "hsn_code": ["hsn_code", "hsn", "hsn/sac", "hsn sac", "sac code", "service code"],
    "place_of_supply": ["place_of_supply", "place of supply", "pos", "supply state", "state"],
    "period": ["period", "tax period", "return period", "month", "filing period"],
    "gstr_type": ["gstr_type", "gstr type", "return type", "form type"],
    "cgst_amount": ["cgst_amount", "cgst", "cgst amt", "central tax"],
    "sgst_amount": ["sgst_amount", "sgst", "sgst amt", "state tax", "utgst"],
    "igst_amount": ["igst_amount", "igst amt", "integrated tax"],
    "supplier_name": ["supplier_name", "supplier name", "party name"],
    "narration": ["narration", "description", "remarks", "particulars"],
    "state_code": ["state_code", "state code"],
}

GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_MONEY_CLEAN_RE = re.compile(r"[₹$€£,\s]")
_AMBIGUOUS_DATE_RE = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})$")
_FRACTION_RATE_MAX = 1.0


@dataclass
class RejectedRow:
    row_number: int  # 1-based data row number (header excluded)
    reason: str
    raw: Dict[str, object] = field(default_factory=dict)


@dataclass
class IngestedSource:
    source: str
    frame: pd.DataFrame
    rows_in: int = 0
    rows_out: int = 0
    mapping: Dict[str, str] = field(default_factory=dict)       # canonical -> original header
    unmapped_columns: List[str] = field(default_factory=list)
    missing_required: List[str] = field(default_factory=list)
    rejected: List[RejectedRow] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and not self.missing_required

    def preview(self) -> dict:
        return {
            "source": self.source,
            "rows_in": self.rows_in,
            "rows_out": self.rows_out,
            "columns_mapped": self.mapping,
            "columns_unmapped": self.unmapped_columns,
            "missing_required_columns": self.missing_required,
            "rejected_count": len(self.rejected),
            "rejected_sample": [
                {"row": r.row_number, "reason": r.reason} for r in self.rejected[:10]
            ],
            "warnings": self.warnings[:20],
            "errors": self.errors,
        }


@dataclass
class BundleResult:
    sources: Dict[str, IngestedSource]
    errors: List[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and all(s.ok for s in self.sources.values())

    def preview(self) -> dict:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "sources": {name: src.preview() for name, src in self.sources.items()},
        }


# ── Normalisation helpers ─────────────────────────────────────────────

def normalise_money(value: object) -> Optional[float]:
    """Parse ₹1,23,456.78 / (1,234) / '' into a float or None."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null", "-", "na", "n/a"}:
        return None
    negative = text.startswith("(") and text.endswith(")")
    text = _MONEY_CLEAN_RE.sub("", text.strip("()"))
    text = text.replace("%", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


def normalise_tax_rate(value: object) -> tuple[Optional[float], bool]:
    """Return (rate_percent, was_fraction).

    Accepts ``18``, ``18%``, ``0.18`` (fraction → 18%). Returns (None, False)
    when unparseable.
    """
    number = normalise_money(value)
    if number is None:
        return None, False
    if 0 < number <= _FRACTION_RATE_MAX and ("." in str(value) or "%" not in str(value)):
        # 0.18 style fraction. 1.0 exactly is ambiguous; treat as 1% only when written as 1.
        if number < 1.0:
            return round(number * 100, 4), True
    return round(number, 4), False


_DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%Y/%m/%d", "%m/%d/%Y", "%Y%m%d")


def normalise_date(value: object) -> tuple[Optional[str], Optional[str]]:
    """Return (iso_date, warning). Day-first for ambiguous DD/MM vs MM/DD."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None, None
    if isinstance(value, (pd.Timestamp, datetime)):
        return pd.Timestamp(value).date().isoformat(), None
    text = str(value).strip()
    if not text or text.lower() in {"nan", "none", "null", "-", "na", "n/a"}:
        return None, None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date().isoformat(), None
        except ValueError:
            continue
    warning = None
    m = _AMBIGUOUS_DATE_RE.match(text)
    if m and int(m.group(1)) <= 12 and int(m.group(2)) <= 12:
        warning = f"Ambiguous date '{text}' parsed as day-first (DD/MM/YYYY)."
    parsed = pd.to_datetime(text, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return None, None
    return parsed.date().isoformat(), warning


def validate_gstin(value: object) -> bool:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return False
    return bool(GSTIN_RE.match(str(value).strip().upper()))


# ── Mapping / validation ──────────────────────────────────────────────

def map_columns(df: pd.DataFrame, source: str) -> tuple[pd.DataFrame, Dict[str, str], List[str], List[str]]:
    """Rename alias columns to canonical names.

    Returns (frame, mapping canonical→original, unmapped originals, missing required).
    """
    alias_to_canonical: Dict[str, str] = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            alias_to_canonical.setdefault(alias.lower(), canonical)

    required = REQUIRED_COLUMNS[source]
    optional = OPTIONAL_COLUMNS.get(source, [])
    allowed = set(required) | set(optional)

    mapping: Dict[str, str] = {}
    unmapped: List[str] = []
    rename: Dict[str, str] = {}
    taken: set[str] = set()
    for original in df.columns:
        key = str(original).strip().lower().replace("_", " ")
        canonical = alias_to_canonical.get(key)
        if canonical is None:
            canonical = alias_to_canonical.get(str(original).strip().lower())
        if canonical and canonical in allowed and canonical not in taken:
            mapping[canonical] = str(original)
            rename[original] = canonical
            taken.add(canonical)
        else:
            unmapped.append(str(original))

    out = df.rename(columns=rename)
    # Drop unmapped columns except identifier passthrough columns that are harmless.
    keep = [c for c in out.columns if c in allowed or c in rename.values()]
    out = out[[c for c in keep if c in out.columns]]
    missing = [c for c in required if c not in out.columns]
    return out, mapping, unmapped, missing


def _normalise_frame(df: pd.DataFrame, source: str) -> tuple[pd.DataFrame, List[RejectedRow], List[str]]:
    rejected: List[RejectedRow] = []
    warnings: List[str] = []
    out = df.copy()

    date_cols = {"invoices": ["invoice_date"], "ledger": ["entry_date"], "gst_records": ["filing_date"], "vendors": []}[source]
    money_cols = [c for c in ["taxable_amount", "tax_amount", "total_amount", "cgst_amount", "sgst_amount", "igst_amount"] if c in out.columns]
    rate_cols = [c for c in ["tax_rate"] if c in out.columns]

    ambiguous_seen = False
    fraction_seen = False
    for col in date_cols:
        parsed, warns = [], []
        for v in out[col]:
            iso, w = normalise_date(v)
            parsed.append(iso)
            warns.append(w)
        if any(w for w in warns):
            ambiguous_seen = True
        out[col] = parsed
    for col in money_cols:
        out[col] = [normalise_money(v) for v in out[col]]
    for col in rate_cols:
        values, fractions = [], []
        for v in out[col]:
            rate, frac = normalise_tax_rate(v)
            values.append(rate)
            fractions.append(frac)
        if any(fractions):
            fraction_seen = True
        out[col] = values

    if ambiguous_seen:
        warnings.append("Some dates were ambiguous (e.g. 05/08/2026); parsed day-first (DD/MM/YYYY).")
    if fraction_seen:
        warnings.append("Some tax rates looked like fractions (0.18); converted to percentages (18%).")

    # Derive total_amount when missing but taxable+tax are present (deterministic arithmetic).
    if source in {"invoices", "ledger"} and "total_amount" in out.columns:
        derivable = out["total_amount"].isna() & out["taxable_amount"].notna() & out["tax_amount"].notna()
        if derivable.any():
            out.loc[derivable, "total_amount"] = (out.loc[derivable, "taxable_amount"] + out.loc[derivable, "tax_amount"]).round(2)
            warnings.append(f"Derived total_amount for {int(derivable.sum())} row(s) from taxable_amount + tax_amount.")

    # Row-level rejection rules.
    id_col = {"invoices": "invoice_id", "ledger": "ledger_ref", "gst_records": "gst_ref", "vendors": "vendor_code"}[source]
    link_col = "invoice_id" if source in {"ledger", "gst_records"} else None
    for idx, row in out.iterrows():
        row_number = int(idx) + 1 if isinstance(idx, (int,)) else len(rejected) + 1
        problems: List[str] = []
        if row.get(id_col) is None or str(row.get(id_col)).strip() in {"", "nan"}:
            problems.append(f"{id_col} is missing")
        if link_col and (row.get(link_col) is None or str(row.get(link_col)).strip() in {"", "nan"}):
            problems.append(f"{link_col} is missing")
        for col in date_cols:
            if row.get(col) is None:
                problems.append(f"{col} could not be parsed as a date")
        for col in money_cols:
            if pd.isna(row.get(col)):
                problems.append(f"{col} is not numeric")
        for col in rate_cols:
            if pd.isna(row.get(col)):
                problems.append(f"{col} is not numeric")
        if problems:
            rejected.append(RejectedRow(row_number=row_number, reason="; ".join(problems), raw=row.to_dict()))

    if rejected:
        bad_index = [r.row_number - 1 for r in rejected]
        out = out.drop(index=[i for i in bad_index if i in out.index]).reset_index(drop=True)

    # GSTIN validation (warning-level; extended column).
    if "gstin" in out.columns:
        bad = int((~out["gstin"].map(validate_gstin)).sum()) if len(out) else 0
        if bad:
            warnings.append(f"{bad} row(s) have a GSTIN that does not match the 15-character format; kept but flagged.")

    return out, rejected, warnings


def ingest_dataframe(df: pd.DataFrame, source: str) -> IngestedSource:
    """Map + normalise + validate a raw DataFrame for one source type."""
    if source not in REQUIRED_COLUMNS:
        raise ValueError(f"Unknown source '{source}'. Expected one of {sorted(REQUIRED_COLUMNS)}")
    rows_in = len(df)
    mapped, mapping, unmapped, missing = map_columns(df, source)
    src = IngestedSource(source=source, frame=mapped, rows_in=rows_in, mapping=mapping,
                         unmapped_columns=unmapped, missing_required=missing)
    if missing:
        src.errors.append(f"{source}: required column(s) missing after alias mapping: {', '.join(missing)}")
        src.rows_out = 0
        return src
    frame, rejected, warnings = _normalise_frame(mapped, source)
    src.frame = frame
    src.rejected = rejected
    src.warnings = warnings
    src.rows_out = len(frame)
    if rows_in and src.rows_out == 0:
        src.errors.append(f"{source}: every row was rejected during validation.")
    return src


def read_csv_bytes(content: Union[bytes, bytearray], source: str) -> pd.DataFrame:
    try:
        return pd.read_csv(io.BytesIO(bytes(content)), dtype=str, keep_default_na=False)
    except Exception as exc:  # pragma: no cover - pandas raises many types
        raise ValueError(f"Could not parse {source} CSV: {exc}") from exc


def read_csv_path(path: Union[str, Path], source: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"{source}: file not found at {p}")
    try:
        return pd.read_csv(p, dtype=str, keep_default_na=False)
    except Exception as exc:
        raise ValueError(f"Could not parse {source} CSV at {p}: {exc}") from exc


def ingest_bundle(files: Mapping[str, Union[bytes, bytearray, Path, str]]) -> BundleResult:
    """Ingest a set of sources (bytes or paths) and return a validated preview."""
    sources: Dict[str, IngestedSource] = {}
    errors: List[str] = []
    for source, payload in files.items():
        try:
            if isinstance(payload, (bytes, bytearray)):
                raw = read_csv_bytes(payload, source)
            else:
                raw = read_csv_path(payload, source)
            sources[source] = ingest_dataframe(raw, source)
        except (ValueError, FileNotFoundError) as exc:
            errors.append(str(exc))
    return BundleResult(sources=sources, errors=errors)


# ── Commit to disk ────────────────────────────────────────────────────

def backup_existing(data_dir: Path, names: Iterable[str]) -> Optional[Path]:
    """Copy existing CSVs into a timestamped backup folder. Returns folder or None."""
    existing = [data_dir / f"{name}.csv" for name in names if (data_dir / f"{name}.csv").exists()]
    if not existing:
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = data_dir / "backups" / stamp
    backup_dir.mkdir(parents=True, exist_ok=True)
    for path in existing:
        shutil.copy2(path, backup_dir / path.name)
    return backup_dir


def write_bundle(bundle: BundleResult, data_dir: Optional[Path] = None, backup: bool = True) -> Optional[Path]:
    """Persist a validated bundle to canonical CSV names. Refuses invalid bundles."""
    if not bundle.ok:
        raise ValueError("Refusing to write an invalid bundle; fix errors and retry.")
    data_dir = Path(data_dir) if data_dir else config.DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)
    backup_dir = backup_existing(data_dir, bundle.sources.keys()) if backup else None
    for source, src in bundle.sources.items():
        src.frame.to_csv(data_dir / f"{source}.csv", index=False)
    return backup_dir
