"""Bounded, auditable local storage for the public-data forecast app.

Only disposable cache files are automatically trimmed. The immutable forecast
history and the user's historical training downloads are never pruned by the
routine updater. All destructive operations support a preview.
"""
from __future__ import annotations
import csv
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from .config import DATA_DIR

CACHED_FORECASTS = 'quicklook_forecast_cache.jsonl'
LIVE_FORECASTS = 'hrrr_live.jsonl'
HISTORY_DB = 'forecast_history.sqlite3'
OBS_CACHES = ('observed_recent_bdu.csv', 'observed_nearby.json', 'nws_hourly.json')
CACHE_DAYS = 7
TEMP_MIN_AGE_HOURS = 4


def utc(dt):
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def forecast_prune(path, *, now=None, days=CACHE_DAYS, apply=False):
    """Discard old, duplicated run/lead entries; keep latest valid row per key.

    On a read or write failure, leave the original file completely untouched.
    """
    p = Path(path)
    if not p.exists():
        return {'file': p.name, 'before': 0, 'after': 0, 'removed': 0}
    now = utc(now or datetime.now(timezone.utc))
    cutoff = now - timedelta(days=days)
    rows = []
    with p.open(encoding='utf-8') as stream:
        for line in stream:
            if line.strip():
                rows.append(json.loads(line))
    chosen = {}
    for row in rows:
        ts = datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00'))
        if utc(ts) < cutoff:
            continue
        key = (row['run_utc'], int(row['lead_hours']))
        chosen[key] = row
    keep = sorted(chosen.values(), key=lambda r: (r['run_utc'], int(r['lead_hours'])))
    if apply and len(keep) != len(rows):
        stage = p.with_name(p.name + '.cleanup-next')
        try:
            with stage.open('w', encoding='utf-8') as out:
                for row in keep:
                    out.write(json.dumps(row, allow_nan=True) + '\n')
                out.flush()
                os.fsync(out.fileno())
            stage.replace(p)
        finally:
            stage.unlink(missing_ok=True)
    return {'file': p.name, 'before': len(rows), 'after': len(keep),
            'removed': len(rows) - len(keep), 'applied': apply}


def prune_recent_observations(path, *, now=None, days=30, apply=False):
    p=Path(path)
    if not p.exists():
        return {'before': 0, 'after': 0, 'removed': 0}
    now=utc(now or datetime.now(timezone.utc))
    with p.open(newline='') as stream:
        reader=csv.DictReader(stream)
        fields=reader.fieldnames
        if not fields or 'timestamp' not in fields:
            raise ValueError('Unexpected recent observation CSV schema')
        rows=list(reader)
    cutoff=now-timedelta(days=days)
    kept=[]
    for row in rows:
        try:
            timestamp=utc(datetime.fromisoformat(row['timestamp'].replace('Z','+00:00')))
        except (ValueError,KeyError,TypeError):
            kept.append(row)  # don't silently delete ambiguous records
            continue
        if timestamp>=cutoff:
            kept.append(row)
    if apply and len(kept)!=len(rows):
        stage=p.with_name(p.name+'.cleanup-next')
        try:
            with stage.open('w',newline='') as out:
                writer=csv.DictWriter(out,fieldnames=fields)
                writer.writeheader();writer.writerows(kept)
                out.flush();os.fsync(out.fileno())
            stage.replace(p)
        finally:
            stage.unlink(missing_ok=True)
    return {'before':len(rows),'after':len(kept),
            'removed':len(rows)-len(kept),'applied':apply}


def cleanup(data_dir=DATA_DIR, *, now=None, cache_days=CACHE_DAYS,
            apply=False, delete_old_history_days=None):
    """Preview or apply bounded cleanup. Never touches historical training data.

    Pruning the immutable history ledger is only possible with an explicit
    delete_old_history_days argument. No history is deleted by default.
    """
    root = Path(data_dir)
    now = utc(now or datetime.now(timezone.utc))
    if cache_days < 1:
        raise ValueError('cache_days must be >= 1')
    report = {'dry_run': not apply, 'cache_days': cache_days, 'files': [],
              'temporary_files': [], 'history_rows_to_delete': 0}
    for name in (CACHED_FORECASTS, LIVE_FORECASTS):
        report['files'].append(forecast_prune(root / name, now=now, days=cache_days, apply=apply))
    # Only known temporary directory, no recursive deletion of arbitrary paths.
    tmp = root / 'hrrr_tmp'
    if tmp.exists():
        for path in tmp.rglob('*'):
            if not path.is_file() or path.is_symlink():
                continue
            if path.stat().st_mtime < (now - timedelta(hours=TEMP_MIN_AGE_HOURS)).timestamp():
                report['temporary_files'].append({'file': str(path.relative_to(root)), 'bytes': path.stat().st_size})
                if apply:
                    path.unlink(missing_ok=True)
    # Only the short-lived BDU recent-METAR cache is trimmed; the independent
    # multi-year historical observation archive is never affected.
    report['recent_observations'] = prune_recent_observations(
        root / 'observed_recent_bdu.csv', now=now, days=30, apply=apply)
    if delete_old_history_days is not None:
        if delete_old_history_days < 30:
            raise ValueError('History retention must be at least 30 days')
        db_path = root / HISTORY_DB
        if db_path.exists():
            cutoff = (now - timedelta(days=delete_old_history_days)).strftime('%Y-%m-%dT%H:%M:%SZ')
            with sqlite3.connect(db_path, timeout=20) as db:
                report['history_rows_to_delete'] = db.execute(
                    'SELECT COUNT(*) FROM predictions WHERE valid_utc < ?', (cutoff,)).fetchone()[0]
                if apply and report['history_rows_to_delete']:
                    db.execute('DELETE FROM predictions WHERE valid_utc < ?', (cutoff,))
                    db.commit()
    return report


def status(data_dir=DATA_DIR):
    root = Path(data_dir)
    names = [CACHED_FORECASTS, LIVE_FORECASTS, HISTORY_DB, *OBS_CACHES,
             'hrrr_samples.jsonl', 'observed_bdu_2018_2026.csv']
    files = []
    for name in names:
        p = root / name
        if p.is_file():
            files.append({'name': name, 'size_mb': round(p.stat().st_size / 1048576, 2),
                          'last_modified_utc': datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat()})
    history_count = None
    db = root / HISTORY_DB
    if db.exists():
        try:
            with sqlite3.connect(db, timeout=5) as con:
                history_count = con.execute('SELECT COUNT(*) FROM predictions').fetchone()[0]
        except sqlite3.Error:
            pass
    return {'files': files, 'history_snapshots': history_count,
            'policy': {'forecast_cache_days': CACHE_DAYS,
                       'history': 'indefinite unless explicitly purged',
                       'raw_grib': 'deleted immediately after extraction; stale leftovers cleaned after 4h',
                       'historical_training_data': 'untouched'}}
