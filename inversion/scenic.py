"""Uncalibrated *scenic* suitability index, distinct from airport low-cloud odds.

We seek a LOW cloud deck covering Boulder with a DRY transition BELOW a
specific summit AND little mid/high cloud above it. RH is a proxy, NOT a
measured cloud top. A single HRRR column cloud-top value is not the low-deck
cloud top when higher layers exist. No summit observations train this score.

All thresholds are explicit and provisional; calibrate against independent
Boulder/foothills imagery before calling these event probabilities.
"""
import math

from .config import (FEATURE_NAMES, LANDMARKS_FT, OBS_STATION_ELEV_FT,
                     PROFILE_LEVELS, PROFILE_TOP_AGL_M)

VERSION = 'hrrr-scenic-suitability-v4-corridor-payload'
BOULDER_FT_MSL = LANDMARKS_FT['Boulder']
MAX_DESIRED_DECK_TOP_FT_MSL = BOULDER_FT_MSL + 2000
FT_PER_M = 3.280839895


def finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError, OverflowError):
        return None


def ramp(value, low, high):
    return max(0., min(1., (value - low) / (high - low)))


def profile_rh_at(row, elevation_ft, terrain_ft):
    """Interpolate the stored HRRR pressure-profile RH; never extrapolate."""
    profile = row.get('profile')
    if not isinstance(profile, (list, tuple)) and not hasattr(profile, 'shape'):
        return None
    try:
        channel = profile[1]  # v4 profile schema: temp, RH, U, V.
        if len(channel) != PROFILE_LEVELS:
            return None
        m_agl = (elevation_ft - terrain_ft) / FT_PER_M
        if not 0 <= m_agl <= PROFILE_TOP_AGL_M:
            return None
        at = m_agl * (PROFILE_LEVELS - 1) / PROFILE_TOP_AGL_M
        i = min(int(at), PROFILE_LEVELS - 2)
        a, b = finite(channel[i]), finite(channel[i + 1])
        if a is None or b is None:
            return None
        return (1 - (at - i)) * a + (at - i) * b
    except (IndexError, KeyError, TypeError, ValueError):
        return None


def moisture_transition_ft(row, terrain_ft, low_cloud, surface_rh):
    """First sustained drying (<80% RH): diagnostic, never a measured cloud top."""
    if low_cloud is None or surface_rh is None or low_cloud < 50 or surface_rh < 85:
        return None
    profile = row.get('profile')
    if profile is None:
        return None
    try:
        rh = [finite(x) for x in profile[1]]
    except (IndexError, TypeError):
        return None
    if len(rh) != PROFILE_LEVELS or any(x is None for x in rh):
        return None
    for i in range(1, PROFILE_LEVELS - 2):
        elevation = terrain_ft + i * PROFILE_TOP_AGL_M / (PROFILE_LEVELS - 1) * FT_PER_M
        if elevation > LANDMARKS_FT['Green Mountain']:
            break
        if rh[i] < 80 and rh[i + 1] < 85 and rh[i + 2] < 85:
            return round(elevation)
    return None


def evaluate_scenic(row, low_cloud_index):
    """Evaluate scenic setup for Green Mountain and First Flatiron separately.

    Scores represent a product of necessary ingredients, not event frequencies.
    Missing essential measurements return None, NEVER an optimistic score.
    High middle/upper cloud fractions strongly but smoothly penalize the
    scenic index, without an arbitrary 85% all-or-nothing threshold.
    """
    features = row.get('features')
    if features is None or len(features) != len(FEATURE_NAMES):
        raise ValueError('Scenic assessment requires HRRR v4 tabular features')
    feature = {key: finite(value) for key, value in zip(FEATURE_NAMES, features)}
    obs = row.get('observables') or {}
    base = finite(obs.get('forecast_cloud_base_ft_msl'))
    overall_top = finite(obs.get('forecast_cloud_top_ft_msl'))
    low = feature['low_cloud_pct']
    mid = feature['mid_cloud_pct']
    high = feature['high_cloud_pct']
    surface_rh = feature['relative_humidity_2m']
    terrain = finite(obs.get('forecast_terrain_ft_msl'))
    terrain_is_station_proxy = terrain is None
    if terrain is None:
        # Old HRRR point caches lack grid elevation; make the fallback explicit.
        terrain = OBS_STATION_ELEV_FT

    low_presence = (min(low_cloud_index / 100., ramp(low, 30, 95))
                    if low is not None else None)
    base_fit = ramp(base, MAX_DESIRED_DECK_TOP_FT_MSL, BOULDER_FT_MSL + 300) if base is not None else None
    # Missing base with essentially no low clouds is a definite *unfavorable*
    # scenic setup; otherwise we cannot decide whether the deck is low enough.
    if base_fit is None and low is not None and low < 25:
        base_fit = 0.0

    # Independent v2 SCENIC hypothesis: continuously decrease the score for
    # cloud above the peaks, but never turn a cloud fraction into a binary
    # veto. Middle cloud is penalized more heavily than high cloud, because
    # high-cloud coverage alone does not reveal optical thickness (cirrus).
    # The factors are NOT clear-sky probabilities, nor are the two layers
    # statistically independent. Explicit numbers must be backtested.
    mid_sky = math.exp(-2.4 * (max(0., min(100., mid)) / 100.) ** 1.7) if mid is not None else None
    high_sky = math.exp(-1.5 * (max(0., min(100., high)) / 100.) ** 1.7) if high is not None else None
    upper_clear = mid_sky * high_sky if mid_sky is not None and high_sky is not None else None

    # Optional neighborhood values are extracted from the *same* HRRR surface
    # GRIB subset, not a separate download. They describe model-grid disagreement
    # around KBDU and are diagnostic only: no location-specific summit label.
    neighborhood = row.get('observables', {}).get('spatial_cloud_samples') or []
    neighborhood_stats = {'available': False, 'count': 0, 'cloud_spread_pct': {},
                          'classification': 'unavailable', 'note':
                          'Nearby HRRR cloud-grid samples were not collected for this forecast.'}
    if isinstance(neighborhood, list):
        # Include KBDU center: the neighborhood spread should not exclude the
        # very grid cell used by the heuristic itself.
        center_sample = {'label': 'KBDU center',
                         'low_cloud_pct': low, 'mid_cloud_pct': mid,
                         'high_cloud_pct': high}
        clean = [center_sample] + [sample for sample in neighborhood if isinstance(sample, dict) and
                 all(finite(sample.get(key)) is not None for key in
                     ('low_cloud_pct', 'mid_cloud_pct', 'high_cloud_pct'))]
        if len(clean) >= 3:
            spans = {key: round(max(float(v[key]) for v in clean) -
                                min(float(v[key]) for v in clean), 1)
                     for key in ('low_cloud_pct', 'mid_cloud_pct', 'high_cloud_pct')}
            upper_spread = max(spans['mid_cloud_pct'], spans['high_cloud_pct'])
            neighborhood_stats = {
                'available': True, 'count': len(clean),
                'cloud_spread_pct': spans,
                'classification': ('high' if upper_spread >= 40 else
                                   'moderate' if upper_spread >= 20 else 'low'),
                'samples': clean,
                'note': ('Model cloud coverage across nearby grid points; '
                         'not measured fog extent or verified summit sky. '
                         'Large spreads suggest location sensitivity.'),
            }
    transition = moisture_transition_ft(row, terrain, low, surface_rh)
    sites = []
    for name, summit in LANDMARKS_FT.items():
        if name == 'Boulder':
            continue
        # First Flatiron needs a deck top below ~6958 ft; Green Mountain can
        # tolerate one as high as 7400 ft (Boulder + 2000 ft).
        desired_top = min(MAX_DESIRED_DECK_TOP_FT_MSL, summit - 300)
        rh_top = profile_rh_at(row, desired_top, terrain)
        rh_summit = profile_rh_at(row, summit, terrain)
        above_end = min(terrain + FT_PER_M * PROFILE_TOP_AGL_M, summit + 1500)
        rh_above = profile_rh_at(row, above_end, terrain)
        dryness_below = ramp(rh_top, 93, 65) if rh_top is not None else None
        dryness_at = ramp(rh_summit, 95, 65) if rh_summit is not None else None
        dryness_above = ramp(rh_above, 95, 70) if rh_above is not None else None
        factors = {
            'low_deck_present': low_presence,
            'low_cloud_base_near_boulder': base_fit,
            'dry_air_by_below_summit': dryness_below,
            'dry_air_at_summit': dryness_at,
            'dry_air_above_summit': dryness_above,
            'mid_high_sky_clear': upper_clear,
        }
        missing = [key for key, value in factors.items() if value is None]
        if missing:
            score = None
            reason = 'Cannot evaluate scenic setup: missing ' + ', '.join(missing).replace('_', ' ')
        else:
            # Humidity is only a proxy for the disappearance of a low cloud.
            # Requiring dry air by desired_top and at summit reduces high scores
            # from very deep clouds; upper cloud cover receives a smooth penalty.
            number = (100 * low_presence * base_fit * upper_clear
                      * (0.10 + 0.90 * dryness_below)
                      * (0.10 + 0.90 * dryness_at)
                      * (0.25 + 0.75 * dryness_above))
            score = round(number)
            if upper_clear <= .15:
                reason = 'Extensive middle/high cloud is forecast; scenic clarity strongly penalized, without a hard zero.'
            elif dryness_below < .30 or dryness_at < .30:
                reason = 'RH profile does not show sufficiently dry air below/at this summit.'
            elif score >= 65:
                reason = 'Low cloud near Boulder, drier air by the summit, and relatively clear upper sky are all forecast.'
            elif score >= 25:
                reason = 'Some scenic ingredients are favorable, but cloud depth or upper sky remains uncertain.'
            else:
                reason = 'One or more necessary scenic ingredients are weak.'
        sites.append({
            'name': name, 'elevation_ft': summit,
            'scenic_heuristic_score': score,
            'scenic_heuristic_reason': reason,
            'desired_dry_by_ft_msl': desired_top,
            'forecast_rh_at_desired_top_pct': round(rh_top, 1) if rh_top is not None else None,
            'forecast_rh_at_summit_pct': round(rh_summit, 1) if rh_summit is not None else None,
            'forecast_rh_above_summit_pct': round(rh_above, 1) if rh_above is not None else None,
            'factors': {key: round(value * 100, 1) if value is not None else None
                        for key, value in factors.items()},
        })
    green = next(s for s in sites if s['name'] == 'Green Mountain')
    flatiron = next(s for s in sites if s['name'] == 'First Flatiron')
    return {
        'scenic_version': VERSION,
        'scenic_heuristic_score': green['scenic_heuristic_score'],
        'scenic_flatiron_score': flatiron['scenic_heuristic_score'],
        'scenic_heuristic_reason': green['scenic_heuristic_reason'],
        'scenic_upper_clear_factor': round(100 * upper_clear, 1) if upper_clear is not None else None,
        'scenic_mid_sky_factor': round(100 * mid_sky, 1) if mid_sky is not None else None,
        'scenic_high_sky_factor': round(100 * high_sky, 1) if high_sky is not None else None,
        'scenic_spatial_uncertainty': neighborhood_stats,
        'scenic_profile_drying_transition_ft_msl': transition,
        'scenic_terrain_ft_msl': round(terrain),
        'scenic_terrain_uses_station_proxy': terrain_is_station_proxy,
        'scenic_indicators': {
            'low_cloud_cover_pct': low, 'mid_cloud_cover_pct': mid, 'high_cloud_cover_pct': high,
            'forecast_cloud_base_ft_msl': round(base) if base is not None else None,
            'forecast_overall_cloud_top_ft_msl': round(overall_top) if overall_top is not None else None,
            'max_desired_low_deck_top_ft_msl': MAX_DESIRED_DECK_TOP_FT_MSL,
            'green_rh_at_summit_pct': green['forecast_rh_at_summit_pct'],
            'green_rh_at_7400ft_pct': green['forecast_rh_at_desired_top_pct'],
            'green_rh_above_summit_pct': green['forecast_rh_above_summit_pct'],
        },
        'scenic_site_details': sites,
        'scenic_disclaimer': ('Hand-designed 0-100 ranking, NOT an event probability. '
                              'RH-profile drying is NOT a measured or resolved low-cloud top. '
                              'HRRR general cloud top can refer to higher clouds. '
                              'Summit cloudiness is inferred from a single KBDU-area grid cell; '
                              'terrain and geographic differences are not directly resolved. '
                              'The continuous middle/high-cloud penalty is a subjective '
                              'v2 hypothesis, not an observed clear-sky probability.'),
    }
