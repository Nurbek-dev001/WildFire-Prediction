"""Check actual development/calibration tables without opening held-out data."""

import json

import numpy as np
import pandas as pd

from wildfire_kz.data import checksum, dump_json
from wildfire_kz.data.public_study import COVER, FEATURE_CODE_HASH, FEATURES, RUN

names = [f"{y}_train" for y in range(2015, 2022)] + [
    f"{y}_evaluation" for y in [2019, 2020, 2021, 2022]
]
records = []
for name in names:
    path = RUN / f"features/{name}.parquet"
    meta = json.loads(path.with_suffix(".sha256.json").read_text())
    assert meta["feature_code_sha256"] == FEATURE_CODE_HASH, "Feature preparation still in progress"
    assert meta["sha256"] == checksum(path), path.name
    year = int(name[:4])
    f = pd.read_parquet(path)
    assert f.day.dt.year.eq(year).all() and not f.duplicated(["cell_id", "day"]).any(), name
    assert f.label.isin([0, 1]).all() and f.q.between(0, 1, inclusive="right").all(), name
    np.testing.assert_allclose(f.weight * f.q, 1)
    np.testing.assert_allclose(f[COVER].sum(axis=1), 1, atol=1e-5)
    assert f.ndvi.dropna().between(-0.1, 1).all(), name
    assert f.ndvi_age_days.dropna().between(12, 32).all(), name
    assert f.rh.between(0, 100).all() and f.wind.between(0, 80).all(), name
    assert f.tmin.between(-80, 60).all() and f.tmax.between(-80, 60).all(), name
    assert (f.tmax >= f.tmin).all() and f.precip.between(0, 500).all(), name
    assert f.soil_moisture.between(0, 1).all() and f.slope.between(0, 90).all(), name
    record = {
        "table": path.name,
        "sha256": checksum(path),
        "rows": len(f),
        "positives": int(f.label.sum()),
        "weighted_cell_days": float(f.weight.sum()),
        "weighted_prevalence": float(np.average(f.label, weights=f.weight)),
        "ndvi_missing_fraction": float(f.ndvi.isna().mean()),
        "population_missing_fraction": float(f.population_density.isna().mean()),
        "soil_rows_bounded": meta["soil_moisture_rows_bounded_0_1"],
        "ranges": {n: [float(f[n].min()), float(f[n].max())] for n in FEATURES},
    }
    records.append(record)
    print({k: v for k, v in record.items() if k not in ["ranges", "sha256"]}, flush=True)
dump_json(
    RUN / "development_quality.json",
    {"synthetic": False, "test_accessed": False, "tables": records},
)
