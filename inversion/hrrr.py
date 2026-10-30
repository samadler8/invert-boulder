"""Download *selected* HRRR GRIB messages, extract KBDU grid-point scalars,
and discard temporary GRIB files. Requires Herbie and ecCodes.

Examples:
  python -m inversion.hrrr inspect --date 2025-01-15 --fxx 36
  python -m inversion.hrrr collect --start 2025-01-15 --end 2025-01-16 --lead-hours 24,30,36
  python -m inversion.hrrr live --lead-hours 12,18,24,30,36,39

Do not download full CONUS GRIB files; use only indexed message subsets.
"""
import argparse
import json
import math
from datetime import datetime, date, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
from .config import (DATA_DIR, OBS_LAT, OBS_LON, TIMEZONE, MAX_LEAD_HOURS,
                     PRESSURE_LEVELS, PROFILE_LEVELS, PROFILE_TOP_AGL_M,
                     FEATURE_NAMES)

# Search expressions are matched against the NOAA .idx inventory, NOT full GRIB bytes.
SURFACE_REGEX = (
    r':(?:VIS:surface|HGT:surface|TMP:2 m above ground|DPT:2 m above ground|'
    r'RH:2 m above ground|UGRD:10 m above ground|VGRD:10 m above ground|'
    r'LCDC:low cloud layer|MCDC:middle cloud layer|HCDC:high cloud layer|'
    r'HPBL:surface|HGT:cloud base|HGT:cloud top):'
)
# About 6-8 km north, south, east, west of the KBDU reference point.
# These are nearby HRRR grid-cell diagnostics, NOT mountain-point forecasts.
SPATIAL_CLOUD_POINTS = (
    ('north', OBS_LAT + .06, OBS_LON),
    ('south', OBS_LAT - .06, OBS_LON),
    ('east', OBS_LAT, OBS_LON + .08),
    ('west', OBS_LAT, OBS_LON - .08),
)
PRESSURE_REGEX = (
    r':(?:HGT|TMP|RH|UGRD|VGRD):(?:600|650|700|750|800) mb:'
)


def decode_nearest(path, lat=OBS_LAT, lon=OBS_LON, *, neighbors=None):
    """Return scalar values in GRIB message order (no full-grid arrays stored)."""
    from eccodes import codes_grib_new_from_file, codes_grib_find_nearest, codes_release
    result = []
    with open(path, 'rb') as stream:
        while (gid := codes_grib_new_from_file(stream)) is not None:
            try:
                closest = codes_grib_find_nearest(gid, lat, lon % 360, npoints=1)
                center = float(closest[0].value)
                if neighbors is None:
                    result.append(center)
                else:
                    others = []
                    for _, near_lat, near_lon in neighbors:
                        try:
                            sample = codes_grib_find_nearest(gid, near_lat, near_lon % 360, npoints=1)
                            value = float(sample[0].value)
                            others.append(value if math.isfinite(value) else None)
                        except (ValueError, RuntimeError, IndexError, TypeError, OSError):
                            others.append(None)
                    result.append((center, others))
            finally:
                codes_release(gid)
    return result


def download_product(init, fxx, product, pattern, scratch, *, verbose=False, spatial=False):
    """Use index-based byte-range subsetting; return indexed scalars."""
    from herbie import Herbie
    h = Herbie(init.strftime('%Y-%m-%d %H:%M'), model='hrrr', product=product,
               fxx=fxx, verbose=verbose)
    inventory = h.inventory(search=pattern)
    if inventory is None or inventory.empty:
        raise RuntimeError(f'No HRRR {product} inventory messages for {init} F{fxx:02d}')
    path = Path(h.download(pattern, save_dir=scratch, verbose=verbose, errors='raise'))
    try:
        values = decode_nearest(path, neighbors=SPATIAL_CLOUD_POINTS if spatial else None)
        if len(values) != len(inventory):
            raise RuntimeError(f'{product} GRIB fields {len(values)} != index entries {len(inventory)}')
        out = {}
        samples = {name: {} for name, _, _ in SPATIAL_CLOUD_POINTS} if spatial else None
        for (_, item), val in zip(inventory.iterrows(), values):
            name = str(item['variable']).upper()
            level = str(item['level']).strip().lower()
            if spatial:
                center, neighbors = val
                out[(name, level)] = center
                if name in ('LCDC', 'MCDC', 'HCDC'):
                    for (point_name, _, _), value in zip(SPATIAL_CLOUD_POINTS, neighbors):
                        samples[point_name][{'LCDC':'low_cloud_pct',
                                             'MCDC':'mid_cloud_pct',
                                             'HCDC':'high_cloud_pct'}[name]] = value
            else:
                out[(name, level)] = val
        if spatial:
            out['_spatial_cloud_samples'] = [
                {'label': label, 'latitude': lat, 'longitude': lon, **samples[label]}
                for label, lat, lon in SPATIAL_CLOUD_POINTS]
        return out
    finally:
        # Never retain continental GRIB arrays after point extraction.
        path.unlink(missing_ok=True)


def require(fields, variable, level):
    key = (variable, level)
    if key not in fields or not math.isfinite(fields[key]):
        raise ValueError(f'HRRR missing {variable} at {level}; index fields were {list(fields)[:8]}')
    return fields[key]


def build_row(init, lead, surface, pressure):
    """Transform decoded HRRR scalars to common XGBoost and CNN input schema."""
    valid = init + timedelta(hours=lead)
    local = valid.astimezone(ZoneInfo(TIMEZONE))
    temp = require(surface, 'TMP', '2 m above ground') - 273.15
    dew = require(surface, 'DPT', '2 m above ground') - 273.15
    humidity = require(surface, 'RH', '2 m above ground')
    u10 = require(surface, 'UGRD', '10 m above ground')
    v10 = require(surface, 'VGRD', '10 m above ground')
    ground = require(surface, 'HGT', 'surface')
    vis = require(surface, 'VIS', 'surface')
    low = require(surface, 'LCDC', 'low cloud layer')
    mid = require(surface, 'MCDC', 'middle cloud layer')
    high = require(surface, 'HCDC', 'high cloud layer')
    pbl = surface.get(('HPBL', 'surface'), float('nan'))
    cb = surface.get(('HGT', 'cloud base'), float('nan'))
    ct = surface.get(('HGT', 'cloud top'), float('nan'))
    def sane_height(value):
        return value if math.isfinite(value) and ground <= value <= 16000 else float('nan')
    cb, ct = sane_height(cb), sane_height(ct)
    # Output is from model grid; pressure levels under local terrain are excluded.
    layers = [(ground + 2.0, temp, humidity, u10, v10)]
    for level in PRESSURE_LEVELS:
        key = f'{level} mb'
        z = require(pressure, 'HGT', key)
        if z <= ground + 10:
            continue
        layers.append((z, require(pressure, 'TMP', key) - 273.15,
                       require(pressure, 'RH', key), require(pressure, 'UGRD', key),
                       require(pressure, 'VGRD', key)))
    layers.sort()
    if len(layers) < 4 or layers[-1][0] < ground + 2 + PROFILE_TOP_AGL_M:
        raise ValueError('Not enough above-ground HRRR pressure levels for 2 km profile')
    zs = np.asarray([r[0] for r in layers], dtype=float)
    if np.min(np.diff(zs)) < 1:
        raise ValueError('Degenerate pressure-level geopotential heights')
    zgrid = np.linspace(ground + 2, ground + 2 + PROFILE_TOP_AGL_M, PROFILE_LEVELS)
    interp = lambda column, z: float(np.interp(z, zs, [r[column] for r in layers]))
    # Four independently supplied vertical fields. CLWMR is not in the
    # retrieved pressure inventory, so do not invent a fifth profile channel.
    prof = np.asarray([
        [interp(k, z) for z in zgrid] for k in range(1, 5)
    ], dtype=np.float32)
    hr = 2 * math.pi * (local.hour / 24)
    yr = 2 * math.pi * (local.timetuple().tm_yday / 365.25)
    row = np.asarray([
        temp, temp - dew, humidity, low, mid, high, math.log1p(max(0, vis)),
        pbl, cb, ct, u10, v10,
        interp(1, ground+302) - temp, interp(1, ground+752) - temp,
        interp(2, ground+302), interp(2, ground+752),
        interp(3, ground+302), interp(4, ground+302),
        float(lead), math.sin(hr), math.cos(hr), math.sin(yr), math.cos(yr)
    ], dtype=np.float32)
    if len(row) != len(FEATURE_NAMES) or not np.isfinite(prof).all():
        raise ValueError('Invalid HRRR feature/profile dimensions or values')
    direction = math.degrees(math.atan2(-u10, -v10)) % 360
    return {
        'timestamp': valid.isoformat().replace('+00:00', 'Z'),
        'run_utc': init.isoformat().replace('+00:00', 'Z'),
        'lead_hours': float(lead), 'local_time': local.isoformat(),
        'features': row.tolist(), 'profile': prof.tolist(),
        'observables': {
            'lowClouds': low, 'midClouds': mid, 'highClouds': high,
            'spatial_cloud_samples': surface.get('_spatial_cloud_samples'),
            'surfTemp': temp, 'dewPoint': dew, 'rh': humidity,
            'tempDelta': interp(1, ground+302)-temp,
            'windSpeed': math.hypot(u10, v10)*2.23693629, 'windDir': direction,
            'forecast_visibility_m': vis,
            'forecast_terrain_ft_msl': ground*3.280839895,
            'forecast_boundary_layer_height_m': pbl if math.isfinite(pbl) else None,
            'forecast_cloud_base_ft_msl': cb*3.28084 if math.isfinite(cb) else None,
            'forecast_cloud_top_ft_msl': ct*3.28084 if math.isfinite(ct) else None,
        }
    }


def fetch_point(init, fxx, scratch):
    s = download_product(init, fxx, 'sfc', SURFACE_REGEX, scratch, spatial=True)
    p = download_product(init, fxx, 'prs', PRESSURE_REGEX, scratch)
    return build_row(init, fxx, s, p)


def load_jsonl(path):
    if not Path(path).exists():
        return []
    with open(path) as stream:
        return [json.loads(line) for line in stream if line.strip()]


def write_jsonl(path, rows, mode='a'):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, mode) as stream:
        for row in rows:
            stream.write(json.dumps(row, allow_nan=True) + '\n')


def historical_pairs(start, end, run_hour, leads):
    cur = start
    while cur <= end:
        init = datetime(cur.year, cur.month, cur.day, run_hour, tzinfo=timezone.utc)
        for lead in leads:
            if not 0 <= lead < MAX_LEAD_HOURS:
                raise ValueError('Lead must be 0..39 hours')
            # HRRRv3 extended runs were only 36h; HRRRv4 began 2020-12-02.
            if init < datetime(2020, 12, 2, tzinfo=timezone.utc) and lead > 36:
                continue
            yield init, lead
        cur += timedelta(days=1)


def collect(pairs, output, scratch, max_pairs=8):
    output = Path(output)
    seen = {(r['run_utc'], int(r['lead_hours'])) for r in load_jsonl(output)}
    completed = 0
    for init, fxx in pairs:
        key = (init.isoformat().replace('+00:00', 'Z'), fxx)
        if key in seen:
            continue
        if max_pairs is not None and completed >= max_pairs:
            break
        print(f'HRRR {init:%Y-%m-%d %HZ} F{fxx:02d} -> {output}', flush=True)
        row = fetch_point(init, fxx, scratch)
        write_jsonl(output, [row])
        completed += 1
        seen.add(key)
    print(f'New pairs: {completed}; total in cache: {len(seen)}; JSONL: {output}')


def inspect(date_str, fxx):
    from herbie import Herbie
    init = datetime.fromisoformat(date_str).replace(tzinfo=timezone.utc)
    for product, regex in (('sfc', SURFACE_REGEX), ('prs', PRESSURE_REGEX)):
        h = Herbie(init.strftime('%Y-%m-%d %H:%M'), model='hrrr',
                   product=product, fxx=fxx)
        inv = h.inventory(search=regex)
        if inv is None or inv.empty:
            raise RuntimeError(f'No {product} fields matched')
        print(f'\n{product}: {len(inv)} indexed fields to selectively download')
        print(inv[['variable','level']].to_string(index=False))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    i = sub.add_parser('inspect', help='Only inspect .idx, zero GRIB data downloaded')
    i.add_argument('--date', default='2025-01-15')
    i.add_argument('--fxx', type=int, default=36)
    c = sub.add_parser('collect', help='Historical HRRR point samples; resumable')
    c.add_argument('--start', type=date.fromisoformat, required=True)
    c.add_argument('--end', type=date.fromisoformat, required=True)
    c.add_argument('--run-hour', type=int, choices=[0,6,12,18], default=0)
    c.add_argument('--lead-hours', default='24,30,36')
    c.add_argument('--output', type=Path, default=DATA_DIR/'hrrr_samples.jsonl')
    c.add_argument('--max-pairs', type=int, default=8, help='Safety cap per invocation; default 8')
    c.add_argument('--all', action='store_true', help='Explicitly disable per-run limit')
    l = sub.add_parser('live', help='Extract a sparse point forecast for local website')
    l.add_argument('--lead-hours', default='6,9,12,15,18,21,24,27,30,33,36,39')
    l.add_argument('--output', type=Path, default=DATA_DIR/'hrrr_live.jsonl')
    l.add_argument('--morning-hours', default='', help='Optional Boulder local morning hours, e.g. 5,6,7,8,9')
    args = ap.parse_args()
    if args.command == 'inspect':
        inspect(args.date, args.fxx)
        return
    leads = [int(x) for x in args.lead_hours.split(',')]
    if any(n < 0 or n >= MAX_LEAD_HOURS for n in leads):
        ap.error('Allowed lead hours are 0 to 39')
    scratch = DATA_DIR/'hrrr_tmp'
    if args.command == 'collect':
        if args.start > args.end:
            ap.error('--end must follow --start')
        if datetime.combine(args.end, datetime.min.time(), tzinfo=timezone.utc) > datetime.now(timezone.utc) - timedelta(days=3):
            ap.error('Historical verification needs run dates at least 3 days old')
        pairs = historical_pairs(args.start, args.end, args.run_hour, leads)
        collect(pairs, args.output, scratch, None if args.all else args.max_pairs)
    else:
        now = datetime.now(timezone.utc)
        candidate = now - timedelta(hours=7)
        init = candidate.replace(hour=(candidate.hour//6)*6, minute=0, second=0, microsecond=0)
        # Drops already elapsed forecast hours. Early runs can have dissemination lag.
        # Optionally include exact Boulder dawn hours (rather than only a
        # sparse set of UTC lead-times) to preserve retrospective verification.
        if args.morning_hours:
            from datetime import time
            from zoneinfo import ZoneInfo
            from .config import TIMEZONE
            local_now = now.astimezone(ZoneInfo(TIMEZONE))
            morning_hours = [int(x) for x in args.morning_hours.split(',')]
            if any(h < 0 or h > 23 for h in morning_hours):
                ap.error('--morning-hours values must be 0..23')
            for day in range(4):
                local_day = local_now.date() + timedelta(days=day)
                for hour in morning_hours:
                    local_target = datetime.combine(local_day, time(hour), tzinfo=ZoneInfo(TIMEZONE))
                    valid_utc = local_target.astimezone(timezone.utc)
                    lead = (valid_utc - init).total_seconds() / 3600
                    if valid_utc > now and lead.is_integer() and 0 <= lead < MAX_LEAD_HOURS:
                        leads.append(int(lead))
        pairs = [(init, fxx) for fxx in sorted(set(leads))
                 if init + timedelta(hours=fxx) > now]
        if not pairs:
            ap.error('No requested lead times are in the future')
        # Don't destroy a working live forecast cache if a download fails.
        staging = args.output.with_suffix(args.output.suffix + '.next')
        staging.unlink(missing_ok=True)
        collect(pairs, staging, scratch, max_pairs=None)
        staging.replace(args.output)
        # Capture the precise instant the complete cache became publishable by
        # the website, not the earlier partial-download time.
        from .history import capture_published_live
        counts = capture_published_live(load_jsonl(args.output),
                                        published_at=datetime.now(timezone.utc),
                                        db_path=DATA_DIR / 'forecast_history.sqlite3')
        print(f'Captured forecast history in data/forecast_history.sqlite3: {counts}')


if __name__ == '__main__':
    main()
