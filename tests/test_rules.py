from datetime import date

from app.extraction.parse import parse_text
from app.pipeline import decide
from app.validation.rules import Context
from tests.test_parse import SAMPLE_EN


def ctx() -> Context:
    return Context(known_vendors={"Northwind Logistics Ltd"}, today=date(2026, 11, 15))


def test_clean_invoice_is_approved():
    result = decide(parse_text(SAMPLE_EN), ctx())
    assert result.decision == "approved", result.reasons


def test_wrong_total_goes_to_review():
    result = decide(parse_text(SAMPLE_EN.replace("Total 64.80", "Total 74.80")), ctx())
    assert result.decision == "review"
    assert "total_mismatch" in result.reasons


def test_wrong_vat_goes_to_review():
    text = SAMPLE_EN.replace("VAT (20%) 10.80", "VAT (20%) 12.80").replace("64.80", "66.80")
    result = decide(parse_text(text), ctx())
    assert "vat_mismatch" in result.reasons


def test_unknown_vendor_goes_to_review():
    text = SAMPLE_EN.replace("Northwind Logistics Ltd", "Totally New Supplier Ltd")
    assert "unknown_vendor" in decide(parse_text(text), ctx()).reasons


def test_ocr_typo_in_vendor_still_matches():
    text = SAMPLE_EN.replace("Northwind Logistics Ltd", "Northwlnd Logistics Ltd")
    assert "unknown_vendor" not in decide(parse_text(text), ctx()).reasons


def test_second_copy_is_duplicate():
    c = ctx()
    assert decide(parse_text(SAMPLE_EN), c).decision == "approved"
    second = decide(parse_text(SAMPLE_EN), c)
    assert "duplicate" in second.reasons


def test_empty_document_is_rejected():
    assert decide(parse_text(""), ctx()).decision == "rejected"


def test_future_date_goes_to_review():
    text = SAMPLE_EN.replace("Date: 2026-03-14", "Date: 2027-03-14")
    assert "date_out_of_range" in decide(parse_text(text), ctx()).reasons
