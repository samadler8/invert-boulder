# One-command Boulder forecast explorer: previous 48h and next 48h

Run **from the project root** in the existing working Conda environment:

```bash
conda activate inversion312
cd ~/github/invert-boulder
python -m scripts.quicklook
```

The command (1) reconstructs missing past-hour forecast **vintages** using archived issued HRRR GRIB forecasts, (2) retrieves a sparse set of future forecasts from a recent HRRR extended run, (3) saves compact results locally, and (4) starts the web server and opens `http://127.0.0.1:8000`. There is **no need to run `hrrr live` and `uvicorn` separately**. The previous 48h and future window are shown together, and a separate history panel lets you examine as-of T-24, T-18, T-12, T-6, and T-0 when those vintages have been saved.

To stop the server: `Ctrl+C`. To update HRRR while the server is already running in another Terminal, do **not** launch a second server; run:

```bash
python -m scripts.quicklook --refresh-only
```

Then click **Reload saved predictions** on the website. This button only rereads local data; it intentionally does not trigger a large NOAA download.

## How much will it download?

By default it samples every 3 hours, **plus 5, 6, 7, 8, and 9 AM Boulder time**. Historical reconstruction uses one T-6h as-of forecast per missing target. Each new forecast time requires a surface and a pressure-level indexed GRIB subset download and decode. The very first run may take a while or transfer substantial data; repeated runs reuse `data/quicklook_forecast_cache.jsonl` and the existing SQLite history, avoiding those downloads.

To make an inexpensive first smoke test:

```bash
python -m scripts.quicklook --max-new 3 --refresh-only
```

Then rerun the normal command later. The partial results are retained.

For detailed retrospective vintage comparison (up to **four** as-of forecasts per sampled past hour; more downloads):

```bash
python -m scripts.quicklook --refresh-only --past-offsets 6,12,18,24
```

For every hourly target (up to about 96 hours worth of sampled targets and possibly many dozens of additional GRIB requests):

```bash
python -m scripts.quicklook --refresh-only --past-step 1 --future-step 1
```

To start the site without network calls after earlier cache creation:

```bash
python -m scripts.quicklook --no-past --no-future
```

## Scientific and data-integrity notes

* **Future**: NOAA extended HRRR cycles (00, 06, 12, 18 UTC) offer leads 0–48h. A model initialized hours **before now** cannot necessarily forecast out to **now + 48 hours**. The website displays available issued hours and explicitly marks unfilled horizon as unavailable, not a prediction. The quicklook tries an older issued cycle once if the latest selected cycle yields no data.
* **Past**: A previously **captured** score really was saved by this app. A **reconstructed** score was computed after the fact from an archived issued HRRR forecast using the current heuristic and an assumed 2-hour publication delay. It is not proof that the site showed the score at the time. The 48h timeline uses only genuinely pre-event captured scores (at or before T-6h) or clearly marked reconstructions.
* **Uncalibrated scores**: The scenic index assesses potential low cloud below the peaks with relatively clear air above. The older low-cloud index rates favorable fog/low-cloud ingredients. Neither is an observed inversion or a calibrated probability.
* **ML unchanged**: The existing ML dataset and weights still use forecast leads **0–39 hours** (`MAX_LEAD_HOURS=40`). The quicklook's **48-hour display** (`DISPLAY_MAX_LEAD_HOURS=49`) only adds extra heuristic-only hours; it does not silently extrapolate model predictions beyond their training horizon. It does not alter `data/hrrr_samples.jsonl` or the METAR CSV.
* **Caches**: The collector writes `data/quicklook_forecast_cache.jsonl`, `data/hrrr_live.jsonl`, and `data/forecast_history.sqlite3`, all Git-ignored. Existing old versions in the history DB are immutable; new reconstruction versions are stored separately.
* **Failures and interruptions**: Successful individual downloads are saved immediately in the quicklook cache. On the next invocation it skips them. The website's live cache is replaced only after at least one new-cycle sample was assembled; a failed cycle does not erase the previous cache. Keep the Mac awake and online while fetching, or interrupt with `Ctrl+C` and resume later.
* This does not provide continuously running background collection. While your laptop sleeps, no downloads occur; rerun when you want current data.

## Fill all T−6/12/18/24 predictions for one selected past hour

The four-slot history panel is intentionally not a promise that four vintages
have already been downloaded. The normal quicklook collects only T−6 as a
fast starting point. Click a past hour and choose **Fill missing forecast
cutoffs**. This triggers a bounded asynchronous request for just that event's
missing HRRR-issued forecasts. Progress and errors appear below the controls.
The original low-cloud and the two summit-scenic indices are displayed
independently, alongside cloud fractions, humidity, temperature change, wind,
cloud-base and provenance. Missing archived readings show a dash, not zero.

Alternatively in Terminal:

```bash
python -m scripts.quicklook --past-event '2026-10-30 08:00' \
  --past-offsets 24,18,12,6,0 --no-future --refresh-only
```

Use an event within the previous 48 hours. If you want to maintain five
vintages for every selected hour automatically, use
`--past-offsets 24,18,12,6,0` without `--past-event`, but expect up to three
additional NOAA retrievals **per historical hour** and a much slower run.


## New: smooth sky penalty, nearby-grid spread, and observed T-0

The scenic heuristic is now versioned **v2-smooth-sky**. With middle-cloud
fraction `M/100` and high-cloud fraction `H/100`, the revised upper-sky
factor is:

```text
exp(-2.4*(M/100)^1.7) * exp(-1.5*(H/100)^1.7)
```

It strongly penalizes extensive higher clouds **without an all-or-nothing
85% threshold**. The middle-cloud penalty is stronger than the high-cloud
penalty, since high cloud can be optically thin cirrus. These coefficients are
subjective hypotheses that should be tested on verified scenic outcomes; the
result is still a 0-100 *index*, never a probability. Original low-cloud
weights are unchanged.

Newly downloaded NOAA surface GRIB subsets are sampled at the KBDU grid cell
and four nearby model grid cells without additional NOAA files. The separate
spatial diagnostic shows low/mid/high cloud spreads; these are model fields,
not actual summit observations. Older caches lack this information and will
show 'unavailable'.

The history panel now compares T-24, T-18, T-12, T-6 **and T-0** using
forecast runs plausibly available by each cutoff, assuming two hours of
publication delay for retrospective reconstructions. **T-0 is still a model
forecast, not an actual measurement.** The new independent KBDU METAR card
shows nearest-hour airport fog, low ceiling, visibility and reported cloud
*base*, when available. Choose **Refresh actual airport report** to retrieve
that date from Iowa Environmental Mesonet. The original training CSV is
unmodified and missing data stays unknown. METAR cannot verify the mountain
cloud top or scenic view.

The page also computes historical forecast-to-forecast min/max spreads in
low, middle and high cloud cover; that indicates revision across HRRR cycles,
not a calibrated confidence interval.

```bash
# Update just one historical event, including its at-event vintage:
python -m scripts.quicklook --past-event '2026-10-30 08:00' \
  --past-offsets 24,18,12,6,0 --no-future --refresh-only

# Optional: refresh independent real weather reports for recent days:
python -m scripts.refresh_observations --days 4
```
