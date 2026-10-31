"""Forecast-vintage ledger: captured predictions vs retrospectively reconstructed HRRR.

The SQLite ledger records the prediction at ingestion time so changing code/weights
later does not rewrite the historical display. The reconstruct command downloads
archived *issued* HRRR forecasts, but those results were NOT actually captured or
necessarily displayed by the website at the historical cutoff.

Usage:
    python -m inversion.history backfill --local-time '2026-10-30 07:00'
    python -m inversion.history status
"""
import argparse
import csv
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import DATA_DIR, MAX_LEAD_HOURS, DISPLAY_MAX_LEAD_HOURS, TIMEZONE
from .heuristic import evaluate, VERSION as HEURISTIC_VERSION
from .scenic import VERSION as SCENIC_VERSION
from .opportunity import evaluate_opportunity

DEFAULT_DB = DATA_DIR / 'forecast_history.sqlite3'
DEFAULT_OFFSETS = (24, 18, 12, 6, 0)
# Illustrative safety margin when retrospectively selecting a forecast; not
# proof of when HRRR forecast files were actually publicly available.
ARCHIVE_ASSUMED_LAG_HOURS = 2


def as_utc(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if value.tzinfo is None:
        raise ValueError('Datetime needs a timezone offset')
    return value.astimezone(timezone.utc)


def utc_str(value):
    return as_utc(value).isoformat(timespec='seconds').replace('+00:00', 'Z')


def connect(path=DEFAULT_DB):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout = 30000')
    db.execute('PRAGMA journal_mode = WAL')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS predictions (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          valid_utc TEXT NOT NULL,
          run_utc TEXT NOT NULL,
          lead_hours INTEGER NOT NULL,
          origin TEXT NOT NULL CHECK(origin IN ('captured', 'reconstructed')),
          captured_at_utc TEXT NOT NULL,
          heuristic_version TEXT NOT NULL,
          scenic_version TEXT NOT NULL DEFAULT '',
          ml_model_version TEXT NOT NULL DEFAULT '',
          prediction_json TEXT NOT NULL,
          UNIQUE(valid_utc, run_utc, origin, heuristic_version, scenic_version, ml_model_version)
        );
        CREATE INDEX IF NOT EXISTS idx_history_valid ON predictions(valid_utc);
    ''')
    if 'scenic_version' not in {row[1] for row in db.execute('PRAGMA table_info(predictions)')}:
        # One-time lossless migration of the original unique key. Previously,
        # a new scenic score with identical low-cloud weights couldn't coexist
        # with its archived predecessor. Existing rows and IDs are preserved.
        with db:
            old = db.execute('SELECT * FROM predictions').fetchall()
            db.execute('''CREATE TABLE predictions_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                valid_utc TEXT NOT NULL, run_utc TEXT NOT NULL,
                lead_hours INTEGER NOT NULL,
                origin TEXT NOT NULL CHECK(origin IN ('captured','reconstructed')),
                captured_at_utc TEXT NOT NULL,
                heuristic_version TEXT NOT NULL,
                scenic_version TEXT NOT NULL DEFAULT '',
                ml_model_version TEXT NOT NULL DEFAULT '',
                prediction_json TEXT NOT NULL,
                UNIQUE(valid_utc, run_utc, origin, heuristic_version, scenic_version, ml_model_version)
            )''')
            for item in old:
                frozen = json.loads(item['prediction_json'])
                old_scenic = str(frozen.get('scenic_version') or '')
                db.execute('''INSERT INTO predictions_new
                    (id, valid_utc, run_utc, lead_hours, origin, captured_at_utc,
                     heuristic_version, scenic_version, ml_model_version, prediction_json)
                    VALUES (?,?,?,?,?,?,?,?,?,?)''',
                    (item['id'],item['valid_utc'],item['run_utc'],item['lead_hours'],
                     item['origin'],item['captured_at_utc'],item['heuristic_version'],
                     old_scenic,item['ml_model_version'],item['prediction_json']))
            db.execute('DROP TABLE predictions')
            db.execute('ALTER TABLE predictions_new RENAME TO predictions')
            db.execute('CREATE INDEX idx_history_valid ON predictions(valid_utc)')
    return db


def compact_prediction(row, predicted=None):
    """Freeze computed values, not just inputs, so future code cannot alter history."""
    heur = evaluate(row)
    out = {**heur, **evaluate_opportunity(row, heur),
           'lowClouds': row.get('observables', {}).get('lowClouds'),
           'rh': row.get('observables', {}).get('rh'),
           'windSpeed': row.get('observables', {}).get('windSpeed'),
           'tempDelta': row.get('observables', {}).get('tempDelta'),
           'ml_probability': None, 'xgb_probability': None,
           'cnn_probability': None, 'event': None}
    # Legacy SQL/JSON fields remain null in new forecasts for schema compatibility.
    return out


def save_prediction(row, *, origin='captured', captured_at=None, db_path=DEFAULT_DB,
                    predicted=None, ml_model_version=''):
    if origin not in ('captured', 'reconstructed'):
        raise ValueError('origin must be captured or reconstructed')
    valid = as_utc(row['timestamp'])
    run = as_utc(row['run_utc'])
    lead = int(row['lead_hours'])
    if not 0 <= lead < DISPLAY_MAX_LEAD_HOURS or valid - run != timedelta(hours=lead):
        raise ValueError('Inconsistent HRRR run and valid-time timestamp')
    captured_at = utc_str(captured_at or datetime.now(timezone.utc))
    computed = compact_prediction(row, predicted)
    with connect(db_path) as db:
        result = db.execute('''
          INSERT OR IGNORE INTO predictions
          (valid_utc, run_utc, lead_hours, origin, captured_at_utc,
           heuristic_version, scenic_version, ml_model_version, prediction_json)
          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (utc_str(valid), utc_str(run), lead, origin, captured_at,
              computed['heuristic_version'], computed.get('scenic_version', ''), ml_model_version,
              json.dumps(computed, allow_nan=False)))
        return result.rowcount == 1


def capture_published_live(rows, *, published_at=None, db_path=DEFAULT_DB, model_dir=None):
    """Save real captured HRRR heuristic scores; never load archived ML weights."""
    published_at = published_at or datetime.now(timezone.utc)
    count = sum(save_prediction(row, origin='captured', db_path=db_path,
                                captured_at=published_at) for row in rows)
    return {'heuristic_saved': count, 'ml_saved': 0}


def needs_reconstruction_upgrade(forecast):
    """An older retrospective snapshot lacks the now-required scenic evidence.

    Only reconstruct historic *reconstructions*: genuine captured snapshots
    represent what the app saved at the time and must not be reinterpreted.
    A None scenic score with a *current* schema is a valid unresolved prediction,
    not a reason to keep downloading the same HRRR fields.
    """
    if forecast is None:
        return True
    if forecast.get('origin') != 'reconstructed':
        return False
    return (forecast.get('heuristic_version') != HEURISTIC_VERSION
            or forecast.get('scenic_version') != SCENIC_VERSION
            or not isinstance(forecast.get('scenic_indicators'), dict)
            or 'scenic_heuristic_score' not in forecast
            or 'scenic_flatiron_score' not in forecast)


def recorded(db_path, *, valid, run, origin='reconstructed', heuristic_version=HEURISTIC_VERSION,
             scenic_version=SCENIC_VERSION):
    if not Path(db_path).exists():
        return False
    with connect(db_path) as db:
        return db.execute('''SELECT 1 FROM predictions WHERE valid_utc=? AND run_utc=?
                             AND origin=? AND heuristic_version=? AND scenic_version=? LIMIT 1''',
                          (utc_str(valid), utc_str(run), origin, heuristic_version, scenic_version)).fetchone() is not None


def choose_hrrr_run(target, cutoff, lag_hours=ARCHIVE_ASSUMED_LAG_HOURS):
    """Choose a plausibly accessible 6-hour HRRR cycle, not a proven release time."""
    target, cutoff = as_utc(target), as_utc(cutoff)
    latest = cutoff - timedelta(hours=lag_hours)
    init = latest.replace(hour=(latest.hour // 6) * 6, minute=0, second=0, microsecond=0)
    delta = target - init
    if delta.total_seconds() % 3600:
        raise ValueError('The target must lie on an exact UTC hour')
    lead = int(delta.total_seconds() // 3600)
    if not 0 <= lead < MAX_LEAD_HOURS:
        return None
    return init, lead


def backfill_event(target, offsets=DEFAULT_OFFSETS, *, db_path=DEFAULT_DB,
                   scratch=None, lag_hours=ARCHIVE_ASSUMED_LAG_HOURS, fetcher=None):
    target = as_utc(target)
    if target > datetime.now(timezone.utc):
        raise ValueError('Cannot reconstruct a target time in the future')
    if fetcher is None:
        from .hrrr import fetch_point
        fetcher = fetch_point
    scratch = Path(scratch or (DATA_DIR / 'hrrr_tmp'))
    result = []
    seen = set()
    for offset in offsets:
        if offset < 0:
            raise ValueError('Offsets must be nonnegative hours (0 = as-of event)')
        cutoff = target - timedelta(hours=offset)
        candidate = choose_hrrr_run(target, cutoff, lag_hours=lag_hours)
        if candidate is None:
            result.append({'offset_hours': offset, 'status': 'outside_supported_lead'})
            continue
        init, lead = candidate
        key = (utc_str(init), lead)
        if key in seen or recorded(db_path, valid=target, run=init):
            result.append({'offset_hours': offset, 'status': 'already_available',
                           'run_utc': utc_str(init), 'lead_hours': lead})
            continue
        seen.add(key)
        print(f'Reconstruct {utc_str(target)} as of T-{offset}h: '
              f'HRRR {utc_str(init)} F{lead:02d}', flush=True)
        row = fetcher(init, lead, scratch)
        save_prediction(row, origin='reconstructed', db_path=db_path)
        result.append({'offset_hours': offset, 'status': 'saved',
                       'run_utc': utc_str(init), 'lead_hours': lead})
    return result


def observed_at_event(db_path, chosen):
    """Independent KBDU METAR outcome from local CSV, if available.

    The IEM archive is rounded to the nearest hour by observations.parse_iem_csv.
    Never label a missing report as clear, and never infer summit clearance.
    """
    target = utc_str(chosen)
    root = Path(db_path).parent
    paths = [root / 'observed_recent_bdu.csv']
    paths.extend(sorted((x for x in root.glob('observed*.csv') if x != paths[0]),
                        reverse=True))
    for path in paths:
        if not path.exists():
            continue
        try:
            with path.open(newline='') as stream:
                for record in csv.DictReader(stream):
                    if record.get('timestamp') != target:
                        continue
                    from .observations import parse_num
                    def flag(name):
                        raw = record.get(name, '')
                        return int(raw) if raw in ('0', '1') else None
                    return {
                        'timestamp': target, 'station': 'KBDU',
                        'observed_fog': flag('observed_fog'),
                        'observed_low_ceiling': flag('observed_low_ceiling'),
                        'observed_cloud_base_ft_msl': parse_num(record.get('observed_cloud_base_ft_msl')),
                        'visibility_miles': parse_num(record.get('visibility_miles')),
                        'source': record.get('source', 'IEM METAR'),
                        'meaning': ('Independent airport report. Low ceiling and fog are station observations, '
                                    'NOT direct measurements of temperature inversion, low-cloud top, '
                                    'middle/high cloud, or summit sky.'),
                    }
        except (OSError, ValueError, csv.Error):
            continue
    return None


def history_view(db_path=DEFAULT_DB, *, now=None, window_hours=24,
                 target=None, offsets=DEFAULT_OFFSETS):
    """Recent valid times, including the latest HRRR forecast available at T-0.

    Actual captures must have existed by the requested cutoff. Retroactively
    constructed forecasts use an explicit publication-delay assumption instead.
    """
    if window_hours not in (24, 48):
        raise ValueError('History window must be 24 or 48 hours')
    now = as_utc(now or datetime.now(timezone.utc))
    earliest = now - timedelta(hours=window_hours)
    events = []
    candidates = []
    if Path(db_path).exists():
        with connect(db_path) as db:
            candidates = db.execute('''
                SELECT valid_utc, run_utc, lead_hours, origin, captured_at_utc,
                       ml_model_version, heuristic_version, scenic_version, prediction_json FROM predictions
                WHERE valid_utc >= ? AND valid_utc <= ?
                ORDER BY valid_utc DESC, run_utc DESC
            ''', (utc_str(earliest), utc_str(now))).fetchall()
    events = sorted({r['valid_utc'] for r in candidates}, reverse=True)
    chosen = utc_str(target) if target is not None else (events[0] if events else None)
    if chosen is not None and not (earliest <= as_utc(chosen) <= now):
        raise ValueError('Selected event must be within the requested history window')
    comparisons = []
    for offset in offsets:
        if offset < 0:
            raise ValueError('Offsets must be nonnegative')
        cutoff = as_utc(chosen) - timedelta(hours=offset) if chosen else None
        matches = [r for r in candidates if r['valid_utc'] == chosen] if chosen else []
        # For actual captures, a prediction may only be shown as-of a cutoff if
        # our code actually saved it at or before that cutoff.
        captured = [r for r in matches if r['origin'] == 'captured'
                    and as_utc(r['captured_at_utc']) <= cutoff]
        captured.sort(key=lambda r: (r['captured_at_utc'], r['run_utc'],
                                      bool(r['ml_model_version'])), reverse=True)
        # Each comparison must use its *own* selected run/lead. An older
        # reconstructed forecast is not proof that T-12 or T-0 was collected.
        # Captured observations are different: show what the app actually had
        # saved by the cutoff, even when the issue cycle was older.
        expected = choose_hrrr_run(as_utc(chosen), cutoff) if chosen else None
        expected_run = utc_str(expected[0]) if expected else None
        reconstructed = [r for r in matches if r['origin'] == 'reconstructed'
                         and expected_run is not None and r['run_utc'] == expected_run
                         and as_utc(r['run_utc']) <= cutoff - timedelta(
                             hours=ARCHIVE_ASSUMED_LAG_HOURS)]
        reconstructed.sort(key=lambda r: (r['run_utc'],
                                           r['heuristic_version'] == HEURISTIC_VERSION,
                                           r['scenic_version'] == SCENIC_VERSION,
                                           bool(r['ml_model_version'])), reverse=True)
        best = (captured or reconstructed or [None])[0]
        result = {'hours_before_event': offset,
                  'as_of_utc': utc_str(cutoff) if cutoff else None,
                  'forecast': None}
        if best is not None:
            value = json.loads(best['prediction_json'])
            result['forecast'] = {
                'origin': best['origin'],
                'run_utc': best['run_utc'],
                'captured_at_utc': best['captured_at_utc'] if best['origin'] == 'captured' else None,
                'lead_hours': best['lead_hours'],
                'publication_lag_assumption_hours': (
                    ARCHIVE_ASSUMED_LAG_HOURS if best['origin'] == 'reconstructed' else None),
                **value,
            }
        result['needs_refresh'] = needs_reconstruction_upgrade(result['forecast'])
        comparisons.append(result)
    return {
        'window_hours': window_hours,
        'event_times_utc': events,
        'selected_event_utc': chosen,
        'comparisons': comparisons,
        'observation': observed_at_event(db_path, chosen) if chosen else None,
        'note': ('Captured means this app saved a forecast on or before the shown as-of time. '
                 'Reconstructed means the present heuristic was applied later to an archived '
                 'HRRR run, assuming a 2-hour dissemination delay; it is NOT proof of what '
                 'the website displayed, or that the run was available by that cutoff. '
                 'T-0 means the latest run plausibly available at event time, not an F00 analysis. '
                 'KBDU METAR, when present, describes airport conditions only. '
                 'A high index is not a verified meteorological inversion.'),
    }


def timeline_view(db_path=DEFAULT_DB, *, now=None, window_hours=48, cutoff_hours=6):
    """One pre-event vintage per valid hour; never display hindsight as captured."""
    if not 1 <= window_hours <= 48:
        raise ValueError('Only up to 48 past hours may be shown')
    now = as_utc(now or datetime.now(timezone.utc))
    end = now.replace(minute=0, second=0, microsecond=0)
    earliest = end - timedelta(hours=window_hours)
    if not Path(db_path).exists():
        return []
    with connect(db_path) as db:
        found = db.execute('''
            SELECT valid_utc, run_utc, lead_hours, origin, captured_at_utc,
                   ml_model_version, scenic_version, prediction_json
            FROM predictions WHERE valid_utc >= ? AND valid_utc <= ?
            ORDER BY valid_utc, run_utc''',
            (utc_str(earliest), utc_str(end))).fetchall()
    selected = {}
    for item in found:
        valid = as_utc(item['valid_utc'])
        cutoff = valid - timedelta(hours=cutoff_hours)
        if item['origin'] == 'captured':
            if as_utc(item['captured_at_utc']) > cutoff:
                continue
            score = (2, item['captured_at_utc'], item['run_utc'],
                     item['scenic_version'] == SCENIC_VERSION, bool(item['ml_model_version']))
        else:
            if as_utc(item['run_utc']) > cutoff - timedelta(hours=ARCHIVE_ASSUMED_LAG_HOURS):
                continue
            score = (1, item['run_utc'], item['run_utc'],
                     item['scenic_version'] == SCENIC_VERSION, bool(item['ml_model_version']))
        key = item['valid_utc']
        if key not in selected or score > selected[key][0]:
            value = json.loads(item['prediction_json'])
            selected[key] = (score, {
                'timestamp': key,
                'run_utc': item['run_utc'],
                'lead_hours': item['lead_hours'],
                'origin': item['origin'],
                'captured_at_utc': item['captured_at_utc'] if item['origin'] == 'captured' else None,
                'scenic_heuristic_score': value.get('scenic_heuristic_score'),
                'scenic_flatiron_score': value.get('scenic_flatiron_score'),
                'heuristic_score': value.get('heuristic_score'),
                'ml_probability': value.get('ml_probability'),
                'heuristic_version': value.get('heuristic_version'),
            })
    return [selected[k][1] for k in sorted(selected)]

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    back = sub.add_parser('backfill', help='Reconstruct past HRRR vintage forecasts')
    back.add_argument('--local-time', required=True,
                      help='Boulder time, e.g. "2026-10-30 07:00" (hourly)')
    back.add_argument('--offsets', default='24,18,12,6,0')
    back.add_argument('--lag-hours', type=int, default=ARCHIVE_ASSUMED_LAG_HOURS)
    back.add_argument('--db', type=Path, default=DEFAULT_DB)
    status = sub.add_parser('status', help='Inspect saved captured and reconstructed forecasts')
    status.add_argument('--db', type=Path, default=DEFAULT_DB)
    args = ap.parse_args()
    if args.command == 'status':
        if not args.db.exists():
            print(f'No saved forecast history yet at {args.db}')
            return
        with connect(args.db) as db:
            for r in db.execute('SELECT origin, COUNT(*) AS n FROM predictions GROUP BY origin'):
                print(f"{r['origin']}: {r['n']} stored forecasts")
        return
    local = datetime.fromisoformat(args.local_time.replace(' ', 'T'))
    if local.tzinfo is None:
        local = local.replace(tzinfo=ZoneInfo(TIMEZONE))
    offsets = tuple(int(x.strip()) for x in args.offsets.split(','))
    results = backfill_event(local, offsets=offsets, db_path=args.db, lag_hours=args.lag_hours)
    print(json.dumps(results, indent=2))
    print('Open the local site history panel to compare the vintage predictions.')


if __name__ == '__main__':
    main()
