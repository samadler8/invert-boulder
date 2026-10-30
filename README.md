# Boulder Flatirons Inversion Tracker — experimental ML edition

A **local-first** weather-forecast postprocessor with two independently trained models:
1. **XGBoost** on engineered time-of-day, surface, cloud and vertical-gradient features.
2. **PyTorch 1D CNN** on a fixed above-ground temperature, humidity and horizontal-wind profile.

The original interactive SVG dashboard and its synthetic presets are retained. A local
FastAPI app supplies forecasts and runs both models. No database, paid GPU, or server
account is required. **The app requires internet for live forecasts and externally
hosted Tailwind/fonts/icons, but inference itself runs locally.**

## Important: what the model actually predicts

With `--allow-proxy-labels`, the label is a *weather-model-produced proxy* for
low visibility over Boulder with low clouds and clearer skies above:

- Open-Meteo historical GFS-model visibility <= 1,500 m;
- GFS low-cloud cover >= 55%;
- average GFS mid/high cloud cover <= 45%.

This is **not** an independent observation of a thermal inversion, summit visibility,
cloud-top elevation, or the classic sea-of-clouds landscape. Its validation metrics
measure ability to reproduce a **model-derived proxy**, not actual hiking outcomes.
A weather-model's visibility forecast is not observed ground truth. In particular,
**the proxy scores are not demonstrated calibrated real-world inversion chances**.

To actually validate and improve this application, collect timestamped, independently
observed fog/cloud-sea labels (Boulder + summit webcams, visibility observations,
manual photo review, etc.). Train against those via `--observations` below.
Document the observation protocol so labels are consistent.

## Install and run (macOS, Linux, Windows)

Python 3.11 or 3.12 is recommended. From the repo directory:

```bash
python3 -m venv .venv
source .venv/bin/activate              # Windows PowerShell: .venv\\Scripts\\Activate.ps1
python -m pip install -r requirements.txt
```

**Once per model update**, train locally using *one* of the following approaches.
The first uses experimental, modeled proxy labels. It downloads 2022–2025 weather
archives (several API requests, cached in `data/raw/`):

```bash
python -m inversion.train --start 2022-01-01 --end 2025-12-31 --allow-proxy-labels
```

Or train with independently observed event labels (preferred):

```bash
python -m inversion.train --start 2022-01-01 --end 2025-12-31 --observations data/observations.csv
```

The labels file has columns exactly `timestamp,observed_event`. Timestamps must be
ISO-8601 **with UTC offset** (Z recommended), one per observed hour; `0` = not
observed, `1` = observed. For example:

```csv
timestamp,observed_event
2025-10-20T12:00:00Z,1
2025-10-20T13:00:00Z,0
```

Those two example rows do NOT represent verified Boulder observations. **Do not use
example or generated data to make a purportedly validated trained model.**
Negative labels require a human/observation to actually verify absence; otherwise
leave the hour unlabeled. Observations are joined by UTC hour. A usable train/val/test
split must contain both classes in every period. Input errors, API gaps, insufficient
positive examples and unavailable pressure fields halt training with an explanation.

Train scripts produce:

```
models/xgb.json       # small XGBoost artifact
models/cnn.pt         # compact PyTorch weights and training normalization
models/manifest.json  # schema, target type, splits, calibration and held-out metrics
```

Then launch the app:

```bash
python -m uvicorn inversion.server:app --reload
```

Open **http://127.0.0.1:8000/**. The frontend must be served by the Python app;
opening `index.html` with `file://` will not run model inference. The interface
will report **model unavailable** rather than invent probabilities if you haven't
trained models yet or the external forecast API fails. Synthetic presets are clearly
marked demonstrations, not live forecasts.

### Publish a genuinely one-click runnable checkout

The default `.gitignore` excludes downloads and trained artifacts so you don't
accidentally commit large raw weather files or unreviewed pseudo-trained models.
Once you have **trained and reviewed** your artifacts, explicitly commit only the
small inference artifacts:

```bash
git add -f models/xgb.json models/cnn.pt models/manifest.json
git add .
git commit -m "Add evaluated local inversion models"
git push
```

After that, other users can install requirements and run the local web server
**without retraining**. GitHub does not automatically host or execute Python by
opening a plain HTML file; a local server is still needed. For distribution,
make sure the pretrained artifacts were built with supported package versions.

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

No automated test here claims actual forecast accuracy. Tests use **synthetic input
fixtures only**, check preprocessing, artifact reload and HTTP behavior. Do not
ship test-trained models as real predictions.

## Structure

```
inversion/
  config.py       # fixed feature schema / location / pressure levels
  weather.py      # live + historical GFS ingestion with archive caching
  features.py     # common training/inference feature and profile pipeline
  models.py       # XGBoost + CNN architectures, calibration, metrics
  train.py        # explicit labels, chronological train/val/test split
  predict.py      # load compatible saved models and run both
  server.py       # FastAPI /api/forecast and static dashboard
index.html        # existing visual app, adapted for model output
dashboard.js      # browser UI logic
science.html      # model limitations / meteorology
guide.html        # user instructions
tests/            # offline integrity smoke tests
models/           # optional distributable trained artifacts
data/raw/         # cached weather provider response, not tracked
```

## Scientific limitations / work before treating probabilities as reliable

1. **Observation target.** Define two *separate* outcomes: (a) thermal inversion,
   established by temperature profiles, and (b) low-cloud deck + clear mountaintop
   suitable for photography. The current proxy is only a stepping stone toward (b).
2. **Ground truth.** Pair archival *past forecasts* (at the correct forecast issue
   time / lead time) with independent observations. The Historical Forecast API
   stitches the first hours of model runs; it is **not** a historical 7-day-ahead
   forecast. Operational skill must be backtested using **Single Runs** or
   **Previous Runs** data at the intended lead time. Current held-out proxy metrics
   cannot substitute for this test.
3. **Geography and resolution.** GFS pressure fields are coarse (~25 km) relative
   to the Flatirons. It cannot resolve a local fog ceiling/terrain wake faithfully.
   A future system should use HRRR near-term, local surface stations, webcam labels,
   cloud-base/height data and terrain-aware features. High-res HRRR does not offer
   a full 7-day forecast; keep GFS for longer leads or make a model-specific ensemble.
4. **Vertical coordinate.** 850 hPa is commonly at/below Boulder's ground height.
   We use geopotential heights at 800/750/700/650/600 hPa, discard below-ground
   levels, and interpolate onto 25 **above-ground** levels. Sparse interpolation
   cannot create missing physical resolution. Temperature itself is not the same
   as stability: future features should consider potential temperature / moisture.
5. **Calibration and seasons.** This version uses Platt scaling on a held-out
   validation segment, but on proxy labels if trained with proxies. Report Brier,
   calibration curves and event precision on **real observations**, by season and
   forecast lead time. The final test period is never used for early stopping,
   calibration or hyperparameter choices.
6. **Cloud-top altitude is unknown.** Live mode correctly hides the original
   fabricated 6,700/7,500/8,300 ft ceiling and avoids claiming a summit is clear.
   The illustrative diagram still works in **synthetic presets only**.
7. **Missing data.** Incomplete pressure profiles are dropped; there is no
   silent zero imputation. The UI fails visibly rather than silently switching to
   generated predictions.
8. **License / terms.** Verify Open-Meteo data licensing and applicable fair-use
   restrictions if your project becomes commercial; credit Open-Meteo and NOAA.
   Tailwind/browser CDN assets need an internet connection unless bundled.

## Notes for future improvements

- Use a lead-time-specific validation pipeline before reporting actual forecasts
  as probabilities of success.
- Maintain separate models for 0–2 days and 3–7 days if the data supports it.
- Compare against a simple observational climatology baseline, not just
  whichever model looks best against self-generated pseudo labels.
- Add actual ground observations and a cloud top / summit sky-status estimator.
- The GFS parameter selection must be checked against the current Open-Meteo API:
  remote live and historical API availability **was not testable** in the
  offline authoring environment. Missing/renamed parameters produce explicit
  errors; adjust the shared schema and retrain if necessary.

Source documentation:
- https://open-meteo.com/en/docs/gfs-api
- https://open-meteo.com/en/docs/historical-forecast-api
- https://open-meteo.com/en/docs/previous-runs-api
- https://open-meteo.com/en/docs

## License

The original repository does not specify a license in the supplied snapshot.
Before distributing for contributions or reuse, choose and add an appropriate
open-source license. Review external weather-data terms separately.
