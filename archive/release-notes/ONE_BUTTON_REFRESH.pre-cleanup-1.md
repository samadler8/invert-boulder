# One-button website refresh

Install the overlay into your `invert-boulder` repository and run:

```bash
python -m pytest -q
python -m uvicorn inversion.server:app --reload
```

Visit http://127.0.0.1:8000, select a past hour in the history section if you want to investigate a particular event, and click **Refresh everything** near the two-day explorer (or the circular arrow at the top).

The backend executes three steps, sequentially:

1. Get current HRRR forecast data from an appropriately lagged extended run. Reuse the existing per-run cache; at most **six NEW forecast lead hours** per click. Other saved forecast hours from that run are reused.
2. Fill missing/outdated T-24, T-18, T-12, T-6 and T-0 forecast comparisons for the **selected historical hour**. If you haven't selected an hour, use the most recent 7 AM Boulder hour. Reconstruction can require up to five additional historical GRIB requests; the website reports which one is underway.
3. Refresh independent KBDU observations over the past ~55 hours, in a separate CSV. These observations are not summit measurements.

The job reports progress and refreshes the page's local forecast/history panels when complete. If one stage fails, later stages still run; successful downloads are retained. The historical scores remain marked **reconstructed** when generated later.

The default deliberately does *not* reconstruct all five vintages for all ~22 past hours on every click, which could cause 100+ HRRR downloads and a long wait. The existing terminal `python -m scripts.quicklook` remains available for more extensive backfills.

Some new hours may remain unavailable because of NOAA run horizons, processing/publication lag, or the six-new-hour safety limit. Clicking again can fetch additional future hours. Your computer needs internet access and must remain awake for refresh to run. This is a local server, not a hosted background service.
