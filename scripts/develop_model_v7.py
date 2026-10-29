"""Model v7 development: the brief is docs/steppe-prediction-accuracy-prompt-v4-2026-10-29.md.

Commands run in order; each later command checks that the protocol is unchanged:
  protocol  - write and hash the pre-declared plan before any experiment
  samples   - one feature table per year 2015–2025 and the 2026 reassessment rows: the
              existing design-weighted rows, v6's 37 inputs rebuilt by the registered
              code, and the H1 flag
  h1        - rolling-origin test of H1 against the v6 recipe on the primary risk set
  h3        - yesterday's fires (causal 21 UTC cutoff), same engine for later hypotheses
  h2        - upper bound: reanalysis of the target day (never used for selection)
  h2_served - fitted on reanalysis, served with as-issued GFS forecasts (2025, 2026)
  h6_calibration - sigmoid, beta and isotonic calibration on one or two prior years
  v7_candidate - v6 + H3 + H2 with two-year isotonic, against the v6 recipe
  freeze    - the v7 release: fit 2015-2023, isotonic on 2024-2025 with GFS inputs
The final test is prospective (1 March – 31 October 2027) and needs a release frozen first.
"""

from __future__ import annotations

import argparse
import json
import os
import struct
import sys
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
import test_2026 as t26  # noqa: E402

from wildfire_kz import model_upgrade as mu  # noqa: E402
from wildfire_kz.calibration import fit_sigmoid  # noqa: E402
from wildfire_kz.data import checksum, dump_json, public_predictors, public_study  # noqa: E402

RUN = ROOT / "runs/model_v7"
BRIEF = ROOT / "docs/steppe-prediction-accuracy-prompt-v4-2026-10-29.md"
ORIGINS = [2020, 2021, 2022, 2023, 2024, 2025]
# Persistent heat sources (H1): distinct active days of a cell, counted causally.
HEAT_DAYS = 30
HEAT_WINDOW = (366, 2)
HEAT_YEARS_BACK = 3
PRECISION_FLOOR = (
    0.06104854900784197  # v6's 2022 precision floor, frozen in runs/model_v6/frozen.json
)
RELIABILITY_EDGES = [0, 1e-4, 3e-4, 1e-3, 3e-3, 1e-2, 3e-2, 1.0]
V5, V6, OLD = t26.V5, t26.V6, mu.OLD
IND, T26 = ROOT / "runs/independent_2025", t26.RUN
TABLES = [f"{y}_train" for y in range(2015, 2022)] + [f"{y}_evaluation" for y in range(2019, 2025)]
CELL = [
    "cell_fire_30d",
    "cell_fire_365d",
    "cell_days_since_fire",
    "cell_month_climatology",
    "nbr15_month_climatology",
]
META = ["cell_index", "cell_id", "day", "label", "weight", "x", "y_coord", "landcover"]
EPOCH = pd.Timestamp("1970-01-01", tz="UTC")


def log(message: str) -> None:
    print(datetime.now(UTC).isoformat(), message, flush=True)


def protocol() -> None:
    RUN.mkdir(parents=True, exist_ok=True)
    path = RUN / "protocol.json"
    if path.exists():
        raise FileExistsError("The v7 protocol is already registered and immutable")
    dump_json(
        path,
        {
            "synthetic": False,
            "registered_utc": datetime.now(UTC).isoformat(),
            "brief": {"path": str(BRIEF.relative_to(ROOT)), "sha256": checksum(BRIEF)},
            "purpose": "Next-day new-fire forecast for Kazakhstan that finds more real new fires than v6 at no lower precision, with calibrated values, on a risk set without persistent industrial heat sources",
            "years_already_seen": {
                "2015-2022": "development of v1-v6",
                "2023-2024": "reassessment of v1-v5 and an audit that informed v6",
                "2025": "independent test of v5",
                "2026-01-01..2026-10-15": "test of v6; its error analysis informed this protocol",
            },
            "target": "first S-NPP VIIRS nominal/high detection of an event linked within 2 km and 48 hours, 5 km LAEA cell, next day (unchanged from v1-v6)",
            "risk_set": {
                "base": "prior-year vegetated cover, frozen industrial cell list, no detection in the previous 48 hours (unchanged)",
                "h1_exclusion": f"also excluded on day D: cells with at least {HEAT_DAYS} distinct active days in [D-{HEAT_WINDOW[0]}, D-{HEAT_WINDOW[1]}], or with at least {HEAT_DAYS} active days in any of the {HEAT_YEARS_BACK} complete calendar years before D's year. Active day = any S-NPP nominal/high detection in the cell. Causal: uses only detections known before D. N chosen before this protocol from the 2015-2022 distribution of active days per cell-year (99th percentile 10, 99.9th 172); no model output was used.",
                "primary_metrics_risk_set": "base + h1_exclusion for every candidate, including references",
            },
            "data": {
                "rows": "the existing design-weighted samples: runs/public_hindcast/features/{2015..2021}_train and {2019..2024}_evaluation; 2025 the registered independent sample (runs/independent_2025/months) with features rebuilt by the same public adapter as the 2026 test",
                "labels": "2015-2025 standard-processing S-NPP archive as in the existing samples; 2026 NASA GIBS NRT for the reassessment only",
                "weights": "inverse inclusion probability of the sampling design; all metrics weighted",
            },
            "validation": {
                "scheme": "rolling origin, expanding window. At origin Y: fit on train rows of years < Y-1, calibrate on the evaluation rows of Y-1, evaluate on the evaluation rows of Y. Fit tables: *_train for 2015-2021, *_evaluation for 2022-2024 (no train tables exist for those years).",
                "origins": ORIGINS,
                "reassessment": "2026-01-01..2026-10-15 on the registered test_2026 sample, labelled 'reassessment', never 'independent test'",
            },
            "references": {
                "v6_recipe": "v6's 37 inputs and XGBoost parameters, refit at each origin with the same fit/calibration years as every candidate; trained on the base risk set",
                "v6_frozen": "the released v6 at origins 2022-2025, where it has not seen the evaluation year (reported, not used by the rule)",
            },
            "metrics": {
                "selection": "mean weighted average precision across origins on the primary risk set",
                "operating_point": "recall at the highest-recall threshold whose evaluation-year precision is not below the v6 recipe's precision at its own calibrated threshold",
                "calibrated_threshold": f"lowest threshold on the calibration year with precision >= {PRECISION_FLOOR} (v6's frozen floor); used for the reported precision and recall at a fixed threshold",
                "calibration": f"Brier skill score against the evaluation-year base rate; reliability on bins {RELIABILITY_EDGES}",
                "ranking": "weighted ROC-AUC; estimated daily capture in the top 0.1% and 1% of eligible cells",
                "user": "share of first detections with an alert within 10 km on the same or the previous day (reported, not used by the rule)",
            },
            "selection_rule": "A candidate qualifies only if at every origin its AP is higher than the v6 recipe's and its recall at the v6 recipe's precision is not lower. Among qualifiers the highest mean AP is chosen. If none qualifies, no v7 is released.",
            "release_criteria": [
                "Brier skill score > 0 at every origin",
                "in every reliability bin with >= 100 positives, observed/shown within 1/1.5 and 1.5",
                "no region with recall more than 2 percentage points below the v6 recipe without an explanation",
            ],
            "uncertainty": "1000 paired 100 km x 30 day block bootstrap draws, seed 42",
            "subgroups": [
                "region",
                "month",
                "land cover class",
                "ndvi_missing",
                "settlement distance quartile",
            ],
            "hypotheses": {
                "H1": "Exclude persistent heat sources from labels and risk set. Expect higher AP on the primary risk set and no calibrated values near 99%. Refuted if AP of the v6 recipe trained on the cleaned set is not higher at most origins.",
                "H2": "Weather for the target day. As-issued 1-day-lead forecasts (Open-Meteo Previous Runs API, all four variables) exist only from 2024; the instant archive from 2021 is near-analysis. Plan: train on reanalysis of day D-1 and D, serve with as-issued forecasts at origin 2025 and the 2026 reassessment; the reanalysis-at-D score is an upper bound reported separately and never used for selection. Refuted if the forecast-served model does not beat the 7-day-lag model at origin 2025.",
                "H3": "Fire history with a 1-day lag instead of 2, plus counts in 5/15/55 km and distance to yesterday's nearest detection. Expect higher recall during burning waves. Refuted if AP does not rise at most origins.",
                "H4": "Snow-off date, soil moisture, NDVI anomaly against the cell's prior-year climatology, dry-spell length, days since harvest on cropland. Refuted if AP does not rise at most origins.",
                "H5": "Day of week, public holidays, distance to roads and fields. Refuted if AP does not rise or it duplicates cell_month_climatology.",
                "H6": "After features: tuned gradient boosting on the rolling origins, physical monotone constraints, calibration on the two years before the origin; compare isotonic, beta and Platt. Ensembles only if they pass the rule at every origin.",
                "H7": "Report how many false alerts are fires in neighbouring cells or on the next day. Does not change the target.",
            },
            "order": "H1 first and kept if accepted; then H3, H2, H4, H5 one at a time on the same origins and base candidate; H6 last; H7 reported throughout",
            "leakage_rules": [
                "every input for day D is available before 00 UTC of D; its actual latency is recorded",
                "no scaling, imputation, climatology or exclusion list fitted with the evaluation year",
                "cell climatologies at an origin use only years before that origin",
                "negatives sampled by the existing design with inverse-probability weights",
            ],
            "release": "If a candidate passes: refit on 2015-2024, calibrate on 2025 (or the two-year scheme if H6 adopts it), freeze and hash before 2027-03-01.",
            "final_test": "Prospective, once: 2027-03-01..2027-10-31, NASA GIBS S-NPP NRT labels, opened only after the period ends; v7 versus v6 on the same full-grid cell-days; the same metrics and bootstrap.",
            "amendments": "Any change is a dated file in runs/model_v7/amendments/, written before the affected result is seen.",
            "resources": "at most two processes with OPENBLAS_NUM_THREADS=1, OMP_NUM_THREADS=2, MKL_NUM_THREADS=1; disk budget checked before each download",
            "locked": "the 18 hash-pinned source files and all v5/v6 artifacts are read-only",
        },
    )
    dump_json(RUN / "protocol.sha256.json", {"sha256": checksum(path)})
    log(f"protocol registered {checksum(path)}")


def check_protocol() -> None:
    proof = json.loads((RUN / "protocol.sha256.json").read_text())
    if checksum(RUN / "protocol.json") != proof["sha256"]:
        raise PermissionError("Protocol changed after registration")


def fast_guard() -> None:
    """The legacy year guard re-hashes the frozen release on every call; check once per input."""
    original = public_study.permitted

    @cache
    def once(years: tuple, release_path: Path | None) -> None:
        original(list(years), release_path)

    def cached(years, release_path=None):
        once(tuple(years), release_path)

    public_study.permitted = cached
    public_predictors.permitted = cached


def detections() -> tuple[pd.DataFrame, pd.DataFrame]:
    """All-confidence history (as the frozen models use) and nominal/high active days (H1)."""
    history = mu.load_history(2024, V5 / "release.json")
    strong = []
    for year in range(2014, 2025):
        f = pd.read_parquet(
            ROOT / f"data/real/normalized/detections_{year}.parquet",
            columns=["cell_id", "timestamp", "confidence"],
        )
        strong.append(f[f.confidence.isin(["n", "h"])])
    columns = ["cell_id", "timestamp", "confidence"]
    raw25 = pd.read_parquet(IND / "detections_2025.parquet", columns=columns)
    raw26 = pd.read_parquet(T26 / "detections_2026.parquet", columns=columns)
    extra = pd.concat([raw25, raw26], ignore_index=True)
    extra["day"] = extra.timestamp.dt.floor("D")
    history = pd.concat([history, extra[["cell_id", "day"]]], ignore_index=True).drop_duplicates()
    strong.append(extra[extra.confidence.isin(["n", "h"])])
    both = pd.concat(strong, ignore_index=True)
    both["day"] = both.timestamp.dt.floor("D")
    return history, both[["cell_id", "day"]].drop_duplicates()


class HeatRule:
    """H1: persistent heat sources from nominal/high active days known before the target day."""

    def __init__(self, strong: pd.DataFrame, index: pd.Series):
        cells = strong.cell_id.map(index)
        keep = cells.notna().to_numpy()
        self.n = len(index)
        day_no = (strong.day[keep] - EPOCH).dt.days.to_numpy()
        cell = cells[keep].to_numpy(dtype=np.int64)
        order = np.argsort(day_no, kind="stable")
        day_no, cell = day_no[order], cell[order]
        cuts = np.flatnonzero(np.diff(day_no)) + 1
        self.active = {
            int(d[0]): c for d, c in zip(np.split(day_no, cuts), np.split(cell, cuts), strict=True)
        }
        years = (pd.to_datetime(day_no, unit="D")).year.to_numpy()
        self.annual = {
            int(y): np.bincount(cell[years == y], minlength=self.n) for y in np.unique(years)
        }

    def flag(self, keys: pd.DataFrame) -> np.ndarray:
        target = (keys.day - EPOCH).dt.days.to_numpy()
        year = keys.day.dt.year.to_numpy()
        ci = keys.cell_index.to_numpy()
        out = np.zeros(len(keys), dtype=bool)
        first, last = HEAT_WINDOW
        for t in np.unique(target):
            idx = np.flatnonzero(target == t)
            counts = np.zeros(self.n, dtype=np.int32)
            for d in range(t - first, t - last + 1):
                a = self.active.get(d)
                if a is not None:
                    counts[a] += 1
            y = int(year[idx[0]])
            past = np.zeros(self.n, dtype=bool)
            for back in range(1, HEAT_YEARS_BACK + 1):
                if y - back in self.annual:
                    past |= self.annual[y - back] >= HEAT_DAYS
            out[idx] = (counts[ci[idx]] >= HEAT_DAYS) | past[ci[idx]]
        return out


def regions(ids: pd.Index) -> np.ndarray:
    rows = struct.iter_unpack("<hhfffH8H", (ROOT / "platform/dist/assets/cells.bin").read_bytes())
    return pd.Series({f"g5000_{r[0]}_{r[1]}": r[5] for r in rows}).reindex(ids).to_numpy()


def extend(frame, history, cells, heat, region) -> pd.DataFrame:
    """v6's neighbourhood and cell history, the H1 flag and the region of each row."""
    f = mu.augment(frame, mu.FireHistory(history), V5 / "release.json")
    for name, values in cells.features(f).items():
        f[name] = values
    f["heat_source"] = heat.flag(f)
    f["region"] = region[f.cell_index.to_numpy()]
    return f


def write(name: str, f: pd.DataFrame, gate: dict) -> None:
    features = json.loads((V6 / "frozen.json").read_text())["features"]
    cols = [c for c in META if c in f] + ["region", "heat_source", "ndvi_missing", *features]
    out = f[list(dict.fromkeys(cols))].reset_index(drop=True)
    path = RUN / f"samples/{name}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(path, index=False)
    dump_json(
        path.with_suffix(".sha256.json"), {"sha256": checksum(path), "rows": len(out), **gate}
    )
    log(
        f"{name}: {len(out)} rows, {int(out.label.sum())} positives, {int(out.heat_source.sum())} heat rows"
    )


def scored(frame: pd.DataFrame, which: str) -> np.ndarray:
    run = V5 if which == "v5" else V6
    model, cal = joblib.load(run / "model.joblib"), joblib.load(run / "calibrator.joblib")
    raw = model["estimator"].predict_proba(frame[model["features"]])[:, 1]
    return mu.published_probability(cal.predict(raw))


def samples() -> None:
    check_protocol()
    fast_guard()
    t26.verify_v6()
    ids = pd.Index(public_predictors.geography()[0].cell_id)
    index = pd.Series(np.arange(len(ids)), index=ids)
    region = regions(ids)
    history, strong = detections()
    heat = HeatRule(strong, index)
    cells = t26.CellHistory(
        history.assign(cell=history.cell_id.map(index))
        .dropna(subset=["cell"])
        .astype({"cell": np.int64}),
        len(ids),
    )
    log("history ready")

    for name in TABLES:
        if (RUN / f"samples/{name}.parquet").exists():
            continue
        base = pd.read_parquet(OLD / f"features/{name}.parquet")
        gate = {"base_table_sha256": checksum(OLD / f"features/{name}.parquet")}
        f = extend(base, history, cells, heat, region)
        if name == "2015_train":
            # The one v6 development table still on disk: rebuilt features must equal it.
            old = pd.read_parquet(V6 / "features/2015_train.parquet")
            for c in CELL + mu.HISTORY:
                if not np.array_equal(old[c].to_numpy(), f[c].to_numpy().astype(old[c].dtype)):
                    raise ValueError(f"Rebuilt {c} differs from v6 development")
            gate["matches_v6_development_features"] = True
        write(name, f, gate)

    # 2025 and 2026: registered samples, inputs rebuilt by the registered 2026 test code.
    for name, source, column, model in [
        ("2025_evaluation", IND / "months", "probability", "v5"),
        ("2026_reassessment", T26 / "months", "p_v6", "v6"),
    ]:
        if (RUN / f"samples/{name}.parquet").exists():
            continue
        parts, worst = [], 0.0
        for month in sorted(source.glob("*.parquet")):
            rows = pd.read_parquet(month)
            keys = rows[["day", "label", "weight", "q"]].assign(
                cell_index=rows.cell_id.map(index).to_numpy()
            )
            frame = t26.feature_frame(keys)
            frame = frame[frame.required_features_valid].reset_index(drop=True)
            f = extend(frame, history, cells, heat, region)
            registered = rows.set_index(["cell_id", "day"])[column]
            mine = pd.Series(
                scored(f, model), index=pd.MultiIndex.from_frame(f[["cell_id", "day"]])
            )
            common = registered.index.intersection(mine.index)
            gap = float(np.abs(registered[common].to_numpy() - mine[common].to_numpy()).max())
            worst = max(worst, gap)
            log(
                f"{name} {month.stem}: {len(f)} of {len(rows)} rows rebuilt, "
                f"max |p - registered {model}| = {gap:.3g}"
            )
            parts.append(f[f.set_index(["cell_id", "day"]).index.isin(registered.index)])
        f = pd.concat(parts, ignore_index=True)
        write(
            name,
            f,
            {
                "source": str(source.relative_to(ROOT)),
                "registered_column": column,
                "max_abs_gap": worst,
            },
        )


# ---------- rolling-origin experiments ----------
PARAMS = {
    "learning_rate": 0.06252287916406217,
    "max_depth": 5,
    "min_child_weight": 6.440260565429631,
    "n_estimators": 314,
    "reg_alpha": 0.006789053271698486,
    "reg_lambda": 0.14742753159914673,
}
DRAWS = int(os.environ.get("V7_DRAWS", "1000"))  # 0 = point estimates only, a preview


def sample(name: str) -> pd.DataFrame:
    return pd.read_parquet(RUN / f"samples/{name}.parquet")


def fit_table(year: int) -> str:
    return f"{year}_train" if year <= 2021 else f"{year}_evaluation"


@cache
def industrial() -> frozenset:
    return frozenset(json.loads((OLD / "industrial_cells.json").read_text())["cell_ids"])


def primary(frame: pd.DataFrame) -> pd.DataFrame:
    """Primary risk set: base rules (frozen industrial list) plus the H1 exclusion."""
    keep = ~frame.cell_id.isin(industrial()) & ~frame.heat_source
    return frame.loc[keep.to_numpy()].reset_index(drop=True)


def capture(frame: pd.DataFrame, score: np.ndarray) -> dict[str, float]:
    """Estimated share of positives inside each day's top k% of eligible cells (as in v6)."""
    out = {}
    f = frame[["day", "label", "weight"]].assign(score=score)
    for name, share in {"top_0.1pct": 0.001, "top_1pct": 0.01}.items():
        hit = 0.0
        for _, g in f.groupby("day"):
            g = g.sort_values("score", ascending=False)
            inside = g.weight.cumsum().to_numpy() <= share * g.weight.sum()
            hit += g.label.to_numpy()[inside].sum()
        out[name] = float(hit / f.label.sum())
    return out


def recall_at(y, p, w, precision_floor: float) -> float:
    precision, recall, _ = precision_recall_curve(y, p, sample_weight=w)
    ok = precision[:-1] >= precision_floor
    return float(recall[:-1][ok].max()) if ok.any() else 0.0


def at_threshold(y, p, w, threshold: float) -> tuple[float, float]:
    alert = p >= threshold
    tp, fp, fn = (w * (alert & y)).sum(), (w * (alert & ~y)).sum(), (w * (~alert & y)).sum()
    return float(tp / max(tp + fp, 1e-12)), float(tp / max(tp + fn, 1e-12))


def reliability(y, p, w) -> list[dict]:
    b = np.clip(
        np.searchsorted(RELIABILITY_EDGES, p, side="right") - 1, 0, len(RELIABILITY_EDGES) - 2
    )
    rows = []
    for i in range(len(RELIABILITY_EDGES) - 1):
        m = b == i
        weight = float(w[m].sum())
        rows.append(
            {
                "low": RELIABILITY_EDGES[i],
                "high": RELIABILITY_EDGES[i + 1],
                "predicted": float((p[m] * w[m]).sum() / weight) if weight else None,
                "observed": float((y[m] * w[m]).sum() / weight) if weight else None,
                "positives": int(y[m].sum()),
            }
        )
    return rows


def metrics(frame: pd.DataFrame, p: np.ndarray, threshold: float) -> dict:
    y, w = frame.label.to_numpy() == 1, frame.weight.to_numpy()
    base = float((w * y).sum() / w.sum())
    brier = float((w * (p - y) ** 2).sum() / w.sum())
    precision, recall = at_threshold(y, p, w, threshold)
    return {
        "rows": len(frame),
        "positives": int(y.sum()),
        "ap": float(average_precision_score(y, p, sample_weight=w)),
        "roc_auc": float(roc_auc_score(y, p, sample_weight=w)),
        **capture(frame, p),
        "brier": brier,
        "bss": 1 - brier / (base * (1 - base)),
        "threshold": threshold,
        "precision": precision,
        "recall": recall,
        "max_value": float(p.max()),
    }


def clusters(frame: pd.DataFrame) -> np.ndarray:
    """100 km x 30 day blocks, as in every earlier release test."""
    key = pd.DataFrame(
        {
            "x": np.floor(frame.x / 100_000),
            "y": np.floor(frame.y_coord / 100_000),
            "t": (frame.day.dt.dayofyear - 1) // 30,
        }
    )
    return key.groupby(["x", "y", "t"]).ngroup().to_numpy()


def train(fit: pd.DataFrame, features: list[str]) -> XGBClassifier:
    clf = XGBClassifier(
        **PARAMS, objective="binary:logistic", tree_method="hist", random_state=42, n_jobs=4
    )
    clf.fit(fit[features], fit.label, sample_weight=fit.weight.to_numpy())
    return clf


def calibrate(clf, cal: pd.DataFrame, features: list[str], year: int):
    raw = clf.predict_proba(cal[features])[:, 1]
    calibration, _ = fit_sigmoid(cal, raw, year)
    p = mu.published_probability(calibration.predict(raw))
    point = mu.operating_point(cal.label.to_numpy(), p, cal.weight.to_numpy(), PRECISION_FLOOR)
    return calibration, point["threshold"]


def h1() -> None:
    """H1: does training without persistent heat sources beat the v6 recipe on the clean risk set?"""
    check_protocol()
    out = RUN / "experiments/h1"
    out.mkdir(parents=True, exist_ok=True)
    features = json.loads((V6 / "frozen.json").read_text())["features"]
    frozen = joblib.load(V6 / "model.joblib"), joblib.load(V6 / "calibrator.joblib")
    frozen_threshold = json.loads((V6 / "frozen.json").read_text())["threshold"]
    rows, boot, rel = [], {}, {}
    for origin in ORIGINS:
        fit_all = pd.concat(
            [sample(fit_table(y)) for y in range(2015, origin - 1)], ignore_index=True
        )
        fit_clean = fit_all.loc[
            (~fit_all.cell_id.isin(industrial()) & ~fit_all.heat_source).to_numpy()
        ]
        cal = primary(sample(f"{origin - 1}_evaluation"))
        test = primary(sample(f"{origin}_evaluation"))
        y, w = test.label.to_numpy() == 1, test.weight.to_numpy()
        scores = {}
        for name, fit in [("v6_recipe", fit_all), ("h1_clean", fit_clean)]:
            clf = train(fit, features)
            calibration, threshold = calibrate(clf, cal, features, origin - 1)
            p = mu.published_probability(
                calibration.predict(clf.predict_proba(test[features])[:, 1])
            )
            scores[name] = (p, threshold)
        if origin >= 2022:
            raw = frozen[0]["estimator"].predict_proba(test[features])[:, 1]
            scores["v6_frozen"] = (
                mu.published_probability(frozen[1].predict(raw)),
                frozen_threshold,
            )
        ref_p, ref_t = scores["v6_recipe"]
        ref_precision, _ = at_threshold(y, ref_p, w, ref_t)
        for name, (p, threshold) in scores.items():
            rows.append(
                {
                    "origin": origin,
                    "model": name,
                    **metrics(test, p, threshold),
                    "recall_at_v6_recipe_precision": recall_at(y, p, w, ref_precision),
                }
            )
            rel[f"{origin}/{name}"] = reliability(y, p, w)
            log(
                f"{origin} {name} ap={rows[-1]['ap']:.5f} recall@ref={rows[-1]['recall_at_v6_recipe_precision']:.4f} bss={rows[-1]['bss']:.4f}"
            )

        # Paired block bootstrap: h1_clean minus v6_recipe on the same resampled rows.
        group = clusters(test)
        rng = np.random.default_rng(42)
        cand_p = scores["h1_clean"][0]
        draws = {"ap": [], "recall_at_v6_recipe_precision": []}
        for _ in range(DRAWS):
            counts = np.bincount(
                rng.integers(0, group.max() + 1, group.max() + 1), minlength=group.max() + 1
            )
            m = counts[group] * w
            keep = m > 0
            yy, mm = y[keep], m[keep]
            if yy.sum() == 0:
                continue
            draws["ap"].append(
                average_precision_score(yy, cand_p[keep], sample_weight=mm)
                - average_precision_score(yy, ref_p[keep], sample_weight=mm)
            )
            floor, _ = at_threshold(yy, ref_p[keep], mm, ref_t)
            draws["recall_at_v6_recipe_precision"].append(
                recall_at(yy, cand_p[keep], mm, floor) - recall_at(yy, ref_p[keep], mm, floor)
            )
        boot[str(origin)] = {
            k: [float(np.quantile(v, 0.025)), float(np.quantile(v, 0.975))]
            for k, v in draws.items()
        }
        log(f"{origin} bootstrap {boot[str(origin)]}")
        pd.DataFrame(rows).to_csv(out / "metrics.csv", index=False)

    table = pd.DataFrame(rows)
    wins = 0
    for origin in ORIGINS:
        c = table[(table.origin == origin) & (table.model == "h1_clean")].iloc[0]
        r = table[(table.origin == origin) & (table.model == "v6_recipe")].iloc[0]
        wins += int(c.ap > r.ap)
    decision = {
        "hypothesis": "H1",
        "rule": json.loads((RUN / "protocol.json").read_text())["hypotheses"]["H1"],
        "origins_where_clean_ap_higher": wins,
        "origins": len(ORIGINS),
        "accepted": wins > len(ORIGINS) / 2,
        "paired_bootstrap_95": boot,
        "evaluation_risk_set": "primary (frozen industrial list and H1 exclusion removed)",
    }
    dump_json(out / "decision.json", decision)
    dump_json(out / "reliability.json", rel)
    log(f"H1 decision: {decision['accepted']} ({wins}/{len(ORIGINS)})")


# ---------- H3: yesterday's fires ----------
H3 = ["h3_yday_15km", "h3_yday_55km", "h3_d2_15km", "h3_d2_55km", "h3_yday_distance_km"]
# A forecast issued at 00 UTC of D sees D-1 detections only after S-NPP NRT latency (about
# 3 hours), so D-1 counts stop at 21:00 UTC; the night pass runs 19-23 UTC.
YDAY_CUTOFF_HOUR = 21


def timed_detections(index: pd.Series) -> pd.DataFrame:
    """All-confidence detections with acquisition time, 2014–2026, as cell index and day."""
    frames = [
        pd.read_parquet(
            ROOT / f"data/real/normalized/detections_{y}.parquet", columns=["cell_id", "timestamp"]
        )
        for y in range(2014, 2025)
    ]
    for path in [IND / "detections_2025.parquet", T26 / "detections_2026.parquet"]:
        frames.append(pd.read_parquet(path, columns=["cell_id", "timestamp"]))
    d = pd.concat(frames, ignore_index=True)
    d["cell"] = d.cell_id.map(index)
    d = d.dropna(subset=["cell"])
    return pd.DataFrame(
        {
            "cell": d.cell.to_numpy(dtype=np.int64),
            "day_no": (d.timestamp.dt.floor("D") - EPOCH).dt.days.to_numpy(),
            "early": d.timestamp.dt.hour.to_numpy() < YDAY_CUTOFF_HOUR,
        }
    )


def h3_features() -> None:
    """Counts of active cells yesterday (before the cutoff) and the day before, and distance."""
    from scipy.ndimage import distance_transform_edt, uniform_filter

    check_protocol()
    fast_guard()
    ids = pd.Index(public_predictors.geography()[0].cell_id)
    index = pd.Series(np.arange(len(ids)), index=ids)
    _, gr, gc, shape = t26._grid()
    d = timed_detections(index)
    early = {int(k): g.cell.unique() for k, g in d[d.early].groupby("day_no")}
    full = {int(k): g.cell.unique() for k, g in d.groupby("day_no")}
    empty = np.empty(0, dtype=np.int64)

    def image(cells: np.ndarray) -> np.ndarray:
        img = np.zeros(shape, dtype=np.float32)
        img[gr[cells], gc[cells]] = 1
        return img

    out_dir = RUN / "features_h3"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in [*TABLES, "2025_evaluation", "2026_reassessment"]:
        path = out_dir / f"{name}.parquet"
        if path.exists():
            continue
        f = sample(name)[["cell_index", "day"]]
        target = (f.day - EPOCH).dt.days.to_numpy()
        ci = f.cell_index.to_numpy()
        out = {c: np.zeros(len(f), dtype=np.float32) for c in H3}
        for t in np.unique(target):
            idx = np.flatnonzero(target == t)
            r, c = gr[ci[idx]], gc[ci[idx]]
            one, two = image(early.get(int(t) - 1, empty)), image(full.get(int(t) - 2, empty))
            for img, tag in [(one, "yday"), (two, "d2")]:
                for size, km in [(3, 15), (11, 55)]:
                    total = uniform_filter(img, size=size, mode="constant") * size * size
                    out[f"h3_{tag}_{km}km"][idx] = np.rint(total[r, c])
            if one.any():
                distance = distance_transform_edt(one == 0) * 5
                out["h3_yday_distance_km"][idx] = np.minimum(distance[r, c], 200)
            else:
                out["h3_yday_distance_km"][idx] = 200
        pd.DataFrame(out).to_parquet(path, index=False)
        dump_json(
            path.with_suffix(".sha256.json"),
            {"sha256": checksum(path), "sample_sha256": checksum(RUN / f"samples/{name}.parquet")},
        )
        log(f"h3 features {name}")


def loaded(name: str, extras: tuple[str, ...]) -> pd.DataFrame:
    f = sample(name)
    for extra in extras:
        f = pd.concat([f, pd.read_parquet(RUN / f"features_{extra}/{name}.parquet")], axis=1)
    return f


def experiment(
    tag: str,
    candidates: dict[str, list[str]],
    extras: tuple[str, ...],
    rule: str | None = None,
    origins: list[int] = ORIGINS,
    eval_extras: tuple[str, ...] | None = None,
) -> None:
    """One hypothesis on the rolling origins: each candidate against the v6 recipe.

    Same fit/calibration/evaluation years and risk sets as H1; all rows used for fitting,
    as v6 was fitted; metrics on the primary risk set. `eval_extras` swaps inputs for the
    calibration and evaluation rows only (forecasts served to a model fitted on reanalysis).
    """
    check_protocol()
    out = RUN / f"experiments/{tag}"
    out.mkdir(parents=True, exist_ok=True)
    v6_features = json.loads((V6 / "frozen.json").read_text())["features"]
    models = {"v6_recipe": v6_features, **candidates}
    rows, boot, rel = [], {}, {}
    served = eval_extras or extras
    origins = [int(o) for o in os.environ.get("V7_ORIGINS", ",".join(map(str, origins))).split(",")]
    for origin in origins:
        fit = pd.concat(
            [loaded(fit_table(y), extras) for y in range(2015, origin - 1)], ignore_index=True
        )
        cal = primary(loaded(evaluation_name(origin - 1), served))
        test = primary(loaded(evaluation_name(origin), served))
        y, w = test.label.to_numpy() == 1, test.weight.to_numpy()
        scores = {}
        for name, features in models.items():
            clf = train(fit, features)
            calibration, threshold = calibrate(clf, cal, features, origin - 1)
            p = mu.published_probability(
                calibration.predict(clf.predict_proba(test[features])[:, 1])
            )
            scores[name] = (p, threshold)
        ref_p, ref_t = scores["v6_recipe"]
        ref_precision, _ = at_threshold(y, ref_p, w, ref_t)
        for name, (p, threshold) in scores.items():
            rows.append(
                {
                    "origin": origin,
                    "model": name,
                    **metrics(test, p, threshold),
                    "recall_at_v6_recipe_precision": recall_at(y, p, w, ref_precision),
                }
            )
            rel[f"{origin}/{name}"] = reliability(y, p, w)
            log(
                f"{tag} {origin} {name} ap={rows[-1]['ap']:.5f} "
                f"recall@ref={rows[-1]['recall_at_v6_recipe_precision']:.4f} bss={rows[-1]['bss']:.4f}"
            )
        group = clusters(test)
        n_groups = group.max() + 1
        for name in candidates if DRAWS else []:
            rng = np.random.default_rng(42)
            cand_p = scores[name][0]
            draws: dict[str, list[float]] = {"ap": [], "recall_at_v6_recipe_precision": []}
            for _ in range(DRAWS):
                counts = np.bincount(rng.integers(0, n_groups, n_groups), minlength=n_groups)
                m = counts[group] * w
                keep = m > 0
                yy, mm = y[keep], m[keep]
                if yy.sum() == 0:
                    continue
                draws["ap"].append(
                    average_precision_score(yy, cand_p[keep], sample_weight=mm)
                    - average_precision_score(yy, ref_p[keep], sample_weight=mm)
                )
                floor, _ = at_threshold(yy, ref_p[keep], mm, ref_t)
                draws["recall_at_v6_recipe_precision"].append(
                    recall_at(yy, cand_p[keep], mm, floor) - recall_at(yy, ref_p[keep], mm, floor)
                )
            boot[f"{origin}/{name}"] = {
                k: [float(np.quantile(v, 0.025)), float(np.quantile(v, 0.975))]
                for k, v in draws.items()
            }
            log(f"{tag} {origin} {name} bootstrap {boot[f'{origin}/{name}']}")
        pd.DataFrame(rows).to_csv(out / "metrics.csv", index=False)

    table = pd.DataFrame(rows)
    decisions = {}
    for name in candidates:
        wins = sum(
            int(
                table[(table.origin == o) & (table.model == name)].ap.iloc[0]
                > table[(table.origin == o) & (table.model == "v6_recipe")].ap.iloc[0]
            )
            for o in origins
        )
        decisions[name] = {"origins_with_higher_ap": wins, "accepted": wins > len(origins) / 2}
    dump_json(
        out / "decision.json",
        {
            "hypothesis": rule or tag.upper(),
            "rule": json.loads((RUN / "protocol.json").read_text())["hypotheses"][
                rule or tag.upper()
            ],
            "candidates": decisions,
            "origins": origins,
            "fit_inputs": list(extras),
            "evaluation_inputs": list(served),
            "paired_bootstrap_95": boot,
            "evaluation_risk_set": "primary (frozen industrial list and H1 exclusion removed)",
        },
    )
    dump_json(out / "reliability.json", rel)
    log(f"{tag} decisions {decisions}")


def h3() -> None:
    h3_features()
    v6_features = json.loads((V6 / "frozen.json").read_text())["features"]
    experiment("h3", {"h3_yesterday": v6_features + H3}, ("h3",))


# ---------- H2: weather for the target day ----------
H2 = [
    "h2_tmax_d0",
    "h2_tmin_d0",
    "h2_rh_d0",
    "h2_wind_d0",
    "h2_precip_d0",
    "h2_vpd_d0",
    "h2_tmax_d1",
    "h2_rh_d1",
    "h2_wind_d1",
    "h2_precip_d1",
    "h2_precip_3d",
]
WEATHER = ROOT / "data/real/public_predictors/weather"
GFS = ROOT / "data/real/public_predictors/gfs"
DAILY = ["tmax", "tmin", "rh", "wind", "precip"]


class Weather:
    """Daily weather on the ERA5 window: reanalysis (era5) or as-issued GFS forecasts (gfs)."""

    def __init__(self, source: str):
        self.source = source
        self.years: dict[int, dict[str, np.ndarray]] = {}
        with np.load(WEATHER / "2024.npz") as z:
            self.ny, self.nx = (
                z["native_cell_y"].astype(np.int64),
                z["native_cell_x"].astype(np.int64),
            )

    def day(self, day: pd.Timestamp) -> dict[str, np.ndarray] | None:
        if self.source == "gfs":
            path = GFS / f"{day.date()}.npz"
            if not path.exists():
                return None
            with np.load(path) as z:
                return {k: z[k] for k in DAILY}
        if day.year not in self.years:
            path = WEATHER / f"{day.year}.npz"
            if not path.exists():
                return None
            with np.load(path) as z:
                self.years[day.year] = {k: z[k].copy() for k in DAILY}
        values = self.years[day.year]
        k = day.dayofyear - 1
        if k >= values["tmax"].shape[2]:
            return None
        return {name: values[name][:, :, k] for name in DAILY}


def h2_features(source: str, names: list[str]) -> None:
    """Weather of the target day D and of D-1, and precipitation over D-2..D."""
    check_protocol()
    weather = Weather(source)
    out_dir = RUN / f"features_h2{source}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        path = out_dir / f"{name}.parquet"
        if path.exists():
            continue
        f = sample(name)[["cell_index", "day"]]
        ci = f.cell_index.to_numpy()
        out = {c: np.full(len(f), np.nan, dtype=np.float32) for c in H2}
        for day, idx in f.groupby("day").indices.items():
            y, x = weather.ny[ci[idx]], weather.nx[ci[idx]]
            today, yesterday, before = (weather.day(day - pd.Timedelta(days=k)) for k in (0, 1, 2))
            if today is not None:
                for v in DAILY:
                    out[f"h2_{v}_d0"][idx] = today[v][y, x]
                t, rh = today["tmax"][y, x], today["rh"][y, x]
                out["h2_vpd_d0"][idx] = 0.6108 * np.exp(17.27 * t / (t + 237.3)) * (1 - rh / 100)
            if yesterday is not None:
                for v in ["tmax", "rh", "wind", "precip"]:
                    out[f"h2_{v}_d1"][idx] = yesterday[v][y, x]
            if today is not None and yesterday is not None and before is not None:
                out["h2_precip_3d"][idx] = (
                    today["precip"][y, x] + yesterday["precip"][y, x] + before["precip"][y, x]
                )
        pd.DataFrame(out).to_parquet(path, index=False)
        dump_json(
            path.with_suffix(".sha256.json"),
            {
                "sha256": checksum(path),
                "source": source,
                "sample_sha256": checksum(RUN / f"samples/{name}.parquet"),
                "rows_with_target_day_weather": int(np.isfinite(out["h2_tmax_d0"]).sum()),
            },
        )
        log(f"h2 {source} features {name}")


def evaluation_name(year: int) -> str:
    return "2026_reassessment" if year == 2026 else f"{year}_evaluation"


def h2() -> None:
    """Upper bound: reanalysis of D and D-1 at every origin (never used for selection)."""
    h2_features("era5", [*TABLES, "2025_evaluation", "2026_reassessment"])
    v6_features = json.loads((V6 / "frozen.json").read_text())["features"]
    experiment(
        "h2_upper",
        {"h3_yesterday": v6_features + H3, "h2_reanalysis": v6_features + H3 + H2},
        ("h3", "h2era5"),
        rule="H2",
    )


def h2_served() -> None:
    """Operational: trained on reanalysis, calibrated and evaluated with as-issued forecasts."""
    h2_features("gfs", ["2024_evaluation", "2025_evaluation", "2026_reassessment"])
    v6_features = json.loads((V6 / "frozen.json").read_text())["features"]
    experiment(
        "h2_served",
        {"h3_yesterday": v6_features + H3, "h2_forecast": v6_features + H3 + H2},
        ("h3", "h2era5"),
        rule="H2",
        origins=[2025, 2026],
        eval_extras=("h3", "h2gfs"),
    )


# ---------- H6 (calibration part): which calibration gives values that mean a chance ----------
def calibration_rows(year: int, extras: tuple[str, ...]) -> pd.DataFrame:
    """Design-weighted rows of one year; the evaluation table where it exists."""
    name = f"{year}_evaluation" if year >= 2019 else f"{year}_train"
    return primary(loaded(name, extras))


class Calibrator:
    """Weighted sigmoid (Platt on the logit), beta (Kull et al.) or isotonic calibration.

    `isotonic_interp` joins the centres of the isotonic steps with straight lines: values stay
    calibrated, and the map keeps the model's own order instead of ties inside each step.
    """

    def __init__(self, method: str):
        self.method = method

    @staticmethod
    def _design(raw: np.ndarray, method: str) -> np.ndarray:
        p = np.clip(raw, 1e-7, 1 - 1e-7)
        if method == "sigmoid":
            return np.log(p / (1 - p)).reshape(-1, 1)
        return np.column_stack([np.log(p), -np.log(1 - p)])

    def fit(self, raw: np.ndarray, y: np.ndarray, w: np.ndarray) -> Calibrator:
        from sklearn.isotonic import IsotonicRegression
        from sklearn.linear_model import LogisticRegression

        if self.method.startswith("isotonic"):
            self.model = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1)
            self.model.fit(raw, y, sample_weight=w)
            if self.method == "isotonic_interp":
                step = self.model.predict(raw)
                frame = pd.DataFrame({"x": raw * w, "w": w, "v": step})
                blocks = frame.groupby("v").agg(x=("x", "sum"), w=("w", "sum")).reset_index()
                self.knots = ((blocks.x / blocks.w).to_numpy(), blocks.v.to_numpy())
        else:
            self.model = LogisticRegression(C=1e10, max_iter=2000)
            self.model.fit(self._design(raw, self.method), y, sample_weight=w)
        return self

    def predict(self, raw: np.ndarray) -> np.ndarray:
        if self.method == "isotonic":
            return self.model.predict(raw)
        if self.method == "isotonic_interp":
            # Beyond the end knots the end segments continue (capped to [0, 1]), so the
            # highest-risk cells keep their order instead of sharing the top step's value.
            x, v = self.knots
            out = np.interp(raw, x, v)
            if len(x) > 1:
                low, high = raw < x[0], raw > x[-1]
                out[low] = v[0] + (raw[low] - x[0]) * (v[1] - v[0]) / (x[1] - x[0])
                out[high] = v[-1] + (raw[high] - x[-1]) * (v[-1] - v[-2]) / (x[-1] - x[-2])
            return np.clip(out, 0, 1)
        return self.model.predict_proba(self._design(raw, self.method))[:, 1]


def reliability_spread(rows: list[dict], minimum: int = 100) -> float:
    """Largest observed/shown ratio (or its inverse) over bins with enough positives."""
    worst = 1.0
    for r in rows:
        if r["positives"] >= minimum and r["predicted"] and r["observed"]:
            ratio = r["observed"] / r["predicted"]
            worst = max(worst, ratio, 1 / ratio)
    return worst


def h6_calibration() -> None:
    check_protocol()
    out = RUN / "experiments/h6_calibration"
    out.mkdir(parents=True, exist_ok=True)
    v6_features = json.loads((V6 / "frozen.json").read_text())["features"]
    models = {"v6_recipe": v6_features, "h3_yesterday": v6_features + H3}
    # one year: fit < Y-1, calibrate Y-1 (as H1-H3); two years: fit < Y-2, calibrate Y-2..Y-1.
    schemes = {"one_year": 1, "two_years": 2}
    rows, rel = [], {}
    for origin in ORIGINS:
        test = primary(loaded(evaluation_name(origin), ("h3",)))
        y, w = test.label.to_numpy() == 1, test.weight.to_numpy()
        for scheme, years in schemes.items():
            fit = pd.concat(
                [loaded(fit_table(t), ("h3",)) for t in range(2015, origin - years)],
                ignore_index=True,
            )
            cal = pd.concat(
                [calibration_rows(t, ("h3",)) for t in range(origin - years, origin)],
                ignore_index=True,
            )
            cy, cw = cal.label.to_numpy() == 1, cal.weight.to_numpy().astype(float)
            # Each calibration year carries equal total weight, whatever its sample size.
            for t in range(origin - years, origin):
                sel = (cal.day.dt.year == t).to_numpy()
                cw[sel] = cw[sel] / cw[sel].sum()
            for name, features in models.items():
                clf = train(fit, features)
                raw_cal = clf.predict_proba(cal[features])[:, 1]
                raw_test = clf.predict_proba(test[features])[:, 1]
                for method in ["sigmoid", "beta", "isotonic", "isotonic_interp"]:
                    c = Calibrator(method).fit(raw_cal, cy, cw)
                    pc = mu.published_probability(c.predict(raw_cal))
                    p = mu.published_probability(c.predict(raw_test))
                    point = mu.operating_point(cy, pc, cw, PRECISION_FLOOR)
                    m = metrics(test, p, point["threshold"])
                    r = reliability(y, p, w)
                    key = f"{origin}/{scheme}/{name}/{method}"
                    rel[key] = r
                    rows.append(
                        {
                            "origin": origin,
                            "scheme": scheme,
                            "model": name,
                            "method": method,
                            **m,
                            "reliability_spread": reliability_spread(r),
                            "mean_shown": float((p * w).sum() / w.sum()),
                            "observed_rate": float((y * w).sum() / w.sum()),
                        }
                    )
                    log(
                        f"h6 {key} ap={m['ap']:.5f} bss={m['bss']:.4f} "
                        f"spread=x{rows[-1]['reliability_spread']:.2f}"
                    )
        pd.DataFrame(rows).to_csv(out / "metrics.csv", index=False)
    table = pd.DataFrame(rows)
    summary = (
        table.groupby(["scheme", "model", "method"])
        .agg(
            mean_bss=("bss", "mean"),
            min_bss=("bss", "min"),
            origins_bss_positive=("bss", lambda s: int((s > 0).sum())),
            worst_spread=("reliability_spread", "max"),
            mean_ap=("ap", "mean"),
        )
        .reset_index()
    )
    summary.to_csv(out / "summary.csv", index=False)
    passing = summary[(summary.min_bss > 0) & (summary.worst_spread <= 1.5)]
    dump_json(
        out / "decision.json",
        {
            "hypothesis": "H6 (calibration part)",
            "criteria": "BSS > 0 at every origin and every reliability bin with >= 100 positives within x1.5",
            "passing": passing.to_dict("records"),
            "best_by_mean_bss": summary.sort_values("mean_bss", ascending=False)
            .head(3)
            .to_dict("records"),
        },
    )
    dump_json(out / "reliability.json", rel)
    log(f"h6 summary\n{summary.to_string()}")


# ---------- v7 candidate and release ----------
def v7_features() -> list[str]:
    return json.loads((V6 / "frozen.json").read_text())["features"] + H3 + H2


def weather_inputs(year: int) -> tuple[str, ...]:
    """As-issued GFS where the archive has it (2024+), reanalysis before."""
    return ("h3", "h2gfs") if year >= 2024 else ("h3", "h2era5")


def isotonic_two_years(raw: np.ndarray, cal: pd.DataFrame):
    from sklearn.isotonic import IsotonicRegression

    w = cal.weight.to_numpy().astype(float)
    for t in cal.day.dt.year.unique():
        sel = (cal.day.dt.year == t).to_numpy()
        w[sel] = w[sel] / w[sel].sum()
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0, y_max=1)
    iso.fit(raw, cal.label.to_numpy(), sample_weight=w)
    return iso, w


def v7_candidate() -> None:
    """v6 + H3 + H2 with two-year isotonic calibration against the v6 recipe at every origin."""
    check_protocol()
    out = RUN / "experiments/v7_candidate"
    out.mkdir(parents=True, exist_ok=True)
    features, v6_features = v7_features(), json.loads((V6 / "frozen.json").read_text())["features"]
    rows = []
    for origin in ORIGINS:
        test = primary(loaded(evaluation_name(origin), weather_inputs(origin)))
        y, w = test.label.to_numpy() == 1, test.weight.to_numpy()
        # Reference: the v6 recipe exactly as in H1-H3 (fit < Y-1, sigmoid on Y-1).
        fit_ref = pd.concat(
            [loaded(fit_table(t), ("h3",)) for t in range(2015, origin - 1)], ignore_index=True
        )
        ref = train(fit_ref, v6_features)
        cal_ref = primary(loaded(evaluation_name(origin - 1), ("h3",)))
        calibration, ref_t = calibrate(ref, cal_ref, v6_features, origin - 1)
        ref_p = mu.published_probability(
            calibration.predict(ref.predict_proba(test[v6_features])[:, 1])
        )
        ref_precision, _ = at_threshold(y, ref_p, w, ref_t)
        # Candidate: fit < Y-2 on reanalysis, isotonic on Y-2..Y-1 with the inputs of those years.
        fit = pd.concat(
            [loaded(fit_table(t), ("h3", "h2era5")) for t in range(2015, origin - 2)],
            ignore_index=True,
        )
        clf = train(fit, features)
        cal = pd.concat(
            [calibration_rows(t, weather_inputs(t)) for t in (origin - 2, origin - 1)],
            ignore_index=True,
        )
        iso, cw = isotonic_two_years(clf.predict_proba(cal[features])[:, 1], cal)
        pc = mu.published_probability(iso.predict(clf.predict_proba(cal[features])[:, 1]))
        threshold = mu.operating_point(cal.label.to_numpy(), pc, cw, PRECISION_FLOOR)["threshold"]
        p = mu.published_probability(iso.predict(clf.predict_proba(test[features])[:, 1]))
        for name, score, t in [("v6_recipe", ref_p, ref_t), ("v7", p, threshold)]:
            rel_rows = reliability(y, score, w)
            rows.append(
                {
                    "origin": origin,
                    "model": name,
                    "inputs": "gfs" if origin >= 2024 and name == "v7" else "reanalysis",
                    **metrics(test, score, t),
                    "recall_at_v6_recipe_precision": recall_at(y, score, w, ref_precision),
                    "reliability_spread": reliability_spread(rel_rows),
                }
            )
            log(
                f"v7 {origin} {name} ap={rows[-1]['ap']:.5f} "
                f"recall@ref={rows[-1]['recall_at_v6_recipe_precision']:.4f} "
                f"bss={rows[-1]['bss']:.4f} spread=x{rows[-1]['reliability_spread']:.2f}"
            )
        pd.DataFrame(rows).to_csv(out / "metrics.csv", index=False)


def freeze() -> None:
    """Release: fit 2015–2023 on reanalysis, isotonic on 2024–2025 with as-issued GFS inputs."""
    check_protocol()
    if (RUN / "release.json").exists():
        raise FileExistsError("The v7 release is frozen and immutable")
    features = v7_features()
    fit = pd.concat(
        [loaded(fit_table(t), ("h3", "h2era5")) for t in range(2015, 2024)], ignore_index=True
    )
    clf = train(fit, features)
    cal = pd.concat(
        [calibration_rows(t, weather_inputs(t)) for t in (2024, 2025)], ignore_index=True
    )
    raw = clf.predict_proba(cal[features])[:, 1]
    iso, cw = isotonic_two_years(raw, cal)
    point = mu.operating_point(
        cal.label.to_numpy(), mu.published_probability(iso.predict(raw)), cw, PRECISION_FLOOR
    )
    joblib.dump({"estimator": clf, "features": features}, RUN / "model.joblib", compress=3)
    joblib.dump(iso, RUN / "calibrator.joblib", compress=3)
    dump_json(
        RUN / "frozen.json",
        {
            "synthetic": False,
            "model": "xgboost_v7",
            "features": features,
            "threshold": point["threshold"],
            "calibration_metrics": point,
            "precision_floor": PRECISION_FLOOR,
            "fit_years": [2015, 2023],
            "calibration": "isotonic, 2024 and 2025 weighted equally, primary risk set",
            "weather": "fit on ERA5 reanalysis of the target day; served with the GFS 18 UTC run of the previous day (1°, src/wildfire_kz/data/gfs_forecasts.py)",
            "yesterday_cutoff_utc_hour": YDAY_CUTOFF_HOUR,
            "risk_set": "frozen industrial list, no detection in 48 h, H1 persistent heat-source rule",
            "test_used_for_selection": False,
            "operational_validation": False,
            "transport": "float16 before metrics",
        },
    )
    artifacts = ["model.joblib", "calibrator.joblib", "frozen.json", "protocol.json"]
    dump_json(
        RUN / "release.json",
        {
            "synthetic": False,
            "frozen_utc": datetime.now(UTC).isoformat(),
            "prospective_test": "2027-03-01..2027-10-31, labels opened after it ends",
            "labels_used": "2015-2025",
            "artifacts": {a: checksum(RUN / a) for a in artifacts},
            "code": {
                str(Path(f).relative_to(ROOT)): checksum(Path(f))
                for f in [__file__, ROOT / "src/wildfire_kz/data/gfs_forecasts.py"]
            },
        },
    )
    log(f"v7 frozen: threshold {point['threshold']:.6f}, calibration {point}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=[
            "protocol",
            "samples",
            "h1",
            "h3",
            "h2",
            "h2_served",
            "h6_calibration",
            "v7_candidate",
            "freeze",
        ],
    )
    a = parser.parse_args()
    {
        "protocol": protocol,
        "samples": samples,
        "h1": h1,
        "h3": h3,
        "h2": h2,
        "h2_served": h2_served,
        "h6_calibration": h6_calibration,
        "v7_candidate": v7_candidate,
        "freeze": freeze,
    }[a.command]()
