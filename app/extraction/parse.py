"""Turn raw invoice text into fields. Rules only, no ML: every decision can be explained."""

from __future__ import annotations

import re
from datetime import date

from app.models import Extracted, Line

# 1,234.50 and 1.234,50 and 1234.50 and 1234,50. The last separator is always the decimal one.
_AMT = r"(?<![\d.,])(?:\d{1,3}(?:[.,]\d{3})*[.,]\d{2}|\d+[.,]\d{2})(?!\d)"
AMOUNT_RE = re.compile(_AMT)

ROW_RE = re.compile(
    rf"^(?P<desc>.+?)\s+(?P<qty>\d{{1,4}})\s+(?P<unit>{_AMT})\s+(?P<amt>{_AMT})\s*$"
)

INVOICE_NO_RE = re.compile(
    r"(?:invoice\s*(?:no\.?|number|#)|inv\.?\s*no\.?|faktura\s*(?:br\.?|broj)|racun\s*(?:br\.?|broj))"
    r"\s*[:#]?\s*([A-Z0-9][A-Z0-9\-/]{3,})",
    re.IGNORECASE,
)
DATE_LABEL_RE = re.compile(r"\b(date|issued|datum)\b", re.IGNORECASE)
NOT_ISSUE_DATE_RE = re.compile(r"due|valut|rok\s*pla", re.IGNORECASE)

TITLE_ONLY_RE = re.compile(r"^(tax\s+)?(invoice|faktura|racun)$", re.IGNORECASE)
SUBTOTAL_RE = re.compile(r"\b(sub[\s-]?total|osnovica|ukupno\s+bez\s+pdv)", re.IGNORECASE)
VAT_RE = re.compile(r"\b(vat|pdv|tax)\b", re.IGNORECASE)
TOTAL_RE = re.compile(
    r"\b(grand\s+total|amount\s+due|total\s+due|ukupno\s+za\s+uplatu|ukupno|total)\b",
    re.IGNORECASE,
)
RATE_RE = re.compile(r"(\d{1,2}(?:[.,]\d+)?)\s*%")

CURRENCY_CODES = ("EUR", "USD", "GBP", "RSD", "CHF")
CURRENCY_SYMBOLS = (("€", "EUR"), ("$", "USD"), ("£", "GBP"))

MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}


def parse_amount(text: str) -> float:
    """'1.234,50' -> 1234.5 and '1,234.50' -> 1234.5."""
    sep = max(text.rfind("."), text.rfind(","))
    if sep == -1:
        return float(text)
    integer = re.sub(r"[.,\s]", "", text[:sep])
    return float(f"{integer}.{text[sep + 1 :]}")


def find_date(text: str) -> str | None:
    """First date in the text, as ISO yyyy-mm-dd. Numeric dates are read day-first."""
    candidates: list[tuple[int, int, int]] = []
    if m := re.search(r"(\d{4})-(\d{2})-(\d{2})", text):
        candidates.append((int(m[1]), int(m[2]), int(m[3])))
    if m := re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", text):
        candidates.append((int(m[3]), int(m[2]), int(m[1])))
    if m := re.search(r"(\d{1,2})\s+([A-Za-z]{3})[a-z]*\.?,?\s+(\d{4})", text):
        month = MONTHS.get(m[2].lower())
        if month:
            candidates.append((int(m[3]), month, int(m[1])))
    for y, mo, d in candidates:
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            continue
    return None


def _last_amount(line: str) -> float | None:
    found = AMOUNT_RE.findall(line)
    return parse_amount(found[-1]) if found else None


def find_currency(text: str) -> tuple[str | None, float]:
    counts = {c: len(re.findall(rf"\b{c}\b", text)) for c in CURRENCY_CODES}
    best = max(counts, key=lambda c: counts[c])
    if counts[best]:
        return best, 1.0
    for symbol, code in CURRENCY_SYMBOLS:
        if symbol in text:
            return code, 0.8  # a symbol is weaker evidence than an ISO code
    return None, 0.0


def parse_text(text: str, source: str = "text") -> Extracted:
    ex = Extracted(source=source)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    conf = ex.confidence

    # Vendor: the first line that is not just the document title. The title is often printed in
    # a bigger font on the same row, so the text layer can put it on a line of its own, above.
    for ln in lines:
        if TITLE_ONLY_RE.match(ln):
            continue
        vendor = re.sub(r"\s+(INVOICE|FAKTURA|RACUN)\b.*$", "", ln, flags=re.IGNORECASE)
        ex.vendor = vendor.strip() or None
        conf["vendor"] = 1.0 if ex.vendor else 0.0
        break

    for ln in lines:
        if ex.invoice_number is None and (m := INVOICE_NO_RE.search(ln)):
            ex.invoice_number = m[1].rstrip("-/")
            conf["invoice_number"] = 1.0

        if ex.date is None and DATE_LABEL_RE.search(ln) and not NOT_ISSUE_DATE_RE.search(ln):
            label = DATE_LABEL_RE.search(ln)
            if label and (found := find_date(ln[label.end() :])):
                ex.date, conf["date"] = found, 1.0

        amount = _last_amount(ln)
        if amount is not None:
            if SUBTOTAL_RE.search(ln):
                ex.subtotal, conf["subtotal"] = amount, 1.0
            elif VAT_RE.search(ln):
                ex.vat, conf["vat"] = amount, 1.0
                if rate := RATE_RE.search(ln):
                    ex.vat_rate = float(rate[1].replace(",", ".")) / 100
                    conf["vat_rate"] = 1.0
            elif TOTAL_RE.search(ln):
                ex.total, conf["total"] = amount, 1.0  # last match wins: totals sit at the bottom

        if row := ROW_RE.match(ln):
            ex.lines.append(
                Line(
                    description=row["desc"],
                    qty=int(row["qty"]),
                    unit_price=parse_amount(row["unit"]),
                    amount=parse_amount(row["amt"]),
                )
            )

    # Fallbacks: weaker guesses, marked with lower confidence so validation can react.
    if ex.date is None and (found := find_date(text)):
        ex.date, conf["date"] = found, 0.5
    if ex.total is None:
        amounts = [parse_amount(a) for a in AMOUNT_RE.findall(text)]
        if amounts:
            ex.total, conf["total"] = max(amounts), 0.5

    ex.currency, conf["currency"] = find_currency(text)
    return ex
