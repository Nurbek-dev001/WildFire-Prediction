"""Command-line interface: one sub-command per pipeline stage (``wildfire-kz --help``)."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Annotated

import typer

from wildfire_kz.config.loader import load_config
from wildfire_kz.config.schema import Config

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Explainable multisource next-day wildfire occurrence-hazard pipeline.",
)
download_app = typer.Typer(help="Optional real-data downloads (network + credentials).")
app.add_typer(download_app, name="download")

ConfigOpt = Annotated[list[Path], typer.Option("--config", "-c", help="YAML config file(s).")]
SetOpt = Annotated[
    list[str] | None, typer.Option("--set", "-s", help="Override, e.g. events.spatial_link_km=3")
]
ForceOpt = Annotated[bool, typer.Option("--force", "-f", help="Re-run even if cached.")]

DEFAULT_CONFIG = [Path("configs/default.yaml")]


def _cfg(config: list[Path] | None, overrides: list[str] | None) -> Config:
    return load_config(config or DEFAULT_CONFIG, overrides)


def _stage(name: str):  # type: ignore[no-untyped-def]
    def command(
        config: ConfigOpt = DEFAULT_CONFIG, set_: SetOpt = None, force: ForceOpt = False
    ) -> None:
        from wildfire_kz.cli.pipeline import run_stage

        summary = run_stage(name, _cfg(config, set_), force=force)
        typer.echo(f"[{name}] " + ("cached (up to date)" if summary is None else "done"))

    command.__name__ = name.replace("-", "_")
    command.__doc__ = f"Run the '{name}' stage."
    return command


for _name, _help in [
    ("ingest", "Register raw data and write the checksummed data manifest."),
    ("grid", "Build the equal-area analysis grid with stable cell ids."),
    ("events", "QC VIIRS detections, screen industrial hotspots, link events, label positives."),
    ("risk_set", "Build the eligible new-event risk set (48 h past-only exclusion)."),
    ("sampling", "Stratified negative sampling with inverse-inclusion weights."),
    ("features", "Build as-of feature tables and run the automated leakage check."),
    ("splits", "Rolling-origin temporal splits and spatial-block CV folds."),
    ("train", "Tune (Optuna) and train classifiers and baselines."),
    ("calibrate", "Platt calibration, threshold and map classes on the calibration year."),
    ("ablate", "Grouped feature ablations."),
    ("evaluate", "Final evaluation on the untouched test years."),
    ("explain", "TreeSHAP explanations (predictive associations, not causal)."),
    ("map", "Export daily calibrated probability GeoTIFFs."),
    ("report", "Generate tables, figures and the reproducibility record."),
]:
    app.command(name=_name.replace("_", "-"), help=_help)(_stage(_name))


@app.command("run")
def run_pipeline(
    config: ConfigOpt = DEFAULT_CONFIG,
    set_: SetOpt = None,
    until: Annotated[str | None, typer.Option(help="Stop after this stage.")] = None,
    force: ForceOpt = False,
) -> None:
    """Run all stages in order (cached stages are skipped)."""
    from wildfire_kz.cli.pipeline import run_all

    run_all(_cfg(config, set_), until=until, force=force)


@app.command("synth")
def synth(config: ConfigOpt = DEFAULT_CONFIG, set_: SetOpt = None) -> None:
    """Generate the offline SYNTHETIC dataset at project.raw_dir (never real data)."""
    from wildfire_kz.data.synthetic import generate_synthetic
    from wildfire_kz.utils.runtime import setup_logging

    cfg = _cfg(config, set_)
    setup_logging(cfg.project.log_level)
    path = generate_synthetic(cfg)
    typer.echo(f"SYNTHETIC data written to {path}")


@app.command("event-sensitivity")
def event_sensitivity(config: ConfigOpt = DEFAULT_CONFIG, set_: SetOpt = None) -> None:
    """Event counts for 1–5 km x 24–72 h linkage settings (requires the events stage)."""
    from wildfire_kz.events.build import run_event_sensitivity
    from wildfire_kz.paths import RunPaths

    cfg = _cfg(config, set_)
    p = RunPaths.from_config(cfg)
    table = run_event_sensitivity(cfg, p.stage("events"), p.grid_file, p.grid_meta)
    typer.echo(table.to_string(index=False))


@download_app.command("firms")
def dl_firms(
    start: str,
    end: str,
    config: ConfigOpt = DEFAULT_CONFIG,
    bbox: Annotated[str, typer.Option(help="minlon,minlat,maxlon,maxlat")] = "46.4,40.5,87.4,55.5",
) -> None:
    """Download FIRMS VIIRS_SNPP_SP detections (needs FIRMS_MAP_KEY)."""
    from wildfire_kz.data.download import download_firms

    b = tuple(float(v) for v in bbox.split(","))
    files = download_firms(
        _cfg(config, None),
        b,  # type: ignore[arg-type]
        dt.date.fromisoformat(start),
        dt.date.fromisoformat(end),
    )
    typer.echo(f"{len(files)} files written")


@download_app.command("era5")
def dl_era5(
    year: int,
    month: int,
    config: ConfigOpt = DEFAULT_CONFIG,
    bbox: Annotated[str, typer.Option(help="minlon,minlat,maxlon,maxlat")] = "46.4,40.5,87.4,55.5",
) -> None:
    """Download one month of hourly ERA5-Land (needs cdsapi + ~/.cdsapirc)."""
    from wildfire_kz.data.download import download_era5_land

    b = tuple(float(v) for v in bbox.split(","))
    path = download_era5_land(_cfg(config, None), b, year, month)  # type: ignore[arg-type]
    typer.echo(str(path))


if __name__ == "__main__":  # pragma: no cover
    app()
