"""Deterministic artificial fixtures; never substitutes for missing observations."""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import yaml
from scipy.special import expit
from shapely import union_all
from shapely.geometry import box

from wildfire_kz.config import Config
from wildfire_kz.data import checksum
from wildfire_kz.grid import build_grid


def generate(destination: Path, config_path: Path, seed: int = 42) -> None:
    """Generate ten years on twenty artificial cells in five separated test patches."""
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    crs = Config().grid.crs
    boundary = gpd.GeoDataFrame(
        {"name": ["SYNTHETIC - not Kazakhstan"]},
        geometry=[union_all([box(300000 * i, 0, 300000 * i + 10000, 10000) for i in range(5)])],
        crs=crs,
    )
    boundary.to_parquet(destination / "boundary.parquet")
    grid = build_grid(boundary, crs, 5000)
    days = pd.date_range("2014-01-01", "2024-12-31", tz="UTC")
    weather, vegetation, covers, statics, humans, detections = [], [], [], [], [], []
    for index, cell in grid.iterrows():
        seasonal = np.sin(2 * np.pi * (days.dayofyear.to_numpy() - 100) / 365.25)
        temperature = 5 + 20 * seasonal + rng.normal(0, 4, len(days))
        rain = rng.gamma(0.5, 2, len(days)) * (rng.random(len(days)) < 0.35)
        moisture = np.clip(0.3 - 0.12 * seasonal + rng.normal(0, 0.03, len(days)), 0.03, 0.6)
        wind = rng.uniform(0, 12, len(days))
        weather.append(
            pd.DataFrame(
                {
                    "cell_id": cell.cell_id,
                    "day": days,
                    "available_at": days + pd.Timedelta(days=2),
                    "tmax": temperature + 6,
                    "tmin": temperature - 6,
                    "rh": np.clip(60 - 20 * seasonal + rng.normal(0, 8, len(days)), 1, 100),
                    "wind": wind,
                    "precip": rain,
                    "soil_moisture": moisture,
                    "year": days.year,
                }
            )
        )
        starts = pd.date_range("2014-01-01", "2024-12-31", freq="16D", tz="UTC")
        greenness = 0.4 + 0.25 * np.sin(2 * np.pi * (starts.dayofyear.to_numpy() - 80) / 365.25)
        vegetation.append(
            pd.DataFrame(
                {
                    "cell_id": cell.cell_id,
                    "interval_start": starts,
                    "interval_end": starts + pd.Timedelta(days=16),
                    "available_at": starts + pd.Timedelta(days=18),
                    "qa": np.where(rng.random(len(starts)) < 0.1, 3, 0),
                    "ndvi": greenness,
                    "evi": greenness * 0.7,
                    "year": starts.year,
                }
            )
        )
        cover = ["forest", "grassland", "shrubland", "cropland", "other"][index % 5]
        for year in range(2014, 2025):
            covers.append(
                {
                    "cell_id": cell.cell_id,
                    "map_year": year,
                    "year": year,
                    "available_at": pd.Timestamp(f"{year}-12-31", tz="UTC"),
                    **{
                        c: 0.8 if c == cover else 0.05
                        for c in ["forest", "grassland", "shrubland", "cropland", "other"]
                    },
                }
            )
            humans.append(
                {
                    "cell_id": cell.cell_id,
                    "year": year,
                    "available_at": pd.Timestamp(f"{year}-01-01", tz="UTC"),
                    "population": float(50 + index * 15),
                    "settlement_distance": float(1000 + index * 500),
                }
            )
        statics.append(
            {
                "cell_id": cell.cell_id,
                "year": 2014,
                "available_at": pd.Timestamp("2014-01-01", tz="UTC"),
                "elevation": float(200 + index * 30),
                "slope": float(index % 6),
                "aspect_sin": float(np.sin(index)),
                "aspect_cos": float(np.cos(index)),
                "nonvegetated": False,
            }
        )
        # Known artificial relationship; these are fixture labels, not scientific outcomes.
        probability = expit(
            -5.4 + 0.065 * temperature + 0.06 * wind - 2 * moisture + 0.3 * (cover == "cropland")
        )
        selected = np.flatnonzero((rng.random(len(days)) < probability) & (days.year >= 2015))
        for i in selected:
            timestamp = days[int(i)] + pd.Timedelta(hours=13)
            for lag in [0, 8]:
                detections.append(
                    {
                        "cell_id": cell.cell_id,
                        "timestamp": timestamp + pd.Timedelta(hours=lag),
                        "x": cell.x + float(rng.uniform(-200, 200)),
                        "y_coord": cell.y_coord,
                        "confidence": "n",
                        "satellite": "N",
                        "year": int(days[int(i)].year),
                    }
                )
    tables = {
        "weather": pd.concat(weather),
        "vegetation": pd.concat(vegetation),
        "landcover": pd.DataFrame(covers),
        "static": pd.DataFrame(statics),
        "human": pd.DataFrame(humans),
        "detections": pd.DataFrame(detections),
    }
    for kind, frame in tables.items():
        frame.to_parquet(destination / f"{kind}.parquet", index=False)
    sources = {}
    for kind in ["boundary", *tables]:
        path = destination / f"{kind}.parquet"
        sources[kind] = {
            "path": str(path),
            "source_id": f"SYNTHETIC/{kind}",
            "version": "fixture-v1",
            "downloaded_at": "generated locally; not downloaded",
            "sha256": checksum(path),
        }
    cfg = Config(seed=seed)
    cfg.output_dir = config_path.resolve().parent.parent / "runs" / "synthetic"
    cfg.data.synthetic = True
    cfg.data.weather_mode = "daily"
    cfg.models.trials = 1
    cfg.models.n_estimators_min = 12
    cfg.models.n_estimators_max = 16
    cfg.models.early_stopping_rounds = 5
    cfg.models.threads = 2
    cfg.evaluation.bootstrap_resamples = 20
    cfg.evaluation.shap_rows = 100
    raw = cfg.model_dump(mode="json")
    raw["data"]["sources"] = sources
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
