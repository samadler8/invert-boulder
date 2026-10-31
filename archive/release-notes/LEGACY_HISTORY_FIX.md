# Why October 30 at 7 AM showed only low-cloud scores

These are *legacy reconstructed* snapshots created with `hrrr-setup-index-v1` before mountain scenic calculations were introduced. The database stored numeric low-cloud scores and a few readings, but did not archive the full original GRIB features, cloud-layer metrics, or summit relative humidity. A scenic score cannot be recovered from the old snapshot alone.

The historical page previously treated any record as complete. This fix shows older reconstructed records as needing an **update**, while protecting the original immutable snapshots.

## Refresh one historical event using the website

Select the recorded target hour. Click **Fetch / update N forecast cutoff(s)**. This downloads *only* the out-of-date reconstructions for that one selected weather hour. Wait for the completion message and refresh the history cards. Older reconstructed rows are retained in SQLite; new scored rows are saved separately with the current heuristic version.

## Alternatively, use Terminal

While the selected target is still within the previous 48h:

```bash
python -m scripts.quicklook --past-event "2026-10-30 07:00" --past-offsets 6,12,18,24 --no-future --refresh-only
```

The command will now consider legacy reconstructed forecasts stale, not only absent forecasts. Normal `quicklook` without `--past-event` remains cache-first and does not force a mass redownload of old records.

## Interpret correctly

- The records are **reconstructed** by applying the current heuristic to previously issued NOAA HRRR forecasts. They are not proof that the website displayed the current scenic score before the event.
- Genuine **captured** historical predictions are never overwritten or passed off as new captures.
- If the newly reconstructed scenic score remains blank, HRRR's required atmospheric input may genuinely be absent. It is not necessarily an error; a valid current-version record won't trigger endless downloads.
- Each extra vintage requires HRRR archive network I/O. If retrieval fails, the old low-cloud score remains viewable.
