# Stage runner. Every target is idempotent: stages whose configuration and upstream
# fingerprints are unchanged are skipped (use FORCE=1 to re-run).
#
#   make synthetic-demo              # offline demo on generated data (all 14 stages)
#   make all CONFIG=configs/default.yaml   # real data (after placing raw files)
#   make features SET="events.spatial_link_km=3"

CONFIG ?= configs/default.yaml
SET ?=
FORCE ?= 0
PY ?= python

SET_ARGS := $(foreach s,$(SET),--set $(s))
FORCE_ARG := $(if $(filter 1,$(FORCE)),--force,)
CLI := $(PY) -m wildfire_kz.cli.main
RUN = $(CLI) $(1) --config $(CONFIG) $(SET_ARGS) $(FORCE_ARG)

STAGES := ingest grid events risk-set sampling features splits train calibrate ablate \
          evaluate explain map report

.PHONY: help install dev all $(STAGES) synth synthetic-demo smoke lint format typecheck test \
        check clean-synthetic

help:
	@echo "Stages (in order): $(STAGES)"
	@echo "make all CONFIG=...   run every stage;  make <stage> CONFIG=...   run one stage"
	@echo "make synthetic-demo   generate synthetic data and run the full pipeline offline"
	@echo "make check            lint + type-check + tests"

install:
	$(PY) -m pip install -e .

dev:
	$(PY) -m pip install -e ".[dev]"
	pre-commit install || true

ingest:
	$(call RUN,ingest)
grid: ingest
	$(call RUN,grid)
events: grid
	$(call RUN,events)
risk-set: events
	$(call RUN,risk-set)
sampling: risk-set
	$(call RUN,sampling)
features: sampling
	$(call RUN,features)
splits: features
	$(call RUN,splits)
train: splits
	$(call RUN,train)
calibrate: train
	$(call RUN,calibrate)
ablate: calibrate
	$(call RUN,ablate)
evaluate: ablate
	$(call RUN,evaluate)
explain: evaluate
	$(call RUN,explain)
map: evaluate
	$(call RUN,map)
report: explain map
	$(call RUN,report)

all: report

synth:
	$(CLI) synth --config $(CONFIG) $(SET_ARGS)

synthetic-demo:
	$(MAKE) synth CONFIG=configs/synthetic.yaml
	$(MAKE) all CONFIG=configs/synthetic.yaml

smoke:
	$(MAKE) synth CONFIG=configs/test_smoke.yaml
	$(MAKE) all CONFIG=configs/test_smoke.yaml

lint:
	ruff check src tests
	ruff format --check src tests

format:
	ruff format src tests
	ruff check --fix src tests

typecheck:
	mypy

test:
	pytest -q

check: lint typecheck test

clean-synthetic:
	rm -rf data/synthetic_raw data/smoke_raw data/work/synthetic data/work/smoke
