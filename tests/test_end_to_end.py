"""Generate a few real PDFs and run them through the full pipeline (text layer and OCR)."""

import json

from app.pipeline import extract
from tools.synth.generate import generate


def test_generated_documents_are_read(tmp_path):
    generate(n=12, out=tmp_path, seed=7)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    clean_ok, ocr_totals_ok, ocr_docs = 0, 0, 0
    for doc_id in manifest["documents"]:
        truth = json.loads((tmp_path / f"{doc_id}.json").read_text())
        ex = extract(tmp_path / f"{doc_id}.pdf")
        if truth["noise"] == "clean":
            assert ex.source == "text"
            assert ex.invoice_number == truth["invoice_number"]
            assert ex.total == truth["total"]
            clean_ok += 1
        else:
            assert ex.source == "ocr"
            ocr_docs += 1
            ocr_totals_ok += ex.total == truth["total"]
    assert clean_ok > 0 and ocr_docs > 0
    assert ocr_totals_ok >= ocr_docs // 2  # OCR is imperfect, but not useless
