"""Business rules. Each rule returns a short reason code; no reasons means the invoice is clean."""

from __future__ import annotations

import difflib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta

from app.models import Extracted

MONEY_TOLERANCE = 0.02  # rounding differences between lines, VAT and total
MIN_CONFIDENCE = 0.7
CRITICAL_FIELDS = ("vendor", "invoice_number", "date", "total")
MAX_AGE_DAYS = 3 * 365


def normalize_vendor(name: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", "", name.lower())).strip()


@dataclass
class Context:
    """State the rules need: who we buy from, what we have already seen, and what day it is."""

    known_vendors: set[str]
    today: date = field(default_factory=date.today)
    seen: set[tuple[str, str]] = field(default_factory=set)
    # Optional shared store for duplicates (the service uses PostgreSQL). Returns True when this
    # document is the first one with that key, False when another document already owns it.
    claim_key: Callable[[tuple[str, str]], bool] | None = None


def is_known_vendor(vendor: str, known: set[str]) -> bool:
    """Fuzzy match, because OCR can misread a letter or two."""
    wanted = normalize_vendor(vendor)
    normalized = {normalize_vendor(v) for v in known}
    return bool(difflib.get_close_matches(wanted, normalized, n=1, cutoff=0.85))


def check(ex: Extracted, ctx: Context) -> list[str]:
    reasons: list[str] = []

    missing = [f for f in CRITICAL_FIELDS if getattr(ex, f) is None]
    if missing:
        reasons.append("missing_fields:" + ",".join(missing))
    low = [
        f
        for f in CRITICAL_FIELDS
        if ex.confidence.get(f, 1.0) < MIN_CONFIDENCE and f not in missing
    ]
    if low:
        reasons.append("low_confidence:" + ",".join(low))

    if ex.vendor and not is_known_vendor(ex.vendor, ctx.known_vendors):
        reasons.append("unknown_vendor")

    if ex.date:
        parsed = date.fromisoformat(ex.date)
        if parsed > ctx.today or parsed < ctx.today - timedelta(days=MAX_AGE_DAYS):
            reasons.append("date_out_of_range")

    lines_sum = round(sum(ln.amount for ln in ex.lines), 2) if ex.lines else None
    base = ex.subtotal if ex.subtotal is not None else lines_sum

    if ex.subtotal is not None and lines_sum is not None:
        if abs(ex.subtotal - lines_sum) > MONEY_TOLERANCE:
            reasons.append("line_sum_mismatch")
    if base is not None and ex.vat_rate is not None and ex.vat is not None:
        if abs(base * ex.vat_rate - ex.vat) > MONEY_TOLERANCE:
            reasons.append("vat_mismatch")
    if base is not None and ex.vat is not None and ex.total is not None:
        if abs(base + ex.vat - ex.total) > MONEY_TOLERANCE:
            reasons.append("total_mismatch")

    if ex.vendor and ex.invoice_number:
        key = (normalize_vendor(ex.vendor), ex.invoice_number)
        if ctx.claim_key is not None:
            if not ctx.claim_key(key):
                reasons.append("duplicate")
        else:
            if key in ctx.seen:
                reasons.append("duplicate")
            ctx.seen.add(key)

    return reasons
