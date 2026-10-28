"""The event analysis specified in the pre-label 2025 protocol, at fixed threshold."""

import json

import joblib
import numpy as np
import pandas as pd

from wildfire_kz import model_upgrade as mu
from wildfire_kz.data import dump_json
from wildfire_kz.data.public_predictors import geography
from wildfire_kz.independent import RELEASE, RUN, feature_frame, labels_gate


def main():
    labels_gate()
    evaluation = json.loads((RUN / "evaluation.json").read_text())
    events = pd.read_parquet(RUN / "events.parquet")
    first = events[events.is_first & events.day.dt.year.eq(2025)].copy()
    predictions = pd.read_parquet(
        RUN / "predictions.parquet", columns=["cell_id", "day", "probability"]
    )
    first = first.merge(predictions, on=["cell_id", "day"], how="left", validate="many_to_one")
    first["covered"] = first.probability.notna()
    threshold = evaluation["threshold"]
    first["same_day_alert"] = first.probability.ge(threshold)
    grid = geography()[0]
    ids = pd.Index(grid.cell_id)
    keys = pd.DataFrame(
        {
            "cell_index": ids.get_indexer(first.cell_id),
            "day": first.day - pd.Timedelta(days=1),
            "event_id": first.event_id,
        }
    )
    keys = keys.sort_values(["day", "cell_index"]).reset_index(drop=True)
    raw = pd.read_parquet(RUN / "detections_2025.parquet", columns=["cell_id", "timestamp"])
    raw["day"] = raw.timestamp.dt.floor("D")
    model_dir = mu.ROOT / "runs/model_stack_v5"
    history = mu.FireHistory(
        pd.concat(
            [mu.load_history(2024, model_dir / "release.json"), raw[["cell_id", "day"]]],
            ignore_index=True,
        ).drop_duplicates()
    )
    model = joblib.load(model_dir / "model.joblib")
    cal = joblib.load(model_dir / "calibrator.joblib")
    industrial = set(json.loads((mu.OLD / "industrial_cells.json").read_text())["cell_ids"])
    recent = events.groupby("day").cell_id.apply(set).to_dict()
    scores = []
    for _, group in keys.groupby([keys.day.dt.year, keys.day.dt.month], sort=True):
        f = feature_frame(group, RELEASE)
        f = mu.augment(f, history, model_dir / "release.json")
        eligible = f.required_features_valid & ~f.cell_id.isin(industrial)
        for day, indices in f.groupby("day").groups.items():
            previous = recent.get(day - pd.Timedelta(days=1), set()) | recent.get(
                day - pd.Timedelta(days=2), set()
            )
            eligible.loc[indices] &= ~f.loc[indices, "cell_id"].isin(previous)
        f["prior_probability"] = np.nan
        if eligible.any():
            rawp = model["estimator"].predict_proba(f.loc[eligible, model["features"]])[:, 1]
            f.loc[eligible, "prior_probability"] = mu.published_probability(cal.predict(rawp))
        scores.append(f[["event_id", "prior_probability"]])
    first = first.merge(pd.concat(scores, ignore_index=True), on="event_id", validate="one_to_one")
    first["prior_day_alert"] = first.prior_probability.ge(threshold)
    result = {
        "synthetic": False,
        "year": 2025,
        "release_sha256": evaluation["release_sha256"],
        "protocol_sha256": evaluation["protocol_sha256"],
        "events": len(first),
        "covered_first_day_events": int(first.covered.sum()),
        "uncovered_first_day_events": int((~first.covered).sum()),
        "same_day_event_recall_all": float(first.same_day_alert.mean()),
        "same_day_event_recall_covered": float(first.loc[first.covered, "same_day_alert"].mean()),
        "prior_day_event_recall_all": float(first.prior_day_alert.mean()),
        "day_or_prior_event_recall_all": float(
            (first.same_day_alert | first.prior_day_alert).mean()
        ),
        "uncertainty": "Not estimated for event diagnostics",
        "interpretation": "Same-cell matching to first satellite event; retrospective features; not verified ignition or actual warning lead time",
        "model_or_threshold_changed": False,
    }
    first.to_parquet(RUN / "event_scores.parquet", index=False)
    dump_json(RUN / "event_metrics.json", result)
    print(json.dumps(result))


if __name__ == "__main__":
    main()
