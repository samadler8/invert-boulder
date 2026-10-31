"""Optional NWS public hourly forecast for downtown Boulder.

Separate forecast guidance, NOT an observation or a component of the
HRRR-based inversion index. Failure leaves the last good cache untouched.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from .config import DATA_DIR

POINT = 'https://api.weather.gov/points/40.015,-105.2705'
CACHE = DATA_DIR / 'nws_hourly.json'
HEADERS = {'User-Agent': 'BoulderInversionOutlook/1.0 (local public weather dashboard)',
           'Accept': 'application/geo+json'}


def normalize(data, *, fetched=None, source_url=None):
    periods = ((data.get('properties') or {}).get('periods') or [])
    results = []
    for p in periods:
        try:
            start = datetime.fromisoformat(str(p['startTime']).replace('Z', '+00:00'))
            if start.tzinfo is None:
                continue
        except (KeyError, ValueError, TypeError):
            continue
        pp = p.get('probabilityOfPrecipitation') or {}
        rh = p.get('relativeHumidity') or {}
        results.append({
            'timestamp_utc': start.astimezone(timezone.utc).isoformat().replace('+00:00','Z'),
            'summary': str(p.get('shortForecast') or '')[:140],
            'temperature': p.get('temperature') if isinstance(p.get('temperature'), (int,float)) else None,
            'temperature_unit': str(p.get('temperatureUnit') or ''),
            'relative_humidity_pct': rh.get('value') if isinstance(rh,dict) else None,
            'precipitation_probability_pct': pp.get('value') if isinstance(pp,dict) else None,
            'wind_speed': str(p.get('windSpeed') or ''),
            'wind_direction': str(p.get('windDirection') or ''),
            'is_daytime': bool(p.get('isDaytime',False)),
        })
    if not results:
        raise ValueError('NWS hourly forecast has no usable periods')
    return {'source': 'NWS Weather Forecast Office hourly forecast',
            'source_url': source_url,
            'fetched_utc': (fetched or datetime.now(timezone.utc)).isoformat(),
            'hours': sorted(results,key=lambda x:x['timestamp_utc']),
            'note': 'NWS hourly guidance is a separate forecast, not an observation and not included in the HRRR inversion index.'}


def refresh_nws(*, output=CACHE, client=None, now=None):
    client = client or requests
    now = now or datetime.now(timezone.utc)
    lookup = client.get(POINT, headers=HEADERS, timeout=20)
    lookup.raise_for_status()
    hourly_url = (lookup.json().get('properties') or {}).get('forecastHourly')
    parsed = urlparse(hourly_url or '')
    if parsed.scheme != 'https' or parsed.hostname != 'api.weather.gov':
        raise ValueError('NWS point lookup returned an untrusted hourly URL')
    response = client.get(hourly_url, headers=HEADERS, timeout=25)
    response.raise_for_status()
    data = normalize(response.json(),fetched=now,source_url=hourly_url)
    p = Path(output)
    p.parent.mkdir(parents=True, exist_ok=True)
    stage = p.with_name(p.name+'.next')
    try:
        stage.write_text(json.dumps(data,indent=2)+'\n')
        stage.replace(p)
    finally:
        stage.unlink(missing_ok=True)
    return {'hours':len(data['hours']), 'path':str(p)}


def cached_nws(path=CACHE):
    p=Path(path)
    if not p.exists():
        return {'hours': [], 'status': 'not_loaded'}
    try:
        v=json.loads(p.read_text())
        if not isinstance(v.get('hours'),list):
            raise ValueError('Bad cached forecast')
        return v
    except (OSError, ValueError):
        return {'hours': [], 'status': 'unavailable'}
