"""HTTP API and the review page.

uvicorn app.service.api:app --reload
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from pydantic import BaseModel
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.service import storage
from app.service.config import get_settings
from app.service.db import Document, get_sessionmaker, init_db
from app.service.jobs import enqueue, get_redis
from app.service.logs import correlation_id, setup_logging
from app.service.metrics import http_latency, http_requests, registry

log = logging.getLogger("invoicelens.api")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_logging(os.environ.get("LOG_LEVEL", "INFO"))
    for attempt in range(1, 16):  # the stores can need a few seconds after "docker compose up"
        try:
            init_db()
            storage.ensure_bucket()
            break
        except Exception:
            if attempt == 15:
                raise
            log.warning("dependencies not ready, retrying", extra={"attempt": attempt})
            time.sleep(2)
    yield


app = FastAPI(title="InvoiceLens", version="0.3.0", lifespan=lifespan)


def get_session():
    with get_sessionmaker()() as session:
        yield session


@app.middleware("http")
async def correlation_and_metrics(request: Request, call_next):
    cid = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    token = correlation_id.set(cid)
    started = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        correlation_id.reset(token)
    route = request.scope.get("route")
    path = getattr(route, "path", "unmatched")
    http_requests.labels(request.method, path, str(response.status_code)).inc()
    http_latency.labels(path).observe(time.perf_counter() - started)
    response.headers["X-Request-ID"] = cid
    return response


class DocumentOut(BaseModel):
    id: str
    filename: str
    status: str
    machine_decision: str | None
    reasons: list[str]
    extracted: dict | None
    attempts: int
    error: str | None
    processing_ms: int | None
    review_action: str | None
    created_at: datetime
    processed_at: datetime | None
    reviewed_at: datetime | None

    model_config = {"from_attributes": True}


class ReviewIn(BaseModel):
    action: Literal["approve", "reject"]
    note: str | None = None


@app.post("/documents", status_code=201, response_model=DocumentOut)
async def upload(
    response: Response,
    file: UploadFile = File(...),
    session: Session = Depends(get_session),
):
    """Upload a PDF. The same file uploaded twice returns the first document (HTTP 200)."""
    limit = get_settings().max_upload_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"File larger than {limit} bytes")
    if not data.startswith(b"%PDF-"):
        raise HTTPException(415, "Only PDF files are accepted")

    sha = hashlib.sha256(data).hexdigest()
    existing = session.scalar(select(Document).where(Document.sha256 == sha))
    if existing:
        response.status_code = 200
        return existing

    key = f"documents/{sha}.pdf"
    storage.put(key, data)  # content-addressed: writing the same file twice is harmless
    doc = Document(
        sha256=sha,
        filename=(file.filename or "upload.pdf")[:255],
        storage_key=key,
        correlation_id=correlation_id.get(),
    )
    session.add(doc)
    try:
        session.commit()
    except IntegrityError:  # two uploads of the same file at the same moment
        session.rollback()
        response.status_code = 200
        return session.scalar(select(Document).where(Document.sha256 == sha))

    enqueue(doc.id, correlation_id.get())
    log.info("document queued", extra={"document_id": doc.id, "file_name": doc.filename})
    return doc


@app.get("/documents/{doc_id}", response_model=DocumentOut)
def get_document(doc_id: str, session: Session = Depends(get_session)):
    doc = session.get(Document, doc_id)
    if doc is None:
        raise HTTPException(404, "Document not found")
    return doc


@app.get("/documents", response_model=list[DocumentOut])
def list_documents(
    status: str | None = None, limit: int = 100, session: Session = Depends(get_session)
):
    query = select(Document).order_by(Document.created_at.desc()).limit(min(limit, 1000))
    if status:
        query = query.where(Document.status == status)
    return session.scalars(query).all()


def _review(session: Session, doc_id: str, body: ReviewIn) -> Document:
    doc = session.get(Document, doc_id, with_for_update=True)
    if doc is None:
        raise HTTPException(404, "Document not found")
    if doc.status != "review":
        raise HTTPException(409, f"Document is '{doc.status}', only 'review' can be decided")
    doc.status = "approved" if body.action == "approve" else "rejected"
    doc.review_action, doc.review_note = body.action, body.note
    doc.reviewed_at = datetime.now(UTC)
    session.commit()
    log.info("document reviewed", extra={"document_id": doc_id, "action": body.action})
    return doc


@app.post("/review/{doc_id}", response_model=DocumentOut)
def review(doc_id: str, body: ReviewIn, session: Session = Depends(get_session)):
    return _review(session, doc_id, body)


@app.get("/review", response_class=HTMLResponse)
def review_page(request: Request, session: Session = Depends(get_session)):
    docs = session.scalars(
        select(Document).where(Document.status == "review").order_by(Document.created_at)
    ).all()
    counts = dict(
        session.execute(select(Document.status, func.count()).group_by(Document.status)).all()
    )
    return templates.TemplateResponse(request, "review.html", {"docs": docs, "counts": counts})


@app.post("/ui/review/{doc_id}")
def review_form(
    doc_id: str,
    action: Literal["approve", "reject"] = Form(...),
    session: Session = Depends(get_session),
):
    _review(session, doc_id, ReviewIn(action=action))
    return RedirectResponse("/review", status_code=303)


@app.get("/healthz")
def healthz(session: Session = Depends(get_session)):
    checks = {}
    for name, probe in (
        ("database", lambda: session.execute(text("SELECT 1"))),
        ("redis", lambda: get_redis().ping()),
        ("storage", storage.ensure_bucket),
    ):
        try:
            probe()
            checks[name] = "ok"
        except Exception as exc:  # noqa: BLE001 - report any failure as unhealthy
            checks[name] = f"error: {type(exc).__name__}"
    ok = all(v == "ok" for v in checks.values())
    return JSONResponse({"status": "ok" if ok else "degraded", **checks}, 200 if ok else 503)


@app.get("/metrics")
def metrics():
    return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
