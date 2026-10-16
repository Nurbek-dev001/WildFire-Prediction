"""Pydantic-validated configuration schema.

Every tunable number used anywhere in the pipeline lives here (with the defaults
prescribed by the research methodology) and is loaded from YAML. Modules never
hard-code methodological parameters.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)


# --------------------------------------------------------------------------- project
class ProjectConfig(_Strict):
    name: str = "wildfire_kz"
    seed: int = 20240917
    raw_dir: Path = Path("data/raw")
    work_dir: Path = Path("data/work")
    run_label: str = "default"
    log_level: str = "INFO"


class CRSConfig(_Strict):
    """Documented equal-area projection used for every spatial operation."""

    name: str = "Kazakhstan Albers Equal-Area Conic (WGS84)"
    proj4: str = (
        "+proj=aea +lat_0=48 +lon_0=67 +lat_1=43 +lat_2=53 "
        "+x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs"
    )
    geographic: str = "EPSG:4326"


class StudyConfig(_Strict):
    start: dt.date = dt.date(2015, 1, 1)
    end: dt.date = dt.date(2024, 12, 31)
    lookback_days: int = Field(
        60,
        description="Days of input data required before `start` (antecedent windows, "
        "48 h exclusion, MODIS lag, event linking across the start date).",
    )
    timezone: Literal["UTC"] = "UTC"

    @model_validator(mode="after")
    def _check(self) -> StudyConfig:
        if self.end <= self.start:
            raise ValueError("study.end must be after study.start")
        return self

    @property
    def years(self) -> list[int]:
        return list(range(self.start.year, self.end.year + 1))


# --------------------------------------------------------------------------- grid
class GridSpec(_Strict):
    cell_size_m: float = 5000.0
    region_bbox_lonlat: tuple[float, float, float, float] | None = Field(
        None, description="Optional (minlon, minlat, maxlon, maxlat) restriction (regional runs)."
    )


class GridConfig(_Strict):
    active: Literal["primary", "sensitivity"] = "primary"
    primary: GridSpec = GridSpec(cell_size_m=5000.0)
    sensitivity: GridSpec = GridSpec(
        cell_size_m=1000.0, region_bbox_lonlat=(76.0, 49.5, 78.0, 50.5)
    )
    min_inside_fraction: float = Field(
        0.5, ge=0.0, le=1.0, description="Min. share of the cell area inside the boundary."
    )

    @property
    def active_spec(self) -> GridSpec:
        return self.primary if self.active == "primary" else self.sensitivity


# --------------------------------------------------------------------------- sources
class SourceMeta(_Strict):
    """Provenance fields recorded in the data manifest for every source."""

    source_id: str
    version: str = "unknown"
    provider: str = ""
    url: str = ""
    license_note: str = "Provider-specific terms; public access != unrestricted redistribution."
    retrieved_on: dt.date | None = None
    required: bool = True


class BoundarySource(SourceMeta):
    path: Path = Path("boundary/kazakhstan_adm0.geojson")
    border_buffer_km: float = Field(
        10.0,
        description="Detections within this buffer outside the border are kept for event "
        "linking only; positives must fall inside the grid.",
    )


class FirmsSource(SourceMeta):
    path: Path = Path("firms")
    glob: str = "*.csv"
    expected_satellite: str = "N"  # Suomi-NPP
    expected_instrument: str = "VIIRS"
    keep_confidence: list[str] = ["n", "h"]
    drop_confidence: list[str] = ["l"]
    vegetation_type_values: list[int] = Field(
        [0], description="FIRMS `type` values treated as presumed vegetation fire (if present)."
    )
    api_key_env: str = "FIRMS_MAP_KEY"
    api_product: str = "VIIRS_SNPP_SP"
    api_max_days_per_request: int = 5

    @field_validator("keep_confidence", "drop_confidence")
    @classmethod
    def _viirs_categories(cls, v: list[str]) -> list[str]:
        bad = [c for c in v if c not in {"l", "n", "h"}]
        if bad:
            raise ValueError(
                f"VIIRS confidence is categorical (l/n/h), not MODIS percentages; got {bad}"
            )
        return v


class Era5Source(SourceMeta):
    path: Path = Path("era5_land")
    glob: str = "*.nc"
    variables: dict[str, str] = {
        "t2m": "2m_temperature",
        "d2m": "2m_dewpoint_temperature",
        "u10": "10m_u_component_of_wind",
        "v10": "10m_v_component_of_wind",
        "tp": "total_precipitation",
        "swvl1": "volumetric_soil_water_layer_1",
    }
    accumulated_variables: list[str] = ["tp"]
    interpolation: Literal["linear", "nearest"] = "linear"
    cds_dataset: str = "reanalysis-era5-land"


class RasterCatalogSource(SourceMeta):
    """A directory of GeoTIFFs whose date/year is parsed from the file name."""

    path: Path
    glob: str = "*.tif"
    filename_regex: str
    working_resolution_m: float = Field(
        ...,
        description="Resolution of the equal-area working "
        "raster used during aggregation (~native).",
    )
    window_size_km: float = 200.0
    backend: Literal["local", "gee"] = "local"
    gee_collection: str | None = None


class ModisVISource(RasterCatalogSource):
    path: Path = Path("mod13a2")
    filename_regex: str = r"MOD13A2_061_(?P<year>\d{4})(?P<doy>\d{3})\.tif$"
    working_resolution_m: float = 1000.0
    gee_collection: str | None = "MODIS/061/MOD13A2"
    ndvi_band: int = 1
    evi_band: int = 2
    qa_band: int = 3
    scale_factor: float = 0.0001
    fill_value: int = -3000
    valid_qa_values: list[int] = Field([0, 1], description="SummaryQA: 0 good, 1 marginal")
    composite_length_days: int = 16
    publication_lag_days: int = Field(
        10, description="Conservative lag after the composite interval ends before use."
    )
    max_gap_fill_days: int = 32


class LandCoverSource(RasterCatalogSource):
    path: Path = Path("mcd12q1")
    filename_regex: str = r"MCD12Q1_061_(?P<year>\d{4})\.tif$"
    working_resolution_m: float = 500.0
    gee_collection: str | None = "MODIS/061/MCD12Q1"
    year_offset: int = Field(-1, description="Use the map of (target year + offset).")
    classes: dict[str, list[int]] = {
        "forest": [1, 2, 3, 4, 5],
        "shrubland": [6, 7],
        "grassland": [8, 9, 10],
        "cropland": [12, 14],
        "other": [0, 11, 13, 15, 16, 17, 255],
    }
    non_vegetated_classes: list[int] = [13, 15, 16, 17]


class TerrainSource(RasterCatalogSource):
    path: Path = Path("srtm")
    filename_regex: str = r".*\.tif$"
    working_resolution_m: float = 90.0
    window_size_km: float = 100.0
    gee_collection: str | None = "USGS/SRTMGL1_003"
    reference_date: dt.date = dt.date(2000, 2, 22)
    nodata: float = -32768.0
    flat_slope_threshold_deg: float = Field(
        0.5, description="Pixels flatter than this have undefined aspect (excluded from aspect)."
    )


class WorldPopSource(RasterCatalogSource):
    path: Path = Path("worldpop")
    filename_regex: str = r"kaz_ppp_(?P<year>\d{4})\.tif$"
    working_resolution_m: float = 100.0
    product: Literal["ppp_counts", "density"] = "ppp_counts"
    year_offset: int = -1


class VectorSnapshot(_Strict):
    snapshot_date: dt.date
    path: Path


class VectorSource(SourceMeta):
    snapshots: list[VectorSnapshot] = []


class SourcesConfig(_Strict):
    boundary: BoundarySource = BoundarySource(source_id="geoBoundaries-KAZ-ADM0")
    regions: VectorSource | None = None
    firms: FirmsSource = FirmsSource(source_id="FIRMS-VIIRS_SNPP_SP")
    era5_land: Era5Source = Era5Source(source_id="C3S-ERA5-Land-hourly")
    mod13a2: ModisVISource = ModisVISource(source_id="MOD13A2.061")
    mcd12q1: LandCoverSource = LandCoverSource(source_id="MCD12Q1.061")
    srtm: TerrainSource = TerrainSource(source_id="SRTMGL1.003")
    worldpop: WorldPopSource = WorldPopSource(source_id="WorldPop-ppp-unconstrained")
    settlements: VectorSource = VectorSource(source_id="settlements", required=False)
    roads: VectorSource = VectorSource(source_id="OSM-historical-roads", required=False)
    burned_area: VectorSource | None = None


# --------------------------------------------------------------------------- events
class IndustrialMaskConfig(_Strict):
    screening_resolution_m: float = 1000.0
    min_detection_days: int = 20
    min_years: int = 3
    min_non_vegetated_fraction: float = 0.5
    use_static_type_flag: bool = True  # FIRMS type==2 "other static land source"


class EventSensitivityConfig(_Strict):
    run: bool = True
    spatial_km: list[float] = [1.0, 2.0, 3.0, 4.0, 5.0]
    temporal_h: list[float] = [24.0, 48.0, 72.0]


class EventsConfig(_Strict):
    dedupe_decimals: int = Field(4, description="Coordinate rounding for exact-duplicate removal.")
    spatial_link_km: float = 2.0
    temporal_link_h: float = 48.0
    linking_window_days: int = 30
    sensitivity: EventSensitivityConfig = EventSensitivityConfig()
    industrial_mask: IndustrialMaskConfig = IndustrialMaskConfig()
    tie_break: list[str] = ["acq_datetime", "confidence_rank", "-frp", "cell_id"]


class RiskSetConfig(_Strict):
    exclusion_hours: float = 48.0


# --------------------------------------------------------------------------- sampling
class SamplingConfig(_Strict):
    negatives_per_positive: float = 10.0
    min_negatives_per_stratum: int = 50
    strata: list[Literal["year", "month", "lc_group"]] = ["year", "month", "lc_group"]
    eval_negative_fraction: float = Field(
        1.0,
        gt=0.0,
        le=1.0,
        description="1.0 = complete (unbalanced) evaluation risk set; <1 = stratified "
        "probability sample with inverse-inclusion weights.",
    )
    training_weighting: Literal["inverse_inclusion", "class_weight"] = "inverse_inclusion"


# --------------------------------------------------------------------------- features
class WeatherFeatureConfig(_Strict):
    antecedent_windows_days: list[int] = [7, 14]
    rain_day_threshold_mm: float = 1.0
    include_fire_weather_index: bool = False


class HumanFeatureConfig(_Strict):
    use_roads: bool = True
    use_settlements: bool = True
    use_population: bool = True
    allow_nonhistorical_roads_in_sensitivity: bool = False


class FireHistoryConfig(_Strict):
    enabled: bool = False
    window_days: int = 365


class FeatureGroupsConfig(_Strict):
    """Named groups used for ablations and grouped SHAP analysis."""

    ablation_groups: dict[str, list[str]] = {
        "anthropogenic": ["@anthropogenic"],
        "lagged_weather": ["@weather_antecedent"],
        "vegetation": ["@vegetation"],
    }
    correlated_groups: dict[str, list[str]] = {
        "temperature": [
            "t2m_max_c",
            "t2m_min_c",
            "t2m_mean_c",
            "d2m_mean_c",
            "t2m_max_mean_7d_c",
            "t2m_max_mean_14d_c",
        ],
        "moisture": [
            "rh_mean_pct",
            "rh_min_pct",
            "precip_mm",
            "swvl1",
            "precip_sum_7d_mm",
            "precip_sum_14d_mm",
            "rh_mean_7d_pct",
            "rh_mean_14d_pct",
            "dry_days_14d",
        ],
        "wind": ["wind_mean_ms", "wind_max_ms"],
        "vegetation_index": ["ndvi", "evi", "ndvi_delta", "veg_age_days"],
        "land_cover": [
            "lc_frac_forest",
            "lc_frac_shrubland",
            "lc_frac_grassland",
            "lc_frac_cropland",
            "lc_frac_other",
        ],
        "terrain": ["elevation_m", "slope_deg", "aspect_sin", "aspect_cos"],
        "human": ["pop_density", "dist_settlement_km", "dist_road_km"],
    }
    correlation_threshold: float = 0.8
    weather_only_groups: list[str] = ["weather_prior_day", "weather_antecedent"]


class FeaturesConfig(_Strict):
    weather: WeatherFeatureConfig = WeatherFeatureConfig()
    human: HumanFeatureConfig = HumanFeatureConfig()
    fire_history: FireHistoryConfig = FireHistoryConfig()
    groups: FeatureGroupsConfig = FeatureGroupsConfig()
    include_calendar: bool = True
    float_dtype: Literal["float32", "float64"] = "float32"


# --------------------------------------------------------------------------- splits
class RollingFold(_Strict):
    train_years: list[int]
    val_year: int


class SpatialCVConfig(_Strict):
    n_folds: int = 5
    block_size_km: float = 100.0
    sensitivity_block_sizes_km: list[float] = [50.0, 150.0]
    buffer_km: float = 25.0
    inner_validation: Literal["last_dev_year"] = "last_dev_year"


class SplitsConfig(_Strict):
    development_years: list[int] = [2015, 2016, 2017, 2018, 2019, 2020, 2021]
    rolling_origin: list[RollingFold] = [
        RollingFold(train_years=[2015, 2016, 2017, 2018], val_year=2019),
        RollingFold(train_years=[2015, 2016, 2017, 2018, 2019], val_year=2020),
        RollingFold(train_years=[2015, 2016, 2017, 2018, 2019, 2020], val_year=2021),
    ]
    calibration_years: list[int] = [2022]
    test_years: list[int] = [2023, 2024]
    spatial_cv: SpatialCVConfig = SpatialCVConfig()

    @model_validator(mode="after")
    def _disjoint(self) -> SplitsConfig:
        dev, cal, test = (
            set(self.development_years),
            set(self.calibration_years),
            set(self.test_years),
        )
        if dev & cal or dev & test or cal & test:
            raise ValueError("development, calibration and test years must be disjoint")
        if min(test) <= max(cal) or min(cal) <= max(dev):
            raise ValueError("splits must be chronological: dev < calibration < test")
        for fold in self.rolling_origin:
            if not set(fold.train_years) <= dev or fold.val_year not in dev:
                raise ValueError("rolling-origin folds must lie inside development years")
            if max(fold.train_years) >= fold.val_year:
                raise ValueError("rolling-origin validation year must follow training years")
        return self


# --------------------------------------------------------------------------- models
class IntRange(_Strict):
    low: int
    high: int
    log: bool = False


class FloatRange(_Strict):
    low: float
    high: float
    log: bool = False


class LogisticSpace(_Strict):
    C: FloatRange = FloatRange(low=1e-4, high=1e2, log=True)


class RandomForestSpace(_Strict):
    max_depth: IntRange = IntRange(low=3, high=20)
    min_samples_leaf: IntRange = IntRange(low=1, high=200, log=True)
    max_features: FloatRange = FloatRange(low=0.2, high=1.0)
    n_estimators: IntRange = IntRange(low=100, high=600)


class XGBoostSpace(_Strict):
    max_depth: IntRange = IntRange(low=2, high=10)
    min_child_weight: FloatRange = FloatRange(low=1e-2, high=1e2, log=True)
    learning_rate: FloatRange = FloatRange(low=1e-3, high=0.3, log=True)
    reg_lambda: FloatRange = FloatRange(low=1e-3, high=1e2, log=True)
    reg_alpha: FloatRange = FloatRange(low=1e-4, high=1e1, log=True)
    subsample: FloatRange = FloatRange(low=0.5, high=1.0)
    colsample_bytree: FloatRange = FloatRange(low=0.5, high=1.0)
    n_estimators: IntRange = IntRange(low=100, high=2000)


class CatBoostSpace(_Strict):
    depth: IntRange = IntRange(low=3, high=10)
    min_data_in_leaf: IntRange = IntRange(low=1, high=200, log=True)
    learning_rate: FloatRange = FloatRange(low=1e-3, high=0.3, log=True)
    l2_leaf_reg: FloatRange = FloatRange(low=1e-2, high=1e2, log=True)
    iterations: IntRange = IntRange(low=100, high=2000)


class SearchSpaces(_Strict):
    logistic: LogisticSpace = LogisticSpace()
    random_forest: RandomForestSpace = RandomForestSpace()
    xgboost: XGBoostSpace = XGBoostSpace()
    catboost: CatBoostSpace = CatBoostSpace()


ModelName = Literal["logistic", "random_forest", "xgboost", "catboost"]
BaselineName = Literal["seasonal_landcover", "weather_logistic"]


class ModelsConfig(_Strict):
    classifiers: list[ModelName] = ["logistic", "random_forest", "xgboost", "catboost"]
    baselines: list[BaselineName] = ["seasonal_landcover", "weather_logistic"]
    n_trials_ensemble: int = 50
    n_trials_logistic: int = 20
    n_trials_spatial_cv: int = 50
    early_stopping_rounds: int = 50
    objective: Literal["weighted_average_precision"] = "weighted_average_precision"
    logistic_max_iter: int = 2000
    seasonal_smoothing_alpha: float = Field(
        50.0,
        description="Pseudo-count (weighted cell-days) shrinking each LC x month rate "
        "toward the overall training rate.",
    )
    feature_screening_max_missing: float = Field(
        0.99,
        description="Drop features whose missing share in the TRAINING partition exceeds this.",
    )
    n_jobs: int = -1
    search_spaces: SearchSpaces = SearchSpaces()
    run_spatial_cv: bool = True
    run_class_weight_sensitivity: bool = True


# --------------------------------------------------------------------------- calibration
class CalibrationConfig(_Strict):
    method: Literal["sigmoid"] = "sigmoid"
    threshold_metric: Literal["weighted_f1"] = "weighted_f1"
    score_clip: float = 1e-6


class AblationConfig(_Strict):
    models: list[ModelName] = ["logistic", "random_forest", "xgboost", "catboost"]
    retune: bool = False
    include_correlated_groups: bool = True


# --------------------------------------------------------------------------- evaluation
class BootstrapConfig(_Strict):
    n_resamples: int = 1000
    spatial_block_km: float = 100.0
    temporal_block_days: int = 7
    ci_level: float = 0.95


class EvaluationConfig(_Strict):
    reliability_bins: int = 10
    capture_fractions: list[float] = [0.05, 0.10, 0.20]
    capture_modes: list[Literal["pooled", "daily"]] = ["pooled", "daily"]
    bootstrap: BootstrapConfig = BootstrapConfig()
    strata: list[str] = ["year", "month", "region", "lc_group"]
    min_positives_for_stratum: int = 5
    wilson_z: float = 1.96


class ExplainConfig(_Strict):
    partitions: list[Literal["calibration", "test"]] = ["calibration", "test"]
    max_rows: int = 20000
    n_dependence_plots: int = 8
    n_local_examples: int = 5


class MappingConfig(_Strict):
    years: list[int] = [2022, 2023, 2024]
    max_days: int | None = Field(None, description="Limit number of exported days (None=all).")
    class_quantiles: list[float] = [0.50, 0.80, 0.95, 0.99]
    class_labels: list[str] = ["very low", "low", "moderate", "high", "very high"]
    nodata: float = -9999.0
    class_nodata: int = 255

    @model_validator(mode="after")
    def _labels(self) -> MappingConfig:
        if len(self.class_labels) != len(self.class_quantiles) + 1:
            raise ValueError("class_labels must have len(class_quantiles)+1 entries")
        return self


# --------------------------------------------------------------------------- synthetic
class SyntheticConfig(_Strict):
    bbox_lonlat: tuple[float, float, float, float] = (70.0, 48.0, 76.5, 50.8)
    era5_resolution_deg: float = 0.5
    modis_resolution_deg: float = 0.02
    landcover_resolution_deg: float = 0.01
    dem_tiles: tuple[int, int] = (2, 2)
    worldpop_resolution_deg: float = 0.02
    n_settlements: int = 40
    base_ignition_logit: float = -9.0
    n_industrial_sites: int = 3
    low_confidence_share: float = 0.15
    duplicate_share: float = 0.02


# --------------------------------------------------------------------------- root
class Config(_Strict):
    project: ProjectConfig = ProjectConfig()
    crs: CRSConfig = CRSConfig()
    study: StudyConfig = StudyConfig()
    grid: GridConfig = GridConfig()
    sources: SourcesConfig = SourcesConfig()
    events: EventsConfig = EventsConfig()
    risk_set: RiskSetConfig = RiskSetConfig()
    sampling: SamplingConfig = SamplingConfig()
    features: FeaturesConfig = FeaturesConfig()
    splits: SplitsConfig = SplitsConfig()
    models: ModelsConfig = ModelsConfig()
    calibration: CalibrationConfig = CalibrationConfig()
    ablation: AblationConfig = AblationConfig()
    evaluation: EvaluationConfig = EvaluationConfig()
    explain: ExplainConfig = ExplainConfig()
    mapping: MappingConfig = MappingConfig()
    synthetic: SyntheticConfig = SyntheticConfig()

    @model_validator(mode="after")
    def _years_within_study(self) -> Config:
        years = set(self.study.years)
        s = self.splits
        needed = set(s.development_years) | set(s.calibration_years) | set(s.test_years)
        if not needed <= years:
            raise ValueError(f"split years {sorted(needed - years)} outside study period")
        for y in self.mapping.years:
            if y in s.development_years:
                continue
            if y not in years:
                raise ValueError(f"mapping year {y} outside study period")
        return self

    @property
    def run_dir(self) -> Path:
        return self.project.work_dir / self.project.run_label

    def raw(self, rel: Path) -> Path:
        """Resolve a source path relative to ``project.raw_dir``."""
        return rel if rel.is_absolute() else self.project.raw_dir / rel
