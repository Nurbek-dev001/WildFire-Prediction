"""One command per stage; optional data generation/download are separate operations."""

from pathlib import Path
from typing import Annotated
from urllib.request import urlopen

import typer

from wildfire_kz.config import load_config
from wildfire_kz.data import checksum
from wildfire_kz.data.synthetic import generate
from wildfire_kz.pipeline import STAGES, PipelineRunner

app = typer.Typer(
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,
    help="Kazakhstan | auditable next-day fire occurrence hazard",
)
ConfigOption = Annotated[Path, typer.Option("--config", "-c", exists=True, dir_okay=False)]


def _register(stage: str) -> None:
    def command(config: ConfigOption = Path("configs/primary.yaml"), force: bool = False) -> None:
        """Execute the stage with validated YAML and verified content caching."""
        result = PipelineRunner(load_config(config)).run(stage, force=force)
        typer.echo(f"{stage}: complete | seed={result['seed']} | {result['seconds']:.2f}s")

    command.__name__ = stage
    app.command(name=stage.replace("_", "-"))(command)


for _stage in STAGES:
    _register(_stage)


@app.command("run-all")
def run_all(config: ConfigOption = Path("configs/primary.yaml")) -> None:
    """Run all stages, including release of the final test holdout."""
    PipelineRunner(load_config(config)).run_all()


@app.command()
def synthetic(
    destination: Path = Path("data/synthetic"),
    config: Path = Path("configs/synthetic.yaml"),
    seed: int = 42,
) -> None:
    """Create explicit artificial data and a reduced-compute demonstration config."""
    generate(destination, config, seed)
    typer.echo(f"SYNTHETIC fixture ready: {config}")


@app.command()
def download(url: str, destination: Path, sha256: str) -> None:
    """Download one explicitly requested HTTPS asset and verify a supplied checksum."""
    if not url.startswith("https://"):
        raise typer.BadParameter("An HTTPS source URL is required")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".download")
    try:
        with urlopen(url, timeout=60) as source, temporary.open("wb") as output:
            while chunk := source.read(1024 * 1024):
                output.write(chunk)
        if checksum(temporary) != sha256:
            raise ValueError("Download checksum mismatch; source not registered")
        temporary.replace(destination)
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        raise typer.BadParameter(f"Source unavailable or invalid: {exc}") from exc


if __name__ == "__main__":
    app()
