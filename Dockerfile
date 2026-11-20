# One image for both the API and the worker; docker-compose.yml picks the command.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 app
WORKDIR /app

# Dependencies first, so code changes do not reinstall them.
COPY pyproject.toml README.md ./
COPY app ./app
COPY tools ./tools
COPY eval ./eval
RUN pip install ".[service]"

COPY config ./config

USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8000/healthz', timeout=4).status == 200 else 1)"
CMD ["uvicorn", "app.service.api:app", "--host", "0.0.0.0", "--port", "8000"]
