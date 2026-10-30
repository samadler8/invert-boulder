"""New, offline-only validation of smoothing, spatial uncertainty and T-0/METAR."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json

import pytest
from fastapi.testclient import TestClient

from inversion import server
from inversion.history import (backfill_event, choose_hrrr_run, connect, history_view,
                               observed_at_event, save_prediction, utc_str)
from inversion.heuristic import evaluate
from inversion.hrrr import build_row
from scripts.refresh_observations import refresh_observations
from tests.test_pipeline import hrrr_scalars


def sample_row(init, lead, *, mid=10., high=0., spatial=None):
    surface, pressure = hrrr_scalars(True)
    surface[('LCDC', 'low cloud layer')] = 100.
    surface[('MCDC', 'middle cloud layer')] = mid
    surface[('HCDC', 'high cloud layer')] = high
    surface[('HGT', 'cloud base')] = 1700.
    if spatial is not None:
        surface['_spatial_cloud_samples'] = spatial
    result = build_row(init, lead, surface, pressure)
    result['profile'][1] = [98.] * 3 + [48.] * 22
    return result


def test_smooth_sky_penalty_respects_middle_vs_high_clouds():
    run = datetime(2026, 10, 29, tzinfo=timezone.utc)
    results = {name: evaluate(sample_row(run, 24, mid=mid, high=high))
               for name, (mid, high) in {
                   'clear': (0, 0), 'high_overcast': (0, 100),
                   'middle_overcast': (100, 0), 'mixed': (25, 5),
               }.items()}
    assert results['clear']['scenic_heuristic_score'] > results['mixed']['scenic_heuristic_score']
    assert results['mixed']['scenic_heuristic_score'] > results['high_overcast']['scenic_heuristic_score']
    assert results['high_overcast']['scenic_heuristic_score'] > results['middle_overcast']['scenic_heuristic_score'] > 0
    assert all(r['heuristic_score'] == results['clear']['heuristic_score'] for r in results.values())
    assert all(r['scenic_version'].endswith('v3-precise-elevations') for r in results.values())


def test_spatial_samples_are_optional_and_do_not_invent_certainty():
    run = datetime(2026, 10, 29, tzinfo=timezone.utc)
    old = evaluate(sample_row(run, 24))
    assert old['scenic_spatial_uncertainty']['classification'] == 'unavailable'
    mixed = [{'label': name, 'low_cloud_pct': 100., 'mid_cloud_pct': mid,
              'high_cloud_pct': 10.}
             for name, mid in [('north', 5), ('south', 88), ('east', 19), ('west', 72)]]
    new = evaluate(sample_row(run, 24, spatial=mixed))
    assert new['scenic_spatial_uncertainty']['available'] is True
    assert new['scenic_spatial_uncertainty']['count'] == 5
    assert new['scenic_spatial_uncertainty']['classification'] == 'high'
    assert new['scenic_spatial_uncertainty']['cloud_spread_pct']['mid_cloud_pct'] >= 70
    assert new['scenic_heuristic_score'] == old['scenic_heuristic_score']


def test_zero_hour_vintage_is_forecast_not_metar(tmp_path):
    target = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=3)
    db = tmp_path / 'forecast_history.sqlite3'
    calls = []
    def fetch(init, lead, scratch):
        calls.append((init, lead))
        return sample_row(init, lead)
    backfill_event(target, offsets=(24, 18, 12, 6, 0), db_path=db, fetcher=fetch)
    view = history_view(db, now=target+timedelta(hours=3), target=target)
    assert [x['hours_before_event'] for x in view['comparisons']] == [24, 18, 12, 6, 0]
    zero = view['comparisons'][-1]
    assert zero['forecast']['origin'] == 'reconstructed'
    assert zero['forecast']['lead_hours'] >= 2
    assert datetime.fromisoformat(zero['forecast']['run_utc'].replace('Z','+00:00')) <= target - timedelta(hours=2)
    assert view['observation'] is None
    assert len(calls) == 5


def test_metar_independent_csv_cache_and_merge(tmp_path):
    target = datetime(2026, 10, 30, 14, tzinfo=timezone.utc)
    path = tmp_path / 'observed_recent_bdu.csv'
    def fetch(start, end):
        return [{'timestamp': utc_str(target), 'station': 'BDU', 'observed_fog':1,
                 'observed_low_ceiling':1, 'observed_cloud_base_ft_msl':5560,
                 'visibility_miles':0.3, 'source':'IEM METAR (independent station observation)'}]
    r1 = refresh_observations(target.date(), target.date(), output=path, fetcher=fetch)
    r2 = refresh_observations(target.date(), target.date(), output=path, fetcher=fetch)
    assert r1['new_reports'] == 1
    assert r2['total_cached_hours'] == 1
    db = tmp_path / 'forecast_history.sqlite3'
    obs = observed_at_event(db, target)
    assert obs['observed_low_ceiling'] == 1
    assert obs['observed_fog'] == 1
    assert obs['visibility_miles'] == pytest.approx(.3)
    assert obs['observed_cloud_base_ft_msl'] == 5560
    assert observed_at_event(db, target-timedelta(hours=1)) is None


def test_observation_refresh_endpoint_bounded_and_opt_in(tmp_path, monkeypatch):
    monkeypatch.setattr(server, 'DATA_DIR', tmp_path)
    target = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=5)
    calls = []
    def mock_refresher(start, end, *, output):
        calls.append((start, end))
        return {'new_reports': 1, 'total_cached_hours': 1}
    from scripts import refresh_observations as mod
    monkeypatch.setattr(mod, 'refresh_observations', mock_refresher)
    with TestClient(server.app) as client:
        assert client.get('/api/history').status_code == 200
        assert calls == []  # GET has no weather network side effects
        response = client.post('/api/history/observation/refresh', json={'event_utc': utc_str(target)})
        assert response.status_code == 202, response.text
        status = client.get('/api/history/reconstruct/status', params={'job_id':response.json()['id']}).json()
        assert status['state'] == 'complete'
        assert status['progress'][0]['status'] == 'saved'
        assert calls == [(target.date(), target.date())]
        assert client.post('/api/history/observation/refresh',json={'event_utc':'2025-01-01T00:00:00Z'}).status_code==400


def test_saved_previous_version_not_recomputed(tmp_path):
    target = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)-timedelta(hours=5)
    db = tmp_path / 'forecast_history.sqlite3'
    row = sample_row(target - timedelta(hours=14), 14, high=100.)
    save_prediction(row, db_path=db, origin='reconstructed')
    with connect(db) as sql:
        r = sql.execute('SELECT id, prediction_json FROM predictions').fetchone()
        previous = json.loads(r['prediction_json'])
        previous['scenic_version'] = 'hrrr-scenic-suitability-v1'
        previous['scenic_heuristic_score'] = 0
        previous['heuristic_version'] = 'hrrr-setup-index-v2-scenic'
        sql.execute('UPDATE predictions SET heuristic_version=?, prediction_json=? WHERE id=?',
                    (previous['heuristic_version'], json.dumps(previous), r['id']))
    def fake(init, lead, scratch):
        return sample_row(init, lead, high=100.)
    backfill_event(target, offsets=(6,), db_path=db, fetcher=fake)
    with connect(db) as sql:
        versions = [(r['heuristic_version'],json.loads(r['prediction_json'])['scenic_heuristic_score'])
                    for r in sql.execute('SELECT heuristic_version,prediction_json FROM predictions ORDER BY id')]
    assert versions[0] == ('hrrr-setup-index-v2-scenic', 0)
    assert versions[1][0].endswith('v3-smooth-sky')
    assert versions[1][1] > 0
