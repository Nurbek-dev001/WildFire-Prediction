"""Train chronological stacking candidates; refuses final-year inputs."""

import json

import joblib
import numpy as np
import pandas as pd
from scipy.special import logit
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from wildfire_kz import model_upgrade as mu


def data(year):
    if year >= 2023:
        raise PermissionError("Only pre-2023 inputs allowed")
    f = pd.read_parquet(mu.RUN / f"features/{year}_evaluation.parquet")
    old = pd.read_parquet(mu.OLD / f"validation/xgboost_{year}.parquet")
    f = old[["cell_id", "day"]].merge(f, on=["cell_id", "day"], how="left", validate="one_to_one")
    if f.label.isna().any():
        raise ValueError("OOF alignment failed")
    x = f[mu.HISTORY].copy()
    x["baseline_logit"] = logit(np.clip(old.probability.to_numpy(), 1e-7, 1 - 1e-7))
    return f, x


if __name__ == "__main__":
    pairs = [data(y) for y in [2019, 2020]]
    train = pd.concat([a for a, b in pairs], ignore_index=True)
    x = pd.concat([b for a, b in pairs], ignore_index=True)
    valid, vx = data(2021)
    weights = train.weight.to_numpy() / train.weight.mean()
    rows = []
    candidates = {
        f"logistic_C{c}": make_pipeline(StandardScaler(), LogisticRegression(C=c, max_iter=1000))
        for c in [0.01, 0.1, 1]
    }
    candidates["hist_depth2"] = HistGradientBoostingClassifier(
        max_iter=120,
        max_depth=2,
        max_leaf_nodes=4,
        l2_regularization=5,
        learning_rate=0.05,
        early_stopping=False,
        random_state=42,
    )
    for name, model in candidates.items():
        if name.startswith("logistic"):
            model.fit(x, train.label, logisticregression__sample_weight=weights)
        else:
            model.fit(x, train.label, sample_weight=weights)
        p = model.predict_proba(vx)[:, 1]
        result = {
            "name": name,
            **mu.operating_point(valid.label.to_numpy(), p, valid.weight.to_numpy()),
        }
        result["recall_at_6"] = mu.operating_point(
            valid.label.to_numpy(), p, valid.weight.to_numpy(), 0.06
        )["recall"]
        rows.append(result)
        joblib.dump(model, mu.RUN / f"meta_{name}.joblib", compress=3)
        pd.DataFrame({"probability": p}).to_parquet(
            mu.RUN / f"meta_{name}_2021.parquet", index=False
        )
        print(json.dumps(result), flush=True)
    pd.DataFrame(rows).to_csv(mu.RUN / "meta_comparison.csv", index=False)
