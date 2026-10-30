# Boulder Weather Explorer Update

## What changed

- Detailed time-of-day forecast explorer with previous/next/play buttons and a
  slider that visits **only actual HRRR forecast valid hours**. It does not
  fabricate missing hourly predictions.
- Schematic, responsive vector atmospheric cross section (Boulder -> First
  Flatiron -> Green Mountain). Low/mid/high cloud cover drives the illustration;
  a dashed line **only** shows an RH drying-transition proxy when available.
  The actual cloud-top altitude and summit clearance remain unverified.
- Sunrise/sunset, civil twilight, morning/evening golden-hour boundaries,
  and daylight duration in Boulder local time. These times are calculated
  offline from astronomical equations, not from HRRR or a third-party API.
  They assume a level apparent horizon and do not account for Flatirons terrain.
- A 19-item HRRR diagnostic grid, showing the available forecast readings
  and uncertainty rather than inventing missing values.
- First Flatiron elevation: **7,258 ft**; Green Mountain: **8,133 ft**.
  Heights are used in the Python scenic calculation, not only front-end labels.
- A new scenic version marks the elevation adjustment. SQLite forecast-history
  tables migrate losslessly to store both scenic algorithm versions side by side;
  old captured predictions are never altered or backdated.

## Install

```bash
cd ~/github/invert-boulder
unzip -o ~/Downloads/invert-boulder-weather-explorer-overlay.zip -d .
conda activate inversion312
python -m pytest -q
python -m uvicorn inversion.server:app --reload
```

Then open http://127.0.0.1:8000. The existing **Refresh everything** button
still downloads only a bounded set of new HRRR forecasts and selected history.
The atmospheric time slider runs entirely on existing forecast records and
never downloads additional GRIB data.

## Astronomy endpoint

`GET /api/solar?date_local=2026-10-31`

Coordinates: downtown Boulder at 40.0150, -105.2705.
Sunrise/sunset use the standard apparent solar altitude of -0.833 degrees;
civil dawn/dusk use -6 degrees. Golden-hour bounds are approximated by the
sun crossing +6 degrees altitude. Small differences (1-2 minutes) from
commercial almanacs are expected.

## Data provenance and limitations

- HRRR model fields represent a model grid cell near **KBDU**, not observed
  clouds at either mountain summit.
- The 25-level RH profile is interpolated from sparse pressure levels and
  can miss shallow cloud structures. RH drying **is not a measured cloud top**.
- A generic HRRR `HGT:cloud top` can refer to upper-level clouds, not the
  low valley fog; it remains an independent diagnostic, not the visual fog top.
- Slider steps are sparse issued-run valid times; when NOAA downloaded no hour,
  the visualization does not interpolate one.
- Heuristic 0-100 values are uncalibrated suitability indices, not probabilities.
- Sun times are astronomical and aren't local topographic sunrise times.

## Files modified

`index.html`, `dashboard.js`, `inversion/config.py`, `inversion/scenic.py`,
`inversion/solar.py`, `inversion/server.py`, `inversion/history.py`,
`guide.html`, `science.html`, `README.md`, and added
`tests/test_weather_explorer.py`.
