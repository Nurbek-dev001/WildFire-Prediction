# Notebooks (exploration only)

Notebooks here only **read** pipeline artifacts (`data/work/<run_label>/...`) for ad-hoc
inspection. They must not contain logic the pipeline depends on: anything reusable belongs
in `src/wildfire_kz` with tests.

`01_inspect_run.ipynb` loads a finished run's metrics, reliability table and one daily map.
