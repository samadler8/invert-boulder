# Boulder HRRR low-cloud / scenic forecaster (experimental)

## Inspect five forecast vintages plus actual KBDU observations

The default `python -m scripts.quicklook` reconstructs **T−6 only** for each past hour
(to keep initial downloads manageable). The history panel deliberately shows
T−24, T−18, T−12, T−6 and T−0; missing cards do **not** mean the forecast was zero.

**Recommended:** click a past hour in **Two days back**, then click **Fill missing
forecast cutoffs** in the **Past 48 hours · forecast history** section. The
website fetches only the selected weather hour's missing runs (up to five),
shows progress and reloads the five detailed cards. The cards include Green
Mountain, First Flatiron and Boulder low-cloud indices, cloud layers, surface
humidity, near-surface temperature gradient, wind, cloud-base and summit RH,
plus the saved HRRR run and source inventory links. This button explicitly
contacts NOAA; normal GET/reload requests remain offline/cache-only.

Equivalent command-line operation, useful if the server is not running:

```bash
python -m scripts.quicklook --past-event '2026-10-30 08:00' \
  --past-offsets 24,18,12,6,0 --no-future --refresh-only
```

The time is **Boulder local** (America/Denver), not UTC. Change it to a past
hour **within the last 48 hours**; older archived events require a separate
manual backfill workflow. The command skips already available vintages. Do not
run `--past-offsets 24,18,12,6,0` for **every** past target unless you really
want many more GRIB downloads.

A **captured** prediction was saved by the app before the cutoff. A
**reconstructed** one was generated later from an HRRR-issued forecast using
an **assumed** two-hour publication lag and today's heuristic; it is not proof
that the same calculation was shown on the website then. Scores are
uncalibrated **indices**, not event probabilities.

## One-command website: past two days + next two days

**Recommended:** instead of manually downloading forecasts and starting a server
in separate Terminal sessions, run:

```bash
conda activate inversion312
cd ~/github/invert-boulder
python -m scripts.quicklook
```

It reconstructs a **sampled** 48-hour history, downloads **sampled** extended
HRRR forecasts up to the available 48-hour issue-time lead, and opens the local
site. Subsequent runs reuse the historical forecast ledger and point cache.
While the site is already running, use `python -m scripts.quicklook --refresh-only`
and click **Reload saved predictions**. For an initial small connectivity test,
use `python -m scripts.quicklook --max-new 3 --refresh-only`.

Read **[QUICKLOOK.md](QUICKLOOK.md)** for exact options, download costs,
publication-time assumptions, limitations, and offline viewing. The 48-hour
**heuristic display** does not extend the still-40-hour **ML training contract**.


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

## Scenic goal: LOW clouds over Boulder, CLEAR summits and upper sky

**The main gauge now measures a separate uncalibrated Green Mountain scenic
suitability index**; the original low-cloud/inversion setup index is still
shown independently. The previous low-cloud index could reach 96/100 even
when HRRR forecast 100% HIGH clouds. That was a wrong optimization target for
above-cloud hiking and photography, even if a reasonable low-cloud proxy.

`inversion/scenic.py` addresses the full intended configuration using the
**existing HRRR** (no additional GRIB fields or downloads necessary):

1. Low cloud near the Boulder valley and a cloud base near 5,400 ft MSL.
2. Evidence that the low-cloud deck *might* end within approximately 1,000–2,000
   ft above Boulder. Specifically, use low-level RH-profile drying by
   **7,400 ft MSL for Green Mountain**, or by **6,958 ft MSL for First Flatiron**.
3. Favor dry air **at and above** each target summit (8,133 / 7,258 ft).
4. **Penalize middle and high cloud** above the valley, with lower scenic
   scores when these layers are overcast. 100% high-cloud cover now strongly lowers scenic suitability, but does not force a hard zero by itself.

The scenic index is a deterministic *product* of these necessary ingredients,
not a calibrated 0–100% probability. Its RH-derived drying height is **not a
predicted or observed cloud top**. HRRR's generic single cloud-top field can
refer to upper cloud (such as a 37,960 ft top), and MUST NOT be confused with
the top of the low cloud covering Boulder. Pressure levels are too coarse to
resolve all shallow inversions. We currently sample one KBDU-area grid point,
not the actual Flatirons summits. No webcam/summit outcome validation exists.
If important scenic inputs are unavailable, the scorer reports N/A rather
than pretending a missing cloud top means clear skies.

**For existing data:** No rerun of archived observations, history collection,
XGBoost/CNN training, or GRIB downloading is necessary. Existing HRRR JSONL
records already contain mid/high cloud cover, cloud base, and RH profiles.
New live forecasts additionally store model-grid terrain elevation; old
caches use the nearby KBDU station elevation transparently. Old forecast
history snapshots remain unmodified. Reconstructed versions use a new
heuristic version and are explicitly labeled reconstructions.

For tomorrow morning, inspect both indices and all supporting measurements:

```bash
python -m scripts.explain_forecast --date 2026-10-31 --hour 6
python -m uvicorn inversion.server:app --reload
```

Reference: [NOAA HRRR surface forecast GRIB field inventory](https://www.nco.ncep.noaa.gov/pmb/products/hrrr/hrrr.t00z.wrfsfcf02.grib2.shtml).

## Heuristic now, observation-trained ML later

The website **works before training XGBoost or the CNN**. The deterministic,
transparent heuristic in `inversion/heuristic.py` assigns a **0-100 setup index**
using six forecast ingredients: low-level thermal stability (29%), near-surface
moisture (24%), HRRR low clouds (20%), light wind (12%), shallow modeled
boundary layer (10%), and reduced forecast visibility (5%). These are
**hypothesized weights, not learned coefficients**. The score is NOT a
probability, not an observed inversion, and not a verified above-clouds event.
It is useful for ranking forecast hours; validation/tuning comes later.

To see a real heuristic today, **without waiting for historical training**:

```bash
conda activate inversion312
cd ~/github/invert-boulder
python -m inversion.hrrr live --lead-hours 12,18,24,30,36,39
python -m uvicorn inversion.server:app --reload
```

Open <http://127.0.0.1:8000>. `/api/forecast` serves real HRRR heuristic
scores from `data/hrrr_live.jsonl` even when `models/manifest.json` does not
exist. `/api/health` reports cache/model availability. It does *not* auto-fetch
new NOAA data on a browser refresh. To update weather data, rerun `hrrr live`
with a second Terminal; collecting the historical training samples is
independent and can continue in its own Terminal.

Once trained compatible model weights exist, the same page **retains the
heuristic** and displays a separate calibrated/experimental ML probability for
**an observed KBDU low ceiling (or fog target)**. Only forecast leads seen in
training receive an ML probability. A mountain's elevation relative to the
HRRR *modeled* cloud-top field is shown as a diagnostic, **not** a summit-clear
probability (cloud top may include upper cloud layers or be inaccurate).

The chart can switch between the **Green Mountain scenic index**, the original **low-cloud setup index**, and modeled low-cloud coverage, none of which is an ML probability. The ML card
shows the independent XGBoost, CNN, and ensemble probabilities when available.
Synthetic presets remain labeled and separate from real HRRR data.

## Past 48 hours: forecasts at T-24, T-18, T-12, T-6, T-0 plus independent METAR

The site contains a **Past 48 hours · forecast history** panel. Pick an
actual past **forecast target hour** (e.g. 07:00 Mountain Time) and see the
stored heuristic and optional ML outputs at 24, 18, 12 and 6 hours before,
plus the latest HRRR forecast plausibly available at the event time (T-0). Each entry displays the relevant **HRRR initialization time**,
forecast lead, score, and provenance. Reconstructed vintages use a different model initiation per offset; an older reconstructed forecast does not satisfy later missing cutoffs. Captured records display what was actually saved by the cutoff.

### The immutable local ledger

`data/forecast_history.sqlite3` is an ignored SQLite database, not checked
into GitHub. The `python -m inversion.hrrr live` command now automatically
archives the entire **successfully published** forecast cache, even if you
don't open the website. The `/api/forecast` endpoint also archives the values
actually computed for browser requests, including available ML probabilities.
The *captured* timestamp is the point at which the app saved/published the
prediction. We can't prove someone opened the page, only what the app had
saved by that time. New ML model versions and heuristic versions never
retroactively overwrite old snapshots. History remains readable if today's
live HRRR download fails.

To check the ledger:

```bash
python -m inversion.history status
```

**The Mac must actually collect forecasts over time.** Merely running the
FastAPI server doesn't fetch new HRRR data. For a manual collection:

```bash
python -m inversion.hrrr live \
  --lead-hours 12,18,24,30,36,39 \
  --morning-hours 5,6,7,8,9
```

The extra `--morning-hours` selects exact Boulder local dawn hours within the
current HRRR issue-time horizon, so the site can later compare predictions
for 05:00, 06:00, 07:00, 08:00, and 09:00. This downloads *additional* HRRR
run/lead pairs. For this short-term local site, selecting target hours is
preferable to downloading every model hour.

**Optional scheduling on a Mac:** From the active `inversion312` environment,
run:

```bash
python -m scripts.history_autorefresh
launchctl bootstrap "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/org.invertboulder.hrrr-history.plist"
```

The first command writes a macOS LaunchAgent plist using the **currently
running Python interpreter**, and the second enables it. It runs at load and
approximately every six hours while macOS is awake, downloads selected HRRR
leads and dawn hours, and archives them locally. This transfers weather data
regularly, so install it only if you want recurring downloads. Logs go into
`data/history_refresh.log` and `data/history_refresh_errors.log`. To disable:

```bash
launchctl bootout "gui/$(id -u)" \
  "$HOME/Library/LaunchAgents/org.invertboulder.hrrr-history.plist"
```

If the lid is closed or internet unavailable, scheduled runs can be missed.
The app **cannot** claim to have captured forecasts it never downloaded.
The database remains on your laptop; running the website on GitHub Pages or
another remote server won't automatically read your local SQLite file.

### Investigate this morning, even if nothing was saved at the time

Archived HRRR **issued** forecasts permit a *retrospective reconstruction*.
For example, to explore the October 30, 2026 morning event around 7 AM in
Boulder (adjust the local date/time as needed):

```bash
python -m inversion.history backfill --local-time "2026-10-30 07:00"
python -m inversion.history status
```

This retrieves up to four historic HRRR run/lead pairs selected as plausibly
available at T-24, T-18, T-12, T-6 and T-0. A **two-hour archive dissemination lag is
assumed for run selection, not verified**. The current heuristic is applied to
those old forecast fields and each result is explicitly labeled
**RECONSTRUCTED**, never **CAPTURED**. It therefore answers *what today's
heuristic would have scored using those archived issued forecasts*, **not**
what your webpage definitely displayed on those dates. If the GRIB archive
is unavailable for a selected cycle, the backfill will report an error.

Start the local server as usual and select the 7 AM event in the history
panel. The site only shows events from the **last 24 hours**, even though
the SQLite ledger can retain historical forecasts for longer. You can backfill
any earlier event, but it won't appear in the last-24h website view.

The index (0–100) is **not** a probability, and neither an airport low ceiling
nor an HRRR inversion signal proves that the actual Boulder sea-of-clouds
scene occurred. Compare with your observations and nearby METARs if you want
to assess the event scientifically.

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

Live heuristic coverage may include 12/18/24/30/36/39-hour leads, while ML
probabilities are limited to trained lead hours. The display is **sparse**
(not a full hourly prediction). Collect a recent extended cycle:

```bash
python -m inversion.hrrr live --lead-hours 12,18,24,30,36,39
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
- The public HRRR indexes expose the 13 selected surface fields and 25 pressure fields.
  Your first real eight-sample historical extraction succeeded on a Mac; archive-specific
  download/caching failures may still occur and must not be silently skipped.

References: [NOAA HRRR](https://rapidrefresh.noaa.gov/hrrr/),
[Herbie documentation](https://herbie.readthedocs.io/en/latest/),
[Iowa Mesonet METAR download](https://mesonet.agron.iastate.edu/request/download.phtml).

## Explain each heuristic score with actual HRRR readings

The live **Heuristic: forecast setup index** card now shows **Why this score?**
for the exact selected forecast valid hour. It lists six transparent factors,
including the raw HRRR model reading, the 0–100 factor score, its hand-selected
weight, and the actual weighted points earned. E.g., the maximum possible
stability contribution is **29 points**, moisture **24**, low clouds **20**,
wind **12**, mixing-layer height **10**, and visibility **5**. The contributions
are summed and rounded to create the published 0–100 index.

A reading of **96/100 does not mean a 96% chance of an inversion**. HRRR
humidity, low-cloud and visibility forecasts are correlated; the v1 weights can
therefore reinforce the same model error. The near-surface stability proxy also
uses a coarse vertical HRRR profile. We deliberately have not tuned the formula
to a single observed inversion event.

The same card links to the exact NOAA AWS **surface and pressure-level `.idx`
inventory files** for the selected HRRR initialization time and forecast lead.
Those inventories prove what forecast products were available, and identify
model variables and GRIB byte ranges; **they do not themselves show the extracted
numeric KBDU grid-cell readings**. The numeric point values are displayed in
our score panel and were extracted by the application's ecCodes parser. The
card also links to [NOAA HRRR documentation](https://rapidrefresh.noaa.gov/hrrr/).

To audit the highest-scoring hours from your local live cache in Terminal:

```bash
python -m scripts.explain_forecast --top 8
```

To inspect **October 31, 2026** near sunrise (if those forecast hours are
present in your live cache):

```bash
python -m scripts.explain_forecast --date 2026-10-31 --hour 7
```

Or pick another local hour or date. To get more morning hours in the cache, run:

```bash
python -m inversion.hrrr live --lead-hours 12,18,24,30,36,39 --morning-hours 5,6,7,8,9
```

Saved **new** forecast history snapshots contain the entire explanation and
source links. Open **Why this historical score?** in a T-24/T-18/T-12/T-6/T-0
comparison card. Older database snapshots retain their original scores but may
lack raw values; the site explicitly says that their unavailable inputs cannot
be reconstructed from the saved snapshot. Re-running the live cache doesn't
rewrite an older snapshot or retrospectively claim that a forecast was captured.



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


## Interactive 48-hour weather explorer (new)

The website has a **timeline slider** and previous/next/play buttons for all
**actually downloaded forecast valid hours**. Unlike a smooth animation, the
slider never interpolates hypothetical HRRR hours. The atmospheric illustration
shows low-cloud extent *schematically* (opacity derived from HRRR `LCDC`),
middle/high cloud amounts and an optional dashed **RH drying transition**.
That line is **not** a verified cloud top, and no summit clearance is observed.
Forecast views remain available only for cached forecast hours.

The displayed target elevations used in the actual scenic calculation are now
**7,258 ft MSL First Flatiron** and **8,133 ft MSL Green Mountain**. This
revisions the scenic method as `hrrr-scenic-suitability-v3-precise-elevations`;
older archived versions are preserved in SQLite. The site also shows a broad
set of existing forecast variables without requesting more GRIB fields:
low/middle/high clouds, temperature, dew point, humidity, 300 m warming,
10 m wind, modeled visibility, PBL height, cloud base, whole-column cloud top,
RH drying transition, summit-level humidity and neighboring-grid spread.

The `/api/solar?date_local=YYYY-MM-DD` endpoint calculates, without network
requests, approximate Boulder sunrise, sunset, civil twilight and ±6°-sun-angle
photographic golden hour. All times display in `America/Denver`, including
mountain daylight-saving changes. Horizon and refraction calculations don't
account for the actual Flatirons blocking the sun, so the time of **visible**
sunrise while hiking may be later.

Start the existing server and open the local site:

```bash
conda activate inversion312
python -m uvicorn inversion.server:app --reload
```

Click **Refresh everything** to update weather and selected historical forecasts
without restarting the server. The time slider uses those locally cached
forecasts and creates no new NOAA requests. For a manual update of all
historical hours, use the separate `quicklook` command on purpose; a routine
page load does not start a large backfill.
