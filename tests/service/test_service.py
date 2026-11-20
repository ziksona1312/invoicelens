from datetime import date

import pytest
from botocore.exceptions import ClientError
from fastapi.testclient import TestClient

from app.service.api import app
from app.service.db import Document, get_sessionmaker
from app.service.jobs import get_queue, process_document
from tools.synth.generate import KNOWN_VENDORS, apply_defect, build_invoice, render_pdf_bytes


def invoice_pdf(seed: int = 1, defect: str | None = None) -> bytes:
    import random

    rng = random.Random(seed)
    inv = build_invoice(rng, seed, "en", "classic_en")
    inv["vendor"] = KNOWN_VENDORS["en"][0]
    inv["date"] = date.today().replace(day=1).isoformat()
    if defect:
        apply_defect(rng, inv, defect)
    return render_pdf_bytes(inv)


def upload(client: TestClient, data: bytes, name: str = "inv.pdf"):
    return client.post("/documents", files={"file": (name, data, "application/pdf")})


@pytest.fixture
def client(service):
    with TestClient(app) as c:
        yield c


def test_upload_queues_and_worker_approves_clean_invoice(client):
    r = upload(client, invoice_pdf(1))
    assert r.status_code == 201
    doc_id = r.json()["id"]
    assert r.json()["status"] == "queued"
    assert len(get_queue()) == 1
    assert r.headers["X-Request-ID"]

    assert process_document(doc_id) == "approved"
    body = client.get(f"/documents/{doc_id}").json()
    assert body["status"] == "approved"
    assert body["extracted"]["vendor"] == KNOWN_VENDORS["en"][0]
    assert body["processing_ms"] is not None


def test_same_file_twice_is_one_document(client):
    data = invoice_pdf(2)
    first, second = upload(client, data), upload(client, data)
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]
    assert len(get_queue()) == 1


def test_second_copy_of_invoice_is_flagged_duplicate(client):
    data = invoice_pdf(3)
    a = upload(client, data).json()["id"]
    b = upload(client, data + b"\n% scanned again\n").json()["id"]  # different bytes, same invoice
    assert process_document(a) == "approved"
    assert process_document(b) == "review"
    assert "duplicate" in client.get(f"/documents/{b}").json()["reasons"]


def test_reprocessing_same_document_is_not_a_duplicate(client):
    doc_id = upload(client, invoice_pdf(4)).json()["id"]
    assert process_document(doc_id) == "approved"
    with get_sessionmaker()() as s:  # simulate a retry after a crash
        s.get(Document, doc_id).status = "queued"
        s.commit()
    assert process_document(doc_id) == "approved"


def test_wrong_total_goes_to_review_and_person_approves(client):
    doc_id = upload(client, invoice_pdf(5, "total_mismatch")).json()["id"]
    assert process_document(doc_id) == "review"

    page = client.get("/review")
    assert page.status_code == 200 and "total_mismatch" in page.text

    r = client.post(f"/review/{doc_id}", json={"action": "approve", "note": "checked by phone"})
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert r.json()["review_action"] == "approve"
    assert client.post(f"/review/{doc_id}", json={"action": "reject"}).status_code == 409


def test_review_form_redirects(client):
    doc_id = upload(client, invoice_pdf(6, "unknown_vendor")).json()["id"]
    process_document(doc_id)
    r = client.post(f"/ui/review/{doc_id}", data={"action": "reject"}, follow_redirects=False)
    assert r.status_code == 303
    assert client.get(f"/documents/{doc_id}").json()["status"] == "rejected"


def test_rejects_non_pdf_and_missing(client):
    assert upload(client, b"hello", "x.txt").status_code == 415
    assert client.get("/documents/nope").status_code == 404


def test_failure_marks_document_failed(client):
    from app.service import storage

    doc_id = upload(client, invoice_pdf(7)).json()["id"]
    storage.get_client().delete_object(Bucket="test-invoices", Key=_key(doc_id))
    with pytest.raises(ClientError):
        process_document(doc_id)
    body = client.get(f"/documents/{doc_id}").json()
    assert body["status"] == "failed" and body["error"]


def _key(doc_id: str) -> str:
    with get_sessionmaker()() as s:
        return s.get(Document, doc_id).storage_key


def test_health_and_metrics(client):
    assert client.get("/healthz").json()["status"] == "ok"
    doc_id = upload(client, invoice_pdf(8)).json()["id"]
    process_document(doc_id)
    text = client.get("/metrics").text
    assert 'invoicelens_documents{status="approved"} 1.0' in text
    assert "invoicelens_dead_letter_jobs 0.0" in text
    assert "invoicelens_processing_seconds_count 1.0" in text
