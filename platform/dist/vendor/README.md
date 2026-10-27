# Vendored libraries

Loaded only when the satellite detail view opens. Copied unmodified from cdnjs.

| File | Library | Version | License | Source | SHA-256 |
|---|---|---|---|---|---|
| `leaflet.min.js` | Leaflet | 1.9.4 | BSD-2-Clause | https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js | `5c9aecfc30e4564519dbdcddcc53a418227dcc7568e619e9762ddcec7609ed47` |
| `leaflet.min.css` | Leaflet | 1.9.4 | BSD-2-Clause | https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css | `b570abbda963c60b4de4b4ff4b26f9326f53fb2ccf1461fdf0955ca094fb2539` |
| `proj4.js` | proj4js | 2.11.0 | MIT | https://cdnjs.cloudflare.com/ajax/libs/proj4js/2.11.0/proj4.js | `4975fbf411fac1842c5b91d362d323d3f01ca0cb52385a2ea219790ffaa20a80` |

The detail view requests imagery tiles at view time:

- Esri World Imagery, `server.arcgisonline.com`. Attribution required:
  Esri, Maxar, Earthstar Geographics. Commercial use needs an ArcGIS account
  under Esri's terms.
- Sentinel-2 cloudless 2016 by EOX IT Services, `tiles.maps.eox.at`,
  CC BY 4.0, contains modified Copernicus Sentinel data 2016.

The rest of the map works offline; only this view needs a connection.
