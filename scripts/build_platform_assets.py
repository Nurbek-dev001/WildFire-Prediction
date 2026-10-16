"""Export actual geography and permitted 2015–2022 observations for the map UI.

Never opens sealed archives or any detection partition after 2022. This is a
display export, not model training. Simplification applies only to map outlines.
"""

import json
import struct
from pathlib import Path

import geopandas as gpd
import pandas as pd
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "platform/dist/assets"


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    grid = gpd.read_parquet(ROOT / "data/real/normalized/grid_5km.parquet")
    regions = gpd.read_parquet(ROOT / "data/real/normalized/regions.parquet").to_crs(grid.crs)
    boundary = gpd.read_parquet(ROOT / "data/real/normalized/boundary.parquet").to_crs(grid.crs)
    # Representative points ensure even partially clipped coastal cells get a region.
    points = grid.copy()
    points.geometry = grid.representative_point()
    joined = gpd.sjoin(points, regions[["region", "geometry"]], how="left", predicate="intersects")
    joined = joined[~joined.index.duplicated()].reindex(grid.index)
    assert joined.region.notna().all()
    ids = regions.region.tolist()
    counts = []
    for year in range(2015, 2023):
        observations = pd.read_parquet(
            ROOT / f"data/real/normalized/detections_{year}.parquet",
            columns=["cell_id", "confidence"],
        )
        permitted = observations[observations.confidence.isin(["n", "h"])]
        c = permitted.groupby("cell_id").size().reindex(grid.cell_id, fill_value=0).to_numpy()
        assert c.max() <= 65535
        counts.append(c)
    transform = Transformer.from_crs(grid.crs, 4326, always_xy=True)
    lon, lat = transform.transform(points.geometry.x, points.geometry.y)
    payload = bytearray()
    for i, row in enumerate(grid.itertuples()):
        payload.extend(
            struct.pack(
                "<hhfffH8H",
                row.row,
                row.col,
                row.area_km2,
                lon[i],
                lat[i],
                ids.index(joined.region.iloc[i]),
                *(int(c[i]) for c in counts),
            )
        )
    (DEST / "cells.bin").write_bytes(payload)

    def coords(geom):
        if geom.geom_type == "Polygon":
            return [
                [[round(x / 1000, 2), round(-y / 1000, 2)] for x, y in ring.coords]
                for ring in [geom.exterior, *geom.interiors]
            ]
        return [r for part in geom.geoms for r in coords(part)]

    ru = [
        "Павлодарская",
        "Жамбылская",
        "Костанайская",
        "Мангистауская",
        "Карагандинская",
        "Кызылординская",
        "Восточно-Казахстанская",
        "Актюбинская",
        "Атырауская",
        "Южно-Казахстанская",
        "Акмолинская",
        "Алматинская",
        "Северо-Казахстанская",
        "Алматы",
        "Западно-Казахстанская",
        "Астана",
    ]
    city_coordinates = [
        ("Астана", 71.43, 51.17),
        ("Алматы", 76.89, 43.24),
        ("Шымкент", 69.59, 42.32),
        ("Актобе", 57.17, 50.28),
        ("Атырау", 51.92, 47.09),
        ("Караганда", 73.09, 49.81),
        ("Костанай", 63.62, 53.22),
        ("Павлодар", 76.97, 52.29),
        ("Семей", 80.23, 50.41),
        ("Кызылорда", 65.51, 44.85),
        ("Актау", 51.17, 43.65),
    ]
    forward = Transformer.from_crs(4326, grid.crs, always_xy=True)
    cities = []
    for name, lng, lt in city_coordinates:
        x, y = forward.transform(lng, lt)
        cities.append({"name": name, "x": round(x / 1000, 2), "y": round(-y / 1000, 2)})
    meta = {
        "count": len(grid),
        "record_bytes": 34,
        "resolution_km": 5,
        "years": list(range(2015, 2023)),
        "bounds": [round(v / 1000, 2) for v in grid.total_bounds],
        "crs": grid.crs.to_string(),
        "outline": coords(boundary.geometry.union_all().simplify(2000, preserve_topology=True)),
        "regions": [
            {
                "name": ids[i],
                "label": ru[i],
                "rings": coords(row.geometry.simplify(3000, preserve_topology=True)),
            }
            for i, row in enumerate(regions.itertuples())
        ],
        "cities": cities,
        "history_totals": [int(c.sum()) for c in counts],
        "source": {
            "boundary": "geoBoundaries / OSM, 2017; ODbL",
            "boundary_url": "https://www.geoboundaries.org/",
            "observations": "NASA FIRMS S-NPP VIIRS, nominal/high; исходные детекции, не события",
            "observations_url": "https://firms.modaps.eosdis.nasa.gov/",
            "holdout": "2023–2024 sealed; not included in this export",
        },
    }
    (DEST / "geography.json").write_text(
        json.dumps(meta, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    status = {
        "ready": False,
        "available_days": [],
        "synthetic": False,
        "missing_sources": ["weather", "vegetation", "landcover", "static", "human"],
        "holdout_sealed": True,
        "message": "Реальная модель ещё не обучена. Доступен демонстрационный сценарий.",
    }
    (DEST / "forecast-manifest.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Exported {len(grid):,} actual cells; {len(payload):,} bytes. Holdout untouched.")


if __name__ == "__main__":
    main()
