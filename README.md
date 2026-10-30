# Boulder HRRR 40-hour low-cloud predictor (experimental)

This version supersedes the earlier Open-Meteo GFS 72-hour code. It trains on
**original NOAA HRRR issued forecast runs** paired with **independent Boulder
Municipal Airport (KBDU) METAR observations**. The default binary target is a
**BKN/OVC/VV ceiling at or below 1,000 feet AGL at the airport**, not an actual
thermodynamic inversion or a proven clear mountain summit. The dense-fog label
is retained as a separate, much rarer training option.

Models: XGBoost on tabular HRRR fields, 1D CNN on four vertical channels,
independent regression of **reported cloud BASE** (not cloud top). The airport
is a proxy for the Flatirons; model forecast cloud-base/top heights are predictors,
not validated outcomes. The website explicitly does **not** claim mountain clearance.

## 0. Free space / download cautions

- **Recommended free disk space: 25–40 GB** on Apple Silicon, although a small
  test can work with around 10–15 GB free. A Conda/PyTorch/Herbie environment is
  often 2–6 GB; temporary indexed GRIB subsets are ordinarily much smaller than
  whole HRRR files, and the final point JSONL/models are small.
- **Internet transfer is the larger risk**: each HRRR forecast sample downloads
  selected GRIB messages from both `sfc` and `prs` products. It may transfer tens
  of MB per sample; thousands of samples can consume tens to hundreds of GB in
  total, depending on the subset and archive. **Do not download whole HRRR GRIBs**
  (full CONUS pressure product can approach ~400+ MB per forecast hour).
- The script DELETES each temporary subset after reading the single point and
  stores only compact JSONL samples. Caching raw data is not needed.
- Default `collect` downloads **at most eight** new forecast pairs each invocation.
  `--all` deliberately opts into a potentially very large multi-day download.

## 1. Merge this repository ZIP into your existing local repo

```bash
cd ~/github/invert-boulder
git status --short                      # Save/commit any work before overwrite
git switch -c feature/hrrr-40h
unzip -o ~/Downloads/invert-boulder-hrrr-40h.zip -d .
```

If ZIP is in another folder, replace its path. Do not delete your existing
`data/observed_bdu.csv`; the new data uses a different filename.

## 2. Dependencies: use your working Python 3.12 Conda environment

```bash
conda activate inversion312
conda install -c conda-forge herbie-data python-eccodes -y
python -m pip install -r requirements-dev.txt
python -c "from herbie import Herbie; import eccodes, xgboost, torch; print('ready')"
python -m eccodes selfcheck
python -m pytest -q tests/test_pipeline.py
```

`requirements-hrrr.txt` is available for pip-only installation; the Conda
commands above are preferred for native GRIB dependencies on macOS.

## 3. Retrieve a longer history of independent KBDU observations

```bash
python -m inversion.observations \
  --start 2018-07-13 --end 2026-10-20 \
  --output data/observed_bdu_2018_2026.csv
```

The new observation CSV contains both `observed_low_ceiling` and `observed_fog`
plus reported cloud base when present. Unknown sky conditions remain unlabeled.
This observation download does not download HRRR data.

## 4. Inspect the HRRR archive without GRIB download

```bash
python -m inversion.hrrr inspect --date 2025-01-15 --fxx 36
```

You should see selected `sfc` and `prs` inventory entries for the requested
forecast. If any required field is missing or the archive is unavailable,
stop and inspect the error before the bulk download.

## 5. Download a tiny real-world test (eight forecast samples)

```bash
python -m inversion.hrrr collect \
  --start 2025-01-15 --end 2025-01-17 \
  --run-hour 0 --lead-hours 24,30,36,39 \
  --max-pairs 8 --output data/hrrr_samples.jsonl
```

The downloader extracts nearest model grid point to KBDU (~40.0394,-105.2250),
removes temporary large subsets, and appends a row to `data/hrrr_samples.jsonl`.
Rerunning exactly the same command skips already completed run/lead pairs.

Check what you downloaded:

```bash
python -m scripts.data_status \
  --features data/hrrr_samples.jsonl \
  --observations data/observed_bdu_2018_2026.csv

du -sh data/* 2>/dev/null
df -h .
```

> **Live archive integration caveat:** the code and offline tests were checked
> without live NOAA access. The first indexed-HRRR download on your Mac is a
> necessary integration test; GRIB inventory naming/availability can vary by
> year. Don't run `--all` until the 8-sample test completes successfully.

## 6. Expand to one winter, then to more years

One winter, after the 8-sample test succeeds:

```bash
python -m inversion.hrrr collect \
  --start 2024-12-01 --end 2025-02-28 \
  --run-hour 0 --lead-hours 24,30,36,39 \
  --all --output data/hrrr_samples.jsonl
```

Older HRRR runs before December 2, 2020 include lead hours through 36, not 39.
The tool automatically skips these unavailable historical 39-hour forecasts.

Additional winters (repeat with different years):

```bash
python -m inversion.hrrr collect \
  --start 2023-12-01 --end 2024-02-29 \
  --run-hour 0 --lead-hours 24,30,36,39 \
  --all --output data/hrrr_samples.jsonl
```

Use several winters and some shoulder seasons before interpreting validation
probabilities. A full eight-year daily 3/4-lead archive can be **thousands of
samples and a very large cumulative internet download**. Build incrementally.

## 7. Train independently observed KBDU low-ceiling classifier

```bash
python -m scripts.data_status \
  --features data/hrrr_samples.jsonl \
  --observations data/observed_bdu_2018_2026.csv

python -m inversion.train \
  --features data/hrrr_samples.jsonl \
  --observations data/observed_bdu_2018_2026.csv \
  --target low_ceiling
```

This trains XGBoost and the vertical-profile CNN and writes
`models/xgb.json`, `models/cnn.pt`, and `models/manifest.json`, with held-out
calibration and evaluation metrics. If fewer than three **distinct positive
calendar days** occur in train, validation, or test, training refuses to make a
probability model. Fetch more periods rather than oversampling one event.

If you want to train **only the cloud-base regression** while building the
classifier dataset:

```bash
python -m inversion.train \
  --features data/hrrr_samples.jsonl \
  --observations data/observed_bdu_2018_2026.csv \
  --base-only
```

`--target fog` trains the rarer strict visibility/fog outcome if enough
independent events are available. Do not assume it can be trained immediately.

## 8. Prepare a sparse live HRRR forecast, then open the website

Training samples are at 24/30/36/39-hour leads, so the first live display is
**sparse**, not a full hourly chart. Collect a recent extended cycle:

```bash
python -m inversion.hrrr live --lead-hours 24,30,36,39
python -m uvicorn inversion.server:app --reload
```

Open <http://127.0.0.1:8000>. To refresh underlying HRRR data, rerun the
`hrrr live` command in another Terminal; the website refresh button rereads
that cache. We intentionally do not hide a large GRIB download inside an HTTP
request. Forecast horizon is measured **from issue time** (f00–f39), so the
remaining forecast horizon from the current clock is shorter.

## 9. Publish safely

```bash
git add .
git status --short
git commit -m "Add HRRR archive point extractor and observed low-ceiling training"
git push -u origin feature/hrrr-40h
```

`data/*.csv`, `data/*.jsonl`, `data/hrrr_tmp`, and generated models are ignored
by default. Only publish model artifacts after separately checking scientific
skill, licenses, model compatibility, and commit size. Do not commit full GRIB
files. A future release can explicitly commit validated weights for one-command
local inference.

## Honest limitations

- NOAA HRRR model grid values are not exact point measurements; steep terrain
  adds representativeness error even at 3 km grid spacing.
- KBDU METAR cloud-base is not cloud-top. The HRRR predicted cloud-top field
  is an **input**, not independently verified truth.
- The CNN uses four variables at five pressure levels, interpolated to 25 heights; this is not 25
  independent observations and is not a spatial CNN.
- The current training sample recipe focuses on 24–39 hour forecast leads;
  the model **must not** be used at untrained leads without fresh validation.
- Calendar-day grouping and sparse-hour rendering are provisional. A denser
  operational forecast would require training and downloading more leads.
- The public HRRR indexes expose the 13 selected surface fields and 25 pressure fields;
  a real sample download and extraction still need validation on your Mac.

References: [NOAA HRRR](https://rapidrefresh.noaa.gov/hrrr/),
[Herbie documentation](https://herbie.readthedocs.io/en/latest/),
[Iowa Mesonet METAR download](https://mesonet.agron.iastate.edu/request/download.phtml).
