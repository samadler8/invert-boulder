"""Transparent, uncalibrated HRRR low-cloud/inversion-setup *index*.

This is not a probability, nor is it a direct measurement of an inversion or
above-cloud summit conditions. It intentionally requires no training artifacts.
Thresholds and weights are hand-selected hypotheses to be tested against METAR
and, eventually, independent mountain observations. Version them before tuning.
"""
import math
from datetime import datetime, timezone

from .config import FEATURE_NAMES, LANDMARKS_FT, OBS_LAT, OBS_LON

VERSION = 'hrrr-setup-index-v3-smooth-sky'
WEIGHTS = {
    'low_level_stability': 0.29,
    'near_surface_moisture': 0.24,
    'forecast_low_cloud': 0.20,
    'light_wind': 0.12,
    'shallow_mixed_layer': 0.10,
    'reduced_visibility': 0.05,
}


def clamp(x):
    return max(0.0, min(1.0, x))


def ramp(x, low, high):
    """Map low -> 0, high -> 1; handles reversed ranges."""
    return clamp((x - low) / (high - low))


def finite(value):
    try:
        val = float(value)
        return val if math.isfinite(val) else None
    except (ValueError, TypeError, OverflowError):
        return None


def forecast_provenance(row):
    """Link directly to the small original NOAA HRRR GRIB index inventories.

    These are model SOURCE inventories, not copies of the precise extracted
    grid-cell reading, and not independent meteorological observations.
    """
    issued = datetime.fromisoformat(str(row['run_utc']).replace('Z', '+00:00'))
    if issued.tzinfo is None:
        raise ValueError('HRRR run timestamp must be timezone aware')
    issued = issued.astimezone(timezone.utc)
    lead = int(row['lead_hours'])
    if lead < 0 or lead > 48 or lead != float(row['lead_hours']):
        raise ValueError('Invalid HRRR GRIB lead for source URL')
    base = ('https://noaa-hrrr-bdp-pds.s3.amazonaws.com/'
            f'hrrr.{issued:%Y%m%d}/conus/hrrr.t{issued:%H}z.')
    valid = datetime.fromisoformat(str(row['timestamp']).replace('Z', '+00:00'))
    return {
        'model': 'NOAA HRRR, CONUS nearest model grid cell to KBDU',
        'run_utc': issued.isoformat().replace('+00:00', 'Z'),
        'valid_utc': valid.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'forecast_lead_hours': lead,
        'requested_latitude': OBS_LAT, 'requested_longitude': OBS_LON,
        'surface_inventory_url': base + f'wrfsfcf{lead:02d}.grib2.idx',
        'pressure_inventory_url': base + f'wrfprsf{lead:02d}.grib2.idx',
        'model_documentation_url': 'https://rapidrefresh.noaa.gov/hrrr/',
        'important_note': ('Inventory links list all fields in the issued HRRR file. '
                           'The numerical values shown here were decoded at the nearest '
                           'HRRR grid cell near KBDU, not measured at the airport. '
                           'The AWS inventory does not itself display extracted point values.'),
    }


def reading(label, value, unit, field):
    """Primitive JSON values are safe to archive without future recomputation."""
    return {'label': label, 'value': finite(value), 'unit': unit, 'field': field}


def evaluate(row):
    """Compute a 0..100 *favorability index* for one issued HRRR forecast.

    The index combines cold-air stability, moisture, predicted low cloud,
    light wind, a shallow HRRR boundary layer, and low predicted visibility.
    Forecast cloud-top and site elevations are reported as separate diagnostics:
    they are NOT independently verified and do not affect this index.
    """
    features = row.get('features')
    if features is None or len(features) != len(FEATURE_NAMES):
        raise ValueError('HRRR heuristic expects the active feature schema')
    values = {key: finite(value) for key, value in zip(FEATURE_NAMES, features)}
    obs = row.get('observables') or {}

    def score(value, low, high, *, default=0.5):
        return ramp(value, low, high) if value is not None else default

    # HRRR temperature rise from 2 m to about 300 m AGL: a coarse inversion
    # proxy, not a resolved local inversion sounding.
    stable = score(values['t_delta_300m'], -1.5, 2.0)
    rh = score(values['relative_humidity_2m'], 65, 98)
    dew = score(values['dewpoint_depression_c'], 7, 0)
    moisture = 0.6 * rh + 0.4 * dew
    cloud = score(values['low_cloud_pct'], 5, 95)
    u, v = values['wind_u_10m_ms'], values['wind_v_10m_ms']
    wind_ms = math.hypot(u, v) if u is not None and v is not None else None
    wind = score(wind_ms, 9, 1.5)
    pbl = score(values['forecast_pbl_height_m'], 1400, 150)
    log_visibility = values['forecast_visibility_log_m']
    vis = math.expm1(log_visibility) if log_visibility is not None else None
    visibility = score(vis, 16000, 1200)
    components = {
        'low_level_stability': stable, 'near_surface_moisture': moisture,
        'forecast_low_cloud': cloud, 'light_wind': wind,
        'shallow_mixed_layer': pbl, 'reduced_visibility': visibility,
    }
    index = round(100 * sum(WEIGHTS[key] * val for key, val in components.items()))
    if index >= 75:
        category = 'Very favorable setup'
    elif index >= 55:
        category = 'Favorable setup'
    elif index >= 35:
        category = 'Mixed signals'
    else:
        category = 'Unfavorable setup'

    reasons = []
    delta = values['t_delta_300m']
    if delta is not None:
        reasons.append(f"HRRR 300 m warming: {delta:+.1f} C" if delta > 0 else
                       f"HRRR 300 m temperature change: {delta:+.1f} C")
    if values['relative_humidity_2m'] is not None:
        reasons.append(f"Surface relative humidity: {values['relative_humidity_2m']:.0f}%")
    if values['low_cloud_pct'] is not None:
        reasons.append(f"HRRR low-cloud coverage: {values['low_cloud_pct']:.0f}%")
    if wind_ms is not None:
        reasons.append(f'10 m wind: {wind_ms * 2.23693629:.0f} mph')

    base_ft = finite(obs.get('forecast_cloud_base_ft_msl'))
    top_ft = finite(obs.get('forecast_cloud_top_ft_msl'))
    if base_ft is not None and top_ft is not None and top_ft < base_ft:
        # The HRRR products may describe inconsistent or different cloud fields.
        top_ft = None
    sites = []
    for name, elevation_ft in LANDMARKS_FT.items():
        if top_ft is None:
            relation = 'unknown'
        elif elevation_ft > top_ft + 450:
            relation = 'above_modeled_cloud_top'
        elif elevation_ft < top_ft - 450:
            relation = 'below_modeled_cloud_top'
        else:
            relation = 'near_modeled_cloud_top'
        sites.append({'name': name, 'elevation_ft': elevation_ft,
                      'relative_to_modeled_cloud_top': relation,
                      'scenic_probability': None})

    # Store the exact raw inputs and the contribution to the score. This does
    # not change the v1 mathematical heuristic or retroactively change scores.
    descriptions = {
        'low_level_stability': ('Low-level stability',
            'A +2 C temperature rise from the surface to about 300 m earns full points; -1.5 C or less earns none. The HRRR profile is a coarse proxy, not a measured inversion.',
            [reading('Temperature change at ~300 m AGL', delta, '°C', 't_delta_300m')]),
        'near_surface_moisture': ('Near-surface moisture',
            '60% of this factor comes from RH (65 to 98%); 40% from dew-point depression (7 to 0 C). Both describe closely related moisture conditions.',
            [reading('2 m relative humidity', values['relative_humidity_2m'], '%', 'relative_humidity_2m'),
             reading('2 m dew-point depression', values['dewpoint_depression_c'], '°C', 'dewpoint_depression_c')]),
        'forecast_low_cloud': ('Modeled low clouds',
            'HRRR low-cloud coverage from 5% (none) to 95% (full factor). This is a model prediction, not an observation.',
            [reading('Low-cloud coverage', values['low_cloud_pct'], '%', 'low_cloud_pct')]),
        'light_wind': ('Light surface winds',
            'The 10 m wind earns full points at 1.5 m/s or less and none at 9 m/s or more.',
            [reading('10 m wind speed', wind_ms * 2.23693629 if wind_ms is not None else None, 'mph', 'wind_u_10m_ms,wind_v_10m_ms')]),
        'shallow_mixed_layer': ('Shallow boundary layer',
            'The modeled mixing-layer height earns full points at 150 m or below, none at 1400 m or above. This field can be a poor proxy for shallow inversions.',
            [reading('Predicted boundary-layer height', values['forecast_pbl_height_m'], 'm', 'forecast_pbl_height_m')]),
        'reduced_visibility': ('Reduced visibility',
            'Modeled visibility earns full points at 1200 m or less and none at 16000 m or more.',
            [reading('Predicted visibility', vis / 1609.344 if vis is not None else None, 'miles', 'forecast_visibility_log_m')]),
    }
    breakdown = []
    for key, weight in WEIGHTS.items():
        title, rationale, readings = descriptions[key]
        breakdown.append({
            'key': key, 'label': title,
            'weight_pct': round(100 * weight, 2),
            'factor_score': round(100 * components[key], 1),
            'weighted_points': round(100 * weight * components[key], 2),
            'max_points': round(100 * weight, 2),
            'readings': readings, 'scoring_rule': rationale,
            'has_missing_readings': any(r['value'] is None for r in readings),
        })
    extra_readings = [
        reading('2 m air temperature', values['temperature_2m_c'], '°C', 'temperature_2m_c'),
        reading('2 m dew-point depression', values['dewpoint_depression_c'], '°C', 'dewpoint_depression_c'),
        reading('Mid-level cloud coverage', values['mid_cloud_pct'], '%', 'mid_cloud_pct'),
        reading('High-level cloud coverage', values['high_cloud_pct'], '%', 'high_cloud_pct'),
        reading('Temperature change at ~750 m AGL', values['t_delta_750m'], '°C', 't_delta_750m'),
        reading('Modeled cloud base', base_ft, 'ft MSL', 'forecast_cloud_base_ft_msl'),
        reading('Modeled cloud top', top_ft, 'ft MSL', 'forecast_cloud_top_ft_msl'),
    ]
    provenance = forecast_provenance(row)
    from .scenic import evaluate_scenic
    scenic = evaluate_scenic(row, index)
    for site in sites:
        matched = next((s for s in scenic['scenic_site_details'] if s['name'] == site['name']), None)
        if matched is not None:
            site.update(matched)

    return {
        **scenic,
        'heuristic_score': index,
        'heuristic_unrounded_score': round(100 * sum(WEIGHTS[key] * val for key, val in components.items()), 2),
        'heuristic_breakdown': breakdown,
        'heuristic_extra_readings': extra_readings,
        'forecast_source': provenance,
        'heuristic_category': category,
        'heuristic_version': VERSION,
        'heuristic_components': {key: round(100 * val) for key, val in components.items()},
        'heuristic_reasons': reasons,
        'forecast_inversion_warming_signal': delta is not None and delta > 0.4,
        'forecast_cloud_base_ft_msl': round(base_ft) if base_ft is not None else None,
        'forecast_cloud_top_ft_msl': round(top_ft) if top_ft is not None else None,
        'landmarks': sites,
    }
