"""Scenic forecast is distinct from low cloud / inversion strength."""
from datetime import datetime, timezone
import json

from inversion.hrrr import build_row
from inversion.heuristic import evaluate
from inversion.scenic import VERSION
from inversion.history import save_prediction, backfill_event, connect
from tests.test_pipeline import hrrr_scalars


def base_row():
    s, p = hrrr_scalars(True)
    s[('LCDC', 'low cloud layer')] = 100.
    s[('MCDC', 'middle cloud layer')] = 0.
    s[('HCDC', 'high cloud layer')] = 0.
    s[('HGT', 'cloud base')] = 1700.  # ~5577 ft near Boulder
    s[('HGT', 'cloud top')] = 2200.
    row = build_row(datetime(2026, 10, 29, tzinfo=timezone.utc), 36, s, p)
    # Artificial shallow low cloud with a rapid transition to dry air aloft;
    # this fixture is NOT a measured Colorado forecast.
    row['profile'][1] = [98.] * 3 + [48.] * 22
    return row


def test_shallow_deck_clear_upper_sky_beats_thick_high_clouds():
    shallow = base_row()
    clear = evaluate(shallow)
    assert clear['scenic_version'] == VERSION
    assert clear['scenic_heuristic_score'] >= 50
    assert clear['scenic_flatiron_score'] >= 40
    assert clear['heuristic_score'] > 65
    assert clear['scenic_profile_drying_transition_ft_msl'] is not None
    high = base_row()
    high['features'][5] = 100.  # HRRR high-cloud coverage; low setup unchanged
    cloudy = evaluate(high)
    assert cloudy['heuristic_score'] == clear['heuristic_score']
    assert 0 < cloudy['scenic_heuristic_score'] < clear['scenic_heuristic_score']
    assert 0 < cloudy['scenic_flatiron_score'] < clear['scenic_flatiron_score']
    assert 0 < cloudy['scenic_upper_clear_factor'] < 30


def test_deep_moist_cloud_to_summit_is_not_scenic():
    shallow = base_row()
    dry = evaluate(shallow)
    thick = base_row()
    thick['profile'][1] = [98.] * 25
    moist = evaluate(thick)
    assert moist['scenic_heuristic_score'] < dry['scenic_heuristic_score']
    assert moist['scenic_profile_drying_transition_ft_msl'] is None
    assert moist['scenic_heuristic_score'] <= 3


def test_base_far_above_boulder_blocks_low_deck_scenic_target():
    row = base_row()
    row['observables']['forecast_cloud_base_ft_msl'] = 7850
    assert evaluate(row)['scenic_heuristic_score'] == 0


def test_whole_column_cloud_top_does_not_masquerade_as_low_deck_top():
    row = base_row()
    row['observables']['forecast_cloud_top_ft_msl'] = 37960
    result = evaluate(row)
    assert result['scenic_heuristic_score'] >= 50
    assert result['scenic_indicators']['forecast_overall_cloud_top_ft_msl'] == 37960
    assert 'NOT' in result['scenic_disclaimer']


def test_missing_clouds_or_profile_yields_no_scenic_score():
    row = base_row()
    row['features'][5] = float('nan')
    assert evaluate(row)['scenic_heuristic_score'] is None
    row = base_row()
    row['profile'] = []
    assert evaluate(row)['scenic_heuristic_score'] is None


def test_existing_snapshots_not_overwritten_by_new_scenic_version(tmp_path):
    row = base_row()
    db = tmp_path / 'history.sqlite3'
    assert save_prediction(row, db_path=db)
    with connect(db) as sql:
        saved = json.loads(sql.execute('SELECT prediction_json FROM predictions').fetchone()[0])
    assert saved['scenic_heuristic_score'] >= 50
    assert saved['heuristic_version'].endswith('v3-smooth-sky')


def test_historical_old_heuristic_version_kept_and_new_reconstructed(tmp_path):
    from datetime import timedelta
    from inversion.history import backfill_event, history_view
    target = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=3)
    row = base_row()
    row['run_utc'] = (target - timedelta(hours=13)).isoformat().replace('+00:00', 'Z')
    row['timestamp'] = target.isoformat().replace('+00:00', 'Z')
    row['lead_hours'] = 13
    db = tmp_path / 'history.sqlite3'
    save_prediction(row, db_path=db, origin='reconstructed')
    with connect(db) as sql:
        item = sql.execute('SELECT prediction_json FROM predictions').fetchone()
        old = json.loads(item['prediction_json'])
        old.pop('scenic_heuristic_score', None)
        old['heuristic_version'] = 'hrrr-setup-index-v1'
        sql.execute('UPDATE predictions SET heuristic_version=?, prediction_json=?',
                    ('hrrr-setup-index-v1', json.dumps(old)))
    def fetch(init, lead, scratch):
        result = base_row()
        result['run_utc'] = init.isoformat().replace('+00:00', 'Z')
        result['timestamp'] = target.isoformat().replace('+00:00', 'Z')
        result['lead_hours'] = lead
        return result
    # A new reconstruction with the revised algorithm is explicitly versioned,
    # never quietly added to an old saved forecast.
    backfill_event(target, offsets=(6,), db_path=db, fetcher=fetch)
    with connect(db) as sql:
        snapshots = sql.execute('SELECT heuristic_version FROM predictions ORDER BY id').fetchall()
    assert len(snapshots) == 2
    assert snapshots[0]['heuristic_version'].endswith('v1')
    assert snapshots[1]['heuristic_version'].endswith('v3-smooth-sky')
    view = history_view(db, now=target + timedelta(hours=3), target=target, offsets=(6,))
    assert view['comparisons'][0]['forecast']['scenic_heuristic_score'] is not None


def test_api_makes_scenic_primary_but_retains_old_score(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from inversion import server
    from inversion.hrrr import write_jsonl
    from datetime import timedelta
    row = base_row()
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    row['run_utc'] = now.isoformat().replace('+00:00', 'Z')
    row['timestamp'] = (now + timedelta(hours=24)).isoformat().replace('+00:00', 'Z')
    row['lead_hours'] = 24
    row['features'][5] = 100. # High cloud overcast; still a low-cloud event.
    write_jsonl(tmp_path / 'hrrr_live.jsonl', [row], mode='w')
    monkeypatch.setattr(server, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(server, 'MODEL_DIR', tmp_path / 'no_models')
    data = TestClient(server.app).get('/api/forecast').json()
    assert data['scenic']['available'] is True
    assert 0 < data['hours'][0]['scenic_heuristic_score'] < 35
    assert data['hours'][0]['heuristic_score'] > 65
    assert 0 < data['hours'][0]['scenic_flatiron_score'] < 35
