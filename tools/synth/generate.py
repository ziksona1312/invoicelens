"""Synthetic invoice generator.

Makes PDF invoices in four layouts (two English, two Serbian-in-ASCII), at three quality levels,
with a ground-truth JSON next to every file. Some invoices carry a deliberate defect so we can
measure whether validation catches it. Fully deterministic for a given --seed.

    python -m tools.synth.generate --n 300 --out data/synth --seed 42
"""

from __future__ import annotations

import argparse
import copy
import io
import json
import random
from pathlib import Path

import numpy as np
import pdfplumber
from PIL import Image, ImageEnhance, ImageFilter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

# ---------------------------------------------------------------- data pools (all invented)
KNOWN_VENDORS = {
    "en": [
        "Northwind Logistics Ltd",
        "Brightline Supplies Inc",
        "Kestrel Industrial Ltd",
        "Harbor Point Services",
        "Lumen Office Products",
        "Granite Peak Trading",
        "Silverleaf Packaging Ltd",
        "Ironwood Freight Co",
    ],
    "sr": [
        "Dunav Trgovina doo",
        "Sumadija Promet doo",
        "Tamis Servis doo",
        "Morava Pak doo",
        "Fruska Gora Oprema doo",
        "Banat Logistika doo",
        "Kosava Kancelarija doo",
        "Sava Komerc doo",
    ],
}
UNKNOWN_VENDORS = {
    "en": ["Quickfix Wholesale Ltd", "Redwood Imports Inc", "Zenith Parts Co"],
    "sr": ["Brzi Promet doo", "Novi Dom Trade doo", "Zlatibor Uvoz doo"],
}
ITEMS = {
    "en": [
        "Cardboard boxes (50 pack)",
        "Pallet wrap film",
        "Label printer ribbon",
        "Safety gloves",
        "Warehouse shelving unit",
        "USB-C cable 2m",
        "Thermal paper rolls",
        "Cleaning supplies set",
        "Forklift battery service",
        "Packing tape 48mm",
        "Delivery pallet",
        "Laser toner cartridge",
    ],
    "sr": [
        "Kartonske kutije (50 kom)",
        "Strec folija",
        "Termalni rolni",
        "Zastitne rukavice",
        "Magacinska polica",
        "USB-C kabl 2m",
        "Set za ciscenje",
        "Servis viljuskara",
        "Selotejp 48mm",
        "Transportna paleta",
        "Toner za stampac",
        "Kancelarijski papir A4",
    ],
}
ADDRESSES = {
    "en": ["14 Mill Lane, Leeds", "220 Harbour Road, Bristol", "9 Station Street, Derby"],
    "sr": [
        "Bulevar Oslobodjenja 14, Novi Sad",
        "Knez Mihailova 22, Beograd",
        "Vojvode Stepe 9, Nis",
    ],
}
MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

TEMPLATES = {"en": ["classic_en", "compact_en"], "sr": ["sr_standard", "sr_racun"]}
NOISE_LEVELS = ["clean", "scanned", "degraded"]
NOISE_WEIGHTS = [0.40, 0.35, 0.25]
DEFECTS = ["total_mismatch", "vat_mismatch", "unknown_vendor", "duplicate"]


# ---------------------------------------------------------------- formatting
def money(x: float, locale: str) -> str:
    s = f"{x:,.2f}"
    if locale == "sr":  # 1.234,50
        s = s.replace(",", "X").replace(".", ",").replace("X", ".")
    return s


def fmt_date(iso: str, style: str) -> str:
    y, m, d = iso.split("-")
    if style == "iso":
        return iso
    if style == "dmy_slash":
        return f"{d}/{m}/{y}"
    if style == "dmy_dot":
        return f"{int(d)}.{int(m)}.{y}."
    return f"{int(d)} {MONTH_NAMES[int(m) - 1]} {y}"  # "14 Mar 2026"


def add_days(iso: str, days: int) -> str:
    from datetime import date, timedelta

    return (date.fromisoformat(iso) + timedelta(days=days)).isoformat()


# ---------------------------------------------------------------- invoice data
def build_invoice(rng: random.Random, idx: int, locale: str, template: str) -> dict:
    n_lines = rng.randint(1, 6)
    lines: list[dict] = []
    for desc in rng.sample(ITEMS[locale], n_lines):
        qty = rng.randint(1, 20)
        unit = round(rng.uniform(5, 900), 2)
        lines.append(
            {"description": desc, "qty": qty, "unit_price": unit, "amount": round(qty * unit, 2)}
        )
    subtotal = round(sum(ln["amount"] for ln in lines), 2)
    vat_rate = rng.choice([0.20, 0.19, 0.10] if locale == "en" else [0.20, 0.10])
    vat = round(subtotal * vat_rate, 2)
    currency = rng.choice(["EUR", "USD", "GBP"] if locale == "en" else ["RSD", "RSD", "EUR"])
    year, month, day = 2025 + rng.randint(0, 1), rng.randint(1, 10), rng.randint(1, 28)
    number = 1000 + idx * 7 + rng.randint(0, 6)
    number_fmt = {
        "classic_en": f"INV-2026-{number:05d}",
        "compact_en": f"{rng.choice(['AB', 'KT', 'NW'])}{number:06d}",
        "sr_standard": f"2026/{number:04d}",
        "sr_racun": f"FA-{number:05d}/26",
    }[template]
    date_style = {
        "classic_en": "iso",
        "compact_en": "long",
        "sr_standard": "dmy_dot",
        "sr_racun": "dmy_slash",
    }[template]
    return {
        "locale": locale,
        "template": template,
        "vendor": rng.choice(KNOWN_VENDORS[locale]),
        "address": rng.choice(ADDRESSES[locale]),
        "vat_id": f"{rng.randint(10_000_000, 99_999_999)}",
        "invoice_number": number_fmt,
        "date": f"{year:04d}-{month:02d}-{day:02d}",
        "date_style": date_style,
        "currency": currency,
        "lines": lines,
        "subtotal": subtotal,
        "vat_rate": vat_rate,
        "vat": vat,
        "total": round(subtotal + vat, 2),
    }


def apply_defect(rng: random.Random, inv: dict, defect: str) -> None:
    """Change what is PRINTED, so the ground truth stays equal to what the document shows."""
    if defect == "total_mismatch":
        inv["total"] = round(inv["total"] + rng.choice([-1, 1]) * rng.uniform(5, 200), 2)
    elif defect == "vat_mismatch":
        inv["vat"] = round(inv["vat"] * rng.uniform(1.15, 1.6), 2)
        inv["total"] = round(inv["subtotal"] + inv["vat"], 2)  # consistent total: only VAT is wrong
    elif defect == "unknown_vendor":
        inv["vendor"] = rng.choice(UNKNOWN_VENDORS[inv["locale"]])


# ---------------------------------------------------------------- PDF templates
SYMBOL = {"EUR": "€", "USD": "$", "GBP": "£"}


def draw_classic_en(c: canvas.Canvas, inv: dict) -> None:
    m = lambda x: money(x, "en")  # noqa: E731
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, 790, inv["vendor"])
    c.setFont("Helvetica-Bold", 20)
    c.drawRightString(555, 790, "INVOICE")
    c.setFont("Helvetica", 9)
    c.drawString(40, 774, inv["address"])
    c.drawString(40, 762, f"VAT ID: {inv['vat_id']}")
    c.setFont("Helvetica", 11)
    c.drawString(40, 730, f"Invoice No: {inv['invoice_number']}")
    c.drawString(40, 714, f"Date: {fmt_date(inv['date'], inv['date_style'])}")
    c.drawString(40, 698, f"Due date: {fmt_date(add_days(inv['date'], 30), inv['date_style'])}")
    c.drawString(40, 682, f"Currency: {inv['currency']}")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, 644, "Description")
    c.drawRightString(360, 644, "Qty")
    c.drawRightString(450, 644, "Unit price")
    c.drawRightString(555, 644, "Total")
    c.setFont("Helvetica", 10)
    y = 624
    for ln in inv["lines"]:
        c.drawString(40, y, ln["description"])
        c.drawRightString(360, y, str(ln["qty"]))
        c.drawRightString(450, y, m(ln["unit_price"]))
        c.drawRightString(555, y, m(ln["amount"]))
        y -= 18
    y -= 14
    for label, value, bold in [
        ("Subtotal", inv["subtotal"], False),
        (f"VAT ({round(inv['vat_rate'] * 100)}%)", inv["vat"], False),
        ("Total", inv["total"], True),
    ]:
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 11)
        c.drawString(380, y, label)
        c.drawRightString(555, y, m(value))
        y -= 18


def draw_compact_en(c: canvas.Canvas, inv: dict) -> None:
    """No subtotal line, month-name dates, symbol instead of currency code."""
    m = lambda x: money(x, "en")  # noqa: E731
    sym = SYMBOL[inv["currency"]]
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, 800, inv["vendor"])
    c.setFont("Helvetica", 9)
    c.drawString(40, 786, f"{inv['address']}  |  Tax ID {inv['vat_id']}")
    c.setFont("Helvetica", 10)
    c.drawString(40, 750, f"Invoice # {inv['invoice_number']}")
    c.drawString(40, 736, f"Issued: {fmt_date(inv['date'], inv['date_style'])}")
    c.drawString(40, 722, f"Payment due: {fmt_date(add_days(inv['date'], 14), inv['date_style'])}")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, 690, "Item")
    c.drawRightString(330, 690, "Qty")
    c.drawRightString(430, 690, "Price")
    c.drawRightString(555, 690, "Amount")
    c.setFont("Helvetica", 10)
    y = 672
    for ln in inv["lines"]:
        c.drawString(40, y, ln["description"])
        c.drawRightString(330, y, str(ln["qty"]))
        c.drawRightString(430, y, m(ln["unit_price"]))
        c.drawRightString(555, y, m(ln["amount"]))
        y -= 16
    y -= 16
    c.drawString(380, y, f"VAT {round(inv['vat_rate'] * 100)}%")
    c.drawRightString(555, y, m(inv["vat"]))
    y -= 20
    c.setFont("Helvetica-Bold", 12)
    c.drawString(380, y, "Amount due")
    c.drawRightString(555, y, f"{sym}{m(inv['total'])}")


def draw_sr_standard(c: canvas.Canvas, inv: dict) -> None:
    m = lambda x: money(x, "sr")  # noqa: E731
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, 790, inv["vendor"])
    c.setFont("Helvetica-Bold", 20)
    c.drawRightString(555, 790, "FAKTURA")
    c.setFont("Helvetica", 9)
    c.drawString(40, 774, inv["address"])
    c.drawString(40, 762, f"PIB: {inv['vat_id']}")
    c.setFont("Helvetica", 11)
    c.drawString(40, 730, f"Faktura br.: {inv['invoice_number']}")
    c.drawString(40, 714, f"Datum izdavanja: {fmt_date(inv['date'], inv['date_style'])}")
    c.drawString(40, 698, f"Datum valute: {fmt_date(add_days(inv['date'], 30), inv['date_style'])}")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, 660, "Opis")
    c.drawRightString(330, 660, "Kolicina")
    c.drawRightString(440, 660, "Cena")
    c.drawRightString(555, 660, "Iznos")
    c.setFont("Helvetica", 10)
    y = 640
    for ln in inv["lines"]:
        c.drawString(40, y, ln["description"])
        c.drawRightString(330, y, str(ln["qty"]))
        c.drawRightString(440, y, m(ln["unit_price"]))
        c.drawRightString(555, y, m(ln["amount"]))
        y -= 18
    y -= 14
    c.drawString(330, y, "Osnovica")
    c.drawRightString(555, y, m(inv["subtotal"]))
    y -= 18
    c.drawString(330, y, f"PDV {round(inv['vat_rate'] * 100)}%")
    c.drawRightString(555, y, m(inv["vat"]))
    y -= 20
    c.setFont("Helvetica-Bold", 11)
    c.drawString(330, y, f"Ukupno za uplatu {inv['currency']}")
    c.drawRightString(555, y, m(inv["total"]))


def draw_sr_racun(c: canvas.Canvas, inv: dict) -> None:
    m = lambda x: money(x, "sr")  # noqa: E731
    c.setFont("Helvetica-Bold", 15)
    c.drawString(40, 795, inv["vendor"])
    c.setFont("Helvetica", 9)
    c.drawString(40, 781, f"{inv['address']}  PIB {inv['vat_id']}")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, 748, f"Racun broj: {inv['invoice_number']}")
    c.setFont("Helvetica", 10)
    c.drawString(40, 732, f"Datum: {fmt_date(inv['date'], inv['date_style'])}")
    c.drawString(40, 718, f"Rok placanja: {fmt_date(add_days(inv['date'], 15), inv['date_style'])}")
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, 684, "Naziv")
    c.drawRightString(320, 684, "Kol.")
    c.drawRightString(430, 684, "Jed. cena")
    c.drawRightString(555, 684, "Ukupno")
    c.setFont("Helvetica", 10)
    y = 666
    for ln in inv["lines"]:
        c.drawString(40, y, ln["description"])
        c.drawRightString(320, y, str(ln["qty"]))
        c.drawRightString(430, y, m(ln["unit_price"]))
        c.drawRightString(555, y, m(ln["amount"]))
        y -= 16
    y -= 16
    c.drawString(300, y, "Ukupno bez PDV-a")
    c.drawRightString(555, y, m(inv["subtotal"]))
    y -= 16
    c.drawString(300, y, f"PDV ({round(inv['vat_rate'] * 100)}%)")
    c.drawRightString(555, y, m(inv["vat"]))
    y -= 20
    c.setFont("Helvetica-Bold", 12)
    c.drawString(300, y, "Ukupno")
    c.drawRightString(555, y, f"{m(inv['total'])} {inv['currency']}")


DRAWERS = {
    "classic_en": draw_classic_en,
    "compact_en": draw_compact_en,
    "sr_standard": draw_sr_standard,
    "sr_racun": draw_sr_racun,
}


def render_pdf_bytes(inv: dict) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    DRAWERS[inv["template"]](c, inv)
    c.save()
    return buf.getvalue()


# ---------------------------------------------------------------- scan simulation
def degrade(pdf_bytes: bytes, level: str, rng: np.random.Generator) -> tuple[Image.Image, int]:
    """Rasterize the clean PDF and damage it. The result has no text layer, so OCR must run."""
    dpi = 200 if level == "scanned" else 130
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        img = pdf.pages[0].to_image(resolution=dpi).original.convert("RGB")
    angle = float(rng.uniform(-0.6, 0.6) if level == "scanned" else rng.uniform(-2.5, 2.5))
    img = img.rotate(
        angle, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=(255, 255, 255)
    )
    img = img.filter(ImageFilter.GaussianBlur(0.4 if level == "scanned" else 1.0))
    if level == "degraded":
        img = ImageEnhance.Contrast(img).enhance(0.75)
    sigma = 6 if level == "scanned" else 18
    arr = np.asarray(img).astype(np.int16)
    arr = arr + rng.normal(0, sigma, arr.shape).astype(np.int16)
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)), dpi


# ---------------------------------------------------------------- dataset
def expected_decision(defect: str | None) -> str:
    return "approved" if defect is None else "review"


def generate(n: int, out: Path, seed: int) -> None:
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)
    np_rng = np.random.default_rng(seed)
    originals: list[dict] = []  # clean, defect-free invoices we may duplicate later
    manifest = []

    for idx in range(n):
        noise = rng.choices(NOISE_LEVELS, NOISE_WEIGHTS)[0]
        roll = rng.random()
        defect = None
        if roll < 0.28:
            defect = DEFECTS[int(roll / 0.07)]
        if defect == "duplicate" and not originals:
            defect = None

        if defect == "duplicate":
            inv = copy.deepcopy(rng.choice(originals))
        else:
            locale = rng.choice(["en", "sr"])
            inv = build_invoice(rng, idx, locale, rng.choice(TEMPLATES[locale]))
            if defect:
                apply_defect(rng, inv, defect)
            else:
                originals.append(inv)

        doc_id = f"{idx:04d}"
        pdf_bytes = render_pdf_bytes(inv)
        pdf_path = out / f"{doc_id}.pdf"
        if noise == "clean":
            pdf_path.write_bytes(pdf_bytes)
        else:
            image, dpi = degrade(pdf_bytes, noise, np_rng)
            image.save(pdf_path, "PDF", resolution=dpi)

        truth = {
            "id": doc_id,
            "noise": noise,
            "defect": defect,
            "expected_decision": expected_decision(defect),
            "vendor": inv["vendor"],
            "invoice_number": inv["invoice_number"],
            "date": inv["date"],
            "currency": inv["currency"],
            # compact_en prints no subtotal line, so the ground truth says None for it
            "subtotal": None if inv["template"] == "compact_en" else inv["subtotal"],
            "vat_rate": inv["vat_rate"],
            "vat": inv["vat"],
            "total": inv["total"],
            "line_count": len(inv["lines"]),
            "template": inv["template"],
            "locale": inv["locale"],
        }
        (out / f"{doc_id}.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")
        manifest.append(doc_id)

    known = sorted({v for vs in KNOWN_VENDORS.values() for v in vs})
    (out / "manifest.json").write_text(
        json.dumps({"seed": seed, "documents": manifest, "known_vendors": known}, indent=2),
        encoding="utf-8",
    )
    print(f"Generated {n} documents in {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=300)
    parser.add_argument("--out", type=Path, default=Path("data/synth"))
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    generate(args.n, args.out, args.seed)


if __name__ == "__main__":
    main()
