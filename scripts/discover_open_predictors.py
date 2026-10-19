"""Probe documented anonymous predictor endpoints, using development dates only."""

import concurrent.futures
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/real/public_discovery"


def probe(item):
    name, url = item
    result = {"name": name, "url": url, "checked_utc": datetime.now(UTC).isoformat()}
    try:
        req = Request(
            url,
            headers={
                "User-Agent": "wildfire-kz research public-data discovery",
                "Accept": "application/json",
            },
        )
        with urlopen(req, timeout=45) as response:
            body = response.read(2_000_001)
            if len(body) > 2_000_000:
                raise ValueError("Probe response exceeded 2 MB limit")
            result.update(
                status=response.status,
                final_url=response.url,
                bytes=len(body),
                sha256=hashlib.sha256(body).hexdigest(),
                content_type=response.headers.get("Content-Type"),
            )
            (OUT / f"{name}.body").write_bytes(body)
            try:
                value = json.loads(body)
                result["keys"] = list(value) if isinstance(value, dict) else "list"
                result["preview"] = str(value)[:600]
            except (ValueError, UnicodeDecodeError):
                result["prefix"] = body[:24].hex()
    except Exception as exc:
        result["error"] = str(exc)
    return result


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    OUT.mkdir(parents=True, exist_ok=True)
    base = "https://modis.ornl.gov/rst/api/v1/"
    point = {
        "latitude": 49.5,
        "longitude": 68,
        "startDate": "A2015193",
        "endDate": "A2015193",
        "kmAboveBelow": 1,
        "kmLeftRight": 1,
    }
    targets = {
        "ornl_products": base + "products",
        "ornl_mod13_bands": base + "MOD13A2/bands",
        "ornl_landcover_bands": base + "MCD12Q1/bands",
        "ornl_vegetation_sample": base + "MOD13A2/subset?" + urlencode(point),
        "ornl_landcover_sample": base
        + "MCD12Q1/subset?"
        + urlencode(point | {"startDate": "A2015001", "endDate": "A2015001", "band": "LC_Type1"}),
        "om_era5_land_sample": "https://archive-api.open-meteo.com/v1/archive?"
        + urlencode(
            {
                "latitude": 49.5,
                "longitude": 68,
                "start_date": "2015-07-01",
                "end_date": "2015-07-03",
                "models": "era5_land",
                "hourly": "temperature_2m,relative_humidity_2m,wind_speed_10m,precipitation,soil_moisture_0_to_7cm",
                "timezone": "UTC",
                "wind_speed_unit": "ms",
            }
        ),
        "opentopo_srtm_listing": "https://s3.opentopography.org/?list-type=2&prefix=SRTM_GL1/SRTM_GL1_srtm&max-keys=2",
        "worldpop_2014_metadata": "https://data.worldpop.org/GIS/Population/Global_2000_2020/2014/KAZ/kaz_ppp_2014_metadata.html",
        "om_era5_tutorial": "https://raw.githubusercontent.com/open-meteo/open-data/main/tutorial_download_era5/README.md",
    }
    evidence = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for item in pool.map(probe, targets.items()):
            evidence.append(item)
            print(json.dumps(item, ensure_ascii=False), flush=True)
            (OUT / "evidence.json").write_text(
                json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8"
            )


if __name__ == "__main__":
    main()
