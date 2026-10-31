"""One-command local past-48h / next-48h Boulder forecast dashboard.

Run: python -m scripts.quicklook
Or refresh a server already running: python -m scripts.quicklook --refresh-only

Download scope is deliberately sampled and bounded. `--past-step 1` and
`--future-step 1` enable denser sampling, at a correspondingly higher download
cost. Historical reconstructions are labeled as such, not as previously captured
website predictions. Does not touch the ML training dataset.
"""
import argparse
import webbrowser
from datetime import datetime, timedelta, timezone, time as clock_time
from pathlib import Path
from threading import Timer
from zoneinfo import ZoneInfo

from inversion.config import DATA_DIR, DISPLAY_MAX_LEAD_HOURS, TIMEZONE
from inversion.history import (DEFAULT_DB, backfill_event, history_view,
                               utc_str, as_utc)
from inversion.hrrr import load_jsonl, write_jsonl

LOCAL = ZoneInfo(TIMEZONE)
CACHE = DATA_DIR / 'quicklook_forecast_cache.jsonl'
LIVE = DATA_DIR / 'hrrr_live.jsonl'


def issue_cycle(now, availability_lag_hours=3):
    """Use an extended (00/06/12/18Z) issue time plausibly published already."""
    cutoff = as_utc(now) - timedelta(hours=availability_lag_hours)
    return cutoff.replace(hour=(cutoff.hour // 6) * 6, minute=0,
                          second=0, microsecond=0)


def hourly_targets(now, hours, step, *, future, dawn_hours=(5, 6, 7, 8, 9)):
    """UTC step-grid plus exact local morning targets, DST-aware."""
    now = as_utc(now)
    if not (1 <= step <= 12) or hours < 1:
        raise ValueError('Sampling step must be 1-12 hours')
    start = now.replace(minute=0, second=0, microsecond=0)
    grid = set()
    # Sample on fixed UTC clock boundaries for stability across reruns.
    for delta in range(-hours, hours + 1):
        target = start + timedelta(hours=delta)
        if (target > now if future else target <= now) and (target - now).total_seconds() <= hours * 3600:
            if (now - target).total_seconds() <= hours * 3600 and target.hour % step == 0:
                grid.add(target)
    local_day = now.astimezone(LOCAL).date()
    for d in range(-3, 4):
        day = local_day + timedelta(days=d)
        for hour in dawn_hours:
            local = datetime.combine(day, clock_time(hour), tzinfo=LOCAL)
            target = local.astimezone(timezone.utc)
            in_window = (now < target <= now + timedelta(hours=hours)) if future else (
                now - timedelta(hours=hours) <= target <= now)
            if in_window:
                grid.add(target)
    return sorted(grid)


def update_future(*, now, step=3, cache=CACHE, live=LIVE, fetcher=None,
                  lag_hours=3, dawn_hours=(5, 6, 7, 8, 9),
                  scratch=None, stop_after=None):
    """Fetch missing point forecasts with per-pair persistent cache, atomic live output."""
    from inversion.history import capture_published_live
    from inversion.hrrr import fetch_point
    fetcher = fetcher or (lambda init, lead, scratch: fetch_point(init, lead, scratch, transect=True))
    now = as_utc(now)
    init = issue_cycle(now, availability_lag_hours=lag_hours)
    targets = hourly_targets(now, 48, step, future=True, dawn_hours=dawn_hours)
    leads = sorted({int((target - init).total_seconds() // 3600) for target in targets
                    if (target - init).total_seconds() % 3600 == 0
                    and 0 <= (target - init).total_seconds() / 3600 < DISPLAY_MAX_LEAD_HOURS})
    saved = {(r['run_utc'], int(r['lead_hours'])): r for r in load_jsonl(cache)}
    rows = []
    fetched = 0
    failed = 0
    skipped = len(targets) - len(leads)
    print(f'Future: {len(leads)} forecast hours from HRRR {utc_str(init)} '
          f'(up to F48), {skipped} beyond available run horizon.', flush=True)
    for lead in leads:
        key = (utc_str(init), lead)
        if key in saved:
            rows.append(saved[key])
            continue
        if stop_after is not None and fetched >= stop_after:
            break
        try:
            print(f'  Fetch F{lead:02d} valid {utc_str(init + timedelta(hours=lead))}', flush=True)
            row = fetcher(init, lead, Path(scratch or (DATA_DIR / 'hrrr_tmp')))
            # Check the returned metadata before persisting it as a forecast.
            if row['run_utc'] != key[0] or int(row['lead_hours']) != lead:
                raise ValueError('Downloaded forecast initialization or lead mismatch')
            write_jsonl(cache, [row])
            saved[key] = row
            rows.append(row)
            fetched += 1
        except (Exception) as exc:
            # Continue at the next forecast hour, preserving prior successful rows.
            failed += 1
            print(f'  SKIPPED F{lead:02d}: {type(exc).__name__}: {exc}', flush=True)
    if rows:
        rows.sort(key=lambda row: row['timestamp'])
        stage = Path(str(live) + '.next')
        write_jsonl(stage, rows, mode='w')
        stage.replace(live)
        if live == LIVE:
            counts = capture_published_live(rows, published_at=datetime.now(timezone.utc),
                                            db_path=DEFAULT_DB)
        else:
            counts = {'heuristic_saved': 0, 'ml_saved': 0}
        print(f'  Future available: {len(rows)} hours; downloaded: {fetched}; '
              f'failed: {failed}; archive: {counts}', flush=True)
    else:
        print('  No new forecasts available; existing live file left untouched.', flush=True)
    return {'fetched': fetched, 'available': len(rows), 'failed': failed,
            'outside_horizon': skipped, 'run_utc': utc_str(init)}


def update_past(*, now, step=3, db_path=DEFAULT_DB, fetcher=None,
                dawn_hours=(5, 6, 7, 8, 9), stop_after=None, offsets=(6,)):
    """Retrospectively reconstruct an as-of-T-6h vintage only for missing hours."""
    now = as_utc(now)
    targets = hourly_targets(now, 48, step, future=False, dawn_hours=dawn_hours)
    attempted = 0
    saved = 0
    failures = 0
    print(f'Past: checking {len(targets)} target hours in the previous 48h.', flush=True)
    for target in targets:
        comparisons = history_view(db_path, now=now, window_hours=48,
                                   target=target, offsets=offsets)['comparisons']
        missing_offsets = tuple(r['hours_before_event'] for r in comparisons
                                if r['forecast'] is None)
        if not missing_offsets:
            continue
        if stop_after is not None and attempted >= stop_after:
            break
        attempted += 1
        try:
            result = backfill_event(target, offsets=missing_offsets, db_path=db_path,
                                    fetcher=fetcher)
            saved += sum(r['status'] == 'saved' for r in result)
        except Exception as exc:
            failures += 1
            print(f'  SKIPPED {utc_str(target)}: {type(exc).__name__}: {exc}', flush=True)
    print(f'  Past reconstructions saved: {saved}; errors: {failures}. '
          'Previously captured forecasts are preserved.', flush=True)
    return {'targets': len(targets), 'saved': saved, 'failed': failures}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--refresh-only', action='store_true',
                    help='Update saved data without launching another web server')
    ap.add_argument('--no-past', action='store_true',
                    help='Skip historical reconstruction and use existing saved history')
    ap.add_argument('--no-future', action='store_true',
                    help='Skip updating future forecasts; useful for offline review')
    ap.add_argument('--past-step', type=int, default=3,
                    help='Historical spacing in hours (default 3; 1 costs much more)')
    ap.add_argument('--future-step', type=int, default=3,
                    help='Forecast spacing in hours (default 3; 1 costs much more)')
    ap.add_argument('--max-new', type=int, default=None,
                    help='Optional cap on new downloads in each direction for quick testing')
    ap.add_argument('--past-offsets', default='6',
                    help='As-of vintages (e.g. 24,18,12,6,0); normal quicklook fetches T-6 only')
    ap.add_argument('--past-event', default=None,
                    help='Only reconstruct this one past Boulder-local hour, e.g. \"2026-10-30 08:00\"; use with --no-future --refresh-only')
    ap.add_argument('--no-browser', action='store_true',
                    help='Do not automatically open the dashboard in a browser')
    ap.add_argument('--port', type=int, default=8000)
    args = ap.parse_args(argv)
    now = datetime.now(timezone.utc)
    print('Boulder forecast quicklook: previous 48h and next 48h', flush=True)
    print('This command will retrieve selected NOAA HRRR fields unless disabled. '
          'Existing ML training data is not changed.', flush=True)
    from inversion.history import needs_reconstruction_upgrade
    try:
        offsets = tuple(int(x) for x in args.past_offsets.split(','))
    except ValueError:
        ap.error('--past-offsets must be a comma-separated list of hours')
    if not offsets or any(h < 0 or h >= 36 for h in offsets):
        ap.error('--past-offsets must be nonnegative, under 36 hours (0 = at event)')
    if not args.no_past:
        if args.past_event:
            local = datetime.fromisoformat(args.past_event.replace(' ', 'T'))
            if local.tzinfo is None:
                local = local.replace(tzinfo=LOCAL)
            target = local.astimezone(timezone.utc)
            if not (now - timedelta(hours=48) <= target <= now):
                ap.error('--past-event must be in the previous 48 hours')
            if target.minute or target.second or target.microsecond:
                ap.error('--past-event must be on an exact hour')
            view = history_view(DEFAULT_DB, now=now, window_hours=48, target=target,
                                offsets=offsets)
            missing = tuple(c['hours_before_event'] for c in view['comparisons']
                            if needs_reconstruction_upgrade(c['forecast']))
            print(f'Past selected target: {target.isoformat()}, missing cutoffs: {missing}', flush=True)
            if missing:
                result = backfill_event(target, offsets=missing, db_path=DEFAULT_DB)
                print('Archive reconstruction:', result, flush=True)
        else:
            update_past(now=now, step=args.past_step, stop_after=args.max_new,
                        offsets=offsets)
    if not args.no_future:
        result = update_future(now=now, step=args.future_step, stop_after=args.max_new)
        if result['available'] == 0:
            print('No forecasts from this HRRR cycle; trying preceding 6-hour cycle once.',
                  flush=True)
            update_future(now=now, step=args.future_step, stop_after=args.max_new,
                          lag_hours=9)
    print(f'Dashboard: http://127.0.0.1:{args.port}', flush=True)
    if args.refresh_only:
        print('Reload the already-running dashboard in the browser to see updates.')
        return
    if not args.no_browser:
        Timer(2.0, lambda: webbrowser.open(f'http://127.0.0.1:{args.port}')).start()
    import uvicorn
    uvicorn.run('inversion.server:app', host='127.0.0.1', port=args.port,
                log_level='info')


if __name__ == '__main__':
    main()
