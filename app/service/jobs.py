"""Queue access and the background job that processes one document."""

from __future__ import annotations

import dataclasses
import logging
import tempfile
import time
from datetime import UTC, date, datetime
from functools import lru_cache
from pathlib import Path

from redis import Redis
from rq import Queue, Retry, get_current_job
from rq.registry import FailedJobRegistry

from app.pipeline import decide, extract
from app.service import storage
from app.service.config import get_settings
from app.service.db import Document, claim_invoice_key, get_sessionmaker
from app.service.logs import correlation_id
from app.validation.rules import Context

log = logging.getLogger("invoicelens.worker")

# 3 retries: after 10 s, 30 s and 90 s. After that the job lands in RQ's failed registry,
# which is our dead-letter queue, and the document is marked "failed".
RETRY = Retry(max=3, interval=[10, 30, 90])
JOB_TIMEOUT = 120


@lru_cache
def get_redis() -> Redis:
    return Redis.from_url(get_settings().redis_url)


def get_queue() -> Queue:
    return Queue(get_settings().queue_name, connection=get_redis())


def enqueue(document_id: str, cid: str | None) -> None:
    get_queue().enqueue(
        process_document,
        document_id,
        job_id=f"doc-{document_id}",
        retry=RETRY,
        job_timeout=JOB_TIMEOUT,
        meta={"correlation_id": cid},
    )


def dead_letter_count() -> int:
    return FailedJobRegistry(queue=get_queue()).count


def process_document(document_id: str) -> str:
    """Download, extract, validate, decide, save. Raises on failure so RQ can retry."""
    job = get_current_job()
    if job is not None:
        correlation_id.set(job.meta.get("correlation_id"))
    Session = get_sessionmaker()
    started = time.perf_counter()

    with Session() as session:
        doc = session.get(Document, document_id)
        if doc is None:
            log.warning("document not found", extra={"document_id": document_id})
            return "missing"
        if doc.status not in ("queued", "processing"):
            return doc.status  # already done (e.g. job delivered twice): nothing to do
        doc.status, doc.attempts = "processing", doc.attempts + 1
        session.commit()
        storage_key = doc.storage_key

    try:
        data = storage.get(storage_key)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "doc.pdf"
            path.write_bytes(data)
            extracted = extract(path)

        with Session() as session:
            ctx = Context(
                known_vendors=get_settings().known_vendors,
                today=date.today(),
                claim_key=lambda key: claim_invoice_key(session, key, document_id),
            )
            result = decide(extracted, ctx)
            doc = session.get(Document, document_id)
            assert doc is not None
            doc.status = doc.machine_decision = result.decision
            doc.reasons = result.reasons
            doc.extracted = dataclasses.asdict(extracted)
            doc.source = extracted.source
            doc.error = None
            doc.processed_at = datetime.now(UTC)
            doc.processing_ms = int((time.perf_counter() - started) * 1000)
            session.commit()

        log.info(
            "document processed",
            extra={
                "document_id": document_id,
                "decision": result.decision,
                "reasons": result.reasons,
                "source": extracted.source,
                "processing_ms": doc.processing_ms,
            },
        )
        return result.decision

    except Exception as exc:
        final = job is None or not job.retries_left
        with Session() as session:
            doc = session.get(Document, document_id)
            if doc is not None:
                doc.status = "failed" if final else "queued"
                doc.error = f"{type(exc).__name__}: {exc}"[:2000]
                session.commit()
        log.exception(
            "document failed",
            extra={"document_id": document_id, "final": final},
        )
        raise
