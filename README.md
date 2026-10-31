# Boulder Inversion Outlook

A **real-data, public-source forecast explorer** for a very particular Boulder morning: low cloud over the city, dry air and a possible cloud break below **Green Mountain (8,133 ft)**, and little cloud above. First Flatiron (7,258 ft) is a map landmark, not a separate score. All numerical forecast scores are **0–100 uncalibrated indices, not probabilities or verified events**.

The active application contains **no machine learning, fabricated demo forecasts, or pretrained model dependencies**. Previous XGBoost/CNN experiments are retained under `archive/machine-learning/` but not imported.

## Install this release into your existing checkout

**Preserve your local work first:** run `git status --short`, commit or back up any changes you want to keep, and back up the `data/` folder if you have valuable observations. This release replaces some source and website files, but the supplied packages do **not** include user forecasts or databases.

After extracting the **overlay ZIP** into the project root, run `python -m scripts.finalize_checkout` **once** to move older ML entry points and obsolete root-level release notes into `archive/`. It never moves or deletes anything inside `data/` or `models/` and never overwrites an existing archived file.

## Install and run (macOS / Linux)

```bash
cd ~/github/invert-boulder
conda activate inversion312
python -m pip install -r requirements.txt -r requirements-hrrr.txt
python -m pytest -q
python -m uvicorn inversion.server:app --reload
```

Open **http://127.0.0.1:8000**. Cached forecasts render immediately. Click **Refresh forecast** to retrieve actual issued NOAA HRRR fields, selected historical vintages, independent airport reports, and a separately labeled NWS outlook. Failed sources leave their last usable cached data in place. Internet is needed to refresh; no external calls happen on ordinary page GET requests. The first refresh can be slow because it downloads selected indexed GRIB fields for multiple hours.

From a separate terminal:

```bash
python -m scripts.quicklook --no-past --refresh-only --max-new 6
python -m scripts.explain_forecast --top 8
python -m scripts.storage status
python -m scripts.storage cleanup         # dry-run
python -m scripts.storage cleanup --apply # safe disposable-cache cleanup
```

You can also launch the self-contained quicklook with `python -m scripts.quicklook`, though this may backfill many historical hours on the first run. The `--no-past` option is much quicker.

## Where the information comes from

| Source | Used for | Important limitation |
|---|---|---|
| [NOAA HRRR GRIB2 archive](https://registry.opendata.aws/noaa-hrrr-pds/) via Herbie/ecCodes | Issued forecasts; low/mid/high cloud, visibility, wind, boundary layer, surface temperature/dew point, vertical humidity and sampled terrain | ~3 km horizontal grid; sparse humidity levels cannot measure low-cloud top |
| Ten HRRR sampling locations from Boulder to the foothills | Local changes along the route, model terrain and altitude-dependent RH | Points may share a grid cell; not separate observations |
| [Iowa Environmental Mesonet](https://mesonet.agron.iastate.edu/request/download.phtml?network=CO_ASOS) | Independent METAR data for Boulder (BDU), Broomfield (BJC), Erie (EIK), Longmont (LMO, when reporting) | Airport clouds and visibility **do not verify summit conditions** |
| [NWS hourly forecast](https://api.weather.gov/) | A second, independent forecast narrative, wind, humidity and precipitation guidance | Separate from HRRR; not an observation and never scored as independent evidence |
| Local astronomical calculations | Sunrise, sunset, civil twilight and golden hour | Assumes flat apparent horizon, not mountain-shadow timing |

**One headline score** (`inversion/opportunity.py`) combines the previous physically motivated low-deck scenic setup (surface saturation/stability, HRRR cloud fractions, drying toward 8,133 ft, and smoother mid/high-cloud penalties) with a **small optional spatial modifier** from actual cached HRRR grid points. If mandatory profile data are missing, the score stays unavailable; if spatial data are missing, the previous model-column result is used without inventing spatial evidence. The formula is versioned and *must not* be treated as observed inversion odds.

## Storage, provenance, and privacy

The application stores only small decoded forecast records: `data/hrrr_live.jsonl` (current run), `data/quicklook_forecast_cache.jsonl` (reusable issued-run leads), and `data/forecast_history.sqlite3` (immutable captured and explicitly labeled reconstructed score vintages). New nearby-station METARs are kept in `data/observed_nearby.json`; NWS hourly guidance in `data/nws_hourly.json`; recent BDU reports in `data/observed_recent_bdu.csv`.

- HRRR GRIB subsets are deleted immediately after decoding. Stale leftovers in `data/hrrr_tmp` older than four hours are eligible for cleanup.
- The latest forecast caches are **trimmed to seven days** on website refresh. `scripts.storage cleanup` previews changes before `--apply`.
- History rows are **never deleted automatically**. Only an explicit `python -m scripts.storage cleanup --apply --history-days 365` purges ledger rows older than one year.
- Existing archival datasets such as `data/hrrr_samples.jsonl`, old observation CSVs, and `models/` files are **never deleted** by cleanup. You can archive them manually outside Git if disk space matters.
- The data directory is Git-ignored. The downloaded NOAA numerical values remain on your own machine unless you independently deploy the site.

## History and scientific safeguards

Historical views display the model prediction from T−24, −18, −12, −6 and T−0, alongside KBDU METAR. **Captured** means the app saved it by the cutoff; **reconstructed** means today's scoring code was applied later to an archived issued run with a two-hour *assumed* publication lag. Neither establishes what the summit looked like. When the score algorithm changes, earlier snapshots are not overwritten.

## Development layout

- `inversion/hrrr.py`: indexed NOAA GRIB subsetting and nearest-grid decoding
- `inversion/transect.py`: ten named foothills locations and vertical humidity diagnostics
- `inversion/heuristic.py`, `inversion/scenic.py`, `inversion/opportunity.py`: physical setup and **single primary score**
- `inversion/history.py`, `inversion/observations.py`, `inversion/nearby.py`: provenance and observation evidence
- `inversion/storage.py`, `scripts/storage.py`: bounded caching, safe cleanup, disk report
- `inversion/server.py`, `index.html`, `dashboard.js`: FastAPI and a responsive real-data dashboard
- `tests/`: offline fixtures and regression tests (no public weather request needed)
- `archive/`: earlier prototypes and machine-learning experiments

The site is an experimental planning tool, not a substitute for weather warnings, trail conditions, a camera facing Boulder, or summit observations. See [the methodology page](science.html).
