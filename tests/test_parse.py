from app.extraction.parse import find_date, parse_amount, parse_text


def test_parse_amount_both_formats():
    assert parse_amount("1,234.50") == 1234.5
    assert parse_amount("1.234,50") == 1234.5
    assert parse_amount("1234,50") == 1234.5
    assert parse_amount("12.345.678,90") == 12345678.9


def test_find_date_formats():
    assert find_date("2026-03-14") == "2026-03-14"
    assert find_date("14/03/2026") == "2026-03-14"
    assert find_date("14.3.2026.") == "2026-03-14"
    assert find_date("14 Mar 2026") == "2026-03-14"
    assert find_date("31/02/2026") is None  # not a real date


SAMPLE_EN = """INVOICE
Northwind Logistics Ltd
14 Mill Lane, Leeds
VAT ID: 12345678
Invoice No: INV-2026-01007
Date: 2026-03-14
Due date: 2026-04-13
Currency: EUR
Description Qty Unit price Total
Safety gloves 3 12.50 37.50
USB-C cable 2m 2 8.25 16.50
Subtotal 54.00
VAT (20%) 10.80
Total 64.80
"""

SAMPLE_SR = """Dunav Trgovina doo FAKTURA
Faktura br.: 2026/1014
Datum izdavanja: 14.3.2026.
Datum valute: 13.4.2026.
Opis Kolicina Cena Iznos
Magacinska polica 2 1.200,00 2.400,00
Osnovica 2.400,00
PDV 20% 480,00
Ukupno za uplatu RSD 2.880,00
"""


def test_parse_english_invoice():
    ex = parse_text(SAMPLE_EN)
    assert ex.vendor == "Northwind Logistics Ltd"  # title line skipped
    assert ex.invoice_number == "INV-2026-01007"
    assert ex.date == "2026-03-14"  # not the due date
    assert ex.currency == "EUR"
    assert (ex.subtotal, ex.vat, ex.total) == (54.0, 10.8, 64.8)
    assert ex.vat_rate == 0.2
    assert len(ex.lines) == 2
    assert ex.lines[1].description == "USB-C cable 2m"


def test_parse_serbian_invoice():
    ex = parse_text(SAMPLE_SR)
    assert ex.vendor == "Dunav Trgovina doo"
    assert ex.invoice_number == "2026/1014"
    assert ex.date == "2026-03-14"  # "Datum valute" ignored
    assert ex.currency == "RSD"
    assert (ex.subtotal, ex.vat, ex.total) == (2400.0, 480.0, 2880.0)


def test_total_fallback_has_low_confidence():
    ex = parse_text("Some Vendor\nSomething 10.00\nOther 99.90\n")
    assert ex.total == 99.9
    assert ex.confidence["total"] < 0.7
