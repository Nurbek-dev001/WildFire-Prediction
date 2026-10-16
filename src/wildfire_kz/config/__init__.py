"""Validated experiment configuration; all paths resolve relative to the YAML file."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Source(StrictModel):
    path: Path
    source_id: str
    version: str
    downloaded_at: str
    sha256: str | None = None
    url: str | None = None


class DataConfig(StrictModel):
    synthetic: bool = False
    sources: dict[str, Source] = Field(default_factory=dict)
    weather_mode: Literal["daily", "era5_land_cumulative", "hourly_increment"] = (
        "era5_land_cumulative"
    )
    historical_roads: bool = False
    publication_lag_days: int = Field(default=2, ge=0)
    vegetation_fill_days: int = Field(default=32, ge=0)
    weather_lag_days: int = Field(default=1, ge=0)
    chunk_rows: int = Field(default=200_000, gt=0)
    cell_chunk_size: int = Field(default=256, gt=0)
    maximum_evaluation_rows: int = Field(default=2_000_000, gt=0)


class GridConfig(StrictModel):
    crs: str = "+proj=laea +lat_0=48 +lon_0=67 +datum=WGS84 +units=m +no_defs"
    resolution_m: int = Field(default=5000, gt=0)
    regional_resolution_m: int = 1000


class EventConfig(StrictModel):
    radius_m: float = Field(default=2000, gt=0)
    window_hours: float = Field(default=48, gt=0)
    exclusion_hours: float = Field(default=48, gt=0)
    sensitivity_radius_m: list[int] = [1000, 2000, 3000, 4000, 5000]
    sensitivity_hours: list[int] = [24, 48, 72]
    hotspot_min_days: int = Field(default=30, gt=0)


class SamplingConfig(StrictModel):
    mode: Literal["probability", "class_weight"] = "probability"
    negative_ratio: float = Field(default=10, gt=0)
    minimum_negatives: int = Field(default=20, ge=1)


class SplitConfig(StrictModel):
    start_year: int = 2015
    development_end: int = 2021
    validation_years: list[int] = [2019, 2020, 2021]
    calibration_year: int = 2022
    test_years: list[int] = [2023, 2024]
    spatial_folds: int = Field(default=5, ge=2)
    block_m: int = Field(default=100000, gt=0)
    buffer_m: int = Field(default=25000, ge=25000)
    sensitivity_block_m: list[int] = [50000, 150000]


class ModelConfig(StrictModel):
    names: list[str] = ["logistic", "random_forest", "xgboost", "catboost"]
    trials: int = Field(default=50, gt=0)
    n_estimators_min: int = Field(default=100, ge=2)
    n_estimators_max: int = Field(default=600, ge=2)
    early_stopping_rounds: int = Field(default=30, ge=1)
    threads: int = Field(default=4, ge=1)
    seasonal_smoothing: float = Field(default=20, gt=0)


class EvaluationConfig(StrictModel):
    bootstrap_resamples: int = Field(default=1000, ge=1)
    bootstrap_block_days: int = Field(default=30, ge=1)
    confidence_level: float = Field(default=0.95, gt=0, lt=1)
    reliability_bins: int = Field(default=10, ge=2)
    top_fractions: list[float] = [0.05, 0.10, 0.20]
    map_quantiles: list[float] = [0.50, 0.80, 0.95]
    shap_rows: int = Field(default=500, gt=0)


class Config(StrictModel):
    seed: int = 42
    output_dir: Path = Path("../runs/primary")
    data: DataConfig = DataConfig()
    grid: GridConfig = GridConfig()
    events: EventConfig = EventConfig()
    sampling: SamplingConfig = SamplingConfig()
    splits: SplitConfig = SplitConfig()
    models: ModelConfig = ModelConfig()
    evaluation: EvaluationConfig = EvaluationConfig()

    @model_validator(mode="after")
    def validate_design(self) -> "Config":
        s = self.splits
        if not (s.development_end < s.calibration_year < min(s.test_years)):
            raise ValueError("Development, calibration and test years must be disjoint and ordered")
        if any(y <= s.start_year or y > s.development_end for y in s.validation_years):
            raise ValueError("Rolling validation must remain within development")
        if self.models.n_estimators_min > self.models.n_estimators_max:
            raise ValueError("Invalid tree count interval")
        if not set(self.models.names) <= {"logistic", "random_forest", "xgboost", "catboost"}:
            raise ValueError("Unknown model")
        if not all(
            0 < x < 1 for x in self.evaluation.map_quantiles + self.evaluation.top_fractions
        ):
            raise ValueError("Fractions must lie strictly between zero and one")
        return self


def load_config(path: Path) -> Config:
    """Load YAML and normalize paths without reading any source data."""
    cfg = Config.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    cfg.output_dir = (path.resolve().parent / cfg.output_dir).resolve()
    for source in cfg.data.sources.values():
        source.path = (path.resolve().parent / source.path).resolve()
    return cfg
