# ADR 0003: Service architecture (API, queue, workers, database, object storage)

Status: accepted (2026-11-20)

## Context

Phase 1 is a batch script. A real intake process receives invoices one by one, must not lose
any, must survive a crashed worker, and needs a place where a person decides the exceptions.
OCR takes 1-2 seconds per scanned page, so it cannot run inside the HTTP request.

## Decision

- **FastAPI** receives uploads, stores the file and returns at once with status `queued`.
- **Redis + RQ** hold the jobs; **workers** (2 by default) run the existing `app.pipeline`.
  RQ was chosen over Celery because it needs no broker configuration and is small enough to read.
- **PostgreSQL** is the source of truth: document status, extracted fields, reasons, review
  actions, and timings.
- **Object storage over the S3 API** keeps the PDFs (see ADR 0004 for the product). Files are
  stored under their SHA-256, so the same file is never stored twice.
- **Idempotency.** `sha256` is unique: uploading the same file again returns the first document
  (HTTP 200) and queues nothing. A worker that receives a finished document does nothing.
- **Duplicates across workers.** The in-memory `seen` set from phase 1 does not work with several
  workers. Each worker claims `(vendor, invoice number)` with `INSERT ... ON CONFLICT DO NOTHING`
  in PostgreSQL and then reads the owner. The insert is atomic, so two workers handling two copies
  at the same moment cannot both win, and a retry of the same document is not its own duplicate.
- **Retries and dead letters.** A failing job is retried 3 times (after 10, 30 and 90 s). After
  that RQ moves it to its failed-job registry, which is the dead-letter queue, and the document
  is marked `failed` with the error text.
- **Observability.** JSON logs carry a correlation id from the `X-Request-ID` header (or a new
  one) through the queue into the worker. `/metrics` reads document counts and processing time
  from PostgreSQL and queue/dead-letter sizes from Redis at scrape time, because counters in one
  process would miss the work of the other workers.
- **Review UI** is one server-rendered HTML page (`/review`) with approve/reject buttons, the
  smallest thing that lets a person work the exception queue.
- Tables are created with `create_all` on startup. Schema migrations (Alembic) come when the
  schema first has to change with data in it.

## Consequences

- Upload latency no longer depends on OCR; throughput scales with the number of workers.
- The machine's decision (`machine_decision`) and the person's action (`review_action`) are both
  kept, so later we can measure how often people overrule the rules.
- First-come wins for duplicates: if a copy is processed before the original, the original is
  the one flagged. Both still end in the review queue, which is what matters for payment.
- More moving parts: five containers instead of one script. Phase 4 and 5 automate running them.
