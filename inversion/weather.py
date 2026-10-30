"""Consistent GFS historical-forecast and current-forecast acquisitions."""
import json
import time
from datetime import date, timedelta
from urllib.parse import urlencode
from pathlib import Path

import requests
from .config import (BOULDER_LAT, BOULDER_LON, HOURLY_FIELDS,
                     MODEL_SOURCE, TIMEZONE)

LIVE_URL = 'https://api.open-meteo.com/v1/forecast'
HISTORY_URL = 'https://historical-forecast-api.open-meteo.com/v1/forecast'


def params(start=None, end=None, *, days=9):
    p = {
        'latitude': BOULDER_LAT, 'longitude': BOULDER_LON,
        'hourly': ','.join(HOURLY_FIELDS),
        'models': MODEL_SOURCE, 'timezone': 'UTC',
        'temperature_unit': 'celsius', 'wind_speed_unit': 'kmh',
    }
    if start is not None:
        p['start_date'], p['end_date'] = str(start), str(end)
    else:
        p['forecast_days'] = days
    return p


def fetch(url, parameters, *, session=None):
    client = session if session is not None else requests
    last_error = None
    for attempt in range(3):
        try:
            result = client.get(url, params=parameters, timeout=45)
            result.raise_for_status()
            data = result.json()
            if 'hourly' not in data or 'time' not in data['hourly']:
                raise ValueError(f'Open-Meteo response lacks hourly data: {str(data)[:250]}')
            return data
        except (requests.RequestException, ValueError) as ex:
            last_error = ex
            if attempt < 2:
                time.sleep(1 + attempt)
    raise RuntimeError(f'Open-Meteo request failed: {last_error}') from last_error


def fetch_live(*, session=None):
    return fetch(LIVE_URL, params(), session=session)


def fetch_history(start: date, end: date, *, cache_dir=None, session=None):
    """Archive in bounded 90-day chunks; cache raw source including timestamps."""
    if end < start:
        raise ValueError('end must not precede start')
    cache = Path(cache_dir) if cache_dir else None
    if cache:
        cache.mkdir(parents=True, exist_ok=True)
    output = []
    cursor = start
    while cursor <= end:
        chunk_end = min(end, cursor + timedelta(days=89))
        key = f'gfs_{cursor.isoformat()}_{chunk_end.isoformat()}.json'
        cache_file = cache / key if cache else None
        if cache_file and cache_file.exists():
            data = json.loads(cache_file.read_text())
        else:
            data = fetch(HISTORY_URL, params(cursor, chunk_end), session=session)
            if cache_file:
                cache_file.write_text(json.dumps(data))
        output.append(data)
        cursor = chunk_end + timedelta(days=1)
    return output
