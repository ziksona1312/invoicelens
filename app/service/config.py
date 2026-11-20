"""Service settings, read from environment variables (see .env.example)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path


def _known_vendors(path: str) -> set[str]:
    return set(json.loads(Path(path).read_text(encoding="utf-8"))["known_vendors"])


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://invoicelens:invoicelens@localhost:5432/invoicelens",
        )
    )
    redis_url: str = field(
        default_factory=lambda: os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    )
    s3_endpoint_url: str | None = field(
        default_factory=lambda: os.environ.get("S3_ENDPOINT_URL") or None
    )
    s3_bucket: str = field(default_factory=lambda: os.environ.get("S3_BUCKET", "invoices"))
    s3_region: str = field(default_factory=lambda: os.environ.get("S3_REGION", "us-east-1"))
    queue_name: str = field(default_factory=lambda: os.environ.get("QUEUE_NAME", "invoicelens"))
    max_upload_bytes: int = field(
        default_factory=lambda: int(os.environ.get("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024)))
    )
    known_vendors_file: str = field(
        default_factory=lambda: os.environ.get("KNOWN_VENDORS_FILE", "config/known_vendors.json")
    )

    @property
    def known_vendors(self) -> set[str]:
        return _known_vendors(self.known_vendors_file)


@lru_cache
def get_settings() -> Settings:
    return Settings()
