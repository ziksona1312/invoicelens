"""The whole flow for one document: read, parse, validate, decide."""

from __future__ import annotations

from pathlib import Path

from app.extraction.parse import parse_text
from app.extraction.text import read_text
from app.models import Extracted, Result
from app.validation.rules import Context, check


def extract(path: str | Path) -> Extracted:
    """Pure function of the file: safe to run in parallel."""
    text, source = read_text(path)
    return parse_text(text, source)


def decide(ex: Extracted, ctx: Context) -> Result:
    """Stateful because of duplicate detection: call in arrival order."""
    if not (ex.vendor or ex.invoice_number or ex.total):
        return Result("rejected", ["unreadable"], ex)
    reasons = check(ex, ctx)
    return Result("review" if reasons else "approved", reasons, ex)


def process(path: str | Path, ctx: Context) -> Result:
    return decide(extract(path), ctx)
