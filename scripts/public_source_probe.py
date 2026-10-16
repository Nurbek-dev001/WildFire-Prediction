"""Fetch small public source metadata/assets; no credentials, no observations parsed."""

import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen

sys.stdout.reconfigure(encoding="utf-8")
root = Path("data/real/raw")
root.mkdir(parents=True, exist_ok=True)
targets = {
    "kaz_adm0.geojson": "https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/KAZ/ADM0/geoBoundaries-KAZ-ADM0.geojson",
    "kaz_adm1.geojson": "https://github.com/wmgeolab/geoBoundaries/raw/9469f09/releaseData/gbOpen/KAZ/ADM1/geoBoundaries-KAZ-ADM1.geojson",
    "firms_content.js": "https://firms.modaps.eosdis.nasa.gov/dist/firms_content.ae4369b7.js",
}
for name, url in targets.items():
    try:
        request = Request(url, headers={"User-Agent": "wildfire-kz research acquisition/0.1"})
        with urlopen(request, timeout=25) as response:
            body = response.read(30 * 1024 * 1024 + 1)
            if len(body) > 30 * 1024 * 1024:
                raise ValueError("Metadata/geometry download exceeds the public probe budget")
            (root / name).write_bytes(body)
            print(
                json.dumps(
                    {
                        "file": name,
                        "status": response.status,
                        "bytes": len(body),
                        "final_url": response.url,
                    }
                ),
                flush=True,
            )
    except Exception as exc:
        print(json.dumps({"file": name, "error": str(exc)}), flush=True)
