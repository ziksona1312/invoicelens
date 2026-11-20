"""Prometheus metrics.

Business numbers are read from PostgreSQL and Redis at scrape time instead of being counted in
memory: there can be several workers, and the database is the single source of truth.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Histogram
from prometheus_client.core import GaugeMetricFamily, SummaryMetricFamily
from sqlalchemy import func, select

from app.service.db import STATUSES, Document, get_sessionmaker
from app.service.jobs import dead_letter_count, get_queue

registry = CollectorRegistry()

http_requests = Counter(
    "invoicelens_http_requests_total",
    "HTTP requests by route and status code",
    ["method", "route", "status"],
    registry=registry,
)
http_latency = Histogram(
    "invoicelens_http_request_seconds",
    "HTTP request duration",
    ["route"],
    registry=registry,
)


class PipelineCollector:
    def collect(self):
        with get_sessionmaker()() as session:
            counts = dict(
                session.execute(
                    select(Document.status, func.count()).group_by(Document.status)
                ).all()
            )
            total_ms, done = session.execute(
                select(func.coalesce(func.sum(Document.processing_ms), 0), func.count()).where(
                    Document.processing_ms.is_not(None)
                )
            ).one()

        docs = GaugeMetricFamily(
            "invoicelens_documents", "Documents by current status", labels=["status"]
        )
        for status in STATUSES:
            docs.add_metric([status], counts.get(status, 0))
        yield docs

        summary = SummaryMetricFamily(
            "invoicelens_processing_seconds", "Time to process one document in the worker"
        )
        summary.add_metric([], count_value=done, sum_value=total_ms / 1000)
        yield summary

        yield GaugeMetricFamily(
            "invoicelens_queue_depth", "Jobs waiting in the queue", value=len(get_queue())
        )
        yield GaugeMetricFamily(
            "invoicelens_dead_letter_jobs",
            "Jobs that failed after all retries",
            value=dead_letter_count(),
        )


registry.register(PipelineCollector())
