# Boulder Inversion Tracker

A public-data weather explorer for Boulder, the First Flatiron (7,258 ft), and Green Mountain (8,133 ft). Focus: low cloud over Boulder with clear conditions above summit height.

**No machine learning is required or executed.** The former XGBoost/CNN research experiment is preserved in [`archive/machine-learning/`](archive/machine-learning/). The active service never reads `models/` or trains weights.

## Install

For an **overlay onto your existing checkout**, run `python -m scripts.archive_legacy_ml` immediately after unzipping; this moves old active ML modules into the archive.


```bash
conda activate inversion312
python -m pip install -r requirements.txt -r requirements-hrrr.txt
python -m uvicorn inversion.server:app --reload
```

Open http://127.0.0.1:8000 and use **Refresh everything**, or run `python -m scripts.quicklook --refresh-only` in a second terminal. The app shows cached forecasts immediately; HRRR downloads may take some time.

## Features

- Hand-designed 0–100 **low-cloud setup** and **above-the-clouds scenic** indices; **neither is a probability**.
- Separate middle/high-cloud penalties, humidity profiles and forecast disagreements.
- Sunrise/sunset, twilight and sliding time-lapse mountain/cloud illustration (schematic, not measured cloud top).
- Boulder-to-foothills HRRR spatial transect; nearby sites may share model grid cells.
- Historical 24/18/12/6/0-hour forecast comparisons; reconstructed runs clearly marked.
- Independent KBDU METAR observations, **not** proof of mountain summit visibility.
- NOAA numerical HRRR retrieval via Herbie and ecCodes.

## Refresh

```bash
python -m scripts.quicklook --max-new 3 --refresh-only
```

Or use the one-button in-page refresh; selected historical vintages are prioritized and saved on disk. The full CLI is `python -m scripts.quicklook --help`.

## Tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

## Data safety

Keep `data/` and any `models/` artifacts from your previous checkout. The replacement ZIP does **not** include your local data; `.gitignore` keeps caches and prediction history out of Git. Historical SQLite rows retain old ML columns for backward compatibility but active forecasts never populate them. **Old ML training files are archived, not erased.**

## Scientific limitations

HRRR is about 3 km horizontally; the vertical profile has limited resolution. Near-surface inversions, fog depth, and clear summits cannot be confirmed from the index alone. The HRRR whole-column cloud-top field can be high cirrus and is not the top of a Boulder fog deck. Compare multiple runs and nearby grid cells, and check camera/METAR reports before hiking.

See [FOOTHILLS_TRANSECT.md](FOOTHILLS_TRANSECT.md) and [guide.html](guide.html).
