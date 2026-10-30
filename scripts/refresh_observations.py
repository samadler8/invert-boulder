"""Refresh a small independent KBDU METAR cache for recent history comparisons.

Usage:
    python -m scripts.refresh_observations --days 4

No HRRR forecast is needed. This DOES NOT alter the long-term training labels.
"""
import argparse
import csv
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from inversion.config import DATA_DIR
from inversion.observations import download_iem, save_csv

RECENT = DATA_DIR / 'observed_recent_bdu.csv'


def refresh_observations(start, end, *, output=RECENT, fetcher=None):
    """Fetch IEM data and merge by rounded UTC hour, preserving older recent hours."""
    if end < start or (end - start).days > 7:
        raise ValueError('Observation refresh must cover 0-7 days')
    fetcher = fetcher or download_iem
    path = Path(output)
    by_hour = {}
    if path.exists():
        with path.open(newline='') as stream:
            for record in csv.DictReader(stream):
                if record.get('timestamp'):
                    by_hour[record['timestamp']] = record
    fresh = fetcher(start, end)
    for record in fresh:
        if record.get('timestamp'):
            by_hour[record['timestamp']] = record
    staging = path.with_name(path.name + '.next')
    save_csv([by_hour[key] for key in sorted(by_hour)], staging)
    staging.replace(path)
    return {'new_reports': len(fresh), 'total_cached_hours': len(by_hour),
            'source': 'IEM KBDU METAR', 'path': str(path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--days', type=int, default=4,
                        help='Number of recent UTC dates to fetch (default 4)')
    args = parser.parse_args()
    if not 1 <= args.days <= 7:
        parser.error('--days must be between 1 and 7')
    today = datetime.now(timezone.utc).date()
    result = refresh_observations(today - timedelta(days=args.days - 1), today)
    print(result)
    print('The historical forecast page can now display cached independent airport reports.')


if __name__ == '__main__':
    main()
