"""Spatial HRRR transect diagnostics from indexed GRIB subsets.

The same gridded numerical fields are queried at several locations. This is
not a cloud-top retrieval, a summit observation, or independent 3-km-resolved
measurements at every marker. Terrain is HRRR grid-cell terrain, not peak height.
"""
import math
from datetime import timedelta

# The known coordinates are targets for nearest-HRRR-grid sampling. Several
# markers may map to the SAME HRRR grid cell (~3 km nominal grid spacing).
# Summit elevations for labels come from the site configuration, not HRRR.
TRANSECT_POINTS = (
    ('kbdu', 'Boulder airport', 40.0394, -105.2250, None),
    ('east_boulder', 'East Boulder', 40.0260, -105.2470, None),
    ('downtown', 'Central Boulder', 40.0150, -105.2705, None),
    ('chautauqua', 'Chautauqua', 39.9978, -105.2814, None),
    ('flatiron', 'First Flatiron', 39.990472, -105.294667, 7258),
    ('green', 'Green Mountain', 39.9794304, -105.3016578, 8133),
)
TRANSECT_VERSION = 'boulder-foothills-grid-transect-v1'
FT_M = 3.280839895
# The additional GRIB fields are already inside the existing 13 surface and
# 25 pressure records; no full CONUS files or additional products required.
SURFACE_KEYS = {
    ('HGT', 'surface'): 'terrain_m',
    ('RH', '2 m above ground'): 'surface_rh_pct',
    ('LCDC', 'low cloud layer'): 'low_cloud_pct',
    ('MCDC', 'middle cloud layer'): 'mid_cloud_pct',
    ('HCDC', 'high cloud layer'): 'high_cloud_pct',
}


def finite(value):
    try:
        number = float(value)
        return number if math.isfinite(number) and abs(number) < 1e15 else None
    except (ValueError, TypeError):
        return None


def relative_humidity_at(layers, height_ft):
    """Linear height interpolation only INSIDE the sampled terrain/pressure range."""
    valid = sorted((z, rh) for z, rh in layers if z is not None and rh is not None)
    if len(valid) < 2 or height_ft < valid[0][0] or height_ft > valid[-1][0]:
        return None
    for (z0, r0), (z1, r1) in zip(valid, valid[1:]):
        if z0 <= height_ft <= z1 and z1 > z0:
            return round(max(0., min(100., r0 + (r1-r0)*(height_ft-z0)/(z1-z0))), 1)
    return None


def assemble(surface, pressure):
    """Build JSON-safe point diagnostics without touching the ML feature schema."""
    s_points = surface.get('_transect_fields')
    p_points = pressure.get('_transect_fields')
    if not isinstance(s_points, dict) or not isinstance(p_points, dict):
        return None
    points = []
    for key, name, lat, lon, summit_ft in TRANSECT_POINTS:
        s = s_points.get(key, {})
        p = p_points.get(key, {})
        terrain_m = finite(s.get(('HGT', 'surface')))
        surf_rh = finite(s.get(('RH', '2 m above ground')))
        layers = []
        if terrain_m is not None and surf_rh is not None:
            layers.append((round((terrain_m + 2)*FT_M, 1), surf_rh))
        for level in (800, 750, 700, 650, 600):
            height_m = finite(p.get(('HGT', f'{level} mb')))
            rh = finite(p.get(('RH', f'{level} mb')))
            if height_m is not None and rh is not None and terrain_m is not None and height_m > terrain_m + 10:
                layers.append((round(height_m*FT_M, 1), round(rh, 1)))
        # A 2-m RH reading can be missing or the first pressure level can be
        # below the coarse terrain. Do not fill the gaps by extrapolation.
        layers = sorted({z: rh for z, rh in layers}.items())
        grid = s.get('_grid') or p.get('_grid') or {}
        grid_lat = finite(grid.get('latitude'))
        grid_lon = finite(grid.get('longitude'))
        if grid_lon is not None and grid_lon > 180:
            grid_lon -= 360
        grid_id = (f'{grid_lat:.4f},{grid_lon:.4f}' if grid_lat is not None and grid_lon is not None else None)
        point = {
            'id': key, 'name': name, 'latitude': lat, 'longitude': lon,
            'summit_elevation_ft_msl': summit_ft,
            'grid_latitude': grid_lat, 'grid_longitude': grid_lon,
            'grid_distance_km': finite(grid.get('distance_km')),
            'grid_id': grid_id,
            'grid_terrain_ft_msl': round(terrain_m*FT_M) if terrain_m is not None else None,
            'surface_rh_pct': round(surf_rh, 1) if surf_rh is not None else None,
            'low_cloud_pct': finite(s.get(('LCDC', 'low cloud layer'))),
            'mid_cloud_pct': finite(s.get(('MCDC', 'middle cloud layer'))),
            'high_cloud_pct': finite(s.get(('HCDC', 'high cloud layer'))),
            'rh_at_6500ft_pct': relative_humidity_at(layers, 6500),
            'rh_at_7258ft_pct': relative_humidity_at(layers, 7258),
            'rh_at_8133ft_pct': relative_humidity_at(layers, 8133),
            'rh_at_summit_pct': relative_humidity_at(layers, summit_ft) if summit_ft else None,
            'humidity_by_height': [
                {'height_ft_msl': z, 'rh_pct': round(rh, 1)} for z, rh in layers
            ],
        }
        points.append(point)
    unique = {x['grid_id'] for x in points if x['grid_id'] is not None}
    # Older ecCodes shims may not report the grid center: do not claim six
    # independent HRRR cells when the grid coordinates are unavailable.
    return {
        'version': TRANSECT_VERSION, 'model': 'NOAA HRRR CONUS ~3 km',
        'sample_method': 'nearest grid point per named target; height interpolation between sampled RH levels',
        'points': points, 'unique_model_cells': len(unique) if unique else None,
        'note': ('Model forecasts, not camera observations. Cloud fractions describe broad low/mid/high layers, '
                 'not the exact fog top. Humidity by height uses sparse pressure levels and model terrain. '
                 'Two locations may share a grid cell; summit elevations are user-specified labels.'),
    }
