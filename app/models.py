"""Data structures shared by extraction, validation and evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Line:
    description: str
    qty: int
    unit_price: float
    amount: float


@dataclass
class Extracted:
    """Fields read from one invoice. None means "not found"."""

    vendor: str | None = None
    invoice_number: str | None = None
    date: str | None = None  # ISO yyyy-mm-dd
    currency: str | None = None
    subtotal: float | None = None
    vat_rate: float | None = None  # 0.20 means 20 %
    vat: float | None = None
    total: float | None = None
    lines: list[Line] = field(default_factory=list)
    source: str = "text"  # "text" = PDF text layer, "ocr" = Tesseract
    # 1.0 = found next to a clear label, lower = guessed by a fallback rule
    confidence: dict[str, float] = field(default_factory=dict)


@dataclass
class Result:
    decision: str  # approved | review | rejected
    reasons: list[str]
    extracted: Extracted
