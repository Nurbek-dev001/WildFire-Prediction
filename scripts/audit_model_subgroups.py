"""Stratified diagnostics on the previously evaluated test; never selects a model."""

import json
import struct

import numpy as np
import pandas as pd

from wildfire_kz import model_upgrade as mu
from wildfire_kz.data import checksum, dump_json
from wildfire_kz.evaluation import metrics

run = mu.ROOT / "runs/model_stack_v5"
mu.verify_release(run / "release.json")
pred = pd.read_parquet(run / "predictions.parquet")
parts = [
    pd.read_parquet(
        mu.OLD / f"features/{y}_evaluation.parquet",
        columns=["cell_id", "day", "ndvi_missing", "ndvi_age_days"],
    )
    for y in [2023, 2024]
]
frame = pred.merge(
    pd.concat(parts, ignore_index=True), on=["cell_id", "day"], validate="one_to_one"
)
rows = list(
    struct.iter_unpack("<hhfffH8H", (mu.ROOT / "platform/dist/assets/cells.bin").read_bytes())
)
regions = {f"g5000_{r[0]}_{r[1]}": r[5] for r in rows}
geo = json.loads((mu.ROOT / "platform/dist/assets/geography.json").read_text())
frame["region"] = frame.cell_id.map(regions)
frozen = json.loads((run / "frozen.json").read_text())
reference = np.full(len(frame), frozen["original_2022_metrics"]["prevalence"])
records = []
for field, groups in [
    ("region", frame.region),
    ("month", frame.day.dt.month),
    ("ndvi_missing", frame.ndvi_missing),
]:
    for key, indices in groups.groupby(groups).groups.items():
        f = frame.loc[indices]
        i = frame.index.get_indexer(indices)
        record = {
            "group": field,
            "value": str(key),
            "name": geo["regions"][int(key)]["name"] if field == "region" else str(key),
            "sampled_rows": len(f),
            "ndvi_missing_weighted": float(np.average(f.ndvi_missing, weights=f.weight)),
            **metrics(
                f.label.to_numpy(),
                f.probability.to_numpy(),
                f.weight.to_numpy(),
                frozen["threshold"],
                reference[i],
            ),
        }
        records.append(record)
out = run / "audit"
out.mkdir(exist_ok=True)
pd.DataFrame(records).to_csv(out / "subgroups.csv", index=False)
dump_json(
    out / "subgroups.json",
    {
        "synthetic": False,
        "release_sha256": checksum(run / "release.json"),
        "test_previously_evaluated": True,
        "model_selection_performed": False,
        "ndvi_missing_weighted": float(np.average(frame.ndvi_missing, weights=frame.weight)),
        "interpretation": "Weighted cell-day subgroup diagnostics, not regional transfer validation",
        "metrics": records,
    },
)
print(
    json.dumps(
        {
            "subgroups": len(records),
            "ndvi_missing_weighted": float(np.average(frame.ndvi_missing, weights=frame.weight)),
        }
    )
)
