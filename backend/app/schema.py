from sqlalchemy import Boolean, Date, Float, Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB_PATH = ROOT / "data" / "reconai.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

class Base(DeclarativeBase):
    pass

class Vendor(Base):
    __tablename__ = "vendors"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    vendor_code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    vendor_name: Mapped[str] = mapped_column(String(255), index=True)
    gstin: Mapped[str] = mapped_column(String(20), unique=True)

class Invoice(Base):
    __tablename__ = "invoices"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[str] = mapped_column(String(80), index=True)
    vendor_code: Mapped[str] = mapped_column(String(50), index=True)
    invoice_date: Mapped[object] = mapped_column(Date)
    taxable_amount: Mapped[float] = mapped_column(Float)
    tax_rate: Mapped[float] = mapped_column(Float)
    tax_amount: Mapped[float] = mapped_column(Float)
    total_amount: Mapped[float] = mapped_column(Float)

class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ledger_ref: Mapped[str] = mapped_column(String(80), index=True)
    invoice_id: Mapped[str] = mapped_column(String(80), index=True)
    vendor_code: Mapped[str] = mapped_column(String(50), index=True)
    entry_date: Mapped[object] = mapped_column(Date)
    taxable_amount: Mapped[float] = mapped_column(Float)
    tax_amount: Mapped[float] = mapped_column(Float)
    total_amount: Mapped[float] = mapped_column(Float)

class GSTRecord(Base):
    __tablename__ = "gst_records"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    gst_ref: Mapped[str] = mapped_column(String(80), index=True)
    invoice_id: Mapped[str] = mapped_column(String(80), index=True)
    vendor_code: Mapped[str] = mapped_column(String(50), index=True)
    filing_date: Mapped[object] = mapped_column(Date)
    taxable_amount: Mapped[float] = mapped_column(Float)
    tax_rate: Mapped[float] = mapped_column(Float)
    tax_amount: Mapped[float] = mapped_column(Float)

class DiscrepancyTruth(Base):
    __tablename__ = "discrepancy_truth"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[str] = mapped_column(String(80), index=True)
    discrepancy_type: Mapped[str] = mapped_column(String(50), index=True)
    affected_table: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(String(500))
    injected: Mapped[bool] = mapped_column(Boolean, default=True)

engine = create_engine(f"sqlite:///{DB_PATH}", future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

def init_db() -> None:
    Base.metadata.create_all(engine)
