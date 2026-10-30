"""Simple baselines against the v6 recipe and v7 at every rolling origin, overall and on cropland.

A forecast is worth its complexity only if it beats what a fire officer could do without ML:
- climatology: how often the cell burned in this calendar month in earlier years;
- persistence: fires yesterday (to 21 UTC) within 15 and 55 km, then the day before;
- FWI: the Canadian Fire Weather Index of D-1 from ERA5 reanalysis (generous: in operation
  ERA5 arrives five days late);
- simple model: weighted logistic regression on those inputs plus cropland and season,
  fitted on the same years as the v6 recipe.
Same test rows (primary risk set), same years and same weights as develop_model_v7.v7_candidate.
Cropland cells (land-cover fraction >= 0.5) are where stubble burning dominates; the split shows
whether skill comes from the burning calendar or holds on steppe and forest too.
Usage: baselines_v7.py   (development evidence; the frozen releases are not touched)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import bootstrap_v7  # noqa: E402
import develop_model_v7 as v7  # noqa: E402

from wildfire_kz.data import dump_json  # noqa: E402
from wildfire_kz.fire_weather import FireWeather  # noqa: E402

WEATHER = ROOT / "data/real/public_predictors/weather"
OUT = v7.RUN / "experiments/baselines"
SIMPLE = ["clim", "nbr15", "yday15", "yday55", "d2_55", "fwi", "cropland", "month_sin", "month_cos"]


def fwi_by_day() -> tuple[dict[pd.Timestamp, np.ndarray], np.ndarray, np.ndarray]:
    """Daily FWI on the ERA5 window, run continuously from November 2014 to the end of 2025."""
    out: dict[pd.Timestamp, np.ndarray] = {}
    state = None
    for year in range(2014, 2026):
        with np.load(WEATHER / f"{year}.npz") as z:
            first = pd.Timestamp(str(z["first_day"]), tz="UTC")
            tmax, rh, wind, precip = (z[k] for k in ["tmax", "rh", "wind", "precip"])
            ny, nx = z["native_cell_y"].astype(int), z["native_cell_x"].astype(int)
        state = state or FireWeather(tmax.shape[:2])
        for k in range(tmax.shape[2]):
            day = first + pd.Timedelta(days=k)
            state.step(tmax[:, :, k], rh[:, :, k], wind[:, :, k], precip[:, :, k], day.month)
            out[day] = state.fwi.astype("float32").copy()
    return out, ny, nx


def inputs(frame: pd.DataFrame, fwi: dict, ny: np.ndarray, nx: np.ndarray) -> pd.DataFrame:
    ci = frame.cell_index.to_numpy()
    f = np.full(len(frame), np.nan, dtype="float32")
    for day, idx in frame.groupby("day").indices.items():
        grid = fwi.get(day - pd.Timedelta(days=1))
        if grid is not None:
            f[idx] = grid[ny[ci[idx]], nx[ci[idx]]]
    return pd.DataFrame(
        {
            "clim": frame.cell_month_climatology.to_numpy(),
            "nbr15": frame.nbr15_month_climatology.to_numpy(),
            "yday15": np.log1p(frame.h3_yday_15km.to_numpy()),
            "yday55": np.log1p(frame.h3_yday_55km.to_numpy()),
            "d2_55": np.log1p(frame.h3_d2_55km.to_numpy()),
            "fwi": np.nan_to_num(f),
            "cropland": frame.cropland.to_numpy(),
            "month_sin": frame.month_sin.to_numpy(),
            "month_cos": frame.month_cos.to_numpy(),
        }
    )


def scores_of(x: pd.DataFrame, simple: LogisticRegression) -> dict[str, np.ndarray]:
    return {
        "climatology": (x.clim + 0.01 * x.nbr15).to_numpy(),
        "persistence": (100 * x.yday15 + x.yday55 + 0.01 * x.d2_55).to_numpy(),
        "fwi": x.fwi.to_numpy(),
        "simple_model": simple.predict_proba(x[SIMPLE])[:, 1],
    }


def main() -> None:
    v7.check_protocol()
    OUT.mkdir(parents=True, exist_ok=True)
    fwi, ny, nx = fwi_by_day()
    v7.log(f"baselines: FWI for {len(fwi)} days")
    rows = []
    for origin in v7.ORIGINS:
        test, ref_p, _, p = bootstrap_v7.scores(origin)
        fit = pd.concat(
            [v7.loaded(v7.fit_table(t), ("h3",)) for t in range(2015, origin - 1)],
            ignore_index=True,
        )
        xf = inputs(fit, fwi, ny, nx)
        simple = LogisticRegression(C=1.0, max_iter=2000)
        simple.fit(xf[SIMPLE], fit.label.to_numpy(), sample_weight=fit.weight.to_numpy())
        scores = {"v6_recipe": ref_p, "v7": p, **scores_of(inputs(test, fwi, ny, nx), simple)}
        crop = test.cropland.to_numpy() >= 0.5
        for subset, keep in [
            ("all", np.ones(len(test), bool)),
            ("cropland", crop),
            ("not_cropland", ~crop),
        ]:
            t = test.loc[keep]
            y, w = t.label.to_numpy() == 1, t.weight.to_numpy()
            for name, s in scores.items():
                rows.append(
                    {
                        "origin": origin,
                        "subset": subset,
                        "model": name,
                        "positives": int(y.sum()),
                        "ap": float(average_precision_score(y, s[keep], sample_weight=w)),
                        "roc_auc": float(roc_auc_score(y, s[keep], sample_weight=w)),
                        **v7.capture(t, s[keep]),
                    }
                )
        v7.log(
            f"baselines {origin}: "
            + ", ".join(
                f"{r['model']} {r['ap']:.4f}"
                for r in rows
                if r["origin"] == origin and r["subset"] == "all"
            )
        )
        pd.DataFrame(rows).to_csv(OUT / "metrics.csv", index=False)
    table = pd.DataFrame(rows)
    summary = (
        table.groupby(["subset", "model"])
        .agg(
            mean_ap=("ap", "mean"), mean_top_1pct=("top_1pct", "mean"), mean_auc=("roc_auc", "mean")
        )
        .reset_index()
    )
    wins = {}
    for subset in ["all", "cropland", "not_cropland"]:
        t = table[table.subset == subset].pivot(index="origin", columns="model", values="ap")
        best_simple = t[["climatology", "persistence", "fwi", "simple_model"]].max(axis=1)
        wins[subset] = {m: int((t[m] > best_simple).sum()) for m in ["v6_recipe", "v7"]}
    dump_json(
        OUT / "summary.json",
        {
            "origins": v7.ORIGINS,
            "mean_by_model": summary.to_dict("records"),
            "origins_where_model_beats_best_baseline_ap": wins,
            "note": "Development evidence. FWI uses ERA5 of D-1, which an operational forecast does not have.",
        },
    )
    v7.log(f"baselines summary\n{summary.to_string()}\nwins over the best baseline: {wins}")


if __name__ == "__main__":
    main()
