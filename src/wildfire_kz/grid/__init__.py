"""Equal-area lattice with stable globally anchored integer cell identifiers."""

import geopandas as gpd
import numpy as np
from pyproj import CRS
from shapely import covers, intersects, prepare
from shapely.geometry import box


def build_grid(boundary: gpd.GeoDataFrame, crs: str, resolution_m: int) -> gpd.GeoDataFrame:
    """Intersect a zero-anchored square lattice with a polygonal study boundary."""
    projection = CRS.from_user_input(crs)
    operation = projection.coordinate_operation
    if (
        not projection.is_projected
        or operation is None
        or not any(term in operation.method_name.lower() for term in ("equal area", "equal-area"))
    ):
        raise ValueError("A documented equal-area projected CRS is required")
    national = boundary.to_crs(projection).geometry.union_all()
    if not national.is_valid:
        raise ValueError("Study boundary must be a valid polygonal geometry")
    prepare(national)
    cells = []
    # Polygon-wise iteration avoids scanning the enormous empty bounding box of island fixtures.
    parts = list(national.geoms) if national.geom_type == "MultiPolygon" else [national]
    seen: set[tuple[int, int]] = set()
    for part in parts:
        xmin, ymin, xmax, ymax = part.bounds
        for row in range(int(np.floor(ymin / resolution_m)), int(np.ceil(ymax / resolution_m))):
            for col in range(int(np.floor(xmin / resolution_m)), int(np.ceil(xmax / resolution_m))):
                if (row, col) in seen:
                    continue
                square = box(
                    col * resolution_m,
                    row * resolution_m,
                    (col + 1) * resolution_m,
                    (row + 1) * resolution_m,
                )
                if not intersects(national, square):
                    continue
                # Preparing the complex national boundary avoids repeatedly clipping
                # fully interior squares against all its vertices.
                clipped = square if covers(national, square) else square.intersection(national)
                if clipped.area <= 0:
                    continue
                seen.add((row, col))
                cells.append(
                    {
                        "cell_id": f"g{resolution_m}_{row}_{col}",
                        "row": row,
                        "col": col,
                        "x": square.centroid.x,
                        "y_coord": square.centroid.y,
                        "area_km2": clipped.area / 1e6,
                        "geometry": clipped,
                    }
                )
    return gpd.GeoDataFrame(cells, crs=projection).sort_values("cell_id").reset_index(drop=True)
