"""Verify neighbor retrieval and new-row spatial metadata without NOAA access."""
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
import sys

from inversion.hrrr import decode_nearest, build_row, SPATIAL_CLOUD_POINTS
from inversion.heuristic import evaluate
from tests.test_pipeline import hrrr_scalars


def test_eccodes_nearest_samples_same_messages_without_grid_array(tmp_path, monkeypatch):
    # A deliberately minimal replacement for the ecCodes GRIB reader.
    fake = ModuleType('eccodes')
    released = []
    def new_from(stream):
        content = stream.read(1)
        return content[0] if content else None
    def find_nearest(gid, lat, lon, *, npoints=1):
        assert npoints == 1
        return [SimpleNamespace(value=float(gid) + (lat - 40) * 20)]
    fake.codes_grib_new_from_file = new_from
    fake.codes_grib_find_nearest = find_nearest
    fake.codes_release = lambda gid: released.append(gid)
    monkeypatch.setitem(sys.modules, 'eccodes', fake)
    path = tmp_path / 'fake.grib'
    path.write_bytes(bytes([10, 20, 30]))
    near = decode_nearest(path, lat=40., lon=-105., neighbors=SPATIAL_CLOUD_POINTS)
    assert len(near) == 3
    assert all(len(values) == 4 for _, values in near)
    assert near[0][0] == 10.
    assert near[0][1][0] != near[0][1][1]
    assert len(released) == 3  # release all messages, no full-grid extraction
    original = decode_nearest(path, lat=40., lon=-105.)
    assert original == [10., 20., 30.]


def test_build_row_retains_spatial_points_separate_from_ml_features():
    s, p = hrrr_scalars(True)
    s['_spatial_cloud_samples'] = [
        {'label': 'north', 'latitude': 40.1, 'longitude': -105.2,
         'low_cloud_pct': 90., 'mid_cloud_pct': 80., 'high_cloud_pct': 2.},
        {'label': 'south', 'latitude': 39.9, 'longitude': -105.2,
         'low_cloud_pct': 95., 'mid_cloud_pct': 12., 'high_cloud_pct': 5.},
        {'label': 'east', 'latitude': 40., 'longitude': -105.15,
         'low_cloud_pct': 95., 'mid_cloud_pct': 15., 'high_cloud_pct': 8.},
        {'label': 'west', 'latitude': 40., 'longitude': -105.3,
         'low_cloud_pct': 100., 'mid_cloud_pct': 21., 'high_cloud_pct': 1.},
    ]
    r = build_row(datetime(2026, 10, 29, tzinfo=timezone.utc), 12, s, p)
    assert len(r['features']) == 23
    assert len(r['profile']) == 4
    assert len(r['observables']['spatial_cloud_samples']) == 4
    assert evaluate(r)['scenic_spatial_uncertainty']['classification'] == 'high'
