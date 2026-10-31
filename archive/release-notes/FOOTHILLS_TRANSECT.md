# Foothills HRRR spatial transect

## What changed

The live dashboard now includes a **Boulder → Flatirons → Green Mountain** spatial forecast map and a relative-humidity-by-elevation heatmap. It shares the existing time slider with the cloud-layer view. A location click reveals the raw readings. OpenStreetMap tiles are optional; an offline geographic coordinate plot is used when map tiles/Leaflet are unavailable.

The sampled targets are Boulder airport, East Boulder, Central Boulder, Chautauqua, First Flatiron (7,258 ft label), and Green Mountain (8,133 ft label). They are sampling coordinates, **not six independent observations**. Actual model-cell lat/lon, smoothed model terrain elevation, and number of distinct model cells are retained with the forecast. Multiple targets may share a nearest HRRR grid cell.

### HRRR data: already available on AWS

- `wrfsfc` indexed GRIB2 messages: `HGT:surface`, `RH:2 m above ground`, and `LCDC`, `MCDC`, `HCDC` cloud cover. The existing point forecast downloads these already.
- `wrfprs`: `HGT` and `RH` at 800, 750, 700, 650, and 600 hPa (the existing point downloader also uses these).
- Each new future forecast passes the selected GRIB messages through ecCodes once, retrieves several grid-cell values per message using `codes_grib_find_nearest`, and then deletes the temporary GRIB subset.
- The model is **~3 km resolution**. We do not download full continental datasets and do not call the NOAA GSL image server.

See [NOAA HRRR data on AWS](https://registry.opendata.aws/noaa-hrrr-pds/) and [NOAA HRRR model-field inventory](https://www.nco.ncep.noaa.gov/pmb/products/hrrr/hrrr.t00z.wrfsfcf02.grib2.shtml).

### How to use it

1. Install the small overlay ZIP in `~/github/invert-boulder` and run `python -m pytest -q`.
2. Launch `python -m uvicorn inversion.server:app --reload`.
3. In **Interactive weather explorer**, select a forecast hour. Scroll to **Spatial HRRR weather map** to view locations and the humidity heatmap.
4. On **new** HRRR future forecasts, the geographic data is saved automatically by `python -m scripts.quicklook --no-past --refresh-only` or the site's **Refresh everything** button when that process fetches a new forecast hour.
5. For **older cached** future forecast hours, click **Load spatial data for selected hour**. This downloads just five surface and ten pressure messages for that HRRR run/lead, then updates both `data/hrrr_live.jsonl` and `data/quicklook_forecast_cache.jsonl` atomically. There is no 48-hour refetch. The site will show a status message. You can continue to view other forecast cards while it works.
6. The selected-hour spatial cache remains local and is not written over existing historical prediction snapshots.

**No ML retraining needed.** `features` (23 scalar values) and `profile` (4 × 25 values) are unchanged. The geographic samples are stored separately as `row['observables']['foothills_transect']`. The main scenic-index equation remains unchanged until the spatial evidence has been validated.

### Interpreting the display

Cloud percentages are HRRR's broad low/middle/high layer fractions **at each sampled grid cell**, not cloud top heights at the summit. The humidity heatmap interpolates between 2 m RH and sparse 800–600 hPa RH data by geopotential height; it never extrapolates below model terrain or above the measured profile range. A dry value near 8,133 ft can be encouraging but **does not certify an unobstructed view**. Vertical cloud condensate / cloud water and finer terrain modeling would be necessary to estimate fog-deck tops much more reliably.

The OpenStreetMap background (if online) provides geographic context only; the colored markers and heatmap are NOAA HRRR numerical model predictions, not OSM weather measurements.

This is primarily a **future-hour explorer**. Older saved history comparisons retain their original forecast snapshots; the new transect does not rewrite or relabel those historical predictions.
