"""Centralized meteorological and model contract. Changes require retraining."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / 'models'
DATA_DIR = ROOT / 'data'
BOULDER_LAT, BOULDER_LON = 40.015, -105.2705
TIMEZONE = 'America/Denver'
# All pressure levels used must lie above Boulder (~1,650 m ASL).
# GFS has these pressure levels; HRRR/GFS seamless blends are deliberately avoided.
PRESSURE_LEVELS = (800, 750, 700, 650, 600)
PROFILE_CHANNELS = ('temperature_c', 'relative_humidity_pct', 'u_wind_ms', 'v_wind_ms')
PROFILE_LEVELS = 25
PROFILE_TOP_AGL_M = 2000
MODEL_SOURCE = 'gfs_global'
MODEL_VERSION = 'boulder-gfs-profile-v1'
SURFACE_FIELDS = (
    'temperature_2m', 'dew_point_2m', 'relative_humidity_2m',
    'cloud_cover_low', 'cloud_cover_mid', 'cloud_cover_high',
    'wind_speed_10m', 'wind_direction_10m',
)
PROFILE_FIELDS = tuple(
    f'{kind}_{p}hPa'
    for p in PRESSURE_LEVELS
    for kind in ('temperature', 'relative_humidity', 'wind_speed',
                 'wind_direction', 'geopotential_height')
)
# Visibility is *only* a proxy-label source, never a model input.
LABEL_FIELDS = ('visibility',)
HOURLY_FIELDS = SURFACE_FIELDS + PROFILE_FIELDS + LABEL_FIELDS
FEATURE_NAMES = (
    'temperature_2m', 'dewpoint_depression', 'relative_humidity_2m',
    'low_cloud_pct', 'mid_cloud_pct', 'high_cloud_pct',
    'wind_u_10m_ms', 'wind_v_10m_ms',
    't_delta_300m', 't_delta_750m', 'rh_300m', 'rh_750m',
    'wind_u_300m_ms', 'wind_v_300m_ms',
    'hour_sin', 'hour_cos', 'year_sin', 'year_cos',
)
