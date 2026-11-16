PYTHON ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: install lint test bench evidence reproduce probe web serve check

install:
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install -r requirements.txt
	cd web && npm install

test:
	$(BIN)/pytest -q

lint:
	$(BIN)/ruff check --select E4,E7,E9,F .

bench:
	$(BIN)/python -m dreamgraph.bench

evidence:
	$(BIN)/python -m dreamgraph.evidence

reproduce:
	DG_BACKEND=hydradb $(BIN)/python -m scripts.reproduce

probe:
	$(BIN)/python scripts/probe_hydradb.py

web:
	cd web && npm run build

serve:
	$(BIN)/uvicorn dreamgraph.api:app --host 0.0.0.0 --port $${PORT:-8000}

check: test
