"""Offline Boulder-area solar times, using the NOAA-style sunrise equation.

Astronomical estimates, not forecast weather; civil twilight is -6 degrees,
standard sunrise/sunset is -0.833 degrees, golden-hour endpoint +6 degrees.
"""
import math
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .config import TIMEZONE

BOULDER_LAT = 40.0150
BOULDER_LON = -105.2705


def _solar_event(local_day: date, lat: float, lon: float,
                 altitude_degrees: float, rising: bool):
    n = local_day.timetuple().tm_yday
    lon_hour = lon / 15.0
    t = n + ((6 - lon_hour) / 24 if rising else (18 - lon_hour) / 24)
    mean_anomaly = 0.9856 * t - 3.289
    m = math.radians(mean_anomaly)
    true_lon = (mean_anomaly + 1.916 * math.sin(m)
                + 0.020 * math.sin(2 * m) + 282.634) % 360
    true_rad = math.radians(true_lon)
    ra = math.degrees(math.atan(0.91764 * math.tan(true_rad))) % 360
    ra += math.floor(true_lon / 90) * 90 - math.floor(ra / 90) * 90
    ra /= 15
    sin_dec = 0.39782 * math.sin(true_rad)
    cos_dec = math.cos(math.asin(sin_dec))
    latitude = math.radians(lat)
    cos_hour_angle = ((math.cos(math.radians(90 - altitude_degrees))
                       - sin_dec * math.sin(latitude))
                      / (cos_dec * math.cos(latitude)))
    if not -1 <= cos_hour_angle <= 1:
        return None
    angle = math.degrees(math.acos(cos_hour_angle))
    hour_angle = (360 - angle if rising else angle) / 15
    local_mean_time = hour_angle + ra - 0.06571 * t - 6.622
    utc_hour = (local_mean_time - lon_hour) % 24
    local_tz = ZoneInfo(TIMEZONE)
    result = (datetime(local_day.year, local_day.month, local_day.day,
                       tzinfo=timezone.utc) + timedelta(hours=utc_hour)).astimezone(local_tz)
    # Boulder sunset is usually UTC on the following day; match the local day.
    if result.date() < local_day:
        result = (result.astimezone(timezone.utc) + timedelta(days=1)).astimezone(local_tz)
    if result.date() > local_day:
        result = (result.astimezone(timezone.utc) - timedelta(days=1)).astimezone(local_tz)
    return result


def solar_day(local_day: date, lat=BOULDER_LAT, lon=BOULDER_LON):
    events = {
        'civil_dawn': _solar_event(local_day, lat, lon, -6, True),
        'sunrise': _solar_event(local_day, lat, lon, -0.833, True),
        'morning_golden_end': _solar_event(local_day, lat, lon, 6, True),
        'evening_golden_start': _solar_event(local_day, lat, lon, 6, False),
        'sunset': _solar_event(local_day, lat, lon, -0.833, False),
        'civil_dusk': _solar_event(local_day, lat, lon, -6, False),
    }
    sunrise, sunset = events['sunrise'], events['sunset']
    return {
        'date': local_day.isoformat(),
        'coordinates': {'latitude': lat, 'longitude': lon},
        'timezone': TIMEZONE,
        'source': 'Astronomical calculation (NOAA-style sunrise equation), not HRRR',
        'daylight_minutes': round((sunset - sunrise).total_seconds() / 60) if sunrise and sunset else None,
        **{name: (value.isoformat() if value else None) for name, value in events.items()},
    }
