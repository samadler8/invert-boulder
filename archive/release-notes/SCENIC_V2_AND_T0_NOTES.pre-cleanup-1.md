# Boulder scenic v2 + historical T-0 + observed METAR

## What changed

1. The separate mountain scenic heuristic has **smooth continuous** middle/high cloud penalties. It does not force a zero just because one cloud layer is at 85–100%. The separate Boulder low-cloud heuristic keeps its six original factor weights.
2. Each recent historical target hour can compare **T-24, T-18, T-12, T-6, T-0** forecast vintages. The new T-0 means the latest issued HRRR forecast plausibly available at that time, **not** the observed conditions and **not** necessarily an F00 analysis.
3. A new independent **observed KBDU METAR** panel shows low ceiling, fog-like condition, visibility and cloud base when recorded. Fetch it with **Refresh actual airport report**, or `python -m scripts.refresh_observations --days 4`. An airport report does **not** verify the mountain view.
4. History shows large forecast-to-forecast swings in middle/high cloud coverage. New HRRR downloads also sample four nearby points from the *same* surface GRIB2 fields without fetching additional files; spread is reported as an optional **spatial disagreement diagnostic**, not an observation.
5. Both the scenic algorithm and stored predictions are versioned. Older snapshots remain intact; selecting an old reconstructed event offers an explicit upgrade rather than silently rewriting the historical score.

## Install the overlay

```bash
cd ~/github/invert-boulder
unzip -o ~/Downloads/invert-boulder-scenic-v2-t0-overlay.zip -d .
conda activate inversion312
python -m pytest -q
python -m uvicorn inversion.server:app --reload
```

In the website, choose a past hour and click **Fetch / update** to fill its five forecast vintages. Use **Refresh actual airport report** to request the independent IEM/METAR observations for that target date.

Alternatively, in a separate Terminal:

```bash
python -m scripts.quicklook --past-event '2026-10-30 08:00' \
  --past-offsets 24,18,12,6,0 --no-future --refresh-only
python -m scripts.refresh_observations --days 4
```

The `--past-event` shortcut is restricted to past 48 hours. If the selected date has aged out, use the more general `inversion.history backfill --local-time '...' --offsets 24,18,12,6,0` CLI and review historical results separately.

## Caveats

- All scenic scores remain **uncalibrated indices**, not event probabilities.
- Middle/high cloud coverage is not cloud optical depth or direct evidence of summit visibility.
- The HRRR pressure-profile humidity transition is a coarse indication of drying aloft, not a reliable cloud-top measurement.
- A reconstructed historical forecast is not proof the page displayed that number earlier. Historical issue-time availability uses a **two-hour assumed dissemination lag**.
- Older JSONL and SQLite snapshots have **no nearby-grid data**. The website will say unavailable; retrieving new model fields is optional.
- No change to the 40-hour ML training horizon, existing training data files, or model weights.
