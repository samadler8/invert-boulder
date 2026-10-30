"""HRRR model contract. Never reuse models trained on older GFS features."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / 'models'
DATA_DIR = ROOT / 'data'
TIMEZONE = 'America/Denver'
MODEL_SOURCE = 'hrrr'
MODEL_VERSION = 'hrrr-kbdu-low-ceiling-v4'
MAX_LEAD_HOURS = 40  # ML contract: keep existing trained-model semantics unchanged
DISPLAY_MAX_LEAD_HOURS = 49  # HRRR extended cycles provide f00-f48 for heuristic display
PRESSURE_LEVELS = (800, 750, 700, 650, 600)
PROFILE_CHANNELS = ('temperature_c', 'rh_pct', 'u_ms', 'v_ms')
PROFILE_LEVELS = 25
PROFILE_TOP_AGL_M = 2000
LANDMARKS_FT = {'Boulder': 5400, 'First Flatiron': 7258, 'Green Mountain': 8133}
OBS_STATION, OBS_NETWORK = 'BDU', 'CO_ASOS'
OBS_STATION_ELEV_FT = 5288
OBS_LAT, OBS_LON = 40.0394, -105.2250
FEATURE_NAMES = (
    'temperature_2m_c', 'dewpoint_depression_c', 'relative_humidity_2m',
    'low_cloud_pct', 'mid_cloud_pct', 'high_cloud_pct',
    'forecast_visibility_log_m', 'forecast_pbl_height_m',
    'hrrr_forecast_cloud_base_msl_m', 'hrrr_forecast_cloud_top_msl_m',
    'wind_u_10m_ms', 'wind_v_10m_ms',
    't_delta_300m', 't_delta_750m', 'rh_300m', 'rh_750m',
    'wind_u_300m_ms', 'wind_v_300m_ms',
    'lead_hours', 'hour_sin', 'hour_cos', 'year_sin', 'year_cos',
)
SCENIC_FEATURE_NAMES = FEATURE_NAMES + ('target_elevation_ft',)
