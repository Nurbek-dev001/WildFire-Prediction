"""Causal spatial/fire-history features for the separately versioned model upgrade."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.ndimage import uniform_filter
from sklearn.metrics import average_precision_score, precision_recall_curve

from wildfire_kz.data import checksum
from wildfire_kz.data.public_study import FEATURES

ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT / "runs/public_hindcast"
RUN = ROOT / "runs/model_upgrade_v4"
FIRE_WINDOWS = [(7, 3), (7, 11), (30, 3), (30, 11), (90, 11), (365, 11)]
STATIC = ["x_km", "y_km", "day_sin", "day_cos", "vpd_kpa", "temperature_range"]
HISTORY = [f"past_fire_{days}d_{size*5}km" for days, size in FIRE_WINDOWS]
ALL_FEATURES = FEATURES + STATIC + HISTORY
PRECISION_FLOOR = 0.10


def verify_release(path: Path) -> dict:
    if not path.is_file():
        raise PermissionError("Final years require the new frozen model release")
    record = json.loads(path.read_text())
    if record.get("selection_max_year") != 2022 or not record.get("frozen_utc"):
        raise PermissionError("A pre-2023-only frozen model is required")
    for name, digest in record["artifacts"].items():
        if checksum(path.parent / name) != digest:
            raise PermissionError(f"Frozen upgrade changed: {name}")
    if checksum(Path(__file__)) != record["feature_code_sha256"]:
        raise PermissionError("Frozen feature code changed")
    return record


def load_history(end_year: int, release: Path | None = None) -> pd.DataFrame:
    if end_year >= 2023:
        if release is None:
            raise PermissionError("Final history inputs are sealed until new model freeze")
        verify_release(release)
    proof = json.loads((OLD / f"outcomes/events_through_{2024 if end_year>=2023 else 2022}.sha256.json").read_text())
    frames = []
    for year in range(2014, end_year+1):
        path = ROOT / f"data/real/normalized/detections_{year}.parquet"
        if checksum(path) != proof["source_hashes"][str(year)]:
            raise ValueError(f"Detection source changed: {year}")
        f = pd.read_parquet(path, columns=["cell_id", "timestamp"])
        frames.append(f.assign(day=f.timestamp.dt.floor("D"))[["cell_id", "day"]].drop_duplicates())
    return pd.concat(frames, ignore_index=True).drop_duplicates()


class FireHistory:
    """Streaming active-cell-day counts; windows end at target day minus lag_days.

    Neighbourhoods are square 15/55 km windows on the equal-area 5 km grid.
    The refined run uses two days; seven-day candidates are retained separately.
    Only raw detections are used, never future-connected event IDs or labels.
    """

    def __init__(self, detections: pd.DataFrame, lag_days: int=2):
        self.lag_days=lag_days
        grid = pd.read_parquet(ROOT / "data/real/normalized/grid_5km.parquet", columns=["cell_id"])
        parts = grid.cell_id.str.split("_", expand=True)
        self.rmin, self.cmin = int(parts[1].astype(int).min()), int(parts[2].astype(int).min())
        self.shape = (int(parts[1].astype(int).max())-self.rmin+1,
                      int(parts[2].astype(int).max())-self.cmin+1)
        parts = detections.cell_id.str.split("_", expand=True)
        rows, cols = parts[1].astype(int).to_numpy()-self.rmin, parts[2].astype(int).to_numpy()-self.cmin
        data = detections.assign(flat=rows*self.shape[1]+cols)
        self.events = {int(d.value//86400000000000):np.unique(g.flat.to_numpy()) for d,g in data.groupby("day")}
        self.current = min(self.events)-1
        self.rolling = {n:np.zeros(self.shape, dtype="float32") for n in [7,30,90,365]}

    def get(self, day: pd.Timestamp, cell_ids: pd.Series) -> dict[str,np.ndarray]:
        cutoff = int(day.value//86400000000000)-self.lag_days
        if cutoff < self.current:
            raise ValueError("Fire history must be queried in chronological order")
        while self.current < cutoff:
            self.current += 1
            added = self.events.get(self.current, [])
            for n, image in self.rolling.items():
                image.flat[added] += 1
                image.flat[self.events.get(self.current-n, [])] -= 1
        parts = cell_ids.str.split("_",expand=True)
        rows,cols = parts[1].astype(int).to_numpy()-self.rmin,parts[2].astype(int).to_numpy()-self.cmin
        result = {}
        for n,size in FIRE_WINDOWS:
            summed = np.rint(uniform_filter(self.rolling[n],size=size,mode="constant")*(size*size))
            result[f"past_fire_{n}d_{size*5}km"] = np.log1p(np.maximum(0,summed[rows,cols])).astype("float32")
        return result


def augment(frame: pd.DataFrame, history: FireHistory, release: Path | None = None) -> pd.DataFrame:
    if frame.day.dt.year.max() >= 2023:
        if release is None:
            raise PermissionError("Final feature construction requires new model freeze")
        verify_release(release)
    f = frame.copy()
    f["x_km"],f["y_km"] = (f.x/1000).astype("float32"),(f.y_coord/1000).astype("float32")
    angle = 2*np.pi*(f.day.dt.dayofyear-1)/365.25
    f["day_sin"],f["day_cos"] = np.sin(angle).astype("float32"),np.cos(angle).astype("float32")
    f["vpd_kpa"] = (.6108*np.exp(17.27*f.tmax/(f.tmax+237.3))*(1-f.rh/100)).astype("float32")
    f["temperature_range"] = (f.tmax-f.tmin).astype("float32")
    for name in HISTORY:
        f[name] = np.float32(0)
    for day, indices in f.groupby("day",sort=True).groups.items():
        for name,values in history.get(day,f.loc[indices,"cell_id"]).items():
            f.loc[indices,name] = values
    return f


def operating_point(y: np.ndarray, p: np.ndarray, w: np.ndarray, floor: float=PRECISION_FLOOR) -> dict:
    precision,recall,t = precision_recall_curve(y,p,sample_weight=w)
    eligible = np.flatnonzero(precision[:-1]>=floor)
    if not len(eligible):
        return {"threshold":1.0,"precision":0.,"recall":0.,"f1":0.,"average_precision":float(average_precision_score(y,p,sample_weight=w))}
    best = eligible[recall[eligible]==recall[eligible].max()]
    index = best[np.argmax(t[best])]
    pp,rr = float(precision[index]),float(recall[index])
    return {"threshold":float(t[index]),"precision":pp,"recall":rr,"f1":2*pp*rr/(pp+rr),
            "average_precision":float(average_precision_score(y,p,sample_weight=w))}


def published_probability(p: np.ndarray) -> np.ndarray:
    """Declare float16 transport before evaluation; metrics use exactly these values."""
    return np.asarray(p,dtype="float16").astype("float32")


@dataclass
class ModelBlend:
    """A new score model; the mixture weight is selected only on 2021."""
    components: list[tuple[Any,float]]

    def predict_proba(self,frame: pd.DataFrame) -> np.ndarray:
        p=sum(weight*model.predict(frame) for model,weight in self.components)
        return np.column_stack([1-p,p])
