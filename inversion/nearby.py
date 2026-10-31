"""Independent neighboring airport METAR context from Iowa Environmental Mesonet.

This is corroboration of local visibility/sky, NOT a measurement of the cloud
top over the Flatirons or a substitute for the HRRR forecast.
"""
import csv
import io
import json
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

import requests
from .config import DATA_DIR
from .observations import IEM_URL, parse_num

STATIONS = {
    'BDU': {'name': 'Boulder airport', 'lat': 40.0394, 'lon': -105.2250},
    'BJC': {'name': 'Rocky Mountain Metropolitan', 'lat': 39.9088, 'lon': -105.1172},
    'EIK': {'name': 'Erie municipal', 'lat': 40.0102, 'lon': -105.0480},
    'LMO': {'name': 'Longmont/Vance Brand', 'lat': 40.1637, 'lon': -105.1630},
}
RECENT_PATH = DATA_DIR / 'observed_nearby.json'


def parse_reports(raw, *, end_time=None):
    """Newest valid report per station; missing stations remain omitted."""
    cleaned = '\n'.join(line for line in raw.splitlines() if line.strip() and not line.startswith('#'))
    reader = csv.DictReader(io.StringIO(cleaned))
    if not {'station', 'valid'}.issubset(set(reader.fieldnames or [])):
        raise ValueError('Unexpected IEM METAR response columns')
    result = {}
    for r in reader:
        key = r.get('station', '').strip().upper().removeprefix('K')
        if key not in STATIONS:
            continue
        try:
            timestamp = datetime.fromisoformat(r['valid'].strip().replace('Z', '+00:00'))
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            timestamp = timestamp.astimezone(timezone.utc)
        except (ValueError, TypeError):
            continue
        if end_time and timestamp > end_time + timedelta(minutes=5):
            continue
        if key in result and result[key]['timestamp_utc'] >= timestamp.isoformat():
            continue
        sky = []
        for i in range(1, 5):
            code = (r.get(f'skyc{i}') or '').strip().upper()
            height = parse_num(r.get(f'skyl{i}'))
            if code and code not in {'M', 'NA'}:
                sky.append({'coverage': code, 'height_ft_agl': height})
        result[key] = {
            'station': key, 'name': STATIONS[key]['name'],
            'latitude': STATIONS[key]['lat'], 'longitude': STATIONS[key]['lon'],
            'timestamp_utc': timestamp.isoformat().replace('+00:00','Z'),
            'temperature_f': parse_num(r.get('tmpf')),
            'dew_point_f': parse_num(r.get('dwpf')),
            'relative_humidity_pct': parse_num(r.get('relh')),
            'visibility_miles': parse_num(r.get('vsby')),
            'wind_knots': parse_num(r.get('sknt')),
            'weather_codes': (r.get('wxcodes') or '').strip(),
            'sky_layers': sky,
            'metar': (r.get('metar') or '').strip(),
            'source': 'Iowa Environmental Mesonet / airport METAR',
        }
    return sorted(result.values(), key=lambda x: x['station'])


def refresh_nearby(*, now=None, output=RECENT_PATH, session=None):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError('now must be timezone aware')
    client = session or requests
    first = (now - timedelta(days=2)).date()
    end = now.date() + timedelta(days=1)
    params = [('station', key) for key in STATIONS]
    params.extend([('network', 'CO_ASOS'), ('data', 'all'),
        ('year1', first.year), ('month1', first.month), ('day1', first.day),
        ('year2', end.year), ('month2', end.month), ('day2', end.day),
        ('tz', 'Etc/UTC'), ('format', 'onlycomma'), ('missing','M'),
        ('report_type','3'), ('report_type','4')])
    response = client.get(IEM_URL, params=params, timeout=35)
    response.raise_for_status()
    stations = parse_reports(response.text, end_time=now)
    if not stations:
        raise ValueError('IEM returned no usable nearby airport reports')
    result = {'retrieved_utc': now.isoformat().replace('+00:00','Z'),
              'source_url': 'https://mesonet.agron.iastate.edu/request/download.phtml?network=CO_ASOS',
              'stations': stations,
              'caveat': 'Observed airport weather only; no station measures cloud tops or summit visibility.'}
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = path.with_name(path.name + '.next')
    try:
        stage.write_text(json.dumps(result, indent=2) + '\n')
        stage.replace(path)
    finally:
        stage.unlink(missing_ok=True)
    return {'stations': len(stations), 'path': str(path)}


def cached_nearby(path=RECENT_PATH):
    p = Path(path)
    if not p.exists():
        return {'stations': [], 'retrieved_utc': None, 'status': 'not_loaded'}
    try:
        obj = json.loads(p.read_text())
        if not isinstance(obj.get('stations'), list):
            raise ValueError('Invalid stations data')
        return obj
    except (OSError, ValueError, TypeError):
        return {'stations': [], 'retrieved_utc': None, 'status': 'unavailable'}
