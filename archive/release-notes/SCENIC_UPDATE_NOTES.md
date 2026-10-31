# Above-the-clouds scenic suitability update

The original low-cloud index can be **96/100 when the modeled sky is completely
cloudy above Green Mountain**. That low-cloud index is still useful but is not
an answer to the photography question.

This update introduces a separate, **uncalibrated 0–100 scenic suitability index**
for Green Mountain (8,133 ft) and First Flatiron (7,258 ft). The main gauge,
forecast-day cards, and first timeline mode now use the Green Mountain scenic
index, while the original low-cloud setup index remains visible beside it and
in a separate timeline mode. A machine-learning airport low-ceiling probability
remains separate when models have been trained.

Scenic suitability requires simultaneous:

- A meaningful low-cloud / fog setup near Boulder.
- A forecast cloud base near the Boulder valley, not already above the peaks.
- Forecast relative humidity falling toward drier air by **7,400 ft MSL**
  for Green Mountain (or by **6,900 ft** for First Flatiron), and dry air at
  and above the summit.
- **Little middle and high cloud coverage**. The high/medium cloud penalty is
  strong: 100% forecast high cloud -> scenic index 0 even for excellent fog
  near Boulder.

HRRR's generic `HGT:cloud top` value may represent high cloud at ~38,000 ft;
it **does not separately report the top of Boulder's low stratus**. Our
vertical relative humidity is only a physically motivated *proxy*, not a
verified low-cloud-top forecast. Index values are NOT calibrated event odds.
There are still no independent summit-clear observations in the training set.
The underlying HRRR pressure levels are sparse and only sample the KBDU-area
model grid point; this is not a 3D cloud-resolving summit forecast.

## Apply to existing local repo

Stop the HTTP server if running; stop any *active* HRRR downloader with Ctrl+C
before replacing code. Extract the overlay over your repo, then:

```bash
conda activate inversion312
python -m pytest -q
python -m scripts.explain_forecast --date 2026-10-31 --hour 6
python -m uvicorn inversion.server:app --reload
```

**No historical downloads, observation CSV regeneration, new dependencies,
or retraining are needed.** Your existing `data/hrrr_live.jsonl` already has
vertical relative-humidity profile, cloud base and mid/high cloud coverage.
The scorer uses the known KBDU station elevation for older caches that lack
model-grid terrain elevation, and discloses this approximation. Running
`python -m inversion.hrrr live --lead-hours 12,18,24,30,36,39` updates the
live cache and adds the HRRR grid-cell terrain height for future records.

The history database is *never overwritten*. Newly captured and reconstructed
vintages use a new heuristic version. Old saved scores remain intact and do not
retroactively acquire a scenic value. Re-running a past-event `backfill`
can obtain a versioned scenic reconstruction from archived HRRR if desired;
this is not proof the website showed that new number at the time.

NOAA HRRR documentation: https://www.nco.ncep.noaa.gov/pmb/products/hrrr/hrrr.t00z.wrfsfcf02.grib2.shtml
