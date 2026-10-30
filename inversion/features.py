"""Strict, shared feature assembly for training and live prediction."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import math
import numpy as np

from .config import (FEATURE_NAMES, PRESSURE_LEVELS, PROFILE_LEVELS,
                     PROFILE_TOP_AGL_M, SURFACE_FIELDS, PROFILE_FIELDS,
                     TIMEZONE)


def uv(speed_kmh, bearing_deg):
    """Meteorological direction is where wind comes FROM."""
    angle = math.radians(float(bearing_deg))
    speed = float(speed_kmh) / 3.6
    return -speed * math.sin(angle), -speed * math.cos(angle)


def row_at(data, i):
    """Return None for incomplete/below-ground profiles; no zero imputation."""
    h = data['hourly']
    required = SURFACE_FIELDS + PROFILE_FIELDS
    try:
        values = {k: float(h[k][i]) for k in required}
        if not all(np.isfinite(x) for x in values.values()):
            return None
        timestamp = datetime.fromisoformat(h['time'][i])
        # Request UTC explicitly. Naive ISO Open-Meteo timestamps are UTC.
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        timestamp = timestamp.astimezone(timezone.utc)
        local = timestamp.astimezone(ZoneInfo(TIMEZONE))
        z_surface = float(data['elevation']) + 2.0
        z = [z_surface]
        temperature = [values['temperature_2m']]
        humidity = [values['relative_humidity_2m']]
        u0, v0 = uv(values['wind_speed_10m'], values['wind_direction_10m'])
        u, v = [u0], [v0]
        for p in PRESSURE_LEVELS:
            z_p = values[f'geopotential_height_{p}hPa']
            # This altitude must be above local ground. 850 hPa often isn't.
            if z_p < z_surface + 5:
                continue
            up, vp = uv(values[f'wind_speed_{p}hPa'],
                        values[f'wind_direction_{p}hPa'])
            z.append(z_p)
            temperature.append(values[f'temperature_{p}hPa'])
            humidity.append(values[f'relative_humidity_{p}hPa'])
            u.append(up)
            v.append(vp)
        order = np.argsort(z)
        zs = np.asarray(z)[order]
        if len(zs) < 4 or zs[-1] < z_surface + PROFILE_TOP_AGL_M:
            return None
        if np.any(np.diff(zs) < 1):
            return None
        heights = np.linspace(z_surface, z_surface + PROFILE_TOP_AGL_M,
                              PROFILE_LEVELS, dtype=np.float32)
        profile = np.stack([
            np.interp(heights, zs, np.asarray(channel)[order])
            for channel in (temperature, humidity, u, v)
        ]).astype(np.float32)
        t300 = float(np.interp(z_surface + 300, zs, np.asarray(temperature)[order]))
        t750 = float(np.interp(z_surface + 750, zs, np.asarray(temperature)[order]))
        rh300 = float(np.interp(z_surface + 300, zs, np.asarray(humidity)[order]))
        rh750 = float(np.interp(z_surface + 750, zs, np.asarray(humidity)[order]))
        u300 = float(np.interp(z_surface + 300, zs, np.asarray(u)[order]))
        v300 = float(np.interp(z_surface + 300, zs, np.asarray(v)[order]))
        year_phase = 2 * math.pi * (local.timetuple().tm_yday / 365.25)
        hour_phase = 2 * math.pi * ((local.hour + local.minute / 60) / 24)
        features = np.asarray([
            values['temperature_2m'],
            values['temperature_2m'] - values['dew_point_2m'],
            values['relative_humidity_2m'],
            values['cloud_cover_low'], values['cloud_cover_mid'],
            values['cloud_cover_high'], u0, v0,
            t300 - values['temperature_2m'],
            t750 - values['temperature_2m'],
            rh300, rh750, u300, v300,
            math.sin(hour_phase), math.cos(hour_phase),
            math.sin(year_phase), math.cos(year_phase),
        ], dtype=np.float32)
        assert len(features) == len(FEATURE_NAMES)
        visibility = h.get('visibility', [None] * len(h['time']))[i]
        return {
            'timestamp': timestamp.isoformat().replace('+00:00','Z'),
            'local_time': local.isoformat(),
            'features': features, 'profile': profile,
            'visibility_m': float(visibility) if visibility is not None else None,
            'observables': {
                'lowClouds': values['cloud_cover_low'],
                'midClouds': values['cloud_cover_mid'],
                'highClouds': values['cloud_cover_high'],
                'surfTemp': values['temperature_2m'],
                'dewPoint': values['dew_point_2m'],
                'rh': values['relative_humidity_2m'],
                'tempDelta': t300 - values['temperature_2m'],
                'windSpeed': values['wind_speed_10m'] / 1.609344,
                'windDir': values['wind_direction_10m'],
            },
        }
    except (ValueError, KeyError, IndexError, TypeError, AssertionError):
        return None


def rows_from_data(response):
    times = response.get('hourly', {}).get('time', [])
    return [r for i in range(len(times)) if (r := row_at(response, i)) is not None]


def proxy_label(row):
    """Model-produced low-cloud/visibility proxy, NOT a verified ground event.

    Clouds aloft are also required to be limited; physically this is only a
    rough approximation to 'a sea of clouds while peaks are clear'.
    """
    v = row['visibility_m']
    if v is None or not np.isfinite(v):
        return None
    o = row['observables']
    return int(v <= 1500 and o['lowClouds'] >= 55
               and (o['midClouds'] + o['highClouds']) / 2 <= 45)
