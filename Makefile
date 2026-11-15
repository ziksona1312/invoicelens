# Run from WSL2 / Linux / macOS. `make help` lists targets.
PY ?= python3
N ?= 300
SEED ?= 42

.PHONY: help install lint test data eval demo clean

help:
	@grep -E '^[a-z]+:.*## ' Makefile | sed 's/:.*## /\t/'

install: ## Create .venv and install the project with dev tools
	$(PY) -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/pre-commit install || true

lint: ## Ruff lint + format check
	ruff check app tools eval tests && ruff format --check app tools eval tests

test: ## Unit + end-to-end tests
	$(PY) -m pytest -q

data: ## Generate the synthetic dataset (N=300 SEED=42)
	rm -rf data/synth && $(PY) -m tools.synth.generate --n $(N) --out data/synth --seed $(SEED)

eval: ## Measure accuracy and write eval/report.md
	$(PY) -m eval.run_eval --data data/synth --report eval/report.md

demo: data eval ## Generate data and print the report

clean:
	rm -rf data .pytest_cache .ruff_cache **/__pycache__
