"""Stage 5 — stratified negative sampling with documented inclusion probabilities.

Two designs are drawn for every year, both stratified by h = (year, month, land-cover group):

* **training design** — all positives (q = 1); negatives by simple random sampling without
  replacement with n_h = min(N_h, max(round(r * P_h), m)), where r is the target negatives
  per positive and m the minimum allocation (so strata without observed fires still get
  negatives). q_h = n_h / N_h and the inverse-inclusion weight 1 / q_h makes weighted totals
  reproduce the complete risk set (exactly for SRSWOR within strata).
* **evaluation design** — unbalanced: all positives and either every negative
  (``eval_negative_fraction = 1``) or a stratified probability sample with weights 1 / q_h.

Strata are nested within calendar years so that the samples of different split partitions
(development / calibration / test) are drawn independently of each other.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from wildfire_kz.config.schema import Config
from wildfire_kz.features.landcover import landcover_fractions
from wildfire_kz.grid.grid import GridMeta, load_grid
from wildfire_kz.utils.io import read_partitions, write_partition
from wildfire_kz.utils.runtime import derive_seed, get_logger, write_json

log = get_logger("sampling")


def allocate_training(n_neg: int, n_pos: int, ratio: float, minimum: int) -> int:
    return int(min(n_neg, max(round(ratio * n_pos), minimum)))


def allocate_evaluation(n_neg: int, fraction: float) -> int:
    return n_neg if fraction >= 1.0 else int(min(n_neg, math.ceil(fraction * n_neg)))


def stratified_sample(
    df: pd.DataFrame,
    strata_cols: Sequence[str],
    design: str,
    cfg: Config,
) -> tuple[pd.Series, pd.Series, pd.DataFrame]:
    """Return (inclusion indicator, inclusion probability q, strata table) for one design."""
    sc = cfg.sampling
    included = pd.Series(False, index=df.index)
    q = pd.Series(np.nan, index=df.index)
    rows = []
    pos_mask = df["label"] == 1
    included[pos_mask] = True
    q[pos_mask] = 1.0
    for key, g in df.groupby(list(strata_cols), sort=True, observed=True):
        key_t = key if isinstance(key, tuple) else (key,)
        neg_idx = g.index[g["label"] == 0]
        n_pos, n_neg = int((g["label"] == 1).sum()), len(neg_idx)
        if design == "train":
            n = allocate_training(
                n_neg, n_pos, sc.negatives_per_positive, sc.min_negatives_per_stratum
            )
        else:
            n = allocate_evaluation(n_neg, sc.eval_negative_fraction)
        rng = np.random.default_rng(derive_seed(cfg.project.seed, "sampling", design, *key_t))
        chosen = (
            rng.choice(neg_idx.to_numpy(), size=n, replace=False)
            if n < n_neg
            else neg_idx.to_numpy()
        )
        qh = n / n_neg if n_neg else 1.0
        included[chosen] = True
        q[chosen] = qh
        rows.append(
            {
                **dict(zip(strata_cols, key_t, strict=True)),
                "design": design,
                "N_negatives": n_neg,
                "P_positives": n_pos,
                "n_sampled_negatives": n,
                "q_h": qh,
                "weight": 1.0 / qh if qh > 0 else np.nan,
            }
        )
    return included, q, pd.DataFrame(rows)


def run_sampling(
    cfg: Config, grid_file: Path, grid_meta_file: Path, risk_dir: Path, out_dir: Path
) -> dict[str, Any]:
    grid = load_grid(grid_file)
    meta = GridMeta.load(grid_meta_file)
    years = cfg.study.years
    lc = landcover_fractions(cfg, grid, meta, years)
    out_dir.mkdir(parents=True, exist_ok=True)
    lc.to_parquet(out_dir / "landcover_fractions.parquet", index=False)
    strata_cols = list(cfg.sampling.strata)
    tables = []
    summary: dict[str, Any] = {}
    for year in years:
        rs = read_partitions(risk_dir / "risk_set", "year", [year])
        rs = rs.merge(lc.loc[lc["year"] == year, ["cell_id", "lc_group"]], on="cell_id", how="left")
        rs["lc_group"] = rs["lc_group"].fillna("other")
        rs["month"] = pd.to_datetime(rs["date"]).dt.month.astype(np.int8)
        rs["year"] = year
        inc_t, q_t, tab_t = stratified_sample(rs, strata_cols, "train", cfg)
        inc_e, q_e, tab_e = stratified_sample(rs, strata_cols, "eval", cfg)
        keep = inc_t | inc_e
        out = rs.loc[keep].copy()
        out["in_train"] = inc_t[keep].to_numpy()
        out["in_eval"] = inc_e[keep].to_numpy()
        out["q_train"] = q_t[keep].to_numpy()
        out["q_eval"] = q_e[keep].to_numpy()
        out["w_train"] = np.where(out["in_train"], 1.0 / out["q_train"], 0.0)
        out["w_eval"] = np.where(out["in_eval"], 1.0 / out["q_eval"], 0.0)
        out["stratum"] = out[strata_cols].astype(str).agg("|".join, axis=1)
        write_partition(
            out.drop(columns="year").reset_index(drop=True), out_dir / "sample", "year", year
        )
        tables += [tab_t, tab_e]
        summary[str(year)] = {
            "risk_set_cell_days": len(rs),
            "positives": int(rs["label"].sum()),
            "train_rows": int(out["in_train"].sum()),
            "eval_rows": int(out["in_eval"].sum()),
            "train_weight_total": float(out["w_train"].sum()),
            "eval_weight_total": float(out["w_eval"].sum()),
        }
        log.info("sampling %d: %s", year, summary[str(year)])
    pd.concat(tables, ignore_index=True).to_csv(
        out_dir / "strata_inclusion_probabilities.csv", index=False
    )
    write_json(out_dir / "sampling_summary.json", summary)
    return summary
