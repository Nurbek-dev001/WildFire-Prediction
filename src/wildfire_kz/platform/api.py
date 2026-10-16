"""FastAPI application: hazard maps, per-cell drill-down, production model card, evaluation.

Run with ``wildfire-kz serve -c <config>``. The API only reads pipeline artifacts, except
``POST /api/forecast`` which runs the production model for a new target day.
"""

from __future__ import annotations

import datetime as dt
from functools import cached_property
from pathlib import Path
from typing import Any

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from wildfire_kz import __version__
from wildfire_kz.config.schema import Config
from wildfire_kz.forecast.engine import DISCLAIMER, ForecastEngine, run_forecast
from wildfire_kz.platform.data import DayRecord, RunArtifacts, clean, overlay_png
from wildfire_kz.splits.guard import TestSetAccessError

STATIC = Path(__file__).parent / "static"


class PlatformState:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.art = RunArtifacts(cfg)

    @cached_property
    def engine(self) -> ForecastEngine:
        return ForecastEngine(self.cfg, self.art.paths)

    def day(self, date: str) -> DayRecord:
        rec = self.art.days().get(date)
        if rec is None:
            raise HTTPException(404, f"no map or forecast for {date}")
        return rec


def create_app(cfg: Config) -> FastAPI:
    state = PlatformState(cfg)
    app = FastAPI(title=cfg.platform.title, version=__version__, description=DISCLAIMER)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__, **state.art.status()}

    @app.get("/api/config")
    def config() -> dict[str, Any]:
        return {
            "title": cfg.platform.title,
            "disclaimer": DISCLAIMER,
            "class_colors": cfg.platform.class_colors,
            "test_period": cfg.splits.resolved().test.model_dump(mode="json"),
            "calibration_period": cfg.splits.resolved().calibration.model_dump(mode="json"),
            "study": [str(cfg.study.start), str(cfg.study.end)],
            "basemap_url": cfg.platform.basemap_url,
            "basemap_attribution": cfg.platform.basemap_attribution,
            **state.art.status(),
        }

    @app.get("/api/boundary")
    def boundary() -> Response:
        return Response(state.art.boundary_geojson(), media_type="application/geo+json")

    @app.get("/api/model")
    def model() -> dict[str, Any]:
        if not state.art.stage_done("train"):
            raise HTTPException(409, "no trained models yet: run the pipeline through 'train'")
        return state.art.model_card()

    @app.get("/api/models")
    def models() -> list[dict[str, Any]]:
        if not state.art.stage_done("train"):
            raise HTTPException(409, "no trained models yet")
        return state.art.models_table()

    @app.get("/api/evaluation")
    def evaluation() -> dict[str, Any]:
        ev = state.art.evaluation()
        if ev is None:
            raise HTTPException(409, "final evaluation has not been run yet")
        return ev

    @app.get("/api/days")
    def days() -> list[dict[str, Any]]:
        out = []
        for date, rec in state.art.days().items():
            meta = pd.read_json(rec.meta_path, typ="series")
            out.append(
                {
                    "date": date,
                    "source": rec.source,
                    "partition": str(meta.get("partition", "")),
                    "model": str(meta.get("model", "")),
                    "max_p": clean({"v": meta.get("max_p")})["v"],
                }
            )
        return out

    @app.get("/api/days/{date}")
    def day(date: str) -> dict[str, Any]:
        return clean(state.art.day_summary(state.day(date)))

    @app.get("/api/days/{date}/overlay.png")
    def overlay(date: str) -> Response:
        rec = state.day(date)
        png = overlay_png(
            rec.class_path, tuple(cfg.platform.class_colors), cfg.platform.map_overlay_max_px
        )
        return Response(
            png, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"}
        )

    @app.get("/api/days/{date}/prob.tif")
    def prob_tif(date: str) -> FileResponse:
        rec = state.day(date)
        return FileResponse(rec.prob_path, media_type="image/tiff", filename=rec.prob_path.name)

    @app.get("/api/days/{date}/top")
    def top(date: str, n: int = Query(default=None, ge=1, le=500)) -> list[dict[str, Any]]:
        return state.art.top_cells(state.day(date), n or cfg.platform.top_cells)

    @app.get("/api/days/{date}/cell")
    def cell(date: str, lat: float, lon: float, explain: bool = True) -> dict[str, Any]:
        rec = state.day(date)
        info = state.art.cell_at(rec, lat, lon)
        if info is None:
            raise HTTPException(404, "point is outside the analysis grid")
        observed = state.art.observed(date)
        info["observed_new_event"] = None if observed is None else info["cell_id"] in observed
        if explain and info.get("eligible"):
            try:
                expl = state.engine.explain_cells(
                    pd.Timestamp(date), [int(info["cell_id"])], cfg.platform.n_drivers
                )
                info["explanation"] = expl.get(int(info["cell_id"]))
            except (TestSetAccessError, FileNotFoundError) as exc:
                info["explanation"] = {"error": str(exc)}
        info["disclaimer"] = DISCLAIMER
        return clean(info)

    @app.post("/api/forecast")
    def forecast(date: dt.date) -> dict[str, Any]:
        try:
            return clean(run_forecast(cfg, state.art.paths, date))
        except TestSetAccessError as exc:
            raise HTTPException(403, str(exc)) from exc
        except (FileNotFoundError, KeyError, ValueError) as exc:
            raise HTTPException(422, f"cannot forecast {date}: {exc}") from exc

    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
    return app
