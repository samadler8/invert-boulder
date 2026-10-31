"""Inspect and safely prune local HRRR caches without touching historical datasets.

python -m scripts.storage status
python -m scripts.storage cleanup           # preview only
python -m scripts.storage cleanup --apply   # apply 7-day cache retention
python -m scripts.storage cleanup --apply --history-days 365  # opt-in history purge
"""
import argparse
import json
from inversion.storage import status, cleanup

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command', choices=['status', 'cleanup'])
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--cache-days', type=int, default=7)
    ap.add_argument('--history-days', type=int, default=None,
                    help='Explicitly delete history older than this many days (>=30); never default')
    a = ap.parse_args()
    if a.command == 'status':
        result = status()
    else:
        result = cleanup(cache_days=a.cache_days, apply=a.apply,
                         delete_old_history_days=a.history_days)
    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()
