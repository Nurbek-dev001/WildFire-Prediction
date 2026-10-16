PYTHON ?= python
CONFIG ?= configs/primary.yaml
.PHONY: install demo check test lint typecheck all ingest grid events risk-set sampling features splits train calibrate ablate evaluate explain map report
install:
	$(PYTHON) -m pip install -e ".[dev]"
demo:
	$(PYTHON) -m wildfire_kz synthetic
	$(PYTHON) -m wildfire_kz run-all -c configs/synthetic.yaml
all:
	$(PYTHON) -m wildfire_kz run-all -c $(CONFIG)
ingest grid events risk-set sampling features splits train calibrate ablate evaluate explain map report:
	$(PYTHON) -m wildfire_kz $@ -c $(CONFIG)
test:
	$(PYTHON) -m pytest -q
lint:
	ruff check .
	ruff format --check .
typecheck:
	mypy src/wildfire_kz
check: lint typecheck test
