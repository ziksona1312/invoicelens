"""Worker process: python -m app.service.worker"""

from __future__ import annotations

import os

from rq import Worker

from app.service.db import init_db
from app.service.jobs import get_queue, get_redis
from app.service.logs import setup_logging


def main() -> None:
    setup_logging(os.environ.get("LOG_LEVEL", "INFO"))
    init_db()
    # with_scheduler=True is needed for retries with a delay.
    Worker([get_queue()], connection=get_redis()).work(with_scheduler=True)


if __name__ == "__main__":
    main()
