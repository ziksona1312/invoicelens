# Run from WSL2 / Linux / macOS. `make help` lists targets.
PY ?= python3
N ?= 300
SEED ?= 42

.PHONY: help install lint test data eval demo up down logs load clean

help:
	@grep -E '^[a-z]+:.*## ' Makefile | sed 's/:.*## /\t/'

install: ## Create .venv and install the project with dev + service tools
	$(PY) -m venv .venv && .venv/bin/pip install -e ".[dev,service]" && .venv/bin/pre-commit install || true

lint: ## Ruff lint + format check + mypy type check
	ruff check app tools eval tests && ruff format --check app tools eval tests
	mypy app tools eval

test: ## Unit + end-to-end tests
	$(PY) -m pytest -q

data: ## Generate the synthetic dataset (N=300 SEED=42)
	rm -rf data/synth && $(PY) -m tools.synth.generate --n $(N) --out data/synth --seed $(SEED)

eval: ## Measure accuracy and write eval/report.md
	$(PY) -m eval.run_eval --data data/synth --report eval/report.md

demo: data eval ## Generate data and print the report

up: ## Start the whole stack in Docker (creates .env from .env.example the first time)
	@test -f .env || (cp .env.example .env && echo "Created .env from .env.example")
	docker compose up -d --build
	@echo "API: http://localhost:8000/docs   Review: http://localhost:8000/review"

down: ## Stop the stack (data is kept in Docker volumes)
	docker compose down

logs: ## Follow API and worker logs
	docker compose logs -f api worker

load: ## Upload 50 generated invoices to the running stack and check decisions
	$(PY) -m tools.load_demo --n 50

clean:
	rm -rf data .pytest_cache .ruff_cache **/__pycache__
