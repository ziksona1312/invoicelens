"""Service tests need PostgreSQL and Redis (docker compose or CI service containers).

S3 is replaced by moto's in-memory fake, so no object store is needed. Without PostgreSQL or
Redis the tests are skipped, so `make test` still works on a plain machine.
"""

import os

import pytest

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://invoicelens:invoicelens@localhost:5432/invoicelens_test"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ["S3_ENDPOINT_URL"] = ""
os.environ["S3_BUCKET"] = "test-invoices"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"


def _reachable() -> str | None:
    try:
        import redis
        from sqlalchemy import create_engine, text

        with create_engine(os.environ["DATABASE_URL"]).connect() as conn:
            conn.execute(text("SELECT 1"))
        redis.Redis.from_url(os.environ["REDIS_URL"]).ping()
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {exc}"
    return None


_problem = _reachable()


def pytest_collection_modifyitems(config, items):
    if _problem and os.environ.get("REQUIRE_SERVICES"):
        raise pytest.UsageError(f"REQUIRE_SERVICES is set but PostgreSQL/Redis fail: {_problem}")
    if _problem:
        skip = pytest.mark.skip(reason=f"PostgreSQL/Redis not reachable ({_problem[:80]})")
        for item in items:
            if "tests/service" in str(item.fspath):
                item.add_marker(skip)


@pytest.fixture
def service():
    """Fresh tables, empty Redis db, fake S3, and every cached client rebuilt."""
    from moto import mock_aws

    from app.service import config, db, jobs, storage

    for cached in (
        config.get_settings,
        db.get_engine,
        db.get_sessionmaker,
        jobs.get_redis,
        storage.get_client,
    ):
        cached.cache_clear()
    with mock_aws():
        engine = db.get_engine()
        db.Base.metadata.drop_all(engine)
        db.Base.metadata.create_all(engine)
        jobs.get_redis().flushdb()
        storage.ensure_bucket()
        yield
        jobs.get_redis().flushdb()
    engine.dispose()
