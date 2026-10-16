"""Record anonymous access evidence for required products, using development dates only."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from wildfire_kz.data import dump_json


def get_json(url: str) -> dict:
    """Read public catalog metadata, not time-indexed held-out observations."""
    request = Request(
        url, headers={"User-Agent": "wildfire-kz/0.1 public research", "Accept": "application/json"}
    )
    with urlopen(request, timeout=25) as response:
        return json.loads(response.read(20 * 1024 * 1024))


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    root = Path("runs/primary/acquisition")
    evidence: list[dict] = []
    for product in ["MOD13A2", "MCD12Q1"]:
        query = {
            "short_name": product,
            "version": "061",
            "page_size": 1,
            "bounding_box": "46,40,88,56",
            "temporal": "2015-01-01T00:00:00Z,2015-01-20T23:59:59Z",
        }
        url = "https://cmr.earthdata.nasa.gov/search/granules.json?" + urlencode(query)
        item = {"product": product, "catalog_url": url, "query_year": 2015}
        try:
            catalog = get_json(url)
            dump_json(root / f"{product}_development_granule_metadata.json", catalog)
            entries = catalog.get("feed", {}).get("entry", [])
            links = [
                link["href"]
                for entry in entries
                for link in entry.get("links", [])
                if "data#" in link.get("rel", "")
                and not link.get("inherited", False)
                and link.get("href", "").startswith("https://")
            ]
            if not links:
                item["result"] = "no_data_link_returned"
            else:
                item["data_url"] = links[0]
                request = Request(
                    links[0], headers={"Range": "bytes=0-15", "User-Agent": "wildfire-kz/0.1"}
                )
                try:
                    with urlopen(request, timeout=25) as response:
                        prefix = response.read(16)
                        item.update(
                            http_status=response.status,
                            content_type=response.headers.get("Content-Type"),
                            final_host=urlsplit(response.url).hostname,
                            binary_prefix=prefix.hex() if b"html" not in prefix.lower() else None,
                        )
                        item["result"] = (
                            "authentication_page"
                            if "urs.earthdata" in response.url
                            else "anonymous_header_received"
                        )
                except HTTPError as exc:
                    item.update(result="http_access_denied", http_status=exc.code)
        except (HTTPError, URLError, TimeoutError) as exc:
            item.update(result="catalog_or_network_unavailable", detail=str(exc))
        evidence.append(item)
        print(json.dumps(item), flush=True)
        dump_json(root / "public_access_probes.json", evidence)
    for name, url in {
        "ERA5-Land Earth Data Hub": "https://api.earthdatahub.destine.eu/era5/era5-land-v0.zarr/.zmetadata",
        "Planetary Computer exact-product catalog": "https://planetarycomputer.microsoft.com/api/stac/v1/collections",
    }.items():
        item = {"product": name, "url": url}
        try:
            catalog = get_json(url)
            if "collections" in catalog:
                identifiers = [record["id"] for record in catalog["collections"]]
                item.update(
                    result="catalog_accessible",
                    exact_modis_candidates=[
                        i for i in identifiers if "13a2" in i.lower() or "12q1" in i.lower()
                    ],
                )
            else:
                item["result"] = "anonymous_metadata_accessible"
            dump_json(
                root
                / ("planetary_catalog.json" if "Planetary" in name else "era5_land_zmetadata.json"),
                catalog,
            )
        except HTTPError as exc:
            item.update(result="http_access_denied", http_status=exc.code)
        except (URLError, TimeoutError) as exc:
            item.update(result="network_unavailable", detail=str(exc))
        evidence.append(item)
        print(json.dumps(item), flush=True)
        dump_json(root / "public_access_probes.json", evidence)


if __name__ == "__main__":
    main()
