"""Export a true-colour satellite basemap of Kazakhstan for the map UI.

Downloads NASA Blue Marble Next Generation (cloud-free composite, 500 m,
public domain) from NASA GIBS WMS in EPSG:4326 tiles, keeps the raw tiles with
SHA-256 records, and resamples them onto the project's equal-area grid at 1 km
per pixel. This is a display layer only; it is not a model input.
"""

import hashlib
import io
import json
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image
from pyproj import CRS, Transformer

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "platform/dist/assets"
RAW = ROOT / "data/real/public_predictors/satellite/raw"
LAYER = "BlueMarble_NextGeneration"
WMS = "https://gibs.earthdata.nasa.gov/wms/epsg4326/best/wms.cgi"
# Output extent in the map's km coordinates (x east, y south), 1 km per pixel.
X0, X1, Y0, Y1 = -1520, 1480, -850, 850
DEG = 0.008
TILES = (4, 2)


def fetch_tile(lon0, lon1, lat0, lat1):
    width, height = round((lon1 - lon0) / DEG), round((lat1 - lat0) / DEG)
    query = {
        "SERVICE": "WMS",
        "REQUEST": "GetMap",
        "VERSION": "1.3.0",
        "LAYERS": LAYER,
        "STYLES": "",
        "CRS": "EPSG:4326",
        "BBOX": f"{lat0},{lon0},{lat1},{lon1}",
        "WIDTH": width,
        "HEIGHT": height,
        "FORMAT": "image/jpeg",
    }
    url = WMS + "?" + urllib.parse.urlencode(query)
    name = f"{LAYER}_{lon0:.3f}_{lat0:.3f}_{lon1:.3f}_{lat1:.3f}.jpg"
    path = RAW / name
    if not path.exists():
        with urllib.request.urlopen(url, timeout=180) as response:
            body = response.read()
            if not response.headers.get("Content-Type", "").startswith("image/"):
                raise RuntimeError(
                    f"GIBS returned {response.headers.get('Content-Type')}: {body[:300]!r}"
                )
        path.write_bytes(body)
        (RAW / (name + ".sha256.json")).write_text(
            json.dumps(
                {"url": url, "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)},
                indent=1,
            ),
            encoding="utf-8",
        )
    return np.asarray(Image.open(io.BytesIO(path.read_bytes())).convert("RGB")), path


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    geo = json.loads((DEST / "geography.json").read_text(encoding="utf-8"))
    crs = CRS.from_json(geo["crs"])
    to_lonlat = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)

    # Output pixel centres -> projected metres (north positive) -> lon/lat.
    xs = np.arange(X0, X1) + 0.5
    ys = np.arange(Y0, Y1) + 0.5
    gx, gy = np.meshgrid(xs, ys)
    lon, lat = to_lonlat.transform(gx * 1000, -gy * 1000)
    lon0, lon1 = np.floor(lon.min()) - 0.5, np.ceil(lon.max()) + 0.5
    lat0, lat1 = np.floor(lat.min()) - 0.5, np.ceil(lat.max()) + 0.5

    # Download in tiles and stitch into one lon/lat mosaic.
    nx, ny = TILES
    lons, lats = np.linspace(lon0, lon1, nx + 1), np.linspace(lat0, lat1, ny + 1)
    rows, sources = [], []
    for j in range(ny - 1, -1, -1):  # north to south
        row = []
        for i in range(nx):
            tile, path = fetch_tile(lons[i], lons[i + 1], lats[j], lats[j + 1])
            row.append(tile)
            sources.append(path.name)
        rows.append(np.concatenate(row, axis=1))
    mosaic = np.concatenate(rows, axis=0).astype(np.float32)
    h, w, _ = mosaic.shape

    # Bilinear sampling of the mosaic at each output pixel.
    fx = (lon - lon0) / (lon1 - lon0) * w - 0.5
    fy = (lat1 - lat) / (lat1 - lat0) * h - 0.5
    x0 = np.clip(np.floor(fx).astype(int), 0, w - 2)
    y0 = np.clip(np.floor(fy).astype(int), 0, h - 2)
    ax = np.clip(fx - x0, 0, 1)[..., None]
    ay = np.clip(fy - y0, 0, 1)[..., None]
    top = mosaic[y0, x0] * (1 - ax) + mosaic[y0, x0 + 1] * ax
    bottom = mosaic[y0 + 1, x0] * (1 - ax) + mosaic[y0 + 1, x0 + 1] * ax
    image = np.clip(top * (1 - ay) + bottom * ay, 0, 255).astype(np.uint8)

    out = io.BytesIO()
    Image.fromarray(image).save(out, "JPEG", quality=82, optimize=True, progressive=True)
    payload = out.getvalue()
    (DEST / "satellite.jpg").write_bytes(payload)
    meta = {
        "source": "NASA Blue Marble Next Generation via NASA GIBS WMS",
        "layer": LAYER,
        "license": "NASA imagery, public domain; acknowledgement to NASA GIBS / ESDIS",
        "raw_tiles": sources,
        "resampling": "bilinear from EPSG:4326 mosaic at 0.008 degrees",
        "extent_km": {
            "x0": X0,
            "x1": X1,
            "y0": Y0,
            "y1": Y1,
            "y_axis": "south positive, as in geography.json",
        },
        "pixel_km": 1,
        "width": X1 - X0,
        "height": Y1 - Y0,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
    }
    (DEST / "satellite.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: meta[k] for k in ("width", "height", "bytes", "sha256")}))


if __name__ == "__main__":
    main()
