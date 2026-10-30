"""Download genuinely independent surface weather observations from IEM METAR.

Airport fog/ceiling observations are NOT summit cloud-top observations.
Unknown and ambiguous hours stay unlabeled (never negative by default).
"""
import argparse
import csv
import io
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from .config import (DATA_DIR, OBS_STATION, OBS_NETWORK,
                     OBS_STATION_ELEV_FT)

IEM_URL = 'https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py'
CEILING_CODES = {'BKN', 'OVC', 'VV'}
FOG_CODES = {'FG', 'FZFG'}


def parse_num(s):
    if s is None or str(s).strip().upper() in ('', 'M', 'T', 'NA', 'NULL'):
        return None
    try:
        value = float(str(s).strip())
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def observed_cloud_base_ft(report):
    """Lowest reported BKN/OVC/VV ceiling, meters? No: METAR skyl in ft AGL."""
    candidates = []
    for n in range(1, 5):
        cover = (report.get(f'skyc{n}') or '').strip().upper()
        height = parse_num(report.get(f'skyl{n}'))
        if cover in CEILING_CODES and height is not None and 0 <= height <= 5000:
            candidates.append(height)
    return (min(candidates) + OBS_STATION_ELEV_FT) if candidates else None


def classify_report(report):
    """Conservative ground-level visibility/low-ceiling fog definition.

    1 if vis<=1 mile and direct FG/FZFG or a reported ceiling <=1000ft AGL.
    0 if vis>=5 miles and no fog code.
    else None. Note cloud base is not cloud top, nor does METAR prove an inversion.
    """
    vsby = parse_num(report.get('vsby'))
    wx = (report.get('wxcodes') or '').upper().replace('-', ' ').replace('+', ' ')
    tokens = set(wx.split())
    fog = bool(tokens & FOG_CODES)
    base = observed_cloud_base_ft(report)
    low_ceiling = base is not None and base - OBS_STATION_ELEV_FT <= 1000
    if vsby is None:
        return None
    if vsby <= 1 and (fog or low_ceiling):
        return 1
    if vsby >= 5 and not fog:
        return 0
    return None



def classify_low_ceiling(report, threshold_agl_ft=1000):
    """Strict station low-ceiling target: 1 if BKN/OVC/VV <=threshold AGL.

    0 if sky layers were reported and none qualifies. Missing sky reports remain
    unknown, including clear-visibility-only reports.
    """
    sky_codes = [(report.get(f'skyc{n}') or '').strip().upper() for n in range(1, 5)]
    valid = {'CLR', 'SKC', 'FEW', 'SCT', 'BKN', 'OVC', 'VV', 'NSC', 'NCD'}
    if not any(code in valid for code in sky_codes):
        return None
    for n, code in enumerate(sky_codes, 1):
        if code in CEILING_CODES:
            height = parse_num(report.get(f'skyl{n}'))
            if height is not None and 0 <= height <= threshold_agl_ft:
                return 1
    # A VV code without a numeric height cannot confirm absence of low ceiling.
    if 'VV' in sky_codes and not any(parse_num(report.get(f'skyl{n}')) is not None
                                      for n, code in enumerate(sky_codes, 1) if code == 'VV'):
        return None
    return 0

def parse_iem_csv(raw):
    """Convert unvalidated METAR reports to nearest hour, prefer closest report.

    Rejects duplicate station-hour collisions by choosing the observation closest
    to the UTC forecast valid time; ties prefer later report.
    """
    meaningful = '\n'.join(line for line in raw.splitlines()
                            if line.strip() and not line.lstrip().startswith('#'))
    reader = csv.DictReader(io.StringIO(meaningful))
    if not {'valid', 'vsby', 'station'}.issubset(reader.fieldnames or []):
        raise ValueError('IEM CSV missing expected valid/vsby/station columns')
    selected = {}
    for r in reader:
        if r.get('station', '').upper().removeprefix('K') != OBS_STATION:
            continue
        rawtime = r.get('valid', '').strip()
        try:
            at = datetime.fromisoformat(rawtime.replace('Z', '+00:00'))
            at = at.replace(tzinfo=timezone.utc) if at.tzinfo is None else at.astimezone(timezone.utc)
        except ValueError:
            continue
        closest = (at + timedelta(minutes=30)).replace(minute=0, second=0, microsecond=0)
        offset = abs((at - closest).total_seconds())
        if offset > 30 * 60:
            continue
        key = closest.isoformat().replace('+00:00', 'Z')
        priority = (offset, -at.timestamp())
        if key not in selected or priority < selected[key][0]:
            selected[key] = (priority, r)
    results = []
    for stamp, (_, r) in sorted(selected.items()):
        label = classify_report(r)
        base_ft = observed_cloud_base_ft(r)
        results.append({
            'timestamp': stamp, 'station': OBS_STATION,
            'observed_fog': '' if label is None else label,
            'observed_low_ceiling': '' if classify_low_ceiling(r) is None else classify_low_ceiling(r),
            'observed_cloud_base_ft_msl': '' if base_ft is None else round(base_ft),
            'visibility_miles': '' if parse_num(r.get('vsby')) is None else parse_num(r.get('vsby')),
            'source': 'IEM METAR (independent station observation)',
        })
    return results


def download_iem(start, end, *, session=None):
    """Start inclusive, end inclusive (dates); download query uses exclusive end."""
    if start > end:
        raise ValueError('start must precede end')
    client = session or requests
    output = []
    cur = start
    while cur <= end:
        stop = min(end + timedelta(days=1), cur + timedelta(days=31))
        params = [
            ('station', OBS_STATION), ('network', OBS_NETWORK), ('data', 'all'),
            ('year1', cur.year), ('month1', cur.month), ('day1', cur.day),
            ('year2', stop.year), ('month2', stop.month), ('day2', stop.day),
            ('tz', 'Etc/UTC'), ('format', 'onlycomma'),
            ('latlon', 'no'), ('elev', 'no'), ('missing', 'M'),
            ('trace', 'T'), ('direct', 'no'),
            ('report_type', '3'), ('report_type', '4'),
        ]
        response = client.get(IEM_URL, params=params, timeout=120)
        response.raise_for_status()
        output.extend(parse_iem_csv(response.text))
        cur = stop
    return list({r['timestamp']: r for r in output}.values())


def save_csv(records, dest):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    names = ('timestamp', 'station', 'observed_fog', 'observed_low_ceiling', 'observed_cloud_base_ft_msl',
             'visibility_miles', 'source')
    with dest.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=names)
        writer.writeheader()
        writer.writerows(records)


def read_csv(path):
    records = {}
    with open(path, newline='') as f:
        for r in csv.DictReader(f):
            key = r['timestamp']
            if key in records:
                raise ValueError(f'Duplicate station observation hour: {key}')
            label = (int(r['observed_fog']) if r.get('observed_fog', '') != '' else None)
            low = (int(r['observed_low_ceiling']) if r.get('observed_low_ceiling', '') != '' else None)
            if low not in (None, 0, 1):
                raise ValueError(f'Invalid observed low ceiling label: {low}')
            if label not in (None, 0, 1):
                raise ValueError(f'Invalid observed fog label: {label}')
            base = parse_num(r.get('observed_cloud_base_ft_msl'))
            records[key] = {'fog': label, 'low_ceiling': low, 'cloud_base_ft': base}
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', type=date.fromisoformat, required=True)
    parser.add_argument('--end', type=date.fromisoformat, required=True)
    parser.add_argument('--output', type=Path, default=DATA_DIR / 'observed_bdu.csv')
    args = parser.parse_args()
    records = download_iem(args.start, args.end)
    save_csv(records, args.output)
    counts = {k: sum(r['observed_fog'] == k for r in records) for k in (0, 1)}
    lowpos = sum(r['observed_low_ceiling'] == 1 for r in records)
    print(f'Saved {len(records)} unique reported hours: {counts[1]} fog, {counts[0]} clear; {lowpos} low-ceiling positives; '
          f'{sum(r["observed_cloud_base_ft_msl"] != "" for r in records)} low cloud-base reports. '
          f'Unlabeled hours remain unknown. File: {args.output}')


if __name__ == '__main__':
    main()
