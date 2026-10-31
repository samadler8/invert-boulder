"""One transparent, uncalibrated Boulder basin-to-Green-Mountain opportunity index.

This answers whether numerical forecasts support a *shallow valley low deck with
clearer air aloft*. It does not prove a thermodynamic inversion, cloud top,
scenic visibility, or event probability. Missing essential evidence stays missing.
"""
from .scenic import finite

VERSION = 'boulder-corridor-opportunity-v1'


def evaluate_opportunity(row, evaluated):
    base = finite(evaluated.get('scenic_heuristic_score'))
    cloud = finite((row.get('observables') or {}).get('lowClouds'))
    track = (row.get('observables') or {}).get('foothills_transect')
    points = (track or {}).get('points', []) if isinstance(track, dict) else []
    by_id = {p.get('id'): p for p in points if isinstance(p, dict)}
    # Spatial samples are a modifier, not a second set of airport observations.
    boulder = [by_id.get(k) for k in ('kbdu', 'east_boulder', 'downtown')]
    # Require distinct forecast grid cells rather than counting nearby place
    # labels as independent evidence. If grid IDs are unavailable, do not
    # adjust the score using a pseudo-replicated spatial mean.
    valley_by_grid = {}
    for point in boulder:
        if not isinstance(point, dict):
            continue
        cell = point.get('grid_id')
        value = finite(point.get('low_cloud_pct'))
        if cell and value is not None and cell not in valley_by_grid:
            valley_by_grid[cell] = value
    present = list(valley_by_grid.values())
    mountain = by_id.get('green') or {}
    mountain_rh = finite(mountain.get('rh_at_8133ft_pct'))
    unique_cells = (track or {}).get('unique_model_cells') if isinstance(track, dict) else None
    spatial = None
    if len(present) >= 2 and mountain_rh is not None:
        valley = max(0., min(1., (sum(present)/len(present) - 35) / 60))
        aloft = max(0., min(1., (90 - mountain_rh) / 35))
        spatial = 0.65 * valley + 0.35 * aloft
    # Preserve the legacy physics score exactly when spatial data are absent,
    # rather than manufacture favorable or unfavorable mountain observations.
    if base is None:
        score = None
    elif spatial is None:
        score = round(base)
    else:
        score = round(base * (0.80 + 0.20 * spatial))
    if score is None:
        label = 'Insufficient forecast data'
    elif score >= 70:
        label = 'Promising inversion opportunity'
    elif score >= 40:
        label = 'Mixed inversion signals'
    else:
        label = 'Unfavorable inversion setup'
    indicators = evaluated.get('scenic_indicators') or {}
    issues = []
    if not points:
        issues.append('No foothills transect saved for this forecast; score uses airport-column profile only.')
    elif len(present) < 2:
        issues.append('Fewer than two distinct Boulder-area HRRR cells have usable low-cloud data; no spatial adjustment applied.')
    elif unique_cells is not None and unique_cells < 4:
        issues.append('Several locations share the same ~3 km HRRR grid cells.')
    if indicators.get('green_rh_at_summit_pct') is None:
        issues.append('No reliable forecast relative humidity at Green Mountain elevation.')
    if (indicators.get('mid_cloud_cover_pct') or 0) >= 75 or (indicators.get('high_cloud_cover_pct') or 0) >= 75:
        issues.append('Higher cloud layers may block views or sunrise light.')
    return {
        'opportunity_score': score,
        'opportunity_version': VERSION,
        'opportunity_label': label,
        'opportunity_note': ('Single 0–100 forecast setup INDEX for low cloud over Boulder and relatively clear air up to '
                             'Green Mountain (8,133 ft), not a calibrated probability, observed inversion, '
                             'verified summit visibility, or resolved cloud-top height.'),
        'opportunity_evidence': {
            'boulder_low_cloud_pct': cloud,
            'middle_cloud_pct': indicators.get('mid_cloud_cover_pct'),
            'high_cloud_pct': indicators.get('high_cloud_cover_pct'),
            'drying_transition_ft_msl': evaluated.get('scenic_profile_drying_transition_ft_msl'),
            'summit_rh_pct': indicators.get('green_rh_at_summit_pct'),
            'spatial_modifier': round(spatial, 3) if spatial is not None else None,
            'unique_hrrr_cells': unique_cells,
            'data_issues': issues,
        },
    }
